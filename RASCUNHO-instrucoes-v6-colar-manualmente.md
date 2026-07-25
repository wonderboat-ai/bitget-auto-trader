# Projeto Auto-Trade — Instruções de Projeto (v6 — 2026-07-21)

Documento de referência para qualquer chat/agente que trabalhe neste projeto. Se um
passo proposto violar alguma regra aqui, o passo está errado — não a regra.

Convenção desta versão: **[HOJE]** = implementado e verificado no código;
**[PRONTO-SEM-VALIDAR]** = código existe (testado offline), nunca rodou ao vivo;
**[ALVO]** = escopo do produto final, ainda não construído.
**v6 herda a disciplina da v2-v5 — só atualiza os fatos, não a regra. "Status
atual" é uma FOTO (21/07, ~21:40 UTC), não uma promessa. O detalhe minuto a
minuto vive em `CLAUDE.md`, que muda mais rápido do que este documento deveria.**

## Status atual (fatos verificados em 2026-07-21, até ~21:40 UTC)

- **Fase 1 — FECHADA em 19/07.** O ciclo completo foi validado na exchange real
  (testnet spot), ponta a ponta e confirmado 1:1 contra a UI/histórico da Bybit:
  entrada a mercado + stop real (17/07), e **saída lucrativa automática**
  (19/07 15:15 UTC — TP por software do BTC, pnl +56,51 USDT; vários TPs desde
  então). O robô abre, protege e realiza sozinho, rodando ao vivo a maior
  parte do dia 21/07.
- **Engenharia validada ≠ estratégia validada.** PnL positivo em dias
  individuais é encanamento funcionando + mercado favorável — NÃO é evidência
  de edge. A pesquisa formal (16/07 e 21/07, ver abaixo) diz o contrário. Não
  escalar capital com base em PnL de curto prazo.
