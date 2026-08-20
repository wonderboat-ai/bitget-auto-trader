"""Leitura de estado para supervisão (Fase 4) — READ-ONLY.

Reúne, num único lugar, as respostas às perguntas que você faz ao sistema rodando:
  - "Como está o PnL / a banca?"           -> read_account()
  - "Quais posições estão abertas?"          -> read_positions()
  - "O que o sistema decidiu ultimamente?"   -> recent_decisions()
  - "Por que entrou nesse trade?"            -> explain_symbol()
  - "O kill switch disparou? Por quê?"       -> read_halt_status()

Fontes:
  - A exchange (via BitgetClient) para saldo e posições — fonte da verdade do estado.
  - A trilha de auditoria (logs/audit.jsonl) para o PORQUÊ de cada decisão
    (aprovado/vetado/executado, racional do LLM, kill switch).

Nada aqui executa ordem, muda risco ou move dinheiro — é só observação. Ações de
controle ficam no MCP e são deliberadas.
"""
from __future__ import annotations

import json
from pathlib import Path

from src.exchange.bitget_client import BitgetClient
from src.logger import get_logger

log = get_logger("state_reader")

ROOT = Path(__file__).resolve().parent.parent.parent
AUDIT_PATH = ROOT / "logs" / "audit.jsonl"


def _read_audit() -> list[dict]:
    """Lê e parseia o audit.jsonl inteiro.

    Sem parâmetro de corte por linha de propósito (fix 21/07/2026): um corte
    por LINHA BRUTA, feito antes de filtrar por tipo de evento, empurra
    eventos raros (ex.: `trade_closed`) para fora da janela sempre que
    houver ruído repetitivo suficiente entre eles (ex.: `signal_vetoed`
    disparando a cada ciclo) — quem precisar de "últimos N" de um tipo
    específico deve filtrar primeiro e cortar depois, no chamador."""
    if not AUDIT_PATH.exists():
        return []
    with open(AUDIT_PATH, "r", encoding="utf-8") as fh:
        lines = fh.readlines()
    out = []
    for ln in lines:
        ln = ln.strip()
        if not ln:
            continue
        try:
            out.append(json.loads(ln))
        except json.JSONDecodeError:
            continue
    return out


