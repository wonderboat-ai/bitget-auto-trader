# Projeto Auto-Trade — Instruções de Projeto (v3 — 2026-07-16)

Documento de referência para qualquer chat/agente que trabalhe neste projeto. Se um
passo proposto violar alguma regra aqui, o passo está errado — não a regra.

Convenção desta versão: **[HOJE]** = implementado e verificado no código;
**[PRONTO-SEM-VALIDAR]** = código existe, nunca rodou de verdade;
**[ALVO]** = escopo do produto final, ainda não construído.
Misturar "é" com "será" foi o que inflou o status da v1. **v3 herda a mesma
disciplina da v2 — só atualiza os fatos, não a regra: "Status atual" descreve o
que foi verificado numa leitura ao vivo da trilha em 16/07 ~20:35 UTC, é uma
FOTO, não uma promessa. O detalhe minuto a minuto vive em `CLAUDE.md`, que
muda mais rápido do que este documento deveria.**

## Status atual (fatos verificados em 2026-07-16 ~20:35 UTC)

- **Fase 1 — EM FECHAMENTO, mais perto do que ontem mas ainda não fechada.**
  O motor rodou AO VIVO (`dry_run: False`) em testnet, mercado SPOT, em 4
  sessões no dia 16/07 (a última: 17:05 UTC até pelo menos 20:35, ~3h30
  contínuas, sem `engine_stop`). Mesmo assim, **zero `order_executed`** na
  trilha — o mercado ficou "FLAT" o dia todo (sem cruzamento EMA/RSI) e
  BTC/USDT está travado desde 19:29 UTC por "posição já aberta" sem nenhum
  `signal_approved` correspondente hoje. Hipótese não confirmada: saldo de
  BTC/ETH de brinde da testnet (pré-requisito da Etapa B-spot, PASSO-A-PASSO.md
  item B1) não foi vendido antes do pivô pra spot, e virou pseudo-posição.
  1 `cycle_error` isolado (Bybit 503, autorrecuperado). Kill switch não
  disparou. **Critério de fechamento (ver seção 7) continua não atendido:
  falta uma ordem + stop reais confirmados na exchange.**
