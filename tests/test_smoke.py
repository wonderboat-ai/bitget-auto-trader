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
# Usa tests/_guard.py desde 18/08/2026. ANTES, esta suíte e a test_ciclo.py
# gravavam o backup no MESMO nome (audit.jsonl.bak-teste): quando a restauração
# do smoke falhava por lock do Dropbox (erro conhecido no Windows), a suíte
# seguinte copiava a trilha JÁ CONTAMINADA por cima do único backup e restaurava
# essa versão — perda definitiva da trilha real. Aconteceu de verdade em
# 18/08/2026 com a trilha do PC1. O guard garante nome de backup por suíte e
# nunca sobrescreve um backup pendente. Ver tests/_guard.py.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _guard import FileGuard  # noqa: E402

AUDIT = ROOT / "logs" / "audit.jsonl"
_GUARD_AUDIT = FileGuard(AUDIT, "smoke")

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

import src.execution.protection_state as protection_state  # noqa: E402
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


# A suíte inteira, daqui pra frente, foi reescrita pro port Bitget
# (20/08/2026). O caminho SPOT (TP por software, _check_spot_exits,
# executor spot-only) não foi portado: Engine.__init__ RECUSA
# market.type=="spot" com RuntimeError, então o antigo monkeypatch global
# "força spot em toda Engine() construída daqui pra baixo" deixou de fazer
# sentido — construiria um Engine() que não existe em produção. Cada
# Engine() agora usa o market_type REAL do YAML (perp) por padrão.
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
engine_mod.BitgetClient = FakeEthQuebrado  # nunca toca a rede
eng = engine_mod.Engine(dry_run=True)
# O YAML real hoje (18/08/2026) tem só 'swing' habilitado (daytrade desligado
# por decisão de estratégia — ver CLAUDE.md) — um símbolo só teria 1 avaliação
# por ciclo, e esta seção existe pra provar EXCLUSIVIDADE (2 perfis competindo
# pelo mesmo símbolo no mesmo ciclo). Habilita 'daytrade' só NESTA instância,
# em memória, sem tocar o arquivo real — mesmo padrão de override pontual que
# outras seções já usam pra isolar o que estão testando do que o YAML ao vivo
# diz no momento.
eng.cfg["trading"]["profiles"]["daytrade"]["enabled"] = True
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



# ---------- 7. executor: proteção não confirma -> fecha posição (nunca nua) ----------
# Reescrito pro port Bitget (20/08/2026): não existe mais um passo separado
# "armar o stop" que pode falhar sozinho — a proteção nasce ANEXADA à entrada.
# O que pode falhar agora é a CONFIRMAÇÃO (fetch_position_tpsl não encontra a
# tpsl, ou encontra uma sem perna de stop) — a regra "nunca posição nua"
# continua igual: sem confirmar, fecha a posição na hora.
class FakeLive:
    is_testnet = True
    calls = []

    def set_leverage(self, *a, **k):
        pass

    def create_order(self, symbol, side, amount, order_type="market", price=None, params=None):
        FakeLive.calls.append(("create_order", side, order_type, dict(params or {})))
        return {"id": f"o{len(FakeLive.calls)}"}

    def fetch_order(self, order_id, symbol):
        return {"average": None, "price": None}

    def amount_to_precision(self, symbol, amount):
        return amount

    def fetch_position_tpsl(self, symbol):
        return None  # tpsl nunca aparece -> proteção nunca confirma


FakeLive.calls = []
ex = Executor(FakeLive(), dry_run=False)
try:
    ex.execute(sig, d_test)
    esc = False
except RuntimeError:
    esc = True
create_calls7 = [c for c in FakeLive.calls if c[0] == "create_order"]
reduce_close = [c for c in create_calls7 if c[3].get("reduceOnly")]
ok("posicao fechada apos protecao nao confirmar (reduceOnly)", len(reduce_close) == 1, str(FakeLive.calls))
ok("2 ordens: entrada + fechamento de emergencia", len(create_calls7) == 2, str(create_calls7))
ok("erro de protecao nao confirmada escalado ao chamador", esc)
ev = [json.loads(l) for l in AUDIT.read_text(encoding="utf-8").splitlines()]
ok("naked_position_close auditado",
   len([e for e in ev if e["event"] == "naked_position_close"]) == 1)

# ---------- 8. backtest sintetico ----------
res = Backtester(cfg, profile="daytrade").run("BTC/USDT:USDT", "15m", make_candles(n=1200))
m = compute_metrics(res)
ok("backtest roda e fecha trades", m.n_trades > 0, f"trades={m.n_trades} ret={m.total_return_pct:.2f}%")
ok("curva de equity termina no end_equity", abs(res.equity_curve[-1][1] - res.end_equity) < 1e-9)



# ---------- 14. risk_manager: teto de capital com 0 explícito veta (nunca aprova size=0) ----------
cfg_zero = copy.deepcopy(cfg)
cfg_zero["per_trade"]["max_notional_pct_equity"] = 0.0
AUDIT.unlink(missing_ok=True)
d_zero = RiskManager(cfg_zero, environment="testnet").evaluate(
    sig_normal, state, funding_rate=-0.005, data_age_sec=0)
ok("teto de capital = 0 explicito VETA (nunca aprova entrada de tamanho zero)",
   not d_zero.approved and "zerou o tamanho" in d_zero.reason, d_zero.reason)



