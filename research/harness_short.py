"""Harness de pesquisa SHORT-only em perpétuos — espelho de harness.py.

PESQUISA HIPOTÉTICA: derivativos estão bloqueados para residente BR na Bybit
(retCode 10024). Esta régua existe para decidir se short valeria a pena em
venue legítima — nunca para contornar o bloqueio.

Diferenças vs o harness long/spot (deliberadas, todas documentadas):
  - preços de PERPÉTUOS (research/data_perp/), não spot;
  - fee taker de perp: 0,055%/lado (spot é 0,1%);
  - FUNDING real a cada 8h: short RECEBE rate positivo, PAGA rate negativo,
    aplicado sobre o nocional marcado no close do candle que contém o evento;
  - alavancagem moderada: nocional até 2x o equity (o sizing continua por
    risco fixo — a alavanca só destrava stops apertados, não aumenta o risco
    por trade);
  - liquidação aproximada de short isolado 2x: preço +47,5% acima da entrada
    (1 + 0.95/leverage); com stops de 1–3,5 ATR isso não deve disparar nunca —
    se disparar, o trade fecha ali com slippage punitiva de 1% (honestidade:
    liquidação real executa pior que stop).

Regras anti-look-ahead idênticas: decisão no close de i, fill no open de i+1,
stop prioritário sobre TP, gap-through no stop preenche no open (pior preço),
trailing atualizado no close vale a partir do candle seguinte.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from harness import Spec, ema, rsi, atr, roc  # mesmas fórmulas do live

HERE = Path(__file__).resolve().parent
DATA_DIR = HERE / "data_perp"

FEE_PCT = 0.055 / 100      # taker perp Bybit, por lado
SLIPPAGE_PCT = 0.02 / 100
RISK_PCT = 0.5 / 100
START_EQUITY = 1000.0
MIN_NOTIONAL = 10.0
LEVERAGE = 2.0             # "moderada": teto de nocional = 2x equity
LIQ_FRAC = 1 + 0.95 / LEVERAGE  # short liquida se high >= entry * LIQ_FRAC
LIQ_SLIPPAGE = 1.0 / 100   # liquidação executa pior que stop comum


@dataclass
class PreparedShort:
    entry: np.ndarray
    exit_sig: np.ndarray
    stop_dist: np.ndarray
    tp_rr: float | None
    trail_mult: float | None
    atr_arr: np.ndarray
    warmup: int


def prepare_short(spec: Spec, df: pd.DataFrame) -> PreparedShort:
    """Espelho short de harness.prepare(): mesmas famílias, condições invertidas."""
    p = spec.params
    close = df["close"]
    atr_arr = atr(df, 14)

    if spec.family == "ema_cross":
        f, s = ema(close, p["fast"]), ema(close, p["slow"])
        down = (f < s) & (f.shift(1) >= s.shift(1))
        regime = f < s
        r = rsi(close, 14)
        entry = (down if p["on_cross_only"] else regime) & (r > p["rsi_min"])
        exit_sig = f > s
        stop_dist = p["atr_stop"] * atr_arr
        warmup = max(p["slow"], 14) + 5
    elif spec.family == "donchian":
        n, m = p["n"], p["exit_m"]
        lo_n = df["low"].rolling(n).min().shift(1)
        hi_m = df["high"].rolling(m).max().shift(1)
        entry = close < lo_n
        exit_sig = close > hi_m
        stop_dist = p["atr_stop"] * atr_arr
        warmup = max(n, m, 14) + 5
    elif spec.family == "rsi_mr":
        r = rsi(close, 14)
        downtrend = close < ema(close, 200)
        entry = (r > p["rsi_sell"]) & downtrend
        exit_sig = r < p["rsi_exit"]
        stop_dist = p["atr_stop"] * atr_arr
        warmup = 205
    elif spec.family == "bollinger_mr":
        mid = close.rolling(20).mean()
        sd = close.rolling(20).std(ddof=0)
        upper = mid + p["k"] * sd
        downtrend = close < ema(close, 200)
        entry = (close > upper) & downtrend
        exit_sig = close < (mid if p["exit"] == "mid" else mid - p["k"] * sd)
        stop_dist = p["atr_stop"] * atr_arr
        warmup = 205
    elif spec.family == "momentum":
        mom = roc(close, p["n"])
        downtrend = close < ema(close, 50)
        entry = (mom < -p["th"]) & downtrend
        exit_sig = close > ema(close, 50)
        stop_dist = p["atr_stop"] * atr_arr
        warmup = max(p["n"], 50, 14) + 5
    elif spec.family == "robot_baseline":
        # A regra SHORT da DeterministicStrategy: EMA_fast<EMA_slow e RSI>rsi_min
        f, s = ema(close, 20), ema(close, 50)
        r = rsi(close, 14)
        entry = (f < s) & (r > p["rsi_short_min"])
        exit_sig = pd.Series(False, index=close.index)
        stop_dist = p["atr_stop_mult"] * atr_arr
        warmup = 60
        return PreparedShort(entry.to_numpy(dtype=bool), exit_sig.to_numpy(dtype=bool),
                             stop_dist.to_numpy(), p["tp_rr"], None,
                             atr_arr.to_numpy(), warmup)
    else:
        raise ValueError(f"família desconhecida: {spec.family}")

    return PreparedShort(entry.to_numpy(dtype=bool), exit_sig.to_numpy(dtype=bool),
                         stop_dist.to_numpy(), p.get("tp_rr"), p.get("trail"),
                         atr_arr.to_numpy(), warmup)


@dataclass
class RunResult:
    trades: int = 0
    wins: int = 0
    pnl_sum: float = 0.0
    gain_sum: float = 0.0
    loss_sum: float = 0.0
    r_sum: float = 0.0
    r_sq_sum: float = 0.0
    fees_paid: float = 0.0
    funding_received: float = 0.0   # líquido: + recebido, - pago
    liquidations: int = 0
    start_equity: float = START_EQUITY
    end_equity: float = START_EQUITY
    max_dd_pct: float = 0.0
    bars_in_pos: int = 0
    bars_total: int = 0
    trade_list: list = field(default_factory=list)

    @property
    def win_rate(self) -> float:
        return self.wins / self.trades if self.trades else 0.0

    @property
    def profit_factor(self) -> float:
        return self.gain_sum / abs(self.loss_sum) if self.loss_sum else float("inf")

    @property
    def expectancy_r(self) -> float:
        return self.r_sum / self.trades if self.trades else 0.0

    @property
    def total_return_pct(self) -> float:
        """Retorno da CHAMADA sobre o start_equity com que ela rodou — mesmo
        bug do RunResult de harness.py, corrigido no mesmo dia (22/07/2026)
        por consistência, mesmo com sweep_short.py já contornando isto com
        fold_ret_pct calculado à parte (ver comentário no topo de sweep_short.py)."""
        return 100.0 * (self.end_equity / self.start_equity - 1)

    @property
    def tstat_r(self) -> float:
        n = self.trades
        if n < 2:
            return 0.0
        mean = self.r_sum / n
        var = max(self.r_sq_sum / n - mean * mean, 1e-12)
        return mean / (var ** 0.5) * (n ** 0.5)


def align_funding(df: pd.DataFrame, funding: pd.DataFrame, tf_ms: int) -> np.ndarray:
    """rate_no_candle[i] = soma dos funding rates cujo timestamp cai dentro do
    candle i (ts[i] <= evento < ts[i]+tf_ms). Aplicado no close do candle."""
    rates = np.zeros(len(df))
    ts = df["ts"].to_numpy()
    idx = np.searchsorted(ts, funding["ts"].to_numpy(), side="right") - 1
    for k, i in enumerate(idx):
        if 0 <= i < len(df) and 0 <= funding["ts"].iloc[k] - ts[i] < tf_ms:
            rates[i] += float(funding["rate"].iloc[k])
    return rates


def run_short(df: pd.DataFrame, prep: PreparedShort, funding_rates: np.ndarray,
              start: int | None = None, end: int | None = None,
              start_equity: float = START_EQUITY,
              keep_trades: bool = False) -> RunResult:
    o = df["open"].to_numpy()
    h = df["high"].to_numpy()
    l = df["low"].to_numpy()
    c = df["close"].to_numpy()
    ts = df["ts"].to_numpy()
    n = len(df)

    lo = max(prep.warmup, start if start is not None else prep.warmup)
    hi = (end if end is not None else n) - 1

    res = RunResult(start_equity=start_equity, end_equity=start_equity)
    equity = start_equity
    peak = equity

    in_pos = False
    size = 0.0
    entry_price = 0.0
    stop = 0.0
    tp = 0.0
    liq_price = 0.0
    entry_fee = 0.0
    risk0 = 0.0
    entry_ts = 0
    pending_exit = False

    def close_trade(exit_price: float, i: int, reason: str) -> None:
        nonlocal equity, in_pos
        gross = (entry_price - exit_price) * size          # short: ganha na queda
        exit_fee = exit_price * size * FEE_PCT
        pnl = gross - exit_fee - entry_fee
        equity += gross - exit_fee
        res.trades += 1
        res.pnl_sum += pnl
        if pnl > 0:
            res.wins += 1
            res.gain_sum += pnl
        else:
            res.loss_sum += pnl
        r_mult = pnl / risk0 if risk0 > 0 else 0.0
        res.r_sum += r_mult
        res.r_sq_sum += r_mult * r_mult
        res.fees_paid += exit_fee + entry_fee
        if keep_trades:
            res.trade_list.append((int(entry_ts), int(ts[i]), round(pnl, 4),
                                   round(r_mult, 3), reason))
        in_pos = False

    for i in range(lo, hi):
        if in_pos:
            res.bars_in_pos += 1
            if pending_exit:
                close_trade(o[i] * (1 + SLIPPAGE_PCT), i, "sinal")
                pending_exit = False
            elif h[i] >= stop and stop < liq_price:
                # Stop protege antes da liquidação (stop < liq sempre nas nossas
                # grades). gap-through: abriu acima do stop → fill no open (pior).
                close_trade(max(stop, o[i]), i, "stop")
            elif h[i] >= liq_price:
                # Só alcançável se o stop estiver além do preço de liquidação
                # (não ocorre nas grades atuais) — mantido por honestidade.
                price = max(liq_price, o[i]) * (1 + LIQ_SLIPPAGE)
                res.liquidations += 1
                close_trade(price, i, "LIQUIDACAO")
            elif tp > 0 and l[i] <= tp:
                close_trade(tp, i, "take_profit")

            if in_pos:
                # funding do candle i: short recebe rate positivo sobre o nocional
                if funding_rates[i] != 0.0:
                    flow = funding_rates[i] * size * c[i]
                    equity += flow
                    res.funding_received += flow
                if prep.trail_mult is not None and prep.atr_arr[i] > 0:
                    stop = min(stop, c[i] + prep.trail_mult * prep.atr_arr[i])
                if prep.exit_sig[i]:
                    pending_exit = True

        if not in_pos and prep.entry[i]:
            dist = prep.stop_dist[i]
            if dist > 0 and not np.isnan(dist):
                fill = o[i + 1] * (1 - SLIPPAGE_PCT)   # short vende: slippage contra
                risk_usdt = equity * RISK_PCT
                sz = risk_usdt / dist
                notional = sz * fill
                max_notional = LEVERAGE * equity
                if notional > max_notional:
                    sz = max_notional / fill
                    notional = max_notional
                if notional >= MIN_NOTIONAL and sz > 0 and equity > 0:
                    in_pos = True
                    size = sz
                    entry_price = fill
                    stop = fill + dist
                    tp = fill - prep.tp_rr * dist if prep.tp_rr else 0.0
                    liq_price = fill * LIQ_FRAC
                    entry_fee = fill * size * FEE_PCT
                    risk0 = dist * size + entry_fee
                    equity -= entry_fee
                    entry_ts = ts[i + 1]
                    pending_exit = False

        mtm = equity + (entry_price - c[i]) * size if in_pos else equity
        peak = max(peak, mtm)
        dd = 100.0 * (peak - mtm) / peak if peak > 0 else 100.0
        res.max_dd_pct = max(res.max_dd_pct, dd)
        res.bars_total += 1

    if in_pos:
        close_trade(c[hi], hi, "fim_do_intervalo")

    res.end_equity = equity
    return res


def build_grid_short() -> list[Spec]:
    """Espelho da grade long — mesmos tamanhos, condições invertidas."""
    specs: list[Spec] = []
    for fast, slow in [(9, 21), (12, 26), (20, 50), (50, 200)]:
        for atr_stop in [1.5, 2.5]:
            for tp_rr in [None, 2.0]:
                for on_cross in [True, False]:
                    specs.append(Spec("ema_cross",
                                      f"ema{fast}/{slow}_stop{atr_stop}_tp{tp_rr}_{'cross' if on_cross else 'regime'}",
                                      {"fast": fast, "slow": slow, "atr_stop": atr_stop,
                                       "tp_rr": tp_rr, "rsi_min": 0.0,
                                       "on_cross_only": on_cross, "trail": None}))
    for n in [20, 55]:
        for exit_m in [10, 20]:
            for atr_stop in [2.0, 3.0]:
                specs.append(Spec("donchian", f"don{n}_exit{exit_m}_stop{atr_stop}",
                                  {"n": n, "exit_m": exit_m, "atr_stop": atr_stop,
                                   "trail": None}))
    for n in [20, 55]:
        for trail in [2.5, 3.5]:
            specs.append(Spec("donchian", f"don{n}_trail{trail}",
                              {"n": n, "exit_m": n // 2, "atr_stop": trail,
                               "trail": trail}))
    for rsi_sell in [65.0, 70.0, 75.0]:
        for rsi_exit in [50.0, 40.0]:
            for atr_stop in [1.5, 2.5]:
                specs.append(Spec("rsi_mr", f"rsi{rsi_sell:.0f}_exit{rsi_exit:.0f}_stop{atr_stop}",
                                  {"rsi_sell": rsi_sell, "rsi_exit": rsi_exit,
                                   "atr_stop": atr_stop, "tp_rr": None}))
    for k in [2.0, 2.5]:
        for exit_ in ["mid", "lower"]:
            for atr_stop in [1.5, 2.5]:
                specs.append(Spec("bollinger_mr", f"bb{k}_{exit_}_stop{atr_stop}",
                                  {"k": k, "exit": exit_, "atr_stop": atr_stop}))
    for n in [10, 20]:
        for th in [0.0, 1.0]:
            for trail in [2.5, 3.5]:
                specs.append(Spec("momentum", f"roc{n}_th{th}_trail{trail}",
                                  {"n": n, "th": th, "atr_stop": trail, "trail": trail}))
    for atr_stop in [1.0, 1.5, 2.0, 2.5]:
        for tp_rr in [1.5, 2.0, 3.0]:
            for rsi_min in [20.0, 30.0, 40.0]:
                specs.append(Spec("robot_baseline",
                                  f"robo_stop{atr_stop}_tp{tp_rr}_rsi{rsi_min:.0f}",
                                  {"atr_stop_mult": atr_stop, "tp_rr": tp_rr,
                                   "rsi_short_min": rsi_min}))
    return specs


def load_perp(symbol_base: str, tf: str) -> pd.DataFrame:
    df = pd.read_csv(DATA_DIR / f"{symbol_base}_USDT_{tf}.csv")
    return df.sort_values("ts").reset_index(drop=True)


def load_funding(symbol_base: str) -> pd.DataFrame:
    df = pd.read_csv(DATA_DIR / f"{symbol_base}_USDT_funding.csv")
    return df.sort_values("ts").reset_index(drop=True)
