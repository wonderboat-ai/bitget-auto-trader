"""Política de restart automático do processo (main.py) — pura, sem I/O.

Fecha a metade pendente do item [ALVO] do charter ("processo supervisionado
com restart automático + alerta ativo") — a metade "alerta" já existia desde
21/07/2026 via a tarefa agendada trader-watchdog, mas aquela SÓ avisa, nunca
religa. Ver CLAUDE.md, seção "Watchdog agendado" e bug-tracking item 6b.

Mantida isolada de subprocess/relógio real de propósito, para ser testável
com timestamps sintéticos sem precisar spawnar processo nenhum (mesmo
espírito de manter risco/execução testável offline que o resto do projeto
já segue)."""
from __future__ import annotations


class RestartPolicy:
    """Janela deslizante de crashes: no máximo `max_restarts` reinícios
    dentro de `window_sec` segundos. Ao exceder, `should_restart()` passa a
    recusar — evita um loop de crash rápido reiniciando indefinidamente
    (config quebrada, exchange fora do ar, etc.) sem nunca alertar ninguém."""

    def __init__(self, max_restarts: int = 5, window_sec: float = 1800.0) -> None:
        self.max_restarts = max_restarts
        self.window_sec = window_sec
        self._history: list[float] = []

    def record_crash(self, now: float) -> None:
        self._history.append(now)
        self._trim(now)

    def _trim(self, now: float) -> None:
        cutoff = now - self.window_sec
        self._history = [t for t in self._history if t >= cutoff]

    def should_restart(self, now: float) -> bool:
        self._trim(now)
        return len(self._history) <= self.max_restarts

    def attempts_in_window(self, now: float) -> int:
        self._trim(now)
        return len(self._history)


def backoff_seconds(attempt: int, base: float = 10.0, cap: float = 300.0) -> float:
    """Backoff exponencial simples: 10s, 20s, 40s, 80s... até `cap` (5min)."""
    if attempt <= 0:
        return base
    return min(base * (2 ** (attempt - 1)), cap)
