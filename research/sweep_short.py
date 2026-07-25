"""Varredura SHORT em perpétuos — grade completa + walk-forward por família.

Espelho de sweep.py (mesma metodologia anti-overfitting: split 70/30, WF com
IS 90d/OOS 18d, seleção por t-stat com mín. 8 trades). Diferenças:
  - motor short de harness_short.py (funding real, leverage 2x, liquidação);
  - dados de PERPÉTUOS (research/data_perp/);
  - fix do bug de pos_folds da rodada long: o retorno por fold agora é DO FOLD
    (base = equity no início do fold), não o cumulativo desde o começo — a
    rodada long reportava 66/108 células com contagem errada por isso.

Saídas: research/results/short/{full_grid.csv, wf_results.csv, summary.json}
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness_short import (  # noqa: E402
    START_EQUITY, align_funding, build_grid_short, load_funding, load_perp,
    prepare_short, run_short,
)

HERE = Path(__file__).resolve().parent
OUT = HERE / "results" / "short"
OUT.mkdir(parents=True, exist_ok=True)

SYMBOLS = ["BTC", "ETH", "SOL", "XRP", "MNT", "BNB"]
TFS = ["15m", "1h", "4h"]
BARS_PER_DAY = {"15m": 96, "1h": 24, "4h": 6}
TF_MS = {"15m": 900_000, "1h": 3_600_000, "4h": 14_400_000}

WF_IS_DAYS = 90
WF_OOS_DAYS = 18
MIN_TRADES_SELECT = 8


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
        f"{prefix}_funding": round(res.funding_received, 2),
        f"{prefix}_liqs": res.liquidations,
    }


def main() -> None:
    t0 = time.time()
    specs = build_grid_short()
    print(f"{len(specs)} combinações × {len(SYMBOLS)} símbolos × {len(TFS)} timeframes")

    grid_rows: list[dict] = []
    wf_rows: list[dict] = []

    for symbol in SYMBOLS:
        funding = load_funding(symbol)
        for tf in TFS:
            df = load_perp(symbol, tf)
            n = len(df)
            split = int(n * 0.7)
            bpd = BARS_PER_DAY[tf]
            frates = align_funding(df, funding, TF_MS[tf])
            print(f"--- {symbol} {tf}: {n} candles (IS {split}, OOS {n - split}, "
                  f"{int((frates != 0).sum())} candles com funding)")

            prepared = {}
            for spec in specs:
                try:
                    prepared[spec.name] = (spec, prepare_short(spec, df))
                except Exception as exc:
                    print(f"  prepare falhou {spec.name}: {exc}", file=sys.stderr)

            # ---------- 1) grade IS/OOS ----------
            for name, (spec, prep) in prepared.items():
                is_res = run_short(df, prep, frates, start=None, end=split)
                oos_res = run_short(df, prep, frates, start=split, end=n)
                grid_rows.append({"symbol": symbol, "tf": tf, "family": spec.family,
                                  "name": name, **metrics_row(is_res, "is"),
                                  **metrics_row(oos_res, "oos")})

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
                    best, best_t = None, -1e9
                    for spec, prep in fam:
                        r = run_short(df, prep, frates, start=start - is_bars, end=start)
                        if r.trades >= MIN_TRADES_SELECT and r.tstat_r > best_t:
                            best, best_t = (spec, prep), r.tstat_r
                    if best is None:
                        fold_stats.append({"fold_start": int(df["ts"].iloc[start]),
                                           "pick": None, "fold_ret_pct": 0.0,
                                           "oos_trades": 0})
                        start += oos_bars
                        continue
                    spec, prep = best
                    eq_before = equity
                    o = run_short(df, prep, frates, start=start,
                                  end=min(start + oos_bars, n), start_equity=equity)
                    equity = o.end_equity
                    picks.append(spec.name)
                    # retorno DO FOLD (base eq_before) — não o cumulativo.
                    fold_stats.append({"fold_start": int(df["ts"].iloc[start]),
                                       "pick": spec.name,
                                       "fold_ret_pct": round(100.0 * (equity / eq_before - 1), 2),
                                       "oos_trades": o.trades,
                                       "oos_pf": round(o.profit_factor, 2) if o.trades else 0.0})
                    start += oos_bars

                traded = [f for f in fold_stats if f["pick"]]
                wf_rows.append({
                    "symbol": symbol, "tf": tf, "family": family,
                    "folds": len(fold_stats), "folds_traded": len(traded),
                    "wf_ret_pct": round(100.0 * (equity / START_EQUITY - 1), 2),
                    "wf_trades": sum(f["oos_trades"] for f in fold_stats),
                    "pos_folds": sum(1 for f in traded if f["fold_ret_pct"] > 0),
                    "picks": " | ".join(dict.fromkeys(picks)),
                    "fold_detail": json.dumps(fold_stats),
                })

    grid = pd.DataFrame(grid_rows)
    grid.to_csv(OUT / "full_grid.csv", index=False)
    wf = pd.DataFrame(wf_rows)
    wf.to_csv(OUT / "wf_results.csv", index=False)

    baseline = grid[(grid["family"] == "robot_baseline") &
                    (grid["name"] == "robo_stop1.5_tp2.0_rsi30")]
    summary = {
        "generated_utc": pd.Timestamp.utcnow().isoformat(),
        "direction": "short_2x_perp_funding",
        "n_specs": len(specs),
        "series": [f"{s} {t}" for s in SYMBOLS for t in TFS],
        "baseline_robot_oos": baseline[["symbol", "tf", "oos_trades", "oos_pf",
                                        "oos_ret_pct", "oos_maxdd_pct",
                                        "oos_funding", "oos_liqs"]].to_dict("records"),
        "wf_by_family": wf.drop(columns=["fold_detail"]).to_dict("records"),
        "runtime_sec": round(time.time() - t0, 1),
    }
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"\nConcluído em {summary['runtime_sec']}s — resultados em research/results/short/")


if __name__ == "__main__":
    main()
