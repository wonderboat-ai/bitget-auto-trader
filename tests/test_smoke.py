"""Smoke tests offline — sem rede, sem exchange real. Rodar da raiz do projeto:

    python tests\\test_smoke.py

Faz backup e restauração automática de logs/audit.jsonl (o teste escreve na
trilha real e devolve o original no fim, mesmo se falhar). Preferir rodar com o
loop (main.py) parado.
"""
from __future__ import annotations

import atexit
import copy
import json
import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

import pandas as pd  # noqa: E402

# ---------- guarda: backup/restauração da trilha ----------
AUDIT = ROOT / "logs" / "audit.jsonl"
_BAK = ROOT / "logs" / "audit.jsonl.bak-teste"
if AUDIT.exists():
    shutil.copy2(AUDIT, _BAK)


def _restaura() -> None:
    if _BAK.exists():
        shutil.move(str(_BAK), str(AUDIT))


atexit.register(_restaura)

# ---------- guarda: state/spot_protections.json (seções 9-12 escrevem nele
# via Executor/engine em modo spot) — precisa capturar o conteúdo ANTES de
# qualquer teste rodar, não só antes da seção que fala dele explicitamente.
# Conteúdo em memória (não arquivo-irmão no disco): a pasta sincroniza via
# OneDrive, e um segundo arquivo indo e voltando em sequência rápida corre
# risco de race com o sync.
_STATE_FILE = ROOT / "state" / "spot_protections.json"
_orig_state_content = _STATE_FILE.read_text(encoding="utf-8") if _STATE_FILE.exists() else None


def _restaura_estado() -> None:
    if _orig_state_content is None:
        if _STATE_FILE.exists():
            _STATE_FILE.unlink()
    else:
        _STATE_FILE.write_text(_orig_state_content, encoding="utf-8")


atexit.register(_restaura_estado)
# Zera pra um baseline limpo ANTES dos testes rodarem (27/07/2026): o backup
# acima só garante restaurar o conteúdo real no final — com o motor operando
# em mainnet e proteções reais persistidas (ex.: posições reais de swing),
# qualquer Engine() instanciado por um teste sem fake que implemente
# fetch_order herdaria essas entradas e tentaria reconciliá-las como
# "fechadas externamente", contaminando testes de exclusividade por símbolo
# que nada têm a ver com proteção de posição. Restaurado ao final como sempre.
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


# ---------- 1. imports ----------
from config.settings import load_risk_config  # noqa: E402
from src.backtest.backtester import Backtester  # noqa: E402
from src.backtest.metrics import compute_metrics  # noqa: E402
from src.data.market_data import compute_indicators, snapshot_from_df  # noqa: E402
from src.execution.executor import Executor  # noqa: E402
from src.risk.risk_manager import PortfolioState, RiskManager  # noqa: E402
from src.strategy.deterministic import DeterministicStrategy  # noqa: E402
from src.strategy.signal import Direction, Signal  # noqa: E402
from src.supervision.restart_policy import RestartPolicy, backoff_seconds  # noqa: E402
from src.context.providers import (  # noqa: E402
    BybitDerivativesProvider, ContextAggregator, DossierMacroProvider, DossierOnChainProvider,
)

ok("imports", True)

cfg = load_risk_config()
state = PortfolioState(equity_usdt=1000.0, day_start_equity=1000.0, peak_equity=1000.0,
                       open_positions=0, total_notional=0.0, aggregate_risk_pct=0.0)
sig = Signal(symbol="BTC/USDT:USDT", direction=Direction.LONG, conviction=0.8,
             entry_price=100.0, stop_price=95.0, take_profit=110.0,
             profile="daytrade", rationale="teste")

# ---------- 2. funding circuit breaker por ambiente ----------
d_test = RiskManager(cfg, environment="testnet").evaluate(sig, state, funding_rate=-0.005, data_age_sec=0)
d_main = RiskManager(cfg).evaluate(sig, state, funding_rate=-0.005, data_age_sec=0)
d_hi = RiskManager(cfg, environment="testnet").evaluate(sig, state, funding_rate=-0.02, data_age_sec=0)
ok("funding -0.005 aprovado em testnet", d_test.approved, d_test.reason)
ok("funding -0.005 vetado em mainnet (default)", not d_main.approved, d_main.reason)
ok("funding -0.02 vetado mesmo em testnet", not d_hi.approved, d_hi.reason)

# ---------- 3. sizing pelo stop ----------
ok("sizing 5 USDT / 5 de distancia = size 1.0", abs(d_test.position_size - 1.0) < 1e-9,
   f"size={d_test.position_size}")
sig_ns = Signal(symbol="X", direction=Direction.LONG, conviction=0.8, entry_price=100.0,
                stop_price=0.0, take_profit=None, profile="daytrade", rationale="sem stop")
d_ns = RiskManager(cfg, environment="testnet").evaluate(sig_ns, state, funding_rate=0.0, data_age_sec=0)
ok("sem stop -> veto", not d_ns.approved, d_ns.reason)

# ---------- 3b. teto de capital por trade individual (decisão 17/07) ----------
# equity 1000, risk_pct 0.5% => risk_usdt=5; stop MUITO apertado (distância 0.1)
# => size teórico 50 / notional 5000 — bem acima de qualquer teto razoável.
# Usa uma cópia ISOLADA do cfg com o teto fixado em 20% (não o valor ao vivo
# de config/risk_config.yaml, que muda com o capital/decisão do Lucas — ver
# padrão idêntico na seção 14 abaixo) para o teste não quebrar a cada ajuste
# do YAML (achado 27/07: subiu pra 100.0 na transição pra mainnet, size real
# virou 10.0 e este teste passou a falhar mesmo com o código correto).
AUDIT.unlink(missing_ok=True)
cfg_teto20 = copy.deepcopy(cfg)
cfg_teto20["per_trade"]["max_notional_pct_equity"] = 20.0
sig_tight = Signal(symbol="BTC/USDT:USDT", direction=Direction.LONG, conviction=0.8,
                   entry_price=100.0, stop_price=99.9, take_profit=100.3,
                   profile="daytrade", rationale="teste stop apertado")
d_tight = RiskManager(cfg_teto20, environment="testnet").evaluate(sig_tight, state, funding_rate=-0.005, data_age_sec=0)
ok("teto por trade: size CLAMPADO a 20% do equity (nunca vetado)",
   d_tight.approved and abs(d_tight.position_size - 2.0) < 1e-9,
   f"size={d_tight.position_size}")
ev = [json.loads(l) for l in AUDIT.read_text(encoding="utf-8").splitlines()]
ap = [e for e in ev if e["event"] == "signal_approved"]
ok("signal_approved audita capped=True quando o teto é atingido",
   len(ap) == 1 and ap[0].get("capped") is True)

AUDIT.unlink(missing_ok=True)
sig_normal = Signal(symbol="BTC/USDT:USDT", direction=Direction.LONG, conviction=0.8,
                    entry_price=100.0, stop_price=95.0, take_profit=110.0,
                    profile="daytrade", rationale="teste normal")
d_normal = RiskManager(cfg, environment="testnet").evaluate(sig_normal, state, funding_rate=-0.005, data_age_sec=0)
ev = [json.loads(l) for l in AUDIT.read_text(encoding="utf-8").splitlines()]
ap = [e for e in ev if e["event"] == "signal_approved"]
ok("sizing normal (abaixo do teto): capped=False, size intacto",
   d_normal.approved and abs(d_normal.position_size - 1.0) < 1e-9
   and len(ap) == 1 and ap[0].get("capped") is False)


# ---------- 4. estratégia: alta + pullback => LONG ----------
def make_candles(n=200, start_ts=1_752_000_000_000, tf_ms=900_000):
    rows, price = [], 100.0
    for i in range(n):
        drift = 0.003 if i < n - 9 else -0.0015
        new = price * (1 + drift)
        high, low = max(price, new) * 1.001, min(price, new) * 0.999
        rows.append([start_ts + i * tf_ms, price, high, low, new, 10.0])
        price = new
    return pd.DataFrame(rows, columns=["ts", "open", "high", "low", "close", "volume"])


df = compute_indicators(make_candles())
snap = snapshot_from_df("BTC/USDT:USDT", "15m", df, funding_rate=-0.005)
s = DeterministicStrategy("daytrade").generate(snap)
ok("estrategia gera LONG no cenario alta+pullback", s.direction == Direction.LONG,
   f"dir={s.direction.value} rsi={snap.indicators['rsi']:.1f}")

# ---------- 5. engine: isolamento de erro + exclusividade por símbolo ----------
import src.engine as engine_mod  # noqa: E402

# A suíte inteira daqui pra baixo é majoritariamente sobre mecânica EXCLUSIVA
# de spot (TP por software em _check_spot_exits, executor spot-only,
# trailing/exit-por-sinal calibrados pro executor spot) — dezenas de
# `Engine()` construídas ao longo do arquivo dependiam implicitamente de
# config/risk_config.yaml real estar em market.type=spot. Isso valia de
# graça até 27/07/2026; desde 28/07/2026 (Lucas religou perp/short em
# produção) o YAML real é "perp". Em vez de decorar cada instância
# individualmente, força "spot" aqui, uma vez, pra TODA Engine() construída
# a partir daqui — decoupled do que o YAML ao vivo disser. Seções que
# precisam testar "perp" explicitamente (ex.: prova de que
# _check_spot_exits vira no-op) fazem seu próprio override PONTUAL depois
# da construção (`eng_x.market_type = "perp"`), que sempre vence por rodar
# depois deste monkeypatch.
engine_mod.get_market_type = lambda cfg: "spot"


class FakeEthQuebrado:
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
        # destes testes por "Funding anômalo", sem relação com o que a seção
        # realmente testa (exclusividade por símbolo / falha de execução).
        return 0.001

    def fetch_ohlcv(self, symbol, timeframe, limit=200):
        if symbol.startswith("ETH"):
            raise RuntimeError("falha de rede simulada (ETH)")
        return make_candles().values.tolist()


AUDIT.unlink(missing_ok=True)
engine_mod.BybitClient = FakeEthQuebrado  # nunca toca a rede
eng = engine_mod.Engine(dry_run=True)
try:
    eng.run_once()
    raised = False
except Exception:
    raised = True
ok("run_once nao levanta com simbolo quebrado", not raised)

ev = [json.loads(l) for l in AUDIT.read_text(encoding="utf-8").splitlines()]
btc_ap = [e for e in ev if e["event"] == "signal_approved" and e["symbol"].startswith("BTC")]
btc_sk = [e for e in ev if e["event"] == "symbol_skipped" and e["symbol"].startswith("BTC")]
eth_er = [e for e in ev if e["event"] == "symbol_cycle_error" and e["symbol"].startswith("ETH")]
ok("BTC: 1 aprovacao (exclusividade por simbolo)", len(btc_ap) == 1, f"{len(btc_ap)}")
ok("BTC: 2o perfil pulado", len(btc_sk) == 1, f"{len(btc_sk)}")
ok("ETH: 2 erros isolados, ciclo seguiu", len(eth_er) == 2, f"{len(eth_er)}")

# ---------- 6. virada de dia UTC refaz o marco do drawdown diário ----------
from datetime import date, timedelta  # noqa: E402

eng2 = engine_mod.Engine(dry_run=True)
eng2._portfolio_state()
eng2._day_start_date = date.today() - timedelta(days=1)
eng2._day_start_equity = 500.0  # marco antigo (falso drawdown)
st2 = eng2._portfolio_state()
ok("virada de dia UTC refaz day_start_equity", st2.day_start_equity == 1000.0,
   f"day_start={st2.day_start_equity}")


# ---------- 7. executor: stop falhou -> fecha posicao (nunca nua) ----------
class FakeLive:
    is_testnet = True
    calls = []

    def set_leverage(self, *a, **k):
        pass

    def create_order(self, symbol, side, amount, order_type="market", price=None, params=None):
        FakeLive.calls.append((side, order_type, dict(params or {})))
        return {"id": f"o{len(FakeLive.calls)}"}

    def set_stop_loss(self, *a, **k):
        raise RuntimeError("stop rejeitado (simulado)")


ex = Executor(FakeLive(), dry_run=False)
try:
    ex.execute(sig, d_test)
    esc = False
except RuntimeError:
    esc = True
reduce_close = [c for c in FakeLive.calls if c[2].get("reduceOnly")]
ok("posicao fechada apos falha do stop (reduceOnly)", len(reduce_close) == 1)
ok("erro do stop escalado ao chamador", esc)
ev = [json.loads(l) for l in AUDIT.read_text(encoding="utf-8").splitlines()]
ok("naked_position_close auditado",
   len([e for e in ev if e["event"] == "naked_position_close"]) == 1)

# ---------- 8. backtest sintetico ----------
res = Backtester(cfg, profile="daytrade").run("BTC/USDT:USDT", "15m", make_candles(n=1200))
m = compute_metrics(res)
ok("backtest roda e fecha trades", m.n_trades > 0, f"trades={m.n_trades} ret={m.total_return_pct:.2f}%")
ok("curva de equity termina no end_equity", abs(res.equity_curve[-1][1] - res.end_equity) < 1e-9)


# ---------- 9. executor coloca TP (decisão #F); falha de TP não fecha posição ----------
class FakeLiveOk:
    is_testnet = True

    def __init__(self):
        self.calls = []

    def set_leverage(self, *a, **k):
        self.calls.append(("set_leverage",))

    def create_order(self, symbol, side, amount, order_type="market", price=None, params=None):
        self.calls.append(("create_order", side, dict(params or {}), price))
        return {"id": f"o{len(self.calls)}"}

    def set_stop_loss(self, symbol, side, amount, stop):
        self.calls.append(("set_stop_loss", stop))
        return {"id": "sl1"}

    def set_take_profit(self, symbol, side, amount, tp):
        self.calls.append(("set_take_profit", tp))
        return {"id": "tp1"}


AUDIT.unlink(missing_ok=True)
flo = FakeLiveOk()
r_tp = Executor(flo, dry_run=False).execute(sig, d_test)
ok("TP colocado apos o stop (decisao #F)",
   ("set_take_profit", 110.0) in flo.calls and r_tp["take_profit"]["id"] == "tp1")
ev = [json.loads(l) for l in AUDIT.read_text(encoding="utf-8").splitlines()]
oe = [e for e in ev if e["event"] == "order_executed"]
ok("order_executed audita tp_id", len(oe) == 1 and oe[0].get("tp_id") == "tp1")


class FakeTpFalha(FakeLiveOk):
    def set_take_profit(self, *a, **k):
        raise RuntimeError("tp rejeitado (simulado)")


AUDIT.unlink(missing_ok=True)
ftf = FakeTpFalha()
try:
    r_tpf = Executor(ftf, dry_run=False).execute(sig, d_test)
    tp_esc = False
except Exception:
    tp_esc = True
fechamentos = [c for c in ftf.calls if c[0] == "create_order" and c[2].get("reduceOnly")]
ok("falha de TP nao escala nem fecha posicao (stop protege)",
   not tp_esc and r_tpf is not None and r_tpf["take_profit"] is None and not fechamentos)
ev = [json.loads(l) for l in AUDIT.read_text(encoding="utf-8").splitlines()]
ok("take_profit_failed auditado",
   len([e for e in ev if e["event"] == "take_profit_failed"]) == 1)

# ---------- 10. modo SPOT (decisão #E): short vetado, leverage 1, exposição 1x ----------
import copy  # noqa: E402

cfg_spot = copy.deepcopy(cfg)
cfg_spot["market"] = {"type": "spot"}
rm_spot = RiskManager(cfg_spot, environment="testnet")

sig_short = Signal(symbol="BTC/USDT", direction=Direction.SHORT, conviction=0.8,
                   entry_price=100.0, stop_price=105.0, take_profit=90.0,
                   profile="daytrade", rationale="teste short spot")
d_short = rm_spot.evaluate(sig_short, state, funding_rate=None, data_age_sec=0)
ok("spot: SHORT vetado", not d_short.approved and "Spot" in d_short.reason, d_short.reason)

sig_spot = Signal(symbol="BTC/USDT", direction=Direction.LONG, conviction=0.8,
                  entry_price=100.0, stop_price=95.0, take_profit=110.0,
                  profile="daytrade", rationale="teste long spot")
d_spot = rm_spot.evaluate(sig_spot, state, funding_rate=None, data_age_sec=0)
ok("spot: LONG aprovado com leverage 1", d_spot.approved and d_spot.leverage == 1,
   f"lev={d_spot.leverage}")

state_cheio = PortfolioState(equity_usdt=1000.0, day_start_equity=1000.0, peak_equity=1000.0,
                             open_positions=1, total_notional=950.0, aggregate_risk_pct=0.5)
d_caixa = rm_spot.evaluate(sig_spot, state_cheio, funding_rate=None, data_age_sec=0)
ok("spot: exposicao limitada a 1x equity (sem margem)",
   not d_caixa.approved and "nocional" in d_caixa.reason, d_caixa.reason)

class FakeSpot(FakeLiveOk):
    """Simula a realidade do spot: a compra credita MENOS base que o size
    teórico (fee na moeda recebida) — 99,9% aqui.

    fetch_free_base agora é chamado 2x pelo executor (antes E depois da
    compra, achado 19/07 — ver executor.py) — a 1ª chamada simula "nada de
    saldo pré-existente" (0.0), a 2ª simula o saldo real pós-compra."""

    FREE_FRAC = 0.999

    def __init__(self):
        super().__init__()
        self._free_base_calls = 0

    def create_order(self, symbol, side, amount, order_type="market", price=None, params=None):
        self.calls.append(("create_order", side, amount, dict(params or {}), price))
        return {"id": f"o{len(self.calls)}"}

    def fetch_free_base(self, symbol):
        self._free_base_calls += 1
        if self._free_base_calls == 1:
            return 0.0
        return d_spot.position_size * self.FREE_FRAC

    def amount_to_precision(self, symbol, amount):
        return round(amount, 8)

    def set_stop_loss(self, symbol, side, amount, stop):
        self.calls.append(("set_stop_loss", stop, amount))
        return {"id": "sl1"}

    def set_take_profit(self, symbol, side, amount, tp):
        self.calls.append(("set_take_profit", tp, amount))
        return {"id": "tp1"}


AUDIT.unlink(missing_ok=True)
fsp = FakeSpot()
r_spot = Executor(fsp, dry_run=False, market_type="spot").execute(sig_spot, d_spot)
entradas = [c for c in fsp.calls if c[0] == "create_order"]
ok("spot: sem set_leverage; entrada leva preco de referencia",
   ("set_leverage",) not in fsp.calls and len(entradas) == 1 and entradas[0][4] == 100.0)
stops = [c for c in fsp.calls if c[0] == "set_stop_loss"]
clamp = round(d_spot.position_size * FakeSpot.FREE_FRAC, 8)
ok("spot: stop clampado ao saldo base REAL (nao ao size teorico)",
   len(stops) == 1 and stops[0][1] == 95.0 and abs(stops[0][2] - clamp) < 1e-12,
   f"protegido={stops[0][2] if stops else '-'} vs teorico={d_spot.position_size}")
tps = [c for c in fsp.calls if c[0] == "set_take_profit"]
ev = [json.loads(l) for l in AUDIT.read_text(encoding="utf-8").splitlines()]
ok("spot: TP e PULADO (sem OCO; stop ocupa o saldo) e auditado",
   not tps and r_spot["take_profit"] is None
   and len([e for e in ev if e["event"] == "take_profit_skipped"]) == 1)


# ---------- 11. spot: caminho nunca-nua com saldo real; auditoria honesta ----------
class FakeSpotStopFalha(FakeSpot):
    def set_stop_loss(self, *a, **k):
        raise RuntimeError("stop spot rejeitado (simulado)")


AUDIT.unlink(missing_ok=True)
fss = FakeSpotStopFalha()
try:
    Executor(fss, dry_run=False, market_type="spot").execute(sig_spot, d_spot)
    esc_sp = False
except RuntimeError:
    esc_sp = True
vendas = [c for c in fss.calls if c[0] == "create_order" and c[1] == "sell"]
ev = [json.loads(l) for l in AUDIT.read_text(encoding="utf-8").splitlines()]
ok("spot: emergencia vende o saldo REAL e escala o erro",
   esc_sp and len(vendas) == 1 and abs(vendas[0][2] - clamp) < 1e-12
   and len([e for e in ev if e["event"] == "naked_position_close"]) == 1)


class FakeSpotTudoFalha(FakeSpotStopFalha):
    def create_order(self, symbol, side, amount, order_type="market", price=None, params=None):
        if side == "sell":
            raise RuntimeError("saldo insuficiente (simulado)")
        return super().create_order(symbol, side, amount, order_type, price, params)


AUDIT.unlink(missing_ok=True)
ftt = FakeSpotTudoFalha()
try:
    Executor(ftt, dry_run=False, market_type="spot").execute(sig_spot, d_spot)
    esc_tt = False
except RuntimeError:
    esc_tt = True
ev = [json.loads(l) for l in AUDIT.read_text(encoding="utf-8").splitlines()]
ok("spot: fechamento falhou -> naked_position_close_failed (trilha nao mente)",
   esc_tt
   and len([e for e in ev if e["event"] == "naked_position_close_failed"]) == 1
   and len([e for e in ev if e["event"] == "naked_position_close"]) == 0)

# ---------- 12. spot: saída por take-profit em software (sem OCO na Bybit) ----------
import src.execution.protection_state as protection_state  # noqa: E402

STATE_FILE = _STATE_FILE  # já capturado/guardado no topo do arquivo


class FakeSpotExit:
    is_testnet = True
    PRICE = 100.0  # ajustado por cada cenário antes de chamar _check_spot_exits
    FREE_BASE = 0.066047  # ajustado quando o cenário simula saldo alheio na carteira
    # order_id -> resposta simulada de fetch_order (18/07/2026: confirmação de
    # fechamento por stop + recuperação de entry_price via entry_id). Vazio =
    # qualquer id consultado devolve "ainda aberta, sem fill" (conservador).
    ORDER_RESPONSES = {}

    def __init__(self, *a, **k):
        self.calls = []

    def fetch_ticker(self, symbol):
        self.calls.append(("fetch_ticker", symbol))
        return {"last": FakeSpotExit.PRICE}

    def cancel_all(self, symbol):
        self.calls.append(("cancel_all", symbol))

    def fetch_free_base(self, symbol):
        return FakeSpotExit.FREE_BASE

    def amount_to_precision(self, symbol, amount):
        return round(amount, 8)

    def create_order(self, symbol, side, amount, order_type="market", price=None, params=None):
        self.calls.append(("create_order", side, amount))
        return {"id": "tp-exit-1", "average": FakeSpotExit.PRICE}

    def fetch_order(self, order_id, symbol):
        self.calls.append(("fetch_order", order_id, symbol))
        return FakeSpotExit.ORDER_RESPONSES.get(
            order_id, {"id": order_id, "status": "open", "filled": 0.0,
                       "average": None, "price": None})


# 12a. DRY_RUN nunca pode tocar a exchange de verdade (achado CRÍTICO da
# revisão adversarial de 17/07: antes deste fix, Engine(dry_run=True) ainda
# cancelava o stop e vendia de verdade assim que o preço batesse o alvo).
AUDIT.unlink(missing_ok=True)
protection_state.clear_protection("BTC/USDT")
protection_state.set_protection("BTC/USDT", entry_price=100.0, take_profit=110.0,
                                stop_price=95.0, size=0.066047)
engine_mod.BybitClient = FakeSpotExit
FakeSpotExit.PRICE = 112.0  # acima do alvo
eng_dry = engine_mod.Engine(dry_run=True)
# Toda a seção 12 testa o caminho SPOT de _check_spot_exits() (TP por
# software) — sem isto, market.type=perp faria o método virar no-op de
# propósito e a maioria das asserções abaixo passaria por acidente (achado
# da 2ª rodada de revisão adversarial de 17/07). Até 27/07/2026 isso valia
# de graça porque o YAML real vivia em spot; desde 28/07/2026 (Lucas religou
# perp/short em produção) o YAML real é "perp" — força o cenário aqui,
# mesmo precedente já usado na seção 13 (`eng_tp.market_type = "perp"`, mais
# abaixo), pra este teste continuar cobrindo o mecanismo spot-only
# independente do que o YAML ao vivo disser.
eng_dry.market_type = "spot"
eng_dry._open_symbols = {"BTC/USDT"}
eng_dry._check_spot_exits()
ok("DRY_RUN: nenhuma chamada real a exchange (nem cancel_all nem create_order)",
   not any(c[0] in ("cancel_all", "create_order") for c in eng_dry.client.calls),
   str(eng_dry.client.calls))
ok("DRY_RUN: protecao permanece intacta (nada foi fechado de verdade)",
   "BTC/USDT" in protection_state.load())
ev_dry = [json.loads(l) for l in AUDIT.read_text(encoding="utf-8").splitlines()]
ok("DRY_RUN: audita dry_run_take_profit em vez de agir",
   len([e for e in ev_dry if e["event"] == "dry_run_take_profit"]) == 1)
protection_state.clear_protection("BTC/USDT")

# 12b. dry_run=False a partir daqui: fluxo real de execução.
AUDIT.unlink(missing_ok=True)
protection_state.set_protection("BTC/USDT", entry_price=100.0, take_profit=110.0,
                                stop_price=95.0, size=0.066047)
FakeSpotExit.FREE_BASE = 0.066047
eng_tp = engine_mod.Engine(dry_run=False)
# Seções 12b-12d testam o caminho SPOT de _check_spot_exits() (TP por
# software) — mesmo motivo/mesmo precedente da seção 12a (ver acima) e da
# seção 13 mais abaixo (`eng_tp.market_type = "perp"`, que reusa este MESMO
# objeto pra provar o no-op no sentido contrário). Desde 28/07/2026 o YAML
# real é "perp"; força "spot" aqui pra estas seções continuarem exercitando
# o mecanismo, independente do YAML ao vivo.
eng_tp.market_type = "spot"
eng_tp._open_symbols = {"BTC/USDT"}

FakeSpotExit.PRICE = 105.0  # abaixo do alvo -> não deve fechar
eng_tp._check_spot_exits()
ok("TP nao atingido: nenhuma venda disparada",
   not any(c[0] == "create_order" for c in eng_tp.client.calls))
ok("TP nao atingido: protecao permanece salva", "BTC/USDT" in protection_state.load())

FakeSpotExit.PRICE = 112.0  # acima do alvo -> deve fechar
eng_tp._check_spot_exits()
ok("TP atingido: cancel_all chamado antes da venda (libera saldo do stop)",
   ("cancel_all", "BTC/USDT") in eng_tp.client.calls)
vendas = [c for c in eng_tp.client.calls if c[0] == "create_order"]
ok("TP atingido: venda a mercado do saldo base REAL",
   len(vendas) == 1 and vendas[0][1] == "sell" and vendas[0][2] == 0.066047, str(vendas))
ok("TP atingido: protecao limpa apos execucao", "BTC/USDT" not in protection_state.load())
ev = [json.loads(l) for l in AUDIT.read_text(encoding="utf-8").splitlines()]
tpx = [e for e in ev if e["event"] == "take_profit_executed" and e["symbol"] == "BTC/USDT"]
tc = [e for e in ev if e["event"] == "trade_closed" and e["symbol"] == "BTC/USDT"]
ok("take_profit_executed auditado", len(tpx) == 1)
pnl_esperado = (112.0 - 100.0) * 0.066047
ok("trade_closed auditado com pnl_usdt correto",
   len(tc) == 1 and abs(tc[0]["pnl_usdt"] - pnl_esperado) < 1e-9,
   f"{tc[0].get('pnl_usdt') if tc else '-'} vs {pnl_esperado}")

