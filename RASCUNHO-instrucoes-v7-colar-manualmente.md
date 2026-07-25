# Projeto Auto-Trade — Instruções de Projeto (v7 — 2026-07-23)

Documento de referência para qualquer chat/agente que trabalhe neste projeto. Se um
passo proposto violar alguma regra aqui, o passo está errado — não a regra.

Convenção desta versão: **[HOJE]** = implementado e verificado no código;
**[PRONTO-SEM-VALIDAR]** = código existe (testado offline), nunca rodou ao vivo;
**[ALVO]** = escopo do produto final, ainda não construído.
**v7 herda a disciplina da v2-v6 — só atualiza os fatos, não a regra. "Status
atual" é uma FOTO (23/07, ~00:30 UTC), não uma promessa. O detalhe minuto a
minuto vive em `CLAUDE.md`, que muda mais rápido do que este documento deveria.**

## Status atual (fatos verificados em 2026-07-22/23, até ~00:30 UTC)

- **Fase 1 — FECHADA em 19/07.** Ciclo completo validado na exchange real
  (testnet spot), ponta a ponta, confirmado 1:1 contra a UI/histórico da Bybit:
  entrada a mercado + stop real + saída lucrativa automática. O robô roda ao
  vivo continuamente desde então (com um restart deliberado em 22/07 pra
  ligar o trailing stop).
- **Engenharia validada ≠ estratégia validada.** PnL positivo em dias
  individuais é encanamento funcionando + mercado favorável — NÃO é
  evidência de edge. A pesquisa formal (16/07, 21/07, 22/07 — ver abaixo)
  diz o contrário. Não escalar capital com base em PnL de curto prazo.
- **PnL realizado total: +182,04 USDT, 30 trades, win rate 33,3%** (equity
  ~10.051 USDT). Caiu de +233,95 numa sequência de stops consecutivos na
  madrugada de 22/07 — o cooldown por símbolo (fix #30) disparou de
  verdade pela primeira vez em produção nessa janela, exatamente como
  desenhado (30min no 1º acionamento do dia, 60min no 2º).
- **Dez bugs REAIS de produção achados e corrigidos ao vivo (19-22/07)**,
  a maioria via monitoramento em tempo real da trilha ou pelo watchdog
  agendado: #23-#30 (ver v6 para detalhe completo — cancel_all incompleto,
  proteção não cobria fill favorável, entry_price aproximado, stop/TP sem
  re-ancoragem, kill switch não persistia restart, saldo não reconfirmado,
  sem cooldown pós-stops); **novo em 22/07**: #31 (`trader_realized_pnl`
  mentia PnL agregado — corte por linha bruta antes de filtrar por tipo de
  evento empurrava `trade_closed` pra fora da janela; corrigido lendo o
  arquivo INTEIRO e filtrando por tipo de evento ANTES de aplicar o
  `limit`, não depois) e #32 (backtester oficial gravava — não só lia — em
  `kill_switch_state.json`/`cooldown_state.json` reais; um trip/cooldown
  SIMULADO podia sobrescrever o estado do motor ao vivo silenciosamente;
  corrigido com override por env var, mesmo padrão que `AUDIT_PATH` já
  usa — este sim isolamento por arquivo, mecanismo DIFERENTE do fix do #31).
- **Fase 2 — EXECUTADA (15/07) + três rodadas de pesquisa formal de
  estratégia (16/07, 21/07, 22/07). O fio donchian/4h está ENCERRADO.**
  Veredito 16/07 (108 combinações, 6 meses 100% bear): sem edge long-only;
  robô atual é a PIOR das 6 famílias. Veredito 21/07 (pesquisa 2b — dado
  novo, 2,25 anos, regime misto): AINDA sem edge validado em donchian nem
  ema_cross; robô atual confirmado DE NOVO pior opção, em DOIS datasets
  independentes agora. **Veredito 22/07 (painel adversarial de 9 agentes —
  6 lentes + 3 juízes — pedido explicitamente antes de qualquer decisão de
  capital): NÃO PROMOVER donchian/4h.** Os únicos 2 resultados
  "positivos" (ETH, BNB) dependiam inteiramente de um único fold
  coincidindo com o crash de 10/10/2025 caindo na MESMA janela OOS dos 5
  símbolos simultaneamente (falha de desenho: janelas de calendário não
  escalonadas por símbolo) — sem esse fold, os 5 símbolos ficam negativos,
  no mesmo patamar do robô atual. **Este fio específico está fechado.**
  Caminho registrado se alguém quiser continuar: universo de símbolos
  maior + ranking (a visão de produto original), ou redesenhar o
  walk-forward com janelas OOS dessincronizadas por símbolo. Relatórios em
  `research/`. Todos os datasets usados estão QUEIMADOS para seleção.