# ---------- 18. executor: entry_price confirma via fetch_order antes de usar o preco do sinal ----------
# Achado 19/07 (Bybit) — continua valendo na Bitget, e ainda mais central:
# `create_order` na Bitget responde SÓ {orderId, clientOid} (medido ao vivo em
# 20/08), então average/price vêm vazios SEMPRE na resposta de criação, e o
# fetch_order de confirmação deixou de ser fallback raro pra virar o único
# caminho pro preço real do fill.
class FakePerpEntryConfirmavel:
    is_testnet = True

    def __init__(self, real_fill):
        self.calls = []
        self.real_fill = real_fill

    def set_leverage(self, symbol, leverage):
        self.calls.append(("set_leverage", leverage))

    def create_order(self, symbol, side, amount, order_type="market", price=None, params=None):
        self.calls.append(("create_order", side, amount, dict(params or {}), price))
        return {"id": "entry-18"}  # sem average/price, igual ao comportamento real medido

    def fetch_order(self, order_id, symbol):
        self.calls.append(("fetch_order", order_id))
        return {"average": self.real_fill, "price": None, "status": "closed"}

    def amount_to_precision(self, symbol, amount):
        return amount

    def fetch_position_tpsl(self, symbol):
        return {"id": "tpsl-18", "stop_trigger": 95.0, "tp_trigger": 110.0, "status": "pending"}

    def move_stop_loss(self, order_id, symbol, new_stop):
        self.calls.append(("move_stop_loss", new_stop))
        return {"id": order_id}

    def move_take_profit(self, order_id, symbol, new_tp):
        self.calls.append(("move_take_profit", new_tp))
        return {"id": order_id}


sig18 = Signal(symbol="BTC/USDT:USDT", direction=Direction.LONG, conviction=0.8,
               entry_price=100.0, stop_price=95.0, take_profit=110.0,
               profile="daytrade", rationale="teste confirmacao de fill")
d18 = RiskManager(cfg, environment="testnet").evaluate(sig18, state, funding_rate=-0.005, data_age_sec=0)

AUDIT.unlink(missing_ok=True)
protection_state.clear_protection("BTC/USDT:USDT")
fec18 = FakePerpEntryConfirmavel(real_fill=101.5)  # diferente do entry_price do sinal (100.0)
Executor(fec18, dry_run=False).execute(sig18, d18)
ev18a = [json.loads(l) for l in AUDIT.read_text(encoding="utf-8").splitlines()]
oe18a = [e for e in ev18a if e["event"] == "order_executed"]
ok("entry_price sem average/price na criacao: confirma via fetch_order (nao usa o preco do sinal)",
   len(oe18a) == 1 and oe18a[0]["entry_price"] == 101.5,
   f"entry_price auditado={oe18a[0]['entry_price'] if oe18a else '-'}")
protection_state.clear_protection("BTC/USDT:USDT")


class FakePerpEntrySemConfirmacao(FakePerpEntryConfirmavel):
    """fetch_order tambem falha (ex.: rate limit) -- cai no fallback antigo
    (preco do sinal), nao trava nem inventa numero."""

    def fetch_order(self, order_id, symbol):
        raise RuntimeError("rate limit (simulado)")


AUDIT.unlink(missing_ok=True)
fesc18 = FakePerpEntrySemConfirmacao(real_fill=101.5)
Executor(fesc18, dry_run=False).execute(sig18, d18)
ev18b = [json.loads(l) for l in AUDIT.read_text(encoding="utf-8").splitlines()]
oe18b = [e for e in ev18b if e["event"] == "order_executed"]
ok("fetch_order tambem falha: cai no fallback do preco do sinal (nunca trava, nunca inventa)",
   len(oe18b) == 1 and oe18b[0]["entry_price"] == sig18.entry_price,
   f"entry_price auditado={oe18b[0]['entry_price'] if oe18b else '-'}")
unc18b = [e for e in ev18b if e["event"] == "entry_price_unconfirmed"]
ok("fallback pro preco do sinal e AUDITADO (antes era 100% mudo)", len(unc18b) == 1)
protection_state.clear_protection("BTC/USDT:USDT")


# ---------- 19. executor: stop/TP re-ancorados no preco REAL do fill (bug #26) ----------
# Achado 20/07 (Bybit), agora resolvido de forma DIFERENTE: como a proteção já
# nasce anexada à entrada (calculada sobre signal.entry_price, o preço do
# ÚLTIMO CANDLE FECHADO — não o preço ao vivo), ela pode nascer deslocada do
# fill real. A correção deixou de ser "calcular certo antes de armar" (não dá
# mais, a ordem já foi enviada) e virou "corrigir DEPOIS via move_stop_loss/
# move_take_profit" — mesma distância de risco preservada, só re-centralizada
# no preço que realmente aconteceu.
sig19 = Signal(symbol="BTC/USDT:USDT", direction=Direction.LONG, conviction=0.8,
               entry_price=100.0, stop_price=95.0, take_profit=110.0,
               profile="daytrade", rationale="teste re-ancoragem por drift")
d19 = RiskManager(cfg, environment="testnet").evaluate(sig19, state, funding_rate=-0.005, data_age_sec=0)

AUDIT.unlink(missing_ok=True)
protection_state.clear_protection("BTC/USDT:USDT")
fsd19 = FakePerpEntryConfirmavel(real_fill=101.5)  # 1.5 acima do entry_price do sinal
Executor(fsd19, dry_run=False).execute(sig19, d19)
drift19 = fsd19.real_fill - sig19.entry_price
esperado_stop19 = d19.stop_price + drift19
esperado_tp19 = sig19.take_profit + drift19

moves19 = [c for c in fsd19.calls if c[0] in ("move_stop_loss", "move_take_profit")]
ok("re-ancoragem: move_stop_loss chamado com o stop deslocado pelo drift",
   any(c[0] == "move_stop_loss" and abs(c[1] - esperado_stop19) < 1e-9 for c in moves19),
   str(moves19))
