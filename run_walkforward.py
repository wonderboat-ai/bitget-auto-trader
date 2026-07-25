"""Roda a validação walk-forward (out-of-sample) da estratégia.

Uso:
    python run_walkforward.py --symbol "BTC/USDT:USDT" --timeframe 15m --candles 3000
    python run_walkforward.py --profile swing --timeframe 4h --candles 3000 --is 300 --oos 100

Baixa dados do endpoint PÚBLICO da Bybit (cache em data/). O relatório mostra o
desempenho por fold e — o que importa — o AGREGADO out-of-sample, com a medida de
degradação IS->OOS (indicador de overfitting).
"""
from __future__ import annotations

import argparse
import os
import sys

# ANTES de importar src.*: a trilha logs/audit.jsonl é do LIVE — sem este
# desvio, cada rodada de walk-forward (48 combos × N folds) despeja dezenas de
# milhares de eventos SIMULADOS nela (visto em 15/07/2026: 500 → 40.405 linhas).
os.environ.setdefault("AUDIT_PATH", "logs/audit-backtest.jsonl")
# Mesmo motivo, mesmo desvio: o backtester instancia um RiskManager de
# verdade, que por padrão lê E GRAVA em state/kill_switch_state.json e
# state/cooldown_state.json — os MESMOS arquivos que o motor ao vivo usa
# (achado em 21/07/2026). Sem isto, um trip/cooldown simulado num fold do
# walk-forward podia sobrescrever o estado real do motor ao vivo silenciosamente.
os.environ.setdefault("KILL_SWITCH_STATE_PATH", "state/kill_switch_state-backtest.json")
os.environ.setdefault("COOLDOWN_STATE_PATH", "state/cooldown_state-backtest.json")
# Console padrão do Windows é cp1252 e quebra nos caracteres do relatório
# (UnicodeEncodeError depois de TODO o cálculo feito). UTF-8 sempre.
sys.stdout.reconfigure(encoding="utf-8")

from config.settings import load_risk_config
from src.backtest.data_loader import fetch_history, load_csv
from src.backtest.walkforward import WalkForward
from src.backtest.wf_report import format_wf_report


def main() -> None:
    p = argparse.ArgumentParser(description="Walk-forward — Bybit Auto Trader Fase 2")
    p.add_argument("--symbol", default="BTC/USDT:USDT")
    p.add_argument("--timeframe", default="15m")
    p.add_argument("--candles", type=int, default=3000)
    p.add_argument("--profile", default="daytrade", choices=["daytrade", "swing"])
    p.add_argument("--is", dest="is_len", type=int, default=400, help="tamanho da janela in-sample")
    p.add_argument("--oos", dest="oos_len", type=int, default=150, help="tamanho da janela out-of-sample")
    p.add_argument("--csv", default=None)
    p.add_argument("--no-cache", action="store_true")
    args = p.parse_args()

    cfg = load_risk_config()
    if args.csv:
        df = load_csv(args.csv)
    else:
        df = fetch_history(args.symbol, args.timeframe, candles=args.candles,
                           use_cache=not args.no_cache)

    wf = WalkForward(cfg, args.symbol, args.timeframe, profile=args.profile,
                     is_len=args.is_len, oos_len=args.oos_len)
    report = wf.run(df)
    print(format_wf_report(report, args.symbol, args.timeframe))


if __name__ == "__main__":
    main()
