# Bybit Auto Trader — Fase 1

Sistema de trading automatizado para Bybit com **execução full-auto sob guardrails
de risco** e supervisão humana. Arquitetura em camadas: o motor de decisão
**propõe** sinais; a camada de risco tem **poder de veto absoluto** e calcula
o sizing; o executor só envia ordens já aprovadas.

> **Fase atual:** estratégia determinística (sem LLM) + mainnet. Mercado religado
> para PERP (`market.type: "perp"` em `config/risk_config.yaml`, 28/07/2026) — o
> bloqueio de compliance da Bybit para derivativos em conta BR (visto em 15/07)
> não se repetiu; long e short confirmados ao vivo, ponta a ponta (entrada,
> trailing real, fechamento auditado, cooldown por símbolo), com dinheiro real.
> Teto de alavancagem 2x, teto de capital 50% do equity por trade (decisões do
> Lucas). O Claude entra na geração de sinal só na Fase 3, usando o mesmo
> contrato `Signal`.
>
> **Onde o motor roda (18/08/2026):** SOMENTE no **PC2** (`C:\BybitAutoTrader`),
> mainnet, `--live`, 24h. A pasta sincronizada (PC1) é **só dev/documentação** —
> as duas máquinas usam a MESMA conta mainnet, então rodar `--live` nas duas ao
> mesmo tempo é proibido por segurança. A trilha de auditoria que vale é a do
> PC2 (`C:\BybitAutoTrader\logs\audit.jsonl`); a do PC1 está congelada desde
> 31/07/2026. O `.mcp.json` do PC1 está **em standby** (aponta pra um caminho
> antigo que não existe mais) — o servidor MCP vivo é o do PC2.
>
> **Perfil de 15 minutos DESLIGADO em 18/08/2026**
> (`trading.profiles.daytrade.enabled: false`). Só o perfil `swing` (4h) opera.
> Causa: com o teto de nocional de 50% do equity mordendo em 90% dos sinais
> reais, o nocional fica constante e a fee vira fração fixa dele, enquanto 1R
> encolhe com a distância do stop — a identidade é `fee/R = 0,11% ÷ stop%`. Em
> 15m o stop mediano é 0,40% do preço, então a fee comia **~27% de cada 1R**;
> em 4h são ~7-9%. Medido em BTC+ETH nos últimos 12 meses, o perfil de 15m dava
> mediana −97,20%. **Espere bem menos operações — é o desenho, não falha.**
>
> **Resultado real até aqui (28/07 → 19/08, 53 trades com dinheiro real):**
> +2,59 USDT bruto / **−0,36 USDT líquido** de fee, win rate 34,0%. Ou seja:
> 22 dias de operação **ainda não pagaram a corretora** — a fee acumulada (2,95)
> é maior que todo o lucro bruto (2,59). Vale o contraste: **19/08 foi o melhor
> dia da conta** (9 trades, +6,42 líquidos, num melt-up de +5,9% em BTC e +8,8%
> em ETH) e sozinho tirou o acumulado de −6,5 para perto de zero — mas 6 trades
> de 53 responderam por todo o movimento, o que confirma a concentração que a
> pesquisa apontou como fragilidade, em vez de estabelecer edge.
> A engenharia está sólida (zero
> kill switch, zero posição nua, zero falha de fechamento, trailing e cooldown
> funcionando ao vivo); **a estratégia é que ainda não tem edge** — veredito
> reconfirmado por uma TERCEIRA rodada de pesquisa (18/08, perp long+short,
> painel adversarial de 9 agentes, decisão unânime de não promover). Ver
> `research/RELATORIO-2026-08-18-pesquisa-3-perp.md`.
>
> **Este README é referência de arquitetura/instalação, não status do dia.** Para
> o estado exato agora (o que rodou, o que travou, decisões em aberto), leia
> `CLAUDE.md` — é o handoff vivo, atualizado a cada sessão de trabalho.

## Princípio de design

```
dados de mercado ─▶ snapshot ─▶ ESTRATÉGIA (propõe Signal)
                                      │
                                      ▼
                              CAMADA DE RISCO  ◀── risk_config.yaml (não-negociável)
                              (veto absoluto + sizing pelo stop + kill switch)
                                      │  aprovado?
                                      ▼
                                  EXECUTOR ─▶ Bybit (testnet/mainnet)
                                      │
                                      ▼
                              audit.jsonl (trilha de toda decisão)
```

