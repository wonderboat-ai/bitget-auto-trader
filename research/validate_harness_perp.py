"""Validacao do harness_perp contra a REALIDADE — nao contra outro backtest.

O projeto nunca fez esta checagem: toda paridade anterior comparou backtester x
harness (duas simulacoes concordando podem estar erradas juntas). Aqui a regua
e outra: rodar a configuracao EXATA de producao sobre a janela EXATA em que o
motor operou com dinheiro real (28/07 -> 18/08/2026) e comparar as estatisticas
agregadas com os 43 trade_closed reais da trilha.

Se o harness estiver certo, os numeros tem que cair na mesma vizinhanca (nao
identicos — o live amostra preco a cada ~62s, o replay a cada candle; o live
tem cooldown/kill switch/quantizacao de tamanho, o replay nao). Divergencia
GRANDE = o harness esta medindo outra coisa e a pesquisa inteira mentiria.

Uso:  python research/validate_harness_perp.py
"""
from __future__ import annotations

import datetime as dt
import json
import statistics as st
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from harness import Spec
from harness_perp import (load_ohlcv, load_funding, funding_per_candle,
                          prepare_both, run)

# Janela real de operacao em perp mainnet (primeiro order_executed de perp ->
# agora). Timestamps em ms UTC.
WIN_START = int(dt.datetime(2026, 7, 28, 0, 0, tzinfo=dt.timezone.utc).timestamp() * 1000)
WIN_END = int(dt.datetime(2026, 8, 18, 15, 0, tzinfo=dt.timezone.utc).timestamp() * 1000)

# Config EXATA de producao hoje (config/risk_config.yaml + StrategyParams):
#   atr_stop_mult 1.5 | tp_rr 2.0 | rsi 70/30 | trailing on
#   trail_distance no live = |fill - stop| = 1.5 * ATR  -> trail = 1.5
#   TRAIL_MIN_STEP_PCT = 0.001
LIVE = dict(atr_stop_mult=1.5, tp_rr=2.0, rsi_long_max=70.0, rsi_short_min=30.0,
            trail=1.5, trail_min_step=0.001)

PROFILES = {"daytrade": "15m", "swing": "4h"}
SYMBOLS = ["BTC", "ETH"]


def real_trades() -> list[dict]:
    paths = [Path(r"C:\Users\lucas\Wonder BOAT Dropbox\Lucas Souza\PC\Documents\Projects\Projeto Auto-trader\logs\audit.jsonl"),
             Path(r"C:\BybitAutoTrader\logs\audit.jsonl")]
    ev = []
    for p in paths:
        if not p.exists():
            continue
        with open(p, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    ev.append(json.loads(line))
                except Exception:
                    pass
    ev.sort(key=lambda d: d.get("ts", ""))
    last_entry: dict = {}
    out = []
    for e in ev:
        sym = e.get("symbol")
        if e.get("event") == "order_executed":
            last_entry[sym] = e
        elif e.get("event") == "trade_closed":
            en = last_entry.get(sym)
            pnl = e.get("pnl_usdt")
            size = e.get("size")
            if not (en and pnl is not None and size):
                continue
            fe, sp = en.get("entry_price"), en.get("stop_price")
            if not (fe and sp):
                continue
            risk = abs(fe - sp) * size
            if risk <= 0:
                continue
            out.append(dict(profile=en.get("profile"), side=e.get("side"),
                            symbol=sym, R=pnl / risk, pnl=pnl,
                            reason=e.get("reason")))
    return out


def stats(Rs: list[float]) -> dict:
    if not Rs:
        return {}
    w = [r for r in Rs if r > 0]
    lo = [r for r in Rs if r <= 0]
    return dict(n=len(Rs), r_sum=sum(Rs), r_mean=sum(Rs) / len(Rs),
                wr=100 * len(w) / len(Rs),
                gain=st.mean(w) if w else 0.0,
                loss=st.mean(lo) if lo else 0.0,
                payoff=abs(st.mean(w) / st.mean(lo)) if w and lo else float("nan"))


def show(label: str, s: dict) -> None:
    if not s:
        print(f"{label:34s} (sem trades)")
        return
    print(f"{label:34s} n={s['n']:4d}  R/trade={s['r_mean']:+.3f}  "
          f"Rsum={s['r_sum']:+7.2f}  WR={s['wr']:4.1f}%  "
          f"ganho={s['gain']:+.3f}R  perda={s['loss']:+.3f}R  payoff={s['payoff']:.2f}")


def main() -> None:
    print("=" * 100)
    print("VALIDACAO harness_perp x REALIDADE — config de producao, janela real de perp")
    print("=" * 100)

    real = real_trades()
    print(f"\n--- REAL (trilha de auditoria, {len(real)} trades com risco apurado) ---")
    show("REAL total", stats([t["R"] for t in real]))
    for prof in ("daytrade", "swing"):
        show(f"REAL {prof}", stats([t["R"] for t in real if t["profile"] == prof]))
    for side in ("long", "short"):
        show(f"REAL {side}", stats([t["R"] for t in real if t["side"] == side]))

    print(f"\n--- SIMULADO (harness_perp, mesma janela, mesma config) ---")
    all_sim: list[float] = []
    per_prof: dict[str, list[float]] = {p: [] for p in PROFILES}
    per_side: dict[str, list[float]] = {"long": [], "short": []}
    for prof, tf in PROFILES.items():
        for base in SYMBOLS:
            df = load_ohlcv(base, tf)
            fund = load_funding(base)
            farr = funding_per_candle(df, fund)
            spec = Spec("robot_live", "live", dict(LIVE))
            prep = prepare_both(spec, df)
            ts = df["ts"].to_numpy()
            i0 = int((ts >= WIN_START).argmax())
            i1 = int((ts >= WIN_END).argmax() or len(ts))
            res = run(spec, df, prep, farr, start=i0, end=i1)
            Rs = [t[5] for t in res.trade_list]
            all_sim += Rs
            per_prof[prof] += Rs
            per_side["long"] += [t[5] for t in res.trade_list if t[1] == "long"]
            per_side["short"] += [t[5] for t in res.trade_list if t[1] == "short"]
            reasons: dict[str, int] = {}
            for t in res.trade_list:
                reasons[t[6]] = reasons.get(t[6], 0) + 1
            print(f"  {base} {tf} ({prof}): {res.trades} trades  "
                  f"R/trade={res.r_mean:+.3f}  ret={res.total_return_pct:+.2f}%  "
                  f"fee={res.fees_paid:.2f}  funding={res.funding_paid:+.3f}  {reasons}")

    show("SIM total", stats(all_sim))
    for prof in PROFILES:
        show(f"SIM {prof}", stats(per_prof[prof]))
    for side in ("long", "short"):
        show(f"SIM {side}", stats(per_side[side]))

    print("\n" + "=" * 100)
    print("LEITURA: R/trade, WR e payoff do SIM devem cair na vizinhanca do REAL.")
    print("O REAL tem cooldown (pausa apos cada stop), kill switch e quantizacao")
    print("de tamanho que o SIM nao tem -> o SIM opera MAIS trades. A comparacao")
    print("que importa e a de MEDIA por trade (R/trade, WR, payoff), nao a contagem.")
    print("=" * 100)


if __name__ == "__main__":
    main()
