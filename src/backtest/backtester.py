"""Motor de backtest — replay candle-a-candle SEM look-ahead.

Regra de ouro contra viés de antecipação (look-ahead):
  - A decisão no candle i usa APENAS dados até o fechamento de i.
  - A entrada é preenchida no OPEN do candle i+1 (você não opera o preço que
    ainda não fechou).
  - Stop e take-profit de uma posição aberta são checados contra o high/low dos
    candles seguintes.

Reutiliza o MESMO RiskManager e o MESMO contrato Signal do live. É isso que
garante que o backtest reflita o comportamento real de risco (veto, sizing, kill
switch). A estratégia é injetada — hoje a determinística, amanhã a do Claude.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from src.data.market_data import compute_indicators, snapshot_from_df
from src.logger import get_logger
from src.risk.risk_manager import PortfolioState, RiskManager
from src.strategy.deterministic import DeterministicStrategy
from src.strategy.signal import TRAIL_MIN_STEP_PCT, Direction, Signal

log = get_logger("backtester")

# Custos por lado (taker) — ajuste conforme sua taxa real na Bybit.
DEFAULT_FEE_PCT = 0.055 / 100        # perpétuos: 0.055% por execução
DEFAULT_FEE_PCT_SPOT = 0.1 / 100     # spot: taker 0.1% (quase 2x o perp)
DEFAULT_SLIPPAGE_PCT = 0.02 / 100


@dataclass
class Trade:
    symbol: str
    direction: str
    entry_ts: int
    entry_price: float
    size: float
    stop_price: float
    take_profit: float | None
    entry_fee: float = 0.0
    exit_ts: int | None = None
    exit_price: float | None = None
    pnl_usdt: float | None = None
    exit_reason: str | None = None
    # Trailing stop (20/07/2026) — paridade com o live: distância fixa entre o
    # pico visto e o stop; o pico só é atualizado DEPOIS das checagens de
    # saída do candle (sem look-ahead intra-candle: não dá pra saber se o
    # high veio antes do low dentro do mesmo candle).
    trailing: bool = False
    trail_distance: float | None = None
    peak_price: float | None = None

    @property
    def is_open(self) -> bool:
        return self.exit_ts is None


@dataclass
class BacktestResult:
    trades: list[Trade] = field(default_factory=list)
    equity_curve: list[tuple[int, float]] = field(default_factory=list)
    start_equity: float = 0.0
    end_equity: float = 0.0
    # ts (ms) do 1º disparo do kill switch no intervalo, ou None. Sem isto, o
    # trip censurava silenciosamente o resto da janela (zero entradas) e o
    # relatório saía como "AMOSTRA PEQUENA" sem causa visível — visto no
    # backtest BTC 15m de 15/07/2026 (drawdown 3,42% no dia 12/07).
    kill_switch_ts: int | None = None


class Backtester:
    def __init__(
        self,
        risk_cfg: dict,
        strategy=None,
        profile: str = "daytrade",
        fee_pct: float = DEFAULT_FEE_PCT,
        slippage_pct: float = DEFAULT_SLIPPAGE_PCT,
        warmup: int = 60,
    ) -> None:
        self.cfg = risk_cfg
        # Aceita uma instância de estratégia (para injetar params otimizados no
        # walk-forward). Se nenhuma vier, usa a determinística com defaults.
        self.strategy = strategy if strategy is not None else DeterministicStrategy(profile)
        # Com market.type=spot no YAML, a taxa default acompanha (taker spot é
        # ~2x a de perp; backtest spot com fee de perp sairia otimista). Um
        # fee_pct passado explicitamente pelo chamador continua mandando.
        if fee_pct == DEFAULT_FEE_PCT:
            from config.settings import get_market_type
            if get_market_type(risk_cfg) == "spot":
                fee_pct = DEFAULT_FEE_PCT_SPOT
        self.fee_pct = fee_pct
        self.slippage_pct = slippage_pct
        self.warmup = warmup

    def run(
        self,
        symbol: str,
        timeframe: str,
        df: pd.DataFrame,
        start: int | None = None,
        end: int | None = None,
        start_equity: float | None = None,
        precomputed: bool = False,
    ) -> BacktestResult:
        """Roda o backtest.

        start/end delimitam o intervalo de índices a operar (para folds de
        walk-forward). Os indicadores são calculados sobre o DataFrame INTEIRO,
        então mesmo o primeiro candle do intervalo tem histórico válido — sem
        recomputar por fold e sem quebra de warmup na fronteira.
        precomputed=True pula o cálculo (o df já traz as colunas de indicadores).
        start_equity permite costurar o capital entre folds OOS.
        """
        if not precomputed:
            df = compute_indicators(df).reset_index(drop=True)
        risk = RiskManager(self.cfg)

        equity = float(start_equity if start_equity is not None
                       else self.cfg["account"]["base_capital_usdt"])
        day_start = equity
        current_day: int | None = None  # dia UTC corrente (ts // 86_400_000)
        peak = equity
        result = BacktestResult(start_equity=equity)

        open_trade: Trade | None = None

        lo = max(self.warmup, start if start is not None else self.warmup)
        hi = (end if end is not None else len(df)) - 1
        for i in range(lo, hi):
            row = df.iloc[i]
            nxt = df.iloc[i + 1]  # candle onde a ordem seria preenchida

            # Virada de dia UTC: refaz o marco do drawdown DIÁRIO (mesma semântica
            # do live corrigido). Antes, day_start ficava preso no início do
            # intervalo — um dip de 3% em QUALQUER ponto disparava o kill switch
            # e travava silenciosamente todo o resto do backtest/fold.
            row_day = int(row["ts"]) // 86_400_000
            if current_day is None:
                current_day = row_day
            elif row_day != current_day:
                current_day = row_day
                day_start = equity

            # 1) Gestão de posição aberta: checa stop/TP no candle atual.
            if open_trade is not None:
                closed = self._try_close(open_trade, row)
                if closed is not None:
                    equity += closed
                    result.trades.append(open_trade)
                    open_trade = None

            # 1b) Saída por SINAL (20/07/2026) — paridade com o live: a
            # estratégia decide no candle FECHADO i e a venda a mercado
            # preenche no OPEN de i+1 (mesma convenção da entrada; o open é o
            # primeiro preço disponível cronologicamente — fechar nele nunca
            # é mais otimista que o live, que sai a mercado no ciclo após a
            # virada). Roda DEPOIS do stop/TP do candle i (que têm prioridade
            # cronológica dentro do candle já fechado) e só consulta a
            # estratégia se ela declarar wants_exit_signals (custo zero com o
            # default desligado — replay idêntico ao validado).
            if (open_trade is not None
                    and getattr(self.strategy, "wants_exit_signals", False)
                    # mesmo guard defensivo do engine (_check_signal_exit):
                    # estratégia que declara wants_exit_signals sem implementar
                    # should_exit não pode derrubar o replay inteiro.
                    and getattr(self.strategy, "should_exit", None) is not None):
                window = df.iloc[: i + 1]
                snap = snapshot_from_df(symbol, timeframe, window,
                                        funding_rate=0.0, fetched_at=0.0)
                position = {"entry_price": open_trade.entry_price,
                            "stop_price": open_trade.stop_price,
                            "take_profit": open_trade.take_profit,
                            "size": open_trade.size,
                            "side": open_trade.direction}
                rationale = self.strategy.should_exit(snap, position)
                if rationale:
                    fill = float(nxt["open"]) * (
                        1 - self.slippage_pct
                        if open_trade.direction == Direction.LONG.value
                        else 1 + self.slippage_pct
                    )
                    equity += self._close_at(open_trade, fill, int(nxt["ts"]),
                                             "signal_exit")
                    result.trades.append(open_trade)
                    open_trade = None

            # 2) Saúde do portfólio (drawdown/kill switch) com equity corrente.
            state = PortfolioState(
                equity_usdt=equity,
                day_start_equity=day_start,
                peak_equity=peak,
                open_positions=1 if open_trade else 0,
                total_notional=(open_trade.size * open_trade.entry_price) if open_trade else 0.0,
                aggregate_risk_pct=self.cfg["per_trade"]["risk_pct"] if open_trade else 0.0,
            )
            risk.check_portfolio_health(state)
            if risk.halted and result.kill_switch_ts is None:
                result.kill_switch_ts = int(row["ts"])

            # 3) Nova entrada só se não há posição aberta e sem kill switch.
            if open_trade is None and not risk.halted:
                window = df.iloc[: i + 1]  # SEM look-ahead: só até o candle i
                snap = snapshot_from_df(symbol, timeframe, window, funding_rate=0.0,
                                        fetched_at=0.0)
                snap.fetched_at = float(row["ts"]) / 1000  # idade "fresca" no backtest
                signal = self.strategy.generate(snap)
                # data_age_sec=0 no backtest (dado sempre "atual" no replay).
                decision = risk.evaluate(signal, state, funding_rate=0.0, data_age_sec=0)
                if decision.approved:
                    fill = float(nxt["open"]) * (
                        1 + self.slippage_pct if signal.direction == Direction.LONG
                        else 1 - self.slippage_pct
                    )
                    # Re-ancora stop/TP no fill — MESMA regra do executor live
                    # (fix #26 de 20/07): stop/TP vêm calculados sobre o close
                    # do candle do sinal; o fill é o open do candle seguinte
                    # (gap + slippage). Sem o deslocamento, o replay arrisca
                    # d+drift por unidade (não o d que o sizing usou), o R:R
                    # efetivo diverge do live e um gap pode fechar "take_profit"
                    # com prejuízo — achado confirmado da revisão adversarial
                    # de 20/07 (paridade live↔replay é requisito da régua).
                    drift = fill - signal.entry_price
                    stop_bt = decision.stop_price + drift
                    tp_bt = (signal.take_profit + drift
                             if signal.take_profit else None)
                    entry_fee = fill * decision.position_size * self.fee_pct
                    open_trade = Trade(
                        symbol=symbol,
                        direction=signal.direction.value,
                        entry_ts=int(nxt["ts"]),
                        entry_price=fill,
                        size=decision.position_size,
                        stop_price=stop_bt,
                        take_profit=tp_bt,
                        entry_fee=entry_fee,
                        # Paridade com o executor live (20/07): distância do
                        # trailing = |fill - stop re-ancorado| = a distância
                        # PURA do sinal (o drift cancela); pico começa no fill.
                        trailing=signal.trailing,
                        trail_distance=(abs(fill - stop_bt)
                                        if signal.trailing else None),
                        peak_price=(fill if signal.trailing else None),
                    )
                    equity -= entry_fee  # caixa: taxa de entrada sai no ato

            peak = max(peak, equity)
            result.equity_curve.append((int(row["ts"]), equity))

        # Fecha posição remanescente no último candle DO INTERVALO (não do df inteiro).
        if open_trade is not None:
            last = df.iloc[hi]
            pnl = self._close_at(open_trade, float(last["close"]), int(last["ts"]), "fim_do_intervalo")
            equity += pnl
            result.trades.append(open_trade)
            # Registra o ponto final na curva — senão o max drawdown ignora
            # o efeito do fechamento forçado.
            result.equity_curve.append((int(last["ts"]), equity))

        result.end_equity = equity
        log.info("Backtest: %d trades, equity %.2f -> %.2f", len(result.trades),
                 result.start_equity, result.end_equity)
        return result

    # ---------------- fechamento ----------------
    def _try_close(self, trade: Trade, row) -> float | None:
        """Checa se stop ou TP foi atingido no candle. Conservador: stop tem
        prioridade. Trailing (20/07/2026): o stop checado é o TRAILED até o
        candle ANTERIOR; o pico só avança DEPOIS das checagens deste candle —
        dentro de um candle não dá pra saber se o high veio antes do low, e
        usar o high do próprio candle pra subir o stop e então checá-lo
        contra o low do mesmo candle seria look-ahead otimista."""
        high, low = float(row["high"]), float(row["low"])
        stop_reason = "trailing_stop" if trade.trailing else "stop"
        result = None
        if trade.direction == Direction.LONG.value:
            if low <= trade.stop_price:
                result = self._close_at(trade, trade.stop_price, int(row["ts"]), stop_reason)
            elif trade.take_profit and high >= trade.take_profit:
                result = self._close_at(trade, trade.take_profit, int(row["ts"]), "take_profit")
        else:  # SHORT
            if high >= trade.stop_price:
                result = self._close_at(trade, trade.stop_price, int(row["ts"]), stop_reason)
            elif trade.take_profit and low <= trade.take_profit:
                result = self._close_at(trade, trade.take_profit, int(row["ts"]), "take_profit")

        # Atualiza o trailing SÓ se o trade continua aberto — mesmo passo
        # mínimo do live (TRAIL_MIN_STEP_PCT sobre o close do candle, o
        # análogo do "preço atual" do ciclo). O pico persiste mesmo quando o
        # stop não move (paridade com o live, que grava o pico no arquivo).
        if result is None and trade.trailing and trade.trail_distance:
            min_step = float(row["close"]) * TRAIL_MIN_STEP_PCT
            if trade.direction == Direction.LONG.value:
                peak = max(trade.peak_price or trade.entry_price, high)
                new_stop = peak - trade.trail_distance
                if new_stop > trade.stop_price + min_step:
                    trade.stop_price = new_stop
                trade.peak_price = peak
            else:  # SHORT: o "pico" é o fundo; o stop desce travando lucro
                trough = min(trade.peak_price or trade.entry_price, low)
                new_stop = trough + trade.trail_distance
                if new_stop < trade.stop_price - min_step:
                    trade.stop_price = new_stop
                trade.peak_price = trough
        return result

    def _close_at(self, trade: Trade, price: float, ts: int, reason: str) -> float:
        gross = (price - trade.entry_price) * trade.size
        if trade.direction == Direction.SHORT.value:
            gross = -gross
        exit_fee = price * trade.size * self.fee_pct
        # Retorno = delta de CAIXA no fechamento (a fee de entrada já saiu do
        # equity na abertura). Mas o pnl_usdt do TRADE precisa incluir a fee de
        # entrada: era debitada só do equity, e expectancy/profit factor/win
        # rate (base do veredito SEM EDGE e da otimização IS do walk-forward)
        # saíam inflados ~1 fee de entrada por trade — auditoria de 15/07/2026
        # comprovou sum(pnl) - Δequity = exatamente a soma das fees de entrada.
        # Agora sum(pnl_usdt) == Δequity fecha por construção.
        cash_delta = gross - exit_fee
        trade.exit_ts = ts
        trade.exit_price = price
        trade.pnl_usdt = cash_delta - trade.entry_fee
        trade.exit_reason = reason
        return cash_delta
