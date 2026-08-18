"""Baixa dataset NOVO (rodada 3, 18/08/2026) de PERPÉTUOS USDT da Bybit mainnet
pública: OHLCV 15m/1h/4h + histórico completo de funding rate.

Por que um dataset novo: os dois anteriores estão QUEIMADOS para seleção
(research/data/ inspecionado por ~9 agentes em 16/07; research/data_2b/ usado
na rodada de 21/07) e ambos terminam em 21/07/2026 — não cobrem a janela em
que o motor operou ao vivo em perp (28/07 → 18/08). Além disso, TODA a pesquisa
anterior mediu SPOT long-only (fee 0,1%/lado) ou short-only puro; a configuração
REAL de produção hoje é PERP long E short, fee taker 0,055%/lado, alavancagem
até 2x. Nenhuma rodada anterior mediu isso.

Uso:  python research/download_data_3.py
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import ccxt
import pandas as pd

HERE = Path(__file__).resolve().parent
DATA_DIR = HERE / "data_3"
DATA_DIR.mkdir(exist_ok=True)

# 8 símbolos: os 2 que o motor opera de verdade (BTC/ETH) + 6 para evidência
# transversal. Um resultado que só aparece em 1-2 símbolos é ruído; a pesquisa
# anterior errou ao usar universo pequeno demais (achado dos juízes de 22/07).
SYMBOLS = ["BTC/USDT:USDT", "ETH/USDT:USDT", "SOL/USDT:USDT", "XRP/USDT:USDT",
           "BNB/USDT:USDT", "DOGE/USDT:USDT", "ADA/USDT:USDT", "LINK/USDT:USDT"]

# 15m em 2 anos, 1h/4h em 3 anos: 15m só interessa para confirmar/refutar de
# novo a inviabilidade por fricção (já 0/108 em 16/07) — não precisa de 3 anos.
TIMEFRAMES = {"15m": 730 * 96, "1h": 1095 * 24, "4h": 1095 * 6}
TF_MS = {"15m": 900_000, "1h": 3_600_000, "4h": 14_400_000}
FUNDING_DAYS = 1100


def safe_name(symbol: str) -> str:
    return symbol.split("/")[0]


def fetch_ohlcv(exchange, symbol: str, timeframe: str, candles: int) -> pd.DataFrame:
    alvo = candles + 1  # o candle em formação é descartado no fim
    tf_ms = TF_MS[timeframe]
    since = exchange.milliseconds() - alvo * tf_ms
    rows: list[list[float]] = []
    while len(rows) < alvo:
        batch = exchange.fetch_ohlcv(symbol, timeframe=timeframe, since=since, limit=1000)
        if not batch:
            break
        rows.extend(batch)
        new_since = batch[-1][0] + tf_ms
        # A Bybit devolve 999 por página (off-by-one dela) — parar em
        # len(batch)<1000 truncaria o download na 1ª página.
        if new_since <= since or new_since > exchange.milliseconds():
            break
        since = new_since
        time.sleep(exchange.rateLimit / 1000)
    df = pd.DataFrame(rows, columns=["ts", "open", "high", "low", "close", "volume"])
    df = df.drop_duplicates(subset="ts").sort_values("ts").reset_index(drop=True)
    if len(df) > 1:
        df = df.iloc[:-1].reset_index(drop=True)   # descarta candle em formação
    return df


def fetch_funding(exchange, symbol: str, days: int = FUNDING_DAYS) -> pd.DataFrame:
    since = exchange.milliseconds() - days * 86_400_000
    rows: list[dict] = []
    while True:
        batch = exchange.fetch_funding_rate_history(symbol, since=since, limit=200)
        if not batch:
            break
        rows.extend({"ts": b["timestamp"], "rate": b["fundingRate"]} for b in batch)
        new_since = batch[-1]["timestamp"] + 1
        if new_since <= since or new_since > exchange.milliseconds():
            break
        since = new_since
        time.sleep(exchange.rateLimit / 1000)
    df = pd.DataFrame(rows).drop_duplicates(subset="ts").sort_values("ts").reset_index(drop=True)
    return df


def main() -> None:
    exchange = ccxt.bybit({"enableRateLimit": True, "options": {"defaultType": "swap"}})
    fail = []
    for symbol in SYMBOLS:
        base = safe_name(symbol)
        for tf, candles in TIMEFRAMES.items():
            path = DATA_DIR / f"{base}_USDT_{tf}.csv"
            if path.exists() and len(pd.read_csv(path)) >= candles * 0.95:
                print(f"cache ok  {path.name}", flush=True)
                continue
            try:
                df = fetch_ohlcv(exchange, symbol, tf, candles)
            except Exception as exc:
                print(f"FALHA     {symbol} {tf}: {exc}", file=sys.stderr, flush=True)
                fail.append(f"{symbol} {tf}")
                continue
            df.to_csv(path, index=False)
            print(f"baixado   {path.name} ({len(df)} candles, {100.0*len(df)/candles:.0f}% do alvo)", flush=True)
        fpath = DATA_DIR / f"{base}_USDT_funding.csv"
        if fpath.exists() and len(pd.read_csv(fpath)) >= 2000:
            print(f"cache ok  {fpath.name}", flush=True)
            continue
        try:
            fdf = fetch_funding(exchange, symbol)
        except Exception as exc:
            print(f"FALHA     funding {symbol}: {exc}", file=sys.stderr, flush=True)
            fail.append(f"funding {symbol}")
            continue
        fdf.to_csv(fpath, index=False)
        print(f"baixado   {fpath.name} ({len(fdf)} eventos de funding)", flush=True)
    print(f"\nConcluido. Falhas: {fail or '-'}", flush=True)


if __name__ == "__main__":
    main()
