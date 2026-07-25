"""Contrato do SINAL — a fronteira entre 'quem decide' e 'quem controla risco'.

Na Fase 1 o sinal vem de uma estratégia determinística. Na Fase 3, virá do Claude
com EXATAMENTE este mesmo formato. A camada de risco não sabe (nem precisa saber)
quem produziu o sinal — ela só valida e veta.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Direction(str, Enum):
    LONG = "long"
    SHORT = "short"
    FLAT = "flat"  # nenhum trade


# Passo mínimo do trailing stop (fração do preço): o stop trailed só é
# efetivado quando melhora além disto. Definido AQUI (o contrato do trailing
# vive neste módulo) porque live (engine) e replay (backtester) precisam da
# MESMA constante — paridade é requisito, não coincidência. No live o passo
# evita churn de cancelar/recriar a ordem condicional a cada micro-avanço;
# no backtest ele existe só pra espelhar esse comportamento.
TRAIL_MIN_STEP_PCT = 0.001


@dataclass(frozen=True)
class Signal:
    symbol: str
    direction: Direction
    conviction: float          # 0.0 a 1.0
    entry_price: float
    stop_price: float          # OBRIGATÓRIO se direction != FLAT
    take_profit: float | None
    profile: str               # "daytrade" | "swing"
    rationale: str             # por que esse trade (vai pra auditoria)
    # Trailing stop (20/07/2026): quando True, o stop desta posição sobe
    # travando lucro conforme o preço avança (distância = |fill - stop| da
    # entrada, mantida a partir do pico visto). Default False preserva o
    # comportamento validado (stop fixo + TP fixo) em todo chamador antigo.
    trailing: bool = False

    def is_actionable(self) -> bool:
        return self.direction in (Direction.LONG, Direction.SHORT)
