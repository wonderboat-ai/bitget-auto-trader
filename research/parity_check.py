"""Paridade: motor de pesquisa vs backtester OFICIAL, mesmos dados e regra.

Roda a estratégia do robô (EMA20/50, RSI<70, stop 1.5×ATR, TP 2R) nos dois
motores sobre o MESMO CSV spot. Não sai idêntico por diferenças estruturais
documentadas (kill switch e reset diário de drawdown só no oficial; long+short
no oficial em perp vs long-only aqui), então o oficial roda com o YAML de spot
(short vetado) — as contagens de trade e o PnL devem ficar na mesma ordem de
grandeza e mesma direção. Divergência grande = bug em um dos dois.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
# ANTES de importar src.*: o RiskManager audita toda decisão — sem este desvio
# a rodada despejaria milhares de eventos SIMULADOS em logs/audit.jsonl (o
# mesmo acidente de 15/07 que o fix #14 corrigiu nos runners oficiais).
os.environ.setdefault("AUDIT_PATH", str(HERE / "audit-research.jsonl"))
# Mesmo motivo, mesmo desvio: o RiskManager real (backtester oficial) lê E
# GRAVA em state/kill_switch_state.json e state/cooldown_state.json — os
# MESMOS arquivos do motor ao vivo (achado em 21/07/2026).
os.environ.setdefault("KILL_SWITCH_STATE_PATH", str(HERE / "kill_switch_state-research.json"))
os.environ.setdefault("COOLDOWN_STATE_PATH", str(HERE / "cooldown_state-research.json"))
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))

import pandas as pd  # noqa: E402

from config.settings import load_risk_config  # noqa: E402
from src.backtest.backtester import Backtester  # noqa: E402
from harness import Spec, load, prepare, run  # noqa: E402


def main() -> None:
    symbol, tf = "BTC/USDT", "4h"
    df = load(symbol, tf)

    # --- motor oficial (com camada de risco, YAML spot => long-only) ---
    cfg = load_risk_config()
    assert cfg["market"]["type"] == "spot", "YAML precisa estar em spot p/ paridade long-only"
    bt = Backtester(cfg, profile="swing")
    official = bt.run(symbol, tf, df.copy())
    o_wins = sum(1 for t in official.trades if (t.pnl_usdt or 0) > 0)
    o_pnl = sum(t.pnl_usdt or 0 for t in official.trades)

    # --- motor de pesquisa em parity_mode (fill do stop no preço exato) ---
    spec = Spec("robot_baseline", "robo_default",
                {"atr_stop_mult": 1.5, "tp_rr": 2.0, "rsi_long_max": 70.0})
    prep = prepare(spec, df)
    mine = run(df, prep, parity_mode=True, keep_trades=True)

    print(f"{'':22} {'oficial':>12} {'pesquisa':>12}")
    print(f"{'trades':22} {len(official.trades):>12} {mine.trades:>12}")
    print(f"{'vencedores':22} {o_wins:>12} {mine.wins:>12}")
    print(f"{'pnl total (USDT)':22} {o_pnl:>12.2f} {mine.pnl_sum:>12.2f}")
    print(f"{'equity final':22} {official.end_equity:>12.2f} {mine.end_equity:>12.2f}")
    print(f"{'kill switch (oficial)':22} {str(official.kill_switch_ts):>12}")
    print()
    print("Primeiros 5 trades de cada (entry_ts):")
    for t in official.trades[:5]:
        print(f"  oficial : {pd.Timestamp(t.entry_ts, unit='ms')} {t.direction} "
              f"pnl={t.pnl_usdt:.2f} ({t.exit_reason})")
    for t in mine.trade_list[:5]:
        print(f"  pesquisa: {pd.Timestamp(t[0], unit='ms')} long pnl={t[2]:.2f} ({t[4]})")


if __name__ == "__main__":
    main()
