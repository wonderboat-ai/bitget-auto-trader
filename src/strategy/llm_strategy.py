"""LLMStrategy — a camada de decisão do Claude (Fase 3).

Implementa a MESMA interface da estratégia determinística: `generate(snap) -> Signal`.
Por isso ela entra no Backtester, no walk-forward e no engine sem mudar mais nada —
é o pagamento por termos mantido o contrato `Signal` como fronteira desde a Fase 1.

Fluxo:
  snapshot -> prompt -> API Anthropic (JSON estrito) -> parse/validação -> Signal

Segurança (o ponto mais importante desta classe):
  - Qualquer falha (rede, timeout, JSON inválido, campo faltando, stop incoerente,
    convicção abaixo do limiar) resulta em FLAT. O sistema NUNCA opera na dúvida.
  - A resposta do Claude ainda passa pela camada de risco, que veta de novo. Duas
    barreiras independentes.
  - A chamada é injetável (client_fn) para permitir teste sem API real e para trocar
    o provedor sem reescrever a lógica de decisão.
"""
from __future__ import annotations

import json
import math
from typing import Callable

from src.data.market_data import MarketSnapshot
from src.logger import audit, get_logger
from src.strategy.llm_prompt import build_system_prompt, build_user_prompt, snapshot_to_payload
from src.strategy.signal import Direction, Signal

log = get_logger("llm_strategy")

# Assinatura da função que fala com o modelo: (system, user) -> texto da resposta.
LLMClientFn = Callable[[str, str], str]

# entry_price do modelo divergindo mais que isto do preço real (snap.last_price)
# vira FLAT — achado da revisão adversarial de 22/07/2026 (única fronteira de
# confiança GENUINAMENTE NOVA que a Fase 3 introduz: a estratégia
# determinística sempre deriva entry_price do candle real; aqui vem de um
# JSON não confiável). Sem isto, um entry_price fabricado passa incoerente só
# internamente (stop coerente com ELE, não com o preço real) e o
# reancoramento de preço no executor.py pode nascer um stop a centavos do
# fill real — stop dispara quase na hora, queimando taxa de ida+volta por
# nada. 2% é generoso o bastante pra não vetar por atraso normal entre o
# snapshot e a resposta do modelo, mas curto o bastante pra pegar preço
# inventado/alucinado.
MAX_ENTRY_PRICE_DEVIATION_PCT = 0.02