- **Fase 2 — EXECUTADA em 15/07 (~20:15 UTC) com dados reais da mainnet.**
  Veredito out-of-sample: SEM EDGE em todos os cenários — o esperado; a régua
  foi validada e corrigida (fixes #12–#15, ver `CLAUDE.md`). Falta o carimbo
  formal do Lucas aceitando a régua (critério da seção 7 ainda pendente nesse
  detalhe, embora o processo já tenha rodado).
- **Fase 3 — PRONTO-SEM-VALIDAR (sem mudança desde 15/07).** `LLMStrategy`
  implementada com todas as salvaguardas (falha→FLAT, dupla barreira); nunca
  ativada (`decision.strategy: deterministic`). Provedores macro/on-chain
  passaram de stub-sempre-vazio para um pipeline real (dossiê diário via
  tarefa agendada do Cowork, gravando em `data/context/latest.json`), mas o
  dado só ganha efeito quando `decision.strategy: llm` — hoje é inerte.
- **Fase 4 — FECHADA.** `mcp_server.py` registrado via `.mcp.json` (Cowork,
  não Claude Desktop clássico — caminho documentado mudou) e validado em
  16/07 com dados reais batendo com a trilha (`trader_get_status`,
  `trader_halt_status`, `trader_get_positions`).
- **Fase 5 — BLOQUEADA**, e o bloqueio deixou de ser uma pendência formal:
  confirmado em 15/07 que a Bybit está descontinuando derivativos/margem para
  residentes do Brasil (migração compulsória para a entidade Bybit Brasil;
  ~20/07/2026 modo close-only, 21/09/2026 liquidação forçada, 24/09/2026
  migração). **Decisão #E tomada e implementada:** pivô para o mercado SPOT
  (`market.type: "spot"` no YAML) como caminho pra seguir validando o
  executor dentro da lei — em teste ao vivo desde 16/07 (ver Fase 1 acima).
- Todo o escopo marcado [ALVO] neste documento (universo completo, ranking,
  infra 24/7, regime, decaimento): **não existe no código ainda**.
- **Limpeza de contexto feita em 16/07:** removidos do Claude Projects 7 docs
  `__init__.py` vazios/duplicados e `COMISSIONAMENTO.md` (órfão, superseded
  por `CLAUDE.md` + `PASSO-A-PASSO.md`); `risk_config.yaml` e `README.md`
  ressincronizados com o conteúdo local (estavam de antes do pivô pra spot);
  `CLAUDE.md` e `PASSO-A-PASSO.md` anexados pela primeira vez.

## 1. Objetivo do projeto

Sistema de decisão assistida por IA com execução automatizada e supervisão humana,
para day trade + swing trade de cripto na Bybit. Full-auto com guardrails. Começa
em testnet, só migra para capital real depois que cada fase anterior fechar.

**Visão de produto (estado final):** o sistema varre os pares USDT da Bybit que
passarem num filtro de liquidez, roda análise completa por ativo (técnica + macro +
on-chain), opera micro-operações 24/7 em full-auto dentro dos guardrails, e devolve
ao usuário um **ranking diário de oportunidades por probabilidade ajustada a
risco**, com swing trade entrando como **sugestão confirmável**, não execução
automática.

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
[HOJE] REST via CCXT a cada ciclo (60s), 2 símbolos fixos (BTC, ETH perpétuo USDT),
candles 15m/4h, funding rate; indicadores EMA/RSI/ATR calculados localmente, nunca
pelo modelo.
[ALVO] WebSocket Bybit; universo completo de pares USDT (500+, muda toda semana);
**filtro de universo por liquidez** antes de qualquer par entrar no pipeline —
volume 24h mínimo, profundidade de book mínima, exclusão de recém-listados e de
funding anômalo (par ilíquido não é oportunidade, é armadilha de slippage); macro
(calendário econômico, DXY, juros, risk-on/off); on-chain (fluxo de exchanges,
stablecoin supply, realized cap, MVRV).

**2. Feature engineering**
[HOJE] snapshot de estado único, a MESMA estrutura no live e no backtest (fonte
única de indicadores — se divergissem, o backtest mentiria).
[ALVO] campos macro/on-chain reais no snapshot (estrutura já preparada), versionado.

**3. Camada de decisão**
[HOJE] estratégia determinística (EMA20/50 + RSI + stop 1,5×ATR) como trilho de
teste. [PRONTO-SEM-VALIDAR] `LLMStrategy` (Claude) com o mesmo contrato `Signal`.
[ALVO] Claude analisa cada par aprovado no filtro; um passo de **agregação/ranking**
ordena por convicção ajustada a risco e gera o "top N do dia"; daytrade full-auto
dentro dos guardrails; **swing vira sugestão com confirmação humana** (mecanismo:
decisão pendente #A, seção 10); para scalp de minutos, o **LLM fica fora do caminho
crítico** — define viés/regime em cadência lenta, timing fino é determinístico.

**4. Camada de risco — poder de veto absoluto**
[HOJE, implementado e testado]
- Risco por trade 0,5% do capital, nunca calculado pelo LLM.
- Sizing derivado da distância até o stop, não o contrário.
- Stop obrigatório e **dinâmico** (1,5×ATR — respira com a volatilidade; nunca
  percentual fixo). Sem stop, sem trade. Stop incoerente com a direção, veto.
- Kill switch por drawdown: 3% diário (marco refeito na virada do dia UTC) e 15%
  total. Reset SEMPRE manual.
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
- Kill switch com ou sem flatten (zerar posições): decisão pendente #B, seção 10.

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
[HOJE] trilha de auditoria `logs/audit.jsonl` com TODA decisão (aprovada, vetada,
pulada, executada, kill switch, erro); servidor MCP **próprio** (`wonder_trader`,
substituiu o plano do CCXT MCP genérico) com tools read-only + halt/reset por
arquivo de controle.
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
4. [ALVO] Confirmação de swing trade sugerido.

## 7. Plano de fases — estado real e critério de fechamento

| Fase | Escopo | Estado | Fecha quando |
|---|---|---|---|
| 1 | Motor determinístico + risco + execução testnet, 2 símbolos | **Em fechamento** — ao vivo rodando em spot, sem order_executed confirmado ainda | `--live` com ordem E stop confirmados na testnet (spot) — falta ainda |
| 2 | Backtest + walk-forward com dados reais | **Executada** (15/07, veredito SEM EDGE — esperado) | Régua de validação ratificada formalmente pelo Lucas (processo já rodou; falta o carimbo) |
| 3 | Decisão Claude em testnet/paper | Código pronto, desligado | LLM ligado, decisões auditadas, comportamento fail-safe confirmado (falha→FLAT) |
| 4 | Supervisão via MCP | **Fechada** — registrada via `.mcp.json` (Cowork) e validada com dados reais em 16/07 | — (critério atendido) |
| 5 | Capital real, size mínimo, 2 símbolos | **Bloqueada** (regulatória — confirmada, não só formal) | Checklist seção 5 completo + paper longo o bastante (seção 8, item 5) + situação Bybit Brasil resolvida |
| 6 | Expansão: universo completo + filtro de liquidez + ranking top-N + swing sugerido + infra 24/7 + regime + decaimento | [ALVO] não iniciada | Cada item validado em testnet antes de valer em capital real |

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
obrigatório; sizing pelo stop; kill switch diário/total com reset manual; limites
agregados intra-ciclo; exclusividade por símbolo; circuit breakers de funding e
feed; proteção de posição nua; idempotência + reconciliação; auditoria completa;
backtest/walk-forward sem lookahead com veredito honesto; MCP read-only.

**Pronto sem validar:** camada Claude (fail-safe→FLAT); walk-forward com dados
reais; MCP no Claude Desktop.

**Não existe ainda (o gap entre hoje e a visão):** varredura do universo USDT;
filtro de liquidez; ranking top-N por probabilidade ajustada a risco; calibração de
probabilidade; macro/on-chain reais (stubs); custo de operação no sinal live;
correlação do portfólio; Monte Carlo; detecção de regime; monitor de decaimento;
swing como sugestão confirmável; infra 24/7 (watchdog, restart, alerta ativo);
WebSocket; portfólio simulado no DRY_RUN (paper PnL entre ciclos).

## 10. Pendências e decisões em aberto

- **#A Mecanismo de confirmação do swing sugerido** — o MCP é read-only por
  princípio; a confirmação precisa de canal próprio (proposta: arquivo de aprovação
  local lido pelo engine, análogo ao `control.json`). Decidir antes da Fase 6.
- **#B Kill switch: com ou sem flatten?** Hoje trava entradas novas e NÃO fecha
  posições. Decidir se "zera exposição" vira comportamento real ou se o texto se
  ajusta ao atual.
- Situação regulatória Bybit/Brasil (bloqueia Fase 5).
- Ratificar os números de risco **em operação provisória** no YAML: 3% DD diário,
  15% total, 3 posições, 2× exposição, 2% risco agregado, 3x alavancagem, 0,5% por
  trade. Estão rodando em testnet; falta o carimbo de decisão consciente.
- Fonte on-chain: Glassnode/CryptoQuant pago vs. alternativa gratuita.
- Parâmetros do filtro de liquidez (volume mínimo 24h, profundidade mínima).
- Banda estatística do monitor de decaimento.
- Antes de mainnet: tirar o `.env` do OneDrive (secrets fora de pasta sincronizada).
- **NOVA (16/07): confirmar se o saldo de BTC/ETH de brinde da testnet foi
  vendido antes do pivô pra spot** (`python diag_saldo.py` com o loop parado).
  É a suspeita mais provável para BTC/USDT estar travado por "posição já
  aberta" sem nenhuma entrada aprovada pelo motor hoje. Bloqueia o
  fechamento da Fase 1 até resolver.
- **#E (venue/produto) já DECIDIDA e implementada em 15/07:** spot na Bybit,
  não perpétuos. Falta só fechar a validação do executor (ver Fase 1).

---
*Referência técnica interna do projeto — não é conteúdo institucional Wonder
BOAT/WonderHUB.AI nem recomendação de investimento.*
