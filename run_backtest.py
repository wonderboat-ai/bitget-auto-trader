"""Roda um backtest da estratégia da Fase 1 sobre dados históricos da Bybit.

Uso:
    python run_backtest.py --symbol "BTC/USDT:USDT" --timeframe 15m --candles 1500
    python run_backtest.py --csv data/meus_dados.csv --timeframe 15m
    python run_backtest.py --profile swing --timeframe 4h

Os dados são baixados do endpoint PÚBLICO da Bybit (não precisa de chave de API)
e cacheados em data/. Use --no-cache para forçar novo download.
"""
from __future__ import annotations

import argparse
import os
import sys

# ANTES de importar src.*: a trilha logs/audit.jsonl é do LIVE — sem este
# desvio, cada rodada de backtest despeja milhares de signal_approved/vetoed
# SIMULADOS nela (visto em 15/07/2026: 500 → 40.405 linhas numa rodada).
os.environ.setdefault("AUDIT_PATH", "logs/audit-backtest.jsonl")
# Mesmo motivo, mesmo desvio: o backtester instancia um RiskManager de
# verdade, que por padrão lê E GRAVA em state/kill_switch_state.json e
# state/cooldown_state.json — os MESMOS arquivos que o motor ao vivo usa
# (achado em 21/07/2026). Sem isto, um trip/cooldown simulado no backtest
# podia sobrescrever o estado real do motor ao vivo silenciosamente.
os.environ.setdefault("KILL_SWITCH_STATE_PATH", "state/kill_switch_state-backtest.json")
os.environ.setdefault("COOLDOWN_STATE_PATH", "state/cooldown_state-backtest.json")
# Console padrão do Windows é cp1252 e quebra nos caracteres do relatório
# (UnicodeEncodeError depois de TODO o cálculo feito). UTF-8 sempre.
sys.stdout.reconfigure(encoding="utf-8")

from config.settings import load_risk_config
from src.backtest.backtester import Backtester
from src.backtest.data_loader import fetch_history, load_csv
from src.backtest.metrics import compute_metrics, format_report


def main() -> None:
    p = argparse.ArgumentParser(description="Backtest — Bybit Auto Trader Fase 2")
    p.add_argument("--symbol", default="BTC/USDT:USDT")
    p.add_argument("--timeframe", default="15m")
    p.add_argument("--candles", type=int, default=1500)
    p.add_argument("--profile", default="daytrade", choices=["daytrade", "swing"])
    p.add_argument("--csv", default=None, help="usar CSV local em vez de baixar")
    p.add_argument("--no-cache", action="store_true")
    args = p.parse_args()

    cfg = load_risk_config()

    if args.csv:
        df = load_csv(args.csv)
    else:
        df = fetch_history(args.symbol, args.timeframe, candles=args.candles,
                           use_cache=not args.no_cache)

    bt = Backtester(cfg, profile=args.profile)
    result = bt.run(args.symbol, args.timeframe, df)
    metrics = compute_metrics(result)
    print(format_report(metrics, args.symbol, args.timeframe,
                        result.start_equity, result.end_equity))


if __name__ == "__main__":
    main()
