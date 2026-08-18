"""Sweep dedicado da GESTAO DE SAIDA — responde a pergunta do Lucas (18/08/2026):
"acho que podemos ajustar a margem do trailing stop para nao ser fisgado em cada
agulhada no mercado lateral".

Ha TRES parametros distintos sob o nome informal "margem do trailing", e eles
fazem coisas diferentes. Confundi-los e o jeito mais facil de mexer no numero
errado:

  1. trail_dist  — a distancia entre o pico visto e o stop. No motor hoje ela e
     amarrada a distancia do stop inicial (trail_distance = |fill - stop| =
     atr_stop_mult x ATR = 1,5 x ATR). E ESTA que decide se uma agulhada pega o
     stop. Mais larga = menos fisgado, mas devolve mais lucro na reversao real.

  2. TRAIL_MIN_STEP_PCT (0,1% hoje) — o quanto o stop precisa MELHORAR para ser
     de fato movido. Serve para nao ficar cancelando/recriando a ordem
     condicional a cada micro-avanco. Praticamente NAO afeta ser fisgado; afeta
     churn de ordem. Aumentar isso achando que resolve agulhada e o erro classico.

  3. trail_start_r — gatilho de ATIVACAO: so comeca a seguir depois de X R de
     lucro. **NAO EXISTE no motor hoje** (o stop segue desde o primeiro tick a
     favor). E o parametro que responde mais diretamente a queixa.

Este sweep varre os tres, de forma independente, sobre a estrategia que roda ao
vivo E sobre as familias candidatas — walk-forward de verdade, nao backtest
unico, para nao escolher parametro por sorte de janela.

Uso:  python research/sweep_trailing.py
"""
from __future__ import annotations

import itertools
import json
import sys
import time
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

from harness import Spec
from harness_perp import (load_ohlcv, load_funding, funding_per_candle,
                          prepare_both, run, START_EQUITY)

HERE = Path(__file__).resolve().parent
OUT = HERE / "results_3"
OUT.mkdir(exist_ok=True)

SYMBOLS = ["BTC", "ETH", "SOL", "XRP", "BNB", "DOGE", "ADA", "LINK"]
TF_MS = {"15m": 900_000, "1h": 3_600_000, "4h": 14_400_000}
DAY_MS = 86_400_000
IS_DAYS, OOS_DAYS = 90, 18


def bases():
    """Configuracoes-base sobre as quais a gestao de saida e variada.

    robot_live com stop 1,5 ATR / tp 2,0 / 15m e 4h = EXATAMENTE producao hoje.
    """
    return [
        ("robot_live_15m", "15m", Spec("robot_live", "live", dict(
            atr_stop_mult=1.5, tp_rr=2.0, rsi_long_max=70.0, rsi_short_min=30.0))),
        ("robot_live_4h", "4h", Spec("robot_live", "live", dict(
            atr_stop_mult=1.5, tp_rr=2.0, rsi_long_max=70.0, rsi_short_min=30.0))),
        ("donchian_4h", "4h", Spec("donchian", "don", dict(
            n=55, exit_m=20, atr_stop=2.0, tp_rr=None))),
        ("ema_cross_4h", "4h", Spec("ema_cross", "ema", dict(
            fast=20, slow=50, on_cross_only=False, rsi_max=100.0,
            atr_stop=2.0, tp_rr=None))),
    ]


def variants():
    """Eixos varridos. None em trail = trailing DESLIGADO (stop fixo)."""
    out = []
    # eixo 1: distancia do trailing (o que realmente decide "ser fisgado")
    for tr in [None, 1.0, 1.5, 2.0, 3.0, 4.0]:
        out.append(dict(trail=tr, trail_min_step=0.001, trail_start_r=0.0))
    # eixo 2: passo minimo (churn) — mantendo a distancia do live
    for ms in [0.0025, 0.005, 0.01, 0.02]:
        out.append(dict(trail=1.5, trail_min_step=ms, trail_start_r=0.0))
    # eixo 3: gatilho de ativacao (a peca que nao existe no motor)
    for st in [0.25, 0.5, 0.75, 1.0, 1.5]:
        out.append(dict(trail=1.5, trail_min_step=0.001, trail_start_r=st))
    # eixo 4: combinacoes promissoras (distancia larga + gatilho)
    for tr, st in itertools.product([2.0, 3.0], [0.5, 1.0]):
        out.append(dict(trail=tr, trail_min_step=0.005, trail_start_r=st))
    return out


def tp_variants():
    """Eixo separado: o alvo fixo. O MFE mediano real e 0,65R e o MAXIMO
    observado em 43 trades foi 1,78R — ou seja tp_rr=2,0 nunca foi alcancavel.
    Testar alvos dentro do alcance observado e obrigatorio."""
    return [None, 0.5, 0.75, 1.0, 1.5, 2.0, 3.0]


