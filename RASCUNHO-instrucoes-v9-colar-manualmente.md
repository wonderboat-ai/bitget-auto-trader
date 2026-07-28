# Projeto Auto-Trade — Instruções de Projeto (v9 — 2026-07-28)

Documento de referência para qualquer chat/agente que trabalhe neste projeto. Se um
passo proposto violar alguma regra aqui, o passo está errado — não a regra.

Convenção desta versão: **[HOJE]** = implementado e verificado no código;
**[PRONTO-SEM-VALIDAR]** = código existe (testado offline), nunca rodou ao vivo;
**[ALVO]** = escopo do produto final, ainda não construído.
**v9 herda a disciplina da v2-v8 — só atualiza os fatos, não a regra. "Status
atual" é uma FOTO (28/07, madrugada UTC), não uma promessa. O detalhe minuto a
minuto vive em `CLAUDE.md`, que muda mais rápido do que este documento deveria.
Substitui a v8, que nunca chegou a ser colada nas instruções do Claude Project
(mesmo padrão da v6→v7).**

## Status atual (fatos verificados até 2026-07-28, madrugada UTC)

- **Mainnet SPOT ao vivo desde 27/07/2026 — primeiro trade real executado
  na madrugada de 28/07.** Motor rodando com `ENVIRONMENT=mainnet`,
  `--live`, via `supervisor.py`. Primeira entrada real: ETH/USDT long,
  ~24,89 USDT de notional (quase todo o equity inicial), com stop e
  trailing armados na exchange real. Kill switch livre, nenhuma posição
  nua, nenhum erro crítico. Equity atual **~110 USDT** (subiu de ~24 USDT
  por um depósito do Lucas na conta, confirmado por ele). PnL realizado em
  mainnet: **0 trades fechados** (a posição ETH segue aberta).