# 12c. venda só pode consumir a posição RASTREADA, nunca saldo alheio na
# mesma moeda-base (achado da revisão de 17/07: antes vendia fetch_free_base()
# inteiro, sem clamp — igual ao saldo de brinde documentado no CLAUDE.md).
AUDIT.unlink(missing_ok=True)
protection_state.set_protection("BTC/USDT", entry_price=100.0, take_profit=110.0,
                                stop_price=95.0, size=0.05)  # só 0,05 é do bot
FakeSpotExit.FREE_BASE = 0.08  # carteira tem 0,08 (0,03 é saldo alheio/brinde)
FakeSpotExit.PRICE = 112.0
eng_tp.client.calls = []
eng_tp._open_symbols = {"BTC/USDT"}
eng_tp._check_spot_exits()
vendas_clamp = [c for c in eng_tp.client.calls if c[0] == "create_order"]
ok("TP so vende o tamanho RASTREADO da posicao, nao o saldo livre inteiro",
   len(vendas_clamp) == 1 and abs(vendas_clamp[0][2] - 0.05) < 1e-9, str(vendas_clamp))
FakeSpotExit.FREE_BASE = 0.066047  # restaura pro resto dos testes

# 12d. preço NaN do ticker NÃO pode disparar venda (NaN < alvo é sempre False
# em Python — achado da revisão de 17/07: passava direto pelo guard antigo).
AUDIT.unlink(missing_ok=True)
protection_state.set_protection("BTC/USDT", entry_price=100.0, take_profit=110.0,
                                stop_price=95.0, size=0.066047)


class FakeSpotExitNaN(FakeSpotExit):
    def fetch_ticker(self, symbol):
        self.calls.append(("fetch_ticker", symbol))
        return {"last": float("nan")}


engine_mod.BybitClient = FakeSpotExitNaN
eng_nan = engine_mod.Engine(dry_run=False)
# Sem isto, com o YAML real em "perp", _check_spot_exits() vira no-op e a
# asserção abaixo passaria por acidente (nenhuma chamada acontece de
# qualquer jeito) — não provaria o guard de NaN de verdade. Mesmo motivo
# das seções 12a/12b-d acima.
eng_nan.market_type = "spot"
eng_nan._open_symbols = {"BTC/USDT"}
eng_nan._check_spot_exits()
ok("preco NaN do ticker NAO dispara venda (guard math.isfinite)",
   not any(c[0] in ("cancel_all", "create_order") for c in eng_nan.client.calls),
   str(eng_nan.client.calls))
protection_state.clear_protection("BTC/USDT")
engine_mod.BybitClient = FakeSpotExit

# proteção órfã sem stop_id (posição fechou por fora, sem confirmação
# possível do fill) é limpa E audita trade_closed aproximado — redesenhado em
# 18/07/2026 junto com a confirmação de fechamento por stop: antes (17/07) só
# emitia take_profit_protection_orphaned, sem QUANTO fechou.
AUDIT.unlink(missing_ok=True)
protection_state.set_protection("SOL/USDT", entry_price=10.0, take_profit=12.0, stop_price=9.0)
eng_tp._open_symbols = set()  # SOL fechou por fora (manual ou stop) — reconciliação não vê mais
eng_tp._check_spot_exits()
ok("protecao orfa (simbolo fechado por fora) e limpa no proximo ciclo",
   "SOL/USDT" not in protection_state.load())
ev_orph = [json.loads(l) for l in AUDIT.read_text(encoding="utf-8").splitlines()]
tc_orph = [e for e in ev_orph if e["event"] == "trade_closed" and e["symbol"] == "SOL/USDT"]
ok("fechamento sem stop_id (sem como confirmar) audita trade_closed aproximado",
   len(tc_orph) == 1 and tc_orph[0]["reason"] == "external_close_unconfirmed"
   and tc_orph[0]["exit_price"] == 9.0 and tc_orph[0]["pnl_usdt"] is None,
   str(tc_orph))

# backfill: posição aberta ANTES desta feature existir (sem protection_state,
# só o order_executed já gravado na trilha em algum momento). free != protect_size
# de propósito (1.5 vs 1.0): se o clamp min(free, tracked) parasse de valer no
# caminho de backfill, este teste venderia 1.5 em vez de 1.0 e pegaria a
# regressão (achado da 2ª rodada de revisão adversarial de 17/07 — a versão
# anterior deste teste usava free==tracked, incapaz de discriminar o bug).
AUDIT.write_text(json.dumps({
    "ts": "2026-07-17T10:00:00+00:00", "event": "order_executed", "symbol": "ETH/USDT",
    "side": "buy", "size": 1.0, "protect_size": 1.0, "entry_price": 50.0,
    "stop_price": 45.0, "take_profit": 60.0, "entry_id": "e1", "stop_id": "s1",
    "tp_id": None, "testnet": True,
}) + "\n", encoding="utf-8")
FakeSpotExit.PRICE = 65.0  # acima do alvo backfilled (60.0)
FakeSpotExit.FREE_BASE = 1.5  # carteira tem mais que o protect_size rastreado (1.0)
eng_tp.client.calls = []
eng_tp._open_symbols = {"ETH/USDT"}
eng_tp._check_spot_exits()
vendas_bf = [c for c in eng_tp.client.calls if c[0] == "create_order"]
ok("TP via backfill vende so o protect_size rastreado (1.0), nao o saldo livre (1.5)",
   len(vendas_bf) == 1 and abs(vendas_bf[0][2] - 1.0) < 1e-9, str(vendas_bf))
ev2 = [json.loads(l) for l in AUDIT.read_text(encoding="utf-8").splitlines()]
ok("trade_closed tambem sai no caminho de backfill",
   len([e for e in ev2 if e["event"] == "trade_closed" and e["symbol"] == "ETH/USDT"]) == 1)
FakeSpotExit.FREE_BASE = 0.066047

# 12e. backfill persiste no arquivo assim que a posição é vista, mesmo sem
# fechar neste ciclo — sem isto, posições abertas antes desta função existir
# (ex.: BTC de 17/07) só têm proteção em memória, nunca sobrevivem a um
# reinício do engine entre ciclos (18/07/2026).
AUDIT.write_text(json.dumps({
    "ts": "2026-07-18T09:00:00+00:00", "event": "order_executed", "symbol": "XRP/USDT",
    "side": "buy", "size": 2.0, "protect_size": 2.0, "entry_price": 1.0,
    "stop_price": 0.9, "take_profit": 1.2, "entry_id": "e2", "stop_id": "s2",
    "tp_id": None, "testnet": True,
}) + "\n", encoding="utf-8")
FakeSpotExit.PRICE = 1.05  # abaixo do alvo -> não fecha neste ciclo
eng_tp.client.calls = []
eng_tp._open_symbols = {"XRP/USDT"}
eng_tp._check_spot_exits()
ok("backfill persiste a protecao no arquivo assim que a posicao e vista, mesmo sem fechar",
   "XRP/USDT" in protection_state.load(), str(protection_state.load().get("XRP/USDT")))
ok("protecao persistida guarda o stop_id da trilha (pra confirmar fechamento depois)",
   protection_state.load().get("XRP/USDT", {}).get("stop_id") == "s2")
protection_state.clear_protection("XRP/USDT")

# 12f. entry_price null na trilha (bug pré-fix #17) é recuperado via
# fetch_order(entry_id) no momento em que a posição backfilled é persistida
# pela primeira vez — sem isto, trades antigos (como o BTC de 17/07) nunca
# calculam pnl_usdt em nenhum fechamento (18/07/2026).
AUDIT.write_text(json.dumps({
    "ts": "2026-07-18T09:00:00+00:00", "event": "order_executed", "symbol": "ADA/USDT",
    "side": "buy", "size": 100.0, "protect_size": 100.0, "entry_price": None,
    "stop_price": 0.4, "take_profit": 0.6, "entry_id": "entry-ada-1", "stop_id": "stop-ada-1",
    "tp_id": None, "testnet": True,
}) + "\n", encoding="utf-8")
FakeSpotExit.ORDER_RESPONSES = {
    "entry-ada-1": {"id": "entry-ada-1", "status": "closed", "filled": 100.0,
                    "average": 0.5, "price": 0.5},
}
FakeSpotExit.PRICE = 0.55  # abaixo do alvo -> só testamos a resolução do entry_price
eng_tp.client.calls = []
eng_tp._open_symbols = {"ADA/USDT"}
eng_tp._check_spot_exits()
ok("entry_price null na trilha e recuperado via fetch_order(entry_id) e persistido",
   protection_state.load().get("ADA/USDT", {}).get("entry_price") == 0.5,
   str(protection_state.load().get("ADA/USDT")))
protection_state.clear_protection("ADA/USDT")
FakeSpotExit.ORDER_RESPONSES = {}

# 12g. fechamento por STOP (não por TP) é detectado e confirmado via
# fetch_order na ordem do stop — a lacuna que motivou esta rodada de
# mudanças: antes, só o caminho de TP emitia trade_closed; a maioria das
# saídas reais (via stop) ficava muda na trilha (18/07/2026).
AUDIT.unlink(missing_ok=True)
protection_state.set_protection("DOT/USDT", entry_price=5.0, take_profit=6.0,
                                stop_price=4.5, size=10.0, stop_id="stop-dot-1")
FakeSpotExit.ORDER_RESPONSES = {
    "stop-dot-1": {"id": "stop-dot-1", "status": "closed", "filled": 10.0,
                   "average": 4.48, "price": 4.48},
}
eng_tp.client.calls = []
eng_tp._open_symbols = set()  # DOT sumiu da reconciliação -> stop disparou
eng_tp._check_spot_exits()
ok("fechamento por stop confirmado: protecao limpa", "DOT/USDT" not in protection_state.load())
ev_dot = [json.loads(l) for l in AUDIT.read_text(encoding="utf-8").splitlines()]
tc_dot = [e for e in ev_dot if e["event"] == "trade_closed" and e["symbol"] == "DOT/USDT"]
pnl_dot_esperado = (4.48 - 5.0) * 10.0
ok("trade_closed confirmado via fetch_order: reason=stop_loss, exit_price do fill real, pnl correto",
   len(tc_dot) == 1 and tc_dot[0]["reason"] == "stop_loss"
   and tc_dot[0]["exit_price"] == 4.48
   and abs(tc_dot[0]["pnl_usdt"] - pnl_dot_esperado) < 1e-9,
   str(tc_dot))
FakeSpotExit.ORDER_RESPONSES = {}

# 12h. stop_id presente mas fetch_order NÃO confirma disparo (ordem
# cancelada/status diferente de closed) -> fechamento aproximado, nunca
# inventa um fill que não foi confirmado.
AUDIT.unlink(missing_ok=True)
protection_state.set_protection("LINK/USDT", entry_price=15.0, take_profit=18.0,
                                stop_price=13.5, size=3.0, stop_id="stop-link-1")
FakeSpotExit.ORDER_RESPONSES = {
    "stop-link-1": {"id": "stop-link-1", "status": "canceled", "filled": 0.0,
                    "average": None, "price": None},
}
eng_tp.client.calls = []
eng_tp._open_symbols = set()
eng_tp._check_spot_exits()
ev_link = [json.loads(l) for l in AUDIT.read_text(encoding="utf-8").splitlines()]
tc_link = [e for e in ev_link if e["event"] == "trade_closed" and e["symbol"] == "LINK/USDT"]
ok("stop_id sem confirmacao de fill (status != closed): aproximado, exit_price = alvo do stop",
   len(tc_link) == 1 and tc_link[0]["reason"] == "external_close_unconfirmed"
   and tc_link[0]["exit_price"] == 13.5, str(tc_link))
FakeSpotExit.ORDER_RESPONSES = {}

# 12i. fetch_order de UM símbolo falha (rede) ao confirmar o stop -> cai
# para aproximado sem propagar; o OUTRO símbolo do mesmo ciclo é confirmado
# normalmente (isolamento entre símbolos no loop de fechados).
AUDIT.unlink(missing_ok=True)
protection_state.set_protection("MATIC/USDT", entry_price=1.0, take_profit=1.2,
                                stop_price=0.9, size=50.0, stop_id="stop-matic-quebrado")
protection_state.set_protection("AVAX/USDT", entry_price=20.0, take_profit=24.0,
                                stop_price=18.0, size=1.0, stop_id="stop-avax-1")
FakeSpotExit.ORDER_RESPONSES = {
    "stop-avax-1": {"id": "stop-avax-1", "status": "closed", "filled": 1.0,
                    "average": 17.9, "price": 17.9},
}


class FakeSpotExitFetchOrderQuebrado(FakeSpotExit):
    def fetch_order(self, order_id, symbol):
        if order_id == "stop-matic-quebrado":
            raise RuntimeError("falha de rede simulada (fetch_order)")
        return super().fetch_order(order_id, symbol)


engine_mod.BybitClient = FakeSpotExitFetchOrderQuebrado
eng_iso = engine_mod.Engine(dry_run=False)
eng_iso._open_symbols = set()
eng_iso._check_spot_exits()
ev_iso = [json.loads(l) for l in AUDIT.read_text(encoding="utf-8").splitlines()]
tc_avax = [e for e in ev_iso if e["event"] == "trade_closed" and e["symbol"] == "AVAX/USDT"]
ok("AVAX confirmado via fetch_order mesmo com falha simultanea no MATIC (isolamento)",
   len(tc_avax) == 1 and tc_avax[0]["reason"] == "stop_loss")
tc_matic = [e for e in ev_iso if e["event"] == "trade_closed" and e["symbol"] == "MATIC/USDT"]
ok("MATIC: falha ao confirmar o stop cai para aproximado, nao trava nem propaga",
   len(tc_matic) == 1 and tc_matic[0]["reason"] == "external_close_unconfirmed"
   and tc_matic[0]["exit_price"] == 0.9, str(tc_matic))
ok("protecao de ambos limpa apos o ciclo",
   "MATIC/USDT" not in protection_state.load() and "AVAX/USDT" not in protection_state.load())
FakeSpotExit.ORDER_RESPONSES = {}
engine_mod.BybitClient = FakeSpotExit

# 12j. erro de verdade DENTRO de _handle_spot_position_closed (não só a
# falha de fetch_order, que já cai num fallback interno) não derruba o
# ciclo nem impede o próximo símbolo — mesmo padrão de isolamento por
# símbolo já validado para o loop de TP (seção 15), agora também no loop de
# fechados.
AUDIT.unlink(missing_ok=True)
protection_state.set_protection("BAD/USDT", entry_price=1.0, take_profit=1.2, stop_price=0.9)
_protecoes_corrompidas = protection_state.load()
_protecoes_corrompidas["BAD/USDT"]["size"] = "nao-e-numero"  # corrompe o arquivo direto
protection_state._save(_protecoes_corrompidas)
protection_state.set_protection("GOOD/USDT", entry_price=2.0, take_profit=2.4, stop_price=1.8,
                                size=1.0, stop_id="stop-good-1")
FakeSpotExit.ORDER_RESPONSES = {
    "stop-good-1": {"id": "stop-good-1", "status": "closed", "filled": 1.0,
                    "average": 1.79, "price": 1.79},
}
eng_bad = engine_mod.Engine(dry_run=False)
eng_bad._open_symbols = set()
try:
    eng_bad._check_spot_exits()
    nao_propagou = True
except Exception:
    nao_propagou = False
ok("erro real na apuracao de UM simbolo (size corrompido) nao derruba o ciclo", nao_propagou)
ev_bad = [json.loads(l) for l in AUDIT.read_text(encoding="utf-8").splitlines()]
err_bad = [e for e in ev_bad if e["event"] == "symbol_cycle_error"
           and e["symbol"] == "BAD/USDT" and e["profile"] == "position_closed_reconcile"]
ok("erro no BAD auditado como symbol_cycle_error (profile=position_closed_reconcile)",
   len(err_bad) == 1)
tc_good = [e for e in ev_bad if e["event"] == "trade_closed" and e["symbol"] == "GOOD/USDT"]
ok("GOOD processado normalmente apesar do erro no BAD (isolamento de verdade)",
   len(tc_good) == 1 and tc_good[0]["reason"] == "stop_loss")
ok("protecao de ambos limpa mesmo assim (finally roda independente do resultado)",
   "BAD/USDT" not in protection_state.load() and "GOOD/USDT" not in protection_state.load())
FakeSpotExit.ORDER_RESPONSES = {}


# ---------- 12k-12r. Regressão dos achados da revisão adversarial de 18/07 ----------

# 12k. venda do TP preenche só PARCIALMENTE (livro raso) — pnl usa o filled
# REAL (não o pedido) e o restante (acima da poeira) é protegido de novo com
# um stop RE-ARMADO, nunca só limpo como se a posição tivesse fechado
# inteira (achado CRÍTICO da revisão adversarial de 18/07).
class FakeSpotExitPartialFill(FakeSpotExit):
    FREE_BASE = 0.1  # saldo disponível pra venda (pré-venda; o fake nunca decrementa sozinho)
    FILLED = 0.07  # quanto a ordem REALMENTE preencheu (< o pedido, derivado da resposta)

    def fetch_free_base(self, symbol):
        # FakeSpotExit.fetch_free_base lê o atributo da classe-MÃE
        # explicitamente (FakeSpotExit.FREE_BASE) — sem este override,
        # definir FREE_BASE aqui na subclasse não teria efeito nenhum.
        # type(self) resolve pra subclasse mais derivada (útil também pra
        # FakeSpotExitDustRemainder, que herda deste fake).
        return type(self).FREE_BASE

    def create_order(self, symbol, side, amount, order_type="market", price=None, params=None):
        self.calls.append(("create_order", side, amount))
        return {"id": "tp-exit-partial", "average": FakeSpotExit.PRICE,
                "filled": type(self).FILLED}

    def set_stop_loss(self, symbol, side, amount, stop_price):
        self.calls.append(("set_stop_loss", side, amount, stop_price))
        return {"id": "stop-rearm-partial"}


AUDIT.unlink(missing_ok=True)
protection_state.set_protection("FILL/USDT", entry_price=400.0, take_profit=480.0,
                                stop_price=360.0, size=0.1, stop_id="stop-fill-orig")
engine_mod.BybitClient = FakeSpotExitPartialFill
eng_partial = engine_mod.Engine(dry_run=False)
eng_partial._open_symbols = {"FILL/USDT"}
FakeSpotExit.PRICE = 500.0  # acima do alvo
eng_partial._check_spot_exits()
ev_partial = [json.loads(l) for l in AUDIT.read_text(encoding="utf-8").splitlines()]
tc_partial = [e for e in ev_partial if e["event"] == "trade_closed" and e["symbol"] == "FILL/USDT"]
pnl_partial_esperado = (500.0 - 400.0) * 0.07  # 0.07 = FILLED, não os 0.1 pedidos
ok("TP com fill parcial: pnl_usdt usa o FILLED real, nao o size pedido",
   len(tc_partial) == 1 and abs(tc_partial[0]["size"] - 0.07) < 1e-9
   and abs(tc_partial[0]["pnl_usdt"] - pnl_partial_esperado) < 1e-9,
   str(tc_partial))
stops_partial = [c for c in eng_partial.client.calls if c[0] == "set_stop_loss"]
ok("TP com fill parcial: stop RE-ARMADO pro restante (nunca posicao nua)",
   len(stops_partial) == 1 and abs(stops_partial[0][2] - 0.03) < 1e-6, str(stops_partial))
protecao_fill = protection_state.load().get("FILL/USDT", {})
ok("TP com fill parcial: protecao NAO limpa, atualizada com o novo stop_id/size",
   protecao_fill.get("stop_id") == "stop-rearm-partial"
   and abs(protecao_fill.get("size", 0) - 0.03) < 1e-6, str(protecao_fill))
protection_state.clear_protection("FILL/USDT")
engine_mod.BybitClient = FakeSpotExit

# 12l. venda do TP preenche parcialmente mas o restante fica ABAIXO da
# poeira (SPOT_DUST_USDT) — tratado como fechamento completo, proteção
# simplesmente limpa (não vale a pena re-armar stop pra poeira).
class FakeSpotExitDustRemainder(FakeSpotExitPartialFill):
    FREE_BASE = 0.1
    FILLED = 0.0999  # sobra 0.0001 * 500 = 0,05 USDT, bem abaixo do limiar de poeira (10)


AUDIT.unlink(missing_ok=True)
protection_state.set_protection("DUST/USDT", entry_price=400.0, take_profit=480.0,
                                stop_price=360.0, size=0.1, stop_id="stop-dust-orig")
engine_mod.BybitClient = FakeSpotExitDustRemainder
eng_dust_r = engine_mod.Engine(dry_run=False)
eng_dust_r._open_symbols = {"DUST/USDT"}
FakeSpotExit.PRICE = 500.0
eng_dust_r._check_spot_exits()
ok("TP com resto abaixo da poeira: protecao limpa (nao re-arma pra valor irrelevante)",
   "DUST/USDT" not in protection_state.load())
stops_dust = [c for c in eng_dust_r.client.calls if c[0] == "set_stop_loss"]
ok("TP com resto abaixo da poeira: nenhum re-arm de stop chamado", len(stops_dust) == 0)
engine_mod.BybitClient = FakeSpotExit

# 12m. saldo zera após cancel_all durante o TP (stop disparou CONCORRENTE) ->
# delega pra _handle_spot_position_closed em vez de só limpar em silêncio
# (achado CRÍTICO, confirmado por 3 lentes independentes na revisão
# adversarial de 18/07: antes, esse fechamento real nunca gerava
# trade_closed — ficava mudo pra sempre).
class FakeSpotExitStopGanhouCorrida(FakeSpotExit):
    def fetch_free_base(self, symbol):
        return 0.0  # o stop já vendeu tudo antes do cancel_all conseguir liberar


AUDIT.unlink(missing_ok=True)
protection_state.set_protection("RACE/USDT", entry_price=20.0, take_profit=24.0,
                                stop_price=18.0, size=1.0, stop_id="stop-race-1")
FakeSpotExit.ORDER_RESPONSES = {
    "stop-race-1": {"id": "stop-race-1", "status": "closed", "filled": 1.0,
                    "average": 17.95, "price": 17.95},
}
engine_mod.BybitClient = FakeSpotExitStopGanhouCorrida
eng_race = engine_mod.Engine(dry_run=False)
eng_race._open_symbols = {"RACE/USDT"}
FakeSpotExit.PRICE = 24.5  # preço bateu o TP também, mas o stop ganhou a corrida
eng_race._check_spot_exits()
ev_race = [json.loads(l) for l in AUDIT.read_text(encoding="utf-8").splitlines()]
tc_race = [e for e in ev_race if e["event"] == "trade_closed" and e["symbol"] == "RACE/USDT"]
ok("stop ganha a corrida durante o TP: trade_closed SAI (antes nenhum evento saia)",
   len(tc_race) == 1 and tc_race[0]["reason"] == "stop_loss"
   and tc_race[0]["exit_price"] == 17.95, str(tc_race))
ok("protecao limpa apos a reconciliacao da corrida", "RACE/USDT" not in protection_state.load())
FakeSpotExit.ORDER_RESPONSES = {}
engine_mod.BybitClient = FakeSpotExit

# 12m2. cancel_all funciona DE VERDADE (stop realmente cancelado) mas a 1a
# leitura de fetch_free_base logo depois vem atrasada/racy (saldo ainda nao
# assentado na exchange) -- achado da revisao adversarial de 27/07/2026,
# mesma classe do bug #29 (21/07, lado da ENTRADA) so que agora do lado da
# SAIDA. Antes do fix: como o stop consultado via fetch_order mostra
# status=canceled (nao open/untriggered -- o cancel_all realmente rodou),
# o diagnostico antigo concluia "fechamento concorrente pelo stop" e
# delegava pra _handle_spot_position_closed, fabricando um trade_closed
# aproximado e limpando a protecao de uma posicao REAL, ainda aberta e
# agora sem NENHUM stop. Fix: reconfirma fetch_free_base uma vez antes de
# diagnosticar -- a 2a leitura mostra o saldo real e a venda acontece
# normalmente, sem fabricar fechamento nenhum.
class FakeSpotExitSaldoPosCancelRacy(FakeSpotExit):
    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self._free_calls = 0

    def fetch_free_base(self, symbol):
        self._free_calls += 1
        self.calls.append(("fetch_free_base", symbol))
        if self._free_calls == 1:
            return 0.0  # 1a leitura: racy, logo apos o cancel_all
        return 1.0  # reconfirmacao: saldo real ja assentado

    def create_order(self, symbol, side, amount, order_type="market", price=None, params=None):
        self.calls.append(("create_order", side, amount))
        return {"id": "racy-exit-1", "average": FakeSpotExit.PRICE, "filled": amount}


AUDIT.unlink(missing_ok=True)
protection_state.set_protection("RACY/USDT", entry_price=20.0, take_profit=24.0,
                                stop_price=18.0, size=1.0, stop_id="stop-racy-1")
FakeSpotExit.ORDER_RESPONSES = {
    "stop-racy-1": {"id": "stop-racy-1", "status": "canceled", "filled": 0.0,
                    "average": None, "price": None},
}
engine_mod.BybitClient = FakeSpotExitSaldoPosCancelRacy
eng_racy = engine_mod.Engine(dry_run=False)
eng_racy._open_symbols = {"RACY/USDT"}
FakeSpotExit.PRICE = 25.0  # acima do alvo -> deveria fechar por TP de verdade
eng_racy._check_spot_exits()
ev_racy = [json.loads(l) for l in AUDIT.read_text(encoding="utf-8").splitlines()]
tc_racy = [e for e in ev_racy if e["event"] == "trade_closed" and e["symbol"] == "RACY/USDT"]
vendas_racy = [c for c in eng_racy.client.calls if c[0] == "create_order"]
ok("saldo pos-cancel_all racy: reconfirma e VENDE de verdade (nao fabrica fechamento concorrente)",
   len(vendas_racy) == 1 and abs(vendas_racy[0][2] - 1.0) < 1e-9
   and len(tc_racy) == 1 and tc_racy[0]["reason"] == "take_profit", str(ev_racy))
ok("saldo pos-cancel_all racy: protecao limpa so DEPOIS da venda real (fluxo normal de TP)",
   "RACY/USDT" not in protection_state.load())
FakeSpotExit.ORDER_RESPONSES = {}
engine_mod.BybitClient = FakeSpotExit

# 12n. fetch_order confirma status=closed e filled>0 mas average/price vêm
# ambos 0 (dado ausente disfarçado de confirmado — cenário plausível pra
# ordem a mercado sem preço-limite) -> NÃO aceita como confirmado (achado
# ALTO da revisão adversarial de 18/07: antes virava reason=stop_loss com
# pnl fabricado).
AUDIT.unlink(missing_ok=True)
protection_state.set_protection("ZERO/USDT", entry_price=5.0, take_profit=6.0,
                                stop_price=4.5, size=10.0, stop_id="stop-zero-1")
FakeSpotExit.ORDER_RESPONSES = {
    "stop-zero-1": {"id": "stop-zero-1", "status": "closed", "filled": 10.0,
                    "average": 0, "price": 0},
}
eng_tp.client.calls = []
eng_tp._open_symbols = set()
eng_tp._check_spot_exits()
ev_zero = [json.loads(l) for l in AUDIT.read_text(encoding="utf-8").splitlines()]
tc_zero = [e for e in ev_zero if e["event"] == "trade_closed" and e["symbol"] == "ZERO/USDT"]
ok("average/price ambos 0 (mesmo com status=closed+filled>0): NAO aceita como confirmado",
   len(tc_zero) == 1 and tc_zero[0]["reason"] == "external_close_unconfirmed"
   and tc_zero[0]["exit_price"] == 4.5, str(tc_zero))
FakeSpotExit.ORDER_RESPONSES = {}

