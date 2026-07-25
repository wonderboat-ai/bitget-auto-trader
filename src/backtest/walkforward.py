"""Validação walk-forward — a defesa contra overfitting.

O problema que isto resolve (causa raiz): se você otimizar parâmetros e medir o
resultado nos MESMOS dados, encontra sempre uma combinação que parece ótima — mas
é ajuste ao ruído do passado, não vantagem real. No mercado real, evapora.

Walk-forward corta os dados em janelas sequenciais. Em cada fold:
  1. OTIMIZA os parâmetros na janela in-sample (IS).
  2. CONGELA os melhores e mede o desempenho na janela out-of-sample (OOS),
     que o otimizador nunca viu.
O desempenho honesto é o AGREGADO das janelas OOS. A diferença IS→OOS mede o
quanto a estratégia está superajustada: degradação grande = overfitting.

Os folds avançam no tempo (rolling), então nunca há vazamento de futuro: o OOS de
um fold é sempre posterior ao seu IS.
"""
from __future__ import annotations

import itertools
from dataclasses import dataclass, field

import pandas as pd

from src.backtest.backtester import Backtester, BacktestResult
from src.backtest.metrics import Metrics, compute_metrics
from src.data.market_data import compute_indicators
from src.logger import get_logger
from src.strategy.deterministic import DeterministicStrategy, StrategyParams

log = get_logger("walkforward")

# Grade de busca padrão (parâmetros de DECISÃO). Ajuste conforme necessário.
DEFAULT_GRID = {
    "atr_stop_mult": [1.0, 1.5, 2.0],
    "tp_rr": [1.0, 1.5, 2.0, 3.0],
    "rsi_long_max": [70.0, 75.0],
    "rsi_short_min": [25.0, 30.0],
}


@dataclass
class FoldReport:
    fold: int
    is_range: tuple[int, int]
    oos_range: tuple[int, int]
    best_params: dict
    is_expectancy: float
    is_trades: int
    oos_expectancy: float
    oos_trades: int
    oos_return_pct: float


@dataclass
class WalkForwardReport:
    folds: list[FoldReport] = field(default_factory=list)
    oos_metrics: Metrics | None = None
    stitched_start_equity: float = 0.0
    stitched_end_equity: float = 0.0

    @property
    def is_oos_degradation(self) -> float:
        """Média (IS_expectancy - OOS_expectancy). Positivo e grande = overfitting."""
        if not self.folds:
            return 0.0
        return sum(f.is_expectancy - f.oos_expectancy for f in self.folds) / len(self.folds)


def _grid_combos(grid: dict) -> list[StrategyParams]:
    keys = list(grid.keys())
    combos = []
    for values in itertools.product(*(grid[k] for k in keys)):
        combos.append(StrategyParams(**dict(zip(keys, values))))
    return combos


def _objective(m: Metrics, min_trades: int) -> float:
    """Função-objetivo da otimização IS. Penaliza amostras pequenas.

    Usa expectativa por trade (edge por operação). Sem trades suficientes -> -inf,
    para não escolher params que 'ganham' com 2 trades de sorte."""
    if m.n_trades < min_trades:
        return float("-inf")
    return m.expectancy_usdt


class WalkForward:
    def __init__(
        self,
        risk_cfg: dict,
        symbol: str,
        timeframe: str,
        profile: str = "daytrade",
        grid: dict | None = None,
        is_len: int = 400,
        oos_len: int = 150,
        warmup: int = 60,
        min_trades_is: int = 10,
    ) -> None:
        self.cfg = risk_cfg
        self.symbol = symbol
        self.timeframe = timeframe
        self.profile = profile
        self.grid = grid or DEFAULT_GRID
        self.is_len = is_len
        self.oos_len = oos_len
        self.warmup = warmup
        self.min_trades_is = min_trades_is

    def _make_bt(self, params: StrategyParams) -> Backtester:
        strat = DeterministicStrategy(self.profile, params)
        return Backtester(self.cfg, strategy=strat, warmup=self.warmup)

    def run(self, df: pd.DataFrame) -> WalkForwardReport:
        # Indicadores uma vez só, no df inteiro (fonte única, sem look-ahead por fold).
        df = compute_indicators(df).reset_index(drop=True)
        combos = _grid_combos(self.grid)
        log.info("Walk-forward: %d combinações por fold", len(combos))

        report = WalkForwardReport()
        base_capital = float(self.cfg["account"]["base_capital_usdt"])
        stitched_equity = base_capital
        report.stitched_start_equity = base_capital
        oos_trades = []
        oos_equity_curve: list[tuple[int, float]] = []

        fold = 0
        is_start = self.warmup
        while is_start + self.is_len + self.oos_len <= len(df):
            is_end = is_start + self.is_len
            oos_start = is_end
            oos_end = oos_start + self.oos_len

            # 1) Otimização in-sample.
            best_params, best_is_metrics = None, None
            best_obj = float("-inf")
            for params in combos:
                res = self._make_bt(params).run(
                    self.symbol, self.timeframe, df,
                    start=is_start, end=is_end, precomputed=True,
                )
                m = compute_metrics(res)
                obj = _objective(m, self.min_trades_is)
                if obj > best_obj:
                    best_obj, best_params, best_is_metrics = obj, params, m

            # Nenhuma combinação atingiu trades mínimos -> pula o fold.
            if best_params is None:
                log.warning("Fold %d sem params válidos (poucos trades IS)", fold)
                is_start += self.oos_len
                fold += 1
                continue

            # 2) Validação out-of-sample com params CONGELADOS, capital costurado.
            oos_res = self._make_bt(best_params).run(
                self.symbol, self.timeframe, df,
                start=oos_start, end=oos_end,
                start_equity=stitched_equity, precomputed=True,
            )
            oos_m = compute_metrics(oos_res)
            stitched_equity = oos_res.end_equity
            oos_trades.extend(oos_res.trades)
            oos_equity_curve.extend(oos_res.equity_curve)

            report.folds.append(FoldReport(
                fold=fold,
                is_range=(is_start, is_end),
                oos_range=(oos_start, oos_end),
                best_params=best_params.as_dict(),
                is_expectancy=best_is_metrics.expectancy_usdt,
                is_trades=best_is_metrics.n_trades,
                oos_expectancy=oos_m.expectancy_usdt,
                oos_trades=oos_m.n_trades,
                oos_return_pct=oos_m.total_return_pct,
            ))

            is_start += self.oos_len  # avança no tempo
            fold += 1

        # Métricas agregadas OOS (a partir da curva costurada).
        stitched = BacktestResult(
            trades=oos_trades,
            equity_curve=oos_equity_curve,
            start_equity=base_capital,
            end_equity=stitched_equity,
        )
        report.oos_metrics = compute_metrics(stitched)
        report.stitched_end_equity = stitched_equity
        return report
