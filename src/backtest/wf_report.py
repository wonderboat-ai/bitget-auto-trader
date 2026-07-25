"""Formatação do relatório de walk-forward."""
from __future__ import annotations

from src.backtest.metrics import _verdict
from src.backtest.walkforward import WalkForwardReport


def format_wf_report(r: WalkForwardReport, symbol: str, timeframe: str) -> str:
    lines = []
    lines.append("")
    lines.append("=" * 72)
    lines.append(f"  WALK-FORWARD (out-of-sample)  —  {symbol}  {timeframe}")
    lines.append("=" * 72)
    lines.append("")
    lines.append("  Fold | IS trades | IS exp | OOS trades | OOS exp | OOS ret% | params")
    lines.append("  " + "-" * 68)
    for f in r.folds:
        p = f.best_params
        pstr = f"stop{p['atr_stop_mult']}/rr{p['tp_rr']}/L{p['rsi_long_max']:.0f}/S{p['rsi_short_min']:.0f}"
        lines.append(
            f"  {f.fold:>4} | {f.is_trades:>9} | {f.is_expectancy:>+6.2f} | "
            f"{f.oos_trades:>10} | {f.oos_expectancy:>+7.2f} | {f.oos_return_pct:>+7.2f} | {pstr}"
        )
    lines.append("")

    m = r.oos_metrics
    if m is None or m.n_trades == 0:
        lines.append("  OOS agregado: sem trades — dados insuficientes ou grade inadequada.")
        lines.append("=" * 72)
        return "\n".join(lines)

    pf = "inf" if m.profit_factor == float("inf") else f"{m.profit_factor:.2f}"
    lines.append("  AGREGADO OUT-OF-SAMPLE (o número que importa):")
    lines.append(f"    Capital costurado ..... {r.stitched_start_equity:,.2f} -> {r.stitched_end_equity:,.2f} USDT")
    lines.append(f"    Retorno OOS ........... {m.total_return_pct:+.2f}%")
    lines.append(f"    Max drawdown OOS ...... {m.max_drawdown_pct:.2f}%")
    lines.append(f"    Trades OOS ............ {m.n_trades} (W{m.n_wins}/L{m.n_losses})  win {m.win_rate:.1f}%")
    lines.append(f"    Profit factor OOS ..... {pf}")
    lines.append(f"    Expectativa/trade OOS . {m.expectancy_usdt:+.2f} USDT")
    lines.append(f"    Degradação IS->OOS .... {r.is_oos_degradation:+.2f} USDT/trade  {_deg_note(r.is_oos_degradation)}")
    lines.append("")
    lines.append(f"    Veredito OOS .......... {_verdict(m)}")
    lines.append("=" * 72)
    return "\n".join(lines)


def _deg_note(deg: float) -> str:
    if deg <= 0:
        return "(OOS >= IS: sem sinal de overfitting)"
    if deg < 1:
        return "(degradação leve)"
    if deg < 3:
        return "(degradação relevante — cuidado)"
    return "(degradação alta — provável OVERFITTING)"
