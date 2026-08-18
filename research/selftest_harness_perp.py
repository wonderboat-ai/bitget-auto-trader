"""Auto-teste do harness_perp com series SINTETICAS — prova a mecanica antes de
qualquer numero de pesquisa ser citado.

Cada check monta um preco onde a resposta certa e conhecida na mao. Sem isto,
um bug silencioso (sinal deslocado, fee dobrada, funding com sinal invertido,
trailing usando o candle atual) faria a pesquisa inteira mentir com aparencia
de rigor — foi exatamente o que aconteceu em 22/07 com o bug de
RunResult.total_return_pct herdado de 16/07.

Uso:  python research/selftest_harness_perp.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

import harness_perp as HP
from harness_perp import PreparedBoth, run

OK = 0
FAIL = 0


def ok(cond: bool, label: str, extra: str = "") -> None:
    global OK, FAIL
    if cond:
        OK += 1
        print(f"  ok   {label}")
    else:
        FAIL += 1
        print(f"  FAIL {label}  {extra}")


def mkdf(closes, highs=None, lows=None, opens=None, step=3_600_000):
    n = len(closes)
    closes = np.asarray(closes, dtype=float)
    opens = closes if opens is None else np.asarray(opens, dtype=float)
    highs = np.maximum(opens, closes) if highs is None else np.asarray(highs, dtype=float)
    lows = np.minimum(opens, closes) if lows is None else np.asarray(lows, dtype=float)
    return pd.DataFrame({"ts": np.arange(n, dtype=np.int64) * step,
                         "open": opens, "high": highs, "low": lows,
                         "close": closes, "volume": np.ones(n)})


def prep(n, entry_l=None, entry_s=None, exit_l=None, exit_s=None,
         stop_dist=1.0, tp_rr=None, trail=None, trail_min_step=0.001,
         atr=1.0, warmup=0):
    z = lambda: np.zeros(n, dtype=bool)
    el, es = (z() if entry_l is None else entry_l), (z() if entry_s is None else entry_s)
    xl, xs = (z() if exit_l is None else exit_l), (z() if exit_s is None else exit_s)
    return PreparedBoth(el, es, xl, xs,
                        np.full(n, stop_dist, dtype=float), tp_rr, trail,
                        trail_min_step, np.full(n, atr, dtype=float), warmup)


print("=" * 78)
print("AUTO-TESTE harness_perp (series sinteticas)")
print("=" * 78)

# ---------------------------------------------------------------- 1. sem look-ahead
print("\n1. Anti-look-ahead: sinal no close de i preenche no OPEN de i+1")
# preco plano 100, com um candle 5 que ABRE em 100 e FECHA em 200 (spike).
closes = [100, 100, 100, 100, 100, 200, 200, 200]
opens = [100, 100, 100, 100, 100, 100, 200, 200]
df = mkdf(closes, opens=opens, highs=[100, 100, 100, 100, 100, 200, 200, 200],
          lows=[100, 100, 100, 100, 100, 100, 200, 200])
e = np.zeros(8, dtype=bool)
e[4] = True                     # decide no close de 4 -> entra no open de 5 (=100)
p = prep(8, entry_l=e, stop_dist=1.0, tp_rr=None)
r = run(None, df, p, np.zeros(8))
ok(r.trades == 1, "abriu 1 trade")
entry = r.trade_list[0][2] if r.trade_list else 0
ok(abs(entry - 100 * (1 + HP.SLIPPAGE_PCT)) < 1e-9,
   f"entrou no OPEN de i+1 (100 + slippage), nao no close 200", f"entry={entry}")

# se o sinal fosse lido do candle 5 (look-ahead), entraria a 200.
ok(entry < 150, "nao usou o close do proprio candle do sinal")

# ---------------------------------------------------------------- 2. fee
print("\n2. Contabilidade de fee (entrada + saida, 0,055%/lado)")
# stop_dist 2.0 num preco 100 -> nocional 250 = 25% do equity: o teto de 50%
# NAO morde, entao o size e exatamente risco/stop_dist (o teto e testado no 7).
closes = [100] * 5 + [110] * 3
df = mkdf(closes)
e = np.zeros(8, dtype=bool); e[3] = True
p = prep(8, entry_l=e, stop_dist=2.0, tp_rr=4.0)   # TP em 100+8 = 108 -> dispara em 110
r = run(None, df, p, np.zeros(8))
ok(r.trades == 1, "1 trade")
if r.trades == 1:
    t = r.trade_list[0]
    ep, xp, pnl = t[2], t[3], t[4]
    size = (HP.START_EQUITY * HP.RISK_PCT) / 2.0
    ok(abs(ep * size - 250.0) < 1.0, "teto de nocional NAO morde neste caso",
       f"nocional={ep*size:.2f}")
    gross = (xp - ep) * size
    fee = (ep + xp) * size * HP.FEE_PCT
    ok(abs(pnl - (gross - fee)) < 1e-9, "pnl = bruto - fee(2 lados)",
       f"pnl={pnl} esperado={gross-fee}")
    ok(abs(r.fees_paid - fee) < 1e-9, "fees_paid registrado")
    ok(abs(r.end_equity - (HP.START_EQUITY + pnl)) < 1e-9, "equity = inicial + pnl")

# ---------------------------------------------------------------- 3. stop 1R
print("\n3. Stop puro = -1R (mais slippage), TP em tp_rr = +tp_rr R")
# stop atingido DENTRO do candle (open acima do stop, low perfura) — sem gap.
# entrada no open de 3 = 100 -> stop em 98. candle 4: open 99, low 97,5.
closes = [100, 100, 100, 100, 99.0, 99.0]
opens = [100, 100, 100, 100, 99.0, 99.0]
lows = [100, 100, 100, 100, 97.5, 99.0]
df = mkdf(closes, opens=opens, lows=lows, highs=[100, 100, 100, 100, 99.5, 99.0])
e = np.zeros(6, dtype=bool); e[2] = True
p = prep(6, entry_l=e, stop_dist=2.0, tp_rr=2.0)
r = run(None, df, p, np.zeros(6))
ok(r.trades == 1 and r.trade_list[0][6] == "stop_loss", "fechou por stop_loss")
if r.trades == 1:
    rr = r.trade_list[0][5]
    ok(-1.15 < rr < -0.98, "R do stop perto de -1 (um pouco pior por slippage/fee)",
       f"R={rr:.3f}")

# gap-through: candle ABRE abaixo do stop -> fill no open (pior que o stop).
# Isto e a diferenca deliberada vs o backtester oficial, tem que ser -2R aqui.
closes = [100, 100, 100, 100, 96, 96]
df = mkdf(closes, lows=[100, 100, 100, 100, 96, 96])
e = np.zeros(6, dtype=bool); e[2] = True
p = prep(6, entry_l=e, stop_dist=2.0, tp_rr=2.0)   # stop em 98, candle abre em 96
r = run(None, df, p, np.zeros(6))
if r.trades == 1:
    rr = r.trade_list[0][5]
    ok(rr < -1.5, "gap-through preenche no open, pior que -1R (conservador)",
       f"R={rr:.3f}")

closes = [100, 100, 100, 100, 103, 103]
df = mkdf(closes, highs=[100, 100, 100, 100, 103, 103])
e = np.zeros(6, dtype=bool); e[2] = True
p = prep(6, entry_l=e, stop_dist=1.0, tp_rr=2.0)   # TP em 102
r = run(None, df, p, np.zeros(6))
ok(r.trades == 1 and r.trade_list[0][6] == "take_profit", "fechou por take_profit")
if r.trades == 1:
    rr = r.trade_list[0][5]
    ok(1.7 < rr < 2.0, "R do TP perto de +2", f"R={rr:.3f}")

# ---------------------------------------------------------------- 4. trailing
print("\n4. Trailing: sobe com o preco, nunca desce, e trava lucro na reversao")
# sobe de 100 a 110 e volta pra 100. Sem trailing, stop fixo em 99 -> nunca
# dispara e fecha 'eod' perto de 100 (~0R). Com trailing de 2.0, o stop sobe
# ate ~108 e o trade fecha POSITIVO.
closes = [100, 100, 102, 104, 106, 108, 110, 105, 100, 100]
df = mkdf(closes, highs=closes, lows=closes)
e = np.zeros(10, dtype=bool); e[1] = True
p_fix = prep(10, entry_l=e, stop_dist=1.0, tp_rr=None, trail=None)
r_fix = run(None, df, p_fix, np.zeros(10))
p_tr = prep(10, entry_l=e, stop_dist=1.0, tp_rr=None, trail=2.0, atr=1.0)
r_tr = run(None, df, p_tr, np.zeros(10))
ok(r_tr.pnl_sum > r_fix.pnl_sum, "trailing lucra mais que stop fixo nesta reversao",
   f"trail={r_tr.pnl_sum:.4f} fixo={r_fix.pnl_sum:.4f}")
ok(r_tr.trades == 1 and r_tr.trade_list[0][6] == "stop_loss",
   "trailing fecha via o proprio stop (movido)")
if r_tr.trades == 1:
    xp = r_tr.trade_list[0][3]
    ok(xp > 104, "saiu bem acima da entrada (stop foi movido)", f"exit={xp:.2f}")

# passo minimo: com passo gigante (50%) o stop nunca se move -> igual ao fixo
p_big = prep(10, entry_l=e, stop_dist=1.0, tp_rr=None, trail=2.0, trail_min_step=0.5)
r_big = run(None, df, p_big, np.zeros(10))
ok(abs(r_big.pnl_sum - r_fix.pnl_sum) < 1e-9,
   "passo minimo gigante neutraliza o trailing (= stop fixo)",
   f"big={r_big.pnl_sum:.4f} fixo={r_fix.pnl_sum:.4f}")

# ---------------------------------------------------------------- 5. short
print("\n5. Short: espelho do long")
closes = [100, 100, 98, 96, 94, 94]
df = mkdf(closes, highs=closes, lows=closes)
e = np.zeros(6, dtype=bool); e[1] = True
p = prep(6, entry_s=e, stop_dist=1.0, tp_rr=2.0)   # short 100, TP em 98
r = run(None, df, p, np.zeros(6))
ok(r.trades == 1 and r.shorts == 1, "abriu short")
ok(r.trades == 1 and r.trade_list[0][6] == "take_profit", "short lucra na queda")
ok(r.pnl_sum > 0, "pnl short positivo na queda", f"pnl={r.pnl_sum:.4f}")

# short entra no open de i+1 = 100 e SO DEPOIS o preco sobe (opens explicitos,
# senao a entrada ja acontece no preco alto e o teste nao prova nada).
closes = [100, 100, 100, 103, 103]
opens = [100, 100, 100, 100, 103]
highs = [100, 100, 100, 103, 103]
df = mkdf(closes, opens=opens, highs=highs, lows=[100, 100, 100, 100, 103])
e = np.zeros(5, dtype=bool); e[1] = True
p = prep(5, entry_s=e, stop_dist=2.0, tp_rr=2.0)   # short em 100, stop em 102
r = run(None, df, p, np.zeros(5))
ok(r.trades == 1 and r.trade_list[0][6] == "stop_loss", "short perde na alta",
   f"reason={r.trade_list[0][6] if r.trades else 'n/a'}")
ok(r.pnl_sum < 0, "pnl short negativo na alta")

# ---------------------------------------------------------------- 6. funding
print("\n6. Funding: long PAGA rate positivo, short RECEBE")
closes = [100] * 8
df = mkdf(closes)
fa = np.zeros(8); fa[4] = 0.001            # +0,1% num candle com posicao aberta
e = np.zeros(8, dtype=bool); e[1] = True
p = prep(8, entry_l=e, stop_dist=2.0, tp_rr=None)
r_l = run(None, df, p, fa)
p_s = prep(8, entry_s=e, stop_dist=2.0, tp_rr=None)
r_s = run(None, df, p_s, fa)
ok(r_l.funding_paid > 0, "long pagou funding positivo", f"{r_l.funding_paid:+.5f}")
ok(r_s.funding_paid < 0, "short recebeu funding positivo", f"{r_s.funding_paid:+.5f}")
# nao e exatamente simetrico: o size de cada lado difere porque a entrada sai a
# open*(1+slip) no long e open*(1-slip) no short. Tem que bater dentro de ~0,1%.
rel = abs(r_l.funding_paid + r_s.funding_paid) / abs(r_l.funding_paid)
ok(rel < 1e-3, "simetrico entre os lados (a menos do slippage de entrada)",
   f"desvio relativo={rel:.2e}")

# ---------------------------------------------------------------- 7. sizing
print("\n7. Sizing: risco 0,5% + teto de nocional de 50% do equity")
# ACHADO IMPORTANTE que este teste documenta: com risk_pct 0,5% e teto de
# nocional de 50% do equity, o teto MORDE sempre que o stop for mais apertado
# que 1% do preco  (nocional pedido = equity * risk_pct / stop_pct; com
# stop_pct = 0,5% isso da 100% do equity, o dobro do teto). O stop mediano
# REAL do perfil daytrade e 0,40% -> o daytrade opera SEMPRE no teto, ou seja
# o risco efetivo por trade dele e ~0,2% do equity, nao os 0,5% do YAML.
closes = [100] * 6
df = mkdf(closes, lows=[100, 100, 100, 100, 0.01, 0.01])   # candle 4 zera -> fecha
e = np.zeros(6, dtype=bool); e[1] = True

def notional_of(stop_dist):
    p = prep(6, entry_l=e, stop_dist=stop_dist, tp_rr=None)
    r = run(None, df, p, np.zeros(6))
    if r.trades != 1:
        return None, r
    ep, xp, pnl = r.trade_list[0][2], r.trade_list[0][3], r.trade_list[0][4]
    # pnl = (xp-ep)*size - (ep+xp)*size*fee  ->  size = pnl / ((xp-ep) - (ep+xp)*fee)
    size = pnl / ((xp - ep) - (ep + xp) * HP.FEE_PCT)
    return ep * size, r

# stop de 2% do preco -> nocional pedido = 1000*0.005/0.02 = 250 (teto nao morde)
n2, _ = notional_of(2.0)
ok(n2 is not None and abs(n2 - 250.0) < 2.0,
   "stop de 2%: nocional 250 (= risco 0,5%, teto nao morde)", f"nocional={n2}")

# stop de 0,4% do preco (o mediano REAL do daytrade) -> pedido = 1250, teto 500
n04, _ = notional_of(0.4)
ok(n04 is not None and abs(n04 - 500.0) < 2.0,
   "stop de 0,4%: teto de 50% corta o nocional em 500 (era 1250)", f"nocional={n04}")
ok(n04 is not None and n04 < 1250 * 0.45,
   "risco efetivo cai a ~0,2% do equity quando o teto morde")

# nocional abaixo do minimo -> nao abre
p3 = prep(6, entry_l=e, stop_dist=100000.0, tp_rr=None)
r3 = run(None, df, p3, np.zeros(6))
ok(r3.trades == 0, "nocional abaixo do minimo nao abre trade")

# ---------------------------------------------------------------- 8. one-way
print("\n8. One-way mode: nunca long e short ao mesmo tempo")
closes = [100] * 8
df = mkdf(closes)
el = np.zeros(8, dtype=bool); el[1] = True; el[3] = True
es = np.zeros(8, dtype=bool); es[3] = True      # sinal contraditorio em 3
p = prep(8, entry_l=el, entry_s=es, stop_dist=1.0, tp_rr=None)
r = run(None, df, p, np.zeros(8))
ok(r.trades <= 1, "sinal contraditorio nao abre dois trades", f"trades={r.trades}")

el = np.zeros(8, dtype=bool); el[1] = True
es = np.zeros(8, dtype=bool); es[3] = True
p = prep(8, entry_l=el, entry_s=es, stop_dist=1.0, tp_rr=None)
r = run(None, df, p, np.zeros(8))
ok(r.longs == 1 and r.shorts == 0,
   "short e ignorado enquanto o long esta aberto (posicao unica)")

# ---------------------------------------------------------------- 9. gates
print("\n9. Gates allow_long / allow_short")
el = np.ones(8, dtype=bool)
p = prep(8, entry_l=el, stop_dist=1.0, tp_rr=None)
r = run(None, df, p, np.zeros(8), allow_long=False)
ok(r.trades == 0, "allow_long=False nao abre long")
es = np.ones(8, dtype=bool)
p = prep(8, entry_s=es, stop_dist=1.0, tp_rr=None)
r = run(None, df, p, np.zeros(8), allow_short=False)
ok(r.trades == 0, "allow_short=False nao abre short")

# ---------------------------------------------------------------- 10. retorno
print("\n10. total_return_pct usa o capital REAL da chamada (bug de 22/07)")
closes = [100, 100, 100, 100, 103, 103]
df = mkdf(closes, highs=[100, 100, 100, 100, 103, 103])
e = np.zeros(6, dtype=bool); e[2] = True
p = prep(6, entry_l=e, stop_dist=1.0, tp_rr=2.0)
r = run(None, df, p, np.zeros(6), start_equity=500.0)
ok(abs(r.total_return_pct - (r.end_equity / 500.0 - 1) * 100) < 1e-9,
   "divide pelo start_equity passado, nao pela constante global")
ok(r.start_equity == 500.0, "start_equity registrado")

print("\n" + "=" * 78)
print(f"RESULTADO: {OK} ok, {FAIL} FAIL")
print("=" * 78)
sys.exit(1 if FAIL else 0)
