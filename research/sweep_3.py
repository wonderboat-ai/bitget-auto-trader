"""Sweep rodada 3 (18/08/2026) — as 6 familias em PERP long+short, dado novo.

O que esta rodada faz de diferente das duas anteriores (e por que):

1. **Mede a configuracao REAL de producao.** 16/07 mediu spot long-only (fee
   0,1%); 21/07 mediu spot long-only de novo. A producao e perp long+short com
   fee 0,055% e teto de nocional de 50%. Ver harness_perp.py.

2. **Janelas de walk-forward DESSINCRONIZADAS por simbolo.** O painel de juizes
   de 22/07 matou a promocao de donchian/4h ao descobrir que os unicos 2
   resultados positivos vinham do MESMO fold — o crash de 10/10/2025 caiu na
   mesma janela OOS dos 5 simbolos porque o walk-forward usava cortes de
   calendario identicos. Aqui cada simbolo tem o inicio deslocado, de modo que
   um unico evento de mercado nao pode carregar varias series ao mesmo tempo.

3. **8 simbolos, nao 5-6.** Os juizes de 22/07 tambem apontaram que o universo
   pequeno pode nao ser onde o edge esta.

4. **Benchmark honesto para long+short = 0% (caixa).** Uma estrategia que opera
   os dois lados nao pode se defender com "perdeu menos que o buy&hold": ela
   tinha a opcao de lucrar na queda. O buy&hold aparece so como contexto.

Uso:  python research/sweep_3.py [--quick]
"""
from __future__ import annotations

import itertools
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

from harness import Spec
from harness_perp import (load_ohlcv, load_funding, funding_per_candle,
                          prepare_both, run, START_EQUITY)

HERE = Path(__file__).resolve().parent
OUT = HERE / "results_3"
OUT.mkdir(exist_ok=True)

SYMBOLS = ["BTC", "ETH", "SOL", "XRP", "BNB", "DOGE", "ADA", "LINK"]
TIMEFRAMES = ["4h", "1h", "15m"]
TF_MS = {"15m": 900_000, "1h": 3_600_000, "4h": 14_400_000}

IS_DAYS = 90
OOS_DAYS = 18
MIN_IS_TRADES = 8
DAY_MS = 86_400_000


# ------------------------------------------------------------------- grades
def grids() -> list[Spec]:
    specs: list[Spec] = []

    for (fast, slow), only, tp, tr in itertools.product(
            [(9, 21), (20, 50), (50, 200)], [True, False], [None, 2.0], [None, 2.0]):
        specs.append(Spec("ema_cross", f"ema{fast}/{slow}_x{int(only)}_tp{tp}_tr{tr}",
                          dict(fast=fast, slow=slow, on_cross_only=only,
                               rsi_max=100.0, atr_stop=2.0, tp_rr=tp, trail=tr)))

    for n, m, st, tr in itertools.product([20, 55, 100], [10, 20], [1.5, 3.0], [None, 2.0]):
        specs.append(Spec("donchian", f"don{n}/{m}_s{st}_tr{tr}",
                          dict(n=n, exit_m=m, atr_stop=st, tp_rr=None, trail=tr)))

    for buy, ex, st, tp in itertools.product([20, 30], [50, 60], [2.0, 3.0], [None, 1.0]):
        specs.append(Spec("rsi_mr", f"rsi{buy}/{ex}_s{st}_tp{tp}",
                          dict(rsi_buy=buy, rsi_exit=ex, atr_stop=st, tp_rr=tp)))

    for k, ex, st in itertools.product([2.0, 2.5, 3.0], ["mid", "band"], [2.0, 3.0]):
        specs.append(Spec("bollinger_mr", f"bb{k}_{ex}_s{st}",
                          dict(k=k, exit=ex, atr_stop=st, tp_rr=None)))

    for n, th, st in itertools.product([12, 24, 48], [2.0, 5.0], [2.0, 3.0]):
        specs.append(Spec("momentum", f"mom{n}_th{th}_s{st}",
                          dict(n=n, th=th, atr_stop=st, tp_rr=None)))

    # controle: a estrategia que roda ao vivo hoje (e variantes do que o Lucas
    # perguntou — stop mais largo, TP dentro do alcance, trailing on/off)
    for st, tp, tr in itertools.product([1.5, 3.0], [0.75, 2.0], [None, 1.5]):
        specs.append(Spec("robot_live", f"live_s{st}_tp{tp}_tr{tr}",
                          dict(atr_stop_mult=st, tp_rr=tp, rsi_long_max=70.0,
                               rsi_short_min=30.0, trail=tr, trail_min_step=0.001)))
    return specs