def wf_series(base: str, tf: str, spec: Spec, sym_idx: int) -> dict:
    """Walk-forward de PARAMETRO FIXO (sem selecao): mede a mesma configuracao
    em todas as janelas OOS, encadeando equity. Sem selecao nao ha vies de
    selecao — e a medida honesta de 'esta config funciona?'."""
    df = load_ohlcv(base, tf)
    farr = funding_per_candle(df, load_funding(base))
    prep = prepare_both(spec, df)
    step = TF_MS[tf]
    is_bars = IS_DAYS * DAY_MS // step
    oos_bars = OOS_DAYS * DAY_MS // step
    start = prep.warmup + sym_idx * 7 * DAY_MS // step
    equity = START_EQUITY
    eq0 = equity
    r_sum, trades, wins = 0.0, 0, 0
    folds = pos = 0
    for _ in range(10_000):
        oos_a = start + is_bars
        oos_b = oos_a + oos_bars
        if oos_b > len(df):
            break
        ro = run(spec, df, prep, farr, start=oos_a, end=oos_b, start_equity=equity)
        if ro.trades:
            r_sum += ro.r_sum
            trades += ro.trades
            wins += ro.wins
            if ro.total_return_pct > 0:
                pos += 1
            folds += 1
        equity = ro.end_equity
        start += oos_bars
    return dict(ret_pct=(equity / eq0 - 1) * 100, r_sum=r_sum, trades=trades,
                wins=wins, folds=folds, pos_folds=pos)


def main() -> None:
    t0 = time.time()
    rows = []
    for label, tf, base_spec in bases():
        for v in variants():
            for tp in ([base_spec.params.get("tp_rr")] if base_spec.family != "robot_live"
                       else tp_variants()):
                params = dict(base_spec.params)
                params.update(v)
                params["tp_rr"] = tp
                spec = Spec(base_spec.family, f"{label}|{v}|tp{tp}", params)
                agg = dict(ret=0.0, r_sum=0.0, trades=0, wins=0, pos=0, folds=0, series=0)
                per_symbol = []
                for si, sym in enumerate(SYMBOLS):
                    try:
                        s = wf_series(sym, tf, spec, si)
                    except Exception as exc:
                        print(f"  falha {sym} {label}: {exc}", file=sys.stderr)
                        continue
                    per_symbol.append(s["ret_pct"])
                    agg["ret"] += s["ret_pct"]
                    agg["r_sum"] += s["r_sum"]
                    agg["trades"] += s["trades"]
                    agg["wins"] += s["wins"]
                    agg["pos"] += s["pos_folds"]
                    agg["folds"] += s["folds"]
                    agg["series"] += 1
                if not per_symbol:
                    continue
                ser = pd.Series(per_symbol)
                rows.append(dict(
                    base=label, tf=tf, family=base_spec.family,
                    trail=v["trail"], trail_min_step=v["trail_min_step"],
                    trail_start_r=v["trail_start_r"], tp_rr=tp,
                    ret_median=float(ser.median()), ret_mean=float(ser.mean()),
                    ret_min=float(ser.min()), ret_max=float(ser.max()),
                    series_pos=int((ser > 0).sum()), series=len(ser),
                    r_sum=agg["r_sum"], trades=agg["trades"],
                    r_mean=agg["r_sum"] / agg["trades"] if agg["trades"] else 0.0,
                    wr=agg["wins"] / agg["trades"] if agg["trades"] else 0.0,
                    pos_folds=agg["pos"], folds=agg["folds"]))
        print(f"  {label} pronto ({time.time()-t0:.0f}s, {len(rows)} linhas)", flush=True)

    df = pd.DataFrame(rows)
    df.to_csv(OUT / "trailing_sweep.csv", index=False)
    print(f"\ntrailing_sweep.csv: {len(df)} linhas ({time.time()-t0:.0f}s)")

    for label in df.base.unique():
        s = df[df.base == label]
        print("\n" + "=" * 104)
        print(f"{label}   (mediana de {int(s.series.iloc[0])} simbolos, walk-forward de parametro FIXO)")
        print("=" * 104)
        print(f'{"trail":>6s} {"min_step":>9s} {"start_R":>8s} {"tp_rr":>6s} '
              f'{"med%":>8s} {"media%":>8s} {"pos":>6s} {"R/trade":>9s} '
              f'{"WR":>6s} {"trades":>7s}')
        for _, r in s.sort_values("r_mean", ascending=False).head(18).iterrows():
            print(f'{str(r.trail):>6s} {r.trail_min_step:9.4f} {r.trail_start_r:8.2f} '
                  f'{str(r.tp_rr):>6s} {r.ret_median:+7.2f}% {r.ret_mean:+7.2f}% '
                  f'{int(r.series_pos)}/{int(r.series)}  {r.r_mean:+9.4f} '
                  f'{100*r.wr:5.1f}% {int(r.trades):7d}')

    json.dump({"n_rows": len(df)}, open(OUT / "trailing_summary.json", "w"), indent=2)
    print(f"\nConcluido em {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
