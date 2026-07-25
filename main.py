"""Ponto de entrada.

Uso:
    python main.py            # roda em loop (DRY_RUN por padrão — paper trading)
    python main.py --once     # um único ciclo (útil para teste/diagnóstico)
    python main.py --live     # desativa DRY_RUN (envia ordens à exchange configurada)

ATENÇÃO: --live com ENVIRONMENT=mainnet opera com DINHEIRO REAL.
Padrão seguro: ENVIRONMENT=testnet + DRY_RUN ligado.
"""
from __future__ import annotations

import argparse

from src.engine import Engine


def main() -> None:
    parser = argparse.ArgumentParser(description="Bybit Auto Trader — Fase 1")
    parser.add_argument("--once", action="store_true", help="Executa um único ciclo e sai")
    parser.add_argument("--live", action="store_true", help="Desativa DRY_RUN (envia ordens)")
    parser.add_argument("--interval", type=int, default=60, help="Segundos entre ciclos")
    args = parser.parse_args()

    engine = Engine(dry_run=not args.live)
    if args.once:
        engine.run_once()
    else:
        engine.run_forever(interval_sec=args.interval)


if __name__ == "__main__":
    main()
