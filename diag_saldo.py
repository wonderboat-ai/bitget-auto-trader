"""Diagnóstico de saldo — mostra O QUE a exchange devolveu, sem segredos.

Uso:
    python diag_saldo.py

Objetivo duplo:
  1. Quando o risco veta com "Saldo/equity zerado", mostrar a resposta crua da
     Bitget para ver ONDE o dinheiro está.
  2. Provar, a qualquer momento, que `fetch_balance_usdt()` continua lendo o
     campo CERTO. Isto não é zelo: em conta UTA o ccxt descarta o bloco de
     equity e `fetch_balance()['USDT']['total']` devolve só o saldo LIVRE —
     sem a margem travada em posição nem o PnL aberto. Usar aquele número como
     equity produz drawdown FANTASMA e dispara o kill switch de 3% (cujo reset
     é MANUAL) sem nenhuma perda real. É o bug #3 do projeto, e este script é
     a rede que o pega.

A diferença entre as duas colunas só é visível COM POSIÇÃO ABERTA — com a conta
chapada os dois números coincidem e nada prova nada.
"""
from __future__ import annotations

import json

from config.settings import get_bitget_credentials, get_environment
from src.exchange.bitget_client import BitgetClient


def main() -> None:
    print(f"Ambiente: {get_environment().upper()}")
    client = BitgetClient(get_bitget_credentials())

    # ---- Resposta CRUA da rota UTA (a fonte da verdade) ----
    data = (client.exchange.privateUtaGetV3AccountAssets({}) or {}).get("data") or {}
    print("\n--- privateUtaGetV3AccountAssets (cru) ---")
    print(f"accountEquity ...... {data.get('accountEquity')!r}   (em USD)")
    print(f"usdtEquity ......... {data.get('usdtEquity')!r}   <- é ESTE que o engine usa")
    print(f"unrealisedPnl ...... {data.get('unrealisedPnl')!r}")
    print(f"effEquity .......... {data.get('effEquity')!r}")
    for a in (data.get("assets") or []):
        if float(a.get("equity") or 0) or float(a.get("balance") or 0):
            print(f"  {a.get('coin'):<8} equity={a.get('equity')!r} "
                  f"balance={a.get('balance')!r} available={a.get('available')!r} "
                  f"locked={a.get('locked')!r}")

    # ---- O que o ccxt entrega pelo caminho "óbvio" (e por que não serve) ----
    usdt = (client.exchange.fetch_balance({"uta": True}).get("USDT") or {})
    print("\n--- fetch_balance() do ccxt — NÃO usar como equity ---")
    print(f"USDT total={usdt.get('total')!r} free={usdt.get('free')!r} used={usdt.get('used')!r}")

    # ---- O que o engine enxerga ----
    equity = client.fetch_balance_usdt()
    print(f"\nEngine (fetch_balance_usdt) -> {equity}")

    # ---- O veredito ----
    posicoes = client.fetch_open_positions()
    print(f"Posições abertas: {len(posicoes)}")
    for p in posicoes:
        print(f"  {p.get('symbol')} {p.get('side')} {p.get('contracts')} "
              f"@ {p.get('entryPrice')} uPnL={p.get('unrealizedPnl')} "
              f"notional={p.get('notional')}")
    total = usdt.get("total")
    if not posicoes:
        print("\nSem posição aberta: `total` e o equity coincidem por construção "
              "— este diagnóstico não distingue os dois agora. Rode de novo com "
              "posição aberta para a comparação valer.")
    elif total is not None and abs(float(total) - equity) < 1e-9:
        print("\n⚠ ATENÇÃO: com posição aberta, equity e `total` deveriam DIFERIR "
              "(margem travada + PnL). Estão iguais — investigar antes de confiar "
              "no equity; é o sintoma do bug #3.")
    else:
        print(f"\nOK: equity ({equity}) difere de `total` ({total}) com posição "
              "aberta, como esperado — a margem travada e o PnL estão contados.")


if __name__ == "__main__":
    main()
