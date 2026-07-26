"""Camada de RISCO — poder de veto absoluto.

Roda DEPOIS da decisão e ANTES da execução. Nenhuma ordem chega à exchange sem
passar por aqui. As regras vêm do risk_config.yaml e não são negociáveis em runtime:
o motor de decisão / LLM não pode contorná-las nem reescrevê-las.

Saída de cada avaliação:
  - RiskDecision.approved=False  -> ordem vetada, com motivo (logado).
  - RiskDecision.approved=True   -> com o position size já calculado pelo stop.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from src.logger import audit, get_logger
from src.risk import cooldown_state, kill_switch_state
from src.strategy.signal import Direction, Signal

log = get_logger("risk_manager")


@dataclass
class RiskDecision:
    approved: bool
    reason: str
    position_size: float = 0.0   # em contratos/quantidade do ativo
    leverage: int = 1
    stop_price: float = 0.0


@dataclass
class PortfolioState:
    equity_usdt: float           # patrimônio atual (saldo + PnL não realizado)
    day_start_equity: float      # patrimônio no início do dia (para drawdown diário)
    peak_equity: float           # pico histórico (para drawdown total)
    open_positions: int
    total_notional: float        # exposição nocional somada
    aggregate_risk_pct: float    # risco em aberto somado (%)


class RiskManager:
    def __init__(self, risk_cfg: dict, environment: str = "mainnet") -> None:
        self.cfg = risk_cfg
        # Default 'mainnet' = limiares estritos. Só relaxa o que tiver chave
        # *_testnet explícita no YAML E o chamador declarar environment=testnet.
        self.environment = environment
        # "perp" | "spot" — lido do YAML aqui (e não recebido do chamador) para
        # engine, backtester e testes enxergarem SEMPRE a mesma resposta.
        # Em spot as regras só APERTAM (short vetado, leverage 1, exposição 1x);
        # nada relaxa — fail-closed por construção.
        from config.settings import get_market_type
        self.market_type = get_market_type(risk_cfg)
        # Recupera o estado do kill switch persistido em disco (21/07) — sem
        # isto, um restart do processo zerava o halt em RAM sem deixar
        # rastro, o que tanto "resetava" sozinho um kill switch disparado por
        # drawdown de verdade (reset devia ser SEMPRE manual) quanto deixava
        # o supervisor via MCP reportando um trip antigo como ativo pra
        # sempre. Sem arquivo prévio, carrega False (mesmo default de antes).
        persisted = kill_switch_state.load()
        self._kill_switch = persisted["halted"]
        self._kill_reason = persisted["reason"]
        if self._kill_switch:
            log.error("Kill switch RESTAURADO do estado persistido — motor "
                      "inicia HALTED (motivo: %s). Reset continua manual.",
                      self._kill_reason)
        # Garante que o arquivo reflete o estado efetivo desde já (cobre o
        # primeiro boot com este código, quando o arquivo ainda não existe).
        kill_switch_state.save(self._kill_switch, self._kill_reason)
        # Cooldown por símbolo após stops seguidos (21/07) — mesmo raciocínio
        # de persistência do kill switch: sem isto, um restart no meio de um
        # cooldown ativo apagaria a proteção silenciosamente.
        self._cooldown = cooldown_state.load()

    # ---------------------- Kill switch ----------------------
    @property
    def halted(self) -> bool:
        return self._kill_switch

    def trip_kill_switch(self, reason: str) -> None:
        if not self._kill_switch:
            self._kill_switch = True
            self._kill_reason = reason
            log.error("KILL SWITCH DISPARADO: %s", reason)
            audit("kill_switch_tripped", reason=reason)
            kill_switch_state.save(True, reason)

    def reset_kill_switch(self) -> None:
        """Reset é MANUAL e deliberado — nunca automático."""
        log.warning("Kill switch resetado manualmente (estava: %s)", self._kill_reason)
        audit("kill_switch_reset", previous_reason=self._kill_reason)
        self._kill_switch = False
        self._kill_reason = ""
        kill_switch_state.save(False, "")

    # ---------------------- Cooldown por símbolo (21/07, 3 níveis desde 25/07) ----------------------
    def record_trade_close(self, symbol: str, reason: str) -> None:
        """Chamado pelo engine sempre que uma posição fecha (qualquer motivo).

        `reason == "stop_loss"` incrementa a sequência de stops seguidos DO
        SÍMBOLO; ao atingir o gatilho (`consecutive_stops_trigger`), ativa um
        cooldown (bloqueia entradas novas nesse símbolo) com duração por
        NÍVEL — 1º acionamento do dia usa `cooldown_minutes_first`, 2º usa
        `cooldown_minutes_escalated`, 3º em diante usa `cooldown_minutes_max`
        (decisão do Lucas, 25/07/2026: `consecutive_stops_trigger` virou 1 —
        cada stop isolado já conta, não precisa mais de 2 seguidos). Qualquer
        outro motivo de fechamento (take_profit/signal_exit/trailing_stop/
        external_close_unconfirmed) QUEBRA a sequência de `consecutive_stops`
        — com o gatilho em 1 isso não muda o resultado prático (cada stop já
        aciona sozinho), mas mantém o campo coerente caso o gatilho volte a
        subir no futuro.

        Sem a chave `cooldown` no YAML, esta função não faz nada (feature
        fica desligada por omissão — mesmo padrão de exit_on_signal/trailing).
        """
        cd_cfg = self.cfg.get("cooldown")
        if not cd_cfg:
            return
        entry = self._cooldown.get(symbol, {"consecutive_stops": 0, "cooldown_until": None,
                                             "triggers_date": None, "triggers_today": 0})
        if reason != "stop_loss":
            entry["consecutive_stops"] = 0
            self._cooldown[symbol] = entry
            cooldown_state.save(self._cooldown)
            return

        entry["consecutive_stops"] = entry.get("consecutive_stops", 0) + 1
        trigger_n = cd_cfg.get("consecutive_stops_trigger", 2)
        if entry["consecutive_stops"] >= trigger_n:
            today = datetime.now(timezone.utc).date().isoformat()
            if entry.get("triggers_date") != today:
                entry["triggers_date"] = today
                entry["triggers_today"] = 0
            entry["triggers_today"] += 1
            # 3 níveis por dia (UTC), por símbolo: 1º -> first, 2º ->
            # escalated, 3º em diante -> max (25/07/2026). Sem a chave nova
            # `cooldown_minutes_max` no YAML, cai no valor de `escalated` —
            # comportamento antigo (2 níveis) preservado por omissão.
            if entry["triggers_today"] <= 1:
                minutes = cd_cfg.get("cooldown_minutes_first", 30)
            elif entry["triggers_today"] == 2:
                minutes = cd_cfg.get("cooldown_minutes_escalated", 60)
            else:
                minutes = cd_cfg.get("cooldown_minutes_max", cd_cfg.get("cooldown_minutes_escalated", 60))
            until = datetime.now(timezone.utc) + timedelta(minutes=minutes)
            entry["cooldown_until"] = until.isoformat()
            entry["consecutive_stops"] = 0  # reinicia a contagem após acionar
            log.warning("Cooldown ativado em %s: %d stops seguidos -> pausa de "
                        "%d min (acionamento nº%d hoje)", symbol, trigger_n,
                        minutes, entry["triggers_today"])
            audit("cooldown_triggered", symbol=symbol, consecutive_stops=trigger_n,
                  cooldown_minutes=minutes, cooldown_until=entry["cooldown_until"],
                  trigger_number_today=entry["triggers_today"])
        self._cooldown[symbol] = entry
        cooldown_state.save(self._cooldown)

    def reset_cooldown(self, symbol: str) -> None:
        """Libera manualmente o cooldown ativo de um símbolo, antes do prazo
        natural (ex.: a pausa de 24h do 3º stop do dia). Reset é sempre
        deliberado — nunca automático, mesma filosofia do kill switch
        (`reset_kill_switch`). Chamado pelo engine em resposta a um pedido
        via MCP (`trader_reset_cooldown`, control.json action=reset_cooldown).

        Símbolo sem cooldown ativo: só loga um aviso, não é erro — evita que
        um pedido "atrasado" (cooldown já tinha expirado sozinho) derrube
        nada."""
        entry = self._cooldown.get(symbol)
        if not entry or not entry.get("cooldown_until"):
            log.warning("Reset de cooldown pedido para %s, mas não há cooldown ativo", symbol)
            return
        previous_until = entry["cooldown_until"]
        entry["cooldown_until"] = None
        self._cooldown[symbol] = entry
        cooldown_state.save(self._cooldown)
        log.warning("Cooldown de %s resetado manualmente (estava até %s)", symbol, previous_until)
        audit("cooldown_reset", symbol=symbol, previous_cooldown_until=previous_until)

    def _cooldown_veto_reason(self, symbol: str) -> str | None:
        """None se o símbolo está livre pra operar; motivo do veto se não."""
        entry = self._cooldown.get(symbol)
        if not entry or not entry.get("cooldown_until"):
            return None
        until = datetime.fromisoformat(entry["cooldown_until"])
        if datetime.now(timezone.utc) < until:
            return f"Cooldown ativo em {symbol} até {entry['cooldown_until']} (stops seguidos)"
        # Cooldown expirou — limpa pra não reavaliar todo ciclo.
        entry["cooldown_until"] = None
        self._cooldown[symbol] = entry
        cooldown_state.save(self._cooldown)
        return None

    # ---------------------- Checagens de portfólio ----------------------
    def check_portfolio_health(self, state: PortfolioState) -> None:
        """Avalia drawdown e dispara kill switch quando necessário. Chamar a cada ciclo."""
        dd_cfg = self.cfg["drawdown"]

        daily_dd = self._pct_drop(state.day_start_equity, state.equity_usdt)
        if daily_dd >= dd_cfg["max_daily_drawdown_pct"]:
            self.trip_kill_switch(
                f"Drawdown diário {daily_dd:.2f}% >= limite {dd_cfg['max_daily_drawdown_pct']}%"
            )

        total_dd = self._pct_drop(state.peak_equity, state.equity_usdt)
        if total_dd >= dd_cfg["max_total_drawdown_pct"]:
            self.trip_kill_switch(
                f"Drawdown total {total_dd:.2f}% >= limite {dd_cfg['max_total_drawdown_pct']}%"
            )

    # ---------------------- Avaliação de um sinal ----------------------
    def evaluate(
        self,
        signal: Signal,
        state: PortfolioState,
        funding_rate: float | None,
        data_age_sec: float,
        profile: str | None = None,
    ) -> RiskDecision:
        # 0) Kill switch trava qualquer entrada nova.
        if self._kill_switch:
            return self._veto(signal, profile, f"Kill switch ativo: {self._kill_reason}")

        # 0b) Cooldown por símbolo (21/07): stops seguidos pausam entradas
        # novas nesse símbolo — trata reentrada em rajada (dado ruim OU
        # whipsaw real), não bloqueia OUTROS símbolos nem fecha posições
        # existentes (mesma filosofia do kill switch: só trava entrada nova).
        cooldown_reason = self._cooldown_veto_reason(signal.symbol)
        if cooldown_reason:
            return self._veto(signal, profile, cooldown_reason)

        # 1) Sinal não acionável -> nada a fazer.
        if not signal.is_actionable():
            return self._veto(signal, profile, "Sinal FLAT — sem entrada")

        # 1b) Spot não tem venda a descoberto: SHORT é vetado, não adaptado.
        # A estratégia continua livre para propor; o veto deixa o racional
        # visível na trilha em vez de silenciar o sinal.
        if self.market_type == "spot" and signal.direction == Direction.SHORT:
            return self._veto(signal, profile, "Spot: short não suportado — sem entrada")

        # 1c) NaN/±inf nunca passam em NENHUMA comparação Python (nan < x,
        # nan <= x, nan >= x são sempre False) — achado CRÍTICO da revisão
        # adversarial de 22/07/2026 (Fase 3, ainda desligada, mas esta
        # camada é o veto ABSOLUTO e deve rejeitar isso INDEPENDENTE da
        # origem do sinal, não só confiar que quem gerou o Signal já filtrou
        # — defesa em profundidade, mesmo espírito de duas barreiras
        # independentes que o resto do projeto já segue). Sem isto, um
        # stop_price=NaN passava por TODOS os guards abaixo (coerência,
        # distância do stop, teto de notional, exposição) e chegava
        # aprovado com position_size=nan até o executor.
        campos_numericos = [signal.entry_price, signal.stop_price]
        if signal.take_profit is not None:
            campos_numericos.append(signal.take_profit)
        if not all(math.isfinite(v) for v in campos_numericos):
            return self._veto(signal, profile, "Campo numérico não-finito (NaN/±inf) no sinal — recusado")

        # 2) Stop obrigatório.
        if self.cfg["per_trade"]["require_stop_loss"]:
            if not signal.stop_price or signal.stop_price <= 0:
                return self._veto(signal, profile, "Stop-loss ausente — trade proibido")

        # 3) Coerência do stop com a direção.
        if signal.direction == Direction.LONG and signal.stop_price >= signal.entry_price:
            return self._veto(signal, profile, "LONG com stop acima da entrada — incoerente")
        if signal.direction == Direction.SHORT and signal.stop_price <= signal.entry_price:
            return self._veto(signal, profile, "SHORT com stop abaixo da entrada — incoerente")

        # 4) Circuit breakers de mercado.
        cb = self.cfg["circuit_breakers"]
        if data_age_sec > cb["max_data_staleness_sec"]:
            return self._veto(signal, profile, f"Feed defasado ({data_age_sec:.0f}s) — entrada suspensa")
        max_funding = cb["max_abs_funding_rate"]
        if self.environment == "testnet":
            # Na testnet o funding vive pregado no clamp da exchange (±0.005) por
            # book raso — artefato do ambiente, não anomalia de mercado. Limiar
            # próprio (se definido no YAML) para não vetar toda a Fase 1.
            max_funding = cb.get("max_abs_funding_rate_testnet", max_funding)
        if funding_rate is not None and abs(funding_rate) > max_funding:
            return self._veto(signal, profile, f"Funding anômalo ({funding_rate:.4f}) — entrada suspensa")

        # 5) Limites de portfólio.
        pf = self.cfg["portfolio"]
        if state.open_positions >= pf["max_open_positions"]:
            return self._veto(signal, profile, f"Máx. posições atingido ({state.open_positions})")

        # 6) Sizing pelo stop: risco fixo / distância até o stop.
        if state.equity_usdt <= 0:
            return self._veto(signal, profile, "Saldo/equity zerado ou negativo — sem capital para operar")

        risk_pct = self.cfg["per_trade"]["risk_pct"] / 100.0
        risk_usdt = state.equity_usdt * risk_pct
        stop_distance = abs(signal.entry_price - signal.stop_price)
        if stop_distance <= 0:
            return self._veto(signal, profile, "Distância de stop nula — sizing impossível")

        position_size = risk_usdt / stop_distance  # quantidade do ativo
        notional = position_size * signal.entry_price

        # 6b) Teto de capital por trade INDIVIDUAL (decisão do Lucas, 17/07/2026).
        # Sizing por risco fixo não tem teto próprio: stop apertado -> size grande,
        # limitado só pelo agregado de portfólio (item 7). CLAMPA, nunca veta: o
        # risco realizado fica ABAIXO do risk_pct alvo nesse caso, nunca acima —
        # a entrada acontece, só menor, deixando caixa pra outros trades/símbolos.
        capped = False
        max_notional_pct = self.cfg["per_trade"].get("max_notional_pct_equity")
        # "is not None", não truthy: 0.0 configurado explicitamente é um valor
        # válido (teto zero) e não pode ser confundido com "chave ausente" —
        # `if max_notional_pct:` tratava as duas coisas como "sem teto",
        # desligando o clamp exatamente quando o operador pediu o mais
        # restritivo (achado da revisão adversarial de 17/07).
        if max_notional_pct is not None:
            max_single_notional = state.equity_usdt * (max_notional_pct / 100.0)
            if notional > max_single_notional:
                position_size = max_single_notional / signal.entry_price
                notional = max_single_notional
                capped = True

        # 6c) Clamp não pode degenerar em aprovação de tamanho zero/negativo
        # (ex.: max_notional_pct_equity configurado como 0) — isso é um VETO
        # disfarçado de aprovação, e o executor não tem guard de size==0
        # (achado da 2ª rodada de revisão adversarial de 17/07).
        if position_size <= 0:
            return self._veto(signal, profile,
                              "Teto de capital por trade zerou o tamanho — sem entrada")

        # 7) Exposição agregada e alavancagem.
        exposure_mult = pf["max_total_exposure_mult"]
        if self.market_type == "spot":
            # Sem margem no spot: não dá para comprar mais do que o caixa.
            # O teto do YAML continua valendo se for MENOR que 1x.
            exposure_mult = min(exposure_mult, 1.0)
        max_notional = state.equity_usdt * exposure_mult
        if state.total_notional + notional > max_notional:
            return self._veto(signal, profile, "Exposição nocional total excederia o limite")

        if state.aggregate_risk_pct + self.cfg["per_trade"]["risk_pct"] > pf["max_aggregate_risk_pct"]:
            return self._veto(signal, profile, "Risco agregado em aberto excederia o limite")

        if self.market_type == "spot":
            leverage = 1  # à vista não existe alavancagem
        else:
            leverage = min(
                self.cfg["per_trade"]["max_leverage"],
                max(1, int(notional / state.equity_usdt) + 1),
            )

        audit(
            "signal_approved",
            symbol=signal.symbol,
            direction=signal.direction.value,
            size=position_size,
            notional=notional,
            risk_usdt=risk_usdt,
            leverage=leverage,
            rationale=signal.rationale,
            capped=capped,
        )
        log.info(
            "APROVADO %s %s size=%.6f notional=%.2f risco=%.2f USDT%s",
            signal.direction.value, signal.symbol, position_size, notional, risk_usdt,
            " (CLAMPADO ao teto por trade)" if capped else "",
        )
        return RiskDecision(
            approved=True,
            reason="ok",
            position_size=position_size,
            leverage=leverage,
            stop_price=signal.stop_price,
        )

    # ---------------------- Helpers ----------------------
    def _veto(self, signal: Signal, profile: str | None, reason: str) -> RiskDecision:
        log.warning("VETO %s: %s", signal.symbol, reason)
        audit("signal_vetoed", symbol=signal.symbol, profile=profile, reason=reason)
        return RiskDecision(approved=False, reason=reason)

    @staticmethod
    def _pct_drop(reference: float, current: float) -> float:
        if reference <= 0:
            return 0.0
        return max(0.0, (reference - current) / reference * 100.0)
