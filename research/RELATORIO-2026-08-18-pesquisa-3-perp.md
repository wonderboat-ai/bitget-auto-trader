# Pesquisa 3 — PERP long+short, dado novo, 8 símbolos (18/08/2026)

**Pergunta do Lucas:** "analise as outras 5 estratégias, qual podemos tentar
rodar um teste na mainnet agora" + "ajustar a margem do trailing stop para não
ser fisgado em cada agulhada no mercado lateral".

**Resposta curta:**

1. **Nenhuma das 5 outras famílias está pronta para capital real** — veredito
   unânime de um painel de 9 agentes que recomputou tudo do zero. O que parecia
   edge (+9 a +11% em 4h) não sobrevive a três testes: **uma grade ingênua de
   300 configurações dá 100% de medianas positivas na mesma janela** (ou seja,
   o critério não discrimina nada); **o resultado já é negativo nos últimos 12
   meses**, que é o regime em que o robô opera hoje; e **remover 1 único trade
   por símbolo** derruba o melhor candidato de +336,65R para −12,75R.
2. **A estratégia em produção é, de novo, a pior de todas** — agora em um 4º
   dataset independente e em 4 metodologias. E o contraste que decide a
   prioridade: a evidência de que ela **perde** é estatisticamente mais forte
   (4/8 séries com |t| ≥ 2) do que a de que qualquer candidata **ganha** (0/8).
3. **Uma mudança tem evidência que se sustenta em todas as janelas: desligar o
   perfil 15m.** Nos últimos 12 meses, em BTC+ETH, ele mede **−97,20%** com
   9.401 trades e 1.317 USDT de fee. Ele responde por metade dos trades reais.
4. **A hipótese da "agulhada" não se confirma nos dados reais**: 90,6% das
   saídas ocorreram com recuo de 0,95–1,05R do pico — o stop faz exatamente o
   que foi configurado. O trailing prejudica por **churn/fee**, não por ser
   fisgado. E esse prejuízo **inverteu no semestre corrente**, então mexer nele
   agora não tem suporte.
5. **Correção de uma premissa desta rodada:** long+short **não** é melhor que
   long-only (+9,86% vs +13,34%), e spot long-only com fee de 0,1% rende ainda
   mais. A diferença desta rodada não é perp/short/fee — é dado novo + regra de
   saída nova.

---

## 1. O que esta rodada faz de diferente

As duas rodadas anteriores (`RELATORIO-2026-07-16.md`, `RELATORIO-2026-07-21-pesquisa-2b.md`)
mediram **SPOT LONG-ONLY com fee 0,1%/lado**. A produção real desde 28/07/2026 é
**PERP LONG+SHORT com fee taker 0,055%/lado**, alavancagem até 2x e teto de
nocional de 50% do equity. **Nenhuma rodada anterior mediu essa configuração** —
as duas mediam metade do sistema. Um resultado long-only não diz nada sobre uma
estratégia que também vende a descoberto: o mesmo sinal que antes significava
"ficar em caixa" (custo zero) agora vira uma posição short com fee e funding.

- **Dados novos**: `research/data_3/` — 8 símbolos (BTC, ETH, SOL, XRP, BNB,
  DOGE, ADA, LINK), 1h/4h de 2023-08-19 a 2026-08-18 (3 anos), 15m de 2 anos,
  + histórico completo de funding. 849.841 linhas, **zero gaps, zero
  duplicatas**, candle em formação descartado. Os datasets antigos estão
  queimados para seleção e terminam em 21/07 — não cobrem a janela em que o
  motor operou em perp.
- **Motor novo**: `research/harness_perp.py` — long **e** short no mesmo passe,
  one-way mode (como o live), fee 0,055%/lado, slippage 0,02%/lado, funding real
  a cada 8h, risco 0,5%/trade, teto de nocional 50%, alavancagem 2x.
- **8 símbolos em vez de 5-6** — recomendação direta do painel de juízes de
  22/07.
- **Janelas de walk-forward dessincronizadas por símbolo** — corrige a falha de
  desenho que derrubou a promoção de donchian/4h em 22/07 (o crash de
  10/10/2025 caía na mesma janela OOS de todos os símbolos ao mesmo tempo).

