# Projeto Auto-Trade — Instruções de Projeto (v5 — 2026-07-21)

Documento de referência para qualquer chat/agente que trabalhe neste projeto. Se um
passo proposto violar alguma regra aqui, o passo está errado — não a regra.

Convenção desta versão: **[HOJE]** = implementado e verificado no código;
**[PRONTO-SEM-VALIDAR]** = código existe (testado offline), nunca rodou ao vivo;
**[ALVO]** = escopo do produto final, ainda não construído.
**v5 herda a disciplina da v2-v4 — só atualiza os fatos, não a regra. "Status
atual" é uma FOTO (21/07, ~15:30 UTC), não uma promessa. O detalhe minuto a
minuto vive em `CLAUDE.md`, que muda mais rápido do que este documento deveria.**

## Status atual (fatos verificados em 2026-07-21, até ~15:30 UTC)

- **Fase 1 — FECHADA em 19/07.** O ciclo completo foi validado na exchange real
  (testnet spot), ponta a ponta e confirmado 1:1 contra a UI/histórico da Bybit:
  entrada a mercado + stop real (17/07), e **saída lucrativa automática**
  (19/07 15:15 UTC — TP por software do BTC, pnl +56,51 USDT; depois mais dois
  TPs em 20/07: BTC +9,30 e ETH +83,82). O robô abre, protege e realiza sozinho.
- **Engenharia validada ≠ estratégia validada.** O PnL positivo desses dias é
  encanamento funcionando + mercado subindo — NÃO é evidência de edge (n≈5,
  e a pesquisa formal diz o contrário, ver Fase 2). Não escalar capital com
  base nisso.