# -------------------------------------------------------------- walk-forward
def walk_forward(base: str, tf: str, specs: list[Spec], sym_idx: int) -> list[dict]:
    """IS de 90d seleciona por t-stat do R; OOS de 18d opera as cegas.

    O inicio e deslocado por simbolo (sym_idx * 7 dias) para DESSINCRONIZAR as
    janelas OOS entre simbolos — sem isso, um unico evento de mercado (tipo o
    crash de 10/10/2025) cai no mesmo fold de todos e finge ser edge repetido.
    """
    df = load_ohlcv(base, tf)
    fund = load_funding(base)
    farr = funding_per_candle(df, fund)
    ts = df["ts"].to_numpy()
    step = TF_MS[tf]
    is_bars = IS_DAYS * DAY_MS // step
    oos_bars = OOS_DAYS * DAY_MS // step

    preps = {}
    for sp in specs:
        try:
            preps[sp.name] = prepare_both(sp, df)
        except Exception as exc:
            print(f"    prepare falhou {sp.name}: {exc}", file=sys.stderr)

    warm = max((p.warmup for p in preps.values()), default=60)
    offset = sym_idx * 7 * DAY_MS // step      # dessincroniza por simbolo
    folds = []
    equity = START_EQUITY
    start = warm + offset
    while start + is_bars + oos_bars <= len(df):
        is_a, is_b = start, start + is_bars
        oos_a, oos_b = is_b, is_b + oos_bars
        best, best_t = None, -1e9
        for sp in specs:
            prep = preps.get(sp.name)
            if prep is None:
                continue
            r = run(sp, df, prep, farr, start=is_a, end=is_b)
            if r.trades < MIN_IS_TRADES:
                continue
            t = r.r_tstat
            if t > best_t:
                best_t, best = t, sp
        if best is None:
            start += oos_bars
            continue
        prep = preps[best.name]
        ro = run(best, df, prep, farr, start=oos_a, end=oos_b, start_equity=equity)
        folds.append(dict(symbol=base, tf=tf, family=best.family, pick=best.name,
                          is_tstat=best_t, oos_trades=ro.trades,
                          oos_ret_pct=ro.total_return_pct,
                          oos_r_sum=ro.r_sum, oos_r_mean=ro.r_mean,
                          oos_wr=ro.win_rate, equity_in=equity,
                          equity_out=ro.end_equity,
                          ts_oos_start=int(ts[oos_a]), ts_oos_end=int(ts[oos_b - 1])))
        equity = ro.end_equity
        start += oos_bars
    return folds


def wf_family(base: str, tf: str, specs: list[Spec], sym_idx: int) -> dict:
    """Walk-forward RESTRITO a uma familia (a selecao so escolhe dentro dela) —
    e assim que as rodadas anteriores mediram 'familia X tem edge?'."""
    return {}


