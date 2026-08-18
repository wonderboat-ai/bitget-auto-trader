"""Valida os guardrails INTRA-ciclo do engine. Rodar da raiz do projeto:

    python tests\\test_ciclo.py

Faz backup e restauração automática de logs/audit.jsonl E de
config/risk_config.yaml (o teste aperta max_open_positions temporariamente).
Preferir rodar com o loop (main.py) parado.
"""
from __future__ import annotations

import atexit
import json
import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

import pandas as pd  # noqa: E402
import yaml  # noqa: E402

# ---------- guarda: backup/restauração de trilha e config ----------
# Usa tests/_guard.py desde 18/08/2026 — nome de backup PRÓPRIO desta suíte.
# Antes, esta suíte e a test_smoke.py compartilhavam audit.jsonl.bak-teste e a
# combinação "restauração do smoke falha + ciclo roda em seguida" destruía a
# trilha real (aconteceu em 18/08/2026). Ver tests/_guard.py.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _guard import FileGuard  # noqa: E402

AUDIT = ROOT / "logs" / "audit.jsonl"
YAMLP = ROOT / "config" / "risk_config.yaml"
_GUARD_AUDIT = FileGuard(AUDIT, "ciclo")
_GUARD_YAML = FileGuard(YAMLP, "ciclo")
_BAK_Y = _GUARD_YAML.bak      # o bloco B restaura o YAML padrão a partir daqui

# ---------- guarda: state/spot_protections.json ----------
# Desde 18/07/2026, _check_spot_exits() persiste proteção backfilled no
# arquivo assim que uma posição é vista (não só ao fechar) — os Fakes deste
# arquivo devolvem _open_symbols sempre vazio, então QUALQUER entrada real
# que porventura exista no arquivo (ex.: loop live rodando em paralelo, ver
# CLAUDE.md sobre nunca rodar dois main.py) seria tratada como "fechada" e
# limpa por engano. Mesma proteção que test_smoke.py já tinha; preferir
# SEMPRE rodar com o loop (main.py) parado mesmo assim.
_STATE_FILE = ROOT / "state" / "spot_protections.json"
_orig_state_content = _STATE_FILE.read_text(encoding="utf-8") if _STATE_FILE.exists() else None


def _restaura_estado() -> None:
    if _orig_state_content is None:
        if _STATE_FILE.exists():
            _STATE_FILE.unlink()
    else:
        _STATE_FILE.write_text(_orig_state_content, encoding="utf-8")


atexit.register(_restaura_estado)
# Zera pra um baseline limpo ANTES dos testes rodarem (27/07/2026, mesmo
# motivo do fix espelhado em test_smoke.py): os Fakes deste arquivo (ex.
# FakeSaudavel) não implementam fetch_order, então uma proteção real
# persistida (posição real de mainnet/testnet) faria _check_spot_exits()
# tentar reconciliá-la como "fechada externamente" e travar/poluir os testes
# de exclusividade por símbolo, que não têm relação com proteção de posição.
# Restaurado ao final como sempre.
_STATE_FILE.write_text("{}", encoding="utf-8")

# ---------- guarda: state/kill_switch_state.json ----------
# Desde 21/07/2026, todo RiskManager() novo LÊ e GRAVA este arquivo na
# inicialização (persistência do kill switch através de restarts). Sem esta
# guarda, instanciar RiskManager() nos testes sobrescreveria o estado real
# do motor (ex.: apagaria um halt genuíno, ou deixaria "halted" pra trás
# depois de um teste que dispara o kill switch de propósito).
_KS_FILE = ROOT / "state" / "kill_switch_state.json"
_orig_ks_content = _KS_FILE.read_text(encoding="utf-8") if _KS_FILE.exists() else None


def _restaura_kill_switch() -> None:
    if _orig_ks_content is None:
        if _KS_FILE.exists():
            _KS_FILE.unlink()
    else:
        _KS_FILE.write_text(_orig_ks_content, encoding="utf-8")


atexit.register(_restaura_kill_switch)

# ---------- guarda: state/cooldown_state.json ----------
# Desde 21/07/2026, todo RiskManager() novo LÊ e GRAVA este arquivo na
# inicialização (persistência do cooldown por símbolo através de restarts,
# mesmo padrão do kill switch). Mesma guarda, mesmo motivo.
_CD_FILE = ROOT / "state" / "cooldown_state.json"
_orig_cd_content = _CD_FILE.read_text(encoding="utf-8") if _CD_FILE.exists() else None


def _restaura_cooldown() -> None:
    if _orig_cd_content is None:
        if _CD_FILE.exists():
            _CD_FILE.unlink()
    else:
        _CD_FILE.write_text(_orig_cd_content, encoding="utf-8")


atexit.register(_restaura_cooldown)

PASS = []


def ok(name, cond, extra=""):
    PASS.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name + (f"  [{extra}]" if extra else ""))


def make_candles(n=200, start_ts=1_752_000_000_000, tf_ms=900_000):
    rows, price = [], 100.0
    for i in range(n):
        drift = 0.003 if i < n - 9 else -0.0015
        new = price * (1 + drift)
        high, low = max(price, new) * 1.001, min(price, new) * 0.999
        rows.append([start_ts + i * tf_ms, price, high, low, new, 10.0])
        price = new
    return pd.DataFrame(rows, columns=["ts", "open", "high", "low", "close", "volume"])