O LLM nunca toca na ordem. Ele produz um `Signal` estruturado; a camada de risco
valida contra limites hard-coded e **descarta** o que violar — sem negociar.

## Estrutura

```
Projeto Auto-trader/
├── main.py                     # ponto de entrada (--once / --live / --interval)
├── config/
│   ├── settings.py             # ambiente + credenciais (testnet/mainnet separados)
│   └── risk_config.yaml        # LIMITES DE RISCO — o coração do sistema
├── src/
│   ├── exchange/bybit_client.py   # wrapper CCXT (só fala com a exchange)
│   ├── data/market_data.py        # snapshot + indicadores (EMA/RSI/ATR)
│   ├── context/providers.py       # macro/on-chain/derivativos (dossiê 3x/dia + Bybit direto, decisão #G — inertes até a Fase 3 ligar)
│   ├── strategy/signal.py         # contrato Signal (fronteira decisão↔risco)
│   ├── strategy/deterministic.py  # estratégia Fase 1 (sem LLM; trailing stop + take-profit fixo convivem em produção)
│   ├── strategy/llm_strategy.py   # camada Claude (Fase 3, pronta/endurecida e desligada)
│   ├── risk/risk_manager.py       # guardrails + veto + kill switch + cooldown por símbolo
│   ├── execution/executor.py      # ordens idempotentes + stop obrigatório
│   ├── supervision/state_reader.py # leitura de estado para o MCP
│   ├── supervision/restart_policy.py # política de restart do supervisor.py
│   ├── backtest/                  # backtester + walk-forward (Fase 2)
│   ├── engine.py                  # loop principal
│   └── logger.py                  # console + trilha de auditoria JSONL
├── supervisor.py                # roda main.py com restart automático em crash (recomendado p/ produção)
├── mcp_server.py                # servidor MCP read-only (Fase 4)
├── CLAUDE.md                    # handoff vivo — estado exato, decisões, bugs
├── PASSO-A-PASSO.md             # guia operacional passo a passo (histórico — ver CLAUDE.md pro estado atual)
├── INSTRUCOES-PROJETO-v2.md     # charter original — regras inegociáveis (fatos atualizados nas RASCUNHO-instrucoes-vN)
└── logs/audit.jsonl             # gerado em runtime
```

## Instalação

```bash
cd "Projeto Auto-trader"
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
```

## Gerar chaves da TESTNET da Bybit (sem dinheiro real)

1. Acesse **https://testnet.bybit.com** e crie/entre numa conta de testnet
   (é separada da conta real; o login é independente).
2. No menu do perfil → **API** → **Create New Key**.
3. Escolha **System-generated API Keys**.
4. Permissões: marque **Contract / Trade** (e *Read*). **NÃO** habilite saque/withdraw.
5. Em *IP restriction*, restrinja ao seu IP se possível (boa prática).
6. Copie a **API Key** e o **API Secret** (o secret só aparece uma vez).
7. Cole no `.env`:
   ```
   ENVIRONMENT=testnet
   BYBIT_TESTNET_API_KEY=sua_key
   BYBIT_TESTNET_API_SECRET=seu_secret
   ```
8. Pegue saldo fictício na testnet: na interface, **Assets → Request a Coupon** /
   faucet de USDT de teste, para ter banca para o paper trading.

## Rodar

```bash
# 1 ciclo em DRY_RUN (não envia ordem — só mostra o que faria)
python main.py --once

# loop contínuo em DRY_RUN (paper trading), ciclo a cada 60s
python main.py

# executar ordens DE VERDADE na exchange configurada (testnet, enquanto ENVIRONMENT=testnet)
python main.py --live

# recomendado p/ produção: mesma coisa, mas religa sozinho se o processo cair por crash
python supervisor.py --live
```

`--live` com `ENVIRONMENT=testnet` envia ordens reais **na testnet** (dinheiro fictício).
Só passe para mainnet de forma deliberada — ver abaixo.

`supervisor.py` (novo) spawna `main.py` como subprocesso e o religa automaticamente
em caso de crash (nunca em parada manual — Ctrl+C encerra os dois juntos), com
backoff exponencial e um teto de tentativas por janela. Recomendado como forma
padrão de rodar em produção; `main.py` direto continua válido pra teste manual.

## Camada de risco (`config/risk_config.yaml`)

