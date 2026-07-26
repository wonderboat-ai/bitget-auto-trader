# Projeto Auto-Trade — Instruções de Projeto (v8 — 2026-07-26)

Documento de referência para qualquer chat/agente que trabalhe neste projeto. Se um
passo proposto violar alguma regra aqui, o passo está errado — não a regra.

Convenção desta versão: **[HOJE]** = implementado e verificado no código;
**[PRONTO-SEM-VALIDAR]** = código existe (testado offline), nunca rodou ao vivo;
**[ALVO]** = escopo do produto final, ainda não construído.
**v8 herda a disciplina da v2-v7 — só atualiza os fatos, não a regra. "Status
atual" é uma FOTO (26/07, ~20h UTC), não uma promessa. O detalhe minuto a
minuto vive em `CLAUDE.md`, que muda mais rápido do que este documento deveria.**

## Status atual (fatos verificados até 2026-07-26, ~20h UTC)

- **Fase 1 — FECHADA em 19/07.** Ciclo completo validado na exchange real
  (testnet spot), ponta a ponta: entrada a mercado + stop real + saída
  lucrativa automática. O robô roda ao vivo continuamente desde então (com
  restarts deliberados pra ligar features novas — trailing em 22/07,
  cooldown endurecido em 25-26/07).
- **Engenharia validada ≠ estratégia validada.** PnL positivo em dias
  individuais é encanamento funcionando + mercado favorável — NÃO é
  evidência de edge. A pesquisa formal (16/07, 21/07, 22/07) diz o
  contrário. Não escalar capital com base em PnL de curto prazo.
- **Cooldown por símbolo ENDURECIDO pra 3 níveis + reset manual (25-26/07,
  a pedido do Lucas).** Antes exigia 2 stops SEGUIDOS pra pausar qualquer
  entrada nova no símbolo; agora **1 stop isolado já pausa** — motivo:
  Lucas viu o robô tomar 1 stop e reentrar comprado quase na hora e
  questionou se não valeria "acalmar" antes, pergunta reforçada pelo
  próprio veredito de pesquisa (a estratégia atual é a PIOR família
  testada em 3 rodadas independentes). Escalada por dia (UTC), por
  símbolo: 1º stop → 30min; 2º → 60min; **3º em diante → 24h** (nova
  chave `cooldown_minutes_max` no YAML) — a pausa de 24h auto-libera
  sozinha no prazo, ou pode ser liberada antes por pedido manual
  deliberado (`RiskManager.reset_cooldown`/MCP `trader_reset_cooldown`,
  nunca automático — mesma filosofia do reset do kill switch). Dois MCP
  tools novos: `trader_cooldown_status` (leitura) e `trader_reset_cooldown`
  (ação, exige `confirm=true`). **Confirmado ao vivo no mesmo dia**: 1
  stop isolado disparando cooldown, e a escalada 30→60min, ambos
  observados em produção horas depois de ligar a feature.
- **Incidente operacional (26/07), JÁ RESOLVIDO: crash-loop do supervisor
  investigado e explicado — não era bug de código.** Um processo de
  diagnóstico avulso (`main.py --live` fora do `supervisor.py`, subido
  numa sessão de troubleshooting de um erro de rede intermitente da
  testnet) ficou órfão depois de duas tentativas de parada limpa
  falharem sem isso ser percebido na hora. Toda tentativa seguinte do
  `supervisor.py` de subir um `main.py` novo colidia com esse órfão
  (disputa pelos mesmos arquivos de estado em `state/*.json`,
  sincronizados via OneDrive) e morria quase instantaneamente — 6
  `engine_crash_restart` até o supervisor desistir
  (`engine_supervisor_giveup`). Rodar `main.py`/`supervisor.py` isolados
  funcionou perfeitamente em todos os testes — não é bug. Resolvido
  derrubando o processo órfão à força. **Lição registrada em `CLAUDE.md`**:
  sempre confirmar que um processo de diagnóstico avulso morreu de
  verdade (checar o processo, não só assumir que o Ctrl+C remoto
  funcionou) antes de seguir em frente.
- **PnL realizado total: +140,94 USDT, 35 trades, win rate ~31%** (equity
  ~9.900-9.980 USDT, oscilando). Trajetória segue a mesma leitura de
  sempre: engenharia funcionando, mercado/estratégia sem edge comprovado.
