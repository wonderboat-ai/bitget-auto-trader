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
    # Terceiro segredo, exigido pela Bitget e inexistente na Bybit. Fica com
    # default vazio para não quebrar quem constrói credenciais da Bybit.
    passphrase: str = ""


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


def get_bitget_credentials() -> ExchangeCredentials:
    """Credenciais da Bitget — sempre MAINNET, sempre dinheiro real.

    Não existe ramo de testnet aqui, e a ausência é deliberada: a Bitget não
    tem testnet acessível via ccxt (`urls['test']` é None). Aceitar
    `ENVIRONMENT=testnet` devolvendo credenciais vazias faria o MCP entrar em
    modo offline silencioso e o motor parecer saudável sem estar conectado a
    nada — por isso o erro é explícito."""
    env = get_environment()
    if env != "mainnet":
        raise RuntimeError(
            f"ENVIRONMENT={env!r}, mas a Bitget não tem testnet via ccxt. "
            "Use ENVIRONMENT=mainnet — e saiba que é dinheiro real."
        )
    key = os.getenv("BITGET_MAINNET_API_KEY", "").strip()
    secret = os.getenv("BITGET_MAINNET_API_SECRET", "").strip()
    passphrase = os.getenv("BITGET_MAINNET_API_PASSPHRASE", "").strip()
    if not key or not secret or not passphrase:
        # A passphrase entra no guard junto com key/secret: sem ela nenhuma
        # chamada assinada passa, e o erro que a exchange devolve não deixa
        # óbvio que o problema é uma variável de ambiente faltando.
        faltam = [n for n, v in (("KEY", key), ("SECRET", secret),
                                 ("PASSPHRASE", passphrase)) if not v]
        raise RuntimeError(
            f"Credenciais da Bitget incompletas (faltam: {', '.join(faltam)}). "
            "Operação real abortada por segurança."
        )
    return ExchangeCredentials(key, secret, testnet=False, passphrase=passphrase)


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
