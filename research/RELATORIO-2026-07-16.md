# Pesquisa de estratégia — 6 meses spot, 6 pares (16/07/2026)

**Pergunta do Lucas:** com base no histórico de 6 meses de BTC, ETH, SOL, XRP,
MNT e BNB (par USDT), qual a melhor estratégia de day trade / swing trade para
lucrar na compra e na venda em SPOT?

**Resposta curta: nenhuma das 108 combinações testadas (6 famílias de
estratégia) mostrou edge negociável nesta janela — e a janela foi 100% bear.
Day trade em 15m é matematicamente inviável com custo spot (0/108 combinações
positivas). A estratégia atual do robô é a PIOR das 6 famílias testadas. Em
spot não existe "lucro na venda" (short é impossível); em mercado de queda, a
melhor posição foi ficar em caixa (USDT) — que foi exatamente o que os stops e
vetos fizeram.**

## Metodologia

- Dados: 6 meses de OHLCV SPOT da mainnet pública Bybit (12/01–16/07/2026),
  15m/1h/4h, baixados por `research/download_data.py` (candle em formação
  descartado, sem gaps/duplicatas — auditado).
- Motor: `research/harness.py` — long-only (spot), fill no open do candle
  seguinte, stop prioritário sobre TP, gap-through no stop preenche no open
  (mais conservador que o backtester oficial), fee 0,1%/lado + slippage
  0,02%/lado, risco 0,5% do equity por trade, teto de nocional = caixa.
- Paridade com o backtester oficial do projeto: verificada exata (diferença
  0,0000 USDT em 18/18 séries para a estratégia do robô).
- 6 famílias × 108 combinações: ema_cross, donchian (rompimento), rsi_mr e
  bollinger_mr (reversão à média), momentum (ROC), robot_baseline (a
  EMA20/50+RSI atual do robô, com a grade do walk-forward oficial).
- Validação: split IS/OOS 70/30 + walk-forward por família (IS 90d → opera 18d
  às cegas, 5 folds, seleção por t-stat com mín. 8 trades no IS).
- Verificação adversarial multi-agente (9 agentes): 3 auditorias (look-ahead,
  custos/fill, metodologia estatística), benchmark buy & hold, 3 refutadores
  dos resultados positivos, 1 refutador da conclusão negativa, 1 crítico de
  completude. Scripts reproduzíveis em `research/scratch/`.

## Resultados principais

### O regime: 6 meses de bear market (a régua que importa)

Buy & hold nos 6 meses: BTC **-29,7%**, ETH **-40,2%**, SOL **-46,1%**,
XRP **-47,4%**, MNT **-55,0%**, BNB **-36,5%**. Na janela operada pelo
walk-forward (11/04→10/07): BTC -12,6%, ETH -21,8%, SOL -8,3%, XRP -18,8%,
MNT -37,0%, BNB -5,7%. Ficar 100% em USDT (0%) ganhou de quase tudo.

### Walk-forward por família (mediana das 18 séries símbolo×timeframe)

| Família        | Mediana WF | Séries positivas |
|----------------|-----------:|-----------------:|
| bollinger_mr   |     -0,02% |             3/18 |
| donchian       |     -1,42% |             4/18 |
| rsi_mr         |     -2,12% |             0/18 |
| momentum       |     -2,60% |             0/18 |
| ema_cross      |     -2,94% |             3/18 |
| **robot_baseline (atual)** | **-3,40%** | **0/18** |

Por timeframe (mediana WF): 15m **-6,8%** | 1h -2,0% | 4h -0,4%.

### A estratégia atual do robô, OOS (~54 dias finais), por símbolo

Em 15m: -29% a -39% em TODOS os 6 símbolos (PF 0,43–0,57, win rate ~28–34%),
sendo **60–95% da perda pura taxa** (ex.: BTC -357,90 USDT dos quais 283,50
foram fees em 189 trades). Em 1h: -5% a -9%. Em 4h: -0,3% a -4,2% (poucos
trades). Conclusão dupla e verificada por vias independentes: (a) 15m tritura
a conta por fricção — 0/108 combinações com mediana OOS positiva; (b) a regra
EMA20/50-regime + RSI é a pior família testada (é a única sem saída por sinal,
o que gira fees no stop/TP sem nunca sair "de graça").