class LLMStrategy:
    def __init__(
        self,
        profile: str,
        client_fn: LLMClientFn,
        min_conviction: float = 0.6,
        market_type: str = "perp",
    ) -> None:
        self.profile = profile
        self.client_fn = client_fn
        self.min_conviction = min_conviction
        # market_type condiciona o prompt (spot: sem short/alavancagem) — ver
        # llm_prompt.build_system_prompt. Construído uma vez aqui, não a cada
        # chamada: nunca muda durante a vida do processo (mudar de modo exige
        # editar o YAML e reiniciar o motor, igual a tudo mais no projeto).
        self.system_prompt = build_system_prompt(market_type)

    def generate(self, snap: MarketSnapshot) -> Signal:
        try:
            # snapshot_to_payload() ficava FORA deste try (achado da revisão
            # de 22/07/2026): uma exceção ali (ex.: indicador ausente,
            # contexto não serializável) escapava de generate() inteiro em
            # vez de virar FLAT como todo resto da classe promete — e ainda
            # pulava o risk_manager.evaluate() daquele ciclo por completo (só
            # o catch genérico do engine.run_once() segurava, sem o mesmo
            # rastro de auditoria de um FLAT normal).
            payload = snapshot_to_payload(snap)
            raw = self.client_fn(self.system_prompt, build_user_prompt(payload))
        except Exception as exc:  # noqa: BLE001
            return self._flat(snap, f"Falha na chamada ao modelo: {exc}")

        parsed = self._parse(raw)
        if parsed is None:
            return self._flat(snap, "Resposta do modelo não é JSON válido")

        return self._to_signal(snap, parsed)

    # ------------------- parsing e validação -------------------
    @staticmethod
    def _parse(raw: str) -> dict | None:
        """Extrai o objeto JSON da resposta, tolerando cercas de código."""
        text = raw.strip()
        if text.startswith("```"):
            # remove ```json ... ``` se o modelo cercar a resposta
            text = text.strip("`")
            if text.lower().startswith("json"):
                text = text[4:]
        # pega do primeiro { ao último } para ignorar preâmbulos acidentais
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end == -1 or end <= start:
            return None
        try:
            return json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            return None

    def _to_signal(self, snap: MarketSnapshot, data: dict) -> Signal:
        direction_raw = str(data.get("direction", "flat")).lower()
        if direction_raw not in ("long", "short", "flat"):
            return self._flat(snap, f"Direção inválida: {direction_raw!r}")

        if direction_raw == "flat":
            return self._flat(snap, str(data.get("rationale", "modelo retornou flat")))

        try:
            conviction = float(data.get("conviction", 0.0))
            entry = float(data.get("entry_price", snap.last_price))
            stop = float(data.get("stop_price", 0.0))
            tp = data.get("take_profit")
            tp = float(tp) if tp is not None else None
        except (TypeError, ValueError):
            return self._flat(snap, "Campos numéricos inválidos na resposta")

        # NaN/±inf nunca passam em NENHUMA comparação Python (nan < x, nan <= x,
        # nan >= x são sempre False) — achado CRÍTICO da revisão de 22/07/2026:
        # TODOS os guards abaixo (convicção, coerência do stop) e os
        # equivalentes em risk_manager.py compartilham esse ponto cego, então
        # um stop_price=NaN vindo do modelo passava por TUDO e chegava
        # aprovado (position_size=nan) até o executor. Cortado aqui, na
        # fronteira de dado não confiável, antes de qualquer guard que
        # dependa de comparação numérica.
        if not all(math.isfinite(v) for v in (conviction, entry, stop, *([tp] if tp is not None else []))):
            return self._flat(snap, "Campo numérico não-finito (NaN/±inf) na resposta")

        # Convicção abaixo do limiar -> não opera.
        if conviction < self.min_conviction:
            return self._flat(snap, f"Convicção {conviction:.2f} < limiar {self.min_conviction}")

        direction = Direction.LONG if direction_raw == "long" else Direction.SHORT

        # Coerência do stop (a camada de risco veta de novo, mas filtramos cedo).
        if not stop or stop <= 0:
            return self._flat(snap, "Stop ausente na resposta do modelo")
        if direction == Direction.LONG and stop >= entry:
            return self._flat(snap, "long com stop >= entry (incoerente)")
        if direction == Direction.SHORT and stop <= entry:
            return self._flat(snap, "short com stop <= entry (incoerente)")

        # entry_price fabricado/alucinado (achado MÉDIO da revisão, a única
        # fronteira de confiança genuinamente NOVA que a Fase 3 introduz): a
        # estratégia determinística sempre deriva entry_price do candle real;
        # aqui vem de JSON não confiável, e os guards acima só checam
        # coerência INTERNA (stop coerente com o entry fabricado, não com o
        # preço real). Sem isto, um entry_price bem longe do mercado real
        # ainda passa, e o reancoramento de preço no executor.py pode nascer
        # um stop a centavos do fill de verdade.
        if snap.last_price and math.isfinite(snap.last_price):
            deviation = abs(entry - snap.last_price) / snap.last_price
            if deviation > MAX_ENTRY_PRICE_DEVIATION_PCT:
                return self._flat(
                    snap,
                    f"entry_price {entry:.2f} diverge {deviation:.1%} do preço real "
                    f"{snap.last_price:.2f} (limite {MAX_ENTRY_PRICE_DEVIATION_PCT:.0%})",
                )

        conviction_clamped = max(0.0, min(1.0, conviction))
        rationale_curto = str(data.get("rationale", ""))[:280]
        audit("llm_signal", symbol=snap.symbol, direction=direction.value,
              conviction=conviction_clamped, rationale=rationale_curto)
        return Signal(
            symbol=snap.symbol,
            direction=direction,
            conviction=conviction_clamped,
            entry_price=entry,
            stop_price=stop,
            take_profit=tp,
            profile=self.profile,
            rationale=rationale_curto,
        )

    def _flat(self, snap: MarketSnapshot, why: str) -> Signal:
        log.info("LLM -> FLAT: %s", why)
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


def anthropic_client_fn(model: str, temperature: float = 0.2, max_tokens: int = 512) -> LLMClientFn:
    """Fábrica do client_fn real usando o SDK da Anthropic.

    Requer o pacote `anthropic` e a variável ANTHROPIC_API_KEY. Mantido separado da
    lógica de decisão para que o backtest/teste use um client_fn simulado.
    """
    from anthropic import Anthropic  # import tardio: só quando for usar de verdade

    client = Anthropic()

    def _call(system: str, user: str) -> str:
        resp = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        return "".join(block.text for block in resp.content if block.type == "text")

    return _call
