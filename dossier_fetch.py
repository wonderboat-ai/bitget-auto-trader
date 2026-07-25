#!/usr/bin/env python
"""dossier_fetch.py — Camada 1.5: contexto externo diário para o Auto-Trade.

Roda 1x/dia (cron / Windows Task Scheduler / scheduled task no Cowork), ANTES da
abertura do mercado americano. Nunca deve rodar dentro do loop de 60s do engine —
seria caro e lento chamar um LLM com busca web a cada ciclo. O engine só LÊ o
resultado já processado (ver DossierMacroProvider/DossierOnChainProvider em
src/context/providers.py).

O que faz, em ordem:
  1. Pesquisa o dossiê de mercado cripto completo (calendário, notícias, macro,
     técnico, on-chain, radar de 20 moedas, posicionamento, síntese) via Claude
     + web search — mesmo conteúdo do Dossie-Cripto-Prompt-Template-v2.html.
  2. Extrai os dados relevantes em formato estruturado numa chamada SEPARADA,
     com tool_choice forçado — nunca faz parsing manual do texto livre.
  3. Grava três artefatos:
       a) Dossie Cripto/Historico/{data}.md               — leitura humana
       b) Dossie Cripto/importar-no-dashboard-{data}.json  — mesmo formato que
          já vinha sendo usado manualmente (date/price/bias/funding/fg/etf/fullText)
       c) data/context/{data}.json + data/context/latest.json + history.jsonl
          — o contrato que DossierMacroProvider/DossierOnChainProvider leem
          para alimentar snap.context (entra no prompt da Camada 3, quando ligada).

Regra de segurança (mesma disciplina do resto do projeto): dado não confirmado na
pesquisa fica AUSENTE — nunca inventado. Se a extração vier incompleta, o script
grava o que puder e deixa registrado em log/audit o que faltou. Se falhar por
completo, sai com código != 0 e NÃO toca em latest.json — o provider então lê o
arquivo do dia anterior, vê a data desatualizada, e devolve {} sozinho (já
implementado em providers.py; ver docstring de lá).

Este script só produz DADOS. Não manda ordem, não mexe em state/control.json,
não mexe em config/risk_config.yaml. Fora do escopo de decisão/execução por
desenho — mesma separação rígida do resto do Auto-Trade (ver INSTRUCOES-PROJETO-v2.md).

Uso:
    python dossier_fetch.py                  # dossiê de hoje (UTC)
    python dossier_fetch.py --date 2026-06-10 # backfill de uma data específica
    python dossier_fetch.py --date 2026-06-10 --no-latest  # backfill sem tocar
                                               # no ponteiro "latest.json" do dia atual
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
HIST_DIR = ROOT / "Dossie Cripto" / "Historico"
DASH_DIR = ROOT / "Dossie Cripto"
CTX_DIR = ROOT / "data" / "context"

# Ajuste aqui ou via variável de ambiente DOSSIER_MODEL. Verifique o nome vigente
# em docs.claude.com/en/docs/about-claude/models antes de trocar.
DEFAULT_MODEL = "claude-sonnet-5"

WEEKDAYS_PT = ["Segunda", "Terça", "Quarta", "Quinta", "Sexta", "Sábado", "Domingo"]

DOSSIER_PROMPT_TEMPLATE = """Você é o meu analista-chefe de mesa de operações cripto. Sua função é me entregar um dossiê completo do mercado em uma única resposta estruturada. Pesquise dados atuais e confirmados antes de responder e cite a fonte e a data de cada dado quantitativo. Comece a resposta com o título "# \U0001F4CA DOSSIÊ DE MERCADO CRIPTO — {weekday}, {data}" seguido de uma linha curta com ativo principal e preço aproximado.

Data de hoje: {data}
Ativo principal: BTC (cite ETH e altcoins quando relevante).
Tempo gráfico de referência: Mensal, Semanal, Diário e 4H.

PARTE 1 — CALENDÁRIO ECONÔMICO DA SEMANA
1. Os eventos mais importantes da SEMANA (de segunda a domingo), em ordem cronológica, com dia e horário de Brasília: CPI, PCE, PPI, NFP, jobless claims, PIB, ISM, vendas no varejo, FOMC e falas de dirigentes do Fed, leilões de Tesouro, vencimentos de opções BTC/ETH (Deribit/CME), unlocks de tokens relevantes, decisões da SEC e Copom/IPCA.
2. Classifique cada evento por impacto potencial no BTC: 🔴 alto / 🟡 médio / 🟢 baixo.
3. Para os dados de juros/inflação, traga a probabilidade de corte/alta precificada (CME FedWatch / futuros de Fed funds).
4. Destaque qual é O evento da semana — aquele que pode definir a direção — e por quê.

