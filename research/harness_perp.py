"""Harness de pesquisa rodada 3 (18/08/2026) — PERP, LONG **E** SHORT juntos.

Por que existe (e por que os dois harness antigos nao servem):
  - harness.py        mede SPOT long-only, fee 0,1%/lado, sem funding.
  - harness_short.py  mede PERP short-only, fee 0,055%/lado, com funding.
  A producao REAL hoje (config/risk_config.yaml, desde 28/07/2026) e PERP com
  long E short habilitados, fee taker 0,055%/lado, teto de alavancagem 2x e
  teto de nocional de 50% do equity por trade. **Nenhuma rodada de pesquisa
  anterior mediu essa configuracao** — as duas mediam metade dela. Um resultado
  long-only nao diz nada sobre uma estrategia que tambem vende a descoberto: o
  mesmo sinal que antes era "ficar em caixa" (custo zero) agora virou uma
  posicao short com custo de fee + funding.

Regras anti-look-ahead (identicas ao backtester oficial e aos dois harness):
  - a decisao no candle i usa SO dados ate o FECHAMENTO de i;
  - entrada e saida por sinal preenchem no OPEN de i+1 (com slippage);
  - stop/TP sao checados contra high/low de cada candle com posicao aberta;
  - stop tem prioridade sobre TP no mesmo candle (conservador);
  - o trailing calculado no close de i so vale a partir de i+1.

Diferencas deliberadas vs o backtester oficial (mais conservador, documentado):
  - gap-through: candle que ABRE alem do stop preenche no open (o oficial
    preenche no preco exato do stop — otimista);
  - funding real a cada 8h sobre o nocional marcado no close do candle do
    evento (long PAGA rate positivo, short RECEBE);
  - sem kill switch: aqui medimos o edge CRU da regra. A camada de risco fica
    por cima em producao de qualquer jeito, e um kill switch simulado
    censuraria o resto da janela (mesmo achado do fix #15, 15/07).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from harness import ema, rsi, atr, roc, Spec   # MESMAS formulas do live

HERE = Path(__file__).resolve().parent
DATA_DIR = HERE / "data_3"

FEE_PCT = 0.055 / 100       # taker perp Bybit, por lado
SLIPPAGE_PCT = 0.02 / 100   # por lado
RISK_PCT = 0.5 / 100        # = per_trade.risk_pct do YAML
START_EQUITY = 1000.0
MIN_NOTIONAL = 10.0
LEVERAGE = 2.0                    # = per_trade.max_leverage do YAML
MAX_NOTIONAL_PCT_EQUITY = 50.0    # = per_trade.max_notional_pct_equity do YAML
# Passo minimo do trailing: espelha src/strategy/signal.TRAIL_MIN_STEP_PCT.
# Aqui e PARAMETRO (a pergunta do Lucas e exatamente qual deve ser o valor),
# mas o default reproduz o live de hoje.
TRAIL_MIN_STEP_PCT_DEFAULT = 0.001


# --------------------------------------------------------------------- dados
def load_ohlcv(base: str, tf: str) -> pd.DataFrame:
    df = pd.read_csv(DATA_DIR / f"{base}_USDT_{tf}.csv")
    return df.sort_values("ts").reset_index(drop=True)


def load_funding(base: str) -> pd.DataFrame:
    path = DATA_DIR / f"{base}_USDT_funding.csv"
    if not path.exists():
        return pd.DataFrame(columns=["ts", "rate"])
    return pd.read_csv(path).sort_values("ts").reset_index(drop=True)


def funding_per_candle(df: pd.DataFrame, fund: pd.DataFrame) -> np.ndarray:
    """Soma dos rates de funding cujo timestamp cai DENTRO de cada candle.

    Um candle de 4h contem 0 ou 1 evento; um de 15m quase sempre 0. O rate e
    aplicado no fechamento do candle que o contem — aproximacao de ate 1 candle
    contra o horario exato, deliberada e simetrica (nao favorece nenhum lado).
    """
    out = np.zeros(len(df), dtype=float)
    if fund is None or len(fund) == 0:
        return out
    ts = df["ts"].to_numpy()
    idx = np.searchsorted(ts, fund["ts"].to_numpy(), side="right") - 1
    for i, r in zip(idx, fund["rate"].to_numpy()):
        if 0 <= i < len(out):
            out[i] += float(r)
    return out


# ---------------------------------------------------------------- estrategias
@dataclass
class PreparedBoth:
    """Sinais para os DOIS lados. Tudo vale no FECHAMENTO do candle i
    (execucao no open de i+1)."""
    entry_l: np.ndarray
    entry_s: np.ndarray
    exit_l: np.ndarray
    exit_s: np.ndarray
    stop_dist: np.ndarray
    tp_rr: float | None
    trail_mult: float | None
    trail_min_step: float
    atr_arr: np.ndarray
    warmup: int
    # Gatilho de ATIVACAO do trailing, em multiplos de R: o stop so comeca a
    # seguir o preco depois que o trade acumulou este lucro. 0.0 = comportamento
    # do live hoje (segue desde o primeiro tick a favor).
    #
    # Isto NAO existe no motor hoje — e a peca que responde diretamente a
    # queixa do Lucas ("nao ser fisgado em cada agulhada no mercado lateral").
    # Sem gatilho, uma perna de 0,3R a favor seguida de reversao ja arrasta o
    # stop e transforma o que seria um stop cheio num stop parcial; COM gatilho,
    # o trade so passa a ser gerenciado por trailing depois de provar movimento.
    # E implementavel no live com uma guarda em _update_perp_trailing_stop.
    trail_start_r: float = 0.0


def prepare_both(spec: Spec, df: pd.DataFrame) -> PreparedBoth:
    """Mesmas 6 familias dos harness antigos, agora com os DOIS lados no mesmo
    objeto. As condicoes short sao o espelho exato das long (mesma formula que
    harness_short.prepare_short ja usava), para que a comparacao long-only x
    long+short isole o efeito de habilitar o short — e nada mais."""
    p = spec.params
    close = df["close"]
    atr_arr = atr(df, 14)
    F = pd.Series(False, index=close.index)
    tp_rr = p.get("tp_rr")
    trail = p.get("trail")
    tms = p.get("trail_min_step", TRAIL_MIN_STEP_PCT_DEFAULT)

    if spec.family == "ema_cross":
        f, s = ema(close, p["fast"]), ema(close, p["slow"])
        up = (f > s) & (f.shift(1) <= s.shift(1))
        down = (f < s) & (f.shift(1) >= s.shift(1))
        r = rsi(close, 14)
        base_l = up if p["on_cross_only"] else (f > s)
        base_s = down if p["on_cross_only"] else (f < s)
        entry_l = base_l & (r < p["rsi_max"])
        entry_s = base_s & (r > 100 - p["rsi_max"])
        exit_l, exit_s = f < s, f > s
        stop_dist = p["atr_stop"] * atr_arr
        warmup = max(p["slow"], 14) + 5

    elif spec.family == "donchian":
        n, m = p["n"], p["exit_m"]
        hi_n = df["high"].rolling(n).max().shift(1)   # exclui o candle atual
        lo_n = df["low"].rolling(n).min().shift(1)
        lo_m = df["low"].rolling(m).min().shift(1)
        hi_m = df["high"].rolling(m).max().shift(1)
        entry_l, entry_s = close > hi_n, close < lo_n
        exit_l, exit_s = close < lo_m, close > hi_m
        stop_dist = p["atr_stop"] * atr_arr
        warmup = max(n, m, 14) + 5

    elif spec.family == "rsi_mr":
        r = rsi(close, 14)
        e200 = ema(close, 200)
        entry_l = (r < p["rsi_buy"]) & (close > e200)
        entry_s = (r > 100 - p["rsi_buy"]) & (close < e200)
        exit_l = r > p["rsi_exit"]
        exit_s = r < 100 - p["rsi_exit"]
        stop_dist = p["atr_stop"] * atr_arr
        warmup = 205

    elif spec.family == "bollinger_mr":
        mid = close.rolling(20).mean()
        sd = close.rolling(20).std(ddof=0)
        lower, upper = mid - p["k"] * sd, mid + p["k"] * sd
        e200 = ema(close, 200)
        entry_l = (close < lower) & (close > e200)
        entry_s = (close > upper) & (close < e200)
        exit_l = close > (mid if p["exit"] == "mid" else upper)
        exit_s = close < (mid if p["exit"] == "mid" else lower)
        stop_dist = p["atr_stop"] * atr_arr
        warmup = 205

    elif spec.family == "momentum":
        mom = roc(close, p["n"])
        e50 = ema(close, 50)
        entry_l = (mom > p["th"]) & (close > e50)
        entry_s = (mom < -p["th"]) & (close < e50)
        exit_l, exit_s = close < e50, close > e50
        stop_dist = p["atr_stop"] * atr_arr
        warmup = max(p["n"], 50, 14) + 5

    elif spec.family == "robot_live":
        # Replica EXATA da DeterministicStrategy em producao hoje: regime de
        # EMA20/50 (nao cruzamento), filtro de RSI, stop ATR*mult, TP fixo em
        # tp_rr, SEM saida por sinal, trailing conforme o YAML. Os dois lados
        # habilitados, como o market.type "perp" de hoje permite.
        f, s = ema(close, 20), ema(close, 50)
        r = rsi(close, 14)
        entry_l = (f > s) & (r < p.get("rsi_long_max", 70.0))
        entry_s = (f < s) & (r > p.get("rsi_short_min", 30.0))
        exit_l = exit_s = F
        stop_dist = p["atr_stop_mult"] * atr_arr
        warmup = 60

    else:
        raise ValueError(f"familia desconhecida: {spec.family}")

    return PreparedBoth(
        entry_l.to_numpy(dtype=bool), entry_s.to_numpy(dtype=bool),
        exit_l.to_numpy(dtype=bool), exit_s.to_numpy(dtype=bool),
        stop_dist.to_numpy(), tp_rr, trail, tms, atr_arr.to_numpy(), warmup,
        p.get("trail_start_r", 0.0),
    )


# --------------------------------------------------------------------- motor
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
    funding_paid: float = 0.0
    start_equity: float = START_EQUITY
    end_equity: float = START_EQUITY
    max_dd_pct: float = 0.0
    bars_in_pos: int = 0
    bars_total: int = 0
    longs: int = 0
    shorts: int = 0
    r_long: float = 0.0
    r_short: float = 0.0
    trade_list: list = field(default_factory=list)

    @property
    def win_rate(self) -> float:
        return self.wins / self.trades if self.trades else 0.0

    @property
    def profit_factor(self) -> float:
        return self.gain_sum / abs(self.loss_sum) if self.loss_sum else float("inf")

    @property
    def total_return_pct(self) -> float:
        # Divide pelo capital REAL desta chamada, nao pela constante global —
        # o bug corrigido em 22/07 em harness.py, nao reintroduzir.
        return (self.end_equity / self.start_equity - 1.0) * 100.0

    @property
    def r_mean(self) -> float:
        return self.r_sum / self.trades if self.trades else 0.0

    @property
    def r_tstat(self) -> float:
        n = self.trades
        if n < 2:
            return 0.0
        mean = self.r_sum / n
        var = max(self.r_sq_sum / n - mean * mean, 0.0)
        sd = var ** 0.5
        return mean / (sd / n ** 0.5) if sd > 0 else 0.0

    @property
    def expectancy_r(self) -> float:
        return self.r_mean


def run(spec: Spec, df: pd.DataFrame, prep: PreparedBoth,
        fund_arr: np.ndarray, start: int = 0, end: int | None = None,
        start_equity: float = START_EQUITY,
        allow_long: bool = True, allow_short: bool = True) -> RunResult:
    """Simula UMA posicao por vez (one-way mode, igual ao live: o motor nunca
    tem long e short do mesmo simbolo ao mesmo tempo)."""
    o = df["open"].to_numpy()
    h = df["high"].to_numpy()
    l = df["low"].to_numpy()
    c = df["close"].to_numpy()
    ts = df["ts"].to_numpy()
    n = len(df) if end is None else min(end, len(df))
    i0 = max(start, prep.warmup)

    res = RunResult(start_equity=start_equity, end_equity=start_equity)
    equity = start_equity
    peak = equity

    pos = 0            # 0 flat, +1 long, -1 short
    entry_px = 0.0
    size = 0.0
    stop = 0.0
    tp = 0.0
    risk0 = 0.0        # risco em USDT no momento da entrada (= 1R)
    extreme = 0.0      # pico (long) / fundo (short) visto
    trail_dist = 0.0
    pending = 0        # +1 abrir long, -1 abrir short, 2 fechar, 0 nada

    def close_pos(px: float, idx: int, reason: str) -> None:
        nonlocal pos, equity, size, entry_px, risk0
        gross = (px - entry_px) * size if pos > 0 else (entry_px - px) * size
        fee = (entry_px + px) * size * FEE_PCT
        pnl = gross - fee
        equity += pnl
        res.trades += 1
        res.pnl_sum += pnl
        res.fees_paid += fee
        if pnl > 0:
            res.wins += 1
            res.gain_sum += pnl
        else:
            res.loss_sum += pnl
        r = pnl / risk0 if risk0 > 0 else 0.0
        res.r_sum += r
        res.r_sq_sum += r * r
        if pos > 0:
            res.longs += 1
            res.r_long += r
        else:
            res.shorts += 1
            res.r_short += r
        res.trade_list.append((int(ts[idx]), "long" if pos > 0 else "short",
                               entry_px, px, pnl, r, reason))
        pos = 0
        size = 0.0

    for i in range(i0, n):
        res.bars_total += 1

        # ---- 1. executa o que foi decidido no FECHAMENTO do candle anterior
        if pending == 2 and pos != 0:
            px = o[i] * (1 - SLIPPAGE_PCT) if pos > 0 else o[i] * (1 + SLIPPAGE_PCT)
            close_pos(px, i, "signal_exit")
        elif pending in (1, -1) and pos == 0:
            side = pending
            px = o[i] * (1 + SLIPPAGE_PCT) if side > 0 else o[i] * (1 - SLIPPAGE_PCT)
            sd = prep.stop_dist[i - 1]
            if sd and sd > 0 and np.isfinite(sd) and px > 0:
                risk_usdt = equity * RISK_PCT
                sz = risk_usdt / sd
                cap_notional = min(equity * LEVERAGE,
                                   equity * MAX_NOTIONAL_PCT_EQUITY / 100.0)
                if sz * px > cap_notional:
                    sz = cap_notional / px
                if sz * px >= MIN_NOTIONAL:
                    pos = side
                    entry_px = px
                    size = sz
                    stop = px - sd if side > 0 else px + sd
                    risk0 = sd * sz
                    tp = (px + prep.tp_rr * sd if side > 0 else px - prep.tp_rr * sd) \
                        if prep.tp_rr else 0.0
                    extreme = px
                    trail_dist = (prep.trail_mult * prep.atr_arr[i - 1]
                                  if prep.trail_mult else 0.0)
        pending = 0

        # ---- 2. posicao aberta: funding, stop/TP intra-candle, trailing
        if pos != 0:
            res.bars_in_pos += 1
            if fund_arr[i]:
                # long PAGA rate positivo; short RECEBE.
                cost = fund_arr[i] * c[i] * size * (1 if pos > 0 else -1)
                equity -= cost
                res.funding_paid += cost

            if pos > 0:
                if l[i] <= stop:
                    px = min(o[i], stop) * (1 - SLIPPAGE_PCT)   # gap-through
                    close_pos(px, i, "stop_loss")
                elif tp and h[i] >= tp:
                    close_pos(tp * (1 - SLIPPAGE_PCT), i, "take_profit")
            else:
                if h[i] >= stop:
                    px = max(o[i], stop) * (1 + SLIPPAGE_PCT)
                    close_pos(px, i, "stop_loss")
                elif tp and l[i] <= tp:
                    close_pos(tp * (1 + SLIPPAGE_PCT), i, "take_profit")

        # ---- 3. trailing: atualiza o extremo com o candle ATUAL e move o stop.
        # Vale a partir do candle seguinte (o stop novo nao e checado contra o
        # candle que produziu o extremo) — sem look-ahead intra-candle.
        if pos != 0 and trail_dist > 0:
            if pos > 0:
                extreme = max(extreme, h[i])
                gain_r = (extreme - entry_px) / (risk0 / size) if size else 0.0
                if gain_r >= prep.trail_start_r:
                    cand = extreme - trail_dist
                    if cand > stop * (1 + prep.trail_min_step):
                        stop = cand
            else:
                extreme = min(extreme, l[i])
                gain_r = (entry_px - extreme) / (risk0 / size) if size else 0.0
                if gain_r >= prep.trail_start_r:
                    cand = extreme + trail_dist
                    if cand < stop * (1 - prep.trail_min_step):
                        stop = cand

        # ---- 4. decide no FECHAMENTO de i (executa em i+1)
        if pos != 0:
            if (pos > 0 and prep.exit_l[i]) or (pos < 0 and prep.exit_s[i]):
                pending = 2
        else:
            want_l = allow_long and prep.entry_l[i]
            want_s = allow_short and prep.entry_s[i]
            if want_l and not want_s:
                pending = 1
            elif want_s and not want_l:
                pending = -1
            # ambos ao mesmo tempo = sinal contraditorio -> nao opera (o live
            # tambem nao abriria os dois: exclusividade por simbolo, fix #11).

        # ---- 5. curva de equity com mark-to-market
        mtm = equity
        if pos != 0:
            mtm += ((c[i] - entry_px) * size if pos > 0 else (entry_px - c[i]) * size)
        peak = max(peak, mtm)
        if peak > 0:
            dd = (peak - mtm) / peak * 100.0
            res.max_dd_pct = max(res.max_dd_pct, dd)

    # fecha no ultimo close disponivel (nao deixa trade aberto contaminando)
    if pos != 0:
        close_pos(c[n - 1], n - 1, "eod")

    res.end_equity = equity
    return res
