"""Provedores de CONTEXTO para a camada de decisão do Claude (Fase 3).

O Claude não decide bem só com preço e RSI — ele precisa do cenário macro, do
fluxo on-chain e de indicadores de sentimento. Estes provedores buscam esses dados
de fontes externas e devolvem um dicionário que entra no `MarketSnapshot.context`.

Cada provedor é uma interface fina. Aqui entregamos:
  - a interface (ContextProvider),
  - stubs seguros que retornam {} (NullMacroProvider / NullOnChainProvider),
  - a implementação real usada em produção: DossierMacroProvider /
    DossierOnChainProvider, que leem o cache diário gerado por dossier_fetch.py
    (pesquisa via Claude + web search, 1x/dia — nunca dentro do loop de 60s),
  - o agregador que junta tudo num único dict.

Regra de segurança: se um provedor falhar, ele retorna {} e loga — nunca derruba o
ciclo nem inventa número. Dado ausente é dado ausente; o Claude é instruído a ser
conservador quando o contexto está incompleto.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol

from src.logger import get_logger

log = get_logger("context")

DOSSIER_CONTEXT_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "context" / "latest.json"


class ContextProvider(Protocol):
    name: str

    def fetch(self, symbol: str) -> dict:
        """Retorna um dict de contexto. Em falha, retorna {} (não levanta)."""
        ...


class NullMacroProvider:
    """Placeholder de macro. Substitua por uma implementação com fonte real
    (calendário econômico, DXY, juros, risk-on/off)."""
    name = "macro"

    def fetch(self, symbol: str) -> dict:
        # TODO: integrar fonte real. Exemplo de shape esperado:
        # return {"dxy_trend": "up", "risk_regime": "risk_off", "next_event": "CPI em 2d"}
        return {}


class NullOnChainProvider:
    """Placeholder on-chain. Substitua por Glassnode/CryptoQuant/etc."""
    name = "onchain"

    def fetch(self, symbol: str) -> dict:
        # TODO: integrar fonte real. Exemplo de shape esperado:
        # return {"exchange_netflow": "outflow", "stablecoin_supply": "rising", "mvrv": 1.8}
        return {}


def _read_dossier_context() -> dict | None:
    """Lê data/context/latest.json, gerado 1x/dia por dossier_fetch.py (raiz do
    projeto). Retorna None se o arquivo não existe, está corrompido, OU está
    desatualizado (date != hoje em UTC) — nunca propaga dado velho nem inventa.

    Por que ler um arquivo e não chamar a API aqui: o engine roda a cada ~60s;
    fazer uma pesquisa com LLM+web search nessa cadência seria caro, lento, e
    devolveria o mesmo dado 1400 vezes por dia. dossier_fetch.py já fez a
    pesquisa de manhã — este provider só lê o resultado.
    """
    try:
        raw = DOSSIER_CONTEXT_PATH.read_text(encoding="utf-8")
        data = json.loads(raw)
    except FileNotFoundError:
        log.warning("data/context/latest.json não existe ainda — rode dossier_fetch.py.")
        return None
    except (json.JSONDecodeError, OSError) as exc:
        log.warning("data/context/latest.json ilegível (%s) — tratando como ausente.", exc)
        return None

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if data.get("date") != today:
        log.warning(
            "Contexto do dossiê desatualizado (arquivo é de %s, hoje é %s) — "
            "retornando vazio em vez de usar dado velho.",
            data.get("date"), today,
        )
        return None
    return data


class DossierMacroProvider:
    """Contexto macro extraído do dossiê diário (dossier_fetch.py + Dossie
    Cripto/Historico/). Mesma disciplina de segurança dos providers Null: falha
    ou dado velho -> {} silencioso, nunca exceção, nunca número inventado."""
    name = "macro"

    def fetch(self, symbol: str) -> dict:
        data = _read_dossier_context()
        return data.get("macro", {}) if data else {}


class DossierOnChainProvider:
    """Mesma fonte que DossierMacroProvider, recorte on-chain do dossiê."""
    name = "onchain"

    def fetch(self, symbol: str) -> dict:
        data = _read_dossier_context()
        return data.get("onchain", {}) if data else {}


class BybitDerivativesProvider:
    """Contexto de DERIVATIVOS em tempo real, direto da Bybit (decisão #G,
    18/07/2026) — funding rate, open interest, razão long/short. Complementa
    o DossierOnChainProvider (foto 1x/dia, pesquisa via Claude+web search)
    com granularidade intra-dia, sem custo de API paga.

    IMPORTANTE — isto NÃO é dado on-chain de verdade (a Bybit não lê
    blockchain, não tem fluxo de exchange/MVRV/SOPR). É sentimento de
    DERIVATIVOS dos usuários dela mesma — por isso o nome do provider é
    "derivatives", não "onchain" (evita colidir com a chave já usada por
    DossierOnChainProvider no dict agregado, e evita a confusão semântica).

    Todos os endpoints usados são de mercado PÚBLICO (leitura, não ordem) —
    não dependem do modo de conta (spot/perp) nem esbarram no bloqueio de
    EXECUÇÃO de derivativos para residente BR (que é só sobre criar ordem,
    nunca sobre ler dado público de mercado). Sempre consulta o PERPÉTUO do
    símbolo, mesmo quando a conta opera em modo spot — funding/open
    interest/long-short só existem para derivativos.

    Mesma disciplina de segurança dos outros providers: qualquer falha
    (rede, símbolo sem derivativo listado, endpoint fora do ar) some do
    dict — nunca derruba o ciclo, nunca inventa número. Os métodos do
    client já retornam None em falha; aqui só filtramos o que veio."""
    name = "derivatives"

    def __init__(self, client) -> None:
        self._client = client

    @staticmethod
    def _perp_symbol(symbol: str) -> str:
        """'BTC/USDT' (spot) -> 'BTC/USDT:USDT' (perpétuo USDT). Símbolo já
        em formato perpétuo (tem ':') passa direto."""
        return symbol if ":" in symbol else f"{symbol}:USDT"

    def fetch(self, symbol: str) -> dict:
        perp = self._perp_symbol(symbol)
        out: dict = {}
        # Cada chamada isolada no próprio try/except (revisão adversarial de
        # 22/07/2026): os 3 métodos do client hoje NUNCA levantam (cada um já
        # captura a própria exceção e devolve None), mas se algum dia um
        # regredir e deixar escapar, sem isto o ContextAggregator.build()
        # (a única rede de segurança externa) descartaria TODO o `out`
        # acumulado até ali — perdendo os campos que já tinham vindo certos
        # por causa de um irmão que falhou depois. Mesmo espírito de nunca
        # deixar uma falha localizada apagar trabalho já feito (ex.: audit de
        # sucesso do trailing em try próprio, 21/07).
        try:
            funding = self._client.fetch_derivatives_funding_rate(perp)
            if funding:
                out["funding_rate"] = funding
        except Exception as exc:  # noqa: BLE001
            log.warning("BybitDerivativesProvider: funding de %s falhou: %s", perp, exc)
        try:
            open_interest = self._client.fetch_open_interest(perp)
            if open_interest:
                out["open_interest"] = open_interest
        except Exception as exc:  # noqa: BLE001
            log.warning("BybitDerivativesProvider: open interest de %s falhou: %s", perp, exc)
        try:
            # timeframe explícito (não confiar no default do client
            # coincidir — achado da revisão: um dia diverge silenciosamente).
            long_short = self._client.fetch_long_short_ratio(perp, timeframe="1h")
            if long_short:
                out["long_short_ratio"] = long_short
        except Exception as exc:  # noqa: BLE001
            log.warning("BybitDerivativesProvider: long/short ratio de %s falhou: %s", perp, exc)
        return out


class ContextAggregator:
    """Junta os provedores num único dict de contexto, isolando falhas."""

    def __init__(self, providers: list[ContextProvider] | None = None) -> None:
        self.providers = providers or [NullMacroProvider(), NullOnChainProvider()]

    def build(self, symbol: str) -> dict:
        context: dict = {}
        for p in self.providers:
            try:
                data = p.fetch(symbol)
                if data:
                    context[p.name] = data
            except Exception as exc:  # noqa: BLE001
                log.warning("Provedor de contexto '%s' falhou: %s", p.name, exc)
                context[p.name] = {}
        return context
