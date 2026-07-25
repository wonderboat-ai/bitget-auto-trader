"""Persistência do kill switch através de restarts do processo.

Achado real (20/07/2026, ver CLAUDE.md "Estado exato — 20/07"): antes deste
módulo, `RiskManager._kill_switch` só existia em RAM — reiniciar o processo
zerava o halt SEM gerar nenhum evento na trilha. Duas consequências reais:

1) Um kill switch disparado por drawdown de verdade "resetava" sozinho se o
   processo caísse/reiniciasse — violando a regra do charter de que o reset
   é SEMPRE manual e deliberado (nunca automático).
2) O supervisor via MCP (`state_reader.read_halt_status`, que só lia a
   trilha) continuava reportando o último trip como ativo mesmo com o motor
   livre de novo, porque não existia nenhum evento novo para ele enxergar a
   mudança — visto ao vivo em 21/07 (halted:true reportado enquanto o motor
   operava normalmente).

Este módulo persiste o estado em disco (mesmo padrão de
`execution/protection_state.py`: escrita atômica via tmp+replace, corrupção
nunca derruba o processo) para o RiskManager recuperar o estado real na
inicialização, e para `state_reader.py` ler a MESMA fonte de verdade em vez
de inferir da trilha.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from src.logger import get_logger

log = get_logger("kill_switch_state")

ROOT = Path(__file__).resolve().parent.parent.parent


def _resolve_state_path() -> Path:
    """Destino do arquivo, com override por KILL_SWITCH_STATE_PATH (relativo
    à raiz) — mesmo padrão de AUDIT_PATH em src/logger.py (fix #14, 15/07).

    Motivo (achado em 21/07/2026, corrigido na mesma sessão): sem isto, o
    backtester oficial (`src/backtest/backtester.py`) instancia um
    RiskManager de verdade, que LÊ e GRAVA neste MESMO arquivo que o motor
    ao vivo usa — herda o halted/motivo reais na leitura (resultado do
    backtest fica estranho, tudo vetado), e pode ESCREVER halted=True
    simulado por cima do real se o backtest disparar um trip simulado.
    Essa escrita é SILENCIOSA para quem olha a trilha real: o evento
    `kill_switch_tripped` correspondente vai para o AUDIT_PATH isolado do
    backtest (fix #14), nunca para logs/audit.jsonl — nada explicaria por
    que o motor ao vivo passou a rejeitar entradas."""
    override = os.environ.get("KILL_SWITCH_STATE_PATH")
    if not override:
        return ROOT / "state" / "kill_switch_state.json"
    p = Path(override)
    return p if p.is_absolute() else ROOT / p


STATE_PATH = _resolve_state_path()


def load() -> dict:
    """{"halted": bool, "reason": str}. Arquivo ausente/corrompido = não
    halted — mesmo comportamento de sempre (antes deste módulo existir),
    nunca trava o motor por causa de um arquivo ilegível."""
    if not STATE_PATH.exists():
        return {"halted": False, "reason": ""}
    try:
        data = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        return {"halted": bool(data.get("halted", False)), "reason": data.get("reason") or ""}
    except (OSError, ValueError) as exc:
        # ValueError cobre JSONDecodeError e UnicodeDecodeError — mesmo padrão
        # de protection_state.load() (achado da revisão adversarial de 18/07).
        log.warning("state/kill_switch_state.json corrompido/ilegível (%s) — "
                    "tratando como não-halted", exc)
        return {"halted": False, "reason": ""}


def save(halted: bool, reason: str = "") -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps({"halted": halted, "reason": reason}, indent=2),
                   encoding="utf-8")
    tmp.replace(STATE_PATH)  # atômico no mesmo filesystem, inclusive Windows/NTFS
