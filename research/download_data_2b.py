"""Baixa 2+ anos de OHLCV SPOT (mainnet pública da Bybit) para a pesquisa 2b.

Separado de research/download_data.py (aquele baixa só ~6 meses — jan-jul/2026,
100% bear, já queimado para seleção de estratégia, ver RELATORIO-2026-07-16.md).
Pasta de saída própria (research/data_2b/) para nunca confundir com o dataset
antigo nem sobrescrevê-lo.

Uso:
    python research/download_data_2b.py
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import ccxt
import pandas as pd

HERE = Path(__file__).resolve().parent
DATA_DIR = HERE / "data_2b"
DATA_DIR.mkdir(exist_ok=True)

SYMBOLS = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "XRP/USDT", "BNB/USDT"]
DAYS_BACK = 820  # ~2,25 anos — folga sobre o pedido de "2+ anos"
TIMEFRAMES = {"1h": DAYS_BACK * 24, "4h": DAYS_BACK * 6}
TF_MS = {"1h": 3_600_000, "4h": 14_400_000}


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
        # (off-by-one dela) — parar aí truncava o download na 1ª página (bug
        # visto em 16/07 no dataset antigo). Parar só em página vazia, sem
        # progresso, ou quando passou de agora.
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
                if len(existing) >= candles * 0.90:
                    print(f"cache ok  {path.name} ({len(existing)} candles)")
                    ok.append(path.name)
                    continue
            try:
                df = fetch(exchange, symbol, tf, candles)
            except Exception as exc:  # símbolo pode não ter histórico tão longo
                print(f"FALHA     {symbol} {tf}: {exc}", file=sys.stderr)
                fail.append(f"{symbol} {tf}")
                continue
            if len(df) < 2:
                print(f"FALHA     {symbol} {tf}: 0 candles retornados", file=sys.stderr)
                fail.append(f"{symbol} {tf}")
                continue
            df.to_csv(path, index=False)
            pct = 100.0 * len(df) / candles
            first = pd.to_datetime(df["ts"].iloc[0], unit="ms")
            last = pd.to_datetime(df["ts"].iloc[-1], unit="ms")
            print(f"baixado   {path.name} ({len(df)} candles, {pct:.0f}% do alvo, "
                  f"{first.date()} -> {last.date()})")
            ok.append(path.name)
    print(f"\nConcluído: {len(ok)} arquivos ok, {len(fail)} falhas: {fail or '—'}")


if __name__ == "__main__":
    main()