- **Sete bugs REAIS de produção achados e corrigidos ao vivo (19-21/07)**,
  a maioria via monitoramento em tempo real da trilha ou pelo watchdog
  agendado: (#23, CRÍTICO) `cancel_all` nunca cancelava a categoria
  `tpslOrder` da Bybit v5; (#24) proteção não cobria fill favorável; (#25)
  `entry_price` aproximado em vez do fill real; (#26) stop/TP sem
  re-ancoragem no fill, causou loop de reentrada; (#28) kill switch só
  existia em RAM — reiniciar o processo zerava o halt sem rastro, **agora
  persiste em disco e sobrevive a restart**; (#29) `naked_position_close_failed`
  podia disparar sem nunca reconfirmar o saldo real — **achado PELO watchdog
  agendado**, não por monitoramento manual; (#30) sem cooldown, um único
  evento de dado ruim virava N ciclos de perda seguidos — **novo: cooldown
  por símbolo após stops consecutivos** (2 stops → 30min, escalando a
  60min no 2º acionamento do mesmo dia). Detalhe completo: `CLAUDE.md`,
  seções "Estado exato" e "Bugs corrigidos".
- **Fase 2 — EXECUTADA (15/07) + duas rodadas de pesquisa formal de
  estratégia (16/07 e 21/07).** Veredito 16/07 (108 combinações, 6 meses
  100% bear): sem edge long-only; robô atual é a PIOR das 6 famílias.
  **Veredito 21/07 (pesquisa 2b — dado novo, 2,25 anos, regime misto
  alta+baixa+lateral confirmado): AINDA sem edge validado** em donchian
  (mediana WF -3,43%) nem ema_cross (-6,54%), mesmo já com saída por
  sinal/trailing simuláveis. **O robô atual confirmou DE NOVO ser a pior
  opção — em dois datasets independentes agora** (mediana -29,82% no
  dataset novo, pior que os -3,40% de 16/07). Donchian/4h é o "menos pior"
  (não é recomendação de uso). Relatórios em `research/`. Datasets QUEIMADOS
  para seleção.
- **Capacidades de execução (saída por SINAL + trailing stop + paridade do
  backtester, implementadas 21/07)**: [PRONTO-SEM-VALIDAR ao vivo; testado
  offline, revisão adversarial com achados corrigidos]. **DESLIGADAS por
  default** — ligar é decisão exclusiva do Lucas via YAML
  (`decision.deterministic.exit_on_signal` / `.trailing`).
- **Nova capacidade de supervisão: tarefa agendada `trader-watchdog`**
  (criada 21/07, via scheduled-tasks) — roda de 30 em 30 minutos, checa
  kill switch/erros críticos, notifica só se achar problema real (motor
  parado de propósito = silêncio). **Já provou valor no 1º dia**: achou o
  bug #29 antes de qualquer humano perceber. Limitação real: só roda com o
  Claude Desktop/Cowork aberto — não é daemon independente do app.
- **Fase 3 — PRONTO-SEM-VALIDAR** (sem mudança desde 15/07). `LLMStrategy`
  implementada, desligada. Dossiê diário macro/on-chain roda todo dia.
  Decisão #G (18/07): fonte on-chain real-time via Bybit, não implementada,
  não urgente.
- **Fase 4 — FECHADA** (MCP validado 16/07). Ressalva do kill switch não
  persistir restart (documentada desde 20/07) **RESOLVIDA e CONFIRMADA ao
  vivo em 21/07** (bug #28) — inclusive achado colateral: o `mcp_server.py`
  também não recarrega código, precisa reiniciar o Claude Desktop pra um
  fix em código que o MCP importa valer de verdade (não só reiniciar o
  motor).
- **Fase 5 — BLOQUEADA** por regulação (Bybit descontinuando derivativos para
  residentes BR; spot na entidade Bybit Brasil é o caminho — decisão #E).
- Suíte de testes: **164/164** (`tests/test_smoke.py` 156 + `test_ciclo.py`
  8). Regra operacional REFORÇADA: nunca rodar a suíte com o motor vivo.

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
teste — SEM edge validado em DOIS datasets independentes agora (16/07 e 21/07);
é consistentemente a PIOR família testada. A estratégia agora TAMBÉM pode
emitir saída por sinal e pedir trailing [PRONTO-SEM-VALIDAR ao vivo,
desligado por default].
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
  flatten (decisão #B). **Persiste em disco através de restarts desde 21/07**
  (fix #28, confirmado ao vivo) — `state/kill_switch_state.json`.
- **Cooldown por símbolo após stops consecutivos (novo, 21/07, fix #30)**: 2
  stops seguidos no mesmo símbolo pausa entradas NOVAS nesse símbolo por
  30min (60min do 2º acionamento em diante no mesmo dia) — persiste em disco
  igual ao kill switch. Motivado por um whipsaw real investigado (ver
  `CLAUDE.md`): dado ruim de testnet virou 6 ciclos de perda em 8 minutos por
  falta dessa proteção.
- Limites agregados intra-ciclo: máx. 3 posições, exposição 1× equity em spot,
  risco agregado 2%. Exclusividade por símbolo fail-closed.
- Circuit breakers: funding anômalo, feed defasado.
- Proteção nunca-nua em TODOS os caminhos que tocam o stop (entrada, TP por
  software, saída por sinal, trailing move): falha → re-arma → se falhar,
  evento crítico na trilha + intervenção manual. **Reforçada em 21/07 (fix
  #29)**: antes de declarar uma posição sem proteção, reconfirma o saldo real
  na exchange (a 1ª leitura pode vir atrasada/racy sob reentrada rápida).
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
[PARCIALMENTE FEITO, novo 21/07] alerta ativo via tarefa agendada
`trader-watchdog` (`PushNotification`, não Telegram/e-mail — decisão do
Lucas de reaproveitar a notificação do próprio Claude). **Ainda [ALVO]**:
restart automático do processo — se `main.py` cair sozinho (crash), ninguém
o religa; o watchdog só alerta, não religa.

**6. Supervisão (usuário + MCP)**
[HOJE] trilha `logs/audit.jsonl` com TODA decisão; MCP próprio
(`wonder_trader`) read-only + halt/reset por arquivo de controle, agora com
status de kill switch confiável através de restarts (fix #28). Catálogo de
eventos completo em `CLAUDE.md` (inclui `signal_exit_*`, `trailing_stop_moved`,
`trailing_exit_*`, `cooldown_triggered` (novo), `trade_closed` com
`reason=take_profit|stop_loss|signal_exit|trailing_stop|external_close_unconfirmed`).
Tarefa agendada `trader-watchdog` cobre parte do alerta ativo (ver camada 5).
[ALVO] ranking top-N + alertas ativos completos (restart automático).

## 4. Papel do MCP — só camada 6, só leitura

| Função | Permitido |
|---|---|
| Status, posições, PnL, decisões recentes, explicar símbolo | Sim (read-only) |
| Pausar novas entradas (halt) | Sim — grava sinal em arquivo; o engine decide |
| Resetar kill switch | Sim, com `confirm=true` explícito |
| Criar/cancelar ordem, mudar alavancagem/size | **Não, nunca** |

O halt via MCP foi usado EM PRODUÇÃO em 20/07 para conter o loop de reentrada
(bug #26) — o desenho funcionou como planejado. Status do kill switch agora
confiável através de restarts (fix #28, 21/07) — antes podia reportar um halt
antigo como ativo mesmo com o motor livre de novo.

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
   chaves novas `decision.deterministic.exit_on_signal`/`.trailing` e os
   parâmetros do cooldown (`cooldown.*` no YAML) — mudar é decisão exclusiva
   do Lucas.**
3. Gatilho de ir para capital real.
4. Toda ação direta na exchange (cancelar/armar ordem manualmente) — visto na
   prática em 19/07 (re-armar o stop do ETH foi ação do Lucas, nunca do agente).

## 7. Plano de fases — estado real e critério de fechamento

| Fase | Escopo | Estado | Fecha quando |
|---|---|---|---|
| 1 | Motor determinístico + risco + execução testnet, 2 símbolos | **FECHADA (19/07)** — entrada+stop+saída lucrativa automática confirmados na exchange | — (critério atendido) |
| 2 | Backtest + walk-forward com dados reais | **Executada** (15-16/07, SEM EDGE — esperado; régua validada e corrigida) | Carimbo formal do Lucas na régua |
| 2b | Pesquisa de estratégia com dados novos (2+ anos, regime misto, donchian/ema_cross com saída por sinal/trailing) | **EXECUTADA (21/07) — AINDA sem edge validado**; robô atual confirmado pior opção em 2 datasets | Verificação adversarial completa se alguém quiser promover donchian/4h |
| 3 | Decisão Claude em testnet/paper | Código pronto, desligado | LLM ligado, decisões auditadas, fail-safe confirmado |
| 4 | Supervisão via MCP | **Fechada** (16/07; halt usado em produção 20/07; kill switch agora persiste restart) | — |
| 5 | Capital real, size mínimo | **Bloqueada** (regulatória) | Checklist seção 5 + paper longo (seção 8.5) + Bybit Brasil resolvida |
| 6 | Expansão (universo, ranking, 24/7, regime, decaimento) | [ALVO] — alerta ativo parcialmente feito (watchdog), restart automático ainda não | Cada item validado em testnet |

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
re-ancorado no fill; teto de 20% por trade; kill switch persistente através de
restarts (inclusive via MCP em produção); TP por software em spot; auditoria
completa com pnl honesto (`pnl_usdt: null` quando componente desconhecido —
nunca inventa número); backtest/walk-forward sem look-ahead; MCP; dossiê
diário; watchdog agendado com alerta ativo (achou um bug real no 1º dia).

**Pronto sem validar ao vivo:** saída por sinal; trailing stop; camada Claude;
cooldown por símbolo pós-stops-consecutivos (fix #30, testado offline, ainda
não disparou em produção real); reconfirmação de saldo antes de
`naked_position_close_failed` (fix #29, idem).

**Não existe ainda:** estratégia com edge (o gargalo REAL do projeto, agora
confirmado em DOIS datasets independentes); varredura de universo; ranking;
calibração; custo no sinal live; correlação; Monte Carlo; regime; decaimento;
restart automático do processo; WebSocket.

## 10. Pendências e decisões em aberto

- **Estratégia sem edge (2 datasets independentes agora)**: se alguém quiser
  continuar puxando o fio, donchian/4h é o "menos pior" — precisa de
  verificação adversarial completa (como 16/07, múltiplos agentes) antes de
  qualquer decisão de capital. Alternativa: repensar se o universo fixo de
  5-6 símbolos é onde o edge está (visão de produto original é varredura +
  ranking, não símbolo fixo).
- Ligar `exit_on_signal`/`trailing` no live (decisão do Lucas) — sem edge
  validado em nenhuma estratégia ainda, não é urgente.
- Validar ao vivo os fixes de 21/07 (#29 reconfirmação de saldo, #30
  cooldown) — só testados offline até agora; watchdog e monitoramento devem
  ficar de olho na próxima vez que dispararem de verdade.
- **Restart automático do processo** — ainda não existe; se `main.py` cair
  sozinho, ninguém religa (o watchdog só alerta). Candidato: Task Scheduler
  do Windows monitorando o PID, ou um wrapper supervisor.
- Isolamento de estado do backtester: `kill_switch_state.json` e
  `cooldown_state.json` não têm override por env var como `AUDIT_PATH` tem
  (fix #14) — um backtest rodado enquanto o motor ao vivo estiver halted/em
  cooldown herdaria esse estado real. Risco baixo (resultado obviamente
  estranho, não dano silencioso), documentado, não corrigido.
- Situação regulatória Bybit/Brasil (bloqueia Fase 5).
- Ratificar os números de risco do YAML em operação (0,5%/trade, 20%/trade
  teto, 3%/15% DD, 3 posições, 1× exposição spot, 2 stops/30-60min cooldown).
- #G on-chain real-time da Bybit (decidida, não implementada, não urgente).
- Seleção diária de universo por macro/on-chain (ideia de 16/07, adiada).
- Antes de mainnet: `.env` fora do OneDrive.

---
*Referência técnica interna do projeto — não é conteúdo institucional Wonder
BOAT/WonderHUB.AI nem recomendação de investimento.*
