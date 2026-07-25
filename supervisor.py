"""Supervisor de processo — reinicia main.py automaticamente se ele CAIR
sozinho (crash), sem religar se o operador pediu Ctrl+C de propósito.

Uso (substitui `python main.py` quando se quer auto-restart em produção):
    python supervisor.py            # loop DRY_RUN supervisionado
    python supervisor.py --live     # loop --live supervisionado
    python supervisor.py --live --interval 60

Fecha a metade pendente do item [ALVO] do charter ("processo supervisionado
com restart automático + alerta ativo") — ver CLAUDE.md, "Watchdog agendado"
e item 6b dos Próximos passos (22/07/2026). O watchdog agendado
(trader-watchdog, hora em hora* ver CLAUDE.md) continua útil por cima disso:
ele alerta mesmo quando NEM o supervisor está rodando (ex.: Claude Desktop
fechado) — este script não o substitui.

Como distingue parada deliberada de crash: supervisor e main.py rodam no
MESMO console (subprocesso sem CREATE_NEW_PROCESS_GROUP/CREATE_NEW_CONSOLE
— comportamento padrão no Windows) — um Ctrl+C no terminal chega nos DOIS
processos ao mesmo tempo. O supervisor então só espera main.py terminar
sozinho (ele audita `engine_stop` por conta própria, como sempre fez) e
encerra SEM reiniciar. Se main.py morrer por qualquer outro motivo (Task
Manager, falha de energia/SO, exceção fatal fora do try/except do próprio
run_once/run_forever) o supervisor não recebe KeyboardInterrupt nenhum —
trata como crash e religa, com backoff e um teto de tentativas por janela.

Nunca toca risco/execução/ordem — só spawna/observa o processo main.py e
audita o próprio ciclo de vida (`engine_crash_restart`,
`engine_supervisor_giveup`) na mesma trilha `logs/audit.jsonl` que o motor
usa (via `src.logger.audit`, respeitando AUDIT_PATH se setado)."""
from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from src.logger import audit, get_logger  # noqa: E402
from src.supervision.restart_policy import RestartPolicy, backoff_seconds  # noqa: E402

log = get_logger("supervisor")

MAX_RESTARTS = 5
WINDOW_SEC = 1800.0  # 30 min
MIN_UPTIME_TO_RESET_SEC = 600.0  # 10 min de vida "limpa" reseta a janela/backoff


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Roda main.py em loop, reiniciando automaticamente se ele "
                    "cair sozinho (nunca em parada manual via Ctrl+C).")
    parser.add_argument("--live", action="store_true",
                         help="Repassado a main.py — desativa DRY_RUN")
    parser.add_argument("--interval", type=int, default=60,
                         help="Repassado a main.py — segundos entre ciclos")
    args = parser.parse_args()

    child_args = [sys.executable, str(ROOT / "main.py"), "--interval", str(args.interval)]
    if args.live:
        child_args.append("--live")

    policy = RestartPolicy(max_restarts=MAX_RESTARTS, window_sec=WINDOW_SEC)
    attempt = 0

    log.info("Supervisor iniciando main.py (live=%s, interval=%s)", args.live, args.interval)

    while True:
        start_ts = time.monotonic()
        proc = subprocess.Popen(child_args, cwd=str(ROOT))
        try:
            exit_code = proc.wait()
        except KeyboardInterrupt:
            log.warning("Ctrl+C no supervisor — aguardando main.py encerrar de "
                        "propósito (ele audita engine_stop sozinho).")
            try:
                proc.wait(timeout=15)
            except subprocess.TimeoutExpired:
                log.warning("main.py não encerrou em 15s — finalizando à força.")
                proc.terminate()
                try:
                    proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    proc.kill()
            log.info("Supervisor encerrado (parada manual, sem restart).")
            return

        uptime = time.monotonic() - start_ts
        log.error("main.py encerrou sozinho (código %s, uptime %.0fs) — "
                   "tratando como crash.", exit_code, uptime)

        if uptime >= MIN_UPTIME_TO_RESET_SEC:
            # Rodou "limpo" tempo suficiente antes de cair — não é parte de
            # um loop de crash rápido; recomeça a janela/backoff do zero.
            policy = RestartPolicy(max_restarts=MAX_RESTARTS, window_sec=WINDOW_SEC)
            attempt = 0

        now = time.monotonic()
        policy.record_crash(now)
        audit("engine_crash_restart", exit_code=exit_code, uptime_sec=round(uptime, 1),
              attempt_in_window=policy.attempts_in_window(now))

        if not policy.should_restart(now):
            audit("engine_supervisor_giveup", max_restarts=MAX_RESTARTS, window_sec=WINDOW_SEC)
            log.critical("%d crashes em %.0fmin — desistindo de reiniciar. "
                          "Intervenção manual necessária.",
                          policy.attempts_in_window(now), WINDOW_SEC / 60)
            return

        attempt += 1
        delay = backoff_seconds(attempt)
        log.warning("Reiniciando em %.0fs (tentativa %d)...", delay, attempt)
        time.sleep(delay)


if __name__ == "__main__":
    main()
