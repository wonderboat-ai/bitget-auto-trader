# Projeto Auto-Trade — Instruções de Projeto (v4 — 2026-07-16)

Documento de referência para qualquer chat/agente que trabalhe neste projeto. Se um
passo proposto violar alguma regra aqui, o passo está errado — não a regra.

Convenção desta versão: **[HOJE]** = implementado e verificado no código;
**[PRONTO-SEM-VALIDAR]** = código existe, nunca rodou de verdade;
**[ALVO]** = escopo do produto final, ainda não construído.
Misturar "é" com "será" foi o que inflou o status da v1. **v4 herda a mesma
disciplina da v2/v3 — só atualiza os fatos, não a regra: "Status atual" descreve o
que foi verificado ao longo do dia 16/07, até o `engine_start` das 21:54 UTC (fix
de observabilidade em produção). É uma FOTO, não uma promessa. O detalhe minuto a
minuto vive em `CLAUDE.md`, que muda mais rápido do que este documento deveria.**

## Status atual (fatos verificados em 2026-07-16, até ~21:54 UTC)

- **Fase 1 — EM FECHAMENTO, mais perto do que nunca, ainda não fechada.** O saldo
  de BTC/ETH de brinde da testnet (pseudo-posição que travava BTC/USDT desde
  19:29 UTC) foi **confirmado e vendido** — `diag_saldo.py` mostra carteira só
  com USDT. BTC e ETH estão livres para avaliação. O motor foi reiniciado às
  21:54 UTC (pegando um fix de observabilidade, ver abaixo) e segue rodando.
  **Ainda zero `order_executed`** — falta só o mercado dar um sinal de entrada
  (EMA/RSI cruzar) para fechar o critério da Fase 1 (seção 7).
- **Fase 2 — EXECUTADA em 15/07 e ESTENDIDA em 16/07.** Veredito original
  (BTC/ETH, dados mainnet): SEM EDGE out-of-sample em todos os cenários. Hoje
  testamos backtest simples (15m e 4h) em mais 7 símbolos líquidos (SOL, MNT,
  BNB, XRP, ADA, ARB, LINK) — **nenhum mostrou profit factor > 1 de forma
  confiável**; o único destaque (XRP, PF 1,10 em 15m) foi ao walk-forward e
  virou PF 0,52 out-of-sample (SEM EDGE), confirmando o padrão. No perfil 4h,
  9/9 símbolos vieram "SEM EDGE" com amostra estatisticamente grande (39-51
  trades cada) — resultado mais decisivo que o do 15m. Conclusão: o gargalo é
  o gerador de sinal (EMA/RSI determinístico), não a escolha de símbolo/
  timeframe. Falta só o carimbo formal do Lucas aceitando a régua.
- **Fase 3 — PRONTO-SEM-VALIDAR (sem mudança de código desde 15/07).**
  `LLMStrategy` implementada com todas as salvaguardas; nunca ativada
  (`decision.strategy: deterministic`). O pipeline de dossiê diário (macro/
  on-chain) **já roda de verdade todo dia** via tarefa agendada nativa do
  Cowork ("Dossie cripto diário", ativa desde ~08/06, ~7h) — confirmado com
  arquivo do dia em `data/context/latest.json` e `DossierMacroProvider`/
  `DossierOnChainProvider` (já wired em `engine.py`) lendo com checagem de
  frescor. Inerte para o robô enquanto `decision.strategy` for
  `"deterministic"`.
- **Fase 4 — FECHADA e validada com dados reais em 16/07.** `mcp_server.py`
  registrado via `.mcp.json` na raiz do projeto (não `claude_desktop_config.json`
  clássico — o app do Lucas é Cowork/Claude Code, caminho de registro
  diferente do que a v3 supunha). `trader_get_status`/`trader_halt_status`/
  `trader_get_positions` responderam com dados batendo com a trilha.
- **Fase 5 — BLOQUEADA** por regulação confirmada (Bybit descontinuando
  derivativos/margem para residentes do Brasil). Decisão #E (pivô para SPOT)
  tomada e implementada; validação do executor em andamento na Fase 1.