### Validação do motor (o que nenhuma rodada anterior fez)

Toda paridade anterior comparou backtester × harness — duas simulações podem
concordar e estar erradas juntas. Aqui a régua é a realidade:

- **`research/selftest_harness_perp.py`: 35/35.** Séries sintéticas com resposta
  conhecida na mão, cobrindo anti-look-ahead, fee dos dois lados, gap-through,
  trailing (sobe, nunca desce, passo mínimo), short como espelho do long, sinal
  do funding, teto de nocional e one-way mode.
- **`research/validate_harness_perp.py`**: roda a config EXATA de produção na
  janela EXATA dos 43 trades reais e compara com a trilha de auditoria.
  Resultado no perfil **swing (4h)**: R/trade **−0,397 simulado × −0,466 real**,
  win rate **20,5% × 21,1%**. O motor mede a coisa certa em 4h.
  No perfil **daytrade (15m)** o simulado é bem pior que o real (−0,774 × −0,150)
  por dois motivos conhecidos e ambos **conservadores**: o live tem cooldown
  (pausa após cada stop) que filtra reentradas, e amostra preço a cada ~62s
  (trailing mais fino) enquanto o replay só vê o candle. **Números de 15m devem
  ser lidos como piso, não como estimativa central.**

---

## 2. Erro metodológico encontrado e corrigido no meio da rodada

A primeira versão da varredura de saída segmentava o backtest em janelas de 18
dias e **fechava a posição a mercado no fim de cada janela** (`eod`). Isso
inventa uma saída que não existe na regra. Numa configuração
(`robot_live` sem TP e sem trailing) esse fechamento artificial respondia por
**26% de todos os fechamentos** — e essa configuração aparecia como a melhor de
toda a varredura. Refeito como **rodada contínua** (`eod` ≤ 0,5%), a
configuração caiu para o meio da tabela.

Registrado aqui porque é exatamente a classe de erro que já contaminou este
projeto duas vezes: **um número bom que vem do arcabouço de medição, não da
estratégia.**

---

## 3. Resultados

### 3.1 O timeframe é o eixo dominante

Walk-forward com seleção por fold, 6 famílias × 8 símbolos, mediana das séries:

| timeframe | mediana WF | R/trade | séries positivas |
|---|---:|---:|---:|
| 4h | −0,89% | −0,0074 | 21/48 |
| 1h | −12,48% | −0,0539 | 6/48 |
| 15m | −20,61% | −0,1175 | 1/48 |

**15m é inviável em todas as famílias.** No holdout, a configuração de produção
em 15m dá **mediana −96,36%, 0/8 símbolos, 35.255 trades e 5.441 USDT de fee
sobre 1.000 de capital inicial**. Não é ajuste fino: é o perfil inteiro.

### 3.2 Walk-forward em 4h, por família

| família | mediana WF | positivas | R/trade |
|---|---:|---:|---:|
| donchian | **+4,49%** | 6/8 | +0,056 |
| bollinger_mr | +0,12% | 4/8 | +0,003 |
| momentum | −0,73% | 3/8 | +0,026 |
| rsi_mr | −1,00% | 4/8 | −0,055 |
| ema_cross | −2,08% | 3/8 | +0,005 |
| **robot_live (produção)** | **−10,66%** | **1/8** | **−0,048** |

### 3.3 Teste de holdout limpo (`research/holdout_3.py`)

Parâmetro escolhido **mecanicamente** só no primeiro trecho (até 2025-04-12),
avaliado no trecho final que a regra de escolha nunca viu:

| família | config escolhida | holdout | positivas |
|---|---|---:|---:|
| ema_cross | ema9/120 stop 1,5 | +4,96% | 7/8 |
| donchian | don150/20 stop 1,5 | +2,46% | 6/8 |
| rsi_mr | rsi20/60 stop 2,0 | +1,07% | 6/8 |
| momentum | mom12/5.0 stop 2,0 | +0,04% | 4/8 |
| bollinger_mr | bb3.0/band stop 3,0 | −0,30% | 4/8 |
| **robot_live** | — | **−1,66%** | 2/8 |
| **produção exata (stop1,5 tp2 trail1,5)** | — | **−8,73%** | **0/8** |

