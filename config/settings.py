"""Carregamento central de configuração: ambiente, credenciais e parâmetros de risco.

Separa explicitamente testnet de mainnet. O padrão é SEMPRE testnet — só roda
em mainnet se ENVIRONMENT=mainnet estiver setado de forma deliberada.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

RISK_CONFIG_PATH = ROOT / "config" / "risk_config.yaml"


@dataclass(frozen=True)
class ExchangeCredentials:
    api_key: str
    api_secret: str
    testnet: bool


def get_environment() -> str:
    env = os.getenv("ENVIRONMENT", "testnet").strip().lower()
    if env not in ("testnet", "mainnet"):
        raise ValueError(f"ENVIRONMENT inválido: {env!r}. Use 'testnet' ou 'mainnet'.")
    return env


def get_credentials() -> ExchangeCredentials:
    env = get_environment()
    if env == "testnet":
        key = os.getenv("BYBIT_TESTNET_API_KEY", "")
        secret = os.getenv("BYBIT_TESTNET_API_SECRET", "")
        return ExchangeCredentials(key, secret, testnet=True)

    # mainnet — exige confirmação explícita por ser dinheiro real
    key = os.getenv("BYBIT_MAINNET_API_KEY", "")
    secret = os.getenv("BYBIT_MAINNET_API_SECRET", "")
    if not key or not secret:
        raise RuntimeError(
            "ENVIRONMENT=mainnet mas chaves de mainnet ausentes. "
            "Operação real abortada por segurança."
        )
    return ExchangeCredentials(key, secret, testnet=False)


def load_risk_config(path: Path | None = None) -> dict:
    path = path or RISK_CONFIG_PATH
    with open(path, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def get_market_type(cfg: dict) -> str:
    """"perp" (default) ou "spot" — decisão #E de 15/07/2026 (migração p/ spot).

    Centralizado aqui para engine, risco, executor e backtester lerem a MESMA
    resposta; default "perp" preserva o comportamento validado até a virada
    deliberada do YAML."""
    mt = str((cfg.get("market") or {}).get("type", "perp")).strip().lower()
    if mt not in ("perp", "spot"):
        raise ValueError(f"market.type inválido no risk_config.yaml: {mt!r} (use 'perp' ou 'spot')")
    return mt


def get_log_level() -> str:
    return os.getenv("LOG_LEVEL", "INFO").strip().upper()