- **Decisões #A e #B (seção 10 da v3) — FECHADAS em 16/07, sem mudança de
  código:**
  - **#A confirmação do swing: decidido AUTÔNOMO**, sem portão de aprovação
    humana. Swing já roda assim hoje (perfil determinístico, mesmo tratamento
    do daytrade); a decisão fixa que continua assim quando a Fase 3 ligar.
  - **#B kill switch: decidido MANTER sem flatten** (comportamento atual) —
    trava entradas novas, não fecha posições abertas à força.
- **Distância máxima de stop: decidido MANTER como está** (sizing por risco
  fixo já se autoprotege — stop largo → nocional menor, risco em USDT nunca
  muda). Testada e revertida uma alternativa (stop de estrutura, fundo/topo
  dos últimos 20 candles) — sanity-check promissor (PF 1,63 vs 0,67 em BTC
  15m) mas amostra pequena, não validada por walk-forward; fica registrada em
  `CLAUDE.md` para retomar nos ajustes finos, depois que o robô estiver
  todo estruturado (decisão explícita do Lucas de não mexer em parâmetro
  agora).
- **Fix de observabilidade (16/07):** `signal_vetoed` agora loga o campo
  `profile` (antes só `symbol_skipped` logava) — em produção desde o
  `engine_start` das 21:54 UTC.

## 1. Objetivo do projeto

Sistema de decisão assistida por IA com execução automatizada e supervisão humana,
para day trade + swing trade de cripto na Bybit. Full-auto com guardrails. Começa
em testnet, só migra para capital real depois que cada fase anterior fechar.

**Visão de produto (estado final):** o sistema varre os pares USDT da Bybit que
passarem num filtro de liquidez, roda análise completa por ativo (técnica + macro +
on-chain), opera micro-operações 24/7 em full-auto dentro dos guardrails, e devolve
ao usuário um **ranking diário de oportunidades por probabilidade ajustada a
risco**, com swing trade **também full-auto** (decisão #A fechada em 16/07 — não
"sugestão confirmável" como cogitado antes).

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

## 3. Arquitetura (6 camadas)

**1. Ingestão de dados**
[HOJE] REST via CCXT a cada ciclo (60s), 2 símbolos fixos (BTC, ETH — spot),
candles 15m/4h, funding rate; indicadores EMA/RSI/ATR calculados localmente, nunca
pelo modelo. Dossiê diário (macro/on-chain) já roda de verdade (ver Status atual).
[ALVO] WebSocket Bybit; universo completo de pares USDT (500+, muda toda semana);
**filtro de universo por liquidez** antes de qualquer par entrar no pipeline —
volume 24h mínimo, profundidade de book mínima, exclusão de recém-listados e de
funding anômalo (par ilíquido não é oportunidade, é armadilha de slippage);
seleção diária do universo a operar informada pela análise macro/on-chain (ideia
do Lucas, 16/07 — ainda não desenhada, ver seção 10).

**2. Feature engineering**
[HOJE] snapshot de estado único, a MESMA estrutura no live e no backtest (fonte
única de indicadores — se divergissem, o backtest mentiria).
[ALVO] campos macro/on-chain reais no snapshot (estrutura já preparada, dado já
disponível via dossiê — falta só `decision.strategy: llm` consumir).

**3. Camada de decisão**
[HOJE] estratégia determinística (EMA20/50 + RSI + stop 1,5×ATR) como trilho de
teste — testada em 9 símbolos × 2 timeframes em 16/07, sem edge validado em
nenhum (ver Status atual). [PRONTO-SEM-VALIDAR] `LLMStrategy` (Claude) com o
mesmo contrato `Signal`.
[ALVO] Claude analisa cada par aprovado no filtro; um passo de **agregação/ranking**
ordena por convicção ajustada a risco e gera o "top N do dia"; **daytrade E swing
full-auto** dentro dos guardrails (decisão #A fechada — sem portão de confirmação
humana); para scalp de minutos, o **LLM fica fora do caminho crítico** — define
viés/regime em cadência lenta, timing fino é determinístico.