- **Fase 2 — EXECUTADA + três rodadas de pesquisa formal de estratégia
  (16/07, 21/07, 22/07). O fio donchian/4h está ENCERRADO** (sem mudança
  desde a v7 — ver lá ou `CLAUDE.md` pro histórico completo). Robô atual
  confirmado a PIOR família testada em todos os datasets.
- **Restart automático do processo (`supervisor.py`) e watchdog agendado
  (`trader-watchdog`, 30 em 30 min)** seguem em uso — sem mudança de
  comportamento desde a v7, além do incidente acima já descrito (que foi
  causa externa ao supervisor, não um bug nele).
- **Fase 3 — decisão #G + camada LLM endurecida, AMBAS ainda desligadas**
  (sem mudança desde a v7). Achado novo nesta sessão, fora do escopo da
  pergunta de custo mas relevante antes de ligar: o código atual passa
  `temperature` explícito pro Claude junto com `model="claude-sonnet-5"` —
  a API atual rejeita parâmetro de amostragem não-padrão em Sonnet 5 com
  erro 400. Precisa remover essa linha antes de qualquer teste real com
  `ANTHROPIC_API_KEY` (que continua ausente do `.env`, decisão do Lucas).
- **Suíte de testes: 252/252** (`tests/test_smoke.py` 244 + `test_ciclo.py`
  8 — cresceu de 246 com 18 checks novos do cooldown de 3 níveis + reset
  manual). Regra operacional mantida: nunca rodar a suíte com o motor
  vivo; usar `CTRL_C_EVENT` real via ctypes pra parar limpo.
- Demais itens (Fase 4/5, dossiê 3x/dia, achados operacionais de tarefa
  agendada) sem mudança desde a v7 — ver lá ou `CLAUDE.md`.

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
  todo campo numérico de origem externa precisa de `math.isfinite()` (ou
  equivalente) antes de entrar em qualquer cálculo de sizing/risco.

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
testada, mas a única com trailing stop + cooldown de 3 níveis em produção.
[PRONTO-SEM-VALIDAR] `LLMStrategy` (Claude) com o mesmo contrato `Signal` —
revisada adversarialmente, zero teste com API real ainda (`ANTHROPIC_API_KEY`
ausente, e há um bug de `temperature` a corrigir antes — ver Status atual).
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
- **Cooldown por símbolo, 3 níveis (endurecido 25-26/07)**: 1 stop ISOLADO
  já pausa entradas NOVAS nesse símbolo — 30min no 1º acionamento do dia,
  60min no 2º, **24h no 3º em diante** (auto-libera no prazo, ou reset
  manual deliberado antes via MCP `trader_reset_cooldown`). Take-profit no
  meio quebra a sequência de stops. Confirmado ao vivo (1 stop isolado
  disparando, escalada 30→60min).
- **Guard de NaN/±inf independente**: qualquer campo numérico do sinal
  não-finito é vetado aqui, sem depender de quem gerou o sinal já ter
  filtrado — defesa em profundidade real, não só declarada.
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
pela trilha e cura por consulta à exchange quando stale. Processo
supervisionado com restart automático (`supervisor.py`) — em uso ao vivo.
**Cuidado operacional aprendido em 26/07**: um processo de diagnóstico
avulso (fora do `supervisor.py`) que não for confirmado como realmente
encerrado pode virar um órfão que colide com tentativas de restart
seguintes — sempre confirmar a morte do processo, não só assumir.
[HOJE] alerta ativo via tarefa agendada `trader-watchdog` (`PushNotification`)
— reconhece crash/giveup do supervisor como crítico.

**6. Supervisão (usuário + MCP)**
[HOJE] trilha `logs/audit.jsonl` com TODA decisão; MCP próprio
(`wonder_trader`) read-only + halt/reset por arquivo de controle, **+ 2
tools novos (26/07): `trader_cooldown_status` (leitura) e
`trader_reset_cooldown` (ação, `confirm=true`)**. Catálogo de eventos
completo em `CLAUDE.md` (inclui `signal_exit_*`, `trailing_stop_moved`,
`trailing_exit_*`, `cooldown_triggered`, `cooldown_reset` (novo),
`engine_crash_restart`, `engine_supervisor_giveup`, `trade_closed`).
[ALVO] ranking top-N + confirmação de swing (decidido: autônomo, sem
portão).

## 4. Papel do MCP — só camada 6, só leitura