| Parâmetro | Padrão | O que faz |
|---|---|---|
| `market.type` | `"perp"` | `"perp"` (derivativos, long+short) ou `"spot"` (à vista); em spot, short é vetado e alavancagem forçada a 1 |
| `per_trade.risk_pct` | 0.5% | risco por trade; define o sizing pela distância do stop |
| `per_trade.require_stop_loss` | true | sem stop, o trade é vetado |
| `per_trade.max_leverage` | 2x | teto de alavancagem (irrelevante em spot) — `min(max_leverage, necessária)`, nunca forçado |
| `per_trade.max_notional_pct_equity` | 50% | teto de capital por trade individual (clampa, nunca veta) |
| `portfolio.max_open_positions` | 3 | nº máx. de posições simultâneas |
| `portfolio.max_total_exposure_mult` | 2.0 | exposição nocional máx. (× capital) |
| `drawdown.max_daily_drawdown_pct` | 3% | dispara **kill switch** (trava entradas) |
| `drawdown.max_total_drawdown_pct` | 15% | parada total |
| `circuit_breakers.*` | — | funding anômalo, feed defasado, slippage |

Observação: `circuit_breakers.max_abs_funding_rate_testnet` (0.01) vale SÓ com
`ENVIRONMENT=testnet` — na testnet o funding vive no clamp da exchange (±0.005)
por book raso, o que vetaria toda entrada da Fase 1. A mainnet usa o limiar
estrito `max_abs_funding_rate` (0.003).

O **kill switch** só é resetado **manualmente** (`RiskManager.reset_kill_switch()`),
nunca de forma automática. Mudar qualquer limite é ação manual e deliberada.

## Backtest (Fase 2)

Valida a estratégia em dados históricos **antes** de qualquer execução ao vivo.
Reutiliza o MESMO `RiskManager` e o MESMO contrato `Signal` do live — se divergissem,
o backtest mentiria. Os dados vêm do endpoint **público** da Bybit (não precisa de chave)
e ficam em cache em `data/`.

```bash
# baixa ~1500 candles de 15m e roda o backtest
python run_backtest.py --symbol "BTC/USDT:USDT" --timeframe 15m --candles 1500

# perfil swing em 4h
python run_backtest.py --profile swing --timeframe 4h --candles 1500

# usar um CSV próprio (colunas: ts,open,high,low,close,volume)
python run_backtest.py --csv data/meus_dados.csv --timeframe 15m
```

Cuidados embutidos contra auto-engano: sem **look-ahead** (decisão no candle i,
entrada no open de i+1), custos de **taxa** e **slippage** aplicados, e o mesmo veto
de risco do live. O relatório traz retorno, **max drawdown**, win rate, **profit factor**
e **expectativa por trade** — mais um veredito honesto (ex.: "SEM EDGE — não operar").

> A estratégia EMA+RSI atual é um **trilho de teste**, não uma tese com edge provado.
> Rodada em 15/07 com dados reais: SEM EDGE em todos os cenários out-of-sample —
> esperado; o que se validou foi a régua de medição, não a estratégia. O valor real
> vem da Fase 3 (decisão do Claude) sobre esta fundação de risco e backtest.

### Walk-forward (validação out-of-sample)

Um backtest simples pode enganar: otimizando parâmetros nos mesmos dados que você
mede, sempre acha uma combinação que "funciona" — ajuste ao ruído do passado, não
edge real. O walk-forward corta os dados em janelas sequenciais: **otimiza** os
parâmetros no in-sample (IS) e **valida** no out-of-sample (OOS) que o otimizador
nunca viu. O número honesto é o **agregado OOS**; a **degradação IS→OOS** mede o
overfitting.

```bash
python run_walkforward.py --symbol "BTC/USDT:USDT" --timeframe 15m --candles 3000
python run_walkforward.py --profile swing --timeframe 4h --candles 3000 --is 300 --oos 100
```

O relatório traz, por fold, os melhores parâmetros do IS e o resultado no OOS, mais
o agregado OOS e um alerta quando a degradação indica overfitting. Os folds rolam no
tempo — o OOS de um fold é sempre posterior ao seu IS, sem vazamento de futuro.

> **Sempre valide qualquer estratégia aqui antes de operá-la** — inclusive a do
> Claude na Fase 3. Uma estratégia que só brilha no in-sample não vai pra testnet.

## Camada de decisão do Claude (Fase 3)

A decisão pode vir de duas camadas, selecionadas em `config/risk_config.yaml` →
`decision.strategy`:

