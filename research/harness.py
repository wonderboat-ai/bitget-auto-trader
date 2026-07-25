"""Harness de pesquisa de estratégia — SPOT long-only, 6 pares, 6 meses.

Separado do backtester oficial (src/backtest/) de propósito: aqui a pergunta é
"existe edge em QUAL regra?", então precisamos varrer famílias de estratégia que
o contrato Signal/RiskManager ainda não expressa (saída por sinal, trailing,
Donchian...). O backtester oficial continua sendo a régua de validação final —
a paridade entre os dois é checada no modo `parity` (mesma regra de fill).

Regras anti-look-ahead (idênticas ao backtester oficial):
  - decisão no candle i usa SÓ dados até o fechamento de i;
  - entrada/saída por sinal preenchem no OPEN de i+1 (com slippage);
  - stop/TP são checados contra high/low de cada candle com posição aberta;
  - stop tem prioridade sobre TP no mesmo candle (conservador).

Diferenças deliberadas vs backtester oficial (mais realista, documentado):
  - gap-through: se o candle ABRE abaixo do stop, o fill é no open (o oficial
    preenche no preço exato do stop — otimista). `parity_mode=True` replica o
    comportamento oficial para o teste de paridade.
  - curva de equity com mark-to-market da posição aberta (drawdown intra-trade
    visível; o oficial só marca em fechamento de trade).
  - sem kill switch: aqui medimos o edge CRU da regra; a camada de risco do
    robô fica por cima em produção de qualquer jeito.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from itertools import product
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
DATA_DIR = HERE / "data"

FEE_PCT = 0.1 / 100        # taker spot Bybit, por lado
SLIPPAGE_PCT = 0.02 / 100  # por lado (mesmo default do backtester oficial)
RISK_PCT = 0.5 / 100       # risco por trade sobre o equity (igual ao YAML)
START_EQUITY = 1000.0
MIN_NOTIONAL = 10.0        # ordem spot mínima da Bybit (~10 USDT)


# ---------------------------------------------------------------- indicadores
# Fórmulas IDÊNTICAS a src/data/market_data.py (paridade com o live). Se mudar
# lá, mudar aqui — divergência silenciosa faria a pesquisa mentir.

def ema(series: pd.Series, length: int) -> pd.Series:
    return series.ewm(span=length, adjust=False).mean()


def rsi(series: pd.Series, length: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0).rolling(length).mean()
    loss = (-delta.clip(upper=0)).rolling(length).mean()
    rs = gain / loss.replace(0, float("nan"))
    return 100 - (100 / (1 + rs))


def atr(df: pd.DataFrame, length: int = 14) -> pd.Series:
    high, low, close = df["high"], df["low"], df["close"]
    prev_close = close.shift(1)
    tr = pd.concat(
        [(high - low), (high - prev_close).abs(), (low - prev_close).abs()], axis=1
    ).max(axis=1)
    return tr.rolling(length).mean()


def roc(series: pd.Series, length: int) -> pd.Series:
    return series.pct_change(length) * 100


# ---------------------------------------------------------------- estratégias
@dataclass(frozen=True)
class Spec:
    """Uma combinação (família, parâmetros) pronta para o motor."""
    family: str
    name: str
    params: dict


@dataclass
class Prepared:
    """Arrays que o motor consome. entry[i]/exit_sig[i] valem no FECHAMENTO do
    candle i (execução no open de i+1). stop_dist[i] é a distância do stop se a
    entrada for aprovada no candle i."""
    entry: np.ndarray        # bool
    exit_sig: np.ndarray     # bool — saída por sinal (além de stop/TP)
    stop_dist: np.ndarray    # float — distância inicial do stop (preço)
    tp_rr: float | None      # take-profit em múltiplos de R (None = sem TP)
    trail_mult: float | None # trailing stop em múltiplos de ATR (None = fixo)
    atr_arr: np.ndarray      # ATR por candle (para o trailing)
    warmup: int


def prepare(spec: Spec, df: pd.DataFrame) -> Prepared:
    p = spec.params
    close = df["close"]
    atr_arr = atr(df, 14)

    if spec.family == "ema_cross":
        f, s = ema(close, p["fast"]), ema(close, p["slow"])
        up = (f > s) & (f.shift(1) <= s.shift(1))          # cruzou pra cima
        regime = f > s
        r = rsi(close, 14)
        entry = (up if p["on_cross_only"] else regime) & (r < p["rsi_max"])
        exit_sig = f < s                                    # perdeu o regime
        stop_dist = p["atr_stop"] * atr_arr
        warmup = max(p["slow"], 14) + 5
        return Prepared(entry.to_numpy(dtype=bool), exit_sig.to_numpy(dtype=bool),
                        stop_dist.to_numpy(), p.get("tp_rr"), p.get("trail"),
                        atr_arr.to_numpy(), warmup)

    if spec.family == "donchian":
        n, m = p["n"], p["exit_m"]
        hi_n = df["high"].rolling(n).max().shift(1)         # exclui o candle atual
        lo_m = df["low"].rolling(m).min().shift(1)
        entry = close > hi_n
        exit_sig = close < lo_m
        stop_dist = p["atr_stop"] * atr_arr
        warmup = max(n, m, 14) + 5
        return Prepared(entry.to_numpy(dtype=bool), exit_sig.to_numpy(dtype=bool),
                        stop_dist.to_numpy(), None, p.get("trail"),
                        atr_arr.to_numpy(), warmup)

    if spec.family == "rsi_mr":  # reversão à média com filtro de tendência
        r = rsi(close, 14)
        trend = close > ema(close, 200)
        entry = (r < p["rsi_buy"]) & trend
        exit_sig = r > p["rsi_exit"]
        stop_dist = p["atr_stop"] * atr_arr
        warmup = 205
        return Prepared(entry.to_numpy(dtype=bool), exit_sig.to_numpy(dtype=bool),
                        stop_dist.to_numpy(), p.get("tp_rr"), None,
                        atr_arr.to_numpy(), warmup)

    if spec.family == "bollinger_mr":
        mid = close.rolling(20).mean()
        sd = close.rolling(20).std(ddof=0)
        lower = mid - p["k"] * sd
        trend = close > ema(close, 200)
        entry = (close < lower) & trend
        exit_sig = close > (mid if p["exit"] == "mid" else mid + p["k"] * sd)
        stop_dist = p["atr_stop"] * atr_arr
        warmup = 205
        return Prepared(entry.to_numpy(dtype=bool), exit_sig.to_numpy(dtype=bool),
                        stop_dist.to_numpy(), None, None, atr_arr.to_numpy(), warmup)

    if spec.family == "momentum":
        mom = roc(close, p["n"])
        trend = close > ema(close, 50)
        entry = (mom > p["th"]) & trend
        exit_sig = close < ema(close, 50)
        stop_dist = p["atr_stop"] * atr_arr
        warmup = max(p["n"], 50, 14) + 5
        return Prepared(entry.to_numpy(dtype=bool), exit_sig.to_numpy(dtype=bool),
                        stop_dist.to_numpy(), None, p.get("trail"),
                        atr_arr.to_numpy(), warmup)

    if spec.family == "robot_baseline":
        # Réplica exata da DeterministicStrategy (regime, não cruzamento; sem
        # saída por sinal — só stop e TP), long-only como o spot exige.
        f, s = ema(close, 20), ema(close, 50)
        r = rsi(close, 14)
        entry = (f > s) & (r < p["rsi_long_max"])
        exit_sig = pd.Series(False, index=close.index)
        stop_dist = p["atr_stop_mult"] * atr_arr
        warmup = 60  # mesmo warmup do backtester oficial
        return Prepared(entry.to_numpy(dtype=bool), exit_sig.to_numpy(dtype=bool),
                        stop_dist.to_numpy(), p["tp_rr"], None,
                        atr_arr.to_numpy(), warmup)

    raise ValueError(f"família desconhecida: {spec.family}")


# ------------------------------------------------------------------- motor
@dataclass
class RunResult:
    trades: int = 0
    wins: int = 0
    pnl_sum: float = 0.0
    gain_sum: float = 0.0
    loss_sum: float = 0.0
    r_sum: float = 0.0          # soma de R-múltiplos (pnl / risco inicial)
    r_sq_sum: float = 0.0
    fees_paid: float = 0.0
    start_equity: float = START_EQUITY
    end_equity: float = START_EQUITY
    max_dd_pct: float = 0.0
    bars_in_pos: int = 0
    bars_total: int = 0
    trade_list: list = field(default_factory=list)  # (entry_ts, exit_ts, pnl, r, reason)

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
        """Retorno da CHAMADA, sobre o start_equity com que ela foi rodada —
        nunca a constante global START_EQUITY. Bug real corrigido em 22/07/2026
        (achado pela verificação adversarial de donchian/4h): antes disto, uma
        chamada de walk-forward com start_equity != START_EQUITY (equity
        carregado entre folds) misturava o retorno cumulativo desde o início
        com o retorno daquele fold isolado — contaminava oos_ret_pct/pos_folds
        em sweep_2b.py sem afetar o total agregado (esse já calculava
        manualmente com START_EQUITY correto, ver sweep_2b.py)."""
        return 100.0 * (self.end_equity / self.start_equity - 1)

    @property
    def tstat_r(self) -> float:
        """t-stat da média dos R-múltiplos — significância bruta do edge."""
        n = self.trades
        if n < 2:
            return 0.0
        mean = self.r_sum / n
        var = max(self.r_sq_sum / n - mean * mean, 1e-12)
        return mean / (var ** 0.5) * (n ** 0.5)


def run(df: pd.DataFrame, prep: Prepared,
        start: int | None = None, end: int | None = None,
        start_equity: float = START_EQUITY,
        parity_mode: bool = False, keep_trades: bool = False) -> RunResult:
    """Replay candle-a-candle. start/end delimitam o intervalo OPERADO (os
    indicadores vêm do df inteiro — sem quebra de warmup na fronteira de fold)."""
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
    entry_fee = 0.0
    risk0 = 0.0
    entry_ts = 0
    pending_exit = False  # sinal de saída visto no candle anterior → sai no open

    for i in range(lo, hi):
        # ---- gestão de posição aberta (checa no candle i) ----
        if in_pos:
            res.bars_in_pos += 1
            exit_price = None
            reason = ""
            if pending_exit:
                exit_price = o[i] * (1 - SLIPPAGE_PCT)
                reason = "sinal"
                pending_exit = False
            elif l[i] <= stop:
                # gap-through: abriu abaixo do stop → fill realista no open
                exit_price = stop if parity_mode else min(stop, o[i])
                reason = "stop"
            elif tp > 0 and h[i] >= tp:
                exit_price = tp
                reason = "take_profit"

            if exit_price is not None:
                gross = (exit_price - entry_price) * size
                exit_fee = exit_price * size * FEE_PCT
                pnl = gross - exit_fee - entry_fee
                equity += gross - exit_fee   # entry_fee já saiu do caixa na entrada
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
            else:
                # trailing: atualiza no fechamento de i, vale a partir de i+1
                if prep.trail_mult is not None and prep.atr_arr[i] > 0:
                    stop = max(stop, c[i] - prep.trail_mult * prep.atr_arr[i])
                # saída por sinal vista no fechamento de i → executa no open i+1
                if prep.exit_sig[i]:
                    pending_exit = True

        # ---- nova entrada: sinal no fechamento de i → fill no open de i+1 ----
        if not in_pos and prep.entry[i]:
            dist = prep.stop_dist[i]
            if dist > 0 and not np.isnan(dist):
                fill = o[i + 1] * (1 + SLIPPAGE_PCT)
                risk_usdt = equity * RISK_PCT
                sz = risk_usdt / dist
                notional = sz * fill
                if notional > equity:          # spot: sem alavancagem, caixa manda
                    sz = equity / fill
                    notional = equity
                if notional >= MIN_NOTIONAL and sz > 0:
                    in_pos = True
                    size = sz
                    entry_price = fill
                    stop = fill - dist
                    tp = fill + prep.tp_rr * dist if prep.tp_rr else 0.0
                    entry_fee = fill * size * FEE_PCT
                    risk0 = dist * size + entry_fee  # risco real inclui a fee
                    equity -= entry_fee
                    entry_ts = ts[i + 1]
                    pending_exit = False

        # ---- curva de equity com mark-to-market ----
        mtm = equity + (c[i] - entry_price) * size if in_pos else equity
        peak = max(peak, mtm)
        dd = 100.0 * (peak - mtm) / peak if peak > 0 else 0.0
        res.max_dd_pct = max(res.max_dd_pct, dd)
        res.bars_total += 1

    # fecha posição remanescente no fechamento do último candle do intervalo
    if in_pos:
        exit_price = c[hi]
        gross = (exit_price - entry_price) * size
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
            res.trade_list.append((int(entry_ts), int(ts[hi]), round(pnl, 4),
                                   round(r_mult, 3), "fim_do_intervalo"))

    res.end_equity = equity
    return res


# ------------------------------------------------------------------- grades
def build_grid() -> list[Spec]:
    specs: list[Spec] = []

    for fast, slow in [(9, 21), (12, 26), (20, 50), (50, 200)]:
        for atr_stop in [1.5, 2.5]:
            for tp_rr in [None, 2.0]:
                for on_cross in [True, False]:
                    specs.append(Spec("ema_cross",
                                      f"ema{fast}/{slow}_stop{atr_stop}_tp{tp_rr}_{'cross' if on_cross else 'regime'}",
                                      {"fast": fast, "slow": slow, "atr_stop": atr_stop,
                                       "tp_rr": tp_rr, "rsi_max": 100.0,
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

    for rsi_buy in [25.0, 30.0, 35.0]:
        for rsi_exit in [50.0, 60.0]:
            for atr_stop in [1.5, 2.5]:
                specs.append(Spec("rsi_mr", f"rsi{rsi_buy:.0f}_exit{rsi_exit:.0f}_stop{atr_stop}",
                                  {"rsi_buy": rsi_buy, "rsi_exit": rsi_exit,
                                   "atr_stop": atr_stop, "tp_rr": None}))

    for k in [2.0, 2.5]:
        for exit_ in ["mid", "upper"]:
            for atr_stop in [1.5, 2.5]:
                specs.append(Spec("bollinger_mr", f"bb{k}_{exit_}_stop{atr_stop}",
                                  {"k": k, "exit": exit_, "atr_stop": atr_stop}))

    for n in [10, 20]:
        for th in [0.0, 1.0]:
            for trail in [2.5, 3.5]:
                specs.append(Spec("momentum", f"roc{n}_th{th}_trail{trail}",
                                  {"n": n, "th": th, "atr_stop": trail, "trail": trail}))

    # controle: o robô como está hoje + a grade que o walk-forward oficial varre
    for atr_stop in [1.0, 1.5, 2.0, 2.5]:
        for tp_rr in [1.5, 2.0, 3.0]:
            for rsi_max in [60.0, 70.0, 80.0]:
                specs.append(Spec("robot_baseline",
                                  f"robo_stop{atr_stop}_tp{tp_rr}_rsi{rsi_max:.0f}",
                                  {"atr_stop_mult": atr_stop, "tp_rr": tp_rr,
                                   "rsi_long_max": rsi_max}))
    return specs


def load(symbol: str, tf: str) -> pd.DataFrame:
    path = DATA_DIR / f"{symbol.replace('/', '_')}_{tf}.csv"
    df = pd.read_csv(path)
    return df.sort_values("ts").reset_index(drop=True)