ok("re-ancoragem: move_take_profit chamado com o TP deslocado pelo drift",
   any(c[0] == "move_take_profit" and abs(c[1] - esperado_tp19) < 1e-9 for c in moves19),
   str(moves19))

ev19 = [json.loads(l) for l in AUDIT.read_text(encoding="utf-8").splitlines()]
oe19 = [e for e in ev19 if e["event"] == "order_executed"]
ok("order_executed audita stop_price/take_profit ja re-ancorados (nao o do sinal)",
   len(oe19) == 1 and abs(oe19[0]["stop_price"] - esperado_stop19) < 1e-9
   and abs(oe19[0]["take_profit"] - esperado_tp19) < 1e-9, str(oe19))
ok("TP re-ancorado: sempre do lado lucrativo da entrada real",
   esperado_tp19 > fsd19.real_fill)

prot19 = protection_state.load().get("BTC/USDT:USDT", {})
ok("protection_state salva o TP re-ancorado (nao o do sinal) para o fechamento auditado",
   abs(prot19.get("take_profit", 0) - esperado_tp19) < 1e-9)
protection_state.clear_protection("BTC/USDT:USDT")


class FakePerpEntryReancoragemFalha(FakePerpEntryConfirmavel):
    """move_stop_loss falha na re-ancoragem -- a posição JÁ está protegida
    (a tpsl nasceu com os valores do sinal), então isto NÃO fecha nada:
    audita e segue, gatilhos ficam deslocados pelo drift até o próximo
    trailing/ciclo corrigir."""

    def move_stop_loss(self, order_id, symbol, new_stop):
        raise RuntimeError("modificacao rejeitada (simulado)")


AUDIT.unlink(missing_ok=True)
protection_state.clear_protection("BTC/USDT:USDT")
frf19 = FakePerpEntryReancoragemFalha(real_fill=101.5)
Executor(frf19, dry_run=False).execute(sig19, d19)
ev19b = [json.loads(l) for l in AUDIT.read_text(encoding="utf-8").splitlines()]
ok("falha na re-ancoragem NAO derruba a entrada (posicao ja protegida pela tpsl original)",
   len([e for e in ev19b if e["event"] == "order_executed"]) == 1)
ok("falha na re-ancoragem e AUDITADA (protection_reanchor_failed)",
   len([e for e in ev19b if e["event"] == "protection_reanchor_failed"]) >= 1)
protection_state.clear_protection("BTC/USDT:USDT")

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
import src.exchange.bitget_client as bitget_client_mod  # noqa: E402


class FakeCcxtDerivativesOk:
    def fetch_funding_rate(self, symbol, params=None):
        return {"fundingRate": -0.0001, "nextFundingRate": None, "fundingDatetime": "2026-07-22T22:00:00Z"}

    def fetch_open_interest(self, symbol, params=None):
        return {"openInterestAmount": 53830.16, "datetime": "2026-07-22T22:00:00Z"}

    def fetch_long_short_ratio_history(self, symbol, timeframe=None, limit=None, params=None):
        return [{"longShortRatio": 1.30, "datetime": "2026-07-22T21:00:00Z"},
                {"longShortRatio": 1.31, "datetime": "2026-07-22T22:00:00Z"}]


bc27 = bitget_client_mod.BitgetClient.__new__(bitget_client_mod.BitgetClient)
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


bc27n = bitget_client_mod.BitgetClient.__new__(bitget_client_mod.BitgetClient)
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


bc27v = bitget_client_mod.BitgetClient.__new__(bitget_client_mod.BitgetClient)
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