def main() -> None:
    quick = "--quick" in sys.argv
    tfs = ["4h"] if quick else TIMEFRAMES
    syms = SYMBOLS[:3] if quick else SYMBOLS
    specs = grids()
    families = sorted({s.family for s in specs})
    print(f"{len(specs)} combinacoes | {len(families)} familias | "
          f"{len(syms)} simbolos | {len(tfs)} timeframes")
    for f in families:
        print(f"   {f:14s} {sum(1 for s in specs if s.family == f):3d} combos")

    t0 = time.time()

    # ---------------- 1. grade completa: IS/OOS 70/30 por (simbolo, tf, combo)
    rows = []
    for tf in tfs:
        for si, base in enumerate(syms):
            df = load_ohlcv(base, tf)
            fund = load_funding(base)
            farr = funding_per_candle(df, fund)
            split = int(len(df) * 0.70)
            for sp in specs:
                try:
                    prep = prepare_both(sp, df)
                except Exception:
                    continue
                ri = run(sp, df, prep, farr, start=prep.warmup, end=split)
                ro = run(sp, df, prep, farr, start=split)
                rows.append(dict(symbol=base, tf=tf, family=sp.family, combo=sp.name,
                                 is_trades=ri.trades, is_ret=ri.total_return_pct,
                                 is_r_mean=ri.r_mean, is_tstat=ri.r_tstat,
                                 oos_trades=ro.trades, oos_ret=ro.total_return_pct,
                                 oos_r_mean=ro.r_mean, oos_tstat=ro.r_tstat,
                                 oos_wr=ro.win_rate, oos_pf=ro.profit_factor,
                                 oos_r_long=ro.r_long, oos_r_short=ro.r_short,
                                 oos_longs=ro.longs, oos_shorts=ro.shorts,
                                 oos_fees=ro.fees_paid, oos_funding=ro.funding_paid,
                                 oos_maxdd=ro.max_dd_pct,
                                 exposure=ro.bars_in_pos / max(ro.bars_total, 1)))
            print(f"  grade {tf} {base}: {len(specs)} combos  ({time.time()-t0:.0f}s)",
                  flush=True)
    fg = pd.DataFrame(rows)
    fg.to_csv(OUT / "full_grid.csv", index=False)
    print(f"\nfull_grid.csv: {len(fg)} linhas ({time.time()-t0:.0f}s)")

    # ---------------- 2. walk-forward POR FAMILIA (selecao restrita a familia)
    wf_rows = []
    for fam in families:
        fam_specs = [s for s in specs if s.family == fam]
        for tf in tfs:
            for si, base in enumerate(syms):
                folds = walk_forward(base, tf, fam_specs, si)
                if not folds:
                    continue
                eq0 = folds[0]["equity_in"]
                eq1 = folds[-1]["equity_out"]
                tot = (eq1 / eq0 - 1) * 100
                r_sum = sum(f["oos_r_sum"] for f in folds)
                n_tr = sum(f["oos_trades"] for f in folds)
                pos = sum(1 for f in folds if f["oos_ret_pct"] > 0)
                # concentracao: quanto do R total vem do melhor fold
                best = max((f["oos_r_sum"] for f in folds), default=0.0)
                conc = best / r_sum if r_sum > 0 else float("nan")
                wf_rows.append(dict(family=fam, symbol=base, tf=tf,
                                    folds=len(folds), wf_ret_pct=tot,
                                    r_sum=r_sum, trades=n_tr,
                                    r_mean=r_sum / n_tr if n_tr else 0.0,
                                    pos_folds=pos,
                                    best_fold_share=conc,
                                    picks=len({f["pick"] for f in folds})))
                print(f"  wf {fam:13s} {base:5s} {tf:4s}: {len(folds):3d} folds "
                      f"ret={tot:+7.2f}% Rsum={r_sum:+7.2f} n={n_tr:4d} "
                      f"pos={pos}/{len(folds)}  ({time.time()-t0:.0f}s)", flush=True)
    wf = pd.DataFrame(wf_rows)
    wf.to_csv(OUT / "wf_results.csv", index=False)
    print(f"\nwf_results.csv: {len(wf)} series ({time.time()-t0:.0f}s)")

    # ---------------- 3. resumo por familia
    print("\n" + "=" * 96)
    print("WALK-FORWARD POR FAMILIA (mediana das series simbolo x timeframe)")
    print("=" * 96)
    print(f'{"familia":15s} {"mediana":>9s} {"media":>9s} {"pos":>7s} '
          f'{"pior":>9s} {"melhor":>9s} {"R/trade":>9s} {"trades":>8s}')
    summary = {}
    for fam in families:
        s = wf[wf.family == fam]
        if s.empty:
            continue
        npos = int((s.wf_ret_pct > 0).sum())
        summary[fam] = dict(median=float(s.wf_ret_pct.median()),
                            mean=float(s.wf_ret_pct.mean()),
                            pos=f"{npos}/{len(s)}",
                            worst=float(s.wf_ret_pct.min()),
                            best=float(s.wf_ret_pct.max()),
                            r_mean=float(s.r_sum.sum() / max(s.trades.sum(), 1)),
                            trades=int(s.trades.sum()))
        d = summary[fam]
        print(f'{fam:15s} {d["median"]:+8.2f}% {d["mean"]:+8.2f}% {d["pos"]:>7s} '
              f'{d["worst"]:+8.2f}% {d["best"]:+8.2f}% {d["r_mean"]:+9.4f} {d["trades"]:8d}')

    print("\nPor timeframe:")
    for tf in tfs:
        s = wf[wf.tf == tf]
        if not s.empty:
            print(f"  {tf:4s} mediana={s.wf_ret_pct.median():+7.2f}%  "
                  f"R/trade={s.r_sum.sum()/max(s.trades.sum(),1):+.4f}  "
                  f"series positivas={int((s.wf_ret_pct>0).sum())}/{len(s)}")

    json.dump(dict(summary=summary, n_specs=len(specs), symbols=syms,
                   timeframes=tfs, is_days=IS_DAYS, oos_days=OOS_DAYS),
              open(OUT / "summary.json", "w"), indent=2)
    print(f"\nConcluido em {time.time()-t0:.0f}s -> {OUT}")


if __name__ == "__main__":
    main()