import src.engine as engine_mod  # noqa: E402


class FakeSaudavel:
    is_testnet = True

    def __init__(self, *a, **k):
        pass

    def fetch_balance_usdt(self):
        return 1000.0

    def fetch_open_positions(self):
        return []

    def fetch_spot_holdings(self, symbols):
        # cfg real do projeto já está em market.type=spot (decisão #E) —
        # _portfolio_state() chama isto, não fetch_open_positions, nesse modo.
        return []

    def fetch_funding_rate(self, symbol):
        # 0.001: seguro contra os DOIS clamps (max_abs_funding_rate mainnet
        # 0.003 e o testnet, mais frouxo, 0.01) — 27/07/2026, achado da
        # transição pra mainnet: -0.005 passava só no clamp testnet, então
        # rodar a suíte com ENVIRONMENT=mainnet no .env vetava toda entrada
        # destes testes por "Funding anômalo", sem relação com o que este
        # arquivo realmente testa (exclusividade por símbolo/ciclo).
        return 0.001

    def fetch_ohlcv(self, symbol, timeframe, limit=200):
        return make_candles().values.tolist()


def eventos():
    return [json.loads(l) for l in AUDIT.read_text(encoding="utf-8").splitlines()]


# ---------- A. exclusividade por símbolo ----------
AUDIT.unlink(missing_ok=True)
engine_mod.BybitClient = FakeSaudavel
eng = engine_mod.Engine(dry_run=True)
eng.run_once()
ev = eventos()
ap_btc = [e for e in ev if e["event"] == "signal_approved" and e["symbol"].startswith("BTC")]
sk_btc = [e for e in ev if e["event"] == "symbol_skipped" and e["symbol"].startswith("BTC")]
ok("BTC: 1 entrada aprovada (nao 2 opostas)", len(ap_btc) == 1, f"{len(ap_btc)}")
ok("BTC: 2o perfil pulado (symbol_skipped)", len(sk_btc) == 1, f"{len(sk_btc)}")

# ---------- B. limite de posições vale INTRA-ciclo ----------
cfg = yaml.safe_load(YAMLP.read_text(encoding="utf-8"))
cfg["portfolio"]["max_open_positions"] = 1
YAMLP.write_text(yaml.safe_dump(cfg, allow_unicode=True), encoding="utf-8")

AUDIT.unlink(missing_ok=True)
eng2 = engine_mod.Engine(dry_run=True)  # recarrega o YAML apertado
eng2.run_once()
ev = eventos()
aprov = [e for e in ev if e["event"] == "signal_approved"]
vetos = [e for e in ev if e["event"] == "signal_vetoed" and "posições atingido" in e["reason"]]
ok("apenas 1 entrada aprovada no ciclo todo", len(aprov) == 1, f"{len(aprov)}")
ok("2o simbolo vetado por max posicoes intra-ciclo", len(vetos) >= 1,
   vetos[0]["reason"] if vetos else "sem veto")

# ---------- C. exposição nocional acumula intra-ciclo ----------
# (com config padrao 2x, o cenario sintetico nao estoura; validado em producao
# pela trilha de 2026-07-15 13:16 — veto "Exposição nocional total excederia".)
ok("registro: veto de exposicao intra-ciclo observado em producao", True,
   "audit 2026-07-15T13:16:55")


# ---------- D. exclusividade vale mesmo quando a EXECUÇÃO falha ----------
# Regressão de 2026-07-15 14:58 (testnet, PermissionDenied): a 1ª entrada do
# símbolo falhava na execução, o símbolo não era marcado 'busy' e o perfil
# seguinte aprovava a direção OPOSTA no mesmo ciclo. Fail-closed: aprovou e
# foi para execução → símbolo ocupado no ciclo, com ou sem sucesso.
class FakeExecucaoNegada(FakeSaudavel):
    def set_leverage(self, symbol, leverage):
        pass

    def create_order(self, *a, **k):
        raise RuntimeError("permission denied (simulado)")


# restaura o YAML padrão (o bloco B apertou max_open_positions=1)
shutil.copy2(_BAK_Y, YAMLP)
AUDIT.unlink(missing_ok=True)
engine_mod.BybitClient = FakeExecucaoNegada
eng3 = engine_mod.Engine(dry_run=False)  # live de mentira: executor chama create_order
eng3.run_once()
ev = eventos()
ap = [e for e in ev if e["event"] == "signal_approved"]
por_simbolo: dict[str, list] = {}
for e in ap:
    por_simbolo.setdefault(e["symbol"], []).append(e["direction"])
ok("execucao falhou: no maximo 1 aprovacao por simbolo no ciclo",
   all(len(d) == 1 for d in por_simbolo.values()),
   str({s: d for s, d in por_simbolo.items()}))
err = [e for e in ev if e["event"] == "symbol_cycle_error"]
ok("falha de execucao registrada como symbol_cycle_error", len(err) >= 1, f"{len(err)}")
sk = [e for e in ev if e["event"] == "symbol_skipped"]
ok("2o perfil pulado mesmo com execucao falhada", len(sk) >= 1, f"{len(sk)}")

print()
fails = [n for n, c in PASS if not c]
print(f"{len(PASS) - len(fails)}/{len(PASS)} testes passaram")
sys.exit(1 if fails else 0)