**4. Camada de risco — poder de veto absoluto**
[HOJE, implementado e testado]
- Risco por trade 0,5% do capital, nunca calculado pelo LLM.
- Sizing derivado da distância até o stop, não o contrário — decidido em 16/07
  MANTER sem teto de distância máxima (o sizing por risco fixo já se
  autoprotege: stop largo → nocional menor).
- Stop obrigatório e **dinâmico** (1,5×ATR — respira com a volatilidade; nunca
  percentual fixo). Sem stop, sem trade. Stop incoerente com a direção, veto.
- Kill switch por drawdown: 3% diário (marco refeito na virada do dia UTC) e 15%
  total. Reset SEMPRE manual. **Decidido em 16/07: SEM flatten** — trava
  entradas novas, não fecha posições abertas (protegidas pelo stop individual).
- Limites agregados valendo **dentro do ciclo**: máx. 3 posições, exposição
  nocional 2× o capital, risco agregado 2%, alavancagem máx. 3x.
- Exclusividade por símbolo: um símbolo, uma entrada por ciclo (elimina LONG+SHORT
  simultâneos do mesmo ativo em modo one-way).
- Circuit breakers: funding anômalo (0,003 mainnet; 0,01 só em testnet, onde o
  funding vive no clamp da exchange), feed defasado >60s.
- Proteção de posição nua: stop falhou após entrada → fecha a posição na hora
  (reduceOnly) e audita.
[ALVO]
- Custo de operação (fee maker/taker, funding, slippage estimado pela profundidade
  do book) descontado do sinal ANTES de validar — em micro-operação o custo é o
  primeiro suspeito quando a borda estatística some.
- Checagem de correlação entre os ativos do ranking (5 altcoins correlacionadas ao
  BTC é UMA aposta, não cinco).
- Monitor de **decaimento de performance**: acerto/profit factor abaixo da banda
  estatística do backtest → pausa o perfil e sinaliza revisão.