# 12o. caminho de TP também sempre audita trade_closed mesmo com
# entry_price desconhecido (pnl_usdt=None) — até 18/07 só o caminho de
# STOP tinha teste cobrindo isso (achado de cobertura da revisão
# adversarial: o comportamento já existia no código, mas nenhum teste
# provava — uma regressão futura passaria despercebida).
AUDIT.unlink(missing_ok=True)
protection_state.set_protection("NOENTRY/USDT", entry_price=0.0, take_profit=12.0,
                                stop_price=9.0, size=1.0)
FakeSpotExit.PRICE = 12.5
eng_tp.client.calls = []
eng_tp._open_symbols = {"NOENTRY/USDT"}
eng_tp._check_spot_exits()
ev_noentry = [json.loads(l) for l in AUDIT.read_text(encoding="utf-8").splitlines()]
tc_noentry = [e for e in ev_noentry if e["event"] == "trade_closed" and e["symbol"] == "NOENTRY/USDT"]
ok("TP com entry_price desconhecido: trade_closed AINDA sai, com pnl_usdt=None",
   len(tc_noentry) == 1 and tc_noentry[0]["pnl_usdt"] is None
   and tc_noentry[0]["entry_price"] is None, str(tc_noentry))

# 12p. protection_state.load(): bytes inválidos em UTF-8 não derrubam a
# leitura (UnicodeDecodeError é um ValueError, mas não um OSError nem
# json.JSONDecodeError — o except antigo não cobria; achado MÉDIO da
# revisão adversarial de 18/07).
_STATE_FILE.write_bytes(b"\xff\xfe\xfd\x00invalido")
loaded_invalido = protection_state.load()
ok("protection_state.load() nao propaga UnicodeDecodeError (trata como vazio)",
   loaded_invalido == {}, str(loaded_invalido))
_STATE_FILE.unlink(missing_ok=True)


# venda do TP falha DEPOIS do stop cancelado -> nunca posicao nua: re-arma o stop
class FakeSpotExitVendaFalha(FakeSpotExit):
    def create_order(self, symbol, side, amount, order_type="market", price=None, params=None):
        self.calls.append(("create_order", side, amount))
        raise RuntimeError("venda rejeitada (simulado)")

    def set_stop_loss(self, symbol, side, amount, stop_price):
        self.calls.append(("set_stop_loss", side, amount, stop_price))
        return {"id": "sl-rearm"}


AUDIT.unlink(missing_ok=True)
protection_state.set_protection("BTC/USDT", entry_price=100.0, take_profit=110.0,
                                stop_price=95.0, size=0.066047)
engine_mod.BybitClient = FakeSpotExitVendaFalha
FakeSpotExit.PRICE = 112.0  # fetch_ticker (herdado) referencia a classe-mãe, não a subclasse
eng_vf = engine_mod.Engine(dry_run=False)
eng_vf._open_symbols = {"BTC/USDT"}
eng_vf._check_spot_exits()
ok("venda do TP falhou apos cancelar o stop: stop e RE-ARMADO (nunca posicao nua)",
   ("set_stop_loss", "buy", 0.066047, 95.0) in eng_vf.client.calls,
   str(eng_vf.client.calls))
ok("protecao continua salva apos falha (proximo ciclo tenta de novo)",
   "BTC/USDT" in protection_state.load())
ev3 = [json.loads(l) for l in AUDIT.read_text(encoding="utf-8").splitlines()]
ok("take_profit_exit_failed auditado",
   len([e for e in ev3 if e["event"] == "take_profit_exit_failed"]) == 1)
ok("stop_id atualizado no arquivo apos re-armar (nao fica apontando pro ID cancelado, 18/07/2026)",
   protection_state.load().get("BTC/USDT", {}).get("stop_id") == "sl-rearm",
   str(protection_state.load().get("BTC/USDT")))
protection_state.clear_protection("BTC/USDT")
engine_mod.BybitClient = FakeSpotExit

# 12l/12m. Venda falha E o rearm do stop TAMBÉM falha (achado da auditoria de
# 27/07/2026: mesma chamada set_stop_loss/tpslOrder que o bloqueio de
# compliance de hoje confirma sujeita a rejeição) — última tentativa antes
# de desistir: liquidar a posição a MERCADO (ordem comum, não passa pela
# categoria bloqueada). 12l: liquidação de emergência SUCEDE.


class FakeSpotExitVendaFalhaRearmFalhaLiquidaOk(FakeSpotExit):
    CREATE_ORDER_CALLS = 0

    def create_order(self, symbol, side, amount, order_type="market", price=None, params=None):
        self.calls.append(("create_order", side, amount))
        FakeSpotExitVendaFalhaRearmFalhaLiquidaOk.CREATE_ORDER_CALLS += 1
        if FakeSpotExitVendaFalhaRearmFalhaLiquidaOk.CREATE_ORDER_CALLS == 1:
            raise RuntimeError("venda rejeitada (simulado)")
        # 2ª chamada = a liquidação de emergência dentro do fallback novo.
        return {"id": "liquidacao-emergencia-1", "average": FakeSpotExit.PRICE,
                "filled": amount}

    def set_stop_loss(self, symbol, side, amount, stop_price):
        self.calls.append(("set_stop_loss", side, amount, stop_price))
        raise RuntimeError("bloqueio de compliance simulado (10024/KYC_PROMPT_TOAST)")


AUDIT.unlink(missing_ok=True)
FakeSpotExitVendaFalhaRearmFalhaLiquidaOk.CREATE_ORDER_CALLS = 0
protection_state.set_protection("BTC/USDT", entry_price=100.0, take_profit=110.0,
                                stop_price=95.0, size=0.066047)
engine_mod.BybitClient = FakeSpotExitVendaFalhaRearmFalhaLiquidaOk
FakeSpotExit.PRICE = 112.0
eng_vfl_ok = engine_mod.Engine(dry_run=False)
eng_vfl_ok._open_symbols = {"BTC/USDT"}
eng_vfl_ok._check_spot_exits()
ok("venda falhou e rearm falhou: tentou liquidar a mercado (2ª chamada create_order)",
   eng_vfl_ok.client.CREATE_ORDER_CALLS == 2, str(eng_vfl_ok.client.calls))
ev_vfl_ok = [json.loads(l) for l in AUDIT.read_text(encoding="utf-8").splitlines()]
ok("liquidação de emergência bem-sucedida audita naked_position_close (nao rearm_failed)",
   any(e["event"] == "naked_position_close" for e in ev_vfl_ok)
   and not any(e["event"] == "take_profit_rearm_stop_failed" for e in ev_vfl_ok),
   str([e["event"] for e in ev_vfl_ok]))
protection_state.clear_protection("BTC/USDT")
engine_mod.BybitClient = FakeSpotExit

# 12m. Venda falha, rearm falha, E a liquidação de emergência TAMBÉM falha —
# aí sim é naked_position_close_failed de verdade (intervenção manual).


class FakeSpotExitVendaFalhaRearmFalhaLiquidaFalha(FakeSpotExit):
    def create_order(self, symbol, side, amount, order_type="market", price=None, params=None):
        self.calls.append(("create_order", side, amount))
        raise RuntimeError("venda rejeitada (simulado, inclusive a liquidação de emergência)")

    def set_stop_loss(self, symbol, side, amount, stop_price):
        self.calls.append(("set_stop_loss", side, amount, stop_price))
        raise RuntimeError("bloqueio de compliance simulado (10024/KYC_PROMPT_TOAST)")


AUDIT.unlink(missing_ok=True)
protection_state.set_protection("BTC/USDT", entry_price=100.0, take_profit=110.0,
                                stop_price=95.0, size=0.066047)
engine_mod.BybitClient = FakeSpotExitVendaFalhaRearmFalhaLiquidaFalha
FakeSpotExit.PRICE = 112.0
eng_vfl_fail = engine_mod.Engine(dry_run=False)
eng_vfl_fail._open_symbols = {"BTC/USDT"}
eng_vfl_fail._check_spot_exits()
ev_vfl_fail = [json.loads(l) for l in AUDIT.read_text(encoding="utf-8").splitlines()]
ok("liquidação de emergência TAMBÉM falhou: audita naked_position_close_failed",
   any(e["event"] == "naked_position_close_failed" for e in ev_vfl_fail),
   str([e["event"] for e in ev_vfl_fail]))
ok("liquidação de emergência TAMBÉM falhou: audita take_profit_rearm_stop_failed (alerta do watchdog)",
   any(e["event"] == "take_profit_rearm_stop_failed" for e in ev_vfl_fail),
   str([e["event"] for e in ev_vfl_fail]))
protection_state.clear_protection("BTC/USDT")
engine_mod.BybitClient = FakeSpotExit

# modo perp: _check_spot_exits é no-op (TP em perp já é ordem real na exchange)
eng_tp.market_type = "perp"
eng_tp.client.calls = []
protection_state.set_protection("BTC/USDT", entry_price=100.0, take_profit=1.0, stop_price=50.0)
eng_tp._open_symbols = {"BTC/USDT"}
eng_tp._check_spot_exits()
ok("perp: _check_spot_exits nao faz nada (TP ja e ordem real na exchange)",
   eng_tp.client.calls == [])
protection_state.clear_protection("BTC/USDT")


# ---------- 13. bybit_client: fetch_spot_holdings não pode dropar saldo real ----------
import src.exchange.bybit_client as bybit_client_mod  # noqa: E402


class FakeCcxtBalance:
    def __init__(self, holdings, fail_symbols=None):
        self.holdings = holdings
        self.fail_symbols = fail_symbols or set()

    def fetch_balance(self):
        return {base: {"total": qty} for base, qty in self.holdings.items()}

    def fetch_ticker(self, symbol, **kwargs):
        if symbol in self.fail_symbols:
            raise RuntimeError("network blip (simulado)")
        return {"last": 50000.0}


bc = bybit_client_mod.BybitClient.__new__(bybit_client_mod.BybitClient)
bc.exchange = FakeCcxtBalance({"BTC": 0.001}, fail_symbols={"BTC/USDT"})
holdings_fail = bc.fetch_spot_holdings(["BTC/USDT"])
ok("fetch_spot_holdings MANTEM simbolo com saldo real mesmo se fetch_ticker falhar",
   len(holdings_fail) == 1 and holdings_fail[0]["symbol"] == "BTC/USDT"
   and holdings_fail[0]["notional"] == 0.0, str(holdings_fail))

bc2 = bybit_client_mod.BybitClient.__new__(bybit_client_mod.BybitClient)
bc2.exchange = FakeCcxtBalance({"BTC": 0.0000001})  # poeira: notional bem abaixo de 10 USDT
holdings_dust = bc2.fetch_spot_holdings(["BTC/USDT"])
ok("fetch_spot_holdings AINDA filtra poeira quando o preco vem normalmente",
   holdings_dust == [], str(holdings_dust))

bc3 = bybit_client_mod.BybitClient.__new__(bybit_client_mod.BybitClient)
bc3.exchange = FakeCcxtBalance({"BTC": 0.001})
holdings_ok = bc3.fetch_spot_holdings(["BTC/USDT"])
ok("fetch_spot_holdings normal: saldo real com preco disponivel entra na lista",
   len(holdings_ok) == 1 and holdings_ok[0]["notional"] == 50.0, str(holdings_ok))


# ---------- 14. risk_manager: teto de capital com 0 explícito veta (nunca aprova size=0) ----------
cfg_zero = copy.deepcopy(cfg)
cfg_zero["per_trade"]["max_notional_pct_equity"] = 0.0
AUDIT.unlink(missing_ok=True)
d_zero = RiskManager(cfg_zero, environment="testnet").evaluate(
    sig_normal, state, funding_rate=-0.005, data_age_sec=0)
ok("teto de capital = 0 explicito VETA (nunca aprova entrada de tamanho zero)",
   not d_zero.approved and "zerou o tamanho" in d_zero.reason, d_zero.reason)


# ---------- 15. isolamento de erro por símbolo em _check_spot_exits (2+ símbolos) ----------
# Achado da 2ª rodada de revisão adversarial de 17/07: os testes da seção 12
# só exercitavam UM símbolo por vez, e o único cenário de exceção (venda
# falhando) é capturado por um try/except INTERNO de _execute_spot_take_profit
# (o de re-armar o stop) — nunca chega no try/except EXTERNO por símbolo.
# Pra testar o isolamento de verdade, a falha precisa acontecer DEPOIS da
# venda ter sucesso (ex.: audit()/clear_protection() falhando por lock do
# OneDrive) — cenário real que o achado #3 original descreveu.
_orig_clear_protection = protection_state.clear_protection


def _clear_protection_falha_btc(symbol):
    if symbol == "BTC/USDT":
        raise RuntimeError("falha de I/O simulada (lock do OneDrive)")
    return _orig_clear_protection(symbol)


AUDIT.unlink(missing_ok=True)
protection_state.set_protection("BTC/USDT", entry_price=100.0, take_profit=110.0,
                                stop_price=95.0, size=0.066047)
protection_state.set_protection("ETH/USDT", entry_price=50.0, take_profit=55.0,
                                stop_price=45.0, size=1.0)
engine_mod.BybitClient = FakeSpotExit
FakeSpotExit.PRICE = 200.0  # acima do alvo dos dois
eng_2s = engine_mod.Engine(dry_run=False)
eng_2s._open_symbols = {"BTC/USDT", "ETH/USDT"}
protection_state.clear_protection = _clear_protection_falha_btc
try:
    eng_2s._check_spot_exits()
    nao_propagou = True
except Exception:
    nao_propagou = False
finally:
    protection_state.clear_protection = _orig_clear_protection
ok("erro de I/O pos-venda em UM simbolo nao propaga (nao derruba --once)", nao_propagou)
ok("ETH continuou sendo processado apos erro no BTC (protecao limpa normalmente)",
   "ETH/USDT" not in protection_state.load())
ev15 = [json.loads(l) for l in AUDIT.read_text(encoding="utf-8").splitlines()]
ok("BTC vendeu com sucesso mesmo com a falha sendo no passo SEGUINTE",
   len([e for e in ev15 if e["event"] == "take_profit_executed"
        and e["symbol"] == "BTC/USDT"]) == 1)
ok("erro pos-venda do BTC auditado como symbol_cycle_error (nao mata o ciclo)",
   len([e for e in ev15 if e["event"] == "symbol_cycle_error"
        and e["symbol"] == "BTC/USDT" and e["profile"] == "take_profit_exit"]) == 1)
protection_state.clear_protection("BTC/USDT")  # limpa o residuo que a falha simulada deixou
engine_mod.BybitClient = FakeSpotExit


# ---------- 16. bybit_client.cancel_all precisa cancelar a categoria tpslOrder em spot ----------
# Achado 19/07, visto AO VIVO: a Bybit v5 exige `orderFilter` no cancelamento
# em massa pra atingir a categoria das ordens condicionais. O ccxt cria as
# ordens de stop/take-profit em spot com orderFilter="tpslOrder" (quando a
# chamada usa stopLossPrice/takeProfitPrice — ver set_stop_loss/
# set_take_profit), categoria DIFERENTE do default ("Order", comuns) que
# cancel_all_orders(symbol) atinge sem esse parâmetro. Sem o fix, o stop real
# nunca era cancelado: _execute_spot_take_profit "cancelava com sucesso" sem
# liberar o saldo-base, e toda venda de TP falhava pra sempre com erro de
# precisão mínima (posição BTC real presa nesse loop por ~20min em 19/07).
class FakeCcxtCancelAll:
    def __init__(self):
        self.calls = []

    def cancel_all_orders(self, symbol, params=None):
        self.calls.append((symbol, dict(params or {})))
        return {"result": {"success": "1"}}


bc_spot = bybit_client_mod.BybitClient.__new__(bybit_client_mod.BybitClient)
bc_spot.exchange = FakeCcxtCancelAll()
bc_spot._default_type = "spot"
bc_spot.cancel_all("BTC/USDT")
ok("cancel_all em spot chama a exchange 2x (ordens comuns + tpslOrder)",
   len(bc_spot.exchange.calls) == 2, str(bc_spot.exchange.calls))
ok("cancel_all em spot inclui uma chamada com orderFilter=tpslOrder (cancela o stop real)",
   ("BTC/USDT", {"orderFilter": "tpslOrder"}) in bc_spot.exchange.calls,
   str(bc_spot.exchange.calls))
ok("cancel_all em spot também cancela ordens comuns (categoria default, sem filtro)",
   ("BTC/USDT", {}) in bc_spot.exchange.calls, str(bc_spot.exchange.calls))

bc_swap = bybit_client_mod.BybitClient.__new__(bybit_client_mod.BybitClient)
bc_swap.exchange = FakeCcxtCancelAll()
bc_swap._default_type = "swap"
bc_swap.cancel_all("BTC/USDT")
ok("cancel_all em perp/swap NAO duplica chamada (tpslOrder é conceito só de spot)",
   len(bc_swap.exchange.calls) == 1, str(bc_swap.exchange.calls))


# ---------- 17. executor: protect_size cobre o saldo REAL creditado (não só o teórico) ----------
# Achado 19/07, visto AO VIVO: o preço do fill de ETH veio melhor que o do
# sinal (mercado caiu entre o sinal e a execução) — a compra por CUSTO em
# USDT creditou mais ETH que o size teórico (1,08310 real vs 1,07305
# teórico). O clamp antigo (min(size, saldo_total_da_carteira)) sempre
# escolhia o menor, deixando ~0,01 ETH real sem proteção nenhuma. O fix mede
# o saldo ANTES e DEPOIS da compra e protege a DIFERENÇA — que também é
# imune a saldo alheio pré-existente (dust de outra origem), porque esse
# dust aparece nas duas fotos e se cancela na subtração.
class FakeSpotFillFavoravel(FakeLiveOk):
    def __init__(self, saldo_alheio=0.0):
        super().__init__()
        self._free_base_calls = 0
        self.saldo_alheio = saldo_alheio

    def create_order(self, symbol, side, amount, order_type="market", price=None, params=None):
        self.calls.append(("create_order", side, amount, dict(params or {}), price))
        return {"id": f"o{len(self.calls)}"}

    def fetch_free_base(self, symbol):
        self._free_base_calls += 1
        if self._free_base_calls == 1:
            return self.saldo_alheio  # foto ANTES da compra
        # foto DEPOIS: dust pré-existente + o que a compra creditou de fato
        # (1% A MAIS que o teórico — fill favorável, preço melhor que o sinal)
        return self.saldo_alheio + d_spot.position_size * 1.01

    def amount_to_precision(self, symbol, amount):
        return round(amount, 8)

    def set_stop_loss(self, symbol, side, amount, stop):
        self.calls.append(("set_stop_loss", stop, amount))
        return {"id": "sl1"}

    def set_take_profit(self, symbol, side, amount, tp):
        self.calls.append(("set_take_profit", tp, amount))
        return {"id": "tp1"}


AUDIT.unlink(missing_ok=True)
fsf = FakeSpotFillFavoravel(saldo_alheio=0.0)
Executor(fsf, dry_run=False, market_type="spot").execute(sig_spot, d_spot)
stops_fav = [c for c in fsf.calls if c[0] == "set_stop_loss"]
esperado_fav = round(d_spot.position_size * 1.01, 8)
ok("fill favoravel (preco melhor que o sinal): protege o saldo REAL recebido, nao so o teorico",
   len(stops_fav) == 1 and abs(stops_fav[0][2] - esperado_fav) < 1e-8,
   f"protegido={stops_fav[0][2] if stops_fav else '-'} esperado={esperado_fav} "
   f"teorico={d_spot.position_size}")

AUDIT.unlink(missing_ok=True)
fsf2 = FakeSpotFillFavoravel(saldo_alheio=5.0)  # dust alheio grande, de outra origem
Executor(fsf2, dry_run=False, market_type="spot").execute(sig_spot, d_spot)
stops_dust = [c for c in fsf2.calls if c[0] == "set_stop_loss"]
ok("saldo alheio pre-existente (dust) NAO e absorvido na protecao (so a diferenca desta entrada)",
   len(stops_dust) == 1 and abs(stops_dust[0][2] - esperado_fav) < 1e-8,
   f"protegido={stops_dust[0][2] if stops_dust else '-'} esperado={esperado_fav}")


class FakeSpotSemLeituraPre(FakeSpot):
    """fetch_free_base falha só na 1ª chamada (pré-entrada) — sem essa foto,
    não dá pra isolar o que é desta entrada do que já estava na carteira, e
    o clamp cai no comportamento conservador antigo (nunca protege mais que
    o size teórico)."""

    def fetch_free_base(self, symbol):
        self._free_base_calls += 1
        if self._free_base_calls == 1:
            raise RuntimeError("network blip (simulado)")
        return d_spot.position_size * self.FREE_FRAC


AUDIT.unlink(missing_ok=True)
fsn = FakeSpotSemLeituraPre()
Executor(fsn, dry_run=False, market_type="spot").execute(sig_spot, d_spot)
stops_sem_pre = [c for c in fsn.calls if c[0] == "set_stop_loss"]
ok("sem leitura de saldo PRE-entrada: cai no clamp conservador antigo (min(size, saldo_pos))",
   len(stops_sem_pre) == 1 and abs(stops_sem_pre[0][2] - clamp) < 1e-12,
   f"protegido={stops_sem_pre[0][2] if stops_sem_pre else '-'}")


# ---------- 17b. executor: reconfirma saldo antes de declarar sem protecao ----------
# Achado ao vivo em 21/07 (watchdog agendado pegou): 3x naked_position_close_failed
# numa rajada de reentrada rapida ETH/BTC (compra->stop em ~60-70s, repetido).
# A leitura de fetch_free_base logo apos a compra as vezes saia igual a
# free_before (diff=0), fazendo o executor desistir de proteger/fechar SEM
# nunca reconfirmar o saldo real — o "nunca posicao nua" tinha um furo: se
# aquela leitura tivesse vindo atrasada/racy (a compra creditou base de
# verdade, so nao tinha assentado ainda), a posicao ficaria nua sem o codigo
# perceber. Fix: ate 2 tentativas em spot, reconfirmando fetch_free_base
# antes de desistir.
class FakeSpotSaldoAtrasado(FakeLiveOk):
    """1a leitura pos-compra sai igual a free_before (saldo "atrasado",
    ainda nao assentou na exchange) — a reconfirmacao (2a leitura) mostra o
    saldo real. O stop deve armar na 2a tentativa, nunca desistir na 1a."""

    def __init__(self):
        super().__init__()
        self._free_base_calls = 0

    def create_order(self, symbol, side, amount, order_type="market", price=None, params=None):
        self.calls.append(("create_order", side, amount, dict(params or {}), price))
        return {"id": f"o{len(self.calls)}"}

    def fetch_free_base(self, symbol):
        self._free_base_calls += 1
        if self._free_base_calls <= 2:
            # chamada 1 (free_before) e chamada 2 (1a leitura pos-compra):
            # mesmo valor -> diff 0, saldo "atrasado" na exchange
            return 0.0
        # chamada 3 (reconfirmacao): saldo ja assentou de verdade
        return d_spot.position_size * 0.999

    def amount_to_precision(self, symbol, amount):
        return round(amount, 8)

    def set_stop_loss(self, symbol, side, amount, stop):
        self.calls.append(("set_stop_loss", stop, amount))
        return {"id": "sl1"}

    def set_take_profit(self, symbol, side, amount, tp):
        self.calls.append(("set_take_profit", tp, amount))
        return {"id": "tp1"}


AUDIT.unlink(missing_ok=True)
fsa = FakeSpotSaldoAtrasado()
Executor(fsa, dry_run=False, market_type="spot").execute(sig_spot, d_spot)
stops_atrasado = [c for c in fsa.calls if c[0] == "set_stop_loss"]
vendas_atrasado = [c for c in fsa.calls if c[0] == "create_order" and c[1] == "sell"]
esperado_atrasado = round(d_spot.position_size * 0.999, 8)
ev = [json.loads(l) for l in AUDIT.read_text(encoding="utf-8").splitlines()]
ok("saldo atrasado na 1a leitura: reconfirma e arma o stop na 2a tentativa (nunca desiste sem reconfirmar)",
   len(stops_atrasado) == 1 and abs(stops_atrasado[0][2] - esperado_atrasado) < 1e-8
   and not vendas_atrasado
   and len([e for e in ev if e["event"] == "naked_position_close_failed"]) == 0,
   f"stops={stops_atrasado} vendas={vendas_atrasado}")


class FakeSpotSaldoZeroConfirmado(FakeLiveOk):
    """Duas leituras pos-compra CONFIRMAM 0 de verdade (sem race nenhuma) —
    o retry nao pode inventar protecao nem tentar vender o que nao existe;
    precisa continuar declarando naked_position_close_failed corretamente."""

    def __init__(self):
        super().__init__()
        self._free_base_calls = 0

    def create_order(self, symbol, side, amount, order_type="market", price=None, params=None):
        self.calls.append(("create_order", side, amount, dict(params or {}), price))
        return {"id": f"o{len(self.calls)}"}

    def fetch_free_base(self, symbol):
        self._free_base_calls += 1
        return 0.0  # free_before, 1a leitura e reconfirmacao: sempre zero

    def amount_to_precision(self, symbol, amount):
        return round(amount, 8)

    def set_stop_loss(self, symbol, side, amount, stop):
        raise RuntimeError("nao deveria ser chamado com protect_size 0")


AUDIT.unlink(missing_ok=True)
fsz = FakeSpotSaldoZeroConfirmado()
try:
    Executor(fsz, dry_run=False, market_type="spot").execute(sig_spot, d_spot)
    esc_z = False
except RuntimeError:
    esc_z = True
ev = [json.loads(l) for l in AUDIT.read_text(encoding="utf-8").splitlines()]
ok("saldo zero CONFIRMADO em 2 leituras: nao inventa protecao, declara naked_position_close_failed",
   esc_z and not any(c[0] == "set_stop_loss" for c in fsz.calls)
   and len([e for e in ev if e["event"] == "naked_position_close_failed"]) == 1
   and fsz._free_base_calls == 3,
   f"calls={fsz._free_base_calls}")


# ---------- 18. executor: entry_price confirma via fetch_order antes de usar o preco do sinal ----------
# Achado 19/07, visto AO VIVO duas vezes (BTC e ETH): o ccxt as vezes nao
# devolve average/price na resposta de CRIACAO da ordem a mercado, e o
# fallback pro preco do sinal pode divergir >1% do fill real (o preco se
# move entre o sinal e a execucao). Em vez de aceitar essa aproximacao
# direto, o executor agora tenta confirmar o preco REAL reconsultando a
# propria ordem (fetch_order) antes de cair no preco do sinal.
class FakeSpotEntryFillConfirmavel(FakeLiveOk):
    REAL_FILL = 101.5  # diferente do entry_price do sinal (100.0, sig_spot)

    def __init__(self):
        super().__init__()
        self._free_base_calls = 0

    def create_order(self, symbol, side, amount, order_type="market", price=None, params=None):
        self.calls.append(("create_order", side, amount, dict(params or {}), price))
        return {"id": "entry-1"}  # sem average/price, igual ao comportamento real visto

    def fetch_order(self, order_id, symbol):
        self.calls.append(("fetch_order", order_id, symbol))
        return {"average": self.REAL_FILL, "status": "closed"}

    def fetch_free_base(self, symbol):
        self._free_base_calls += 1
        if self._free_base_calls == 1:
            return 0.0
        return d_spot.position_size * 0.999

    def amount_to_precision(self, symbol, amount):
        return round(amount, 8)

    def set_stop_loss(self, symbol, side, amount, stop):
        self.calls.append(("set_stop_loss", stop, amount))
        return {"id": "sl1"}

    def set_take_profit(self, symbol, side, amount, tp):
        self.calls.append(("set_take_profit", tp, amount))
        return {"id": "tp1"}


