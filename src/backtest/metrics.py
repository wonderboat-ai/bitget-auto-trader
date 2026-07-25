"""Métricas de desempenho do backtest.

Objetivo: dizer honestamente se a estratégia tem edge, sem maquiar. Um número
que importa mais que 'lucro total' é a EXPECTATIVA por trade e o MAX DRAWDOWN —
uma curva que ganha muito mas cava 40% no meio é inoperável na prática.
"""
from __future__ import annotations

from dataclasses import dataclass

from src.backtest.backtester import BacktestResult


@dataclass
class Metrics:
    n_trades: int
    win_rate: float
    total_return_pct: float
    max_drawdown_pct: float
    profit_factor: float
    expectancy_usdt: float
    avg_win: float
    avg_loss: float
    n_wins: int
    n_losses: int
    # Kill switch disparado dentro do intervalo censura o resto da janela
    # (zero entradas até o fim). Sem expor isso, o relatório saía "AMOSTRA
    # PEQUENA" sem causa visível.
    kill_switch_ts: int | None = None


def compute_metrics(result: BacktestResult) -> Metrics:
    closed = [t for t in result.trades if t.pnl_usdt is not None]
    n = len(closed)
    if n == 0:
        return Metrics(0, 0, 0, _max_dd(result), 0, 0, 0, 0, 0, 0,
                       kill_switch_ts=result.kill_switch_ts)

    wins = [t.pnl_usdt for t in closed if t.pnl_usdt > 0]
    losses = [t.pnl_usdt for t in closed if t.pnl_usdt <= 0]
    gross_win = sum(wins)
    gross_loss = abs(sum(losses))

    total_ret = (result.end_equity - result.start_equity) / result.start_equity * 100
    profit_factor = (gross_win / gross_loss) if gross_loss > 0 else float("inf")
    expectancy = sum(t.pnl_usdt for t in closed) / n

    return Metrics(
        n_trades=n,
        win_rate=len(wins) / n * 100,
        total_return_pct=total_ret,
        max_drawdown_pct=_max_dd(result),
        profit_factor=profit_factor,
        expectancy_usdt=expectancy,
        avg_win=(gross_win / len(wins)) if wins else 0.0,
        avg_loss=(-gross_loss / len(losses)) if losses else 0.0,
        n_wins=len(wins),
        n_losses=len(losses),
        kill_switch_ts=result.kill_switch_ts,
    )


def _max_dd(result: BacktestResult) -> float:
    """Máximo drawdown da curva de equity (%)."""
    peak = result.start_equity
    max_dd = 0.0
    for _, eq in result.equity_curve:
        peak = max(peak, eq)
        if peak > 0:
            dd = (peak - eq) / peak * 100
            max_dd = max(max_dd, dd)
    return max_dd


def format_report(m: Metrics, symbol: str, timeframe: str, start_eq: float, end_eq: float) -> str:
    pf = "∞" if m.profit_factor == float("inf") else f"{m.profit_factor:.2f}"
    verdict = _verdict(m)
    ks_line = ""
    if m.kill_switch_ts is not None:
        from datetime import datetime, timezone
        ks_dt = datetime.fromtimestamp(m.kill_switch_ts / 1000, tz=timezone.utc)
        ks_line = (f"  ⚠ Kill switch ........... disparou {ks_dt:%Y-%m-%d %H:%M} UTC — "
                   f"entradas censuradas daí em diante\n")
    return f"""{ks_line}
╔══════════════════════════════════════════════════════════╗
  BACKTEST — {symbol}  {timeframe}
╚══════════════════════════════════════════════════════════╝
  Capital inicial ......... {start_eq:,.2f} USDT
  Capital final ........... {end_eq:,.2f} USDT
  Retorno total ........... {m.total_return_pct:+.2f}%
  Max drawdown ............ {m.max_drawdown_pct:.2f}%
  ----------------------------------------------------------
  Nº de trades ............ {m.n_trades}   (W {m.n_wins} / L {m.n_losses})
  Win rate ................ {m.win_rate:.1f}%
  Profit factor ........... {pf}
  Expectativa / trade ..... {m.expectancy_usdt:+.2f} USDT
  Ganho médio ............. {m.avg_win:+.2f} USDT
  Perda média ............. {m.avg_loss:+.2f} USDT
  ----------------------------------------------------------
  Veredito ................ {verdict}
╚══════════════════════════════════════════════════════════╝
"""


def _verdict(m: Metrics) -> str:
    if m.n_trades < 30:
        return "AMOSTRA PEQUENA — insuficiente para conclusão estatística"
    if m.expectancy_usdt <= 0:
        return "SEM EDGE — expectativa negativa; não operar"
    if m.max_drawdown_pct > 25:
        return "DRAWDOWN ALTO — edge existe mas risco inoperável"
    if m.profit_factor < 1.2:
        return "EDGE FRACO — margem fina, sensível a custos"
    return "PROMISSOR — validar out-of-sample antes de capital real"