**Achado estatístico mais importante da rodada:** a correlação entre desempenho
no trecho de escolha e no holdout é **Pearson r = −0,05 (n=107 configurações)**.
Ou seja: **escolher parâmetro por desempenho histórico não tem poder preditivo
nenhum.** Qualquer número de "melhor parâmetro" nesta pesquisa — inclusive os
desta tabela — é sorte de célula. O que sobrevive é ESTRUTURA, não parâmetro.

### 3.4 A decomposição que derruba a promoção

Período completo (3 anos), 4h, 8 símbolos:

| config | só LONG | só SHORT | ambos |
|---|---:|---:|---:|
| ema9/120 + saída por sinal | **+27,56%** (8/8, R/tr +0,871) | +0,90% (6/8, R/tr +0,020) | +23,22% |
| ema30/80 + saída por sinal | +18,68% (8/8) | −2,55% (3/8) | +14,65% |
| ema20/50 + saída por sinal | +13,34% (8/8) | −3,14% (1/8) | +9,86% |
| donchian 100/20 | +15,67% (8/8) | −1,59% (1/8, R/tr −0,150) | +10,59% |

**O lado SHORT não tem edge em nenhum candidato.** Todo o resultado é do lado
LONG. E por regime:

| config | BULL (→2025-09, buy&hold ~+300%) | BEAR (2025-09→, buy&hold −59,9%) |
|---|---:|---:|
| ema9/120 | +23,70% (8/8) | **+1,93% (6/8)** |
| ema30/80 | +13,74% (8/8) | −0,48% (4/8) |
| ema20/50 | +15,40% (8/8) | −2,91% (2/8) |
| donchian 100/20 | +10,22% (8/8) | −0,81% (3/8) |
| **produção** | **−22,51% (0/8)** | **−6,21% (1/8)** |

Duas leituras obrigatórias:

1. **O ganho é beta de alta.** No bull, os candidatos rendem +10 a +24% enquanto
   **segurar o ativo rendeu ~+300%** — capturaram menos de 10% do movimento. É
   o mesmo padrão que a pesquisa 2b já tinha identificado e recusado.
2. **Só ema9/120 sobrevive ao bear** (+1,93%, 6/8, R/trade +0,047) — e é 1
   configuração entre 107 testadas, com r≈0 de poder preditivo. Não é base para
   capital.

---

## 4. O trailing stop — resposta à pergunta do Lucas

### 4.1 A hipótese da "agulhada" NÃO se confirma

Medido nos **trades reais** (32 pareados com `trailing_stop_moved` na trilha):

- **90,6% das saídas ocorreram com recuo de 0,95–1,05R do pico** — exatamente a
  distância do trailing, toda vez. Se o stop estivesse sendo fisgado por
  agulhadas curtas, o recuo seria muito menor que 1R.
- MFE mediano: **+0,597R**. Máximo em 43 trades: **+1,777R**.
- Só **31%** dos trades chegaram a MFE ≥ 1,00R — que é o mínimo para o stop
  movido passar do breakeven. Nos outros 69%, o trailing **só reduziu a perda**
  (perda média real −0,703R em vez de −1R).

Ou seja: o stop não está sendo fisgado; ele está fazendo exatamente o que foi
configurado. O problema é que o preço raramente anda a favor o suficiente.

### 4.2 Mas o trailing É prejudicial — por churn, não por agulhada

Rodada contínua, 4h, 8 símbolos:

| base | sem trailing | com trailing 1,5 |
|---|---:|---:|
| donchian 55/20 | +9,15% · R/tr **+0,2025** · 781 trades | +1,06% · R/tr **+0,0099** · 1.401 trades |
| ema20/50 | +9,86% · R/tr +0,2175 · 1.548 trades | −5,08% (trail 3,0) · R/tr −0,0076 · 3.075 trades |

O trailing **quase dobra o número de trades** e corta os poucos ganhadores
grandes — que são a fonte inteira do edge em seguidor de tendência. O R/trade
cai ~95%.

Na configuração de produção (4h), no holdout:

| config | mediana | trades | fee |
|---|---:|---:|---:|
| produção (trailing 1,5) | −8,73% | 3.259 | 684,8 |
| trailing DESLIGADO | −4,50% | 1.440 | 298,7 |
| trailing alargado (3,0) | −2,42% | 1.621 | 340,6 |

**Alargar ajuda — mas porque reduz rodadas, não porque evita agulhada.**

### 4.3 Os três parâmetros que se confundem sob o nome "margem do trailing"

1. `trail_distance` — distância entre o pico e o stop. No motor hoje está
   **amarrada** à distância do stop inicial (1,5 × ATR). É esta que decide se
   uma agulhada pega o stop.
2. `TRAIL_MIN_STEP_PCT` (0,1%) — o quanto o stop precisa melhorar para ser
   movido. Serve para não ficar cancelando/recriando ordem. **Praticamente não
   afeta ser fisgado** — mexer aqui achando que resolve agulhada é o erro
   clássico. Medido: variar de 0,1% a 2,0% muda o R/trade de −0,063 para −0,072.
3. `trail_start_r` — gatilho de ativação (só seguir depois de X R de lucro).
   **Não existe no motor.** Foi implementado no harness e testado: melhora o
   retorno (start 1,5R → −16,75% vs −23,29%), mas de novo **por reduzir trades**,
   não por melhorar o R/trade (que piora, −0,062 → −0,074).

---

## 5. Por que "rodar na mainnet agora" não é um toggle

`src/strategy/` contém **apenas** `deterministic.py` (EMA20/50 + RSI) e
`llm_strategy.py`. Não existe donchian, bollinger, momentum nem rsi_mr no motor.
`compute_indicators()` calcula somente `ema_fast(20)`, `ema_slow(50)`, `rsi(14)`
e `atr(14)` — não há canal de Donchian, banda de Bollinger, ROC nem EMA200.

**E o mais importante:** a saída por sinal — a peça estrutural que separa a
config que perde da que ganha — **não funciona em perp**. `_check_signal_exit()`
só é chamada de dentro de `_check_spot_exits()` (`src/engine.py:412`), que
retorna imediatamente quando `market_type != "spot"`. `_check_perp_exits()`
nunca a chama. Além disso, `_check_signal_exit` passa `side="long"` fixo — o que
inverteria a decisão numa posição short mesmo se estivesse ligada.

**Consequência prática: ligar `exit_on_signal: true` no YAML hoje, em perp, não
faz absolutamente nada.**

---

## 5b. Verificação adversarial (9 agentes) — o que ela mudou

Painel de 6 lentes independentes + 3 juízes, cada um recomputando os números do
zero a partir do dado bruto. **Todos os números reproduziram dígito a dígito**
(C1 −25,34%, C3 +9,86%, C4 +10,59%, eod ≤0,45%). O motor foi auditado limpo:
sem look-ahead (teste de clarividência: dar 1 candle de futuro muda donchian de
+0,389 para +2,053 R/trade), identidade contábil fechando a 4,9e-12, fee
conferida trade a trade, selftest 35/35.

**Os 3 juízes decidiram, por unanimidade e com confiança alta: NÃO PROMOVER.**
Cinco achados que eu não tinha e que mudam a leitura:

1. **O critério de aceitação não discrimina nada** (achado decisivo, juiz
   cético). Uma grade ingênua de **300 configurações** de tendência
   (ema_cross e donchian, sem TP e sem trailing) na mesma janela: **300/300
   (100%) têm mediana positiva** e **114 (38%) têm 8/8 símbolos positivos**;
   180 (60%) são MELHORES que C3. C3 e C4 estão no percentil 40-44 de um
   universo onde tudo ganha. "Mediana > 0 com 8/8 símbolos" tem informação
   **zero** nesta janela — é propriedade do período, não da regra.
2. **O edge já morreu na própria amostra.** Nos últimos 12 meses C3 dá −3,36%
   (2/8) e C4 −0,30% (4/8); no semestre corrente C3 −2,86% (0/8) e C4 −1,18%
   (2/8). Decaimento monótono em 6 semestres para C4: +1,31 → +0,41 → +0,42 →
   +0,25 → +0,19 → negativo. **É exatamente a janela em que o robô opera hoje.**