AUDIT.unlink(missing_ok=True)
fec = FakeSpotEntryFillConfirmavel()
Executor(fec, dry_run=False, market_type="spot").execute(sig_spot, d_spot)
ev18a = [json.loads(l) for l in AUDIT.read_text(encoding="utf-8").splitlines()]
oe18a = [e for e in ev18a if e["event"] == "order_executed"]
ok("entry_price sem average/price na criacao: confirma via fetch_order (nao usa o preco do sinal)",
   len(oe18a) == 1 and oe18a[0]["entry_price"] == FakeSpotEntryFillConfirmavel.REAL_FILL,
   f"entry_price auditado={oe18a[0]['entry_price'] if oe18a else '-'}")


class FakeSpotEntrySemConfirmacao(FakeSpotEntryFillConfirmavel):
    """fetch_order tambem falha (ex.: rate limit) -- cai no fallback antigo
    (preco do sinal), nao trava nem inventa numero."""

    def fetch_order(self, order_id, symbol):
        raise RuntimeError("rate limit (simulado)")


AUDIT.unlink(missing_ok=True)
fesc = FakeSpotEntrySemConfirmacao()
Executor(fesc, dry_run=False, market_type="spot").execute(sig_spot, d_spot)
ev18b = [json.loads(l) for l in AUDIT.read_text(encoding="utf-8").splitlines()]
oe18b = [e for e in ev18b if e["event"] == "order_executed"]
ok("fetch_order tambem falha: cai no fallback do preco do sinal (nunca trava, nunca inventa)",
   len(oe18b) == 1 and oe18b[0]["entry_price"] == sig_spot.entry_price,
   f"entry_price auditado={oe18b[0]['entry_price'] if oe18b else '-'}")


# ---------- 19. executor: stop/TP re-ancorados no preco REAL do fill (nao no preco do sinal) ----------
# Achado 20/07, visto AO VIVO num loop de reentrada real: stop_price/
# take_profit vem da estrategia calculados em cima do preco do ULTIMO
# CANDLE FECHADO (signal.entry_price) -- se o preco real se mover ate a
# execucao (ficou ~565 USDT de diferenca numa janela de ~2s ao vivo, logo
# apos um TP disparar), o TP calculado no preco velho podia ficar ABAIXO do
# proprio fill real: a posicao abria ja "no alvo", fechava no ciclo seguinte
# por centavos, e a taxa de ida+volta virava prejuizo liquido -- repetiu 3x
# seguidas ao vivo ate um kill switch manual interromper. Corrigido: desloca
# stop_price e take_profit pela MESMA distancia entre o preco do sinal e o
# fill real (preserva a distancia de risco que o RiskManager usou pra
# dimensionar, so re-centralizada no preco que realmente aconteceu).
class FakeSpotFillComDrift(FakeLiveOk):
    REAL_FILL = 101.5  # 1.5 acima do entry_price do sinal (100.0, sig_spot)

    def __init__(self):
        super().__init__()
        self._free_base_calls = 0

    def create_order(self, symbol, side, amount, order_type="market", price=None, params=None):
        self.calls.append(("create_order", side, amount, dict(params or {}), price))
        return {"id": "entry-drift"}  # sem average/price

    def fetch_order(self, order_id, symbol):
        return {"average": self.REAL_FILL, "status": "closed"}

    def fetch_free_base(self, symbol):
        self._free_base_calls += 1
        if self._free_base_calls == 1:
            return 0.0
        return d_spot.position_size * 0.999

    def amount_to_precision(self, symbol, amount):
        return round(amount, 8)

    def set_stop_loss(self, symbol, side, amount, stop):
        self.calls.append(("set_stop_loss", stop, amount))
        return {"id": "sl-drift"}

    def set_take_profit(self, symbol, side, amount, tp):
        self.calls.append(("set_take_profit", tp, amount))
        return {"id": "tp-drift"}


AUDIT.unlink(missing_ok=True)
fsd = FakeSpotFillComDrift()
Executor(fsd, dry_run=False, market_type="spot").execute(sig_spot, d_spot)
drift19 = FakeSpotFillComDrift.REAL_FILL - sig_spot.entry_price
esperado_stop19 = d_spot.stop_price + drift19
esperado_tp19 = sig_spot.take_profit + drift19
stops19 = [c for c in fsd.calls if c[0] == "set_stop_loss"]
ok("stop re-ancorado no fill real (desloca pela mesma distancia sinal->fill)",
   len(stops19) == 1 and abs(stops19[0][1] - esperado_stop19) < 1e-9,
   f"stop_armado={stops19[0][1] if stops19 else '-'} esperado={esperado_stop19}")

ev19 = [json.loads(l) for l in AUDIT.read_text(encoding="utf-8").splitlines()]
oe19 = [e for e in ev19 if e["event"] == "order_executed"]
tps19 = [e for e in ev19 if e["event"] == "take_profit_skipped"]
ok("TP re-ancorado no fill real: sempre do lado lucrativo da entrada real",
   len(tps19) == 1 and abs(tps19[0]["take_profit"] - esperado_tp19) < 1e-9
   and esperado_tp19 > FakeSpotFillComDrift.REAL_FILL,
   f"tp_alvo={tps19[0]['take_profit'] if tps19 else '-'} esperado={esperado_tp19} "
   f"fill={FakeSpotFillComDrift.REAL_FILL}")
ok("order_executed audita stop_price/take_profit ja re-ancorados (nao o do sinal)",
   len(oe19) == 1 and abs(oe19[0]["stop_price"] - esperado_stop19) < 1e-9
   and abs(oe19[0]["take_profit"] - esperado_tp19) < 1e-9)

prot19 = protection_state.load().get("BTC/USDT", {})
ok("protection_state salva o TP re-ancorado (nao o do sinal) para a checagem de saida",
   abs(prot19.get("take_profit", 0) - esperado_tp19) < 1e-9)


# ---------- 20. saida por SINAL + trailing stop (20/07/2026) ----------
from src.strategy.deterministic import StrategyParams  # noqa: E402
from src.strategy.signal import TRAIL_MIN_STEP_PCT, Signal as Signal20  # noqa: E402


def make_candles_trend(n_up=100, n_down=40, start=100.0, up=0.004, down=-0.005,
                       start_ts=1_752_000_000_000, tf_ms=900_000):
    rows, price = [], start
    for i in range(n_up + n_down):
        drift = up if i < n_up else down
        new = price * (1 + drift)
        high, low = max(price, new) * 1.001, min(price, new) * 0.999
        rows.append([start_ts + i * tf_ms, price, high, low, new, 10.0])
        price = new
    return pd.DataFrame(rows, columns=["ts", "open", "high", "low", "close", "volume"])


# 20a. should_exit da estrategia deterministica
df_down = compute_indicators(make_candles_trend(n_up=60, n_down=80))
snap_down = snapshot_from_df("BTC/USDT:USDT", "15m", df_down, funding_rate=None)
ok("pre-requisito 20a: cenario de baixa tem EMA_fast<EMA_slow",
   snap_down.indicators["ema_fast"] < snap_down.indicators["ema_slow"])
pos_long = {"entry_price": 100.0, "stop_price": 95.0, "take_profit": None,
            "size": 1.0, "side": "long"}
ok("should_exit com exit_on_signal DESLIGADO (default) devolve None mesmo com EMA descruzada",
   DeterministicStrategy("daytrade").should_exit(snap_down, pos_long) is None)
strat_exit = DeterministicStrategy("daytrade", params=StrategyParams(exit_on_signal=True))
ok("should_exit LIGADO + long + EMA descruzada -> manda sair (racional preenchido)",
   bool(strat_exit.should_exit(snap_down, pos_long)))
ok("should_exit LIGADO + long + EMA ainda cruzada pra cima -> None (mantem posicao)",
   strat_exit.should_exit(snap, pos_long) is None)
ok("wants_exit_signals: False no default, True com exit_on_signal",
   not DeterministicStrategy("daytrade").wants_exit_signals
   and strat_exit.wants_exit_signals)


# 20b. engine: saida por sinal fecha a posicao (mecanica identica ao TP)
class FakeStratQuerSair:
    wants_exit_signals = True

    def should_exit(self, snap, position):
        return "teste: tendencia virou, sair"


AUDIT.unlink(missing_ok=True)
protection_state.clear_protection("BTC/USDT")
protection_state.set_protection("BTC/USDT", entry_price=100.0, take_profit=110.0,
                                stop_price=95.0, size=0.066047, stop_id="sl-se",
                                profile="daytrade")
engine_mod.BybitClient = FakeSpotExit
FakeSpotExit.PRICE = 105.0  # ABAIXO do TP (110) — so a saida por sinal dispara
eng_se = engine_mod.Engine(dry_run=False)
eng_se._open_symbols = {"BTC/USDT"}
eng_se._strategies["daytrade"] = FakeStratQuerSair()
_orig_build_snapshot = engine_mod.build_snapshot
engine_mod.build_snapshot = lambda *a, **k: None  # fake nao usa o snapshot
try:
    eng_se._check_spot_exits()
finally:
    engine_mod.build_snapshot = _orig_build_snapshot
vendas_se = [c for c in eng_se.client.calls if c[0] == "create_order" and c[1] == "sell"]
ev20b = [json.loads(l) for l in AUDIT.read_text(encoding="utf-8").splitlines()]
tc20b = [e for e in ev20b if e["event"] == "trade_closed"]
ok("saida por sinal VENDE de verdade (cancel_all + sell a mercado)",
   len(vendas_se) == 1 and any(c[0] == "cancel_all" for c in eng_se.client.calls))
ok("saida por sinal audita signal_exit_executed com o racional",
   len([e for e in ev20b if e["event"] == "signal_exit_executed"
        and e.get("rationale")]) == 1)
ok("trade_closed da saida por sinal: reason=signal_exit, pnl correto",
   len(tc20b) == 1 and tc20b[0]["reason"] == "signal_exit"
   and tc20b[0]["exit_price_source"] == "exit_order_fill"
   and abs(tc20b[0]["pnl_usdt"] - (105.0 - 100.0) * 0.066047) < 1e-9,
   str(tc20b))
ok("protecao limpa apos a saida por sinal", "BTC/USDT" not in protection_state.load())

# 20b2. TP tem prioridade sobre a saida por sinal no mesmo ciclo
AUDIT.unlink(missing_ok=True)
protection_state.set_protection("BTC/USDT", entry_price=100.0, take_profit=110.0,
                                stop_price=95.0, size=0.066047, stop_id="sl-se2",
                                profile="daytrade")
FakeSpotExit.PRICE = 112.0  # ACIMA do TP — os dois disparariam
eng_se2 = engine_mod.Engine(dry_run=False)
eng_se2._open_symbols = {"BTC/USDT"}
eng_se2._strategies["daytrade"] = FakeStratQuerSair()
engine_mod.build_snapshot = lambda *a, **k: None
try:
    eng_se2._check_spot_exits()
finally:
    engine_mod.build_snapshot = _orig_build_snapshot
ev20b2 = [json.loads(l) for l in AUDIT.read_text(encoding="utf-8").splitlines()]
ok("TP e sinal no mesmo ciclo: executa TP (melhor preco), nunca a saida por sinal",
   len([e for e in ev20b2 if e["event"] == "take_profit_executed"]) == 1
   and not [e for e in ev20b2 if e["event"] == "signal_exit_executed"])

# 20b3. DRY_RUN da saida por sinal nunca toca a exchange
AUDIT.unlink(missing_ok=True)
protection_state.set_protection("BTC/USDT", entry_price=100.0, take_profit=110.0,
                                stop_price=95.0, size=0.066047, stop_id="sl-se3",
                                profile="daytrade")
FakeSpotExit.PRICE = 105.0
eng_se3 = engine_mod.Engine(dry_run=True)
eng_se3._open_symbols = {"BTC/USDT"}
eng_se3._strategies["daytrade"] = FakeStratQuerSair()
engine_mod.build_snapshot = lambda *a, **k: None
try:
    eng_se3._check_spot_exits()
finally:
    engine_mod.build_snapshot = _orig_build_snapshot
ev20b3 = [json.loads(l) for l in AUDIT.read_text(encoding="utf-8").splitlines()]
ok("DRY_RUN da saida por sinal: audita dry_run_signal_exit e nao toca a exchange",
   len([e for e in ev20b3 if e["event"] == "dry_run_signal_exit"]) == 1
   and not any(c[0] in ("cancel_all", "create_order") for c in eng_se3.client.calls))
ok("DRY_RUN da saida por sinal: protecao intacta",
   "BTC/USDT" in protection_state.load())

# 20b4. posicao sem profile (aberta antes da feature) nao tem saida por sinal
AUDIT.unlink(missing_ok=True)
protection_state.set_protection("BTC/USDT", entry_price=100.0, take_profit=110.0,
                                stop_price=95.0, size=0.066047, stop_id="sl-se4")
FakeSpotExit.PRICE = 105.0
eng_se4 = engine_mod.Engine(dry_run=False)
eng_se4._open_symbols = {"BTC/USDT"}
eng_se4._strategies["daytrade"] = FakeStratQuerSair()


def _snapshot_nao_deveria_ser_chamado(*a, **k):
    raise AssertionError("build_snapshot chamado pra posicao sem profile")


engine_mod.build_snapshot = _snapshot_nao_deveria_ser_chamado
try:
    eng_se4._check_spot_exits()
finally:
    engine_mod.build_snapshot = _orig_build_snapshot
ok("posicao sem profile: degrada pro comportamento antigo (sem venda, sem snapshot)",
   not any(c[0] == "create_order" for c in eng_se4.client.calls))
protection_state.clear_protection("BTC/USDT")


# 20c. trailing stop no engine
class FakeSpotTrail(FakeSpotExit):
    # ordens condicionais reais "vigentes" na exchange — o move do trailing
    # consulta isto antes de cancelar (guard contra arquivo stale, 20/07)
    REAL_STOP_ORDERS = []

    def set_stop_loss(self, symbol, side, amount, stop):
        self.calls.append(("set_stop_loss", side, amount, stop))
        return {"id": f"sl-new-{len(self.calls)}"}

    def fetch_open_stop_orders(self, symbol):
        self.calls.append(("fetch_open_stop_orders", symbol))
        return list(FakeSpotTrail.REAL_STOP_ORDERS)


AUDIT.unlink(missing_ok=True)
protection_state.set_protection("BTC/USDT", entry_price=100.0, take_profit=None,
                                stop_price=90.0, size=0.066047, stop_id="sl-tr",
                                profile="daytrade", trailing=True,
                                trail_distance=10.0, peak_price=100.0)
engine_mod.BybitClient = FakeSpotTrail
# ATENCAO: o fetch_ticker do fake le FakeSpotExit.PRICE (classe-base) — setar
# PRICE na subclasse criaria um atributo que ninguem le (bug real do 1º draft
# desta secao: o preco efetivo ficava o do teste anterior).
FakeSpotExit.PRICE = 120.0  # pico avanca 20 -> stop deveria ir a 110
eng_tr = engine_mod.Engine(dry_run=False)
eng_tr._open_symbols = {"BTC/USDT"}
eng_tr._check_spot_exits()
stops_tr = [c for c in eng_tr.client.calls if c[0] == "set_stop_loss"]
prot_tr = protection_state.load().get("BTC/USDT", {})
ev20c = [json.loads(l) for l in AUDIT.read_text(encoding="utf-8").splitlines()]
ok("trailing: cancela o stop antigo e arma novo em pico - distancia (120-10=110)",
   any(c[0] == "cancel_all" for c in eng_tr.client.calls)
   and len(stops_tr) == 1 and abs(stops_tr[0][3] - 110.0) < 1e-9, str(stops_tr))
ok("trailing: audita trailing_stop_moved com old/new/pico",
   len([e for e in ev20c if e["event"] == "trailing_stop_moved"
        and abs(e["old_stop"] - 90.0) < 1e-9 and abs(e["new_stop"] - 110.0) < 1e-9
        and abs(e["peak_price"] - 120.0) < 1e-9]) == 1)
ok("trailing: protecao persistida com stop/pico/stop_id novos",
   abs(prot_tr.get("stop_price", 0) - 110.0) < 1e-9
   and abs(prot_tr.get("peak_price", 0) - 120.0) < 1e-9
   and prot_tr.get("stop_id") != "sl-tr", str(prot_tr))

# 20c2. passo minimo: avanco pequeno persiste o pico mas NAO mexe na exchange
AUDIT.unlink(missing_ok=True)
protection_state.set_protection("BTC/USDT", entry_price=100.0, take_profit=None,
                                stop_price=90.0, size=0.066047, stop_id="sl-tr2",
                                profile="daytrade", trailing=True,
                                trail_distance=10.0, peak_price=100.0)
FakeSpotExit.PRICE = 100.05  # novo stop 90.05 < 90 + 100.05*0.1% — sem re-arm
eng_tr2 = engine_mod.Engine(dry_run=False)
eng_tr2._open_symbols = {"BTC/USDT"}
eng_tr2._check_spot_exits()
prot_tr2 = protection_state.load().get("BTC/USDT", {})
ok("trailing passo minimo: nenhuma ordem tocada, pico persistido, stop intacto",
   not any(c[0] in ("cancel_all", "set_stop_loss") for c in eng_tr2.client.calls)
   and abs(prot_tr2.get("peak_price", 0) - 100.05) < 1e-9
   and abs(prot_tr2.get("stop_price", 0) - 90.0) < 1e-9, str(prot_tr2))

# 20c3. DRY_RUN do trailing nunca toca a exchange nem o arquivo
AUDIT.unlink(missing_ok=True)
protection_state.set_protection("BTC/USDT", entry_price=100.0, take_profit=None,
                                stop_price=90.0, size=0.066047, stop_id="sl-tr3",
                                profile="daytrade", trailing=True,
                                trail_distance=10.0, peak_price=100.0)
FakeSpotExit.PRICE = 120.0
eng_tr3 = engine_mod.Engine(dry_run=True)
eng_tr3._open_symbols = {"BTC/USDT"}
eng_tr3._check_spot_exits()
prot_tr3 = protection_state.load().get("BTC/USDT", {})
ev20c3 = [json.loads(l) for l in AUDIT.read_text(encoding="utf-8").splitlines()]
ok("DRY_RUN trailing: audita dry_run_trailing_stop_move, exchange e arquivo intactos",
   len([e for e in ev20c3 if e["event"] == "dry_run_trailing_stop_move"]) == 1
   and not any(c[0] in ("cancel_all", "set_stop_loss") for c in eng_tr3.client.calls)
   and abs(prot_tr3.get("stop_price", 0) - 90.0) < 1e-9
   and abs(prot_tr3.get("peak_price", 0) - 100.0) < 1e-9)


# 20c4. falha ao armar o stop NOVO -> re-arma o ANTIGO (nunca posicao nua)
class FakeSpotTrailFalhaNovo(FakeSpotTrail):
    def set_stop_loss(self, symbol, side, amount, stop):
        self.calls.append(("set_stop_loss", side, amount, stop))
        if abs(stop - 110.0) < 1e-9:
            raise RuntimeError("stop novo rejeitado (simulado)")
        return {"id": "sl-old-rearm"}


AUDIT.unlink(missing_ok=True)
protection_state.set_protection("BTC/USDT", entry_price=100.0, take_profit=None,
                                stop_price=90.0, size=0.066047, stop_id="sl-tr4",
                                profile="daytrade", trailing=True,
                                trail_distance=10.0, peak_price=100.0)
engine_mod.BybitClient = FakeSpotTrailFalhaNovo
FakeSpotExit.PRICE = 120.0
eng_tr4 = engine_mod.Engine(dry_run=False)
eng_tr4._open_symbols = {"BTC/USDT"}
eng_tr4._check_spot_exits()
stops_tr4 = [c for c in eng_tr4.client.calls if c[0] == "set_stop_loss"]
prot_tr4 = protection_state.load().get("BTC/USDT", {})
ev20c4 = [json.loads(l) for l in AUDIT.read_text(encoding="utf-8").splitlines()]
ok("trailing falhou no stop novo: re-arma o ANTIGO e audita trailing_move_failed_stop_rearmed",
   len(stops_tr4) == 2 and abs(stops_tr4[1][3] - 90.0) < 1e-9
   and len([e for e in ev20c4 if e["event"] == "trailing_move_failed_stop_rearmed"]) == 1
   and prot_tr4.get("stop_id") == "sl-old-rearm"
   and abs(prot_tr4.get("stop_price", 0) - 90.0) < 1e-9, str(stops_tr4))
protection_state.clear_protection("BTC/USDT")
engine_mod.BybitClient = FakeSpotExit


# 20e. executor: entrada com trailing salva protecao mesmo SEM take-profit
class FakeSpotEntradaTrailing(FakeSpotFillComDrift):
    pass


AUDIT.unlink(missing_ok=True)
sig_trail = Signal20(symbol="BTC/USDT", direction=Direction.LONG, conviction=0.8,
                     entry_price=100.0, stop_price=95.0, take_profit=None,
                     profile="daytrade", rationale="teste trailing", trailing=True)
fst = FakeSpotEntradaTrailing()
Executor(fst, dry_run=False, market_type="spot").execute(sig_trail, d_spot)
prot20e = protection_state.load().get("BTC/USDT", {})
ev20e = [json.loads(l) for l in AUDIT.read_text(encoding="utf-8").splitlines()]
drift20e = FakeSpotFillComDrift.REAL_FILL - sig_trail.entry_price  # 1.5
stop20e = d_spot.stop_price + drift20e  # 96.5
ok("entrada trailing: protecao salva SEM take_profit (arquivo e o registro da posicao)",
   prot20e.get("trailing") is True and prot20e.get("take_profit") is None
   and abs(prot20e.get("trail_distance", 0) - (FakeSpotFillComDrift.REAL_FILL - stop20e)) < 1e-9
   and abs(prot20e.get("peak_price", 0) - FakeSpotFillComDrift.REAL_FILL) < 1e-9
   and prot20e.get("profile") == "daytrade", str(prot20e))
ok("entrada trailing: sem take_profit_skipped (nao ha alvo fixo pra pular)",
   not [e for e in ev20e if e["event"] == "take_profit_skipped"])
ok("entrada trailing: order_executed audita trailing/trail_distance/peak",
   len([e for e in ev20e if e["event"] == "order_executed"
        and e.get("trailing") is True and e.get("profile") == "daytrade"]) == 1)
protection_state.clear_protection("BTC/USDT")


# 20f. backtester: saida por sinal (decisao no candle fechado, fill no open seguinte)
df_bt_exit = make_candles_trend(n_up=100, n_down=60)
strat_bt_exit = DeterministicStrategy("daytrade", params=StrategyParams(
    exit_on_signal=True, atr_stop_mult=60.0))  # stop longe: so o sinal fecha
res_bt_exit = Backtester(cfg, strategy=strat_bt_exit).run("BTC/USDT:USDT", "15m", df_bt_exit)
saidas_sinal = [t for t in res_bt_exit.trades if t.exit_reason == "signal_exit"]
ok("backtester: saida por sinal fecha trade quando a EMA descruza",
   len(saidas_sinal) >= 1,
   f"reasons={[t.exit_reason for t in res_bt_exit.trades]}")
strat_bt_off = DeterministicStrategy("daytrade", params=StrategyParams(atr_stop_mult=60.0))
res_bt_off = Backtester(cfg, strategy=strat_bt_off).run("BTC/USDT:USDT", "15m", df_bt_exit)
ok("backtester: com exit_on_signal desligado NAO existe saida por sinal (default preservado)",
   not [t for t in res_bt_off.trades if t.exit_reason == "signal_exit"],
   f"reasons={[t.exit_reason for t in res_bt_off.trades]}")

# 20g. backtester: trailing stop trava lucro na reversao. A subida precisa
# ser ONDULADA (sobe 0,9%, desce 0,5%, alternando): subida com perdas de
# menos trava o RSI acima de 70 (ex.: 3-sobe-1-desce fixa RSI=78,9) e a
# estrategia veta todo long — nenhum trade chegaria a "trailar" (bug real
# dos 2 primeiros drafts deste teste). Este padrao da RSI~64 e ainda sobe
# +0,4% a cada 2 candles; o trailing (1,5x ATR ~2% do preco) sobrevive aos
# vales de -0,5% e so e atingido na reversao final de -0,6%/candle.
# 27/07/2026: desde que trailing e TP fixo passaram a conviver (secao 29),
# alguns destes trades fecham via take_profit ANTES da reversao final (o
# rally bate o alvo tp_rr antes de qualquer vale forte) — os que sobram ate
# a reversao ainda fecham via trailing_stop, cobertos pelas duas ultimas
# asserções abaixo.
def make_candles_wavy(n_up=120, n_down=60, start=100.0,
                      start_ts=1_752_000_000_000, tf_ms=900_000):
    rows, price = [], start
    for i in range(n_up + n_down):
        if i < n_up:
            drift = 0.009 if i % 2 == 0 else -0.005
        else:
            drift = -0.006
        new = price * (1 + drift)
        high, low = max(price, new) * 1.001, min(price, new) * 0.999
        rows.append([start_ts + i * tf_ms, price, high, low, new, 10.0])
        price = new
    return pd.DataFrame(rows, columns=["ts", "open", "high", "low", "close", "volume"])


df_bt_trail = make_candles_wavy()
strat_bt_trail = DeterministicStrategy("daytrade", params=StrategyParams(trailing=True))
res_bt_trail = Backtester(cfg, strategy=strat_bt_trail).run("BTC/USDT:USDT", "15m", df_bt_trail)
trail_trades = [t for t in res_bt_trail.trades if t.trailing]
trail_stops = [t for t in trail_trades if t.exit_reason == "trailing_stop"]
ok("backtester: trades com trailing TAMBEM tem take-profit fixo calculado "
   "(27/07/2026 — antes virava None; trailing e TP fixo convivem agora, ver secao 29)",
   len(trail_trades) >= 1 and all(t.take_profit is not None for t in trail_trades),
   f"n={len(trail_trades)}")
ok("backtester: TP fixo captura o rally (exit_reason=take_profit com lucro) "
   "MESMO com trailing tambem ligado nesta mesma posicao (27/07/2026)",
   any(t.exit_reason == "take_profit" and t.exit_price > t.entry_price
       for t in trail_trades),
   f"exits={[(t.exit_reason, round(t.exit_price or 0, 2), round(t.entry_price, 2)) for t in trail_trades]}")
ok("backtester: nenhum fechamento de trailing PIOR que o stop inicial (nunca desce)",
   all(t.exit_price >= t.entry_price - t.trail_distance - 1e-6 for t in trail_stops),
   f"n_stops={len(trail_stops)}")

# Reset do kill switch REAL (27/07/2026): o backtest acima instancia um
# RiskManager de verdade (Backtester.__init__) sem isolar
# KILL_SWITCH_STATE_PATH — com trailing+TP fixo convivendo (fix desta mesma
# sessao), este cenario ondulado agora fecha trades o suficiente pra cruzar
# o limite de drawdown diario (3,20% >= 3,0%) e disparar o kill switch DE
# VERDADE, persistindo halted=True em state/kill_switch_state.json. Sem
# este reset, o proximo teste que instancia RiskManager/Backtester (secao
# 21e) herdava esse halt real e todo APROVADO virava veto silencioso —
# achado ao rodar a suite completa pela primeira vez apos o fix de
# trailing+TP (regressao real, nao intermitente: reproduz sempre).
from src.risk import kill_switch_state as _ks_reset20g  # noqa: E402
_ks_reset20g.save(False, "")


# ---------- 21. correcoes da revisao adversarial de 20/07 ----------
# 21a. backfill recupera posicao TRAILING (take_profit=None por design)
AUDIT.unlink(missing_ok=True)
from src.logger import audit as _audit21  # noqa: E402
_audit21("order_executed", symbol="TRAIL/USDT", side="buy", size=1.0,
         protect_size=0.999, entry_price=100.0, stop_price=95.0,
         take_profit=None, entry_id="e-tr", stop_id="sl-tr-bf", tp_id=None,
         profile="daytrade", trailing=True, trail_distance=5.0,
         peak_price=100.0, testnet=True)