- **Capacidades de execução (saída por SINAL + trailing stop + paridade do
  backtester, implementadas 21/07)**: trailing **LIGADO em produção desde
  22/07** (`decision.deterministic.trailing: true`, a pedido do Lucas,
  depois da pesquisa 2b confirmar de novo que o robô atual é a pior
  família — a melhoria disponível agora é de GESTÃO DE SAÍDA, não troca de
  estratégia). `exit_on_signal` segue desligado (não foi pedido). Posições
  abertas ANTES do boot que ligou o trailing mantêm stop/TP fixo — só
  entradas novas usam trailing.
- **Restart automático do processo — FEITO em 22/07** (`supervisor.py`,
  novo arquivo na raiz — substitui `python main.py` como forma de rodar o
  motor). Religa `main.py` sozinho se ele cair por crash (Task Manager,
  falha de energia/SO), com backoff exponencial e teto de tentativas por
  janela (5 restarts/30min, senão desiste e audita
  `engine_supervisor_giveup` — crítico). NUNCA religa em parada deliberada
  (Ctrl+C chega nos dois processos ao mesmo tempo, já que compartilham
  console — o supervisor só espera `main.py` terminar sozinho, que audita
  `engine_stop` como sempre). **Em uso ao vivo desde 22/07 ~22:43 UTC.**
  Fecha a metade que faltava do item `[ALVO]` "processo supervisionado com
  restart automático + alerta ativo" — a metade "alerta" (watchdog
  agendado) já existia desde 21/07.
