"""Diagnóstico de saldo — mostra O QUE a exchange devolveu, sem segredos.

Uso:
    python diag_saldo.py

Objetivo: quando o risco veta com "Saldo/equity zerado", este script mostra a
resposta crua (resumida) da Bybit para você ver ONDE o dinheiro está — ou
confirmar que a conta de testnet está vazia mesmo.
"""
from __future__ import annotations

from config.settings import get_credentials, get_environment
from src.exchange.bybit_client import BybitClient


def main() -> None:
    env = get_environment()
    print(f"Ambiente: {env.upper()}")
    client = BybitClient(get_credentials())

    bal = client.exchange.fetch_balance()

    # ---- Visão v5 (info crua, resumida) ----
    accounts = (bal.get("info", {}).get("result", {}) or {}).get("list", []) or []
    if not accounts:
        print("A exchange não devolveu nenhuma conta no wallet-balance.")
    for acct in accounts:
        print(f"\nConta tipo ......... {acct.get('accountType')}")
        print(f"totalEquity ........ {acct.get('totalEquity')!r}")
        print(f"totalWalletBalance . {acct.get('totalWalletBalance')!r}")
        print(f"totalAvailable ..... {acct.get('totalAvailableBalance')!r}")
        coins = acct.get("coin") or []
        with_money = [c for c in coins
                      if float(c.get("walletBalance") or 0) != 0
                      or float(c.get("equity") or 0) != 0]
        if with_money:
            print("Moedas com saldo:")
            for c in with_money:
                print(f"  {c.get('coin'):<8} wallet={c.get('walletBalance')!r}  equity={c.get('equity')!r}")
        else:
            print("Moedas com saldo: NENHUMA")

    # ---- Visão unificada do CCXT ----
    usdt = bal.get("USDT", {}) or {}
    print(f"\nCCXT USDT -> total={usdt.get('total')!r}  free={usdt.get('free')!r}  used={usdt.get('used')!r}")

    # ---- O que o engine enxerga ----
    print(f"Engine (fetch_balance_usdt) -> {client.fetch_balance_usdt()}")

    print(
        "\nSe tudo acima está zerado: pegue USDT de teste em https://testnet.bybit.com"
        "\n(Assets -> Request Coupon / faucet). Se o saldo aparece só na conta FUND:"
        "\ntransfira Funding -> Unified Trading dentro da própria testnet."
    )


if __name__ == "__main__":
    main()
