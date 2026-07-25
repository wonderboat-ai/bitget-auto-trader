"""Baixa 6 meses de OHLCV de PERPÉTUOS + histórico de funding rate (Bybit
mainnet pública) para a pesquisa de estratégia SHORT.

Pesquisa HIPOTÉTICA: derivativos estão bloqueados para residente BR na Bybit
(retCode 10024, Etapa B de 15/07) — isto NÃO é preparação de operação real na
Bybit; é régua estatística para decidir se short vale a pena em venue legítima.

Short em perp tem dois custos que o spot não tem: funding a cada 8h (short
RECEBE quando o rate é positivo, PAGA quando negativo) e fee taker própria
(0,055%/lado). Sem o funding real, um backtest short em bear market mente.

Uso:
    python research/download_data_perp.py
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import ccxt
import pandas as pd

HERE = Path(__file__).resolve().parent
DATA_DIR = HERE / "data_perp"
DATA_DIR.mkdir(exist_ok=True)

SYMBOLS = ["BTC/USDT:USDT", "ETH/USDT:USDT", "SOL/USDT:USDT",
           "XRP/USDT:USDT", "MNT/USDT:USDT", "BNB/USDT:USDT"]
TIMEFRAMES = {"15m": 186 * 96, "1h": 186 * 24, "4h": 186 * 6}
TF_MS = {"15m": 900_000, "1h": 3_600_000, "4h": 14_400_000}


def safe_name(symbol: str) -> str:
    return symbol.split("/")[0]


def fetch_ohlcv(exchange: ccxt.bybit, symbol: str, timeframe: str, candles: int) -> pd.DataFrame:
    alvo = candles + 1  # candle em formação é descartado no fim
    tf_ms = TF_MS[timeframe]
    since = exchange.milliseconds() - alvo * tf_ms
    rows: list[list[float]] = []
    while len(rows) < alvo:
        batch = exchange.fetch_ohlcv(symbol, timeframe=timeframe, since=since, limit=1000)
        if not batch:
            break
        rows.extend(batch)
        new_since = batch[-1][0] + tf_ms
        # NÃO parar em len(batch) < 1000 — a Bybit devolve 999 por página
        # (off-by-one dela); parar aí truncava o download na 1ª página.
        if new_since <= since or new_since > exchange.milliseconds():
            break
        since = new_since
        time.sleep(exchange.rateLimit / 1000)
    df = pd.DataFrame(rows, columns=["ts", "open", "high", "low", "close", "volume"])
    df = df.drop_duplicates(subset="ts").sort_values("ts").reset_index(drop=True)
    if len(df) > 1:
        df = df.iloc[:-1].reset_index(drop=True)
    return df


def fetch_funding(exchange: ccxt.bybit, symbol: str, days: int = 187) -> pd.DataFrame:
    """Funding a cada 8h → ~3/dia. Pagina para frente a partir de 6 meses atrás."""
    since = exchange.milliseconds() - days * 86_400_000
    rows: list[dict] = []
    while True:
        batch = exchange.fetch_funding_rate_history(symbol, since=since, limit=200)
        if not batch:
            break
        rows.extend({"ts": b["timestamp"], "rate": b["fundingRate"]} for b in batch)
        new_since = batch[-1]["timestamp"] + 1
        if new_since <= since:
            break
        since = new_since
        time.sleep(exchange.rateLimit / 1000)
        if len(batch) < 200:
            break
    df = pd.DataFrame(rows).drop_duplicates(subset="ts").sort_values("ts").reset_index(drop=True)
    return df


def main() -> None:
    exchange = ccxt.bybit({"enableRateLimit": True, "options": {"defaultType": "swap"}})
    fail = []
    for symbol in SYMBOLS:
        base = safe_name(symbol)
        for tf, candles in TIMEFRAMES.items():
            path = DATA_DIR / f"{base}_USDT_{tf}.csv"
            if path.exists() and len(pd.read_csv(path)) >= candles * 0.98:
                print(f"cache ok  {path.name}")
                continue
            try:
                df = fetch_ohlcv(exchange, symbol, tf, candles)
            except Exception as exc:
                print(f"FALHA     {symbol} {tf}: {exc}", file=sys.stderr)
                fail.append(f"{symbol} {tf}")
                continue
            df.to_csv(path, index=False)
            print(f"baixado   {path.name} ({len(df)} candles, {100.0*len(df)/candles:.0f}% do alvo)")
        fpath = DATA_DIR / f"{base}_USDT_funding.csv"
        if fpath.exists() and len(pd.read_csv(fpath)) >= 500:
            print(f"cache ok  {fpath.name}")
            continue
        try:
            fdf = fetch_funding(exchange, symbol)
        except Exception as exc:
            print(f"FALHA     funding {symbol}: {exc}", file=sys.stderr)
            fail.append(f"funding {symbol}")
            continue
        fdf.to_csv(fpath, index=False)
        print(f"baixado   {fpath.name} ({len(fdf)} eventos de funding)")
    print(f"\nConcluído. Falhas: {fail or '—'}")


if __name__ == "__main__":
    main()