bc27f = bitget_client_mod.BitgetClient.__new__(bitget_client_mod.BitgetClient)
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
ok("BitgetClient real expõe fetch_derivatives_funding_rate/fetch_open_interest/fetch_long_short_ratio",
   # checa a classe REAL via bitget_client_mod, não engine_mod.BitgetClient —
   # este último já foi monkeypatchado pra várias Fakes por seções
   # anteriores deste arquivo e nunca é restaurado entre seções.
   all(hasattr(bitget_client_mod.BitgetClient, m) for m in (
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


engine_mod.BitgetClient = FakeClient27Contador
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
engine_mod.BitgetClient = FakeEthQuebrado
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


from src.strategy.deterministic import StrategyParams  # noqa: E402

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

# A prova de ponta a ponta original (backtest sintético com trailing=True,
# variável `trail_trades`) vivia na seção 20g — deletada no port pra Bitget
# porque testava `_update_trailing_stop`/`_execute_spot_exit`, mecânica
# EXCLUSIVA de spot (cancelar+recriar pra liberar saldo), inalcançável agora
# que Engine recusa market.type=="spot" no boot. As duas asserções acima já
# provam a claim no nível de ESTRATÉGIA (trailing=True ainda calcula
# take_profit fixo); a prova de que o backtester honra os dois mecanismos
# juntos (`src/backtest/backtester.py`, exchange-agnóstico, não tocado neste
# port) não foi reconstruída aqui — risco de reproduzir de memória uma forma
# de candle sintético e mascarar um bug em vez de provar o comportamento.



# ---------- 30. perp: fechamento auditado com fill REAL (20/08/2026, port pra
# Bitget — reescrita completa). Na Bitget não existe mais "duas ordens,
# cancelar a irmã órfã": stop e TP são a MESMA ordem (tpsl), e a exchange a
# cancela sozinha quando a posição zera (medido ao vivo). O que muda:
# (1) uma única leitura por fetch_order(tpsl_id) confirma o fill quando a
#     ordem ainda existe;
# (2) se a tpsl já foi cancelada pela exchange, fetch_last_close_fill busca o
#     preço real nos trades da conta (2a fonte);
# (3) o motivo (stop_loss/take_profit) é derivado por PROXIMIDADE DE PREÇO,
#     não por qual ordem disparou — correção de um bug achado NESTA sessão:
#     com uma ordem só, o laço antigo (stop_id/tp_id) casaria SEMPRE no slot
#     do stop, rotulando até trades VENCEDORES como stop_loss e acionando
#     cooldown depois de acertar. ----------
class FakePerpClose:
    is_testnet = True
    ORDER_RESPONSES: dict = {}
    CLOSE_FILL: dict | None = None

    def __init__(self, *a, **k):
        self.calls = []

    def fetch_order(self, order_id, symbol):
        self.calls.append(("fetch_order", order_id, symbol))
        return type(self).ORDER_RESPONSES.get(
            order_id, {"id": order_id, "status": "open", "filled": 0.0,
                       "average": None, "price": None})

    def fetch_last_close_fill(self, symbol, since_ms, side):
        self.calls.append(("fetch_last_close_fill", symbol, since_ms, side))
        return type(self).CLOSE_FILL


def _reset_fake_perp_close():
    FakePerpClose.ORDER_RESPONSES = {}
    FakePerpClose.CLOSE_FILL = None


# 30a. tpsl confirma fechamento perto do STOP -> reason=stop_loss, fill REAL
# (nao o alvo), cooldown incrementado, SEM tentativa de cancelamento (nao
# existe ordem irma na Bitget).
_reset_fake_perp_close()
AUDIT.unlink(missing_ok=True)
protection_state.set_protection("BTC/USDT:USDT", entry_price=100.0, take_profit=110.0,
                                stop_price=95.0, size=1.0, stop_id="tpsl-30a", tp_id=None,
                                opened_ts=1_700_000_000_000)
FakePerpClose.ORDER_RESPONSES = {
    "tpsl-30a": {"id": "tpsl-30a", "status": "closed", "filled": 1.0,
                 "average": 94.8, "price": 94.8},
}
engine_mod.BitgetClient = FakePerpClose
eng30a = engine_mod.Engine(dry_run=False)
eng30a.market_type = "perp"
eng30a._open_symbols = set()
eng30a._check_perp_exits()
ev30a = [json.loads(l) for l in AUDIT.read_text(encoding="utf-8").splitlines()]
tc30a = [e for e in ev30a if e["event"] == "trade_closed" and e["symbol"] == "BTC/USDT:USDT"]
ok("perp: tpsl confirma fill perto do stop -> reason=stop_loss com o fill REAL (nao o alvo)",
   len(tc30a) == 1 and tc30a[0]["reason"] == "stop_loss"
   and tc30a[0]["exit_price"] == 94.8 and tc30a[0]["exit_price_source"] == "tpsl_order_fill"
   and abs(tc30a[0]["pnl_usdt"] - (94.8 - 100.0) * 1.0) < 1e-9, str(tc30a))
cd30a = [e for e in ev30a if e["event"] == "cooldown_triggered" and e["symbol"] == "BTC/USDT:USDT"]
ok("perp: stop confirmado aciona cooldown", len(cd30a) == 1)
ok("perp: proteção limpa após reconciliação", "BTC/USDT:USDT" not in protection_state.load())
ok("perp: NAO tenta cancelar nada (nao existe ordem irma na Bitget)",
   not any(c[0] == "cancel_order" for c in eng30a.client.calls), str(eng30a.client.calls))

# 30b. tpsl confirma fechamento perto do TP -> reason=take_profit, cooldown
# RESETADO (nao incrementado).
_reset_fake_perp_close()
AUDIT.unlink(missing_ok=True)
protection_state.set_protection("ETH/USDT:USDT", entry_price=1900.0, take_profit=1930.0,
                                stop_price=1880.0, size=0.5, stop_id="tpsl-30b", tp_id=None)
FakePerpClose.ORDER_RESPONSES = {
    "tpsl-30b": {"id": "tpsl-30b", "status": "closed", "filled": 0.5,
                 "average": 1930.5, "price": 1930.5},
}
eng30b = engine_mod.Engine(dry_run=False)
eng30b.market_type = "perp"
eng30b._open_symbols = set()
eng30b._check_perp_exits()
ev30b = [json.loads(l) for l in AUDIT.read_text(encoding="utf-8").splitlines()]
tc30b = [e for e in ev30b if e["event"] == "trade_closed" and e["symbol"] == "ETH/USDT:USDT"]
ok("perp: tpsl confirma fill perto do TP -> reason=take_profit com o fill REAL",
   len(tc30b) == 1 and tc30b[0]["reason"] == "take_profit"
   and tc30b[0]["exit_price"] == 1930.5 and tc30b[0]["exit_price_source"] == "tpsl_order_fill"
   and abs(tc30b[0]["pnl_usdt"] - (1930.5 - 1900.0) * 0.5) < 1e-9, str(tc30b))

# 30c. tpsl NAO confirma (ainda 'open' -- leitura atrasada) E
# fetch_last_close_fill tambem nao acha nada -> trade_closed aproximado
# (reason=external_close_unconfirmed, exit_price=stop_price alvo).
_reset_fake_perp_close()
AUDIT.unlink(missing_ok=True)
protection_state.set_protection("SOL/USDT:USDT", entry_price=150.0, take_profit=160.0,
                                stop_price=140.0, size=2.0, stop_id="tpsl-30c", tp_id=None)
FakePerpClose.ORDER_RESPONSES = {
    "tpsl-30c": {"id": "tpsl-30c", "status": "open", "filled": 0.0,
                 "average": None, "price": None},
}
FakePerpClose.CLOSE_FILL = None
eng30c = engine_mod.Engine(dry_run=False)
eng30c.market_type = "perp"
eng30c._open_symbols = set()
eng30c._check_perp_exits()
ev30c = [json.loads(l) for l in AUDIT.read_text(encoding="utf-8").splitlines()]
tc30c = [e for e in ev30c if e["event"] == "trade_closed" and e["symbol"] == "SOL/USDT:USDT"]
ok("perp: nem tpsl nem trades confirmam -> trade_closed aproximado (external_close_unconfirmed)",
   len(tc30c) == 1 and tc30c[0]["reason"] == "external_close_unconfirmed"
   and tc30c[0]["exit_price"] == 140.0
   and tc30c[0]["exit_price_source"] == "stop_price_target_approx", str(tc30c))

# 30d. tpsl foi CANCELADA pela exchange (status=canceled -- comportamento real
# medido em 20/08: a Bitget cancela a tpsl sozinha quando a posição zera), mas
# fetch_last_close_fill ACHA o trade de fechamento -> confirma via essa 2a
# fonte, reason derivado por proximidade de preço.
_reset_fake_perp_close()
AUDIT.unlink(missing_ok=True)
protection_state.set_protection("ADA/USDT:USDT", entry_price=0.50, take_profit=0.55,
                                stop_price=0.45, size=100.0, stop_id="tpsl-30d", tp_id=None)
FakePerpClose.ORDER_RESPONSES = {
    "tpsl-30d": {"id": "tpsl-30d", "status": "canceled", "filled": 0.0,
                 "average": None, "price": None},
}
FakePerpClose.CLOSE_FILL = {"average": 0.549, "filled": 100.0, "status": "closed"}
eng30d = engine_mod.Engine(dry_run=False)
eng30d.market_type = "perp"
eng30d._open_symbols = set()
eng30d._check_perp_exits()
ev30d = [json.loads(l) for l in AUDIT.read_text(encoding="utf-8").splitlines()]
tc30d = [e for e in ev30d if e["event"] == "trade_closed" and e["symbol"] == "ADA/USDT:USDT"]
ok("perp: tpsl cancelada pela exchange -> confirma via fetch_last_close_fill (2a fonte)",
   len(tc30d) == 1 and tc30d[0]["exit_price"] == 0.549
   and tc30d[0]["exit_price_source"] == "close_trade_fill"
   and tc30d[0]["reason"] == "take_profit",  # 0.549 mais perto de 0.55 que de 0.45
   str(tc30d))

# 30e. backfill na primeira vez que uma posição perp é vista sem registro em
# protection_state (cobre posição real aberta ANTES do fix existir).
from src.logger import audit as _audit30  # noqa: E402
_reset_fake_perp_close()
AUDIT.unlink(missing_ok=True)
_audit30("order_executed", symbol="XRP/USDT:USDT", side="buy", size=200.0,
        protect_size=200.0, entry_price=0.6, stop_price=0.57, take_profit=0.66,
        entry_id="entry-30e", stop_id="tpsl-30e", tp_id=None,
        profile="daytrade", trailing=False, opened_ts=1_700_000_000_000, testnet=False)
eng30e = engine_mod.Engine(dry_run=False)
eng30e.market_type = "perp"
eng30e._open_symbols = {"XRP/USDT:USDT"}  # AINDA aberta -> so backfill, sem reconciliar fechamento
eng30e._check_perp_exits()
backfilled30e = protection_state.load().get("XRP/USDT:USDT")
ok("perp: posicao vista sem protecao e recuperada via backfill_from_audit (incl. opened_ts)",
   backfilled30e is not None and backfilled30e.get("stop_id") == "tpsl-30e"
   and backfilled30e.get("entry_price") == 0.6
   and backfilled30e.get("opened_ts") == 1_700_000_000_000,
   str(backfilled30e))
FakePerpClose.ORDER_RESPONSES = {
    "tpsl-30e": {"id": "tpsl-30e", "status": "closed", "filled": 200.0,
                 "average": 0.565, "price": 0.565},
}
eng30e._open_symbols = set()
eng30e._check_perp_exits()
ev30e = [json.loads(l) for l in AUDIT.read_text(encoding="utf-8").splitlines()]
tc30e = [e for e in ev30e if e["event"] == "trade_closed" and e["symbol"] == "XRP/USDT:USDT"]
ok("perp: posicao backfilled fecha normalmente no ciclo seguinte (stop confirmado)",
   len(tc30e) == 1 and tc30e[0]["reason"] == "stop_loss" and tc30e[0]["exit_price"] == 0.565)
protection_state.clear_protection("XRP/USDT:USDT")

# 30f. isolamento por símbolo: erro real na apuração de UM símbolo (size
# corrompido -> TypeError no cálculo de pnl_usdt) não derruba o ciclo nem
# impede o OUTRO símbolo de ser reconciliado.
_reset_fake_perp_close()
AUDIT.unlink(missing_ok=True)
protection_state.set_protection("BAD/USDT:USDT", entry_price=1.0, take_profit=1.2,
                                stop_price=0.9, size=10.0, stop_id="stop-bad-30f", tp_id=None)
_protecoes30f = protection_state.load()
_protecoes30f["BAD/USDT:USDT"]["size"] = "nao-e-numero"  # corrompe o arquivo direto
protection_state._save(_protecoes30f)
protection_state.set_protection("GOOD/USDT:USDT", entry_price=2.0, take_profit=2.4,
                                stop_price=1.8, size=5.0, stop_id="stop-good-30f", tp_id=None)
FakePerpClose.ORDER_RESPONSES = {
    "stop-bad-30f": {"id": "stop-bad-30f", "status": "closed", "filled": 10.0,
                     "average": 0.89, "price": 0.89},
    "stop-good-30f": {"id": "stop-good-30f", "status": "closed", "filled": 5.0,
                      "average": 1.79, "price": 1.79},
}
engine_mod.BitgetClient = FakePerpClose
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

# 30g. spot/dry_run: _check_perp_exits() é no-op de propósito.
_reset_fake_perp_close()
AUDIT.unlink(missing_ok=True)
engine_mod.BitgetClient = FakePerpClose
eng30g_spot = engine_mod.Engine(dry_run=False)
eng30g_spot.market_type = "spot"
protection_state.set_protection("NOOP1/USDT", entry_price=1.0, take_profit=1.1, stop_price=0.9)
eng30g_spot._open_symbols = set()
eng30g_spot._check_perp_exits()
ok("perp: market_type=spot -> _check_perp_exits e no-op (nao mexe na protecao)",
   "NOOP1/USDT" in protection_state.load())
protection_state.clear_protection("NOOP1/USDT")

eng30g_dry = engine_mod.Engine(dry_run=True)
eng30g_dry.market_type = "perp"
protection_state.set_protection("NOOP2/USDT:USDT", entry_price=1.0, take_profit=1.1,
                                stop_price=0.9, stop_id="tpsl-noop2", tp_id=None)
eng30g_dry._open_symbols = set()
eng30g_dry._check_perp_exits()
ok("perp: dry_run=True -> _check_perp_exits e no-op (defesa em profundidade)",
   "NOOP2/USDT:USDT" in protection_state.load())
protection_state.clear_protection("NOOP2/USDT:USDT")

# 30h. executor: entrada REAL em perp persiste protection_state com o
# tpsl_id (wiring ponta a ponta -- sem isto, nada da seção 30 teria dado real
# pra reconciliar, já que a persistência acontece na ENTRADA).
class FakePerpEntry:
    is_testnet = True

    def __init__(self, *a, **k):
        self.calls = []

    def set_leverage(self, symbol, leverage):
        self.calls.append(("set_leverage", leverage))

    def create_order(self, symbol, side, amount, order_type="market", price=None, params=None):
        self.calls.append(("create_order", side, amount, dict(params or {})))
        return {"id": "entry-30h"}

    def fetch_order(self, order_id, symbol):
        return {"id": order_id, "average": 100.0, "price": 100.0, "status": "closed"}

    def fetch_position_tpsl(self, symbol):
        return {"id": "tpsl-30h", "stop_trigger": 95.0, "tp_trigger": 110.0, "status": "pending"}

    def move_stop_loss(self, order_id, symbol, new_stop):
        self.calls.append(("move_stop_loss", new_stop))
        return {"id": order_id}

    def move_take_profit(self, order_id, symbol, new_tp):
        self.calls.append(("move_take_profit", new_tp))
        return {"id": order_id}

    def amount_to_precision(self, symbol, amount):
        return amount


AUDIT.unlink(missing_ok=True)
protection_state.clear_protection("PERPENTRY/USDT:USDT")
sig30h = Signal(symbol="PERPENTRY/USDT:USDT", direction=Direction.LONG, conviction=0.8,
                entry_price=100.0, stop_price=95.0, take_profit=110.0,
                profile="daytrade", rationale="teste entrada perp")
state30h = PortfolioState(equity_usdt=1000.0, day_start_equity=1000.0, peak_equity=1000.0,
                          open_positions=0, total_notional=0.0, aggregate_risk_pct=0.0)
d30h = RiskManager(cfg, environment="testnet").evaluate(sig30h, state30h, funding_rate=None, data_age_sec=0)
ok("pre-requisito 30h: sinal de entrada perp aprovado (senao o resto do teste e vazio)",
   d30h.approved, d30h.reason)
Executor(FakePerpEntry(), dry_run=False, market_type="perp").execute(sig30h, d30h)
prot30h = protection_state.load().get("PERPENTRY/USDT:USDT")
ok("executor: entrada perp persiste protection_state com stop_id=tpsl_id, tp_id=None por construcao",
   prot30h is not None and prot30h.get("stop_id") == "tpsl-30h"
   and prot30h.get("tp_id") is None and prot30h.get("entry_price") == 100.0,
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
engine_mod.BitgetClient = FakeEthQuebrado

# ---------- 31. perp: trailing stop MOVE de verdade -- reescrita para o modelo
# ATÔMICO da Bitget (20/08/2026, validado ao vivo com dinheiro real). Diferente
# da Bybit (cancelar a ordem antiga + criar outra + re-armar se a criação
# falhasse, com uma janela real sem proteção no meio), aqui é UMA chamada --
# move_stop_loss -- que preserva o take-profit e NÃO muda o orderId. Todo o
# aparato de re-arm (trailing_move_failed_stop_rearmed/
# trailing_rearm_stop_failed) deixou de existir: falhar aqui é inofensivo, a
# proteção ANTERIOR continua ativa e o próximo ciclo tenta de novo. Suporta
# LONG e SHORT (mesmo achado que motivou side em protection_state: short
# precisa do sinal invertido em tudo -- pico vira fundo, sobe vira desce). ----------
class FakePerpTrailing(FakePerpClose):
    MOVE_RESPONSES: list = []  # respostas/excecoes de move_stop_loss, na ordem

    def move_stop_loss(self, order_id, symbol, new_stop):
        self.calls.append(("move_stop_loss", order_id, new_stop))
        if type(self).MOVE_RESPONSES:
            resp = type(self).MOVE_RESPONSES.pop(0)
            if isinstance(resp, Exception):
                raise resp
            return resp
        return {"id": order_id}  # orderId NAO muda -- validado ao vivo em 20/08


def _reset_fake_perp_trailing():
    FakePerpTrailing.ORDER_RESPONSES = {}
    FakePerpTrailing.CLOSE_FILL = None
    FakePerpTrailing.MOVE_RESPONSES = []


engine_mod.BitgetClient = FakePerpTrailing


def _eng31():
    e = engine_mod.Engine(dry_run=False)
    e.market_type = "perp"
    return e


# 31a. LONG: preço avança o suficiente -> move_stop_loss chamado com o novo
# stop, pico atualizado, protection_state persistida com o MESMO stop_id
# (atômico: orderId não muda).
_reset_fake_perp_trailing()
AUDIT.unlink(missing_ok=True)
prot31a = {"entry_price": 100.0, "take_profit": 130.0, "stop_price": 95.0,
          "size": 2.0, "stop_id": "tpsl-31a", "tp_id": None, "side": "long",
          "profile": "daytrade", "trailing": True, "trail_distance": 5.0,
          "peak_price": 100.0}
FakePerpTrailing.ORDER_RESPONSES = {
    "tpsl-31a": {"id": "tpsl-31a", "status": "open", "filled": 0.0,
                "triggerPrice": "95.0"},
}
eng31a = _eng31()
eng31a._update_perp_trailing_stop("BTC/USDT:USDT", prot31a, 110.0)
ok("perp trailing LONG: move_stop_loss chamado no preco certo (peak-trail = 110-5=105)",
   any(c[0] == "move_stop_loss" and c[1] == "tpsl-31a" and abs(c[2] - 105.0) < 1e-9
       for c in eng31a.client.calls), str(eng31a.client.calls))
ok("perp trailing LONG: NAO cancela nem recria (modelo atomico, uma chamada so)",
   not any(c[0] == "cancel_order" for c in eng31a.client.calls))
ev31a = [json.loads(l) for l in AUDIT.read_text(encoding="utf-8").splitlines()]
mv31a = [e for e in ev31a if e["event"] == "trailing_stop_moved" and e["symbol"] == "BTC/USDT:USDT"]
ok("perp trailing LONG: trailing_stop_moved auditado (old=95, new=105, peak=110)",
   len(mv31a) == 1 and mv31a[0]["old_stop"] == 95.0 and mv31a[0]["new_stop"] == 105.0
   and mv31a[0]["peak_price"] == 110.0 and mv31a[0]["side"] == "long", str(mv31a))
prot31a_saved = protection_state.load().get("BTC/USDT:USDT")
ok("perp trailing LONG: protection_state atualizada (MESMO stop_id -- atomico nao troca id)",
   prot31a_saved is not None and prot31a_saved.get("stop_price") == 105.0
   and prot31a_saved.get("peak_price") == 110.0
   and prot31a_saved.get("stop_id") == "tpsl-31a", str(prot31a_saved))
protection_state.clear_protection("BTC/USDT:USDT")

# 31b. LONG: melhora abaixo do passo mínimo -> NÃO mexe na exchange, só
# persiste o pico avançado.
_reset_fake_perp_trailing()
AUDIT.unlink(missing_ok=True)
prot31b = {"entry_price": 100.0, "take_profit": 130.0, "stop_price": 95.0,
          "size": 2.0, "stop_id": "tpsl-31b", "tp_id": None, "side": "long",
          "profile": "daytrade", "trailing": True, "trail_distance": 5.0,
          "peak_price": 100.0}
eng31b = _eng31()
protection_state.set_protection("ETH/USDT:USDT", entry_price=100.0, take_profit=130.0,
                                stop_price=95.0, size=2.0, stop_id="tpsl-31b",
                                tp_id=None, side="long", profile="daytrade",
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
# sempre tem stop REAL -- quem dispara é a própria ordem/exchange).
_reset_fake_perp_trailing()
prot31c = {"entry_price": 100.0, "take_profit": 130.0, "stop_price": 95.0,
          "size": 2.0, "stop_id": "tpsl-31c", "tp_id": None, "side": "long",
          "profile": "daytrade", "trailing": True, "trail_distance": 5.0,
          "peak_price": 100.0}
eng31c = _eng31()
eng31c._update_perp_trailing_stop("SOL/USDT:USDT", prot31c, 80.0)  # bem abaixo do stop
ok("perp trailing LONG: nivel ja rompido -> nenhuma chamada de exchange",
   len(eng31c.client.calls) == 0, str(eng31c.client.calls))

# 31d. SHORT: preço avança a favor (cai) -> stop desce de verdade.
_reset_fake_perp_trailing()
AUDIT.unlink(missing_ok=True)
prot31d = {"entry_price": 100.0, "take_profit": 70.0, "stop_price": 105.0,
          "size": 3.0, "stop_id": "tpsl-31d", "tp_id": None, "side": "short",
          "profile": "daytrade", "trailing": True, "trail_distance": 5.0,
          "peak_price": 100.0}
FakePerpTrailing.ORDER_RESPONSES = {
    "tpsl-31d": {"id": "tpsl-31d", "status": "open", "filled": 0.0,
                "triggerPrice": "105.0"},
}
eng31d = _eng31()
eng31d._update_perp_trailing_stop("XRP/USDT:USDT", prot31d, 90.0)
ok("perp trailing SHORT: move_stop_loss chamado no preco certo (fundo+trail = 90+5=95)",
   any(c[0] == "move_stop_loss" and abs(c[2] - 95.0) < 1e-9
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
          "size": 2.0, "stop_id": "tpsl-31e", "tp_id": None, "side": "long",
          "profile": "daytrade", "trailing": True, "trail_distance": 5.0,
          "peak_price": 100.0}
FakePerpTrailing.ORDER_RESPONSES = {
    "tpsl-31e": {"id": "tpsl-31e", "status": "open", "filled": 0.0,
                "triggerPrice": "98.0"},  # exchange real ja estava em 98
}
eng31e = _eng31()
eng31e._update_perp_trailing_stop("DOGE/USDT:USDT", prot31e, 110.0)
ev31e = [json.loads(l) for l in AUDIT.read_text(encoding="utf-8").splitlines()]
mv31e = [e for e in ev31e if e["event"] == "trailing_stop_moved" and e["symbol"] == "DOGE/USDT:USDT"]
ok("perp trailing: arquivo stale curado com o gatilho REAL (old_stop=98, nao os 95 do arquivo)",
   len(mv31e) == 1 and mv31e[0]["old_stop"] == 98.0, str(mv31e))

# 31f. stop real já FECHADO (confirmado via fetch_order) -> aborta sem
# tentar mover nada.
_reset_fake_perp_trailing()
prot31f = {"entry_price": 100.0, "take_profit": 130.0, "stop_price": 95.0,
          "size": 2.0, "stop_id": "tpsl-31f", "tp_id": None, "side": "long",
          "profile": "daytrade", "trailing": True, "trail_distance": 5.0,
          "peak_price": 100.0}
FakePerpTrailing.ORDER_RESPONSES = {
    "tpsl-31f": {"id": "tpsl-31f", "status": "closed", "filled": 2.0,
                "average": 94.9},
}
eng31f = _eng31()
eng31f._update_perp_trailing_stop("ADA/USDT:USDT", prot31f, 110.0)
ok("perp trailing: stop ja fechado (confirmado) -> nenhum move tentado",
   not any(c[0] == "move_stop_loss" for c in eng31f.client.calls), str(eng31f.client.calls))

# 31f2. tpsl já CANCELADA pela exchange (status=canceled -- a posição zerou por
# outra via) -> mesmo tratamento: aborta sem tentar mover. Achado específico
# do port pra Bitget: sem cobrir este status, o engine tentaria editar uma
# ordem inexistente TODO ciclo (o padrão dos 13.759 symbol_cycle_error
# idênticos que este projeto já conhece de outro bug).
_reset_fake_perp_trailing()
prot31f2 = {"entry_price": 100.0, "take_profit": 130.0, "stop_price": 95.0,
           "size": 2.0, "stop_id": "tpsl-31f2", "tp_id": None, "side": "long",
           "profile": "daytrade", "trailing": True, "trail_distance": 5.0,
           "peak_price": 100.0}
FakePerpTrailing.ORDER_RESPONSES = {
    "tpsl-31f2": {"id": "tpsl-31f2", "status": "canceled", "filled": 0.0},
}
eng31f2 = _eng31()
eng31f2._update_perp_trailing_stop("BNB/USDT:USDT", prot31f2, 110.0)
ok("perp trailing: tpsl ja CANCELADA pela exchange -> aborta sem tentar mover (nao vira erro perpetuo)",
   not any(c[0] == "move_stop_loss" for c in eng31f2.client.calls), str(eng31f2.client.calls))

# 31g. move_stop_loss FALHA -> aborta sem propagar; a proteção ANTERIOR
# continua valendo (nada é persistido) e o próximo ciclo tenta de novo. Sem
# janela sem proteção pra cobrir -- é o que o modelo atômico elimina.
_reset_fake_perp_trailing()
AUDIT.unlink(missing_ok=True)
FakePerpTrailing.MOVE_RESPONSES = [RuntimeError("modificacao rejeitada (simulado)")]
prot31g = {"entry_price": 100.0, "take_profit": 130.0, "stop_price": 95.0,
          "size": 2.0, "stop_id": "tpsl-31g", "tp_id": None, "side": "long",
          "profile": "daytrade", "trailing": True, "trail_distance": 5.0,
          "peak_price": 100.0}
FakePerpTrailing.ORDER_RESPONSES = {
    "tpsl-31g": {"id": "tpsl-31g", "status": "open", "filled": 0.0,
                "triggerPrice": "95.0"},
}
protection_state.set_protection("LINK/USDT:USDT", entry_price=100.0, take_profit=130.0,
                                stop_price=95.0, size=2.0, stop_id="tpsl-31g",
                                tp_id=None, side="long", profile="daytrade",
                                trailing=True, trail_distance=5.0, peak_price=100.0)
eng31g = _eng31()
try:
    eng31g._update_perp_trailing_stop("LINK/USDT:USDT", prot31g, 110.0)
    nao_propagou31g = True
except Exception:
    nao_propagou31g = False
ok("perp trailing: falha ao mover NAO propaga (isolamento)", nao_propagou31g)
# Falha ao mover não audita NADA (por desenho — não há evento de sucesso pra
# fingir) — o arquivo pode nem existir se esta foi a primeira escrita da
# seção. Ausência de arquivo É a prova, não um erro de leitura.
ev31g = ([json.loads(l) for l in AUDIT.read_text(encoding="utf-8").splitlines()]
        if AUDIT.exists() else [])
ok("perp trailing: falha ao mover NAO audita trailing_stop_moved (nao fingiu sucesso)",
   not any(e["event"] == "trailing_stop_moved" for e in ev31g))
prot31g_saved = protection_state.load().get("LINK/USDT:USDT")
ok("perp trailing: falha ao mover -> protecao ANTERIOR intacta (stop_price/stop_id nao mudam)",
   prot31g_saved is not None and prot31g_saved.get("stop_price") == 95.0
   and prot31g_saved.get("stop_id") == "tpsl-31g", str(prot31g_saved))
protection_state.clear_protection("LINK/USDT:USDT")

# 31i. sem stop_id/size rastreado -> aborta sem crashar (defesa, não deveria
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

engine_mod.BitgetClient = FakeEthQuebrado


print()
fails = [n for n, c in PASS if not c]
print(f"{len(PASS) - len(fails)}/{len(PASS)} testes passaram")
sys.exit(1 if fails else 0)
