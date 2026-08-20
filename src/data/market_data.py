"""Constrói o 'snapshot de estado' do mercado — a mesma estrutura usada na decisão
e (futuramente) no backtest. Se as duas pontas divergirem, o backtest mente.

Fase 1: candles + indicadores técnicos básicos. As fontes macro e on-chain
entram como campos adicionais do snapshot na Fase 3 (mesma estrutura, novos campos).
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from src.exchange.bitget_client import BitgetClient


@dataclass
class MarketSnapshot:
    symbol: str
    timeframe: str
    last_price: float
    funding_rate: float | None
    indicators: dict[str, float]
    candles: pd.DataFrame
    fetched_at: float = field(default_factory=time.time)
    # Contexto adicional (macro, on-chain, etc.) usado pela camada de decisão do
    # Claude na Fase 3. Vazio na estratégia determinística — mesma estrutura, novos
    # campos, sem quebrar quem não usa.
    context: dict = field(default_factory=dict)

    def age_sec(self) -> float:
        return time.time() - self.fetched_at


def _ema(series: pd.Series, length: int) -> pd.Series:
    return series.ewm(span=length, adjust=False).mean()


def _rsi(series: pd.Series, length: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0).rolling(length).mean()
    loss = (-delta.clip(upper=0)).rolling(length).mean()
    rs = gain / loss.replace(0, float("nan"))
    return 100 - (100 / (1 + rs))


def _atr(df: pd.DataFrame, length: int = 14) -> pd.Series:
    high, low, close = df["high"], df["low"], df["close"]
    prev_close = close.shift(1)
    tr = pd.concat(
        [(high - low), (high - prev_close).abs(), (low - prev_close).abs()], axis=1
    ).max(axis=1)
    return tr.rolling(length).mean()


def compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Adiciona colunas de indicadores ao DataFrame. FONTE ÚNICA usada por live e backtest.

    Se live e backtest calculassem indicadores de formas diferentes, o backtest
    mentiria. Por isso os dois caminhos passam exatamente por aqui.
    """
    df = df.copy()
    df["ema_fast"] = _ema(df["close"], 20)
    df["ema_slow"] = _ema(df["close"], 50)
    df["rsi"] = _rsi(df["close"], 14)
    df["atr"] = _atr(df, 14)
    return df


def snapshot_from_df(
    symbol: str,
    timeframe: str,
    df: pd.DataFrame,
    funding_rate: float | None,
    fetched_at: float | None = None,
) -> MarketSnapshot:
    """Monta um MarketSnapshot a partir de um DataFrame já com indicadores calculados.

    Usa a ÚLTIMA linha como estado atual. No backtest, passe apenas as linhas até
    o candle corrente (sem look-ahead)."""
    last = df.iloc[-1]
    indicators = {
        "ema_fast": float(last["ema_fast"]),
        "ema_slow": float(last["ema_slow"]),
        "rsi": float(last["rsi"]),
        "atr": float(last["atr"]),
        "close": float(last["close"]),
    }
    snap = MarketSnapshot(
        symbol=symbol,
        timeframe=timeframe,
        last_price=float(last["close"]),
        funding_rate=funding_rate,
        indicators=indicators,
        candles=df,
    )
    if fetched_at is not None:
        snap.fetched_at = fetched_at
    return snap


def build_snapshot(client: BitgetClient, symbol: str, timeframe: str, limit: int = 200) -> MarketSnapshot:
    raw = client.fetch_ohlcv(symbol, timeframe, limit=limit)
    df = pd.DataFrame(raw, columns=["ts", "open", "high", "low", "close", "volume"])
    # A Bybit devolve o candle EM FORMAÇÃO como última linha (high/low/close ainda
    # mudando). Decidir sobre ele gera sinal que 'repinta' — e diverge do backtest,
    # que por princípio decide só em candle FECHADO (sem look-ahead). Descarta.
    if len(df) > 1:
        df = df.iloc[:-1]
    df["dt"] = pd.to_datetime(df["ts"], unit="ms", utc=True)
    df = compute_indicators(df)
    return snapshot_from_df(symbol, timeframe, df, client.fetch_funding_rate(symbol))