PARTE 2 — AGENDA E NOTÍCIAS DE HOJE
5. Eventos de hoje com horário de Brasília e consenso de mercado para cada um.
6. As 3 notícias mais relevantes das últimas 24h para cripto, com fonte e data.
7. As 3 notícias GEOPOLÍTICAS mais importantes do momento, com fonte e data. Para cada uma, explique o canal de transmissão para o BTC (risk-off, dólar, reserva de valor, liquidez global) e se o efeito esperado é de alta, baixa ou neutro.

PARTE 3 — MACRO E LIQUIDEZ
8. Dólar e juros: nível/direção do DXY; Treasuries 10 e 2 anos; yields reais (TIPS).
9. Liquidez global: tendência do M2 global e da liquidez líquida do Fed (balanço − RRP − TGA).
10. Correlações móveis: BTC vs. S&P 500/Nasdaq e BTC vs. ouro.
11. Termômetros de risco: VIX, MOVE e spreads de crédito high-yield.
12. Fora dos EUA: China (PBOC/estímulo) e Japão (BOJ/carry trade do iene).

PARTE 4 — ESTRUTURA TÉCNICA (MENSAL → 4H)
13. Tendência no Mensal e Semanal antes de descer ao Diário e 4H.
14. Médias móveis: preço vs. MM 50/100/200 diária; golden/death cross.
15. Suportes e resistências ancorados em Volume Profile (POC e Value Area).
16. RSI e MACD com divergências. Níveis de Fibonacci relevantes.
17. Nível de INVALIDAÇÃO para o cenário comprado e para o vendido.
18. O que o lado oposto da leitura estaria enxergando.

PARTE 5 — ON-CHAIN
19. Fluxo de exchanges (netflow): pressão de venda ou acumulação?
20. LTH vs. STH; MVRV / MVRV Z-score, SOPR, NUPL.
21. Stablecoins: market cap USDT+USDC e mintagem recente da Tether.
22. Mineradores: hash rate, reservas e Puell Multiple.
23. Baleias: movimentações relevantes nas últimas 24–48h.

PARTE 6 — RADAR DE MOEDAS QUENTES (20 ATIVOS)
24. As 20 moedas/narrativas mais quentes: maiores altas e volume em 7 dias, narrativa (IA, RWA, L2, memecoin, DeFi etc). Tabela ranqueada de 1 a 20.
25. Para cada uma: catalisador real e principal risco.
26. Dominância do BTC e das stablecoins (USDT.D) subindo ou caindo?

PARTE 7 — POSICIONAMENTO E PROBABILIDADES
27. Max pain, funding rate, open interest, fluxo dos ETFs spot de BTC, liquidações 24h.
28. Skew de opções (25-delta), gamma/gamma flip, long/short ratio, CVD.
29. Fear & Greed Index e prêmio Coinbase/Kimchi.
30. Matriz de cenários: ACIMA/EM LINHA/ABAIXO do consenso → impacto provável.

PARTE 8 — SÍNTESE EXECUTIVA E GESTÃO DE RISCO
31. Viés do dia em UMA PALAVRA: long, short ou neutro — máximo 3 linhas de justificativa.
32. Região tática: entrada a favor do viés, alvo(s), onde a tese morre (R:R aproximada).
33. Risco do dia: evento/nível que pode virar o jogo e horário de atenção.
34. Oportunidade da semana: cruzando calendário, radar e on-chain.
35. Delta diário — o que mudou desde ontem.