3. **A premissa da rodada está errada.** long-only rende MAIS que long+short
   (C3 +13,34% vs +9,86%; C4 +15,67% vs +10,59%), e **spot long-only com fee de
   0,1%/lado rende ainda mais** (+14,77% / +16,34%) — exatamente o que as duas
   rodadas anteriores mediram. Ou seja: a diferença desta rodada **não é**
   perp/short/fee; é **dado novo + regra de saída nova**. O lado short é dreno
   líquido (−53,4R e −36,6R).
4. **C5 (minha afirmação estrutural) está errada.** As 5 diferenças isoladas
   somam +0,0419 R/trade — 15% dos +0,2834 necessários. A virada é
   **interação**, não soma; não dá para colher os ganhos incrementalmente. Na
   escada de ablação, **80,5% do efeito vem de UM fator: remover o TP fixo**
   (+0,2281), não da saída por sinal.
5. **Estatística.** Nenhuma das 16 séries atinge |t| ≥ 2 (máx 1,44 e 1,32).
   Remover **1 único trade** por símbolo leva C3 de +336,65R para **−12,75R**.
   Permutação: p = 0,0125 no total, mas **p = 0,37 / 0,44** sem os 5 melhores —
   indistinguível de seguidor de tendência com timing aleatório. Correlação
   entre símbolos dá ~**2,3 séries efetivamente independentes**, não 8.
   E o contraste que inverte tudo: **C1 (a config em produção, que perde) tem
   4/8 séries com |t| ≥ 2 — a evidência de que a produção PERDE é
   estatisticamente mais forte que a de que C3/C4 GANHAM.**

Dois achados de engenharia, ambos críticos:

6. **`side="long"` fixo em `engine.py:789`**: se alguém construir a saída por
   sinal em perp sem corrigir isso, C3 vira **−20,59%** (14.309 trades, 2.165
   USDT de fee). É um bug de uma linha com efeito de inverter o resultado.
7. **O kill switch de 3% de drawdown diário (reset MANUAL) congela C3 em 6 de 8
   símbolos** na simulação — BTC para em 2024-03-05 com 27 trades em vez de 187.
   O harness declara "sem kill switch"; o motor real tem. O resultado ao vivo
   seria materialmente diferente do backtest.

Ressalvas menores confirmadas: o funding é debitado do equity mas não entra no
R por trade (R/trade dos positivos ~10% inflado); `R/trade` e `total_return_pct`
ordenam configs de forma diferente (o motor compõe); e o trailing tem
ambiguidade de caminho intra-candle em 6-21% dos candles, **sistematicamente
favorável às configs com trailing** (no limite pessimista C1 vai a −70,37%) —
o que só reforça as conclusões sobre C1 e C2.

---

## 6. Recomendação

### 6.1 Fazer agora — uma coisa só, e ela é grande

**Desligar o perfil `daytrade` (15m)**: `trading.profiles.daytrade.enabled: false`.

É a única mudança com evidência que se sustenta em **todas** as janelas,
inclusive a atual, e no universo real da produção (BTC+ETH):

| janela (BTC+ETH, 15m) | mediana | R/trade | trades | fee |
|---|---:|---:|---:|---:|
| últimos 12 meses | **−97,20%** | −0,3525 | 9.401 | 1.317,7 |
| 3 anos, 8 símbolos | −98,00% | −0,2179 | 47.900 | 6.271,9 |

O perfil responde por **16 dos 33 `order_executed` reais do PC2** (48,5%) e tem
t até −28,58. Não é ruído amostral — é a estatística mais forte de todo o
dossiê. Reversível em uma linha.

### 6.2 Trailing — ambíguo hoje, decisão secundária

O ganho de desligar decaiu e **inverteu** no regime atual (BTC+ETH, 4h):

| janela | trailing 1,5 (produção) | trailing DESLIGADO |
|---|---:|---:|
| 3 anos | −32,20% | **−14,34%** |
| últimos 12 meses | −5,78% | −4,72% |
| **semestre corrente** | **−2,36%** | −3,68% |