bf21 = protection_state.backfill_from_audit("TRAIL/USDT")
ok("backfill recupera posicao trailing SEM take_profit (antes: irrecuperavel)",
   bf21 is not None and bf21.get("trailing") is True
   and bf21.get("trail_distance") == 5.0 and bf21.get("profile") == "daytrade"
   and bf21.get("take_profit") is None, str(bf21))

# 21b. saldo zero com stop AINDA ativo: NAO fabrica trade_closed nem apaga protecao
AUDIT.unlink(missing_ok=True)
protection_state.set_protection("BTC/USDT", entry_price=100.0, take_profit=110.0,
                                stop_price=95.0, size=0.066047, stop_id="sl-vivo",
                                profile="daytrade")
engine_mod.BybitClient = FakeSpotExit
FakeSpotExit.PRICE = 112.0
_free_orig = FakeSpotExit.FREE_BASE
FakeSpotExit.FREE_BASE = 0.0  # saldo preso: cancel_all "falhou" em liberar
# fetch_order default do fake devolve status="open" -> stop AINDA ativo
eng_21b = engine_mod.Engine(dry_run=False)
eng_21b._open_symbols = {"BTC/USDT"}
eng_21b._check_spot_exits()
FakeSpotExit.FREE_BASE = _free_orig
ev21b = [json.loads(l) for l in AUDIT.read_text(encoding="utf-8").splitlines()]
ok("saldo zero + stop ativo: audita exit_failed, ZERO trade_closed fabricado",
   len([e for e in ev21b if e["event"] == "take_profit_exit_failed"]) == 1
   and not [e for e in ev21b if e["event"] == "trade_closed"], str(ev21b))
ok("saldo zero + stop ativo: protecao MANTIDA (posicao segue viva e rastreada)",
   "BTC/USDT" in protection_state.load())
protection_state.clear_protection("BTC/USDT")

# 21b2. MESMO cenario de 21b, mas pelo caminho do TRAILING MOVE (nao do TP) —
# achado/correcao da auditoria de 27/07/2026: fix #27 nunca tinha sido
# propagado pra _update_trailing_stop. Saldo zero apos cancel_all() com o
# stop real AINDA ativo (cancel_all provavelmente falhou) NAO pode fabricar
# trade_closed nem apagar a protecao.
AUDIT.unlink(missing_ok=True)
protection_state.set_protection("BTC/USDT", entry_price=100.0, take_profit=None,
                                stop_price=90.0, size=0.066047, stop_id="sl-tr5",
                                profile="daytrade", trailing=True,
                                trail_distance=10.0, peak_price=100.0)
engine_mod.BybitClient = FakeSpotTrail
FakeSpotTrail.REAL_STOP_ORDERS = []
FakeSpotExit.PRICE = 120.0  # pico avanca -> tentaria mover o stop de 90 pra 110
_free_orig21b2 = FakeSpotExit.FREE_BASE
FakeSpotExit.FREE_BASE = 0.0  # saldo preso: cancel_all "falhou" em liberar
# fetch_order default do FakeSpotExit devolve status="open" -> stop AINDA ativo
eng_tr5 = engine_mod.Engine(dry_run=False)
eng_tr5._open_symbols = {"BTC/USDT"}
eng_tr5._check_spot_exits()
FakeSpotExit.FREE_BASE = _free_orig21b2
ev21b2 = [json.loads(l) for l in AUDIT.read_text(encoding="utf-8").splitlines()]
ok("trailing: saldo zero + stop AINDA ativo apos cancel_all -> NAO fabrica trade_closed",
   not [e for e in ev21b2 if e["event"] == "trade_closed"], str(ev21b2))
ok("trailing: saldo zero + stop ainda ativo -> audita trailing_move_stop_still_active",
   len([e for e in ev21b2 if e["event"] == "trailing_move_stop_still_active"]) == 1,
   str([e["event"] for e in ev21b2]))
ok("trailing: saldo zero + stop ainda ativo -> protecao MANTIDA (posicao segue rastreada)",
   "BTC/USDT" in protection_state.load())
protection_state.clear_protection("BTC/USDT")

# 21b3. Mesmo cenario, mas o stop CONFIRMADAMENTE nao esta mais ativo (fechamento
# concorrente real) -> continua reconciliando normalmente como antes (a
# correcao acima NAO pode quebrar o caminho de fechamento genuino).


class FakeSpotTrailFechamentoReal(FakeSpotTrail):
    def fetch_order(self, order_id, symbol):
        self.calls.append(("fetch_order", order_id, symbol))
        return {"id": order_id, "status": "closed", "filled": 0.066047,
                "average": 89.5, "price": 89.5}


AUDIT.unlink(missing_ok=True)
protection_state.set_protection("BTC/USDT", entry_price=100.0, take_profit=None,
                                stop_price=90.0, size=0.066047, stop_id="sl-tr6",
                                profile="daytrade", trailing=True,
                                trail_distance=10.0, peak_price=100.0)
engine_mod.BybitClient = FakeSpotTrailFechamentoReal
FakeSpotTrail.REAL_STOP_ORDERS = []
FakeSpotExit.PRICE = 120.0
_free_orig21b3 = FakeSpotExit.FREE_BASE
FakeSpotExit.FREE_BASE = 0.0
eng_tr6 = engine_mod.Engine(dry_run=False)
eng_tr6._open_symbols = {"BTC/USDT"}
eng_tr6._check_spot_exits()
FakeSpotExit.FREE_BASE = _free_orig21b3
ev21b3 = [json.loads(l) for l in AUDIT.read_text(encoding="utf-8").splitlines()]
ok("trailing: stop CONFIRMADAMENTE fechado -> reconcilia normalmente (trade_closed real)",
   len([e for e in ev21b3 if e["event"] == "trade_closed"]) == 1, str(ev21b3))
ok("trailing: stop confirmado fechado -> protecao limpa",
   "BTC/USDT" not in protection_state.load())

# 21c. trailing exit-now: preco ja rompeu o nivel trailed -> vende a mercado
AUDIT.unlink(missing_ok=True)
protection_state.set_protection("BTC/USDT", entry_price=100.0, take_profit=None,
                                stop_price=90.0, size=0.066047, stop_id="sl-en",
                                profile="daytrade", trailing=True,
                                trail_distance=10.0, peak_price=120.0)
engine_mod.BybitClient = FakeSpotTrail
FakeSpotTrail.REAL_STOP_ORDERS = []
FakeSpotExit.PRICE = 105.0  # nivel trailed = 120-10 = 110 > 105 -> rompido
eng_21c = engine_mod.Engine(dry_run=False)
eng_21c._open_symbols = {"BTC/USDT"}
eng_21c._check_spot_exits()
ev21c = [json.loads(l) for l in AUDIT.read_text(encoding="utf-8").splitlines()]
tc21c = [e for e in ev21c if e["event"] == "trade_closed"]
ok("trailing rompido entre ciclos: vende a mercado (nao tenta armar stop acima do preco)",
   len([c for c in eng_21c.client.calls if c[0] == "create_order" and c[1] == "sell"]) == 1
   and not [c for c in eng_21c.client.calls if c[0] == "set_stop_loss"],
   str(eng_21c.client.calls))
ok("trailing rompido: trade_closed com reason=trailing_stop (paridade com o replay)",
   len(tc21c) == 1 and tc21c[0]["reason"] == "trailing_stop", str(tc21c))
ok("trailing rompido: protecao limpa", "BTC/USDT" not in protection_state.load())

# 21d. arquivo stale: gatilho REAL na exchange e mais alto -> cura em vez de rebaixar
AUDIT.unlink(missing_ok=True)
protection_state.set_protection("BTC/USDT", entry_price=100.0, take_profit=None,
                                stop_price=90.0, size=0.066047, stop_id="sl-stale",
                                profile="daytrade", trailing=True,
                                trail_distance=10.0, peak_price=100.0)
FakeSpotTrail.REAL_STOP_ORDERS = [{"id": "sl-real", "triggerPrice": 105.95}]
FakeSpotExit.PRICE = 116.0  # new_stop=106; real=105.95 -> melhora < passo minimo
eng_21d = engine_mod.Engine(dry_run=False)
eng_21d._open_symbols = {"BTC/USDT"}
eng_21d._check_spot_exits()
prot21d = protection_state.load().get("BTC/USDT", {})
ok("arquivo stale: NAO cancela o stop real mais alto (cura o registro e aborta o move)",
   not any(c[0] in ("cancel_all", "set_stop_loss") for c in eng_21d.client.calls)
   and abs(prot21d.get("stop_price", 0) - 105.95) < 1e-9
   and prot21d.get("stop_id") == "sl-real", str(prot21d))
FakeSpotTrail.REAL_STOP_ORDERS = []
protection_state.clear_protection("BTC/USDT")
engine_mod.BybitClient = FakeSpotExit

# 21e. backtester re-ancorado: R:R dos trades e EXATAMENTE o tp_rr do sinal
res21e = Backtester(cfg, profile="daytrade").run("BTC/USDT:USDT", "15m", make_candles(n=1200))
rr_ok = all(
    abs((t.take_profit - t.entry_price) / (t.entry_price - t.stop_price) - 2.0) < 1e-9
    for t in res21e.trades if t.take_profit
)
ok("backtester re-ancora stop/TP no fill (R:R efetivo == tp_rr exato, paridade com o live)",
   len(res21e.trades) > 0 and rr_ok,
   f"n={len(res21e.trades)}")

# ---------- 22. persistência do kill switch através de restarts (21/07) ----------
from src.risk import kill_switch_state  # noqa: E402
from src.supervision.state_reader import StateReader  # noqa: E402

# 22a. sem arquivo persistido -> RiskManager novo inicia NÃO halted (default
# de sempre) e já GRAVA o arquivo (fonte de verdade pro supervisor existir
# desde o primeiro boot com este código).
kill_switch_state.STATE_PATH.unlink(missing_ok=True)
rm22a = RiskManager(cfg, environment="testnet")
ok("kill switch: sem arquivo persistido, RiskManager novo inicia NÃO halted",
   rm22a.halted is False)
ok("kill switch: RiskManager grava o arquivo mesmo quando não halted",
   kill_switch_state.STATE_PATH.exists())

# 22b. trip_kill_switch persiste em disco; um RiskManager NOVO (simulando um
# restart do processo) recupera o halt em vez de nascer livre.
rm22b = RiskManager(cfg, environment="testnet")
rm22b.trip_kill_switch("teste: drawdown simulado")
persisted_b = kill_switch_state.load()
ok("kill switch: trip_kill_switch persiste halted=True + motivo",
   persisted_b["halted"] is True and "drawdown simulado" in persisted_b["reason"])
rm22b_novo = RiskManager(cfg, environment="testnet")
ok("kill switch: RiskManager NOVO após restart recupera o halt (não reseta sozinho)",
   rm22b_novo.halted is True and "drawdown simulado" in rm22b_novo._kill_reason)

# 22c. reset_kill_switch (sempre manual) persiste em disco; um RiskManager
# NOVO enxerga o reset e não volta a halted por conta própria.
rm22b_novo.reset_kill_switch()
persisted_c = kill_switch_state.load()
ok("kill switch: reset_kill_switch persiste halted=False", persisted_c["halted"] is False)
rm22c_novo = RiskManager(cfg, environment="testnet")
ok("kill switch: RiskManager NOVO após reset inicia livre (não revive o halt)",
   rm22c_novo.halted is False)

# 22d. arquivo corrompido -> tratado como NÃO halted, nunca derruba o motor
# (mesmo padrão de protection_state.load(), achado da revisão de 18/07).
kill_switch_state.STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
kill_switch_state.STATE_PATH.write_bytes(b"\xff\xfe\x00{ISTO NAO E JSON VALIDO")
rm22d = RiskManager(cfg, environment="testnet")
ok("kill switch: arquivo corrompido tratado como NÃO halted (nunca derruba o motor)",
   rm22d.halted is False)

# 22e. state_reader.read_halt_status() (o que o MCP trader_halt_status expõe)
# usa o arquivo persistido como fonte PRIMÁRIA — decisivo pro bug real de
# 20-21/07: sem isto, o status ficava preso no último kill_switch_tripped da
# trilha pra sempre, mesmo com o motor livre de novo após um restart.
kill_switch_state.save(True, "teste: reader deve confiar no arquivo")
reader22e = StateReader(client=None, market_type="spot", symbols=[])
status22e = reader22e.read_halt_status()
ok("state_reader.read_halt_status(): reporta halted=True direto do arquivo persistido",
   status22e["halted"] is True
   and status22e["last_reason"] == "teste: reader deve confiar no arquivo")

kill_switch_state.save(False, "")
status22e2 = reader22e.read_halt_status()
ok("state_reader.read_halt_status(): reporta halted=False direto do arquivo persistido",
   status22e2["halted"] is False)

# ---------- 23. cooldown por símbolo após stops (21/07, 3 níveis 25/07) ----------
# Achado pelo watchdog agendado: whipsaw real no ETH/USDT (5 stops em 8
# minutos) porque nada impedia reentrada imediata no mesmo sinal (candle de
# 15m ainda não tinha virado). Investigado (comparação testnet vs mainnet):
# o ETH real não se moveu, foi anomalia de dado da testnet — mas a lacuna de
# arquitetura (sem cooldown) é real independente da causa.
#
# ENDURECIDO em 25/07/2026 (Lucas viu o motor tomar 1 stop e reentrar quase
# na hora, questionou se não devia "acalmar" primeiro): `consecutive_stops_trigger`
# virou 1 (cada stop isolado já pausa, não precisa mais de 2 seguidos) e a
# escalada ganhou um 3º nível: 1º stop do dia -> 30min, 2º -> 60min, 3º em
# diante -> 24h (auto-libera sozinho no prazo, ou reset manual antes via
# `RiskManager.reset_cooldown`/MCP `trader_reset_cooldown`).
from src.risk import cooldown_state  # noqa: E402

# 23a. sem histórico -> aprova normalmente
cooldown_state.STATE_PATH.unlink(missing_ok=True)
rm23a = RiskManager(cfg, environment="testnet")
d23a = rm23a.evaluate(sig, state, funding_rate=None, data_age_sec=0)
ok("cooldown: sem histórico, sinal aprovado normalmente", d23a.approved, d23a.reason)

# 23b. 1 ÚNICO stop já ACIONA o cooldown (gatilho é 1 agora, não 2) -> 30min
AUDIT.unlink(missing_ok=True)
rm23a.record_trade_close(sig.symbol, "stop_loss")
d23b = rm23a.evaluate(sig, state, funding_rate=None, data_age_sec=0)
ok("cooldown: 1 único stop já aciona o cooldown, próxima entrada vetada",
   not d23b.approved and "Cooldown" in d23b.reason, d23b.reason)
ev = [json.loads(l) for l in AUDIT.read_text(encoding="utf-8").splitlines()] if AUDIT.exists() else []
ok("cooldown_triggered auditado com os campos certos (30min, acionamento nº1)",
   any(e["event"] == "cooldown_triggered" and e["symbol"] == sig.symbol
       and e["cooldown_minutes"] == 30 and e["trigger_number_today"] == 1 for e in ev))

# 23c. cooldown ativo bloqueia SÓ o símbolo em cooldown, outro símbolo livre
sig_outro_cd = Signal(symbol="ETH/USDT:USDT", direction=Direction.LONG, conviction=0.8,
                      entry_price=100.0, stop_price=95.0, take_profit=110.0,
                      profile="daytrade", rationale="teste outro simbolo")
d23c = rm23a.evaluate(sig_outro_cd, state, funding_rate=None, data_age_sec=0)
ok("cooldown: outro símbolo NÃO é afetado", d23c.approved, d23c.reason)

# 23d. persiste através de um "restart" simulado (RiskManager novo)
rm23d = RiskManager(cfg, environment="testnet")
d23d = rm23d.evaluate(sig, state, funding_rate=None, data_age_sec=0)
ok("cooldown: sobrevive a um 'restart' simulado (RiskManager novo)",
   not d23d.approved and "Cooldown" in d23d.reason, d23d.reason)

# 23e. escalonamento: 2º stop do dia (mesmo símbolo) -> 60min
cooldown_state.STATE_PATH.unlink(missing_ok=True)
AUDIT.unlink(missing_ok=True)
rm23e = RiskManager(cfg, environment="testnet")
rm23e.record_trade_close(sig.symbol, "stop_loss")  # 1º stop do dia -> 30min
persisted_e1 = dict(cooldown_state.load()[sig.symbol])
rm23e.record_trade_close(sig.symbol, "stop_loss")  # 2º stop do dia -> 60min
persisted_e2 = dict(cooldown_state.load()[sig.symbol])
ok("cooldown: 2º stop do dia escala pra 60min (1º foi 30min)",
   persisted_e1["triggers_today"] == 1 and persisted_e2["triggers_today"] == 2,
   f"e1={persisted_e1} e2={persisted_e2}")
ev = [json.loads(l) for l in AUDIT.read_text(encoding="utf-8").splitlines()] if AUDIT.exists() else []
triggers_cd_e = [e for e in ev if e["event"] == "cooldown_triggered" and e["symbol"] == sig.symbol]
ok("cooldown_triggered audita 30min no 1º e 60min no 2º stop do dia",
   len(triggers_cd_e) == 2 and triggers_cd_e[0]["cooldown_minutes"] == 30
   and triggers_cd_e[1]["cooldown_minutes"] == 60, str(triggers_cd_e))

# 23f. 3º stop do dia (mesmo símbolo) -> 24h (1440min)
rm23e.record_trade_close(sig.symbol, "stop_loss")  # 3º stop do dia -> 1440min
persisted_f3 = dict(cooldown_state.load()[sig.symbol])
ok("cooldown: 3º stop do dia escala pra 1440min (24h)",
   persisted_f3["triggers_today"] == 3, str(persisted_f3))
ev = [json.loads(l) for l in AUDIT.read_text(encoding="utf-8").splitlines()] if AUDIT.exists() else []
triggers_cd_f = [e for e in ev if e["event"] == "cooldown_triggered" and e["symbol"] == sig.symbol]
ok("cooldown_triggered audita 1440min no 3º acionamento do dia",
   len(triggers_cd_f) == 3 and triggers_cd_f[2]["cooldown_minutes"] == 1440,
   str(triggers_cd_f))

# 23g. fechamento != stop_loss (ex. take_profit) zera consecutive_stops —
# checado direto no estado interno (com o gatilho em 1, um stop isolado já
# aciona e a própria linha de "acionou" também zera consecutive_stops;
# testar isolado aqui garante que o reset por TP continua correto mesmo se
# o gatilho um dia voltar a subir de 1 pra N).
cooldown_state.STATE_PATH.unlink(missing_ok=True)
rm23g = RiskManager(cfg, environment="testnet")
rm23g._cooldown[sig.symbol] = {"consecutive_stops": 3, "cooldown_until": None,
                                "triggers_date": None, "triggers_today": 0}
rm23g.record_trade_close(sig.symbol, "take_profit")
ok("cooldown: fechamento por take_profit zera consecutive_stops",
   rm23g._cooldown[sig.symbol]["consecutive_stops"] == 0,
   str(rm23g._cooldown[sig.symbol]))

# 23h. cooldown expira naturalmente -> volta a aprovar
# IMPORTANTE: o RiskManager só lê state/cooldown_state.json na inicialização
# (self._cooldown fica em memória depois disso, mesmo padrão do kill
# switch) — reescrever o ARQUIVO não muda uma instância já viva. Pra
# simular "o tempo passou" na mesma instância (o que acontece de verdade no
# motor rodando continuamente), o teste tem que mexer no dict em memória
# diretamente, não só no arquivo.
cooldown_state.STATE_PATH.unlink(missing_ok=True)
rm23h = RiskManager(cfg, environment="testnet")
rm23h.record_trade_close(sig.symbol, "stop_loss")
rm23h._cooldown[sig.symbol]["cooldown_until"] = "2020-01-01T00:00:00+00:00"
d23h = rm23h.evaluate(sig, state, funding_rate=None, data_age_sec=0)
ok("cooldown: expira naturalmente e volta a aprovar", d23h.approved, d23h.reason)

# 23i. arquivo corrompido -> tratado como vazio, nunca derruba o motor
cooldown_state.STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
cooldown_state.STATE_PATH.write_bytes(b"\xff\xfe\x00{ISTO NAO E JSON VALIDO")
rm23i = RiskManager(cfg, environment="testnet")
d23i = rm23i.evaluate(sig, state, funding_rate=None, data_age_sec=0)
ok("cooldown: arquivo corrompido tratado como vazio (nunca derruba o motor)",
   d23i.approved, d23i.reason)

# 23j. sem a chave "cooldown" no YAML -> feature desligada (nunca veta)
cooldown_state.STATE_PATH.unlink(missing_ok=True)
cfg_sem_cooldown = copy.deepcopy(cfg)
del cfg_sem_cooldown["cooldown"]
rm23j = RiskManager(cfg_sem_cooldown, environment="testnet")
rm23j.record_trade_close(sig.symbol, "stop_loss")
d23j = rm23j.evaluate(sig, state, funding_rate=None, data_age_sec=0)
ok("cooldown: sem a chave no YAML, feature fica desligada (nunca veta)",
   d23j.approved, d23j.reason)

# 23k. reset manual (reset_cooldown) libera um cooldown ativo ANTES do prazo
# natural — pedido deliberado via MCP (control.json action=reset_cooldown),
# mesma filosofia do reset do kill switch: nunca automático.
cooldown_state.STATE_PATH.unlink(missing_ok=True)
AUDIT.unlink(missing_ok=True)
rm23k = RiskManager(cfg, environment="testnet")
rm23k.record_trade_close(sig.symbol, "stop_loss")  # aciona cooldown de 30min
d23k_before = rm23k.evaluate(sig, state, funding_rate=None, data_age_sec=0)
ok("cooldown 23k: cooldown ativo antes do reset manual",
   not d23k_before.approved and "Cooldown" in d23k_before.reason, d23k_before.reason)
rm23k.reset_cooldown(sig.symbol)
d23k_after = rm23k.evaluate(sig, state, funding_rate=None, data_age_sec=0)
ok("cooldown: reset manual libera antes do prazo natural",
   d23k_after.approved, d23k_after.reason)
ev = [json.loads(l) for l in AUDIT.read_text(encoding="utf-8").splitlines()] if AUDIT.exists() else []
ok("cooldown_reset auditado com o símbolo certo",
   any(e["event"] == "cooldown_reset" and e["symbol"] == sig.symbol for e in ev))

# 23l. reset manual num símbolo SEM cooldown ativo é no-op seguro (não
# quebra nada, não audita evento fantasma).
cooldown_state.STATE_PATH.unlink(missing_ok=True)
AUDIT.unlink(missing_ok=True)
rm23l = RiskManager(cfg, environment="testnet")
rm23l.reset_cooldown(sig.symbol)  # nunca houve cooldown -> só loga aviso
d23l = rm23l.evaluate(sig, state, funding_rate=None, data_age_sec=0)
ok("cooldown: reset sem cooldown ativo não quebra nada", d23l.approved, d23l.reason)
ev = [json.loads(l) for l in AUDIT.read_text(encoding="utf-8").splitlines()] if AUDIT.exists() else []
ok("cooldown: reset sem cooldown ativo NÃO audita cooldown_reset (evento fantasma)",
   not any(e["event"] == "cooldown_reset" for e in ev))

cooldown_state.STATE_PATH.unlink(missing_ok=True)

# ---------- 24. state_reader: corte por LINHA BRUTA perdia trade_closed reais
# atrás de ruído (21/07/2026) ----------
# Achado numa sessão real: trader_realized_pnl (MCP, limit=500 default)
# reportou "1 trade fechado, -5,81 USDT" quando a trilha real tinha 20
# trades (+233,95 USDT). Causa: `_read_audit(limit=N)` cortava as últimas N
# LINHAS BRUTAS do arquivo ANTES de filtrar por tipo de evento — com a
# trilha dominada por `signal_vetoed`/`symbol_skipped` repetitivos, o corte
# por linha empurrava `trade_closed` (evento raro) pra fora da janela.
# Corrigido: lê o arquivo inteiro, filtra por tipo, só corta depois.
from src.supervision.state_reader import StateReader as _SR24  # noqa: E402


def _linha24(evt: dict) -> str:
    return json.dumps(evt, ensure_ascii=False)


# 24a. 3 trade_closed no INÍCIO do arquivo, seguidos de 600 linhas de ruído
# (signal_vetoed) -- com limit=500 (default do MCP), a versão antiga via só
# ruído e reportava 0 trades; a corrigida acha os 3 de qualquer forma.
linhas24a = []
for i in range(3):
    linhas24a.append(_linha24({
        "ts": f"2026-01-01T00:00:0{i}+00:00", "event": "trade_closed",
        "symbol": "BTC/USDT", "side": "long", "entry_price": 100.0,
        "exit_price": 105.0, "size": 1.0, "pnl_usdt": 5.0 * (i + 1),
        "reason": "take_profit", "exit_price_source": "tp_order_fill",
    }))
for i in range(600):
    linhas24a.append(_linha24({
        "ts": f"2026-01-01T01:{i // 60:02d}:{i % 60:02d}+00:00",
        "event": "signal_vetoed", "symbol": "ETH/USDT", "profile": "daytrade",
        "reason": "Sinal FLAT — sem entrada",
    }))
AUDIT.write_text("\n".join(linhas24a) + "\n", encoding="utf-8")
reader24 = _SR24(client=None, market_type="spot", symbols=[])
res24a = reader24.realized_pnl(limit=500)
ok("realized_pnl: nao perde trade_closed atras de ruido repetitivo (bug real 21/07, corrigido)",
   res24a["closed_trades"] == 3 and abs(res24a["realized_pnl_usdt"] - 30.0) < 1e-9,
   str(res24a))

# 24b. limit corta pelos N trade_closed MAIS RECENTES (nao pelas ultimas
# linhas cruas) -- com os 3 trades acima (pnl 5, 10, 15), limit=2 deve
# devolver os 2 ULTIMOS (10 + 15 = 25), nao as ultimas linhas (que sao ruido).
res24b = reader24.realized_pnl(limit=2)
ok("realized_pnl(limit=N): corta pelos N trade_closed mais recentes, nao pelas ultimas linhas",
   res24b["closed_trades"] == 2 and abs(res24b["realized_pnl_usdt"] - 25.0) < 1e-9,
   str(res24b))

# 24c. recent_decisions nao fica cego quando ha muitos eventos NAO-interessantes
# (ex.: symbol_skipped, que nem entra no filtro) entre o evento raro e o fim
# do arquivo -- o heuristico antigo (limit*3 linhas cruas) podia devolver
# lista vazia mesmo com um order_executed real mais atras.
linhas24c = [_linha24({
    "ts": "2026-01-01T00:00:00+00:00", "event": "order_executed",
    "symbol": "BTC/USDT", "side": "buy", "size": 1.0, "entry_price": 100.0,
})]
for i in range(100):
    linhas24c.append(_linha24({
        "ts": f"2026-01-01T01:{i // 60:02d}:{i % 60:02d}+00:00",
        "event": "symbol_skipped", "symbol": "BTC/USDT", "profile": "daytrade",
        "reason": "posição já aberta ou entrada aprovada neste ciclo",
    }))
AUDIT.write_text("\n".join(linhas24c) + "\n", encoding="utf-8")
res24c = reader24.recent_decisions(limit=5)
ok("recent_decisions: acha evento interessante raro mesmo atras de muito ruido nao-interessante",
   len(res24c) == 1 and res24c[0]["event"] == "order_executed",
   str(res24c))

