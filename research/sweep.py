"""Varredura de estratégias — grade completa + walk-forward por família.

Metodologia (anti-overfitting):
  1. Split 70/30: os primeiros ~70% dos candles são IN-SAMPLE (IS, onde se
     escolhe), os últimos ~30% são OUT-OF-SAMPLE (OOS, intocados na escolha).
     O veredito de edge usa SÓ o OOS.
  2. Walk-forward por família: janela IS rolante (~90 dias) escolhe a melhor
     combinação DA FAMÍLIA (por t-stat do R-múltiplo, mín. 8 trades), aplica na
     janela OOS seguinte (~18 dias), costura o equity. Repete até o fim.
     Isso simula o que um operador disciplinado faria: re-otimizar
     periodicamente e operar o período seguinte "às cegas".
  3. Métrica de seleção: t-stat da média dos R-múltiplos — penaliza edge
     pequeno E amostra pequena de uma vez. PF sozinho premia sorte.

Saídas: research/results/full_grid.csv, wf_results.csv, summary.json
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import Spec, build_grid, load, prepare, run, START_EQUITY  # noqa: E402

HERE = Path(__file__).resolve().parent
OUT = HERE / "results"
OUT.mkdir(exist_ok=True)

SYMBOLS = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "XRP/USDT", "MNT/USDT", "BNB/USDT"]
TFS = ["15m", "1h", "4h"]
BARS_PER_DAY = {"15m": 96, "1h": 24, "4h": 6}

WF_IS_DAYS = 90
WF_OOS_DAYS = 18
MIN_TRADES_SELECT = 8   # mínimo de trades no IS pra combinação ser elegível


def metrics_row(res, prefix: str) -> dict:
    return {
        f"{prefix}_trades": res.trades,
        f"{prefix}_win_rate": round(res.win_rate, 3),
        f"{prefix}_pf": round(res.profit_factor, 3) if res.trades else 0.0,
        f"{prefix}_exp_r": round(res.expectancy_r, 4),
        f"{prefix}_tstat": round(res.tstat_r, 2),
        f"{prefix}_ret_pct": round(res.total_return_pct, 2),
        f"{prefix}_maxdd_pct": round(res.max_dd_pct, 2),
        f"{prefix}_fees": round(res.fees_paid, 2),
    }


def main() -> None:
    t0 = time.time()
    specs = build_grid()
    print(f"{len(specs)} combinações × {len(SYMBOLS)} símbolos × {len(TFS)} timeframes")

    grid_rows: list[dict] = []
    wf_rows: list[dict] = []

    for symbol in SYMBOLS:
        for tf in TFS:
            df = load(symbol, tf)
            n = len(df)
            split = int(n * 0.7)
            bpd = BARS_PER_DAY[tf]
            print(f"--- {symbol} {tf}: {n} candles (IS {split}, OOS {n - split})")

            prepared = {}
            for spec in specs:
                try:
                    prepared[spec.name] = (spec, prepare(spec, df))
                except Exception as exc:
                    print(f"  prepare falhou {spec.name}: {exc}", file=sys.stderr)

            # ---------- 1) grade IS/OOS ----------
            for name, (spec, prep) in prepared.items():
                is_res = run(df, prep, start=None, end=split)
                oos_res = run(df, prep, start=split, end=n)
                row = {"symbol": symbol, "tf": tf, "family": spec.family,
                       "name": name, **metrics_row(is_res, "is"),
                       **metrics_row(oos_res, "oos")}
                grid_rows.append(row)

            # ---------- 2) walk-forward por família ----------
            is_bars = WF_IS_DAYS * bpd
            oos_bars = WF_OOS_DAYS * bpd
            families = sorted({s.family for s, _ in prepared.values()})
            for family in families:
                fam = [(s, p) for s, p in prepared.values() if s.family == family]
                equity = START_EQUITY
                fold_stats = []
                picks = []
                start = is_bars
                while start + oos_bars <= n:
                    # seleção IS: melhor t-stat com nº mínimo de trades
                    best, best_t = None, -1e9
                    for spec, prep in fam:
                        r = run(df, prep, start=start - is_bars, end=start)
                        if r.trades >= MIN_TRADES_SELECT and r.tstat_r > best_t:
                            best, best_t = (spec, prep), r.tstat_r
                    if best is None:
                        fold_stats.append({"fold_start": int(df["ts"].iloc[start]),
                                           "pick": None, "oos_ret_pct": 0.0,
                                           "oos_trades": 0})
                        start += oos_bars
                        continue
                    spec, prep = best
                    o = run(df, prep, start=start, end=min(start + oos_bars, n),
                            start_equity=equity)
                    equity = o.end_equity
                    picks.append(spec.name)
                    fold_stats.append({"fold_start": int(df["ts"].iloc[start]),
                                       "pick": spec.name,
                                       "oos_ret_pct": round(o.total_return_pct, 2),
                                       "oos_trades": o.trades,
                                       "oos_pf": round(o.profit_factor, 2) if o.trades else 0.0})
                    start += oos_bars

                total_ret = 100.0 * (equity / START_EQUITY - 1)
                n_folds = len(fold_stats)
                traded = [f for f in fold_stats if f["pick"]]
                wf_rows.append({
                    "symbol": symbol, "tf": tf, "family": family,
                    "folds": n_folds, "folds_traded": len(traded),
                    "wf_ret_pct": round(total_ret, 2),
                    "wf_trades": sum(f["oos_trades"] for f in fold_stats),
                    "pos_folds": sum(1 for f in traded if f["oos_ret_pct"] > 0),
                    "picks": " | ".join(dict.fromkeys(picks)),
                    "fold_detail": json.dumps(fold_stats),
                })

    grid = pd.DataFrame(grid_rows)
    grid.to_csv(OUT / "full_grid.csv", index=False)
    wf = pd.DataFrame(wf_rows)
    wf.to_csv(OUT / "wf_results.csv", index=False)

    # ---------- resumo ----------
    baseline = grid[(grid["family"] == "robot_baseline") &
                    (grid["name"] == "robo_stop1.5_tp2.0_rsi70")]
    summary = {
        "generated_utc": pd.Timestamp.utcnow().isoformat(),
        "n_specs": len(specs),
        "series": [f"{s} {t}" for s in SYMBOLS for t in TFS],
        "baseline_robot_oos": baseline[["symbol", "tf", "oos_trades", "oos_pf",
                                        "oos_ret_pct", "oos_maxdd_pct"]].to_dict("records"),
        "wf_by_family": wf.drop(columns=["fold_detail"]).to_dict("records"),
        "runtime_sec": round(time.time() - t0, 1),
    }
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"\nConcluído em {summary['runtime_sec']}s — resultados em research/results/")


if __name__ == "__main__":
    main()