Importante: se algum dado específico não estiver disponível via busca, diga isso explicitamente em vez de inventar número. Inclua uma seção "Fontes" ao final com as pesquisas usadas. Este dossiê é informativo, não recomendação de investimento."""

EXTRACTION_TOOL = {
    "name": "salvar_contexto_estruturado",
    "description": (
        "Estrutura o dossiê pesquisado em dois formatos: um resumo curto para "
        "dashboard e um contexto macro/on-chain para a camada de decisão do "
        "Auto-Trade. Omita qualquer campo que não foi confirmado na pesquisa "
        "— nunca invente número."
    ),
    "input_schema": {
        "type": "object",
        "required": ["dashboard"],
        "properties": {
            "dashboard": {
                "type": "object",
                "required": ["bias"],
                "description": "Resumo curto, mesmo formato do arquivo importar-no-dashboard.",
                "properties": {
                    "price": {"type": "number", "description": "Preço aproximado do BTC em USD no momento da pesquisa"},
                    "bias": {"type": "string", "enum": ["long", "short", "neutro"]},
                    "funding": {"type": "string", "description": "Funding rate atual, texto curto"},
                    "fg": {"type": "string", "description": "Fear & Greed Index, texto curto (valor + rótulo)"},
                    "etf": {"type": "string", "description": "Fluxo de ETF spot recente, texto curto"},
                },
            },
            "macro": {
                "type": "object",
                "description": "Vai para snap.context['macro']. Omita campos não confirmados.",
                "properties": {
                    "dxy_trend": {"type": "string", "description": "up / down / lateral"},
                    "risk_regime": {"type": "string", "enum": ["risk_on", "risk_off", "neutral"]},
                    "next_event": {"type": "string", "description": "evento mais importante da semana + quando"},
                    "fed_funds_prob_hold": {"type": "number"},
                    "fed_funds_prob_hike": {"type": "number"},
                    "fed_funds_prob_cut": {"type": "number"},
                    "vix": {"type": "number"},
                    "ust10y": {"type": "number"},
                    "fear_greed": {"type": "number"},
                    "fear_greed_label": {"type": "string"},
                    "etf_flow_trend": {"type": "string", "description": "inflow_forte / inflow_fraco / outflow / revertendo"},
                    "geopolitical_risk": {"type": "string", "description": "resumo curto do principal risco geopolítico ativo"},
                    "btc_dominance_trend": {"type": "string"},
                },
            },
            "onchain": {
                "type": "object",
                "description": "Vai para snap.context['onchain']. Omita campos não confirmados.",
                "properties": {
                    "mvrv_z_score": {"type": "number"},
                    "nupl": {"type": "number"},
                    "exchange_netflow": {"type": "string", "description": "inflow (pressão venda) / outflow (acumulação) / neutro"},
                    "lth_supply_trend": {"type": "string"},
                    "stablecoin_mcap_trend": {"type": "string"},
                    "hash_rate_trend": {"type": "string"},
                    "miner_stress": {"type": "string"},
                    "whale_signal": {"type": "string"},
                },
            },
        },
    },
}


def _client_and_model():
    import anthropic  # import tardio, mesmo padrão de src/strategy/llm_strategy.py

    return anthropic.Anthropic(), os.getenv("DOSSIER_MODEL", DEFAULT_MODEL)


def research(date_str: str) -> str:
    """Passo 1: pesquisa completa com web search. Retorna o markdown do dossiê.

    web_search é tool server-side: a API executa as buscas e continua a geração
    dentro da MESMA chamada — não é preciso um loop manual de tool_use aqui. Se
    isso mudar no futuro, ver docs.anthropic.com/en/docs/agents-and-tools/tool-use/web-search-tool.
    """
    client, model = _client_and_model()
    weekday = WEEKDAYS_PT[datetime.strptime(date_str, "%Y-%m-%d").weekday()]
    prompt = DOSSIER_PROMPT_TEMPLATE.format(data=date_str, weekday=weekday)

    resp = client.messages.create(
        model=model,
        max_tokens=8000,
        tools=[{"type": "web_search_20250305", "name": "web_search", "max_uses": 25}],
        messages=[{"role": "user", "content": prompt}],
    )
    text = "".join(b.text for b in resp.content if b.type == "text")
    if not text.strip():
        raise RuntimeError(f"Pesquisa retornou vazia (stop_reason={resp.stop_reason!r})")
    return text


def extract(dossie_md: str) -> dict:
    """Passo 2: extração estruturada forçada via tool_choice — nunca regex no texto livre."""
    client, model = _client_and_model()
    resp = client.messages.create(
        model=model,
        max_tokens=3000,
        system="Você é um extrator de dados preciso. Nunca invente valores — omita campos não confirmados no texto fornecido.",
        tools=[EXTRACTION_TOOL],
        tool_choice={"type": "tool", "name": "salvar_contexto_estruturado"},
        messages=[
            {
                "role": "user",
                "content": (
                    "Extraia os dados do dossiê abaixo usando a tool "
                    "salvar_contexto_estruturado.\n\n" + dossie_md
                ),
            }
        ],
    )
    for block in resp.content:
        if block.type == "tool_use" and block.name == "salvar_contexto_estruturado":
            return block.input
    raise RuntimeError(f"Extração não retornou tool_use (stop_reason={resp.stop_reason!r})")


def save(date_str: str, dossie_md: str, structured: dict, update_latest: bool = True) -> None:
    HIST_DIR.mkdir(parents=True, exist_ok=True)
    DASH_DIR.mkdir(parents=True, exist_ok=True)
    CTX_DIR.mkdir(parents=True, exist_ok=True)

    dash = structured.get("dashboard", {})
    macro = structured.get("macro", {})
    onchain = structured.get("onchain", {})

    # a) histórico legível — mesma pasta que você já usa manualmente
    (HIST_DIR / f"{date_str}.md").write_text(dossie_md, encoding="utf-8")

    # b) formato de dashboard — mesmo schema do seu importar-no-dashboard-*.json
    dashboard_entry = [{
        "date": date_str,
        "price": dash.get("price"),
        "bias": dash.get("bias", "neutro"),
        "funding": dash.get("funding", "não confirmado"),
        "fg": dash.get("fg", "não confirmado"),
        "etf": dash.get("etf", "não confirmado"),
        "fullText": dossie_md,
    }]
    (DASH_DIR / f"importar-no-dashboard-{date_str}.json").write_text(
        json.dumps(dashboard_entry, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # c) contexto estruturado — contrato lido por DossierMacroProvider/DossierOnChainProvider
    context_payload = {
        "date": date_str,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "macro": macro,
        "onchain": onchain,
    }
    (CTX_DIR / f"{date_str}.json").write_text(
        json.dumps(context_payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # backup append-only — histórico completo para validar a Camada 3 mais tarde (Fase 2/3)
    with open(CTX_DIR / "history.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(context_payload, ensure_ascii=False) + "\n")

    if update_latest:
        # grava em arquivo temporário e troca de nome no final — o provider nunca
        # deve ler um latest.json pela metade se o processo morrer no meio do write.
        tmp = CTX_DIR / "latest.json.tmp"
        tmp.write_text(json.dumps(context_payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(CTX_DIR / "latest.json")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--date", default=None, help="YYYY-MM-DD (padrão: hoje em UTC)")
    parser.add_argument(
        "--no-latest", action="store_true",
        help="Não sobrescreve latest.json — use ao fazer backfill de datas antigas.",
    )
    args = parser.parse_args()
    date_str = args.date or datetime.now(timezone.utc).strftime("%Y-%m-%d")

    sys.path.insert(0, str(ROOT))  # robusto a partir de qualquer cwd (ex: Task Scheduler)
    from src.logger import audit, get_logger

    log = get_logger("dossier_fetch")

    if not os.getenv("ANTHROPIC_API_KEY"):
        log.error("ANTHROPIC_API_KEY ausente no ambiente/.env — abortando sem chamar a API.")
        audit("dossier_fetch_failed", date=date_str, error="ANTHROPIC_API_KEY ausente")
        return 1

    log.info("Iniciando dossiê para %s", date_str)
    try:
        dossie_md = research(date_str)
        structured = extract(dossie_md)
        save(date_str, dossie_md, structured, update_latest=not args.no_latest)
    except Exception as exc:  # noqa: BLE001 — qualquer falha vira log + audit + exit != 0, nunca silenciosa
        log.error("Falha no dossiê de %s: %s", date_str, exc)
        audit("dossier_fetch_failed", date=date_str, error=str(exc))
        return 1

    missing_macro = [k for k in ("dxy_trend", "risk_regime", "next_event") if k not in structured.get("macro", {})]
    missing_onchain = [k for k in ("mvrv_z_score", "exchange_netflow") if k not in structured.get("onchain", {})]
    audit(
        "dossier_fetch_ok",
        date=date_str,
        bias=structured.get("dashboard", {}).get("bias"),
        missing_macro_fields=missing_macro,
        missing_onchain_fields=missing_onchain,
    )
    log.info("Dossiê de %s salvo (Historico/, importar-no-dashboard, data/context/).", date_str)
    if missing_macro or missing_onchain:
        log.warning("Campos ausentes — macro:%s onchain:%s (ficam ausentes, não inventados)", missing_macro, missing_onchain)
    return 0


if __name__ == "__main__":
    sys.exit(main())