### Os poucos resultados positivos — todos refutados (confiança alta)

- MNT 1h ema_cross (+3,2% WF): 91% do PnL vem de 1 único trade; t-stat ~0,4;
  a mesma combinação perde nos outros 5 símbolos. Sorte, não edge.
- MNT 15m bollinger_mr (+2,8% WF): refutado (concentração + custos 15m).
- XRP 1h donchian / BNB 1h ema_cross: refutados (concentração de PnL,
  instabilidade de parâmetros, beta de regime).
- As 5 células positivas restantes: todas colapsam sem o melhor trade
  (t-stats 0,06–0,55), exceto SOL 1h bollinger que não colapsa mas tem 9
  trades e é 1 célula em 108 comparações — ruído estatístico.
- Zero de 324 células combo×timeframe são positivas em IS **e** OOS de forma
  consistente entre símbolos.

## Limitações honestas (obrigatórias ao citar este relatório)

1. O veredito é **"sem edge long-only detectável NESTA janela de 6 meses 100%
   bear, com custos spot reais"** — não "edge não existe". Famílias de trend
   merecem re-teste em janela com regime de alta/misto (2+ anos de histórico).
2. **Este dataset está queimado para seleção**: o OOS foi inspecionado por ~9
   agentes; qualquer hipótese nova exige dados novos (histórico mais longo ou
   forward). As ~10 células positivas do full_grid NÃO são candidatas — são o
   que ruído produz sob 108+ testes.
3. A coluna `pos_folds` de wf_results.csv tem bug de contabilidade (66/108
   errados — contava cumulativo, não o fold); `wf_ret_pct` e todas as demais
   métricas foram reverificadas e estão corretas. São 5 folds, não 6.
4. `max_dd_pct` carrega um vazamento de mark-to-market de 1 candle (auditoria
   look-ahead; ~bps em dados reais) — não usar max_dd para decisão sem nota.
5. **Executabilidade**: as famílias com saída por sinal/trailing não são
   expressáveis no contrato Signal/RiskManager atual, e o executor spot PULA o
   TP por desenho (`take_profit_skipped`). Mesmo um vencedor não seria operável
   como backtestado sem código novo — pré-condição de engenharia para qualquer
   promoção futura de estratégia.
6. Vieses residuais do motor são CONSERVADORES (stop antes de TP, gap-through
   no stop, TP sem melhora de gap) — o "sem edge" é teto, não piso.

## Recomendações práticas (decisão é do Lucas; nada foi alterado no robô)

1. **Não promover nenhuma estratégia agora.** Nada aqui merece dinheiro real.
2. **Esquecer day trade 15m em spot** enquanto a fee for 0,1%/lado — qualquer
   regra precisa ganhar >>0,24% por rodada só para empatar; 0/108 conseguiram.
3. A Etapa B-spot continua valendo como **teste de encanamento** (validar
   executor/stop reais) — o objetivo dela nunca foi lucro.
4. Se/quando for ajustar estratégia (decisão já adiada pelo Lucas para depois
   da estruturação): re-testar famílias de trend (donchian/ema com saída por
   sinal) em 1h/4h com 2+ anos de dados, e resolver antes a pendência de
   executabilidade (item 5 acima).
5. Em spot, "lucrar na venda" = realizar o lucro da compra. Em queda, a única
   defesa é caixa — os vetos/stops do robô já fazem isso. Short exigiria
   derivativos (bloqueados para residente BR na Bybit — nunca contornar).

*Análise estatística sobre dados históricos para pesquisa do projeto; não é
recomendação de investimento. Desempenho passado não garante resultado futuro.*

## Arquivos

- `research/download_data.py`, `harness.py`, `sweep.py`, `parity_check.py`
- Resultados: `research/results/{full_grid.csv, wf_results.csv, summary.json,
  verificacao_agentes.json}`
- Verificações dos agentes: `research/scratch/*.py`
- Dados: `research/data/*.csv` (spot mainnet, 12/01–16/07/2026)