class StateReader:
    def __init__(self, client: BitgetClient | None = None,
                 market_type: str = "perp",
                 symbols: list[str] | None = None) -> None:
        # client opcional: sem ele, ainda dá pra ler a trilha de auditoria offline.
        self.client = client
        # Em SPOT não existem "posições" na exchange — existem saldos de moeda.
        # Sem este despacho, o supervisor respondia "sem posições" com exposição
        # real na conta (revisão de 15/07) — cegueira perigosa porque parece
        # saudável. symbols = pares spot a avaliar (vem do YAML, já mapeados).
        self.market_type = market_type
        self.symbols = symbols or []

    def _positions_raw(self) -> list[dict]:
        if self.client is None:
            return []
        if self.market_type == "spot":
            return self.client.fetch_spot_holdings(self.symbols)
        return self.client.fetch_open_positions()

    # ---------------- Conta / posições (exige exchange) ----------------
    def read_account(self) -> dict:
        if self.client is None:
            return {"error": "sem conexão com a exchange"}
        equity = self.client.fetch_balance_usdt()
        positions = self._positions_raw()
        unrealized = sum(float(p.get("unrealizedPnl") or 0) for p in positions)
        return {
            "environment": "testnet" if self.client.is_testnet else "mainnet",
            "market_type": self.market_type,
            "equity_usdt": round(equity, 2),
            "open_positions": len(positions),
            "unrealized_pnl_usdt": round(unrealized, 2),
        }

    def read_positions(self) -> list[dict]:
        out = []
        for p in self._positions_raw():
            out.append({
                "symbol": p.get("symbol"),
                "side": p.get("side"),
                "contracts": float(p.get("contracts") or 0),
                "entry_price": float(p.get("entryPrice") or 0),
                "unrealized_pnl_usdt": round(float(p.get("unrealizedPnl") or 0), 2),
                "leverage": p.get("leverage"),
            })
        return out

    # ---------------- Decisões / trilha (não exige exchange) ----------------
    def recent_decisions(self, limit: int = 20) -> list[dict]:
        """Últimos eventos de decisão da trilha, do mais recente ao mais antigo.

        Lê o arquivo INTEIRO e filtra por tipo de evento ANTES de cortar pelo
        `limit` (fix 21/07/2026 — ver docstring de `realized_pnl` para o bug
        que este mesmo padrão causava)."""
        events = _read_audit()
        interesting = {"signal_approved", "signal_vetoed", "order_executed",
                       "dry_run_order", "llm_signal", "kill_switch_tripped",
                       "kill_switch_reset"}
        rows = [e for e in events if e.get("event") in interesting]
        return list(reversed(rows[-limit:]))

    def realized_pnl(self, limit: int | None = None) -> dict:
        """Agrega PnL realizado a partir de fechamentos registrados na trilha.

        Observação: no live, o executor registra execuções; o PnL realizado exato
        vem da exchange. Aqui damos uma visão pela trilha para leitura rápida.

        `limit`, quando informado, corta os N `trade_closed` MAIS RECENTES —
        nunca as N últimas LINHAS BRUTAS do arquivo. Bug real corrigido em
        21/07/2026: a versão anterior cortava `_read_audit(limit=limit)`
        (últimas N linhas cruas) ANTES de filtrar por tipo de evento. Como a
        trilha é dominada por eventos de veto repetitivos (`signal_vetoed`
        "Sinal FLAT" a cada ciclo), o corte por linha empurrava `trade_closed`
        reais para fora da janela sempre que houvesse ruído suficiente entre
        eles — visto ao vivo: com `limit=500` (default do MCP), a ferramenta
        reportava 1 trade fechado (-5,81 USDT) quando a trilha tinha 20
        (+233,95 USDT no total). Agora lê o arquivo inteiro (barato — poucos
        milissegundos mesmo com dezenas de milhares de linhas) e só corta
        DEPOIS de já ter isolado os `trade_closed`.

        `environments` no retorno (27/07/2026): contagem de `trade_closed`
        por valor de `environment` (campo novo em todo evento, ver
        `src/logger.py:audit()`). Eventos gravados ANTES desse fix não têm
        o campo — contados como `"desconhecido"`. Puramente informativo,
        não muda `closed_trades`/`realized_pnl_usdt`/`win_rate_pct` (que
        seguem somando TODOS os fechamentos, como sempre) — é só o sinal
        que faltava pra perceber, sem precisar abrir o arquivo bruto, se o
        total agregado está misturando testnet com mainnet (risco real
        numa transição de ambiente, se a trilha algum dia voltar a
        acumular os dois períodos no mesmo arquivo)."""
        events = _read_audit()
        closes = [e for e in events if e.get("event") == "trade_closed"]
        if limit is not None:
            closes = closes[-limit:]
        total = sum(float(e.get("pnl_usdt") or 0) for e in closes)
        wins = [e for e in closes if float(e.get("pnl_usdt") or 0) > 0]
        environments: dict[str, int] = {}
        for e in closes:
            key = e.get("environment") or "desconhecido"
            environments[key] = environments.get(key, 0) + 1
        return {
            "closed_trades": len(closes),
            "realized_pnl_usdt": round(total, 2),
            "win_rate_pct": round(len(wins) / len(closes) * 100, 1) if closes else 0.0,
            "environments": environments,
        }

    def explain_symbol(self, symbol: str, limit: int = 10) -> list[dict]:
        """Últimas decisões relativas a um símbolo, com o racional — o 'por quê'."""
        events = _read_audit()
        rows = [e for e in events if e.get("symbol") == symbol
                and e.get("event") in {"signal_approved", "signal_vetoed",
                                        "order_executed", "dry_run_order", "llm_signal"}]
        return list(reversed(rows[-limit:]))

    def read_halt_status(self) -> dict:
        """Se e por que o kill switch disparou.

        Fonte primária (21/07): `state/kill_switch_state.json`, persistido
        pelo próprio RiskManager — reflete o estado REAL do processo,
        inclusive através de restarts. Antes disto, este método só inferia
        da trilha (último kill_switch_tripped × kill_switch_reset), o que
        ficava desatualizado sempre que o processo reiniciava com o kill
        switch em RAM (sem persistência, um trip antigo continuava sendo
        reportado como ativo mesmo com o motor livre de novo — visto ao vivo
        em 21/07). Sem o arquivo (setup anterior a este fix, nunca rodou com
        o RiskManager novo), cai no fallback antigo baseado na trilha.
        """
        events = _read_audit()
        tripped = [e for e in events if e.get("event") == "kill_switch_tripped"]
        resets = [e for e in events if e.get("event") == "kill_switch_reset"]
        last_trip = tripped[-1] if tripped else None
        last_reset = resets[-1] if resets else None

        from src.risk import kill_switch_state
        if kill_switch_state.STATE_PATH.exists():
            persisted = kill_switch_state.load()
            return {
                "halted": persisted["halted"],
                "last_reason": persisted["reason"] or (last_trip.get("reason") if last_trip else None),
                "last_trip_ts": last_trip.get("ts") if last_trip else None,
            }

        halted = bool(last_trip) and (
            not last_reset or last_trip["ts"] > last_reset["ts"]
        )
        return {
            "halted": halted,
            "last_reason": last_trip.get("reason") if last_trip else None,
            "last_trip_ts": last_trip.get("ts") if last_trip else None,
        }

    def read_cooldown_status(self) -> dict:
        """Estado de cooldown por símbolo (25/07/2026), direto de
        state/cooldown_state.json — mesmo padrão de read_halt_status: lê o
        arquivo persistido pelo próprio RiskManager, reflete o estado REAL do
        processo através de restarts. Só leitura: nunca limpa cooldown
        expirado no arquivo (isso é trabalho do RiskManager no próximo
        ciclo) — aqui só calcula "ainda ativo?" na hora da leitura."""
        from datetime import datetime, timezone
        from src.risk import cooldown_state

        data = cooldown_state.load()
        now = datetime.now(timezone.utc)
        out: dict[str, dict] = {}
        for symbol, entry in data.items():
            until_str = entry.get("cooldown_until")
            active = False
            if until_str:
                try:
                    active = now < datetime.fromisoformat(until_str)
                except ValueError:
                    active = False
            out[symbol] = {
                "active": active,
                "cooldown_until": until_str if active else None,
                "triggers_today": entry.get("triggers_today", 0),
                "triggers_date": entry.get("triggers_date"),
            }
        return out
