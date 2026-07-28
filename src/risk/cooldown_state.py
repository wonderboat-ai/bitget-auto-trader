"""Persistência do cooldown por símbolo através de restarts do processo.

Decisão do Lucas (21/07/2026): depois de N stops seguidos no mesmo símbolo,
pausar entradas novas nesse símbolo por um tempo (escalando se acontecer mais
de uma vez no mesmo dia). Achado que motivou isto: o watchdog agendado pegou
um whipsaw real no ETH/USDT (5 stops em 8 minutos) — investigação (workflow
com comparação testnet vs mainnet) confirmou que o ETH real não se moveu;
foi anomalia de dado da testnet. Mas o problema de ARQUITETURA é real
independente da causa: nada impedia reentrada imediata enquanto o mesmo
sinal (candle de 15m) continuasse válido, transformando 1 evento de dado
ruim em N ciclos de perda.

Persistido em disco (mesmo padrão de kill_switch_state.py/protection_state.py:
escrita atômica, corrupção nunca derruba o processo) para sobreviver a um
restart do motor — sem isto, um restart no meio de um cooldown ativo
apagaria a proteção silenciosamente, o mesmo tipo de furo já corrigido pro
kill switch (bug #28) nesta mesma sessão.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from src.logger import get_logger

log = get_logger("cooldown_state")

ROOT = Path(__file__).resolve().parent.parent.parent


def _resolve_state_path() -> Path:
    """Destino do arquivo, com override por COOLDOWN_STATE_PATH (relativo à
    raiz) — mesmo padrão de AUDIT_PATH em src/logger.py (fix #14, 15/07) e de
    KILL_SWITCH_STATE_PATH em kill_switch_state.py (mesma sessão, 21/07).

    Sem isto, o backtester oficial herdaria/sobrescreveria o cooldown REAL
    por símbolo do motor ao vivo — mesmo risco de contaminação silenciosa já
    documentado para o kill switch.

    Isolamento por AMBIENTE (achado da auditoria de 27/07/2026, transição
    pra mainnet, mesmo padrão de kill_switch_state.py): sem override
    explícito, o nome também depende de ENVIRONMENT — mainnet mantém o nome
    canônico (`cooldown_state.json`); testnet ganha um arquivo próprio
    (`cooldown_state-testnet.json`). Antes disto, um stop na testnet podia
    acionar cooldown que valeria (por engano) pro símbolo em mainnet, e
    vice-versa."""
    override = os.environ.get("COOLDOWN_STATE_PATH")
    if override:
        p = Path(override)
        return p if p.is_absolute() else ROOT / p
    from config.settings import get_environment
    if get_environment() == "testnet":
        return ROOT / "state" / "cooldown_state-testnet.json"
    return ROOT / "state" / "cooldown_state.json"


STATE_PATH = _resolve_state_path()


def load() -> dict[str, dict]:
    """{symbol: {"consecutive_stops": int, "cooldown_until": str|None,
    "triggers_date": str|None, "triggers_today": int}}. Arquivo
    ausente/corrompido = dict vazio (nenhum símbolo em cooldown) — nunca
    trava o motor por causa de um arquivo ilegível."""
    if not STATE_PATH.exists():
        return {}
    try:
        data = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError) as exc:
        # ValueError cobre JSONDecodeError e UnicodeDecodeError — mesmo
        # padrão de protection_state.load()/kill_switch_state.load().
        log.warning("state/cooldown_state.json corrompido/ilegível (%s) — "
                    "tratando como vazio (nenhum símbolo em cooldown)", exc)
        return {}


def save(data: dict[str, dict]) -> None:
    # Mesmo guard de kill_switch_state.save() (achado da revisão adversarial
    # de 27/07): uma falha transitória de I/O (lock do OneDrive) aqui não
    # pode propagar — `record_trade_close`/`reset_cooldown`/
    # `_cooldown_veto_reason` em risk_manager.py chamam save() como parte de
    # avaliação normal de risco, e deixar a exceção subir derrubaria o ciclo
    # (ou, no caso de `RiskManager.__init__` indiretamente via cooldown
    # carregado no boot, a construção do Engine inteiro). Estado em RAM
    # (RiskManager._cooldown) continua correto no processo atual; só o
    # espelho em disco fica temporariamente desatualizado.
    try:
        STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = STATE_PATH.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        tmp.replace(STATE_PATH)  # atômico no mesmo filesystem, inclusive Windows/NTFS
    except OSError as exc:
        log.warning("Falha ao persistir state/cooldown_state.json (%s) — "
                    "estado em RAM continua correto neste processo; disco "
                    "fica desatualizado até a próxima save()", exc)
