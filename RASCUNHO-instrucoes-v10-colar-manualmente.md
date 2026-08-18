# Projeto Auto-Trade — Instruções de Projeto (v10 — 2026-07-30)

Documento de referência para qualquer chat/agente que trabalhe neste projeto. Se um
passo proposto violar alguma regra aqui, o passo está errado — não a regra.

Convenção desta versão: **[HOJE]** = implementado e verificado no código;
**[PRONTO-SEM-VALIDAR]** = código existe (testado offline), nunca rodou ao vivo;
**[ALVO]** = escopo do produto final, ainda não construído.
**v10 herda a disciplina da v2-v9 — só atualiza os fatos, não a regra. "Status
atual" é uma FOTO (30/07, madrugada UTC), não uma promessa. O detalhe minuto a
minuto vive em `CLAUDE.md`, que muda mais rápido do que este documento deveria.
Substitui a v9, que nunca chegou a ser colada nas instruções do Claude Project
(mesmo padrão da v6→v7 e v8→v9).**

## Status atual (fatos verificados até 2026-07-30, madrugada UTC)

- **Perp (long + short) validado ao vivo PONTA A PONTA pela primeira vez,
  nos dois lados, com dinheiro real.** Religado em 28/07/2026 (decisão do
  Lucas, teto de alavancagem 2x e teto de capital 50%/trade); nesta sessão
  (29-30/07) o ciclo completo — entrada, trailing stop real, fechamento
  auditado, cooldown por símbolo — foi confirmado funcionando em LONG
  (fechamento 03:55:59 UTC) e, pela primeira vez, em **SHORT** (entrada
  04:56:23, trailing moveu 5 vezes de verdade acompanhando o preço a
  favor, fechamento 01:33:02 UTC de 30/07 pelo próprio stop já trailed —
  PnL bem menor do que seria no stop original, prova de que o mecanismo
  funciona). PnL/side corretamente invertidos pro lado short (bug #49 da
  sessão anterior, sem validação ao vivo até agora).
- **Cooldown por símbolo: os 3 níveis de escalada confirmados no MESMO dia
  pela primeira vez.** 1º stop do dia (ETH/USDT:USDT) → 30min; 2º → 60min;
  3º → **24h** (nunca tinha acontecido um 3º stop no mesmo dia até agora).
  Reset manual (`trader_reset_cooldown`) também usado de verdade pela
  primeira vez — liberou o símbolo ~8h antes do prazo natural, motor
  aprovou entrada nova 3 segundos depois no ciclo seguinte.
- **Suíte de testes: 299/299 `test_smoke.py` + 8/8 `test_ciclo.py` =
  307/307.** A seção 31 (trailing em perp, escrita na sessão anterior)
  finalmente foi executada — achou 2 falhas, mas eram bug no FIXTURE de
  teste (`FakePerpExit.fetch_order` lendo o atributo da classe-base em vez
  da subclasse), não no motor. Corrigido; suíte 100% verde confirmada.
- **Dois commits feitos e enviados pro GitHub** (`wonderboat-ai/bybit-auto-trader`,
  branch `main`): o fix do fixture de teste, e o pacote de mudanças da
  sessão anterior (religar perp, teto de risco, fechamento auditado,
  trailing real — bugs #48/#49). PC2 pode atualizar via `git pull` (motor
  parado lá primeiro).
- **Lição operacional nova, registrada pra não se repetir**: rodar
  `supervisor.py --live` (ou `main.py`) usando `python` puro (sem o
  caminho completo do venv) DEPOIS de `.venv\Scripts\activate` PODE
  resolver pro Python de sistema (sem as dependências do projeto) — causou
  um crash-loop real de 6 tentativas até o supervisor desistir sozinho
  (`ModuleNotFoundError: No module named 'yaml'`). Não é bug de código
  (confirmado rodando `main.py --once` direto, funcionou). Sempre usar o
  caminho completo, `.venv\Scripts\python.exe`.
- **Trailing + take-profit fixo convivendo** (decisão de 28/07) segue sem
  mudança de comportamento — ver v9/`CLAUDE.md` pro histórico da mudança.
