"""Teste de HOLDOUT limpo — desempata o conflito metodologico da rodada 3.

O problema: duas medidas discordam.
  (a) rodada CONTINUA de parametro fixo sobre 3 anos disse ema_cross +9,86% e
      donchian 100/20 +10,59%, 8/8 simbolos — MAS os parametros foram escolhidos
      por mim DEPOIS de ver o resultado do periodo inteiro (vies de selecao meu).
  (b) walk-forward com selecao por fold disse, em 4h: donchian +4,49% (6/8),
      ema_cross -2,08% (3/8), robot_live -10,66% (1/8) — sem vies de selecao
      meu, mas com selecao ruidosa a cada 18 dias e janelas OOS curtas demais
      para uma estrategia de baixa frequencia (donchian faz ~3 trades por fold).

Nenhuma das duas e limpa. Este script faz o teste que decide:
  - ESCOLHE o parametro usando SOMENTE o primeiro trecho da serie;
  - AVALIA no trecho final, que a regra de escolha nunca viu;
  - a escolha e MECANICA (melhor mediana de R/trade entre simbolos), sem eu
    olhar nada no meio.

Continua havendo uma contaminacao residual honesta: eu ja vi numeros agregados
do periodo inteiro para ~15 configuracoes antes de escrever isto. O holdout
reduz o problema, nao o elimina. A unica prova limpa de verdade e forward real.

Uso:  python research/holdout_3.py
"""
from __future__ import annotations

import itertools
import statistics as st
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from harness import Spec
from harness_perp import (load_ohlcv, load_funding, funding_per_candle,
                          prepare_both, run)

SYMS = ["BTC", "ETH", "SOL", "XRP", "BNB", "DOGE", "ADA", "LINK"]
TF = "4h"
SPLIT = 0.55          # 55% escolhe, 45% avalia (nunca visto pela regra)


def grid():
    g = []
    for n, m, s in itertools.product([20, 55, 100, 150], [10, 20, 30], [1.5, 2.0, 3.0]):
        g.append(Spec("donchian", f"don{n}/{m}/s{s}",
                      dict(n=n, exit_m=m, atr_stop=s, tp_rr=None, trail=None)))
    for f, s2, s in itertools.product([9, 20, 30], [50, 80, 120], [1.5, 2.0, 3.0]):
        g.append(Spec("ema_cross", f"ema{f}/{s2}/s{s}",
                      dict(fast=f, slow=s2, on_cross_only=False, rsi_max=100.0,
                           atr_stop=s, tp_rr=None, trail=None)))
    for n, th, s in itertools.product([12, 24, 48], [2.0, 5.0], [2.0, 3.0]):
        g.append(Spec("momentum", f"mom{n}/{th}/s{s}",
                      dict(n=n, th=th, atr_stop=s, tp_rr=None, trail=None)))
    for k, ex, s in itertools.product([2.0, 2.5, 3.0], ["mid", "band"], [2.0, 3.0]):
        g.append(Spec("bollinger_mr", f"bb{k}/{ex}/s{s}",
                      dict(k=k, exit=ex, atr_stop=s, tp_rr=None)))
    for b, e, s in itertools.product([20, 30], [50, 60], [2.0, 3.0]):
        g.append(Spec("rsi_mr", f"rsi{b}/{e}/s{s}",
                      dict(rsi_buy=b, rsi_exit=e, atr_stop=s, tp_rr=None)))
    # a estrategia de producao e suas variantes de saida, para comparacao justa
    for s, tp, tr in itertools.product([1.5, 2.0, 3.0], [2.0, None], [None, 1.5]):
        g.append(Spec("robot_live", f"live/s{s}/tp{tp}/tr{tr}",
                      dict(atr_stop_mult=s, tp_rr=tp, rsi_long_max=70.0,
                           rsi_short_min=30.0, trail=tr, trail_min_step=0.001)))
    return g