- **Tarefa agendada `trader-watchdog`**: roda de 30 em 30 minutos, checa
  kill switch/erros críticos, notifica só se achar problema real. Achou o
  bug #29 no 1º dia. **Atualizada em 22/07** pra reconhecer
  `engine_supervisor_giveup`/`engine_crash_restart` como eventos críticos
  (sem isso não saberia diferenciar "motor rodando bem" de "motor caiu e
  o supervisor desistiu de religar"). **Bug de permissão corrigido em
  22/07**: os comandos Bash que ela usa (contagem de eventos no
  `audit.jsonl`) ficavam pedindo aprovação manual toda execução — como
  ninguém está presente pra aprovar, o run morria sem notificar nem
  registrar nada. Causa raiz: cliques antigos de "sempre permitir" só
  geram permissão de match EXATO sobre o comando daquela vez; como o
  prompt embute um timestamp novo a cada execução, nunca generalizava.
  Corrigido com regras de PREFIXO em `~/.claude/settings.json`. Ainda sem
  confirmação num run real na hora em que este documento foi escrito.
- **Fase 3 — decisão #G implementada (22/07), camada LLM endurecida (22-23/07),
  AMBAS ainda desligadas.** `BybitDerivativesProvider` (funding rate/open
  interest/long-short ratio direto da Bybit, decisão de 18/07) construído,
  revisado adversarialmente (11 achados corrigidos — o mais grave: sem
  gate, fazia até 12 chamadas de rede reais por ciclo mesmo com a
  estratégia determinística nunca lendo o resultado) e testado —
  genuinamente inerte hoje (zero custo de rede), só ativa quando
  `decision.strategy: llm` ligar. A própria `LLMStrategy` — implementada
  há tempos mas NUNCA testada nem revisada até 22/07 — passou por revisão
  adversarial completa (6 lentes, 15 achados, os 15 confirmados) antes de
  qualquer teste ao vivo, a pedido explícito do Lucas. Achado CRÍTICO
  real: NaN em `stop_price`/`entry_price` passava por TODAS as barreiras
  (LLMStrategy E RiskManager compartilhavam o mesmo ponto cego —
  comparação Python com NaN é sempre `False`) até chegar sem guarda
  nenhuma na criação da ordem; achado ALTO: NaN em `conviction` virava
  `1.0` (confiança MÁXIMA) em vez de `FLAT`. Ambos corrigidos com
  `math.isfinite()` nos dois pontos independentes. Também corrigido:
  `entry_price` do modelo agora validado contra o preço real de mercado
  (>2% de divergência → `FLAT` — a única fronteira de confiança
  GENUINAMENTE NOVA que a Fase 3 introduz); prompt agora avisa que
  `context` é dado externo, nunca instrução (mitigação de prompt
  injection); fallback de modo de mercado desconhecido virou fail-CLOSED
  (spot) em vez de fail-aberto (perp); nome de modelo atualizado. Teste
  isolado com chamada REAL à API do Claude ficou pendente
  (`ANTHROPIC_API_KEY` ausente no `.env` — decisão do Lucas de deixar
  assim por ora).
- **Dossiê diário virou 3x/dia (22/07)**: tarefa `dossie-cripto-intraday`
  (07h/13h/19h horário local) substitui a antiga de 1x/dia. Achado
  operacional: existem dois sistemas de tarefa agendada sem visibilidade
  cruzada entre si (tarefas criadas no painel do Cowork vs. via
  `mcp__scheduled-tasks`) — ver `CLAUDE.md`, seção "Dossiê diário", pro
  detalhe completo antes de investigar isso de novo numa sessão futura.
- **Fase 4 — FECHADA** (MCP validado 16/07; kill switch persistente
  confirmado ao vivo 21/07).
- **Fase 5 — BLOQUEADA** por regulação (Bybit descontinuando derivativos
  para residentes BR; spot na entidade Bybit Brasil é o caminho — decisão
  #E). **Pendência não revisitada nesta rodada**: o bloqueio documentado é
  especificamente sobre DERIVATIVOS — ninguém voltou a checar se mainnet
  SPOT especificamente continua bloqueado ou já seria viável, desde que o
  robô migrou pra spot.
- **Suíte de testes: 246/246** (`tests/test_smoke.py` 238 + `test_ciclo.py`
  8). Regra operacional REFORÇADA: nunca rodar a suíte com o motor vivo —
  usar `CTRL_C_EVENT` real via ctypes (não `taskkill /F`) pra parar
  limpo sem acesso físico ao terminal, se precisar.

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
- **Campos vindos de fonte não confiável (resposta do LLM, contexto externo)
  nunca são tratados como confirmados sem validação numérica explícita** —
  lição do achado crítico de 22/07: NaN/±inf bypassam comparação Python
  silenciosamente; todo campo numérico de origem externa precisa de
  `math.isfinite()` (ou equivalente) antes de entrar em qualquer cálculo
  de sizing/risco.

## 3. Arquitetura (6 camadas)

**1. Ingestão de dados**
[HOJE] REST via CCXT a cada ciclo (~60s), 2 símbolos fixos (BTC, ETH — spot),
candles 15m/4h (sempre candle FECHADO), funding rate; indicadores EMA/RSI/ATR
calculados localmente, nunca pelo modelo. Dossiê macro/on-chain roda 3x/dia
(07h/13h/19h). Derivativos em tempo real (funding/open interest/long-short
ratio direto da Bybit, decisão #G) implementados e gateados por
`decision.strategy=="llm"` — zero custo de rede enquanto desligado.
[ALVO] WebSocket; universo completo de pares USDT com filtro de liquidez;
seleção diária de universo informada por macro/on-chain.

**2. Feature engineering**
[HOJE] snapshot de estado único, a MESMA estrutura no live e no backtest.
[ALVO] campos macro/on-chain/derivativos consumidos de fato pela decisão
(estrutura pronta; falta `decision.strategy: llm` ligar).

**3. Camada de decisão**
[HOJE] estratégia determinística (EMA20/50 + RSI + stop 1,5×ATR, trailing
LIGADO desde 22/07) como trilho de teste — SEM edge validado em TRÊS
rodadas de pesquisa independentes; é consistentemente a PIOR família
testada, mas a única com trailing stop em produção agora.
[PRONTO-SEM-VALIDAR, endurecida 22/07] `LLMStrategy` (Claude) com o mesmo
contrato `Signal` — revisada adversarialmente (15 achados corrigidos,
incluindo 1 crítico de NaN), zero teste com API real ainda
(`ANTHROPIC_API_KEY` ausente).
[ALVO] ranking top-N por convicção ajustada a risco; scalp com LLM fora do
caminho crítico.

**4. Camada de risco — poder de veto absoluto**
[HOJE, implementado e testado]
- Risco por trade 0,5% do capital, nunca calculado pelo LLM.
- Sizing derivado da distância até o stop. Teto de capital por trade: 20%
  do equity, CLAMPA (nunca veta).
- Stop obrigatório e dinâmico (1,5×ATR ou trailing). Sem stop, sem trade.
  Stop re-ancorado no preço REAL do fill.
- Kill switch por drawdown: 3% diário / 15% total; reset SEMPRE manual; sem
  flatten. Persiste em disco através de restarts.
- Cooldown por símbolo após stops consecutivos: 2 stops seguidos pausa
  entradas NOVAS nesse símbolo por 30min (60min do 2º acionamento em
  diante no mesmo dia). **Disparou de verdade em produção pela primeira
  vez em 22/07** (3 acionamentos numa madrugada, incl. escalonamento
  30→60min confirmado ao vivo).
- **Guard de NaN/±inf independente (novo, 22/07)**: qualquer campo
  numérico do sinal (`entry_price`/`stop_price`/`take_profit`) não-finito
  é vetado aqui, sem depender de quem gerou o sinal já ter filtrado —
  defesa em profundidade real, não só declarada.
- Limites agregados intra-ciclo: máx. 3 posições, exposição 1× equity em spot,
  risco agregado 2%. Exclusividade por símbolo fail-closed.
- Circuit breakers: funding anômalo, feed defasado.
- Proteção nunca-nua em TODOS os caminhos que tocam o stop: falha → re-arma
  → se falhar, evento crítico na trilha + intervenção manual. Reconfirma
  saldo real na exchange antes de declarar posição sem proteção.
[ALVO] custo de operação no sinal; correlação de portfólio; monitor de
decaimento.

**5. Execução**
[HOJE] CCXT/Bybit REST spot; ordens idempotentes; reconciliação por ciclo;
retry com backoff; erro por símbolo isolado; DRY_RUN por padrão; TP por
software em spot; saída por sinal pronta (desligada); trailing stop LIGADO
em produção. Estado local em `state/spot_protections.json` com backfill
pela trilha e cura por consulta à exchange quando stale. **Processo
supervisionado com restart automático (`supervisor.py`, novo 22/07) — em
uso ao vivo.**
[HOJE] alerta ativo via tarefa agendada `trader-watchdog` (`PushNotification`)
— agora também reconhece crash/giveup do supervisor como crítico.

**6. Supervisão (usuário + MCP)**
[HOJE] trilha `logs/audit.jsonl` com TODA decisão; MCP próprio
(`wonder_trader`) read-only + halt/reset por arquivo de controle. Catálogo
de eventos completo em `CLAUDE.md` (inclui `signal_exit_*`,
`trailing_stop_moved`, `trailing_exit_*`, `cooldown_triggered`,
`engine_crash_restart`, `engine_supervisor_giveup`, `trade_closed` com
`reason=take_profit|stop_loss|signal_exit|trailing_stop|external_close_unconfirmed`).
[ALVO] ranking top-N + confirmação de swing (decidido: autônomo, sem
portão).

## 4. Papel do MCP — só camada 6, só leitura

| Função | Permitido |
|---|---|
| Status, posições, PnL, decisões recentes, explicar símbolo | Sim (read-only) |
| Pausar novas entradas (halt) | Sim — grava sinal em arquivo; o engine decide |
| Resetar kill switch | Sim, com `confirm=true` explícito |
| Criar/cancelar ordem, mudar alavancagem/size | **Não, nunca** |

`trader_realized_pnl`/`trader_recent_decisions` estavam com um bug real
(#31, corrigido 22/07) — cortavam pelas últimas N linhas BRUTAS do
`audit.jsonl` antes de filtrar por tipo de evento, o que empurrava
`trade_closed` (raro) pra fora da janela sempre que houvesse ruído
repetitivo suficiente entre eles. Corrigido: filtra por tipo primeiro,
corta depois.

## 5. Checklist de segurança de chaves (antes de capital real)

1. Duas API keys separadas (read-only p/ MCP; trade sem saque p/ motor).
   [HOJE: uma chave única de testnet no `.env` — aceitável só em testnet.]
2. IP whitelist nas duas.
3. Nenhuma chave com permissão de saque — nem em testnet.
4. Chaves fora de arquivo versionado; antes de mainnet, tirar o `.env` do
   OneDrive.
5. Situação regulatória Bybit/Brasil. **Pendente — bloqueia a Fase 5**
   (mas ver ressalva acima: talvez só bloqueie derivativos, não spot —
   não confirmado).

## 6. O que permanece sob controle humano mesmo em full-auto

1. Kill switch manual (e o reset é sempre manual).
2. Aprovação de mudança de parâmetro de risco — o sistema não reescreve os
   próprios limites; nem o LLM, nem o engine, nem agente nenhum. Inclui
   `decision.strategy` (deterministic↔llm), `decision.deterministic.*`,
   `decision.llm.*` e `cooldown.*` — mudar é decisão exclusiva do Lucas.
3. Gatilho de ir para capital real.
4. Toda ação direta na exchange (cancelar/armar ordem manualmente).
5. Trocar o processo de `main.py` direto para `supervisor.py` (ou
   vice-versa) — decisão operacional do Lucas, não automática.

## 7. Plano de fases — estado real e critério de fechamento

| Fase | Escopo | Estado | Fecha quando |
|---|---|---|---|
| 1 | Motor determinístico + risco + execução testnet, 2 símbolos | **FECHADA (19/07)** | — (critério atendido) |
| 2 | Backtest + walk-forward com dados reais | **Executada** (15-16/07, SEM EDGE — esperado; régua validada e corrigida) | Carimbo formal do Lucas na régua |
| 2b | Pesquisa de estratégia com dados novos + verificação adversarial (donchian/ema_cross) | **ENCERRADA (22/07) — veredito unânime NÃO PROMOVER**; robô atual confirmado pior opção em 2 datasets independentes | Fio fechado; retomar exigiria universo maior ou WF redesenhado |
| 3 | Decisão Claude em testnet/paper | Código pronto e ENDURECIDO (22/07, 15 achados corrigidos), desligado; teste com API real pendente | LLM ligado, decisões auditadas, fail-safe confirmado AO VIVO (hoje só testado offline) |
| 4 | Supervisão via MCP | **Fechada** (16/07; kill switch persiste restart) | — |
| 5 | Capital real, size mínimo | **Bloqueada** (regulatória — só derivativos confirmado, spot não revisitado) | Checklist seção 5 + paper cobrindo um ciclo completo de regime (checklist da seção 8) + Bybit Brasil resolvida |
| 6 | Expansão (universo, ranking, 24/7, regime, decaimento) | [ALVO] — alerta ativo + restart automático FEITOS (22/07); resto não iniciado | Cada item validado em testnet |

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
re-ancorado no fill; trailing stop em produção; teto de 20% por trade; kill
switch persistente através de restarts; cooldown por símbolo (disparou de
verdade em 22/07); TP por software em spot; auditoria completa com pnl
honesto; backtest/walk-forward sem look-ahead; MCP; dossiê 3x/dia; watchdog
agendado com alerta ativo (achou bugs reais); **restart automático do
processo (supervisor.py, em uso ao vivo)**.

**Pronto sem validar ao vivo:** saída por sinal; camada Claude (endurecida,
mas zero chamada real à API ainda — falta `ANTHROPIC_API_KEY`); decisão #G
(derivativos em tempo real — código pronto e testado, inerte até Fase 3
ligar).

**Não existe ainda:** estratégia com edge (o gargalo REAL do projeto,
confirmado em TRÊS rodadas de pesquisa independentes agora); varredura de
universo; ranking; calibração; custo no sinal live; correlação; Monte
Carlo; regime; decaimento; WebSocket.

## 10. Pendências e decisões em aberto

- **Estratégia sem edge (3 rodadas de pesquisa independentes agora, fio
  donchian/4h ENCERRADO)**: quem quiser continuar, os 3 juízes do painel
  de 22/07 recomendam universo de símbolos maior + ranking (visão de
  produto original) ou walk-forward com janelas OOS dessincronizadas por
  símbolo — não donchian/4h neste universo de 5 símbolos, já refutado.
- Ligar `exit_on_signal` no live (trailing já ligado) — decisão do Lucas,
  sem edge validado ainda, não é urgente.
- Ligar `decision.strategy: llm` — código pronto e endurecido, mas nunca
  testado com API real (falta `ANTHROPIC_API_KEY` no `.env`) nem ao vivo.
  Decisão do Lucas, sem pressa.
- **Revisitar se o bloqueio regulatório da Fase 5 é só sobre derivativos**
  — desde a migração pra spot (#E), ninguém confirmou se mainnet SPOT
  especificamente continua bloqueado pra residente BR.
- Confirmar num run real que o fix de permissão do `trader-watchdog`
  (22/07) realmente eliminou os prompts de aprovação manual.
- Situação regulatória Bybit/Brasil (bloqueia Fase 5, ver ressalva acima).
- Ratificar os números de risco do YAML em operação.
- Seleção diária de universo por macro/on-chain (ideia de 16/07, adiada).
- Antes de mainnet: `.env` fora do OneDrive.

---
*Referência técnica interna do projeto — não é conteúdo institucional Wonder
BOAT/WonderHUB.AI nem recomendação de investimento.*