**5. Execução**
[HOJE] CCXT/Bybit REST; ordens idempotentes (client order ID único); reconciliação
a cada ciclo (a corretora é a fonte da verdade); retry com backoff; erro em um
símbolo não derruba o ciclo; testnet e produção na mesma base de código, só muda
config; DRY_RUN por padrão.
[ALVO — requisito para 24/7 de verdade] processo supervisionado com restart
automático (Docker/NSSM/Agendador no Windows, ou systemd numa VPS — não "deixa
rodando no terminal"); detecção de perda de feed disparando o circuit breaker;
**alerta ativo** ao usuário (Telegram/e-mail) quando cair, perder conexão ou entrar
em circuit breaker — log passivo não acorda ninguém às 3h.

**6. Supervisão (usuário + MCP)**
[HOJE] trilha de auditoria `logs/audit.jsonl` com TODA decisão (aprovada, vetada —
já com o perfil que a gerou —, pulada, executada, kill switch, erro); servidor MCP
**próprio** (`wonder_trader`) registrado via `.mcp.json` (Cowork), com tools
read-only + halt/reset por arquivo de controle. Validado com dados reais em 16/07.
[ALVO] entrega do ranking diário "top N" por este canal + alertas ativos.

## 4. Papel do MCP — só camada 6, só leitura

O servidor MCP do projeto (`mcp_server.py`, wonder_trader) é o painel de bordo
conversacional. Fronteira:

| Função | Permitido |
|---|---|
| Status, posições, PnL, decisões recentes, explicar símbolo | Sim (read-only) |
| Pausar novas entradas (halt) | Sim — grava sinal em arquivo; o engine decide |
| Resetar kill switch | Sim, com `confirm=true` explícito |
| Criar/cancelar ordem, mudar alavancagem/size | **Não, nunca** |

Não existe tool de execução. O MCP não controla o processo do engine — só deixa
sinal em `state/control.json`, que o engine lê no próximo ciclo.

## 5. Checklist de segurança de chaves (antes de capital real)

1. Duas API keys separadas na Bybit: read-only (MCP/supervisão) e trade-enabled sem
   saque (motor). [HOJE: uma chave única de testnet no `.env` — aceitável só em
   testnet.]
2. IP whitelist nas duas.
3. Nenhuma chave com permissão de saque — nem em testnet.
4. Chaves fora de qualquer arquivo versionado (`.env` está no `.gitignore`).
   Atenção: o `.env` atual sincroniza via OneDrive — antes de chave de mainnet,
   mover para variável de ambiente do sistema ou secrets manager local.
5. Situação regulatória da Bybit para residente no Brasil. **Pendente — bloqueia a
   Fase 5.**

## 6. O que permanece sob controle humano mesmo em full-auto

1. Kill switch manual (e o reset é sempre manual).
2. Aprovação de mudança de parâmetro de risco — o sistema não reescreve os próprios
   limites; nem o LLM, nem o engine, nem agente nenhum.
3. Gatilho de ir para capital real.

(Confirmação de swing trade sugerido **não** entra aqui — decisão #A fechada em
16/07: swing é full-auto dentro dos guardrails, igual ao daytrade.)

## 7. Plano de fases — estado real e critério de fechamento

| Fase | Escopo | Estado | Fecha quando |
|---|---|---|---|
| 1 | Motor determinístico + risco + execução testnet, 2 símbolos | **Em fechamento** — BTC destravado, ao vivo rodando em spot, sem order_executed confirmado ainda | `--live` com ordem E stop confirmados na testnet (spot) — falta ainda |
| 2 | Backtest + walk-forward com dados reais | **Executada e estendida** (15/07 + 16/07, veredito SEM EDGE em 9 símbolos × 2 timeframes — esperado) | Régua de validação ratificada formalmente pelo Lucas (processo já rodou; falta o carimbo) |
| 3 | Decisão Claude em testnet/paper | Código pronto, desligado | LLM ligado, decisões auditadas, comportamento fail-safe confirmado (falha→FLAT) |
| 4 | Supervisão via MCP | **Fechada** — registrada via `.mcp.json` (Cowork) e validada com dados reais em 16/07 | — (critério atendido) |
| 5 | Capital real, size mínimo, 2 símbolos | **Bloqueada** (regulatória — confirmada, não só formal) | Checklist seção 5 completo + paper longo o bastante (seção 8, item 5) + situação Bybit Brasil resolvida |
| 6 | Expansão: universo completo + filtro de liquidez + ranking top-N + swing full-auto + infra 24/7 + regime + decaimento | [ALVO] não iniciada | Cada item validado em testnet antes de valer em capital real |

Regra de avanço inalterada: só passa de fase quando a anterior fechou. A Fase 6
pode rodar em testnet em paralelo à Fase 5, mas nada dela entra em capital real sem
validação própria.

## 8. Sobre meta de acertividade (a resposta definitiva ao "90%")

**Não se mira 90% de taxa de acerto, e um sistema desenhado para bater esse número
tende a ser pior, não melhor.** Causa raiz:

- Taxa de acerto isolada não mede lucratividade. O que importa é **expectância**:
  `(taxa de acerto × ganho médio) − (taxa de erro × perda média)`. 40% de acerto
  com ganho/perda 3:1 é lucrativo; 90% de acerto com uma cauda de perda rara e
  grande quebra a conta numa operação ("recolher moedas na frente do trator").
- Backtest com 90%+ é sintoma clássico de **overfitting** (curve-fitting, viés de
  lookahead, custo de transação ausente) — não sobrevive um dia de mercado real.
- Cripto tem **cauda gorda**: cascata de liquidação, flash crash, gap de funding.
  Sistema robusto se mede pela pior semana, não pela melhor.
- Mesas quant profissionais miram **profit factor, Sharpe/Sortino e max drawdown
  controlado** — é a régua adotada aqui.

O que o usuário quer na prática — "a maior chance de lucro por probabilidade" — é
entregável de outra forma, honesta: um **ranking calibrado**. O sistema reporta a
probabilidade estimada de cada oportunidade E mede continuamente a calibração
(previsto vs. realizado). Confiança vem de calibração comprovada, não de promessa
de win rate.

Pré-requisitos para operar de fato com confiança (checklist de prontidão):

1. Walk-forward com custos realistas — fee ✅ e slippage fixo ✅ já modelados;
   **falta funding e slippage por profundidade de book**.
2. **Monte Carlo** sobre a curva de equity do backtest — distribuição real de
   drawdown esperado, não só o pior caso histórico. [ALVO]
3. **Detecção de regime** (tendência / lateral / alta vol) — saber em qual regime
   está e ajustar ou pausar. [ALVO]
4. **Monitor de decaimento** em produção com banda estatística. [ALVO]
5. Paper/testnet cobrindo **pelo menos um ciclo completo de regime** antes de
   capital real — dias não bastam.
6. Latência compatível com timeframe: scalp de 1–5 min NÃO tem LLM no caminho
   crítico de cada entrada. [ALVO — hoje o ciclo é 60s com 2 pares, ok para 15m]

## 9. Alinhamento do sistema atual com a visão — leitura honesta

**Implementado e validado:** separação decisão/risco/execução; stop dinâmico ATR
obrigatório; sizing pelo stop; kill switch diário/total com reset manual (sem
flatten, decidido); limites agregados intra-ciclo; exclusividade por símbolo;
circuit breakers de funding e feed; proteção de posição nua; idempotência +
reconciliação; auditoria completa (com profile no veto); backtest/walk-forward
sem lookahead com veredito honesto, estendido a 9 símbolos; MCP read-only
registrado e validado; dossiê diário macro/on-chain rodando de verdade.

**Pronto sem validar:** camada Claude (fail-safe→FLAT); walk-forward com dados
reais.

**Não existe ainda (o gap entre hoje e a visão):** varredura do universo USDT;
filtro de liquidez; seleção diária de universo por análise macro/on-chain;
ranking top-N por probabilidade ajustada a risco; calibração de probabilidade;
custo de operação no sinal live; correlação do portfólio; Monte Carlo; detecção
de regime; monitor de decaimento; infra 24/7 (watchdog, restart, alerta ativo);
WebSocket; portfólio simulado no DRY_RUN (paper PnL entre ciclos).

## 10. Pendências e decisões em aberto

- ~~#A Mecanismo de confirmação do swing sugerido~~ **FECHADA em 16/07** —
  autônomo, sem portão de confirmação (ver Status atual).
- ~~#B Kill switch: com ou sem flatten?~~ **FECHADA em 16/07** — mantém sem
  flatten.
- ~~Distância máxima de stop~~ **FECHADA em 16/07** — mantém sem teto (ver
  Status atual e `CLAUDE.md` para a ideia de stop de estrutura, adiada).
- Situação regulatória Bybit/Brasil (bloqueia Fase 5).
- Ratificar os números de risco **em operação provisória** no YAML: 3% DD diário,
  15% total, 3 posições, 2× exposição, 2% risco agregado, 3x alavancagem, 0,5% por
  trade. Estão rodando em testnet; falta o carimbo de decisão consciente (distinto
  da distância de stop, já fechada).
- Fonte on-chain: Glassnode/CryptoQuant pago vs. alternativa gratuita (o dossiê
  diário já cobre on-chain em cadência diária; isto é sobre uma fonte em
  tempo real, se fizer sentido ter).
- **NOVA (16/07): seleção diária do universo de símbolos por análise
  macro/on-chain** (ideia do Lucas) — hoje `trading.symbols` é estático no YAML.
  Faria sentido a análise do dossiê propor um subconjunto diário dentro de um
  universo pré-aprovado (não escolha livre). Ainda não desenhada; explicitamente
  adiada pelo Lucas para depois que o robô estiver todo estruturado.
- Parâmetros do filtro de liquidez (volume mínimo 24h, profundidade mínima).
- Banda estatística do monitor de decaimento.
- Antes de mainnet: tirar o `.env` do OneDrive (secrets fora de pasta sincronizada).
- **#E (venue/produto) já DECIDIDA e implementada em 15/07:** spot na Bybit,
  não perpétuos. Falta só fechar a validação do executor (ver Fase 1).

---
*Referência técnica interna do projeto — não é conteúdo institucional Wonder
BOAT/WonderHUB.AI nem recomendação de investimento.*
