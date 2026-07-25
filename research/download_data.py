"""Baixa 6 meses de OHLCV SPOT (mainnet pública da Bybit) para pesquisa de estratégia.

Separado do data_loader do projeto de propósito: o cache do projeto (data/) guarda
PERPÉTUOS (defaultType=swap); aqui a pesquisa é sobre SPOT — misturar os caches
faria um backtest spot rodar silenciosamente sobre preços de perp.

Uso:
    python research/download_data.py
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import ccxt
import pandas as pd

HERE = Path(__file__).resolve().parent
DATA_DIR = HERE / "data"
DATA_DIR.mkdir(exist_ok=True)

SYMBOLS = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "XRP/USDT", "MNT/USDT", "BNB/USDT"]
# ~186 dias ≈ 6 meses. Contagem por timeframe.
TIMEFRAMES = {"15m": 186 * 96, "1h": 186 * 24, "4h": 186 * 6}
TF_MS = {"15m": 900_000, "1h": 3_600_000, "4h": 14_400_000}


def fetch(exchange: ccxt.bybit, symbol: str, timeframe: str, candles: int) -> pd.DataFrame:
    # +1 porque o candle em formação (última linha) é descartado — mesma regra
    # do data_loader do projeto: decidir só em candle FECHADO.
    alvo = candles + 1
    tf_ms = TF_MS[timeframe]
    since = exchange.milliseconds() - alvo * tf_ms
    rows: list[list[float]] = []
    while len(rows) < alvo:
        batch = exchange.fetch_ohlcv(symbol, timeframe=timeframe, since=since, limit=1000)
        if not batch:
            break
        rows.extend(batch)
        new_since = batch[-1][0] + tf_ms
        # NÃO parar em len(batch) < 1000: a Bybit spot devolve 999 por página
        # (off-by-one dela) — parar aí truncava o download na 1ª página (visto
        # em 16/07: todos os arquivos com 998 candles em vez de ~17.800).
        # Condições de parada: página vazia, sem progresso, ou passou de agora.
        if new_since <= since or new_since > exchange.milliseconds():
            break
        since = new_since
        time.sleep(exchange.rateLimit / 1000)
    df = pd.DataFrame(rows, columns=["ts", "open", "high", "low", "close", "volume"])
    df = df.drop_duplicates(subset="ts").sort_values("ts").reset_index(drop=True)
    if len(df) > 1:
        df = df.iloc[:-1].reset_index(drop=True)  # descarta candle em formação
    return df


def main() -> None:
    exchange = ccxt.bybit({"enableRateLimit": True, "options": {"defaultType": "spot"}})
    ok, fail = [], []
    for symbol in SYMBOLS:
        for tf, candles in TIMEFRAMES.items():
            safe = symbol.replace("/", "_")
            path = DATA_DIR / f"{safe}_{tf}.csv"
            if path.exists():
                existing = pd.read_csv(path)
                if len(existing) >= candles * 0.98:
                    print(f"cache ok  {path.name} ({len(existing)} candles)")
                    ok.append(path.name)
                    continue
            try:
                df = fetch(exchange, symbol, tf, candles)
            except Exception as exc:  # símbolo pode não existir no spot
                print(f"FALHA     {symbol} {tf}: {exc}", file=sys.stderr)
                fail.append(f"{symbol} {tf}")
                continue
            df.to_csv(path, index=False)
            pct = 100.0 * len(df) / candles
            print(f"baixado   {path.name} ({len(df)} candles, {pct:.0f}% do alvo)")
            ok.append(path.name)
    print(f"\nConcluído: {len(ok)} arquivos ok, {len(fail)} falhas: {fail or '—'}")


if __name__ == "__main__":
    main()