- **Incidente de compliance da Bybit (bloqueio no rearme do trailing em
  SPOT, retCode 10024) não é mais o caminho ativo** — o mercado voltou a
  ser `perp` em 28/07, e o trailing em perp usa um mecanismo diferente
  (cancela+recria a ordem real de stop, não um `tpslOrder` de spot); nesta
  sessão o trailing moveu 5 vezes seguidas sem nenhum bloqueio. O
  incidente original fica registrado como histórico (relevante só se spot
  voltar a ser usado), não como pendência ativa.

## 1. Objetivo do projeto

Sistema de decisão assistida por IA com execução automatizada e supervisão humana,
para day trade + swing trade de cripto na Bybit. Full-auto com guardrails. Começou
em testnet; migrou para capital real (mainnet spot) em 27/07/2026 e religou
derivativos (perp, long+short) em 28/07/2026 — decisões explícitas do Lucas, ambas
confirmadas ao vivo com dinheiro real (spot: 28/07; perp long+short ponta a ponta:
29-30/07). Ver "Status atual" e `CLAUDE.md` pro relato completo de cada virada.

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
- **Campos vindos de fonte não confiável (resposta do LLM, contexto externo)
  nunca são tratados como confirmados sem validação numérica explícita** —
  todo campo numérico de origem externa precisa de `math.isfinite()` (ou
  equivalente) antes de entrar em qualquer cálculo de sizing/risco.

## 3. Arquitetura (6 camadas)