| Função | Permitido |
|---|---|
| Status, posições, PnL, decisões recentes, explicar símbolo | Sim (read-only) |
| Status/reset de cooldown por símbolo | Sim — status é leitura; reset exige `confirm=true` |
| Pausar novas entradas (halt) | Sim — grava sinal em arquivo; o engine decide |
| Resetar kill switch | Sim, com `confirm=true` explícito |
| Criar/cancelar ordem, mudar alavancagem/size | **Não, nunca** |

`trader_realized_pnl`/`trader_recent_decisions` tiveram um bug real (#31,
corrigido 22/07) — cortavam pelas últimas N linhas BRUTAS do
`audit.jsonl` antes de filtrar por tipo de evento. Corrigido: filtra por
tipo primeiro, corta depois.

## 5. Checklist de segurança de chaves (antes de capital real)

1. Duas API keys separadas (read-only p/ MCP; trade sem saque p/ motor).
   [HOJE: uma chave única de testnet no `.env` — aceitável só em testnet.]
2. IP whitelist nas duas.
3. Nenhuma chave com permissão de saque — nem em testnet.
4. Chaves fora de arquivo versionado; antes de mainnet, tirar o `.env` do
   OneDrive.
5. Situação regulatória Bybit/Brasil. **Pendente — bloqueia a Fase 5**
   (talvez só bloqueie derivativos, não spot — não confirmado).

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
6. Reset manual de cooldown por símbolo antes do prazo natural (novo,
   26/07) — ação deliberada, exige `confirm=true`, mesma filosofia do
   reset do kill switch.

## 7. Plano de fases — estado real e critério de fechamento

| Fase | Escopo | Estado | Fecha quando |
|---|---|---|---|
| 1 | Motor determinístico + risco + execução testnet, 2 símbolos | **FECHADA (19/07)** | — (critério atendido) |
| 2 | Backtest + walk-forward com dados reais | **Executada** (15-16/07, SEM EDGE — esperado; régua validada e corrigida) | Carimbo formal do Lucas na régua |
| 2b | Pesquisa de estratégia com dados novos + verificação adversarial (donchian/ema_cross) | **ENCERRADA (22/07) — veredito unânime NÃO PROMOVER** | Fio fechado; retomar exigiria universo maior ou WF redesenhado |
| 3 | Decisão Claude em testnet/paper | Código pronto e endurecido, desligado; teste com API real pendente (+ bug de `temperature` a corrigir antes) | LLM ligado, decisões auditadas, fail-safe confirmado AO VIVO |
| 4 | Supervisão via MCP | **Fechada** (16/07; kill switch persiste restart; 2 tools novos de cooldown 26/07) | — |
| 5 | Capital real, size mínimo | **Bloqueada** (regulatória — só derivativos confirmado, spot não revisitado) | Checklist seção 5 + paper cobrindo um ciclo completo de regime + Bybit Brasil resolvida |
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
completo entrada→proteção→saída lucrativa na exchange real; stop dinâmico
re-ancorado no fill; trailing stop em produção; teto de 20% por trade; kill
switch persistente através de restarts; **cooldown por símbolo de 3 níveis
com reset manual (endurecido e confirmado ao vivo em 25-26/07)**; TP por
software em spot; auditoria completa com pnl honesto; backtest/walk-forward
sem look-ahead; MCP (+ 2 tools novos de cooldown); dossiê 3x/dia; watchdog
agendado com alerta ativo; restart automático do processo.

**Pronto sem validar ao vivo:** saída por sinal; camada Claude (endurecida,
zero chamada real à API ainda — falta `ANTHROPIC_API_KEY` + fix do bug de
`temperature`); decisão #G (derivativos em tempo real — inerte até Fase 3
ligar).

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
  400) — achado nesta sessão, ainda não corrigido no código. Decisão do
  Lucas, sem pressa.
- **Revisitar se o bloqueio regulatório da Fase 5 é só sobre derivativos**
  — desde a migração pra spot (#E), ninguém confirmou se mainnet SPOT
  especificamente continua bloqueado pra residente BR.
- Situação regulatória Bybit/Brasil (bloqueia Fase 5, ver ressalva acima).
- Ratificar os números de risco do YAML em operação (incl. os novos
  valores de cooldown: 30/60/1440min).
- Seleção diária de universo por macro/on-chain (ideia de 16/07, adiada).
- Antes de mainnet: `.env` fora do OneDrive.

---
*Referência técnica interna do projeto — não é conteúdo institucional Wonder
BOAT/WonderHUB.AI nem recomendação de investimento.*
