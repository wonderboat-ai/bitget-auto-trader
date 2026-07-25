"""Carrega candles históricos para backtest.

Usa o endpoint PÚBLICO da Bybit via CCXT (OHLCV não exige chave de API). Pagina
para trás a partir de agora, monta um DataFrame limpo e cacheia em CSV para não
rebaixar a API a cada rodada. Se já houver cache, lê do disco.

Também aceita um CSV externo, caso você queira testar com dados de outra fonte.
"""
from __future__ import annotations

import time
from pathlib import Path

import ccxt
import pandas as pd

from src.logger import get_logger

log = get_logger("data_loader")

ROOT = Path(__file__).resolve().parent.parent.parent
CACHE_DIR = ROOT / "data"
CACHE_DIR.mkdir(exist_ok=True)

# Aproximação de milissegundos por timeframe para paginação.
_TF_MS = {
    "1m": 60_000, "3m": 180_000, "5m": 300_000, "15m": 900_000,
    "30m": 1_800_000, "1h": 3_600_000, "2h": 7_200_000, "4h": 14_400_000,
    "6h": 21_600_000, "12h": 43_200_000, "1d": 86_400_000,
}


def _cache_path(symbol: str, timeframe: str) -> Path:
    safe = symbol.replace("/", "_").replace(":", "-")
    return CACHE_DIR / f"{safe}_{timeframe}.csv"


def fetch_history(
    symbol: str,
    timeframe: str,
    candles: int = 1500,
    use_cache: bool = True,
) -> pd.DataFrame:
    """Retorna DataFrame [ts, open, high, low, close, volume, dt] em ordem cronológica."""
    path = _cache_path(symbol, timeframe)
    if use_cache and path.exists():
        df = pd.read_csv(path)
        # O cache é chaveado só por símbolo+timeframe. Sem esta checagem, o
        # fluxo padrão do guia (backtest 1500 → walk-forward 3000) fazia o
        # walk-forward rodar SILENCIOSAMENTE com metade dos dados (6 folds em
        # vez de 16) — o usuário acreditava ter validado 3000 candles.
        if len(df) >= candles:
            log.info("Lendo cache %s (%d candles; usando os últimos %d)", path.name, len(df), candles)
            # Recorta para o pedido — senão um cache de 3000 faria um backtest
            # de "--candles 1500" rodar silenciosamente sobre 3000.
            df = df.iloc[-candles:].reset_index(drop=True)
            df["dt"] = pd.to_datetime(df["ts"], unit="ms", utc=True)
            return df
        log.warning("Cache %s tem só %d candles (< %d pedidos) — baixando de novo.",
                    path.name, len(df), candles)

    exchange = ccxt.bybit({"enableRateLimit": True, "options": {"defaultType": "swap"}})
    tf_ms = _TF_MS.get(timeframe)
    if tf_ms is None:
        raise ValueError(f"Timeframe não suportado no loader: {timeframe}")

    # +1 porque a última linha (candle em formação) é descartada adiante — o
    # alvo vale para o `since` E para o laço, senão a paginação para em
    # `candles` e o descarte entrega candles-1 (aí a checagem de cache acima
    # mandaria re-baixar para sempre).
    alvo = candles + 1
    since = exchange.milliseconds() - alvo * tf_ms
    all_rows: list[list[float]] = []
    log.info("Baixando ~%d candles de %s %s (público)", candles, symbol, timeframe)

    while len(all_rows) < alvo:
        batch = exchange.fetch_ohlcv(symbol, timeframe=timeframe, since=since, limit=1000)
        if not batch:
            break
        all_rows.extend(batch)
        since = batch[-1][0] + tf_ms
        time.sleep(exchange.rateLimit / 1000)
        if len(batch) < 1000:
            break

    df = pd.DataFrame(all_rows, columns=["ts", "open", "high", "low", "close", "volume"])
    df = df.drop_duplicates(subset="ts").sort_values("ts").reset_index(drop=True)
    # A Bybit devolve o candle EM FORMAÇÃO como última linha (high/low/close
    # parciais). O live descarta (market_data.py, df.iloc[:-1]); aqui, além de
    # divergir do contrato "decide só em candle fechado", o to_csv abaixo
    # CONGELARIA o candle parcial no cache para sempre. Descarta antes de salvar.
    if len(df) > 1:
        df = df.iloc[:-1].reset_index(drop=True)
    df["dt"] = pd.to_datetime(df["ts"], unit="ms", utc=True)

    df.to_csv(path, index=False)
    log.info("Salvo cache %s (%d candles)", path.name, len(df))
    return df


def load_csv(path: str | Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    required = {"ts", "open", "high", "low", "close", "volume"}
    if not required.issubset(df.columns):
        raise ValueError(f"CSV precisa conter as colunas {required}")
    df["dt"] = pd.to_datetime(df["ts"], unit="ms", utc=True)
    return df.sort_values("ts").reset_index(drop=True)