Em 3 anos desligar é claramente melhor; nos últimos 6 meses é pior. Como a
evidência não é consistente na janela vigente, **não recomendo mexer nisto
agora** — e, se mexer, tratar como experimento a medir, não como correção.
Vale registrar que a incerteza real é ainda maior: a ambiguidade intra-candle
do trailing (achado 6-21% acima) é favorável às configs COM trailing, então o
número de produção é provavelmente otimista.

### 6.3 NÃO fazer

- **Não promover nenhuma das 5 famílias.** Veredito unânime do painel.
- **Não ligar `exit_on_signal` em perp** — é código morto hoje, e ligá-lo depois
  de construir o caminho sem corrigir `engine.py:789` mede −20,59%.
- **Não baixar `tp_rr`** (recomendação nº1 do CLAUDE.md de hoje mais cedo):
  no walk-forward **piora** (tp 0,75 → −36,90% vs tp 2,0 → −23,29%), porque
  fecha cedo e reentra, multiplicando fee.

### 6.2 NÃO fazer agora

- **Não promover nenhuma das 5 famílias para capital real.** O edge aparente é
  beta de alta, o lado short não tem edge, e a escolha de parâmetro tem r≈0 de
  poder preditivo.
- **Não baixar `tp_rr`** (recomendação nº1 do CLAUDE.md de hoje mais cedo):
  medido no walk-forward, **piora** (tp 0,75 → −36,90% vs tp 2,0 → −23,29%),
  porque fecha cedo e reentra, multiplicando fee. A simulação ingênua sobre MFE
  que sugeria o contrário não considerava reentrada nem custo.

### 6.3 Caminho de verdade (próxima sessão)

O achado de r ≈ −0,05 diz onde NÃO está a resposta: não está em afinar stop, TP
ou trailing, nem em achar o melhor par de EMAs. O que sobrevive é estrutura
(4h em vez de 15m; sair por sinal em vez de por TP fixo; não trilhar). Isso
sugere, na ordem:

1. Construir a **saída por sinal em perp** (com `side` correto) — é a peça
   estrutural que falta e serve a qualquer família futura.
2. Expor `atr_stop_mult` / `tp_rr` no YAML (hoje `_build_strategy` só lê
   `exit_on_signal` e `trailing`).
3. Só então testar família nova, com um **forward real em dry-run** medindo
   contra o motor atual — porque backtest já provou 3 vezes que não decide isto.

---

## 7. Limitações honestas

1. **O holdout é quase todo um regime só** (bear de −59,9% mediano). Um
   resultado que sobrevive lá pode não sobreviver num lateral.
2. **Contaminação residual de seleção**: eu vi números agregados do período
   inteiro para ~15 configurações antes de escrever o `holdout_3.py`. O holdout
   reduz o problema, não o elimina.
3. **Survivorship**: os 8 símbolos existem e são líquidos hoje. Moedas que
   morreram no período não estão na amostra.
4. **107 configurações testadas** no holdout e ~2.300 no grid — sob esse número
   de comparações, células positivas isoladas são o que ruído produz.
5. **15m tem fidelidade ruim** (sem cooldown, trailing mais grosso que o live) —
   os números de 15m são piso, não estimativa central. A direção da conclusão
   (inviável) não muda, a magnitude sim.
6. **Magnitude**: mesmo o melhor candidato rende ~+4% em ~16 meses de mediana.
   Com equity de ~180 USDT e quantização de tamanho (BTC 0,001; ETH 0,01), isso
   é ruído em termos absolutos.

*Análise estatística sobre dados históricos para pesquisa do projeto; não é
recomendação de investimento. Desempenho passado não garante resultado futuro.*

## 8. Arquivos

- `research/download_data_3.py`, `harness_perp.py`, `sweep_3.py`,
  `sweep_trailing.py`, `holdout_3.py`
- Validação: `selftest_harness_perp.py` (35/35), `validate_harness_perp.py`
- Resultados: `research/results_3/{full_grid.csv, wf_results.csv,
  trailing_sweep.csv, summary.json}`
- Dados: `research/data_3/` (perp mainnet pública, 2023-08 → 2026-08)