**1. Ingestão de dados**
[HOJE] REST via CCXT a cada ciclo (~60s), 2 símbolos fixos (BTC, ETH — perp,
long+short), candles 15m/4h (sempre candle FECHADO), funding rate; indicadores
EMA/RSI/ATR calculados localmente, nunca pelo modelo. Dossiê macro/on-chain roda
3x/dia (07h/13h/19h). Derivativos em tempo real (funding/open interest/long-short
ratio direto da Bybit, decisão #G) implementados e gateados por
`decision.strategy=="llm"` — zero custo de rede enquanto desligado.
[ALVO] WebSocket; universo completo de pares USDT com filtro de liquidez;
seleção diária de universo informada por macro/on-chain.

**2. Feature engineering**
[HOJE] snapshot de estado único, a MESMA estrutura no live e no backtest.
[ALVO] campos macro/on-chain/derivativos consumidos de fato pela decisão
(estrutura pronta; falta `decision.strategy: llm` ligar).

**3. Camada de decisão**
[HOJE] estratégia determinística (EMA20/50 + RSI + stop 1,5×ATR) como trilho
de teste — SEM edge validado em TRÊS rodadas de pesquisa independentes; é
consistentemente a PIOR família testada. Trailing stop e take-profit fixo
(`tp_rr`) CONVIVEM na mesma posição desde 28/07 — sai pelo que disparar
primeiro. Cooldown de 3 níveis por símbolo em produção, **os 3 níveis
(30min/60min/24h) já confirmados ao vivo no mesmo dia (29-30/07)**.
[PRONTO-SEM-VALIDAR] `LLMStrategy` (Claude) com o mesmo contrato `Signal` —
revisada adversarialmente, zero teste com API real ainda (`ANTHROPIC_API_KEY`
ausente, e há um bug de `temperature` a corrigir antes — ver `CLAUDE.md`).
[ALVO] ranking top-N por convicção ajustada a risco; scalp com LLM fora do
caminho crítico.

**4. Camada de risco — poder de veto absoluto**
[HOJE, implementado e testado]
- Risco por trade 0,5% do capital, nunca calculado pelo LLM.
- Sizing derivado da distância até o stop. Teto de capital por trade
  INDIVIDUAL: **50% do equity** (decisão do Lucas, 28/07/2026 — "equity
  50% pra cada BTC e ETH"; é teto por-trade, não reserva rígida por
  símbolo), CLAMPA (nunca veta).
- Alavancagem: teto de **2x** (decisão do Lucas, 28/07/2026) — o cálculo é
  `min(max_leverage, necessária pelo notional/equity)`, nunca um valor
  forçado.
- Stop obrigatório e dinâmico (1,5×ATR, sobe/desce com trailing). Sem stop,
  sem trade. Stop re-ancorado no preço REAL do fill.
- **Take-profit fixo (`tp_rr`, default 2,0×distância do stop) calculado
  SEMPRE, com ou sem trailing** (fix de 28/07) — antes só existia quando
  trailing estava desligado.
- Kill switch por drawdown: 3% diário / 15% total; reset SEMPRE manual; sem
  flatten. Persiste em disco através de restarts.
- **Cooldown por símbolo, 3 níveis, confirmado ao vivo nos 3 níveis no
  mesmo dia (29-30/07)**: 1 stop ISOLADO já pausa entradas NOVAS nesse
  símbolo — 30min no 1º acionamento do dia, 60min no 2º, 24h no 3º em
  diante (auto-libera no prazo, ou reset manual deliberado antes via MCP
  `trader_reset_cooldown` — usado de verdade pela primeira vez em 29/07).
  Take-profit no meio quebra a sequência de stops.
- **Guard de NaN/±inf independente**: qualquer campo numérico do sinal
  não-finito é vetado aqui, sem depender de quem gerou o sinal já ter
  filtrado — defesa em profundidade real, não só declarada.
- Limites agregados intra-ciclo: máx. 3 posições, exposição 1× equity,
  risco agregado 2%. Exclusividade por símbolo fail-closed.
- Circuit breakers: funding anômalo, feed defasado.
- Proteção nunca-nua em TODOS os caminhos que tocam o stop: falha → re-arma
  → se falhar, evento crítico na trilha + intervenção manual. Reconfirma
  saldo real na exchange antes de declarar posição sem proteção. Em perp,
  fechamento (stop OU take-profit) sempre auditado com fill real
  (`fetch_order`), a ordem irmã órfã é cancelada só quando confirma qual
  disparou (bug #49).
[ALVO] custo de operação no sinal; correlação de portfólio; monitor de
decaimento.

**5. Execução**
[HOJE] CCXT/Bybit REST perp (long+short); ordens idempotentes; reconciliação
por ciclo; retry com backoff (incl. re-sincronização de relógio em
`InvalidNonce`, bug #48); erro por símbolo isolado; DRY_RUN por padrão;
trailing stop real em perp (cancela+recria a ordem de stop na exchange,
**confirmado movendo 5 vezes seguidas ao vivo numa posição short real**);
saída por sinal pronta (desligada, spot-only). Estado local em
`state/spot_protections.json` (`tp_id`/`side` desde 28/07) — isolado por
AMBIENTE, com backfill pela trilha e cura por consulta à exchange quando
stale. Processo supervisionado com restart automático (`supervisor.py`) —
em uso ao vivo; **sempre invocar com o caminho completo do venv
(`.venv\Scripts\python.exe`), nunca `python` puro** (ver "Status atual"
pra o incidente que isso causou).
[HOJE] alerta ativo via tarefa agendada `trader-watchdog` (`PushNotification`)
— reconhece crash/giveup do supervisor como crítico.

**6. Supervisão (usuário + MCP)**
[HOJE] trilha `logs/audit.jsonl` com TODA decisão (histórico de testnet
arquivado à parte desde 27/07); MCP próprio (`wonder_trader`) read-only +
halt/reset por arquivo de controle, com `trader_cooldown_status`/
`trader_reset_cooldown` (reset usado de verdade em 29/07). Catálogo de
eventos completo em `CLAUDE.md` (inclui `signal_exit_*`, `trailing_stop_moved`,
`trailing_exit_*`, `cooldown_triggered`, `cooldown_reset`,
`engine_crash_restart`, `engine_supervisor_giveup`, `trade_closed`,
`audit_maintenance`).
[ALVO] ranking top-N + confirmação de swing (decidido: autônomo, sem
portão).

## 4. Papel do MCP — só camada 6, só leitura

| Função | Permitido |
|---|---|
| Status, posições, PnL, decisões recentes, explicar símbolo | Sim (read-only) |
| Status/reset de cooldown por símbolo | Sim — status é leitura; reset exige `confirm=true` (usado ao vivo em 29/07) |
| Pausar novas entradas (halt) | Sim — grava sinal em arquivo; o engine decide |
| Resetar kill switch | Sim, com `confirm=true` explícito |
| Criar/cancelar ordem, mudar alavancagem/size | **Não, nunca** |

`trader_realized_pnl`/`trader_recent_decisions` tiveram um bug real (#31,
corrigido 22/07) — cortavam pelas últimas N linhas BRUTAS do
`audit.jsonl` antes de filtrar por tipo de evento. Corrigido: filtra por
tipo primeiro, corta depois. **Limitação real e não-corrigida (spot):**
`unrealized_pnl`/`entry_price` sempre vêm `0` do MCP em posições spot — a
Bybit não rastreia PnL de holdings spot (só de posições de derivativos). Em
**perp**, o MCP já traz `unrealized_pnl`/`entry_price`/`leverage` corretos
direto da posição real (confirmado ao vivo nesta sessão).

## 5. Checklist de segurança de chaves

1. Duas API keys separadas (read-only p/ MCP; trade sem saque p/ motor).
   [HOJE: uma chave única por ambiente no `.env` — mainnet e testnet
   usam chaves distintas, mas cada uma sem separação leitura/trade.]
2. IP whitelist nas duas.
3. Nenhuma chave com permissão de saque — nem em testnet, nem em mainnet.
4. Chaves fora de arquivo versionado. **Pendência real, aceita
   conscientemente**: `.env` continua dentro do OneDrive mesmo em mainnet —
   risco aceito pra viabilizar a virada de 27/07/2026, não um esquecimento.
5. Situação regulatória Bybit/Brasil. **Resolvida na prática**: spot
   confirmado liberado pra mainnet (27/07/2026); derivativos/perp também
   religados e confirmados funcionando ao vivo, long e short (28-30/07/2026)
   — o bloqueio de 15/07 não se repetiu.

## 6. O que permanece sob controle humano mesmo em full-auto

1. Kill switch manual (e o reset é sempre manual).
2. Aprovação de mudança de parâmetro de risco — o sistema não reescreve os
   próprios limites; nem o LLM, nem o engine, nem agente nenhum. Inclui
   `decision.strategy` (deterministic↔llm), `decision.deterministic.*`,
   `decision.llm.*`, `market.type`, `per_trade.max_leverage`,
   `per_trade.max_notional_pct_equity` e `cooldown.*` — mudar é decisão
   exclusiva do Lucas.
3. Gatilho de ir para capital real — já disparado em 27/07/2026 (spot) e
   28/07/2026 (perp).
4. Toda ação direta na exchange (cancelar/armar ordem manualmente).
5. Trocar o processo de `main.py` direto para `supervisor.py` (ou
   vice-versa), e disparar cada `--live` — decisão operacional do Lucas,
   nunca automática, mesmo já tendo rodado antes. **Sempre com o caminho
   completo do interpretador do venv** (ver "Status atual").
6. Reset manual de cooldown por símbolo antes do prazo natural — ação
   deliberada, exige `confirm=true`, mesma filosofia do reset do kill switch.
7. Disparar `--live` em loop contínuo (nunca disparado sozinho pelo agente
   — "executar operação financeira" exige pedido explícito do Lucas a cada
   vez, mesmo já tendo rodado antes).

## 7. Plano de fases — estado real e critério de fechamento

| Fase | Escopo | Estado | Fecha quando |
|---|---|---|---|
| 1 | Motor determinístico + risco + execução testnet, 2 símbolos | **FECHADA (19/07)** | — (critério atendido) |
| 2 | Backtest + walk-forward com dados reais | **Executada** (15-16/07, SEM EDGE — esperado; régua validada e corrigida) | Carimbo formal do Lucas na régua |
| 2b | Pesquisa de estratégia com dados novos + verificação adversarial (donchian/ema_cross) | **ENCERRADA (22/07) — veredito unânime NÃO PROMOVER** | Fio fechado; retomar exigiria universo maior ou WF redesenhado |
| 3 | Decisão Claude em testnet/paper | Código pronto e endurecido, desligado; teste com API real pendente | LLM ligado, decisões auditadas, fail-safe confirmado AO VIVO |
| 4 | Supervisão via MCP | **Fechada** (16/07; kill switch persiste restart; cooldown status/reset, usado ao vivo em 29/07) | — |
| 5 | Capital real, size mínimo | **CICLO COMPLETO VALIDADO (29-30/07/2026)** — spot ao vivo desde 27/07, perp (long+short) religado 28/07 e validado ponta a ponta (entrada→trailing→fechamento→cooldown) nos dois lados | Operação estável por período relevante (spot: sim; perp: ~7h contínuas confirmadas, seguir acompanhando) |
| 6 | Expansão (universo, ranking, 24/7, regime, decaimento) | [ALVO] — alerta ativo + restart automático FEITOS; resto não iniciado | Cada item validado em testnet |

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
completo entrada→proteção→saída lucrativa na exchange real (testnet e
mainnet spot); primeiro trade real em MAINNET (28/07/2026); **ciclo completo
em PERP, long E short, com dinheiro real (29-30/07/2026)**: entrada,
trailing stop real (moveu repetidamente), fechamento auditado com PnL
correto, cooldown 3 níveis escalando no mesmo dia, reset manual de
cooldown; stop dinâmico re-ancorado no fill; trailing stop e take-profit
fixo convivendo na mesma posição; teto de alavancagem 2x e capital 50%/
trade; kill switch persistente através de restarts; TP por software em
spot; auditoria completa com pnl honesto (isolamento por ambiente do
estado de proteção de posição); backtest/walk-forward sem look-ahead; MCP;
dossiê 3x/dia; watchdog agendado com alerta ativo; restart automático do
processo.

**Pronto sem validar ao vivo:** saída por sinal; camada Claude (endurecida,
zero chamada real à API ainda); decisão #G (derivativos em tempo real —
inerte até Fase 3 ligar).

**Não existe ainda:** estratégia com edge (o gargalo REAL do projeto,
confirmado em TRÊS rodadas de pesquisa independentes); varredura de
universo; ranking; calibração; custo no sinal live; correlação; Monte
Carlo; regime; decaimento; WebSocket.

## 10. Pendências e decisões em aberto

- **Estratégia sem edge (fio donchian/4h ENCERRADO)**: quem quiser
  continuar, recomendação é universo de símbolos maior + ranking (visão de
  produto original) ou walk-forward com janelas OOS dessincronizadas.
- Ligar `exit_on_signal` no live (trailing já ligado) — decisão do Lucas,
  sem edge validado ainda, não é urgente.
- Ligar `decision.strategy: llm` — código pronto e endurecido, mas precisa
  primeiro (a) `ANTHROPIC_API_KEY` no `.env` e (b) remover o parâmetro
  `temperature` da chamada (Sonnet 5 rejeita valor não-padrão com erro
  400). Decisão do Lucas, sem pressa.
- **Reavaliar os números de risco do YAML agora que há operação real nos
  dois lados** (cooldown 30/60/1440min, teto de capital 50%, alavancagem
  2x) — decisões tomadas com pouca operação real acumulada; agora já há
  base (long+short, cooldown nos 3 níveis) pra reavaliar se ainda fazem
  sentido. Decisão exclusiva do Lucas.
- BTC/USDT perp segue sem conseguir entrar por causa do notional mínimo da
  Bybit (~0,001 BTC) vs. o teto de capital atual — decisão de capital, não
  bug; reavaliar junto com o item acima se o Lucas quiser destravar.
- Seleção diária de universo por macro/on-chain (ideia de 16/07, adiada).
- **Pendência real, não resolvida**: `.env` continua dentro do OneDrive —
  risco aceito conscientemente. Revisitar se/quando fizer sentido tirar os
  segredos de mainnet do caminho sincronizado.
- **Lição operacional a reforçar em qualquer guia futuro**: sempre
  religar com o caminho COMPLETO do interpretador do venv
  (`.venv\Scripts\python.exe supervisor.py --live`), nunca `python` puro
  mesmo após `.venv\Scripts\activate` — causou um crash-loop real em
  29/07 (ver "Status atual").

---
*Referência técnica interna do projeto — não é conteúdo institucional Wonder
BOAT/WonderHUB.AI nem recomendação de investimento.*
