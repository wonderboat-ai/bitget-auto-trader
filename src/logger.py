"""Logging estruturado: console legível + trilha de auditoria em JSONL.

Toda decisão e execução é registrada em logs/audit.jsonl para que a supervisão
(você + MCP) possa reconstruir POR QUE o sistema fez cada coisa. Sem isso,
'full-auto' vira caixa-preta.
"""
from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOG_DIR = ROOT / "logs"
LOG_DIR.mkdir(exist_ok=True)
AUDIT_PATH = LOG_DIR / "audit.jsonl"


def _audit_path() -> Path:
    """Destino da trilha, com override por AUDIT_PATH (relativo à raiz).

    Motivo: a trilha logs/audit.jsonl é do LIVE. O RiskManager audita toda
    aprovação/veto, então uma rodada de walk-forward (48 combos × 16 folds)
    despejava dezenas de milhares de eventos SIMULADOS na mesma trilha usada
    para auditar o bot real (visto em 15/07: 500 → 40.405 linhas). Os runners
    de backtest apontam AUDIT_PATH para logs/audit-backtest.jsonl."""
    override = os.environ.get("AUDIT_PATH")
    if not override:
        return AUDIT_PATH
    p = Path(override)
    return p if p.is_absolute() else ROOT / p


def get_logger(name: str, level: str = "INFO") -> logging.Logger:
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger
    logger.setLevel(getattr(logging, level, logging.INFO))
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        logging.Formatter("%(asctime)s | %(levelname)-7s | %(name)s | %(message)s")
    )
    logger.addHandler(handler)
    return logger


def audit(event: str, **payload) -> None:
    """Anexa um evento estruturado à trilha de auditoria.

    Todo evento carrega `environment` (testnet/mainnet, de os.environ —
    igual à leitura crua que config.settings.get_environment() faz, sem
    importar esse módulo aqui pra não acoplar o logger de baixo nível à
    config; sem validação de valor, é só rótulo informativo, nunca deve
    fazer audit() lançar exceção). Antes, só o evento `engine_start`
    carregava esse campo (via payload explícito, que continua tendo
    prioridade abaixo) — todo resto da trilha (`trade_closed`,
    `order_executed`, `signal_approved` etc.) era MUDO sobre em qual
    ambiente rodou. Achado por revisão adversarial em 27/07/2026
    (transição testnet->mainnet): sem isso, as ferramentas MCP de leitura
    (`state_reader.py`) não tinham como sinalizar se um evento retornado
    veio de testnet ou mainnet, caso os dois algum dia se misturem na
    mesma trilha de novo."""
    record = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "event": event,
        "environment": os.environ.get("ENVIRONMENT", "testnet").strip().lower(),
        **payload,
    }
    with open(_audit_path(), "a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