AUDIT.unlink(missing_ok=True)

# ---------- 25. isolamento de kill_switch_state.json/cooldown_state.json
# via env var (21/07/2026) ----------
# Achado: o backtester oficial (src/backtest/backtester.py) instancia um
# RiskManager DE VERDADE, que por padrão lê E GRAVA em
# state/kill_switch_state.json e state/cooldown_state.json -- os MESMOS
# arquivos que o motor ao vivo usa. Um trip/cooldown SIMULADO num backtest
# podia sobrescrever o estado REAL silenciosamente (o audit correspondente
# ia pro AUDIT_PATH isolado do backtest, nunca pra logs/audit.jsonl -- nada
# explicaria pro Lucas por que o motor ao vivo passou a rejeitar entradas).
# Corrigido com o mesmo padrão de AUDIT_PATH (fix #14, 15/07): override por
# env var, lido ANTES do import de src.* -- run_backtest.py,
# run_walkforward.py e research/parity_check.py já setam os dois.
ok("kill_switch_state.STATE_PATH: sem override, aponta pro arquivo real (comportamento de sempre)",
   kill_switch_state.STATE_PATH == ROOT / "state" / "kill_switch_state.json")
ok("cooldown_state.STATE_PATH: sem override, aponta pro arquivo real (comportamento de sempre)",
   cooldown_state.STATE_PATH == ROOT / "state" / "cooldown_state.json")

# 22f/23m. Isolamento por AMBIENTE (achado da auditoria de 27/07/2026,
# transição pra mainnet): sem override, o nome também depende de
# ENVIRONMENT -- mainnet mantém o canônico (testado acima, já bate porque
# .env real desta sessão está em mainnet); testnet ganha um arquivo
# dedicado. STATE_PATH é resolvido uma vez no import do módulo, então para
# testar o outro ramo chamamos _resolve_state_path() direto, sem mexer no
# STATE_PATH já cacheado (usado por todos os testes 22/23 acima e abaixo).
_env_antes = os.environ.get("ENVIRONMENT")
os.environ["ENVIRONMENT"] = "testnet"
try:
    ok("kill_switch_state: em testnet, sem override, usa arquivo DEDICADO (nao o canonico de mainnet)",
       kill_switch_state._resolve_state_path() == ROOT / "state" / "kill_switch_state-testnet.json")
    ok("cooldown_state: em testnet, sem override, usa arquivo DEDICADO (nao o canonico de mainnet)",
       cooldown_state._resolve_state_path() == ROOT / "state" / "cooldown_state-testnet.json")
finally:
    if _env_antes is None:
        os.environ.pop("ENVIRONMENT", None)
    else:
        os.environ["ENVIRONMENT"] = _env_antes
# (KILL_SWITCH_STATE_PATH/COOLDOWN_STATE_PATH override vencendo em qualquer
# ambiente já é coberto pelos testes de isolamento de subprocesso logo
# abaixo, seção 25 -- não duplicado aqui.)

import subprocess  # noqa: E402

_ks25_iso = ROOT / "state" / "kill_switch_state-test25.json"
_cd25_iso = ROOT / "state" / "cooldown_state-test25.json"
_ks25_iso.unlink(missing_ok=True)
_cd25_iso.unlink(missing_ok=True)
_real_ks_antes = _KS_FILE.read_bytes() if _KS_FILE.exists() else None
_real_cd_antes = _CD_FILE.read_bytes() if _CD_FILE.exists() else None

_env25 = dict(os.environ)
_env25["KILL_SWITCH_STATE_PATH"] = str(_ks25_iso)
_env25["COOLDOWN_STATE_PATH"] = str(_cd25_iso)
# Isola TAMBÉM o AUDIT_PATH (não só os arquivos de estado) — sem isto, o
# trip_kill_switch/record_trade_close do subprocesso grava eventos reais
# em logs/audit.jsonl (defesa em profundidade: o backup/restore do topo
# deste arquivo já cobre isso quando a suíte roda inteira e termina limpo,
# mas um script isolado/interrompido no meio não tem essa rede de segurança
# — foi exatamente o erro real cometido na sessão que motivou este teste).
_env25["AUDIT_PATH"] = str(ROOT / "logs" / "audit-test25.jsonl")
_codigo25 = (
    "import sys; sys.path.insert(0, '.')\n"
    "from config.settings import load_risk_config\n"
    "from src.risk.risk_manager import RiskManager\n"
    "cfg = load_risk_config()\n"
    "rm = RiskManager(cfg, environment='testnet')\n"
    "rm.trip_kill_switch('teste subprocesso isolado - secao 25')\n"
    "rm.record_trade_close('BTC/USDT:USDT', 'stop_loss')\n"
    "rm.record_trade_close('BTC/USDT:USDT', 'stop_loss')\n"
)
_proc25 = subprocess.run([sys.executable, "-c", _codigo25], cwd=str(ROOT),
                          env=_env25, capture_output=True, text=True, timeout=60)
ok("subprocesso isolado (env var setada ANTES do import) roda sem erro",
   _proc25.returncode == 0, _proc25.stderr[-500:] if _proc25.returncode else "")
ok("com env var setada, o RiskManager real GRAVA no arquivo ISOLADO (nao no real)",
   _ks25_iso.exists() and "teste subprocesso isolado" in _ks25_iso.read_text(encoding="utf-8")
   and _cd25_iso.exists())
_real_ks_depois = _KS_FILE.read_bytes() if _KS_FILE.exists() else None
_real_cd_depois = _CD_FILE.read_bytes() if _CD_FILE.exists() else None
ok("arquivo REAL kill_switch_state.json continua intocado (isolamento funcionou)",
   _real_ks_antes == _real_ks_depois)
ok("arquivo REAL cooldown_state.json continua intocado (isolamento funcionou)",
   _real_cd_antes == _real_cd_depois)

_ks25_iso.unlink(missing_ok=True)
_cd25_iso.unlink(missing_ok=True)
(ROOT / "logs" / "audit-test25.jsonl").unlink(missing_ok=True)


# ---------- 26. restart automático do processo (supervisor.py, 22/07/2026)
# ----------
# Item 6b do charter ("processo supervisionado com restart automático") —
# a metade "alerta" já existia (watchdog agendado, 21/07); esta é a metade
# "restart". A política em si (RestartPolicy/backoff_seconds) é pura —
# testável com timestamps sintéticos, sem spawnar processo nenhum (o
# supervisor de verdade spawna main.py via subprocess, fora do escopo de um
# teste offline).
pol26 = RestartPolicy(max_restarts=3, window_sec=100.0)
ok("RestartPolicy nova: sem histórico, should_restart aprova",
   pol26.should_restart(0.0) and pol26.attempts_in_window(0.0) == 0)

for i in range(3):
    pol26.record_crash(float(i))
ok("RestartPolicy: 3 crashes dentro do teto (max_restarts=3) ainda aprova restart",
   pol26.should_restart(3.0), str(pol26.attempts_in_window(3.0)))
pol26.record_crash(4.0)
ok("RestartPolicy: 4º crash dentro da janela excede o teto -> recusa",
   not pol26.should_restart(4.0), str(pol26.attempts_in_window(4.0)))

pol26b = RestartPolicy(max_restarts=2, window_sec=50.0)
pol26b.record_crash(0.0)
pol26b.record_crash(10.0)
pol26b.record_crash(20.0)
ok("RestartPolicy: excedeu o teto dentro da janela -> recusa",
   not pol26b.should_restart(20.0))
ok("RestartPolicy: crash antigo (fora da janela) some da contagem -> volta a aprovar",
   pol26b.should_restart(65.0) and pol26b.attempts_in_window(65.0) == 1,
   f"attempts={pol26b.attempts_in_window(65.0)}")

ok("backoff_seconds: tentativa 0 (sem histórico) usa o base",
   backoff_seconds(0, base=10.0, cap=300.0) == 10.0)
ok("backoff_seconds: cresce exponencial (10, 20, 40, 80)",
   [backoff_seconds(a, base=10.0, cap=300.0) for a in (1, 2, 3, 4)] == [10.0, 20.0, 40.0, 80.0])
ok("backoff_seconds: nunca passa do teto",
   backoff_seconds(20, base=10.0, cap=300.0) == 300.0)

import ast  # noqa: E402
_supervisor_src = (ROOT / "supervisor.py").read_text(encoding="utf-8")
try:
    ast.parse(_supervisor_src)
    _supervisor_ok = True
except SyntaxError as exc:  # noqa: BLE001
    _supervisor_ok = False
    print(f"  supervisor.py SyntaxError: {exc}")
ok("supervisor.py: parseia sem erro de sintaxe", _supervisor_ok)


# ---------- 27. BybitDerivativesProvider (decisão #G, implementado 22/07/2026,
# revisado adversarialmente no mesmo dia — 11 achados, todos confirmados e
# corrigidos: gate por decision.strategy=="llm" em engine.py — achado MAIS
# grave, sem ele o provider fazia até 12 chamadas de rede REAIS por ciclo
# mesmo com a estratégia determinística nunca lendo o resultado; isolamento
# por chamada dentro de fetch() [antes uma exceção não tratada em UM
# endpoint apagava os outros dois já bem-sucedidos]; guard contra dict
# "verdadeiro" com todos os campos None [mesma classe dos bugs #20/#27];
# next_funding_rate removido [sempre None nesta versão do ccxt, campo
# morto]; timeframe explícito na chamada [antes dependia dos dois lados
# coincidirem no mesmo default]) ----------
# Contexto de derivativos em tempo real (funding/open interest/long-short
# ratio) direto da Bybit, pra Fase 3 (LLM). Hoje INERTE em produção — não só
# porque decision.strategy=deterministic não lê snap.context, mas porque
# desde a revisão o próprio engine só CONSTRÓI o contexto quando
# decision.strategy=="llm" (ver seção 27c).
class FakeClient27Ok:
    """Captura os símbolos recebidos em vez de `assert` dentro do método —
    achado da revisão: um `assert` aqui, se um dia falhar, sobe sem try/except
    NENHUM (este arquivo não tem guarda global) e aborta o script inteiro
    antes do relatório final, em vez de reportar 1 FAIL isolado como todo
    resto do arquivo faz via `ok(...)`."""

    def __init__(self):
        self.received_symbols = []

    def fetch_derivatives_funding_rate(self, symbol):
        self.received_symbols.append(("funding", symbol))
        return {"funding_rate": -0.0001, "timestamp": "2026-07-22T22:00:00Z"}

    def fetch_open_interest(self, symbol):
        self.received_symbols.append(("oi", symbol))
        return {"open_interest": 53830.16, "timestamp": "2026-07-22T22:00:00Z"}

    def fetch_long_short_ratio(self, symbol, timeframe="1h"):
        self.received_symbols.append(("lsr", symbol, timeframe))
        return {"long_short_ratio": 1.31, "timestamp": "2026-07-22T22:00:00Z"}


prov27 = BybitDerivativesProvider(FakeClient27Ok())
ok("_perp_symbol: spot 'BTC/USDT' vira perpetuo 'BTC/USDT:USDT'",
   prov27._perp_symbol("BTC/USDT") == "BTC/USDT:USDT")
ok("_perp_symbol: ja em formato perpetuo passa direto (nao duplica sufixo)",
   prov27._perp_symbol("BTC/USDT:USDT") == "BTC/USDT:USDT")

res27 = prov27.fetch("BTC/USDT")  # símbolo SPOT — provider deve converter pro perpétuo sozinho
ok("fetch com simbolo spot: consulta o PERPETUO (nao o par spot) nos 3 endpoints",
   res27.get("funding_rate", {}).get("funding_rate") == -0.0001
   and res27.get("open_interest", {}).get("open_interest") == 53830.16
   and res27.get("long_short_ratio", {}).get("long_short_ratio") == 1.31,
   str(res27))
ok("os 3 endpoints receberam o simbolo PERPETUO, nao o spot original",
   all(s[1] == "BTC/USDT:USDT" for s in prov27._client.received_symbols),
   str(prov27._client.received_symbols))
ok("long/short ratio recebe timeframe EXPLICITO '1h' (nao depende de default coincidir)",
   [s for s in prov27._client.received_symbols if s[0] == "lsr"][0][2] == "1h")


class FakeClient27ParcialmenteQuebrado:
    def fetch_derivatives_funding_rate(self, symbol):
        return {"funding_rate": -0.0001}

    def fetch_open_interest(self, symbol):
        return None  # simula falha isolada (rede, símbolo sem derivativo etc.)

    def fetch_long_short_ratio(self, symbol, timeframe="1h"):
        return {"long_short_ratio": 1.31}


res27b = BybitDerivativesProvider(FakeClient27ParcialmenteQuebrado()).fetch("ETH/USDT")
ok("falha isolada em UM endpoint (open_interest=None) nao derruba os outros dois",
   "funding_rate" in res27b and "long_short_ratio" in res27b and "open_interest" not in res27b,
   str(res27b))


class FakeClient27TotalmenteQuebrado:
    def fetch_derivatives_funding_rate(self, symbol):
        return None

    def fetch_open_interest(self, symbol):
        return None

    def fetch_long_short_ratio(self, symbol, timeframe="1h"):
        return None


res27c = BybitDerivativesProvider(FakeClient27TotalmenteQuebrado()).fetch("SOL/USDT")
ok("falha total nos 3 endpoints -> dict vazio (nunca inventa numero)", res27c == {})


class FakeClient27UmLevantaExcecao:
    """Achado da revisão adversarial (severidade média): antes, uma exceção
    NÃO tratada em UM dos 3 clientes (bug futuro no client, não hipótese
    vazia — os 3 hoje sempre capturam a própria falha, mas nada garantia
    isso) apagava os resultados dos OUTROS dois que já tinham vindo certos,
    porque só o ContextAggregator (uma camada acima) tinha try/except.
    Corrigido: fetch() agora isola CADA chamada no próprio try/except."""

    def fetch_derivatives_funding_rate(self, symbol):
        return {"funding_rate": -0.0001}

    def fetch_open_interest(self, symbol):
        raise RuntimeError("bug futuro simulado no client — não deveria escapar, mas nao pode derrubar os irmãos")

    def fetch_long_short_ratio(self, symbol, timeframe="1h"):
        return {"long_short_ratio": 1.31}


res27d = BybitDerivativesProvider(FakeClient27UmLevantaExcecao()).fetch("BTC/USDT")
ok("excecao NAO tratada em UM endpoint nao apaga os outros dois que ja funcionaram",
   "funding_rate" in res27d and "long_short_ratio" in res27d and "open_interest" not in res27d,
   str(res27d))

res27e = BybitDerivativesProvider(FakeEthQuebrado()).fetch("BTC/USDT")  # sem os 3 métodos novos
ok("client SEM os 3 métodos novos (AttributeError nos 3): fetch() nao levanta, devolve vazio",
   res27e == {}, str(res27e))

agg27 = ContextAggregator([DossierOnChainProvider(), BybitDerivativesProvider(FakeClient27Ok())])
res27f = agg27.build("BTC/USDT")
ok("nome do provider ('derivatives') NAO colide com DossierOnChainProvider ('onchain')",
   "derivatives" in res27f and "derivatives" != "onchain"
   and res27f["derivatives"].get("open_interest", {}).get("open_interest") == 53830.16,
   str(list(res27f.keys())))


class ProviderQueExplodeAntesDoTry:
    """Simula uma falha ANTES de qualquer try/except do provider entrar em
    ação (ex.: símbolo malformado) — o único cenário real em que a rede de
    segurança do ContextAggregator ainda é necessária, já que fetch() agora
    isola tudo que roda DEPOIS de _perp_symbol()."""
    name = "derivatives"

    def fetch(self, symbol):
        return symbol.upper()  # symbol=None -> AttributeError, escapa antes de qualquer try


agg27b = ContextAggregator([ProviderQueExplodeAntesDoTry()])
res27g = agg27b.build(None)
ok("ContextAggregator ainda protege contra falha ANTES do try interno do provider (defesa em profundidade)",
   res27g == {"derivatives": {}}, str(res27g))

# ---------- 27h. bybit_client: parsing REAL contra respostas no formato do
# ccxt (não só o client já convertido) — achado da revisão: os testes acima
# só provam a agregação; nunca exercitavam .get("fundingRate")/
# .get("openInterestAmount")/rows[-1] de verdade. Shapes abaixo confirmados
# por sonda ao vivo contra a Bybit mainnet (mercado público) antes de
# escrever o código. ----------
import src.exchange.bybit_client as bybit_client_mod  # noqa: E402


class FakeCcxtDerivativesOk:
    def fetch_funding_rate(self, symbol, params=None):
        return {"fundingRate": -0.0001, "nextFundingRate": None, "fundingDatetime": "2026-07-22T22:00:00Z"}

    def fetch_open_interest(self, symbol, params=None):
        return {"openInterestAmount": 53830.16, "datetime": "2026-07-22T22:00:00Z"}

    def fetch_long_short_ratio_history(self, symbol, timeframe=None, limit=None, params=None):
        return [{"longShortRatio": 1.30, "datetime": "2026-07-22T21:00:00Z"},
                {"longShortRatio": 1.31, "datetime": "2026-07-22T22:00:00Z"}]


bc27 = bybit_client_mod.BybitClient.__new__(bybit_client_mod.BybitClient)
bc27.exchange = FakeCcxtDerivativesOk()
fr27 = bc27.fetch_derivatives_funding_rate("BTC/USDT:USDT")
ok("fetch_derivatives_funding_rate: parseia fundingRate/fundingDatetime reais do ccxt",
   fr27 == {"funding_rate": -0.0001, "timestamp": "2026-07-22T22:00:00Z"}, str(fr27))
ok("fetch_derivatives_funding_rate: next_funding_rate NAO existe mais no retorno (campo morto removido)",
   "next_funding_rate" not in (fr27 or {}))

oi27 = bc27.fetch_open_interest("BTC/USDT:USDT")
ok("fetch_open_interest: parseia openInterestAmount/datetime reais do ccxt",
   oi27 == {"open_interest": 53830.16, "timestamp": "2026-07-22T22:00:00Z"}, str(oi27))

lsr27 = bc27.fetch_long_short_ratio("BTC/USDT:USDT")
ok("fetch_long_short_ratio: usa o ULTIMO ponto do historico (limit=1 pede so 1, mas se vier mais, pega o mais recente)",
   lsr27 == {"long_short_ratio": 1.31, "timestamp": "2026-07-22T22:00:00Z"}, str(lsr27))


class FakeCcxtDerivativesCamposNone:
    """Resposta que NÃO levanta exceção mas também não trouxe o campo —
    cenário real do ccxt (parser devolve a chave com valor None em vez de
    omitir), não hipótese vazia (next_funding_rate é hardcoded None sempre
    nesta versão do ccxt para a Bybit — verificado no pacote instalado)."""

    def fetch_funding_rate(self, symbol, params=None):
        return {"fundingRate": None, "nextFundingRate": None, "fundingDatetime": None}

    def fetch_open_interest(self, symbol, params=None):
        return {"openInterestAmount": None, "datetime": None}

    def fetch_long_short_ratio_history(self, symbol, timeframe=None, limit=None, params=None):
        return [{"longShortRatio": None, "datetime": None}]


bc27n = bybit_client_mod.BybitClient.__new__(bybit_client_mod.BybitClient)
bc27n.exchange = FakeCcxtDerivativesCamposNone()
ok("fetch_derivatives_funding_rate: campo None (nao ausente) -> None, NUNCA dict 'verdadeiro' vazio por dentro",
   bc27n.fetch_derivatives_funding_rate("BTC/USDT:USDT") is None)
ok("fetch_open_interest: campo None -> None (mesmo guard)",
   bc27n.fetch_open_interest("BTC/USDT:USDT") is None)
ok("fetch_long_short_ratio: campo None -> None (mesmo guard)",
   bc27n.fetch_long_short_ratio("BTC/USDT:USDT") is None)


class FakeCcxtDerivativesHistoricoVazio:
    def fetch_long_short_ratio_history(self, symbol, timeframe=None, limit=None, params=None):
        return []


bc27v = bybit_client_mod.BybitClient.__new__(bybit_client_mod.BybitClient)
bc27v.exchange = FakeCcxtDerivativesHistoricoVazio()
ok("fetch_long_short_ratio: historico vazio -> None (nao IndexError)",
   bc27v.fetch_long_short_ratio("BTC/USDT:USDT") is None)


class FakeCcxtDerivativesFalhaRede:
    def fetch_funding_rate(self, symbol, params=None):
        raise RuntimeError("falha de rede simulada")

    def fetch_open_interest(self, symbol, params=None):
        raise RuntimeError("falha de rede simulada")

    def fetch_long_short_ratio_history(self, symbol, timeframe=None, limit=None, params=None):
        raise RuntimeError("falha de rede simulada")


bc27f = bybit_client_mod.BybitClient.__new__(bybit_client_mod.BybitClient)
bc27f.exchange = FakeCcxtDerivativesFalhaRede()
ok("os 3 metodos novos capturam falha de rede e devolvem None (nunca levantam)",
   bc27f.fetch_derivatives_funding_rate("BTC/USDT:USDT") is None
   and bc27f.fetch_open_interest("BTC/USDT:USDT") is None
   and bc27f.fetch_long_short_ratio("BTC/USDT:USDT") is None)

# ---------- 27i. wiring real no Engine + o GATE novo (achado MAIS grave da
# revisão): context.build() só deve rodar quando decision.strategy=="llm".
# Em modo determinístico (o real da produção hoje), o provider de
# derivativos NUNCA deve ser chamado — antes deste fix, era chamado TODO
# ciclo, gastando rede de verdade por um dado 100% descartado. ----------
ok("BybitClient real expõe fetch_derivatives_funding_rate/fetch_open_interest/fetch_long_short_ratio",
   # checa a classe REAL via bybit_client_mod, não engine_mod.BybitClient —
   # este último já foi monkeypatchado pra várias Fakes por seções
   # anteriores deste arquivo e nunca é restaurado entre seções.
   all(hasattr(bybit_client_mod.BybitClient, m) for m in (
       "fetch_derivatives_funding_rate", "fetch_open_interest", "fetch_long_short_ratio")))


class FakeClient27Contador(FakeEthQuebrado):
    """Conta quantas vezes os métodos de derivativos foram chamados — se o
    gate por decision.strategy vazar, este contador sobe."""

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        FakeClient27Contador.chamadas = 0

    def fetch_derivatives_funding_rate(self, symbol):
        FakeClient27Contador.chamadas += 1
        return {"funding_rate": -0.0001, "timestamp": "x"}

    def fetch_open_interest(self, symbol):
        FakeClient27Contador.chamadas += 1
        return {"open_interest": 1.0, "timestamp": "x"}

    def fetch_long_short_ratio(self, symbol, timeframe="1h"):
        FakeClient27Contador.chamadas += 1
        return {"long_short_ratio": 1.0, "timestamp": "x"}


engine_mod.BybitClient = FakeClient27Contador
eng27 = engine_mod.Engine(dry_run=True)  # cfg real do projeto: decision.strategy=deterministic
ok("Engine.context inclui um BybitDerivativesProvider (wiring real, não só o teste isolado)",
   any(isinstance(p, BybitDerivativesProvider) for p in eng27.context.providers))
AUDIT.unlink(missing_ok=True)
eng27.run_once()
ok("GATE: com decision.strategy=deterministic (o real da produção), o provider de "
   "derivativos NUNCA e chamado — zero chamadas de rede pra dado que ninguem le",
   FakeClient27Contador.chamadas == 0, f"chamadas={FakeClient27Contador.chamadas}")

FakeClient27Contador.chamadas = 0
eng27._decision_cfg = {"strategy": "llm"}  # abre o gate (é só isso que llm_gate checa)


class FakeFlatStrategy27:
    """Substitui _build_strategy pra abrir o gate SEM acionar a LLMStrategy
    real (que chamaria a API do Claude de verdade — nada a ver com o que
    este teste quer provar, que é só o gate de rede do provider)."""

    def generate(self, snap):
        return Signal(symbol=snap.symbol, direction=Direction.FLAT, conviction=0.0,
                      entry_price=0.0, stop_price=0.0, take_profit=None,
                      profile="daytrade", rationale="fake flat p/ teste do gate")

    def should_exit(self, snap, position):
        return None

    wants_exit_signals = False


eng27._build_strategy = lambda profile_name: FakeFlatStrategy27()
raised27 = False
try:
    eng27.run_once()
except Exception:
    raised27 = True
ok("com o gate ABERTO (decision.strategy=llm) e estrategia fake (sem chamar o Claude de "
   "verdade), run_once nao quebra", not raised27)
ok("GATE aberto: desta vez o provider de derivativos FOI chamado (prova que o gate "
   "realmente é condicional, não sempre-desligado por acidente)",
   FakeClient27Contador.chamadas > 0, f"chamadas={FakeClient27Contador.chamadas}")


# ---------- 28. LLMStrategy (Fase 3) — ZERO cobertura de teste até
# 22/07/2026, apesar de já implementada desde antes. A pedido do Lucas
# ("explorar Fase 3" -> "fazer tudo"), escrita agora, ANTES de qualquer
# teste ao vivo (mesmo em dry_run) — nunca foi revisada nem testada até
# hoje. ----------
from src.strategy.llm_strategy import LLMStrategy  # noqa: E402
from src.strategy.llm_prompt import build_system_prompt, snapshot_to_payload  # noqa: E402

df28 = compute_indicators(make_candles())
snap28 = snapshot_from_df("BTC/USDT:USDT", "15m", df28, funding_rate=-0.005)
# make_candles() (200 candles, +0.2%/candle) fecha bem longe de 100 (~149) —
# preco28 usado em vez de "100.0" cru nos payloads abaixo que esperam
# sinal ACIONAVEL, senão o guard novo de divergência de entry_price (seção
# 28o) rejeitaria como "preço fabricado" por engano.
preco28 = round(snap28.last_price, 2)


def _client_fn_fixo(resposta):
    """Fábrica de client_fn fake: devolve sempre a mesma string, ignora os
    prompts recebidos (quem quiser inspecionar os prompts, capture via
    closure numa lista à parte — ver teste de system_prompt abaixo)."""
    return lambda system, user: resposta


stop28 = round(preco28 - 5, 2)
tp28 = round(preco28 + 10, 2)
json_long_ok = json.dumps({
    "direction": "long", "conviction": 0.8, "entry_price": preco28,
    "stop_price": stop28, "take_profit": tp28, "rationale": "tendência de alta clara",
})
strat28 = LLMStrategy("daytrade", client_fn=_client_fn_fixo(json_long_ok), market_type="spot")
AUDIT.unlink(missing_ok=True)
sig28 = strat28.generate(snap28)
ok("LLMStrategy: JSON valido long -> Signal LONG com os campos certos",
   sig28.direction == Direction.LONG and sig28.conviction == 0.8
   and sig28.stop_price == stop28 and sig28.take_profit == tp28, str(sig28))
ev28 = [json.loads(l) for l in AUDIT.read_text(encoding="utf-8").splitlines()] if AUDIT.exists() else []
llm_signal_ev28 = next((e for e in ev28 if e.get("event") == "llm_signal"), None)
ok("LLMStrategy: sinal valido audita 'llm_signal' com o PAYLOAD certo (nao so o tipo do evento)",
   llm_signal_ev28 is not None
   and llm_signal_ev28.get("direction") == "long"
   and llm_signal_ev28.get("conviction") == 0.8
   and llm_signal_ev28.get("rationale") == "tendência de alta clara",
   str(llm_signal_ev28))

json_cercado = "```json\n" + json_long_ok + "\n```"
sig28b = LLMStrategy("daytrade", client_fn=_client_fn_fixo(json_cercado), market_type="spot").generate(snap28)
ok("LLMStrategy: JSON cercado em ```json ... ``` ainda parseia (tolerante a preambulo)",
   sig28b.direction == Direction.LONG)

