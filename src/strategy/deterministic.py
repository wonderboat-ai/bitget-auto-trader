"""Estratégia determinística da Fase 1 — SEM LLM.

Objetivo: validar o encanamento (dados -> sinal -> risco -> execução) com uma
regra simples e auditável. NÃO é a estratégia final; é o trilho de teste.

Regra (cruzamento de EMAs + filtro de RSI):
  - LONG  se EMA_fast > EMA_slow e RSI < rsi_long_max (alta, não sobrecomprado)
  - SHORT se EMA_fast < EMA_slow e RSI > rsi_short_min (baixa, não sobrevendido)
  - Stop  a atr_stop_mult x ATR; alvo a tp_rr x a distância do stop

Os parâmetros de DECISÃO ficam em StrategyParams — é o que o walk-forward otimiza
in-sample e valida out-of-sample. Os defaults reproduzem o comportamento original,
então o live continua idêntico se nenhum parâmetro for passado.

A camada de risco recalcula e veta independentemente — esta classe só PROPÕE.
"""
from __future__ import annotations

from dataclasses import dataclass

from src.data.market_data import MarketSnapshot
from src.strategy.signal import Direction, Signal


@dataclass(frozen=True)
class StrategyParams:
    atr_stop_mult: float = 1.5
    tp_rr: float = 2.0
    rsi_long_max: float = 70.0
    rsi_short_min: float = 30.0
    # Saída por SINAL (20/07/2026): a pesquisa de 16/07 mostrou que a família
    # atual é a única SEM saída por sinal — ela gira fee no stop/TP sem nunca
    # sair "de graça" quando a tendência vira. Desligado por default: ligar é
    # mudança de comportamento live e decisão do Lucas (walk-forward pode
    # ligar por injeção de params sem tocar o live).
    exit_on_signal: bool = False
    # Trailing stop (20/07/2026): substitui o TP fixo por um stop que sobe
    # travando lucro. Também desligado por default, pelo mesmo motivo.
    trailing: bool = False

    def as_dict(self) -> dict:
        return {
            "atr_stop_mult": self.atr_stop_mult,
            "tp_rr": self.tp_rr,
            "rsi_long_max": self.rsi_long_max,
            "rsi_short_min": self.rsi_short_min,
            "exit_on_signal": self.exit_on_signal,
            "trailing": self.trailing,
        }


class DeterministicStrategy:
    def __init__(self, profile: str, params: StrategyParams | None = None) -> None:
        self.profile = profile
        self.params = params or StrategyParams()

    @property
    def wants_exit_signals(self) -> bool:
        """O engine consulta ISTO antes de montar snapshot pra saída por
        sinal — False (default) mantém custo zero por ciclo (nenhum fetch de
        OHLCV extra) e o comportamento antigo intacto."""
        return self.params.exit_on_signal

    def generate(self, snap: MarketSnapshot) -> Signal:
        p = self.params
        ind = snap.indicators
        price = snap.last_price
        atr = ind.get("atr") or 0.0
        ema_fast, ema_slow, rsi = ind["ema_fast"], ind["ema_slow"], ind["rsi"]

        # Indicadores inválidos (warmup insuficiente / NaN) -> não opera.
        if atr <= 0 or ema_fast != ema_fast or rsi != rsi:
            return self._flat(snap, "Indicadores indisponíveis (warmup)")

        if ema_fast > ema_slow and rsi < p.rsi_long_max:
            stop = price - p.atr_stop_mult * atr
            # Trailing ligado -> SEM alvo fixo: o stop que sobe é o mecanismo
            # de realização (deixa o lucro correr — o ponto das famílias de
            # tendência que a pesquisa de 16/07 recomendou re-testar).
            tp = None if p.trailing else price + p.tp_rr * (price - stop)
            return Signal(
                symbol=snap.symbol,
                direction=Direction.LONG,
                conviction=self._conviction(ema_fast, ema_slow, atr),
                entry_price=price,
                stop_price=stop,
                take_profit=tp,
                profile=self.profile,
                rationale=f"EMA_fast>EMA_slow e RSI={rsi:.1f}<{p.rsi_long_max:.0f}",
                trailing=p.trailing,
            )

        if ema_fast < ema_slow and rsi > p.rsi_short_min:
            stop = price + p.atr_stop_mult * atr
            tp = None if p.trailing else price - p.tp_rr * (stop - price)
            return Signal(
                symbol=snap.symbol,
                direction=Direction.SHORT,
                conviction=self._conviction(ema_slow, ema_fast, atr),
                entry_price=price,
                stop_price=stop,
                take_profit=tp,
                profile=self.profile,
                rationale=f"EMA_fast<EMA_slow e RSI={rsi:.1f}>{p.rsi_short_min:.0f}",
                trailing=p.trailing,
            )

        return self._flat(snap, "Sem alinhamento EMA/RSI")

    def should_exit(self, snap: MarketSnapshot, position: dict) -> str | None:
        """Saída por SINAL de uma posição já aberta (20/07/2026).

        Devolve o racional (string) quando a estratégia manda FECHAR a posição
        agora, ou None pra manter. Contrato deliberadamente separado de
        generate(): entrada passa pelo veto de risco; saída NUNCA passa —
        fechar posição reduz risco (mesma filosofia do stop e do kill switch,
        decisão #B). O engine chama isto a cada ciclo pra cada posição aberta
        (engine._check_spot_exits); estratégias sem o método (ou com
        exit_on_signal desligado) simplesmente não têm saída por sinal — o
        comportamento antigo (só stop + TP fixo) fica intacto.

        `position` é a entrada do protection_state (entry_price, stop_price,
        take_profit, size, side) — side é sempre "long" em spot.
        """
        if not self.params.exit_on_signal:
            return None
        ind = snap.indicators
        ema_fast, ema_slow = ind.get("ema_fast"), ind.get("ema_slow")
        # NaN/ausente -> não decide nada com dado inválido (NaN != NaN).
        if ema_fast is None or ema_slow is None or ema_fast != ema_fast or ema_slow != ema_slow:
            return None
        side = position.get("side", "long")
        if side == "long" and ema_fast < ema_slow:
            return "Saída por sinal: EMA_fast<EMA_slow (tendência virou; era long)"
        if side == "short" and ema_fast > ema_slow:
            return "Saída por sinal: EMA_fast>EMA_slow (tendência virou; era short)"
        return None

    def _flat(self, snap: MarketSnapshot, why: str) -> Signal:
        return Signal(
            symbol=snap.symbol,
            direction=Direction.FLAT,
            conviction=0.0,
            entry_price=snap.last_price,
            stop_price=0.0,
            take_profit=None,
            profile=self.profile,
            rationale=why,
        )

    @staticmethod
    def _conviction(a: float, b: float, atr: float) -> float:
        if atr <= 0:
            return 0.0
        return max(0.0, min(1.0, abs(a - b) / atr))