- **Dois bugs reais achados e corrigidos no primeiro boot `--live` em
  mainnet** (madrugada de 28/07, ver `CLAUDE.md` bugs #46/#47):
  1. `state/spot_protections.json` não era isolado por AMBIENTE (mesma
     classe do bug #39, nunca estendida a este arquivo) — proteções
     RESIDUAIS da era testnet ainda estavam no arquivo quando o motor
     subiu em mainnet pela primeira vez, e o engine as reconciliou como
     fechadas contra a exchange MAINNET, fabricando 2 `trade_closed` com
     -62,73 USDT de PnL que nunca aconteceram. Nenhum dinheiro real foi
     afetado (as ordens não existiam pra cancelar/vender) — só a trilha
     ficou poluída. Corrigido na fonte (isolamento por ambiente, mesmo
     padrão do bug #39) + trilha corrigida (eventos fabricados movidos pra
     arquivo, não apagados).
  2. Aplicação manual de take-profit na posição ETH real (ver decisão
     abaixo) foi auditada com `environment: testnet` por engano de um
     script avulso que não carregou o `.env` — corrigido in-place (o TP em
     si estava certo, só o rótulo do evento).
- **Decisão nova (28/07, a pedido do Lucas: "eu quero os dois"): trailing
  stop e take-profit fixo agora CONVIVEM na mesma posição** — antes,
  `trailing: true` zerava o take-profit por design (desde 22/07); agora a
  posição sai pelo que disparar primeiro (TP fixo se o preço rally até o
  alvo `tp_rr`, ou o stop móvel se reverter antes). Único ponto de código
  alterado: `src/strategy/deterministic.py` parou de zerar o `tp` quando
  `trailing=True` — `engine.py`/`backtester.py` já tratavam os dois de
  forma independente, nenhuma outra mudança foi necessária. Validado com
  backtest sintético isolado (4 fechamentos via TP, 6 via trailing_stop,
  os dois mecanismos coexistindo de ponta a ponta) + take-profit aplicado
  manualmente na posição ETH já aberta (1.959,13 USDT, calculado com a
  mesma fórmula `tp_rr` usando a distância de risco original). **Motor
  reiniciado** pra o fix valer — já ativo para qualquer entrada nova.
- **Suíte de testes: 269/269** (261 em `test_smoke.py` + 8 em
  `test_ciclo.py` — cresceu de 261/9 com 4 checks novos de trailing+TP
  convivendo). Achou e corrigiu uma regressão real no caminho: um dos
  próprios testes novos (backtest sintético de trailing) passou a
  disparar o kill switch REAL por drawdown, vazando `halted=True` pro
  teste seguinte (lacuna de isolamento pré-existente na suíte, não
  intermitente) — corrigido com um reset pontual do kill switch logo após
  aquele teste. Rodada com o motor genuinamente parado (confirmado por
  lista de processos, não só pela trilha); arquivos reais de estado
  verificados intactos e corretamente restaurados depois.
- **Cooldown por símbolo, 3 níveis + reset manual, e demais capacidades de
  20-26/07 (trailing original, restart automático, watchdog agendado)**
  seguem sem mudança de comportamento desde a v8 — ver lá ou `CLAUDE.md`
  pro histórico completo.
- **Incidente de compliance da Bybit (bloqueio no REARME do trailing stop
  em spot, retCode 10024/KYC_PROMPT_TOAST) segue em aberto, sem mudança**
  — mas o trailing JÁ moveu com sucesso (sem bloqueio) pelo menos 3 vezes
  na madrugada de 28/07, na posição ETH real. Ou seja, o bloqueio não é
  100% consistente — pode ser intermitente ou já ter sido parcialmente
  resolvido do lado da Bybit. Acompanhar se volta a ocorrer.

## 1. Objetivo do projeto

Sistema de decisão assistida por IA com execução automatizada e supervisão humana,
para day trade + swing trade de cripto na Bybit. Full-auto com guardrails. Começou
em testnet; migrou para capital real (mainnet spot) em 27/07/2026, decisão explícita
do Lucas — primeiro trade real executado na madrugada de 28/07 (ETH/USDT long) — ver
"Status atual" e `CLAUDE.md` pro relato completo do dia da transição. Perpétuos/
derivativos continuam bloqueados (pendência regulatória BR); só spot está liberado
pra mainnet.

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
[HOJE] estratégia determinística (EMA20/50 + RSI + stop 1,5×ATR) como trilho
de teste — SEM edge validado em TRÊS rodadas de pesquisa independentes; é
consistentemente a PIOR família testada. **Desde 28/07: trailing stop e
take-profit fixo (`tp_rr`) CONVIVEM na mesma posição** — sai pelo que
disparar primeiro; antes, trailing zerava o TP fixo por completo (22/07 a
27/07). Cooldown de 3 níveis por símbolo em produção.
[PRONTO-SEM-VALIDAR] `LLMStrategy` (Claude) com o mesmo contrato `Signal` —
revisada adversarialmente, zero teste com API real ainda (`ANTHROPIC_API_KEY`
ausente, e há um bug de `temperature` a corrigir antes — ver v8/`CLAUDE.md`).
[ALVO] ranking top-N por convicção ajustada a risco; scalp com LLM fora do
caminho crítico.

**4. Camada de risco — poder de veto absoluto**
[HOJE, implementado e testado]
- Risco por trade 0,5% do capital, nunca calculado pelo LLM.
- Sizing derivado da distância até o stop. Teto de capital por trade:
  **100% do equity** (elevado de 20% em 27/07/2026, decisão do Lucas — com
  equity pequeno no início do teste em mainnet, 20% cortava o nocional
  abaixo do mínimo de ordem da Bybit spot; reavaliar se o capital crescer),
  CLAMPA (nunca veta).
- Stop obrigatório e dinâmico (1,5×ATR, sobe com trailing). Sem stop, sem
  trade. Stop re-ancorado no preço REAL do fill.
- **Take-profit fixo (`tp_rr`, default 2,0×distância do stop) agora
  calculado SEMPRE, com ou sem trailing** (fix de 28/07) — antes só
  existia quando trailing estava desligado.
- Kill switch por drawdown: 3% diário / 15% total; reset SEMPRE manual; sem
  flatten. Persiste em disco através de restarts.
- **Cooldown por símbolo, 3 níveis**: 1 stop ISOLADO já pausa entradas
  NOVAS nesse símbolo — 30min no 1º acionamento do dia, 60min no 2º, 24h
  no 3º em diante (auto-libera no prazo, ou reset manual deliberado antes
  via MCP `trader_reset_cooldown`). Take-profit no meio quebra a sequência
  de stops.
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
software em spot (agora ativo mesmo com trailing ligado); saída por sinal
pronta (desligada); trailing stop LIGADO em produção. Estado local em
`state/spot_protections.json` — **isolado por AMBIENTE desde 28/07**
(testnet e mainnet nunca mais leem/gravam o mesmo arquivo; achado ao vivo
no primeiro boot real em mainnet, ver "Status atual") — com backfill pela
trilha e cura por consulta à exchange quando stale. Processo supervisionado
com restart automático (`supervisor.py`) — em uso ao vivo.
[HOJE] alerta ativo via tarefa agendada `trader-watchdog` (`PushNotification`)
— reconhece crash/giveup do supervisor como crítico.

**6. Supervisão (usuário + MCP)**
[HOJE] trilha `logs/audit.jsonl` com TODA decisão (agora com o histórico de
testnet arquivado à parte desde 27/07 — o PnL de mainnet começa do zero);
MCP próprio (`wonder_trader`) read-only + halt/reset por arquivo de
controle, com `trader_cooldown_status`/`trader_reset_cooldown`. Catálogo de
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
| Status/reset de cooldown por símbolo | Sim — status é leitura; reset exige `confirm=true` |
| Pausar novas entradas (halt) | Sim — grava sinal em arquivo; o engine decide |
| Resetar kill switch | Sim, com `confirm=true` explícito |
| Criar/cancelar ordem, mudar alavancagem/size | **Não, nunca** |

`trader_realized_pnl`/`trader_recent_decisions` tiveram um bug real (#31,
corrigido 22/07) — cortavam pelas últimas N linhas BRUTAS do
`audit.jsonl` antes de filtrar por tipo de evento. Corrigido: filtra por
tipo primeiro, corta depois. **Limitação real e não-corrigida (spot):**
`unrealized_pnl`/`entry_price` sempre vêm `0` do MCP em posições spot — a
Bybit não rastreia PnL de holdings spot (só de posições de derivativos); o
cálculo manual (preço atual − entrada) × tamanho precisa ser feito à parte
(ver `CLAUDE.md`, verificado direto na API em 27-28/07).

## 5. Checklist de segurança de chaves

1. Duas API keys separadas (read-only p/ MCP; trade sem saque p/ motor).
   [HOJE: uma chave única por ambiente no `.env` — mainnet e testnet
   usam chaves distintas, mas cada uma sem separação leitura/trade.]
2. IP whitelist nas duas.
3. Nenhuma chave com permissão de saque — nem em testnet, nem em mainnet.
4. Chaves fora de arquivo versionado. **Pendência real, aceita
   conscientemente**: `.env` continua dentro do OneDrive mesmo em mainnet —
   risco aceito pra viabilizar a virada de 27/07/2026, não um esquecimento.
5. Situação regulatória Bybit/Brasil. **Parcialmente resolvida**: spot
   confirmado liberado pra mainnet (27/07/2026); derivativos/perp
   continuam bloqueados.

## 6. O que permanece sob controle humano mesmo em full-auto

1. Kill switch manual (e o reset é sempre manual).
2. Aprovação de mudança de parâmetro de risco — o sistema não reescreve os
   próprios limites; nem o LLM, nem o engine, nem agente nenhum. Inclui
   `decision.strategy` (deterministic↔llm), `decision.deterministic.*`,
   `decision.llm.*` e `cooldown.*` — mudar é decisão exclusiva do Lucas.
3. Gatilho de ir para capital real — já disparado em 27/07/2026 (spot).
4. Toda ação direta na exchange (cancelar/armar ordem manualmente).
5. Trocar o processo de `main.py` direto para `supervisor.py` (ou
   vice-versa) — decisão operacional do Lucas, não automática.
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
| 4 | Supervisão via MCP | **Fechada** (16/07; kill switch persiste restart; cooldown status/reset) | — |
| 5 | Capital real, size mínimo | **INICIADA (27/07/2026)** — spot ao vivo, primeiro trade real executado (28/07); derivativos seguem bloqueados | Ciclo completo validado (entrada→saída) em mainnet + operação estável por período relevante |
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
completo entrada→proteção→saída lucrativa na exchange real (testnet); primeiro
trade real em MAINNET (28/07/2026); stop dinâmico re-ancorado no fill;
**trailing stop e take-profit fixo convivendo na mesma posição** (novo,
28/07); teto de 100% por trade; kill switch persistente através de
restarts; cooldown por símbolo de 3 níveis com reset manual; TP por
software em spot; auditoria completa com pnl honesto (incluindo isolamento
por ambiente do estado de proteção de posição, novo em 28/07); backtest/
walk-forward sem look-ahead; MCP; dossiê 3x/dia; watchdog agendado com
alerta ativo; restart automático do processo.

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
- **Incidente de compliance da Bybit (bloqueio no rearme do trailing stop
  em spot, retCode 10024) segue em aberto** — mas não 100% consistente (o
  trailing já moveu com sucesso 3x na madrugada de 28/07). Trailing
  continua ligado; decisão do Lucas de não mexer no código/config por
  enquanto, só acompanhar.
- Ratificar os números de risco do YAML em operação (cooldown 30/60/1440min,
  teto de capital 100%) — agora com equity real maior (~110 USDT) que
  quando os valores foram definidos, vale reavaliar se ainda fazem sentido.
- Seleção diária de universo por macro/on-chain (ideia de 16/07, adiada).
- **Pendência real, não resolvida**: `.env` continua dentro do OneDrive —
  risco aceito conscientemente. Revisitar se/quando fizer sentido tirar os
  segredos de mainnet do caminho sincronizado.
- **SPOT_DUST_USDT=10.0 colide com equity pequeno** — mitigado pelo
  depósito que elevou o equity pra ~110 USDT; reavaliar se o problema
  reaparecer com posições menores.

---
*Referência técnica interna do projeto — não é conteúdo institucional Wonder
BOAT/WonderHUB.AI nem recomendação de investimento.*