sig28c = LLMStrategy("daytrade", client_fn=_client_fn_fixo("isso nao e JSON nenhum"),
                      market_type="spot").generate(snap28)
ok("LLMStrategy: resposta nao-JSON -> FLAT (nunca levanta, nunca inventa direcao)",
   sig28c.direction == Direction.FLAT)


def _client_fn_explode(system, user):
    raise RuntimeError("timeout de rede simulado")


sig28d = LLMStrategy("daytrade", client_fn=_client_fn_explode, market_type="spot").generate(snap28)
ok("LLMStrategy: client_fn levanta excecao -> FLAT (nunca propaga pro engine)",
   sig28d.direction == Direction.FLAT and "timeout" in sig28d.rationale.lower())

json_direcao_invalida = json.dumps({"direction": "sideways", "conviction": 0.9})
sig28e = LLMStrategy("daytrade", client_fn=_client_fn_fixo(json_direcao_invalida),
                      market_type="spot").generate(snap28)
ok("LLMStrategy: direction fora do enum (long/short/flat) -> FLAT",
   sig28e.direction == Direction.FLAT)

json_flat_explicito = json.dumps({"direction": "flat", "rationale": "sinais contraditorios"})
sig28f = LLMStrategy("daytrade", client_fn=_client_fn_fixo(json_flat_explicito),
                      market_type="spot").generate(snap28)
ok("LLMStrategy: modelo pede flat explicitamente -> FLAT com o rationale do modelo",
   sig28f.direction == Direction.FLAT and sig28f.rationale == "sinais contraditorios")

json_conviccao_baixa = json.dumps({
    "direction": "long", "conviction": 0.3, "entry_price": 100.0,
    "stop_price": 95.0, "rationale": "fraco",
})
sig28g = LLMStrategy("daytrade", client_fn=_client_fn_fixo(json_conviccao_baixa),
                      market_type="spot", min_conviction=0.6).generate(snap28)
ok("LLMStrategy: conviccao abaixo do limiar (0.3 < 0.6) -> FLAT mesmo com direcao/stop ok",
   sig28g.direction == Direction.FLAT)

json_campo_invalido = json.dumps({
    "direction": "long", "conviction": "muito confiante",  # string, nao numero
    "entry_price": 100.0, "stop_price": 95.0,
})
sig28h = LLMStrategy("daytrade", client_fn=_client_fn_fixo(json_campo_invalido),
                      market_type="spot").generate(snap28)
ok("LLMStrategy: campo numerico invalido (conviction como string nao-numerica) -> FLAT",
   sig28h.direction == Direction.FLAT)

json_sem_stop = json.dumps({
    "direction": "long", "conviction": 0.9, "entry_price": 100.0, "stop_price": 0,
})
sig28i = LLMStrategy("daytrade", client_fn=_client_fn_fixo(json_sem_stop),
                      market_type="spot").generate(snap28)
ok("LLMStrategy: stop_price=0 (ausente) -> FLAT (stop e sempre obrigatorio)",
   sig28i.direction == Direction.FLAT)

json_long_stop_incoerente = json.dumps({
    "direction": "long", "conviction": 0.9, "entry_price": 100.0, "stop_price": 105.0,
})
sig28j = LLMStrategy("daytrade", client_fn=_client_fn_fixo(json_long_stop_incoerente),
                      market_type="spot").generate(snap28)
ok("LLMStrategy: long com stop ACIMA do entry (incoerente) -> FLAT",
   sig28j.direction == Direction.FLAT)

json_short_stop_incoerente = json.dumps({
    "direction": "short", "conviction": 0.9, "entry_price": 100.0, "stop_price": 95.0,
})
sig28k = LLMStrategy("daytrade", client_fn=_client_fn_fixo(json_short_stop_incoerente),
                      market_type="perp").generate(snap28)
ok("LLMStrategy: short com stop ABAIXO do entry (incoerente) -> FLAT",
   sig28k.direction == Direction.FLAT)

json_conviccao_fora_do_range = json.dumps({
    "direction": "long", "conviction": 1.5, "entry_price": preco28, "stop_price": stop28,
})
sig28l = LLMStrategy("daytrade", client_fn=_client_fn_fixo(json_conviccao_fora_do_range),
                      market_type="spot").generate(snap28)
ok("LLMStrategy: conviction fora de [0,1] (1.5) e CLAMPADA, nao rejeitada",
   sig28l.direction == Direction.LONG and sig28l.conviction == 1.0, str(sig28l.conviction))

rationale_longo = "x" * 500
json_rationale_longo = json.dumps({
    "direction": "long", "conviction": 0.9, "entry_price": preco28, "stop_price": stop28,
    "rationale": rationale_longo,
})
sig28m = LLMStrategy("daytrade", client_fn=_client_fn_fixo(json_rationale_longo),
                      market_type="spot").generate(snap28)
ok("LLMStrategy: rationale e truncado em 280 caracteres (nao estoura a trilha)",
   len(sig28m.rationale) == 280, str(len(sig28m.rationale)))
AUDIT.unlink(missing_ok=True)
ev28m = [json.loads(l) for l in AUDIT.read_text(encoding="utf-8").splitlines()] if AUDIT.exists() else []
ok("LLMStrategy: rationale auditado em 'llm_signal' TAMBEM e truncado (nao vaza texto cru na trilha)",
   len((next((e for e in ev28m if e.get("event") == "llm_signal"), {}) or {}).get("rationale", "")) <= 280
   if ev28m else True)

# ---------- 28n. CRITICO da revisao adversarial de 22/07/2026: NaN/±inf
# bypassa TODA comparacao Python (nan < x, nan <= x, nan >= x sao sempre
# False) -- sem guard explicito, um stop_price=NaN vindo do modelo passava
# por TODOS os checks de coerencia e chegava aprovado (position_size=nan)
# ate o executor. Testado nos 4 campos numericos E nos dois pontos de defesa
# (LLMStrategy e, mais abaixo na seção de RiskManager, o veto independente).
# ----------
for campo_nan in ("stop_price", "entry_price", "take_profit", "conviction"):
    payload_nan = {
        "direction": "long", "conviction": 0.9, "entry_price": 100.0,
        "stop_price": 95.0, "take_profit": 110.0, "rationale": "x",
    }
    payload_nan[campo_nan] = float("nan")
    sig_nan = LLMStrategy("daytrade", client_fn=_client_fn_fixo(json.dumps(payload_nan)),
                           market_type="spot").generate(snap28)
    ok(f"LLMStrategy: NaN em '{campo_nan}' -> FLAT (nao passa como comparacao Python falsa)",
       sig_nan.direction == Direction.FLAT, f"campo={campo_nan} sig={sig_nan}")

for campo_inf, valor_inf in (("stop_price", float("inf")), ("entry_price", float("-inf"))):
    payload_inf = {
        "direction": "long", "conviction": 0.9, "entry_price": 100.0,
        "stop_price": 95.0, "take_profit": 110.0, "rationale": "x",
    }
    payload_inf[campo_inf] = valor_inf
    sig_inf = LLMStrategy("daytrade", client_fn=_client_fn_fixo(json.dumps(payload_inf)),
                           market_type="spot").generate(snap28)
    ok(f"LLMStrategy: infinito em '{campo_inf}' -> FLAT",
       sig_inf.direction == Direction.FLAT, f"campo={campo_inf} sig={sig_inf}")

# NaN em conviction ANTES do fix seria clampada pra 1.0 (max) em vez de
# rejeitada — max(0.0, min(1.0, nan)) == 1.0 em CPython. Prova explícita de
# que o guard roda ANTES do clamp, não confia só no gate de min_conviction.
sig_conv_nan = LLMStrategy("daytrade", client_fn=_client_fn_fixo(json.dumps({
    "direction": "long", "conviction": float("nan"), "entry_price": 100.0,
    "stop_price": 95.0, "rationale": "x",
})), market_type="spot", min_conviction=0.6).generate(snap28)
ok("LLMStrategy: conviction=NaN NUNCA vira conviction=1.0 (era o bug antes do fix)",
   sig_conv_nan.direction == Direction.FLAT and sig_conv_nan.conviction == 0.0,
   str(sig_conv_nan))

# ---------- 28o. MEDIO da revisao: entry_price fabricado/alucinado — a UNICA
# fronteira de confianca genuinamente NOVA que a Fase 3 introduz (a
# estrategia deterministica sempre deriva entry_price do candle real; aqui
# vem de JSON nao confiavel). snap28.last_price vem do ultimo candle
# fechado de make_candles() — testa contra um entry_price bem longe dele.
# ----------
preco_real28 = snap28.last_price
entry_fabricado = preco_real28 * 1.5  # 50% de divergencia, bem acima do limite de 2%
sig_entry_fabricado = LLMStrategy("daytrade", client_fn=_client_fn_fixo(json.dumps({
    "direction": "long", "conviction": 0.9, "entry_price": entry_fabricado,
    "stop_price": entry_fabricado * 0.95, "rationale": "x",
})), market_type="spot").generate(snap28)
ok("LLMStrategy: entry_price MUITO longe do preco real (50%) -> FLAT, mesmo com stop coerente",
   sig_entry_fabricado.direction == Direction.FLAT, str(sig_entry_fabricado))

entry_proximo = preco_real28 * 1.005  # 0.5%, dentro do limite de 2%
sig_entry_proximo = LLMStrategy("daytrade", client_fn=_client_fn_fixo(json.dumps({
    "direction": "long", "conviction": 0.9, "entry_price": entry_proximo,
    "stop_price": entry_proximo * 0.95, "rationale": "x",
})), market_type="spot").generate(snap28)
ok("LLMStrategy: entry_price perto do preco real (0.5%, dentro do limite) -> aprovado normalmente",
   sig_entry_proximo.direction == Direction.LONG, str(sig_entry_proximo))

# ---------- 28b. build_system_prompt: modo SPOT vs PERP (achado da revisão
# de 22/07/2026 — antes o prompt dizia "perpétuos" incondicionalmente,
# mesmo com o robô rodando em spot; o modelo podia sugerir short e ser
# vetado toda vez pela camada de risco, gastando análise/API à toa) ----------
prompt_spot28 = build_system_prompt("spot")
prompt_perp28 = build_system_prompt("perp")
ok("build_system_prompt('spot') menciona explicitamente SEM short/alavancagem",
   "sem" in prompt_spot28.lower() and "short" in prompt_spot28.lower()
   and "alavancagem" in prompt_spot28.lower(), prompt_spot28[:200])
ok("build_system_prompt('perp') menciona long e short disponiveis",
   "long e short" in prompt_perp28.lower() or ("long" in prompt_perp28.lower()
   and "short" in prompt_perp28.lower() and "disponíveis" in prompt_perp28.lower()))
ok("os dois prompts sao DIFERENTES entre si (nao e so um texto fixo reciclado)",
   prompt_spot28 != prompt_perp28)
ok("market_type desconhecido cai no fallback 'spot' (fail-CLOSED — mais restritivo, "
   "achado da revisao: antes caia em 'perp', o modo permissivo, ao contrario do "
   "principio de falhar fechado)",
   build_system_prompt("modo_que_nao_existe") == prompt_spot28)
ok("prompt avisa explicitamente que o campo 'context' e DADO externo, nunca instrucao "
   "(mitigacao de prompt injection recomendada pela revisao)",
   "dado" in prompt_spot28.lower() and "instru" in prompt_spot28.lower())
ok("prompt avisa que entry_price precisa ficar PROXIMO do last_price fornecido",
   "last_price" in prompt_spot28.lower() or "próximo" in prompt_spot28.lower())

strat28_spot = LLMStrategy("daytrade", client_fn=_client_fn_fixo(json_long_ok), market_type="spot")
strat28_perp = LLMStrategy("daytrade", client_fn=_client_fn_fixo(json_long_ok), market_type="perp")
ok("LLMStrategy(market_type='spot') usa o prompt de spot de verdade (nao o default perp)",
   strat28_spot.system_prompt == prompt_spot28 and strat28_spot.system_prompt != prompt_perp28)
ok("LLMStrategy(market_type='perp') usa o prompt de perp",
   strat28_perp.system_prompt == prompt_perp28)

ok("snapshot_to_payload: contexto vazio ja inclui a chave 'derivatives' (consistente com #G)",
   "derivatives" in snapshot_to_payload(snap28)["context"])

# ---------- 28c. engine: LLMStrategy real recebe o market_type/model/
# min_conviction do Engine (não fica preso nos defaults do construtor) ----------
engine_mod.BybitClient = FakeEthQuebrado
eng28 = engine_mod.Engine(dry_run=True)
# Esta seção prova que Engine._build_strategy passa o market_type REAL pro
# LLMStrategy comparando contra o literal "spot", nunca contra ele mesmo
# (achado da revisão de 22/07/2026). Até 27/07/2026 isso valia de graça
# porque o YAML real vivia em spot; desde 28/07/2026 (Lucas religou
# perp/short em produção) o YAML real é "perp" — força "spot" aqui, mesmo
# padrão já usado na seção 12 e no precedente da seção 13
# (`eng_tp.market_type = "perp"`), pra manter a asserção literal e
# desacoplada do que o YAML ao vivo disser.
eng28.market_type = "spot"

# min_conviction: valor DISTINTO do default da classe (0.6) — um valor igual
# ao default não provaria que o wiring funciona (passaria mesmo se
# engine.py ignorasse o YAML e usasse o próprio default por engano).
eng28._decision_cfg = {"strategy": "llm", "llm": {"min_conviction": 0.42}}

# model: monkeypatcha anthropic_client_fn DENTRO do módulo llm_strategy —
# _build_strategy faz `from src.strategy.llm_strategy import ... anthropic_client_fn`
# a cada chamada (import local, não de topo de arquivo), então substituir o
# nome no módulo É suficiente pra interceptar, sem precisar de
# ANTHROPIC_API_KEY nem chamar a API de verdade. Achado da revisão: o teste
# original pré-populava eng28._llm_client_fn ANTES de chamar
# _build_strategy, o que pulava esse branch inteiro — o fix de hoje (nome do
# modelo desatualizado -> "claude-sonnet-5") ficava sem nenhuma cobertura.
import src.strategy.llm_strategy as llm_strategy_mod  # noqa: E402
_modelos_capturados = []
_anthropic_client_fn_original = llm_strategy_mod.anthropic_client_fn


def _fake_anthropic_client_fn(model, temperature=0.2, max_tokens=512):
    _modelos_capturados.append(model)
    return _client_fn_fixo(json_long_ok)


llm_strategy_mod.anthropic_client_fn = _fake_anthropic_client_fn
try:
    strat_real28 = eng28._build_strategy("daytrade")
finally:
    llm_strategy_mod.anthropic_client_fn = _anthropic_client_fn_original

ok("Engine._build_strategy('llm') passa o market_type REAL ('spot') pro LLMStrategy",
   strat_real28.system_prompt == build_system_prompt("spot")
   and strat_real28.system_prompt != build_system_prompt("perp"))
ok("Engine._build_strategy('llm') le decision.llm.model do YAML (nao um default hardcoded) — "
   "prova a wiring do fix de hoje (claude-sonnet-4-6 -> claude-sonnet-5)",
   _modelos_capturados == ["claude-sonnet-5"], str(_modelos_capturados))
ok("Engine._build_strategy('llm') le decision.llm.min_conviction do YAML de verdade "
   "(valor distinto do default 0.6, prova que nao e coincidencia)",
   strat_real28.min_conviction == 0.42, str(strat_real28.min_conviction))

# ---------- 28p. RiskManager: veto independente de NaN/±inf (defesa em
# profundidade — a Fase 3 pode gerar Signal diretamente em cenários futuros
# como backtest/walk-forward, não só via engine.py; o veto absoluto não pode
# depender de quem gerou o sinal já ter filtrado) ----------
sig_nan_direto = Signal(symbol="BTC/USDT:USDT", direction=Direction.LONG, conviction=0.8,
                         entry_price=100.0, stop_price=float("nan"), take_profit=110.0,
                         profile="daytrade", rationale="teste direto")
dec_nan = RiskManager(cfg, environment="testnet").evaluate(sig_nan_direto, state, funding_rate=0.0, data_age_sec=0)
ok("RiskManager: veta Signal com stop_price=NaN mesmo vindo direto (nao so via LLMStrategy)",
   not dec_nan.approved, dec_nan.reason)

sig_inf_direto = Signal(symbol="BTC/USDT:USDT", direction=Direction.LONG, conviction=0.8,
                         entry_price=float("inf"), stop_price=95.0, take_profit=110.0,
                         profile="daytrade", rationale="teste direto")
dec_inf = RiskManager(cfg, environment="testnet").evaluate(sig_inf_direto, state, funding_rate=0.0, data_age_sec=0)
ok("RiskManager: veta Signal com entry_price=inf mesmo vindo direto",
   not dec_inf.approved, dec_inf.reason)


# ---------- 29. trailing + take-profit fixo coexistem (27/07/2026, a pedido
# do Lucas: "eu quero os dois" — take_profit atingido cancela o stop e
# realiza a mercado, trailing continua subindo o stop enquanto isso nao
# acontece). Antes deste fix, `trailing=True` zerava o take_profit do sinal
# (`tp = None if p.trailing else ...` em deterministic.py) — o UNICO ponto
# do codigo que forcava exclusividade entre os dois mecanismos.
# engine._check_spot_exits (linha ~404: `tp = protection.get("take_profit");
# if tp and price >= tp: ...`) e backtester._try_close (linha ~282: `elif
# trade.take_profit and high >= trade.take_profit`) JA checavam take_profit
# e trailing de forma totalmente independente — nenhuma mudanca foi
# necessaria la, so na estrategia (unica fonte da exclusividade). ----------
from src.data.market_data import MarketSnapshot as MarketSnapshot29  # noqa: E402
_candles29 = pd.DataFrame(columns=["ts", "open", "high", "low", "close", "volume"])

snap29_long = MarketSnapshot29(
    symbol="BTC/USDT:USDT", timeframe="15m", last_price=100.0, funding_rate=None,
    indicators={"ema_fast": 11.0, "ema_slow": 10.0, "rsi": 50.0, "atr": 2.0},
    candles=_candles29)
sig29_long = DeterministicStrategy("daytrade", params=StrategyParams(trailing=True)).generate(snap29_long)
_stop29_long = 100.0 - 1.5 * 2.0  # atr_stop_mult default = 1.5
_tp29_long = 100.0 + 2.0 * (100.0 - _stop29_long)  # tp_rr default = 2.0
ok("estrategia: LONG com trailing=True AINDA calcula take_profit fixo (tp_rr) — "
   "antes deste fix virava None e so a reversao no trailing realizava lucro",
   sig29_long.direction == Direction.LONG and sig29_long.trailing is True
   and sig29_long.take_profit is not None
   and abs(sig29_long.take_profit - _tp29_long) < 1e-9
   and abs(sig29_long.stop_price - _stop29_long) < 1e-9,
   f"tp={sig29_long.take_profit} stop={sig29_long.stop_price}")

snap29_short = MarketSnapshot29(
    symbol="BTC/USDT:USDT", timeframe="15m", last_price=100.0, funding_rate=None,
    indicators={"ema_fast": 9.0, "ema_slow": 10.0, "rsi": 50.0, "atr": 2.0},
    candles=_candles29)
sig29_short = DeterministicStrategy("daytrade", params=StrategyParams(trailing=True)).generate(snap29_short)
_stop29_short = 100.0 + 1.5 * 2.0
_tp29_short = 100.0 - 2.0 * (_stop29_short - 100.0)
ok("estrategia: SHORT com trailing=True AINDA calcula take_profit fixo (tp_rr) — "
   "mesmo fix do ramo LONG, aplicado ao ramo simetrico",
   sig29_short.direction == Direction.SHORT and sig29_short.trailing is True
   and sig29_short.take_profit is not None
   and abs(sig29_short.take_profit - _tp29_short) < 1e-9
   and abs(sig29_short.stop_price - _stop29_short) < 1e-9,
   f"tp={sig29_short.take_profit} stop={sig29_short.stop_price}")

# Regressao: sem trailing, o take_profit continua EXATAMENTE igual ao de
# sempre (o fix so afeta o ramo trailing=True).
sig29_notrail = DeterministicStrategy("daytrade", params=StrategyParams(trailing=False)).generate(snap29_long)
ok("estrategia: sem trailing, take_profit permanece identico ao comportamento antigo (regressao)",
   sig29_notrail.trailing is False
   and abs(sig29_notrail.take_profit - _tp29_long) < 1e-9)

# Prova de ponta a ponta (reusa o backtest da secao 20g/21, ja rodado acima
# com trailing=True): o TP fixo realmente FECHA a posicao quando o preco
# rally o suficiente, mesmo com o trailing tambem ativo na mesma posicao —
# ja coberto pelas duas primeiras asserções da secao 20g (linhas acima,
# `trail_trades`): "TAMBEM tem take-profit fixo calculado" e "TP fixo
# captura o rally... MESMO com trailing tambem ligado".
ok("secao 29: prova de ponta a ponta ja coberta pela secao 20g (reexecutar "
   "aqui so pra deixar o vinculo explicito no relatorio de testes)",
   len(trail_trades) >= 1 and any(t.exit_reason == "take_profit" for t in trail_trades)
   and any(t.exit_reason == "trailing_stop" for t in trail_trades),
   f"exit_reasons={[t.exit_reason for t in trail_trades]}")


# ---------- 30. perp: fechamento auditado + cancelamento da ordem irmã órfã
# (28/07/2026, a pedido do Lucas — "corrige o fechamento auditado pro perp").
# Contexto: Lucas religou perp/short em produção pela primeira vez desde o
# bloqueio de compliance de 15/07. A 1ª entrada real fechou pelo stop (fill
# confirmado direto na exchange) e NADA foi auditado — nem trade_closed, nem
# cooldown, nem o TP órfão da entrada anterior foi cancelado (ficou ativo,
# podia executar contra uma posição nova não relacionada). Este mecanismo
# nunca tinha sido exercitado ao vivo porque perp nunca operou de verdade
# antes de hoje. ----------
class FakePerpExit:
    is_testnet = True
    ORDER_RESPONSES: dict = {}
    CANCEL_SHOULD_FAIL = False

    def __init__(self, *a, **k):
        self.calls = []

    def fetch_order(self, order_id, symbol):
        self.calls.append(("fetch_order", order_id, symbol))
        return type(self).ORDER_RESPONSES.get(
            order_id, {"id": order_id, "status": "open", "filled": 0.0,
                       "average": None, "price": None})

    def cancel_order(self, order_id, symbol):
        self.calls.append(("cancel_order", order_id, symbol))
        if FakePerpExit.CANCEL_SHOULD_FAIL:
            raise RuntimeError("cancelamento rejeitado (simulado)")
        return {"id": order_id, "status": "canceled"}


# 30a. stop confirmado (filled>0) -> trade_closed reason=stop_loss com o fill
# REAL, cooldown incrementado, TP irmão (ainda 'open') CANCELADO.
AUDIT.unlink(missing_ok=True)
protection_state.set_protection("BTC/USDT:USDT", entry_price=100.0, take_profit=110.0,
                                stop_price=95.0, size=1.0,
                                stop_id="stop-30a", tp_id="tp-30a")
FakePerpExit.ORDER_RESPONSES = {
    "stop-30a": {"id": "stop-30a", "status": "closed", "filled": 1.0,
                 "average": 94.8, "price": 94.8},
    "tp-30a": {"id": "tp-30a", "status": "open", "filled": 0.0,
               "average": None, "price": None},
}
FakePerpExit.CANCEL_SHOULD_FAIL = False
engine_mod.BybitClient = FakePerpExit
eng30a = engine_mod.Engine(dry_run=False)
eng30a.market_type = "perp"
eng30a._open_symbols = set()
eng30a._check_perp_exits()
ev30a = [json.loads(l) for l in AUDIT.read_text(encoding="utf-8").splitlines()]
tc30a = [e for e in ev30a if e["event"] == "trade_closed" and e["symbol"] == "BTC/USDT:USDT"]
ok("perp: stop confirmado -> trade_closed com reason=stop_loss e fill REAL (nao o alvo)",
   len(tc30a) == 1 and tc30a[0]["reason"] == "stop_loss"
   and tc30a[0]["exit_price"] == 94.8 and tc30a[0]["exit_price_source"] == "stop_order_fill"
   and abs(tc30a[0]["pnl_usdt"] - (94.8 - 100.0) * 1.0) < 1e-9, str(tc30a))
cd30a = [e for e in ev30a if e["event"] == "cooldown_triggered" and e["symbol"] == "BTC/USDT:USDT"]
ok("perp: stop confirmado aciona cooldown (mesma regra do stop em spot)", len(cd30a) == 1)
ok("perp: ordem TP irmã (ainda open) foi CANCELADA", ("cancel_order", "tp-30a", "BTC/USDT:USDT") in eng30a.client.calls)
ok("perp: proteção limpa após reconciliação", "BTC/USDT:USDT" not in protection_state.load())

# 30b. TP confirmado (filled>0) -> trade_closed reason=take_profit, cooldown
# RESETADO (nao incrementado), stop irmão CANCELADO.
AUDIT.unlink(missing_ok=True)
protection_state.set_protection("ETH/USDT:USDT", entry_price=1900.0, take_profit=1930.0,
                                stop_price=1880.0, size=0.5,
                                stop_id="stop-30b", tp_id="tp-30b")
FakePerpExit.ORDER_RESPONSES = {
    "stop-30b": {"id": "stop-30b", "status": "open", "filled": 0.0,
                 "average": None, "price": None},
    "tp-30b": {"id": "tp-30b", "status": "closed", "filled": 0.5,
               "average": 1930.5, "price": 1930.5},
}
eng30b = engine_mod.Engine(dry_run=False)
eng30b.market_type = "perp"
eng30b._open_symbols = set()
eng30b._check_perp_exits()
ev30b = [json.loads(l) for l in AUDIT.read_text(encoding="utf-8").splitlines()]
tc30b = [e for e in ev30b if e["event"] == "trade_closed" and e["symbol"] == "ETH/USDT:USDT"]
ok("perp: TP confirmado -> trade_closed com reason=take_profit e fill REAL",
   len(tc30b) == 1 and tc30b[0]["reason"] == "take_profit"
   and tc30b[0]["exit_price"] == 1930.5 and tc30b[0]["exit_price_source"] == "tp_order_fill"
   and abs(tc30b[0]["pnl_usdt"] - (1930.5 - 1900.0) * 0.5) < 1e-9, str(tc30b))
ok("perp: ordem stop irmã (ainda open) foi CANCELADA", ("cancel_order", "stop-30b", "ETH/USDT:USDT") in eng30b.client.calls)

# 30c. NENHUMA das duas confirma fechamento (fechamento manual/liquidação, ou
# falha ao consultar) -> trade_closed aproximado (reason=
# external_close_unconfirmed, exit_price=stop_price alvo), e NENHUM
# cancelamento é tentado (sem certeza de qual disparou, cancelar às cegas
# arriscaria derrubar a proteção de uma posição nova já reaberta).
AUDIT.unlink(missing_ok=True)
protection_state.set_protection("SOL/USDT:USDT", entry_price=150.0, take_profit=160.0,
                                stop_price=140.0, size=2.0,
                                stop_id="stop-30c", tp_id="tp-30c")