- **Quatro bugs REAIS de produção achados e corrigidos ao vivo (19-21/07)**,
  todos via monitoramento em tempo real da trilha: (#23, CRÍTICO) `cancel_all`
  nunca cancelava a categoria `tpslOrder` da Bybit v5 — o TP por software
  ficou quebrado desde 17/07, travado em loop de retry; (#24) proteção não
  cobria fill favorável (sobra real sem stop); (#25) `entry_price` aproximado
  em vez do fill real; (#26) stop/TP ancorados no preço do candle FECHADO sem
  re-ancorar no fill — causou loop real de reentrada drenando taxa (contido
  com kill switch manual via MCP, corrigido na causa raiz). Detalhe completo:
  `CLAUDE.md`, seções "Estado exato" e "Bugs corrigidos".
- **Fase 2 — EXECUTADA (15/07) + pesquisa formal de estratégia (16/07).**
  Veredito da pesquisa (108 combinações × 6 famílias × 6 símbolos × 3
  timeframes, walk-forward honesto, 9 agentes de verificação): **sem edge
  long-only detectável na janela testada (6 meses, 100% bear); a estratégia
  atual do robô (EMA/RSI) é a PIOR das 6 famílias (0/18 séries positivas);
  15m é matematicamente inviável em spot (a taxa come 60-95% da perda)**.
  Relatórios em `research/`. Os datasets usados estão QUEIMADOS para seleção
  de estratégia (OOS inspecionado — hipótese nova exige dado novo).
- **Capacidades de execução novas (21/07) — o pré-requisito da pesquisa:**
  **saída por SINAL** (estratégia manda fechar posição aberta; ex.: EMA
  descruzou) e **trailing stop** (stop sobe travando lucro, cancel+re-arm da
  ordem real com salvaguardas nunca-nua e cura de estado stale pela exchange),
  com o **backtester em paridade total** (mesmas convenções anti-look-ahead,
  mesma re-ancoragem no fill, mesma constante de passo mínimo).
  [PRONTO-SEM-VALIDAR ao vivo; testado offline em 141/141 + revisão
  adversarial com achados corrigidos.] **DESLIGADAS por default** — o live é
  idêntico ao validado até o Lucas ligar via YAML
  (`decision.deterministic.exit_on_signal` / `.trailing`).
- **PRÓXIMO PASSO ACORDADO (21/07): pesquisa de estratégia com dados novos** —
  2+ anos, regime misto (alta/baixa/lateral), walk-forward nas famílias de
  tendência (donchian, ema_cross) em 1h/4h, agora COM saída por
  sinal/trailing simuláveis pela régua.
- **Fase 3 — PRONTO-SEM-VALIDAR** (sem mudança desde 15/07). `LLMStrategy`
  implementada, desligada (`decision.strategy: deterministic`). Dossiê diário
  macro/on-chain roda todo dia (tarefa agendada do Cowork). Decisão #G
  (18/07): fonte on-chain real-time será derivada da própria Bybit (funding,
  OI, long/short ratio), sem API paga — ainda não implementada, não urgente.
- **Fase 4 — FECHADA** (MCP validado 16/07). Ressalva conhecida (20/07): o
  kill switch vive só em memória — reiniciar o processo o zera SEM evento na
  trilha, e `trader_halt_status` pode reportar um halt antigo como ativo.
  Documentado, não corrigido.
- **Fase 5 — BLOQUEADA** por regulação (Bybit descontinuando derivativos para
  residentes BR; spot na entidade Bybit Brasil é o caminho — decisão #E).
- Suíte de testes: **141/141** (`tests/test_smoke.py` 133 + `test_ciclo.py`
  8). Regra operacional REFORÇADA: nunca rodar a suíte com o motor vivo (ela
  faz backup/restore da trilha real).

## 1. Objetivo do projeto

Sistema de decisão assistida por IA com execução automatizada e supervisão humana,
para day trade + swing trade de cripto na Bybit. Full-auto com guardrails. Começa
em testnet, só migra para capital real depois que cada fase anterior fechar.

**Visão de produto (estado final):** o sistema varre os pares USDT da Bybit que
passarem num filtro de liquidez, roda análise completa por ativo (técnica + macro +
on-chain), opera micro-operações 24/7 em full-auto dentro dos guardrails, e devolve
ao usuário um **ranking diário de oportunidades por probabilidade ajustada a
risco**, com swing trade **também full-auto** (decisão #A, 16/07).

**Métrica de sucesso declarada:** expectância positiva consistente fora da amostra,
profit factor > 1,5 e max drawdown dentro do limite da camada de risco.
**Taxa de acerto bruta NÃO é meta de projeto** — ver seção 8.

## 2. Princípio de design — inegociável

Separação rígida entre quem decide direção e quem controla risco e executa.

- O **LLM (Claude) nunca cria, altera ou cancela ordem diretamente**. Ele só produz
  um sinal estruturado: `{direção, convicção 0–1, racional, nível de invalidação}`.
- Um **motor determinístico em Python** recebe esse sinal, valida contra regras de
  risco hard-coded, e só então executa via **CCXT**.
- Sinal que viola qualquer guardrail é **descartado silenciosamente** — sem
  negociação com o modelo, sem exceção manual embutida no código.
- Nenhuma ferramenta de execução (criar ordem, cancelar ordem, ajustar alavancagem,
  definir tamanho de posição) pode ser exposta ao Claude como tool-call em nenhuma
  fase. Vale para qualquer MCP, presente ou futuro.
- **Saída de posição não passa pelo veto de risco** (fechar reduz risco — mesma
  filosofia do stop e do kill switch); **entrada SEMPRE passa**.

## 3. Arquitetura (6 camadas)

**1. Ingestão de dados**
[HOJE] REST via CCXT a cada ciclo (~60s), 2 símbolos fixos (BTC, ETH — spot),
candles 15m/4h (sempre candle FECHADO), funding rate; indicadores EMA/RSI/ATR
calculados localmente, nunca pelo modelo. Dossiê diário (macro/on-chain) roda
todo dia.
[ALVO] WebSocket; universo completo de pares USDT com filtro de liquidez;
seleção diária de universo informada por macro/on-chain.

**2. Feature engineering**
[HOJE] snapshot de estado único, a MESMA estrutura no live e no backtest.
[ALVO] campos macro/on-chain reais no snapshot (estrutura pronta; falta
`decision.strategy: llm` consumir).

**3. Camada de decisão**
[HOJE] estratégia determinística (EMA20/50 + RSI + stop 1,5×ATR) como trilho de
teste — SEM edge validado (pesquisa de 16/07: pior família das 6 testadas; a
troca de estratégia é o próximo grande passo, com dados novos). A estratégia
agora TAMBÉM pode emitir saída por sinal e pedir trailing
[PRONTO-SEM-VALIDAR ao vivo, desligado por default].
[PRONTO-SEM-VALIDAR] `LLMStrategy` (Claude) com o mesmo contrato `Signal`.
[ALVO] ranking top-N por convicção ajustada a risco; scalp com LLM fora do
caminho crítico.

**4. Camada de risco — poder de veto absoluto**
[HOJE, implementado e testado]
- Risco por trade 0,5% do capital, nunca calculado pelo LLM.
- Sizing derivado da distância até o stop. **Teto de capital por trade: 20% do
  equity, CLAMPA (nunca veta)** — decisão de 17/07.
- Stop obrigatório e dinâmico (1,5×ATR). Sem stop, sem trade. Stop re-ancorado
  no preço REAL do fill (fix #26).
- Kill switch por drawdown: 3% diário / 15% total; reset SEMPRE manual; sem
  flatten (decisão #B). Ressalva: não persiste restart do processo (ver
  Status).
- Limites agregados intra-ciclo: máx. 3 posições, exposição 1× equity em spot,
  risco agregado 2%. Exclusividade por símbolo fail-closed.
- Circuit breakers: funding anômalo, feed defasado.
- Proteção nunca-nua em TODOS os caminhos que tocam o stop (entrada, TP por
  software, saída por sinal, trailing move): falha → re-arma → se falhar,
  evento crítico na trilha + intervenção manual.
[ALVO] custo de operação no sinal; correlação de portfólio; monitor de
decaimento.

**5. Execução**
[HOJE] CCXT/Bybit REST spot; ordens idempotentes; reconciliação por ciclo;
retry com backoff; erro por símbolo isolado; DRY_RUN por padrão; TP por
software em spot (sem OCO na Bybit — o stop é sempre ordem real; o alvo
lucrativo é checado por ciclo e executado a mercado); saída por sinal e
trailing stop prontos (desligados). Estado local em
`state/spot_protections.json` com backfill pela trilha e cura por consulta à
exchange quando stale.
[ALVO — requisito para 24/7 de verdade] processo supervisionado com restart
automático; alerta ativo (Telegram/e-mail).

**6. Supervisão (usuário + MCP)**
[HOJE] trilha `logs/audit.jsonl` com TODA decisão; MCP próprio
(`wonder_trader`) read-only + halt/reset por arquivo de controle. Catálogo de
eventos completo em `CLAUDE.md` (inclui os novos: `signal_exit_*`,
`trailing_stop_moved`, `trailing_exit_*`, `trade_closed` com
`reason=take_profit|stop_loss|signal_exit|trailing_stop|external_close_unconfirmed`).
[ALVO] ranking top-N + alertas ativos.

## 4. Papel do MCP — só camada 6, só leitura

| Função | Permitido |
|---|---|
| Status, posições, PnL, decisões recentes, explicar símbolo | Sim (read-only) |
| Pausar novas entradas (halt) | Sim — grava sinal em arquivo; o engine decide |
| Resetar kill switch | Sim, com `confirm=true` explícito |
| Criar/cancelar ordem, mudar alavancagem/size | **Não, nunca** |

O halt via MCP foi usado EM PRODUÇÃO em 20/07 para conter o loop de reentrada
(bug #26) — o desenho funcionou como planejado.

## 5. Checklist de segurança de chaves (antes de capital real)

1. Duas API keys separadas (read-only p/ MCP; trade sem saque p/ motor).
   [HOJE: uma chave única de testnet no `.env` — aceitável só em testnet.]
2. IP whitelist nas duas.
3. Nenhuma chave com permissão de saque — nem em testnet.
4. Chaves fora de arquivo versionado; antes de mainnet, tirar o `.env` do
   OneDrive.
5. Situação regulatória Bybit/Brasil. **Pendente — bloqueia a Fase 5.**

## 6. O que permanece sob controle humano mesmo em full-auto

1. Kill switch manual (e o reset é sempre manual).
2. Aprovação de mudança de parâmetro de risco — o sistema não reescreve os
   próprios limites; nem o LLM, nem o engine, nem agente nenhum. **Inclui as
   chaves novas `decision.deterministic.exit_on_signal`/`.trailing` — ligar é
   decisão exclusiva do Lucas.**
3. Gatilho de ir para capital real.
4. Toda ação direta na exchange (cancelar/armar ordem manualmente) — visto na
   prática em 19/07 (re-armar o stop do ETH foi ação do Lucas, nunca do agente).

## 7. Plano de fases — estado real e critério de fechamento

| Fase | Escopo | Estado | Fecha quando |
|---|---|---|---|
| 1 | Motor determinístico + risco + execução testnet, 2 símbolos | **FECHADA (19/07)** — entrada+stop+saída lucrativa automática confirmados na exchange | — (critério atendido) |
| 2 | Backtest + walk-forward com dados reais | **Executada** (15-16/07, SEM EDGE — esperado; régua validada e corrigida) | Carimbo formal do Lucas na régua |
| 2b | **Pesquisa de estratégia com dados novos** (2+ anos, regime misto, famílias de tendência com saída por sinal/trailing) | **PRÓXIMO PASSO — acordado 21/07** | Família com edge OOS verificado, ou veredito honesto de novo |
| 3 | Decisão Claude em testnet/paper | Código pronto, desligado | LLM ligado, decisões auditadas, fail-safe confirmado |
| 4 | Supervisão via MCP | **Fechada** (16/07; halt usado em produção 20/07) | — |
| 5 | Capital real, size mínimo | **Bloqueada** (regulatória) | Checklist seção 5 + paper longo (seção 8.5) + Bybit Brasil resolvida |
| 6 | Expansão (universo, ranking, 24/7, regime, decaimento) | [ALVO] | Cada item validado em testnet |

Regra de avanço inalterada: só passa de fase quando a anterior fechou.

## 8. Sobre meta de acertividade (a resposta definitiva ao "90%")

**Não se mira 90% de taxa de acerto.** O que importa é **expectância**
(`taxa de acerto × ganho médio − taxa de erro × perda média`), profit factor,
Sharpe/Sortino e max drawdown controlado. Backtest com 90%+ é sintoma de
overfitting. Cripto tem cauda gorda — sistema robusto se mede pela pior
semana. O entregável honesto é um **ranking calibrado** (probabilidade
estimada + calibração medida continuamente).

Checklist de prontidão antes de operar com confiança: walk-forward com custos
completos (falta funding/slippage por book); Monte Carlo [ALVO]; detecção de
regime [ALVO]; monitor de decaimento [ALVO]; paper cobrindo um ciclo completo
de regime; latência compatível com timeframe.

## 9. Alinhamento do sistema atual com a visão — leitura honesta

**Implementado e validado ao vivo:** separação decisão/risco/execução; ciclo
completo entrada→proteção→saída lucrativa na exchange real; stop dinâmico
re-ancorado no fill; teto de 20% por trade; kill switch (inclusive via MCP em
produção); TP por software em spot; auditoria completa com pnl honesto
(`pnl_usdt: null` quando componente desconhecido — nunca inventa número);
backtest/walk-forward sem look-ahead; MCP; dossiê diário.

**Pronto sem validar ao vivo:** saída por sinal; trailing stop; camada Claude.

**Não existe ainda:** estratégia com edge (o gargalo REAL do projeto — próximo
passo); varredura de universo; ranking; calibração; custo no sinal live;
correlação; Monte Carlo; regime; decaimento; infra 24/7; WebSocket.

## 10. Pendências e decisões em aberto

- **Pesquisa 2b (PRÓXIMA SESSÃO):** baixar 2+ anos de dados; re-testar
  donchian/ema_cross com saída por sinal/trailing em 1h/4h; 15m descartado.
- Ligar `exit_on_signal`/`trailing` no live (decisão do Lucas, idealmente
  DEPOIS da pesquisa dizer que valem a pena).
- Situação regulatória Bybit/Brasil (bloqueia Fase 5).
- Ratificar os números de risco do YAML em operação (0,5%/trade, 20%/trade
  teto, 3%/15% DD, 3 posições, 1× exposição spot).
- Kill switch não persistir restart (documentado 20/07) — corrigir quando
  tocar nesse código de novo.
- #G on-chain real-time da Bybit (decidida, não implementada, não urgente).
- Seleção diária de universo por macro/on-chain (ideia de 16/07, adiada).
- Antes de mainnet: `.env` fora do OneDrive.

---
*Referência técnica interna do projeto — não é conteúdo institucional Wonder
BOAT/WonderHUB.AI nem recomendação de investimento.*