- `deterministic` — a estratégia de regras (Fases 1/2). **Ativa hoje.**
- `llm` — o Claude analisa o estado de mercado + contexto (macro/on-chain) e
  devolve um `Signal` estruturado. Código pronto, ainda desligada.

```yaml
decision:
  strategy: "llm"          # ou "deterministic"
  llm:
    model: "claude-sonnet-5"
    temperature: 0.2
    min_conviction: 0.6    # abaixo disso, tratado como flat
```

Requer o pacote `anthropic` e a variável `ANTHROPIC_API_KEY`.

**Por que é seguro plugar um LLM no gatilho:** o Claude decide apenas **direção** e
**convicção** — nunca tamanho nem alavancagem. A `LLMStrategy` implementa o mesmo
contrato `Signal`, então entra no engine, no backtester e no walk-forward sem mudar
mais nada. E há **duas barreiras independentes**: qualquer resposta ambígua, JSON
inválido, stop ausente/incoerente, convicção baixa ou erro de API vira `FLAT`
(nunca opera na dúvida); e mesmo um `Signal` válido ainda passa pela camada de
risco, que veta e recalcula o sizing.

**Contexto macro/on-chain:** `src/context/providers.py` traz a interface e stubs
seguros (retornam `{}`). Ligue Glassnode/CryptoQuant/calendário econômico
implementando `fetch()` — dado ausente nunca derruba o ciclo, e o Claude é instruído
a ser conservador quando o contexto está incompleto.

> **Cuidado com backtest de LLM:** rodar a `LLMStrategy` sobre dados históricos tem
> risco de vazamento (o modelo pode "conhecer" o que aconteceu depois do candle) e
> custo alto por chamada. Valide a decisão do Claude **para frente** (paper/testnet),
> não por backtest histórico. O walk-forward é a ferramenta para estratégias de regra.

## Supervisão via MCP (Fase 4)

"Full-auto" não significa caixa-preta. Este servidor MCP expõe o estado do sistema
ao Claude, para você perguntar em linguagem natural: *"como está o PnL?"*, *"quais
posições estão abertas?"*, *"por que entrou nesse short de ETH?"*, *"o kill switch
disparou?"*. A base de tudo é a trilha de auditoria (`logs/audit.jsonl`), onde cada
decisão — aprovada, vetada, executada, o racional do LLM, o kill switch — fica
registrada.

```bash
pip install "mcp[cli]"
python mcp_server.py          # roda o servidor (stdio)
```

Registro (Cowork/Claude Code registra por projeto via `.mcp.json` na raiz — é o
caminho ativo; `claude_desktop_config.json` do Claude Desktop clássico é uma
alternativa, não use os dois ao mesmo tempo apontando pastas diferentes):

```json
{
  "mcpServers": {
    "wonder_trader": {
      "command": "./.venv/Scripts/python.exe",
      "args": ["./mcp_server.py"]
    }
  }
}
```

Tools expostas:

| Tool | Tipo | O que responde |
|---|---|---|
| `trader_get_status` | leitura | equity, ambiente, PnL não realizado |
| `trader_get_positions` | leitura | posições abertas |
| `trader_recent_decisions` | leitura | últimas decisões (aprovado/vetado/executado/LLM) |
| `trader_explain_symbol` | leitura | o **porquê** das decisões de um símbolo |
| `trader_halt_status` | leitura | se/por que o kill switch disparou |
| `trader_realized_pnl` | leitura | PnL realizado (visão pela trilha) |
| `trader_request_halt` | controle | pausa novas entradas (kill switch manual) |
| `trader_request_reset` | controle | retoma entradas (exige `confirm=true`) |

**Fronteira de segurança:** não existe tool para abrir/fechar posição, enviar ordem
ou mover fundos. Execução de trade nunca passa pelo MCP — por princípio. As únicas
ações de controle são **parar** e **retomar** o sistema, e elas apenas gravam um
sinal em `state/control.json` que o engine lê e aplica no próximo ciclo (o MCP não
controla o processo do engine diretamente — fronteira limpa).

## Roadmap

Numeração oficial de fases em `INSTRUCOES-PROJETO-v2.md` (seção 7) — é a fonte da
verdade sobre o que fechou; `CLAUDE.md` tem o estado exato do dia. Resumo:

- **Fase 1** — motor determinístico + risco + execução em testnet: **fechada
  (19/07)** — entrada, proteção e saída lucrativa automática confirmadas 1:1
  contra a exchange real.
- **Fase 2** — backtest + walk-forward com dados reais: rodada em 15/07 + **três**
  rodadas de pesquisa de estratégia (21/07, 22/07 e 18/08); veredito final "sem
  edge, não promover" nas três, sempre após verificação adversarial. A rodada de
  18/08 foi a primeira a medir a configuração REAL de produção (perp long+short,
  fee 0,055%) — as duas anteriores mediam spot long-only com fee 0,1%, ou seja
  metade do sistema. **Achado que muda o método daqui pra frente:** o critério
  de aceitação que vinha sendo usado ("mediana > 0 com maioria dos símbolos
  positiva") **não discrimina nada** — uma grade ingênua de 300 configurações de
  tendência dá 100% de medianas positivas na mesma janela. Foi ele que aprovou
  os falsos positivos das três rodadas. Ver
  `research/RELATORIO-2026-08-18-pesquisa-3-perp.md` para o critério novo exigido.
- **Fase 3** — camada de decisão Claude: código pronto e **endurecido** (revisão
  adversarial de 22/07, 15 achados corrigidos), ainda **desligada**
  (`decision.strategy: deterministic`).
- **Fase 4** — supervisão via MCP: servidor registrado e validado ponta a ponta;
  ganhou watchdog agendado + restart automático do processo (`supervisor.py`).
- **Fase 5** — mainnet, size mínimo: **iniciada em 27/07/2026** (spot, ~24 USDT
  de equity, decisão explícita do Lucas). **Religado para PERP em
  28/07/2026** — o bloqueio de compliance de 15/07 para derivativos em
  conta BR não se repetiu (confirmado por sonda antes da virada); teto de
  alavancagem 2x e teto de capital 50%/trade. **Ciclo completo validado ao
  vivo nos dois lados (29-30/07/2026)**: entrada, trailing real (moveu
  várias vezes seguidas), fechamento auditado com PnL correto, cooldown
  escalando pelos 3 níveis (30min/60min/24h) no mesmo dia, e reset manual
  de cooldown via MCP — tudo confirmado em LONG e em SHORT, com dinheiro
  real. Ver `CLAUDE.md` ("Sessão 29-30/07/2026") pro relato completo.
  **Operação 24h migrada para o PC2 em 31/07/2026** (mesma conta mainnet —
  o PC1 nunca mais roda `--live` sem parar o PC2 antes). **22 dias contínuos
  até 19/08/2026**: 53 trades reais, mecânica impecável (zero kill switch,
  zero posição nua, zero falha de fechamento; um único crash de console
  religado sozinho pelo `supervisor.py`). **PnL líquido em −0,36 USDT** —
  praticamente zero, com a fee acumulada (2,95) maior que todo o lucro bruto
  (2,59). Perfil de 15m desligado em 18/08 por fricção estrutural (ver topo
  deste README); as entradas novas do swing passaram a pagar ~8-9% de 1R em
  fee, contra os ~27% do perfil de 15m. Diagnóstico completo em `CLAUDE.md`.
- **Fase 6** — expansão (universo completo, ranking, infra 24/7): alerta ativo
  + restart automático feitos; fonte on-chain em tempo real (decisão #G)
  implementada; resto (universo, ranking) não iniciado. O dossiê agendado
  (`dossie-cripto-pc2`) segue ligado, mas o **watchdog (`trader-watchdog-pc2`)
  está EM STANDBY desde 18/08/2026** por decisão do Lucas — **não há mais
  supervisão automática fora de sessão**. Dentro de uma sessão dá para armar um
  monitor na trilha (que também precisa vigiar ausência de batimento: se o motor
  morre, a trilha só para de crescer, e um filtro que só procura erro fica mudo).

Não marque uma fase como concluída aqui sem checar o critério de fechamento na
seção 7 de `INSTRUCOES-PROJETO-v2.md` — um Roadmap desatualizado com ✅ prematuro
foi exatamente o tipo de confusão que gerou a v2 das instruções do projeto.

## Avisos

- O sistema **não** executa saques nem move fundos — só abre/fecha posições.
- Mainnet = dinheiro real. Confirme a situação regulatória da Bybit para residentes
  no Brasil antes de operar com capital real.
- Mantenha o kill switch manual acessível. "Full-auto" não significa "sem operador".