FakePerpExit.ORDER_RESPONSES = {
    "stop-30c": {"id": "stop-30c", "status": "open", "filled": 0.0,
                 "average": None, "price": None},
    "tp-30c": {"id": "tp-30c", "status": "open", "filled": 0.0,
               "average": None, "price": None},
}
eng30c = engine_mod.Engine(dry_run=False)
eng30c.market_type = "perp"
eng30c._open_symbols = set()
eng30c._check_perp_exits()
ev30c = [json.loads(l) for l in AUDIT.read_text(encoding="utf-8").splitlines()]
tc30c = [e for e in ev30c if e["event"] == "trade_closed" and e["symbol"] == "SOL/USDT:USDT"]
ok("perp: nenhuma ordem confirma -> trade_closed aproximado (reason=external_close_unconfirmed)",
   len(tc30c) == 1 and tc30c[0]["reason"] == "external_close_unconfirmed"
   and tc30c[0]["exit_price"] == 140.0
   and tc30c[0]["exit_price_source"] == "stop_price_target_approx", str(tc30c))
ok("perp: SEM confirmacao de qual disparou, NENHUM cancelamento e tentado (evita derrubar posicao nova)",
   not any(c[0] == "cancel_order" for c in eng30c.client.calls), str(eng30c.client.calls))

# 30d. cancelamento da ordem órfã FALHA (ex.: ordem já não existe mais) -> não
# escala como falha de proteção, audita perp_orphan_order_cancel_failed, e o
# trade_closed principal já saiu normalmente antes disso.
AUDIT.unlink(missing_ok=True)
protection_state.set_protection("ADA/USDT:USDT", entry_price=0.5, take_profit=0.55,
                                stop_price=0.45, size=100.0,
                                stop_id="stop-30d", tp_id="tp-30d")
FakePerpExit.ORDER_RESPONSES = {
    "stop-30d": {"id": "stop-30d", "status": "closed", "filled": 100.0,
                 "average": 0.44, "price": 0.44},
    "tp-30d": {"id": "tp-30d", "status": "open", "filled": 0.0,
               "average": None, "price": None},
}
FakePerpExit.CANCEL_SHOULD_FAIL = True
eng30d = engine_mod.Engine(dry_run=False)
eng30d.market_type = "perp"
eng30d._open_symbols = set()
try:
    eng30d._check_perp_exits()
    nao_propagou30d = True
except Exception:
    nao_propagou30d = False
ok("perp: falha ao cancelar ordem orfa NAO derruba a reconciliacao", nao_propagou30d)
ev30d = [json.loads(l) for l in AUDIT.read_text(encoding="utf-8").splitlines()]
tc30d = [e for e in ev30d if e["event"] == "trade_closed" and e["symbol"] == "ADA/USDT:USDT"]
ok("perp: trade_closed sai normalmente mesmo com o cancelamento da orfa falhando depois",
   len(tc30d) == 1 and tc30d[0]["reason"] == "stop_loss")
fail30d = [e for e in ev30d if e["event"] == "perp_orphan_order_cancel_failed"
           and e["symbol"] == "ADA/USDT:USDT"]
ok("perp: falha de cancelamento auditada (perp_orphan_order_cancel_failed)", len(fail30d) == 1)
FakePerpExit.CANCEL_SHOULD_FAIL = False

# 30e. backfill na primeira vez que uma posição perp é vista sem registro em
# protection_state (cobre a posição perp real do Lucas, aberta ANTES deste
# fix existir — sem isto, o fechamento dela nunca seria detectado).
from src.logger import audit as _audit30  # noqa: E402
AUDIT.unlink(missing_ok=True)
_audit30("order_executed", symbol="XRP/USDT:USDT", side="buy", size=200.0,
        protect_size=200.0, entry_price=0.6, stop_price=0.57, take_profit=0.66,
        entry_id="entry-30e", stop_id="stop-30e", tp_id="tp-30e",
        profile="daytrade", trailing=False, testnet=False)
eng30e = engine_mod.Engine(dry_run=False)
eng30e.market_type = "perp"
eng30e._open_symbols = {"XRP/USDT:USDT"}  # AINDA aberta -> so backfill, sem reconciliar fechamento
eng30e._check_perp_exits()
backfilled30e = protection_state.load().get("XRP/USDT:USDT")
ok("perp: posicao vista sem protecao e recuperada via backfill_from_audit (incl. tp_id)",
   backfilled30e is not None and backfilled30e.get("stop_id") == "stop-30e"
   and backfilled30e.get("tp_id") == "tp-30e" and backfilled30e.get("entry_price") == 0.6,
   str(backfilled30e))
# Agora ela fecha (some de _open_symbols) -> o ciclo seguinte reconcilia
# normalmente usando o que acabou de ser backfilled.
FakePerpExit.ORDER_RESPONSES = {
    "stop-30e": {"id": "stop-30e", "status": "closed", "filled": 200.0,
                 "average": 0.565, "price": 0.565},
    "tp-30e": {"id": "tp-30e", "status": "open", "filled": 0.0,
               "average": None, "price": None},
}
eng30e._open_symbols = set()
eng30e._check_perp_exits()
ev30e = [json.loads(l) for l in AUDIT.read_text(encoding="utf-8").splitlines()]
tc30e = [e for e in ev30e if e["event"] == "trade_closed" and e["symbol"] == "XRP/USDT:USDT"]
ok("perp: posicao backfilled fecha normalmente no ciclo seguinte (stop confirmado)",
   len(tc30e) == 1 and tc30e[0]["reason"] == "stop_loss" and tc30e[0]["exit_price"] == 0.565)
protection_state.clear_protection("XRP/USDT:USDT")

# 30f. isolamento por símbolo: erro real na apuração de UM símbolo (size
# corrompido no arquivo -> TypeError no cálculo de pnl_usdt, FORA do
# try/except que só cobre a chamada fetch_order) não derruba o ciclo nem
# impede o OUTRO símbolo de ser reconciliado (mesmo padrão de isolamento já
# validado pro caminho spot, seção 12j).
AUDIT.unlink(missing_ok=True)
protection_state.set_protection("BAD/USDT:USDT", entry_price=1.0, take_profit=1.2,
                                stop_price=0.9, size=10.0,
                                stop_id="stop-bad-30f", tp_id=None)
_protecoes30f = protection_state.load()
_protecoes30f["BAD/USDT:USDT"]["size"] = "nao-e-numero"  # corrompe o arquivo direto
protection_state._save(_protecoes30f)
protection_state.set_protection("GOOD/USDT:USDT", entry_price=2.0, take_profit=2.4,
                                stop_price=1.8, size=5.0,
                                stop_id="stop-good-30f", tp_id=None)
FakePerpExit.ORDER_RESPONSES = {
    "stop-bad-30f": {"id": "stop-bad-30f", "status": "closed", "filled": 10.0,
                     "average": 0.89, "price": 0.89},
    "stop-good-30f": {"id": "stop-good-30f", "status": "closed", "filled": 5.0,
                      "average": 1.79, "price": 1.79},
}
engine_mod.BybitClient = FakePerpExit
eng30f = engine_mod.Engine(dry_run=False)
eng30f.market_type = "perp"
eng30f._open_symbols = set()
try:
    eng30f._check_perp_exits()
    nao_propagou30f = True
except Exception:
    nao_propagou30f = False
ok("perp: erro real num simbolo nao derruba o ciclo (isolamento)", nao_propagou30f)
ev30f = [json.loads(l) for l in AUDIT.read_text(encoding="utf-8").splitlines()]
err30f = [e for e in ev30f if e["event"] == "symbol_cycle_error" and e["symbol"] == "BAD/USDT:USDT"]
ok("perp: erro no BAD auditado como symbol_cycle_error", len(err30f) == 1)
tc30f_good = [e for e in ev30f if e["event"] == "trade_closed" and e["symbol"] == "GOOD/USDT:USDT"]
ok("perp: GOOD processado normalmente apesar do erro no BAD (isolamento de verdade)",
   len(tc30f_good) == 1 and tc30f_good[0]["reason"] == "stop_loss")
ok("perp: protecao de AMBOS limpa mesmo assim (finally roda independente do resultado)",
   "BAD/USDT:USDT" not in protection_state.load()
   and "GOOD/USDT:USDT" not in protection_state.load())

# 30g. spot/dry_run: _check_perp_exits() é no-op de propósito (não é o modo
# ativo, ou não deveria tocar exchange fora de --live).
AUDIT.unlink(missing_ok=True)
engine_mod.BybitClient = FakePerpExit
eng30g_spot = engine_mod.Engine(dry_run=False)
eng30g_spot.market_type = "spot"
protection_state.set_protection("NOOP1/USDT", entry_price=1.0, take_profit=1.1, stop_price=0.9)
eng30g_spot._open_symbols = set()
eng30g_spot._check_perp_exits()
ok("perp: market_type=spot -> _check_perp_exits e no-op (nao mexe na protecao de spot)",
   "NOOP1/USDT" in protection_state.load())
protection_state.clear_protection("NOOP1/USDT")

eng30g_dry = engine_mod.Engine(dry_run=True)
eng30g_dry.market_type = "perp"
protection_state.set_protection("NOOP2/USDT:USDT", entry_price=1.0, take_profit=1.1,
                                stop_price=0.9, stop_id="stop-noop2", tp_id="tp-noop2")
eng30g_dry._open_symbols = set()
eng30g_dry._check_perp_exits()
ok("perp: dry_run=True -> _check_perp_exits e no-op (defesa em profundidade)",
   "NOOP2/USDT:USDT" in protection_state.load())
protection_state.clear_protection("NOOP2/USDT:USDT")

# 30h. executor: entrada REAL em perp persiste protection_state com tp_id
# (wiring ponta a ponta — sem isto, nada da seção 30 teria dado real pra
# reconciliar, já que a persistência acontece na ENTRADA, não no fechamento).
class FakePerpEntry:
    is_testnet = True

    def __init__(self, *a, **k):
        self.calls = []

    def set_leverage(self, symbol, leverage):
        self.calls.append(("set_leverage", leverage))

    def create_order(self, symbol, side, amount, order_type="market", price=None, params=None):
        self.calls.append(("create_order", side, amount))
        return {"id": "entry-30h", "average": 100.0}

    def fetch_order(self, order_id, symbol):
        return {"id": order_id, "average": 100.0, "price": 100.0}

    def set_stop_loss(self, symbol, side, amount, stop_price):
        self.calls.append(("set_stop_loss", stop_price))
        return {"id": "stop-30h"}

    def set_take_profit(self, symbol, side, amount, tp_price):
        self.calls.append(("set_take_profit", tp_price))
        return {"id": "tp-30h"}

    def amount_to_precision(self, symbol, amount):
        return amount


AUDIT.unlink(missing_ok=True)
protection_state.clear_protection("PERPENTRY/USDT:USDT")
sig30h = Signal(symbol="PERPENTRY/USDT:USDT", direction=Direction.LONG, conviction=0.8,
                entry_price=100.0, stop_price=95.0, take_profit=110.0,
                profile="daytrade", rationale="teste entrada perp")
# PortfolioState PRÓPRIO (não o `state` global compartilhado, que outras
# seções já mutaram ao longo do arquivo) — evita depender de estado residual.
state30h = PortfolioState(equity_usdt=1000.0, day_start_equity=1000.0, peak_equity=1000.0,
                          open_positions=0, total_notional=0.0, aggregate_risk_pct=0.0)
d30h = RiskManager(cfg, environment="testnet").evaluate(sig30h, state30h, funding_rate=None, data_age_sec=0)
ok("pre-requisito 30h: sinal de entrada perp aprovado (senao o resto do teste e vazio)",
   d30h.approved, d30h.reason)
Executor(FakePerpEntry(), dry_run=False, market_type="perp").execute(sig30h, d30h)
prot30h = protection_state.load().get("PERPENTRY/USDT:USDT")
ok("executor: entrada perp persiste protection_state com stop_id E tp_id (28/07)",
   prot30h is not None and prot30h.get("stop_id") == "stop-30h"
   and prot30h.get("tp_id") == "tp-30h" and prot30h.get("entry_price") == 100.0,
   str(prot30h))
ok("executor: entrada perp LONG persiste side='long'", prot30h.get("side") == "long", str(prot30h))
protection_state.clear_protection("PERPENTRY/USDT:USDT")

sig30h_short = Signal(symbol="PERPSHORT/USDT:USDT", direction=Direction.SHORT, conviction=0.8,
                      entry_price=100.0, stop_price=105.0, take_profit=90.0,
                      profile="daytrade", rationale="teste entrada perp short")
d30h_short = RiskManager(cfg, environment="testnet").evaluate(
    sig30h_short, state30h, funding_rate=None, data_age_sec=0)
Executor(FakePerpEntry(), dry_run=False, market_type="perp").execute(sig30h_short, d30h_short)
prot30h_short = protection_state.load().get("PERPSHORT/USDT:USDT")
ok("executor: entrada perp SHORT persiste side='short'",
   prot30h_short is not None and prot30h_short.get("side") == "short", str(prot30h_short))
protection_state.clear_protection("PERPSHORT/USDT:USDT")
engine_mod.BybitClient = FakeEthQuebrado

# ---------- 31. perp: trailing stop MOVE de verdade (28/07/2026, a pedido do
# Lucas — "corrige o trailing em perp também"). Diferente do spot
# (_update_trailing_stop): perp nunca tem o problema de saldo ocupado —
# mover é sempre cancelar a ordem de STOP antiga (por id) e criar outra; o
# TP nunca é tocado. Suporta LONG e SHORT (mesmo achado que motivou side
# em protection_state: short precisa do sinal invertido em tudo — pico vira
# fundo, sobe vira desce). ----------
class FakePerpTrailing(FakePerpExit):
    SET_STOP_RESPONSES: list = []
    CANCEL_SHOULD_FAIL = False

    def set_stop_loss(self, symbol, side, amount, stop_price):
        self.calls.append(("set_stop_loss", side, amount, stop_price))
        if type(self).SET_STOP_RESPONSES:
            resp = type(self).SET_STOP_RESPONSES.pop(0)
            if isinstance(resp, Exception):
                raise resp
            return resp
        return {"id": f"newstop-{len(self.calls)}"}

    def cancel_order(self, order_id, symbol):
        self.calls.append(("cancel_order", order_id, symbol))
        if type(self).CANCEL_SHOULD_FAIL:
            raise RuntimeError("cancelamento do stop antigo falhou (simulado)")
        return {"id": order_id, "status": "canceled"}


def _reset_fake_perp_trailing():
    FakePerpTrailing.ORDER_RESPONSES = {}
    FakePerpTrailing.SET_STOP_RESPONSES = []
    FakePerpTrailing.CANCEL_SHOULD_FAIL = False


engine_mod.BybitClient = FakePerpTrailing


def _eng31():
    e = engine_mod.Engine(dry_run=False)
    e.market_type = "perp"
    return e


# 31a. LONG: preço avança o suficiente -> stop sobe de verdade (cancela o
# antigo, arma um novo), pico atualizado, protection_state persistida.
_reset_fake_perp_trailing()
AUDIT.unlink(missing_ok=True)
prot31a = {"entry_price": 100.0, "take_profit": 130.0, "stop_price": 95.0,
          "size": 2.0, "stop_id": "stop-31a", "tp_id": "tp-31a", "side": "long",
          "profile": "daytrade", "trailing": True, "trail_distance": 5.0,
          "peak_price": 100.0}
FakePerpTrailing.ORDER_RESPONSES = {
    "stop-31a": {"id": "stop-31a", "status": "open", "filled": 0.0,
                "triggerPrice": "95.0"},
}
eng31a = _eng31()
eng31a._update_perp_trailing_stop("BTC/USDT:USDT", prot31a, 110.0)
ok("perp trailing LONG: cancela o stop antigo", ("cancel_order", "stop-31a", "BTC/USDT:USDT") in eng31a.client.calls)
ok("perp trailing LONG: arma o novo stop no preco certo (peak-trail = 110-5=105)",
   any(c[0] == "set_stop_loss" and c[1] == "buy" and abs(c[3] - 105.0) < 1e-9
       for c in eng31a.client.calls), str(eng31a.client.calls))
ev31a = [json.loads(l) for l in AUDIT.read_text(encoding="utf-8").splitlines()]
mv31a = [e for e in ev31a if e["event"] == "trailing_stop_moved" and e["symbol"] == "BTC/USDT:USDT"]
ok("perp trailing LONG: trailing_stop_moved auditado (old=95, new=105, peak=110)",
   len(mv31a) == 1 and mv31a[0]["old_stop"] == 95.0 and mv31a[0]["new_stop"] == 105.0
   and mv31a[0]["peak_price"] == 110.0 and mv31a[0]["side"] == "long", str(mv31a))
prot31a_saved = protection_state.load().get("BTC/USDT:USDT")
ok("perp trailing LONG: protection_state atualizada (novo stop_id, TP intacto)",
   prot31a_saved is not None and prot31a_saved.get("stop_price") == 105.0
   and prot31a_saved.get("peak_price") == 110.0 and prot31a_saved.get("tp_id") == "tp-31a"
   and prot31a_saved.get("stop_id") != "stop-31a", str(prot31a_saved))
protection_state.clear_protection("BTC/USDT:USDT")

# 31b. LONG: melhora abaixo do passo mínimo -> NÃO mexe na exchange, só
# persiste o pico avançado.
_reset_fake_perp_trailing()
AUDIT.unlink(missing_ok=True)
prot31b = {"entry_price": 100.0, "take_profit": 130.0, "stop_price": 95.0,
          "size": 2.0, "stop_id": "stop-31b", "tp_id": "tp-31b", "side": "long",
          "profile": "daytrade", "trailing": True, "trail_distance": 5.0,
          "peak_price": 100.0}
eng31b = _eng31()
protection_state.set_protection("ETH/USDT:USDT", entry_price=100.0, take_profit=130.0,
                                stop_price=95.0, size=2.0, stop_id="stop-31b",
                                tp_id="tp-31b", side="long", profile="daytrade",
                                trailing=True, trail_distance=5.0, peak_price=100.0)
eng31b._update_perp_trailing_stop("ETH/USDT:USDT", prot31b, 100.05)  # avanco minusculo
ok("perp trailing LONG: melhora insuficiente -> NENHUMA chamada de exchange",
   len(eng31b.client.calls) == 0, str(eng31b.client.calls))
prot31b_saved = protection_state.load().get("ETH/USDT:USDT")
ok("perp trailing LONG: pico avancado ainda assim persistido (stop_price intacto)",
   prot31b_saved.get("peak_price") == 100.05 and prot31b_saved.get("stop_price") == 95.0,
   str(prot31b_saved))
protection_state.clear_protection("ETH/USDT:USDT")

# 31c. LONG: preço já rompeu o nível trailed -> NADA de exchange (perp
# sempre tem stop REAL — quem dispara é a própria ordem/exchange, não este
# método; _check_perp_exits detecta no ciclo seguinte).
_reset_fake_perp_trailing()
prot31c = {"entry_price": 100.0, "take_profit": 130.0, "stop_price": 95.0,
          "size": 2.0, "stop_id": "stop-31c", "tp_id": "tp-31c", "side": "long",
          "profile": "daytrade", "trailing": True, "trail_distance": 5.0,
          "peak_price": 100.0}
eng31c = _eng31()
eng31c._update_perp_trailing_stop("SOL/USDT:USDT", prot31c, 80.0)  # bem abaixo do stop
ok("perp trailing LONG: nivel ja rompido -> nenhuma chamada de exchange (deixa a ordem real disparar)",
   len(eng31c.client.calls) == 0, str(eng31c.client.calls))

# 31d. SHORT: preço avança a favor (cai) -> stop desce de verdade.
_reset_fake_perp_trailing()
AUDIT.unlink(missing_ok=True)
prot31d = {"entry_price": 100.0, "take_profit": 70.0, "stop_price": 105.0,
          "size": 3.0, "stop_id": "stop-31d", "tp_id": "tp-31d", "side": "short",
          "profile": "daytrade", "trailing": True, "trail_distance": 5.0,
          "peak_price": 100.0}
FakePerpTrailing.ORDER_RESPONSES = {
    "stop-31d": {"id": "stop-31d", "status": "open", "filled": 0.0,
                "triggerPrice": "105.0"},
}
eng31d = _eng31()
eng31d._update_perp_trailing_stop("XRP/USDT:USDT", prot31d, 90.0)
ok("perp trailing SHORT: cancela o stop antigo", ("cancel_order", "stop-31d", "XRP/USDT:USDT") in eng31d.client.calls)
ok("perp trailing SHORT: arma o novo stop no preco certo (fundo+trail = 90+5=95), side ORIGEM='sell'",
   any(c[0] == "set_stop_loss" and c[1] == "sell" and abs(c[3] - 95.0) < 1e-9
       for c in eng31d.client.calls), str(eng31d.client.calls))
ev31d = [json.loads(l) for l in AUDIT.read_text(encoding="utf-8").splitlines()]
mv31d = [e for e in ev31d if e["event"] == "trailing_stop_moved" and e["symbol"] == "XRP/USDT:USDT"]
ok("perp trailing SHORT: trailing_stop_moved auditado (old=105, new=95, side=short)",
   len(mv31d) == 1 and mv31d[0]["old_stop"] == 105.0 and mv31d[0]["new_stop"] == 95.0
   and mv31d[0]["side"] == "short", str(mv31d))

# 31e. arquivo STALE curado: gatilho real na exchange é MELHOR (mais alto,
# pra long) que o valor salvo -> cura o registro antes de decidir.
_reset_fake_perp_trailing()
AUDIT.unlink(missing_ok=True)
prot31e = {"entry_price": 100.0, "take_profit": 140.0, "stop_price": 95.0,  # arquivo diz 95 (stale)
          "size": 2.0, "stop_id": "stop-31e", "tp_id": "tp-31e", "side": "long",
          "profile": "daytrade", "trailing": True, "trail_distance": 5.0,
          "peak_price": 100.0}
FakePerpTrailing.ORDER_RESPONSES = {
    "stop-31e": {"id": "stop-31e", "status": "open", "filled": 0.0,
                "triggerPrice": "98.0"},  # exchange real ja estava em 98 (move anterior nao persistiu)
}
eng31e = _eng31()
eng31e._update_perp_trailing_stop("DOGE/USDT:USDT", prot31e, 110.0)
ev31e = [json.loads(l) for l in AUDIT.read_text(encoding="utf-8").splitlines()]
mv31e = [e for e in ev31e if e["event"] == "trailing_stop_moved" and e["symbol"] == "DOGE/USDT:USDT"]
ok("perp trailing: arquivo stale curado com o gatilho REAL (old_stop=98, nao os 95 do arquivo)",
   len(mv31e) == 1 and mv31e[0]["old_stop"] == 98.0, str(mv31e))

# 31f. stop real já FECHADO (confirmado via fetch_order) ao checar antes de
# mover -> aborta sem tentar cancelar/re-armar nada (deixa
# _check_perp_exits reconciliar o fechamento no proximo ciclo).
_reset_fake_perp_trailing()
prot31f = {"entry_price": 100.0, "take_profit": 130.0, "stop_price": 95.0,
          "size": 2.0, "stop_id": "stop-31f", "tp_id": "tp-31f", "side": "long",
          "profile": "daytrade", "trailing": True, "trail_distance": 5.0,
          "peak_price": 100.0}
FakePerpTrailing.ORDER_RESPONSES = {
    "stop-31f": {"id": "stop-31f", "status": "closed", "filled": 2.0,
                "average": 94.9},
}
eng31f = _eng31()
eng31f._update_perp_trailing_stop("ADA/USDT:USDT", prot31f, 110.0)
ok("perp trailing: stop ja fechado (confirmado) -> nenhum cancel/set_stop_loss tentado",
   not any(c[0] in ("cancel_order", "set_stop_loss") for c in eng31f.client.calls),
   str(eng31f.client.calls))

# 31g. cancelamento do stop antigo FALHA -> aborta o move sem crashar e sem
# tentar armar um stop novo (nao sabe se o antigo ainda protege ou nao).
_reset_fake_perp_trailing()
FakePerpTrailing.CANCEL_SHOULD_FAIL = True
prot31g = {"entry_price": 100.0, "take_profit": 130.0, "stop_price": 95.0,
          "size": 2.0, "stop_id": "stop-31g", "tp_id": "tp-31g", "side": "long",
          "profile": "daytrade", "trailing": True, "trail_distance": 5.0,
          "peak_price": 100.0}
FakePerpTrailing.ORDER_RESPONSES = {
    "stop-31g": {"id": "stop-31g", "status": "open", "filled": 0.0,
                "triggerPrice": "95.0"},
}
eng31g = _eng31()
try:
    eng31g._update_perp_trailing_stop("LINK/USDT:USDT", prot31g, 110.0)
    nao_propagou31g = True
except Exception:
    nao_propagou31g = False
ok("perp trailing: falha ao cancelar o stop antigo nao propaga (isolamento)", nao_propagou31g)
ok("perp trailing: falha no cancelamento -> nenhum set_stop_loss tentado (nao sabe se o antigo ainda vale)",
   not any(c[0] == "set_stop_loss" for c in eng31g.client.calls), str(eng31g.client.calls))
FakePerpTrailing.CANCEL_SHOULD_FAIL = False

# 31h. cancelamento sucede mas o NOVO stop falha -> re-arma no preco ANTIGO
# (nunca posicao sem stop nenhum); sucesso do re-arm audita
# trailing_move_failed_stop_rearmed.
_reset_fake_perp_trailing()
AUDIT.unlink(missing_ok=True)
FakePerpTrailing.SET_STOP_RESPONSES = [RuntimeError("novo stop rejeitado (simulado)"),
                                       {"id": "stop-31h-rearmed"}]
prot31h = {"entry_price": 100.0, "take_profit": 130.0, "stop_price": 95.0,
          "size": 2.0, "stop_id": "stop-31h", "tp_id": "tp-31h", "side": "long",
          "profile": "daytrade", "trailing": True, "trail_distance": 5.0,
          "peak_price": 100.0}
FakePerpTrailing.ORDER_RESPONSES = {
    "stop-31h": {"id": "stop-31h", "status": "open", "filled": 0.0,
                "triggerPrice": "95.0"},
}
eng31h = _eng31()
eng31h._update_perp_trailing_stop("DOT/USDT:USDT", prot31h, 110.0)
ev31h = [json.loads(l) for l in AUDIT.read_text(encoding="utf-8").splitlines()]
rearm31h = [e for e in ev31h if e["event"] == "trailing_move_failed_stop_rearmed"
           and e["symbol"] == "DOT/USDT:USDT"]
ok("perp trailing: novo stop falha -> re-arma no preco ANTIGO (95) e audita",
   len(rearm31h) == 1 and rearm31h[0]["stop_price"] == 95.0, str(rearm31h))
prot31h_saved = protection_state.load().get("DOT/USDT:USDT")
ok("perp trailing: protecao persistida com o stop_id do RE-ARM (nao perde o rastreio)",
   prot31h_saved is not None and prot31h_saved.get("stop_id") == "stop-31h-rearmed"
   and prot31h_saved.get("stop_price") == 95.0, str(prot31h_saved))
protection_state.clear_protection("DOT/USDT:USDT")

# 31i. sem stop_id/size rastreado -> aborta sem crashar (defesa, nao deveria
# acontecer numa proteção real persistida pelo executor).
_reset_fake_perp_trailing()
prot31i = {"entry_price": 100.0, "take_profit": 130.0, "stop_price": 95.0,
          "size": None, "stop_id": None, "tp_id": None, "side": "long",
          "profile": "daytrade", "trailing": True, "trail_distance": 5.0,
          "peak_price": 100.0}
eng31i = _eng31()
try:
    eng31i._update_perp_trailing_stop("MATIC/USDT:USDT", prot31i, 110.0)
    nao_propagou31i = True
except Exception:
    nao_propagou31i = False
ok("perp trailing: sem stop_id/size -> aborta sem crashar", nao_propagou31i)

engine_mod.BybitClient = FakeEthQuebrado


print()
fails = [n for n, c in PASS if not c]
print(f"{len(PASS) - len(fails)}/{len(PASS)} testes passaram")
sys.exit(1 if fails else 0)
