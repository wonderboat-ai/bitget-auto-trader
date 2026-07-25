"""Pesquisa 2b — famílias de TENDÊNCIA (donchian, ema_cross) em 1h/4h, com dado
NOVO (2024-04 a 2026-07, ~2,25 anos, regime misto) e saída por sinal/trailing
simuláveis (o pré-requisito de engenharia que faltava em 16/07 já foi resolvido
— ver CLAUDE.md 21/07).

Por que um script separado de research/sweep.py: aquele varria 6 famílias em
3 timeframes sobre 6 meses 100% bear (dataset QUEIMADO — já foi inspecionado
demais para servir de seleção de estratégia de novo, ver
RELATORIO-2026-07-16.md). Este roda só sobre research/data_2b/ (dataset novo,
nunca inspecionado antes desta sessão) e foca só nas duas famílias que a
pesquisa anterior recomendou re-testar quando saída por sinal/trailing
existisse. `robot_baseline` entra só como referência de controle (a estratégia
atual do robô), não como candidata.

Metodologia idêntica a sweep.py (ver docstring lá): split IS/OOS 70/30 pra
grade bruta; walk-forward por família (t-stat de seleção, mín. 8 trades) pra
veredito de edge real. NOVO aqui: benchmark de buy-and-hold sobre a MESMA
janela que o walk-forward testa (da barra `is_bars` até o fim), pra separar
edge real de beta do próprio mercado — a lição da pesquisa short de 16/07
(38/108 células "positivas" que eram 100% beta, 0/38 batiam o passivo).

Saídas: research/results_2b/full_grid.csv, wf_results.csv, summary.json
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import Spec, load as _load_base, prepare, run, START_EQUITY  # noqa: E402

HERE = Path(__file__).resolve().parent
DATA_DIR = HERE / "data_2b"
OUT = HERE / "results_2b"
OUT.mkdir(exist_ok=True)

SYMBOLS = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "XRP/USDT", "BNB/USDT"]
TFS = ["1h", "4h"]
BARS_PER_DAY = {"1h": 24, "4h": 6}

WF_IS_DAYS = 90
WF_OOS_DAYS = 18
MIN_TRADES_SELECT = 8


def load(symbol: str, tf: str) -> pd.DataFrame:
    path = DATA_DIR / f"{symbol.replace('/', '_')}_{tf}.csv"
    df = pd.read_csv(path)
    return df.sort_values("ts").reset_index(drop=True)


def build_grid_2b() -> list[Spec]:
    specs: list[Spec] = []

    # ---- ema_cross: modo stop-fixo (+ TP opcional) ----
    for fast, slow in [(9, 21), (12, 26), (20, 50), (50, 200)]:
        for atr_stop in [1.5, 2.5]:
            for tp_rr in [None, 2.0]:
                for on_cross in [True, False]:
                    specs.append(Spec(
                        "ema_cross",
                        f"ema{fast}/{slow}_stop{atr_stop}_tp{tp_rr}_{'cross' if on_cross else 'regime'}_fixed",
                        {"fast": fast, "slow": slow, "atr_stop": atr_stop,
                         "tp_rr": tp_rr, "rsi_max": 100.0,
                         "on_cross_only": on_cross, "trail": None}))

    # ---- ema_cross: modo trailing (novo — não existia na grade de 16/07) ----
    for fast, slow in [(9, 21), (12, 26), (20, 50), (50, 200)]:
        for atr_stop in [1.5, 2.5]:
            for trail in [2.5, 3.5]:
                for on_cross in [True, False]:
                    specs.append(Spec(
                        "ema_cross",
                        f"ema{fast}/{slow}_stop{atr_stop}_trail{trail}_{'cross' if on_cross else 'regime'}",
                        {"fast": fast, "slow": slow, "atr_stop": atr_stop,
                         "tp_rr": None, "rsi_max": 100.0,
                         "on_cross_only": on_cross, "trail": trail}))

    # ---- donchian: stop fixo + saída por sinal (canal oposto) ----
    for n in [20, 55]:
        for exit_m in [10, 20]:
            for atr_stop in [2.0, 3.0]:
                specs.append(Spec("donchian", f"don{n}_exit{exit_m}_stop{atr_stop}_fixed",
                                  {"n": n, "exit_m": exit_m, "atr_stop": atr_stop,
                                   "trail": None}))

    # ---- donchian: trailing ----
    for n in [20, 55]:
        for trail in [2.5, 3.5]:
            specs.append(Spec("donchian", f"don{n}_trail{trail}",
                              {"n": n, "exit_m": n // 2, "atr_stop": trail,
                               "trail": trail}))

    # ---- controle: robô como está hoje (referência, não candidata) ----
    specs.append(Spec("robot_baseline", "robo_stop1.5_tp2.0_rsi70",
                      {"atr_stop_mult": 1.5, "tp_rr": 2.0, "rsi_long_max": 70.0}))

    return specs


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
    specs = build_grid_2b()
    print(f"{len(specs)} combinações x {len(SYMBOLS)} símbolos x {len(TFS)} timeframes "
          f"(dataset 2024-04..2026-07, regime misto)")

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

            # ---------- 1) grade IS/OOS (70/30) ----------
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

                # benchmark passivo: buy-and-hold da MESMA janela (is_bars -> n)
                bh_start_px = df["close"].iloc[is_bars]
                bh_end_px = df["close"].iloc[n - 1]
                bh_ret_pct = 100.0 * (bh_end_px / bh_start_px - 1)

                wf_rows.append({
                    "symbol": symbol, "tf": tf, "family": family,
                    "folds": n_folds, "folds_traded": len(traded),
                    "wf_ret_pct": round(total_ret, 2),
                    "buy_hold_ret_pct": round(bh_ret_pct, 2),
                    "beats_buy_hold": bool(total_ret > bh_ret_pct),
                    "wf_trades": sum(f["oos_trades"] for f in fold_stats),
                    "pos_folds": sum(1 for f in traded if f["oos_ret_pct"] > 0),
                    "picks": " | ".join(dict.fromkeys(picks)),
                    "fold_detail": json.dumps(fold_stats),
                })

    grid = pd.DataFrame(grid_rows)
    grid.to_csv(OUT / "full_grid.csv", index=False)
    wf = pd.DataFrame(wf_rows)
    wf.to_csv(OUT / "wf_results.csv", index=False)

    summary = {
        "generated_utc": pd.Timestamp.utcnow().isoformat(),
        "n_specs": len(specs),
        "dataset": "research/data_2b (2024-04-22 a 2026-07-21, regime misto)",
        "series": [f"{s} {t}" for s in SYMBOLS for t in TFS],
        "wf_by_family": wf.drop(columns=["fold_detail"]).to_dict("records"),
        "runtime_sec": round(time.time() - t0, 1),
    }
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"\nConcluído em {summary['runtime_sec']}s — resultados em research/results_2b/")


if __name__ == "__main__":
    main()