def main() -> None:
    dados = {}
    for s in SYMS:
        df = load_ohlcv(s, TF)
        dados[s] = (df, funding_per_candle(df, load_funding(s)), int(len(df) * SPLIT))

    import datetime as dt
    d0 = dados["BTC"][0]
    corte = dt.datetime.fromtimestamp(d0.ts.iloc[dados["BTC"][2]] / 1000, dt.timezone.utc)
    fim = dt.datetime.fromtimestamp(d0.ts.iloc[-1] / 1000, dt.timezone.utc)
    print(f"escolha: inicio -> {corte:%Y-%m-%d}   |   holdout: {corte:%Y-%m-%d} -> {fim:%Y-%m-%d}")

    specs = grid()
    print(f"{len(specs)} configuracoes\n")

    resultados = []
    for sp in specs:
        esc, hold = [], []
        tr_e = tr_h = 0
        for s in SYMS:
            df, farr, split = dados[s]
            prep = prepare_both(sp, df)
            a = run(sp, df, prep, farr, start=prep.warmup, end=split)
            b = run(sp, df, prep, farr, start=split)
            esc.append(a.r_mean if a.trades else 0.0)
            hold.append(b.total_return_pct)
            tr_e += a.trades
            tr_h += b.trades
        resultados.append(dict(spec=sp, fam=sp.family, nome=sp.name,
                               esc_r=st.median(esc), esc_tr=tr_e,
                               hold_med=st.median(hold),
                               hold_pos=sum(1 for x in hold if x > 0),
                               hold_tr=tr_h, hold=hold))

    print("=" * 104)
    print("ESCOLHA MECANICA POR FAMILIA (melhor mediana de R/trade no trecho de ESCOLHA)")
    print("depois avaliada no HOLDOUT que a regra nunca viu")
    print("=" * 104)
    print(f'{"familia":14s} {"config escolhida":22s} {"R/tr escolha":>12s} '
          f'{"HOLDOUT med":>12s} {"pos":>6s} {"trades":>7s}')
    for fam in ["donchian", "ema_cross", "momentum", "bollinger_mr", "rsi_mr", "robot_live"]:
        cand = [r for r in resultados if r["fam"] == fam and r["esc_tr"] >= 40]
        if not cand:
            continue
        best = max(cand, key=lambda r: r["esc_r"])
        print(f'{fam:14s} {best["nome"]:22s} {best["esc_r"]:+12.4f} '
              f'{best["hold_med"]:+11.2f}% {best["hold_pos"]}/8   {best["hold_tr"]:7d}')

    print()
    print("=" * 104)
    print("CONTROLE: a configuracao EXATA que roda em producao hoje")
    print("=" * 104)
    prod = [r for r in resultados
            if r["fam"] == "robot_live" and r["nome"] == "live/s1.5/tp2.0/tr1.5"]
    if prod:
        p = prod[0]
        print(f'  producao (stop 1,5 ATR, TP 2R, trailing 1,5): '
              f'R/tr escolha={p["esc_r"]:+.4f}  HOLDOUT mediana={p["hold_med"]:+.2f}%  '
              f'pos={p["hold_pos"]}/8  trades={p["hold_tr"]}')

    print()
    print("=" * 104)
    print("TOP 10 NO HOLDOUT (para ver se a escolha mecanica pegou perto do topo)")
    print("=" * 104)
    for r in sorted(resultados, key=lambda r: r["hold_med"], reverse=True)[:10]:
        print(f'  {r["fam"]:14s} {r["nome"]:22s} holdout={r["hold_med"]:+7.2f}% '
              f'pos={r["hold_pos"]}/8  (R/tr na escolha={r["esc_r"]:+.4f})')

    print()
    print("Correlacao entre desempenho na ESCOLHA e no HOLDOUT")
    print("(se for ~0 ou negativa, escolher parametro por historico nao funciona):")
    import numpy as np
    x = np.array([r["esc_r"] for r in resultados])
    y = np.array([r["hold_med"] for r in resultados])
    print(f"  Pearson r = {np.corrcoef(x, y)[0,1]:+.3f}  (n={len(x)} configuracoes)")


if __name__ == "__main__":
    main()
