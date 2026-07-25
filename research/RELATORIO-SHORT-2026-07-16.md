# Pesquisa de estratégia SHORT (hipotética) — 6 meses perp, 6 pares (16/07/2026)

**Pergunta do Lucas:** a mesma análise da rodada long, mas se fosse SHORT com
alavancagem moderada.

**Enquadramento obrigatório: pesquisa 100% HIPOTÉTICA.** Derivativos estão
bloqueados para residente BR na Bybit (retCode 10024, Etapa B de 15/07) e
contorno de bloqueio regional está fora de questão. Esta régua existe só para
decidir se short valeria a pena em venue legítima (ex.: futuros na B3). A fee
usada (taker perp 0,055%/lado) é portanto hipotética — em qualquer fricção
executável hoje pelo Lucas, todas as medianas ficam ≤ 0.

**Resposta curta: short "ganhou" nesta janela, mas é 100% beta do bear market,
não edge. Nenhuma das 38 células positivas (de 108) bate o short-and-hold
passivo do próprio símbolo na mesma janela — a melhor estratégia da varredura
inteira capturou MENOS DA METADE do que "não fazer timing nenhum" capturaria.
A seleção ex-ante não teria escolhido os vencedores, não existe assimetria de
crash a favor do short, e o robô short teria estreado em julho — um mês em que
os 6 símbolos SOBEM. Nada aqui autoriza construir/promover estratégia short.**

## Metodologia (espelho da rodada long, com as diferenças do short)

- Dados: PERPÉTUOS mainnet pública Bybit (12/01–17/07/2026), 15m/1h/4h, 6
  símbolos, + histórico real de funding (561 eventos/símbolo, 8/8h) —
  `research/download_data_perp.py`, dados em `research/data_perp/`.
- Motor: `research/harness_short.py` — short-only, fee 0,055%/lado, slippage
  0,02%/lado, funding aplicado no candle do evento (short recebe rate
  positivo), alavancagem moderada = teto de nocional 2x equity (sizing continua
  risco fixo 0,5%/trade), liquidação aproximada em entry×1,475 (zero disparos
  em toda a varredura), gap-through no stop preenche no open.
- Varredura: `research/sweep_short.py` — mesmas 6 famílias/108 combinações
  espelhadas, split 70/30 + walk-forward IS 90d/OOS 18d (5 folds, seleção por
  t-stat, mín. 8 trades). Janela OOS do WF: **12/04→11/07/2026 00:00 UTC**
  (os 6 dias finais dos dados, 11–17/07, ficam FORA do WF — e são de ALTA em
  todos os símbolos).
- Fix desta rodada: `fold_ret_pct`/`pos_folds` corrigidos na origem (o bug da
  rodada long) — verificado por 4 caminhos independentes, 108/108 células.
- Verificação adversarial: 9 agentes (2 auditorias com testes empíricos,
  benchmark short-and-hold com funding, 4 refutadores, refutador inverso,
  crítico de completude). Consolidado em
  `research/results/short/verificacao_agentes.json`, scripts em
  `research/scratch/short_*.py`.

## Resultados

### O número que define tudo: a régua passiva

Short-and-hold 1x honesto (com fees e funding) rendeu **+30% a +56% nos 6
meses** (mediana +43%) e **+6% a +37% na janela do walk-forward** (mediana
+15,4%). Contra isso:

- **0 das 38 células WF positivas bate o short-and-hold do próprio símbolo.**
- Melhor célula da varredura: MNT 15m robot_baseline **+16,1%** — vs **+37,3%**
  do short passivo de MNT na mesma janela (captura de 43%).
- MNT 1h robot +8,1% (22% do passivo); MNT 1h donchian +5,5% (15%);
  XRP 1h robot +5,0% (27% do passivo XRP +18,4%).
- Mediana da "melhor" família (+0,52%) ≈ 30x menor que a mediana passiva.

As estratégias não adicionam alfa sobre o beta — **subtraem** dele (fees +
exposição parcial). O ranking das células segue o beta do símbolo (MNT, MNT,
MNT, XRP = os que mais caíram), não a inteligência da regra.

### Por família e timeframe (WF, fee hipotética de perp)

| Família | Mediana WF | Positivas /18 |
|---|---:|---:|
| robot_baseline (short do robô) | +0,52% | 10 |
| donchian | +0,005% | 9 |
| rsi_mr | -0,95% | 6 |
| momentum | -1,19% | 6 |
| ema_cross | -1,64% | 6 |
| bollinger_mr | -1,90% | 1 |

Por timeframe: 15m **-4,84%** | 1h -1,03% | 4h +0,09%. O 15m segue inviável
por fricção mesmo com a fee de perp (quase metade da fee do spot).

Ressalva obrigatória sobre a "melhor família": o rótulo verdadeiro é **"a
menos ruim, e só na fee hipotética de perp"** — 10/18 positivas tem p=0,41
(moeda honesta), zero células com t-stat ≥ 2, e com a fee de spot (0,1%) a
mediana do robot_baseline short vira **-0,79%** (8/18; positivas gerais caem
38→30).

### Por que é beta e não edge (5 linhas de evidência independentes)

1. **Régua passiva:** 0/38 batem short-and-hold (acima).
2. **Sem significância:** t-stat pooled OOS máximo +1,74; a família
   robot_baseline 1h/4h agregada (371 trades) dá t=0,81 com cluster por dia;
   teste de permutação de timing: 0/38 células com p<0,05 (esperado ~5 por
   acaso — o observado é MENOS que sorte).
3. **Sem crash-alpha:** captura por unidade de movimento simétrica (0,139 em
   alta vs 0,147 em queda) — nos 8 meses-símbolo de ALTA da janela (BTC +11,8%
   abr; BNB +15,5% mai; ETH +18,6% jul parcial) a estratégia média perdeu
   -1,06%. Short só ganha quando o mercado cai, na mesma proporção.
4. **Seleção ex-ante falha:** as top-3 células por t-stat IS deram OOS
   -0,55%/-0,22%/+0,42%; o grande vencedor OOS era rank 4. O que persiste
   IS→OOS é "qual config gira menos fee", não timing.
5. **Timing frágil:** defasar tudo em 1 candle destrói 64–86% do retorno de
   2 das 4 células top (MNT 1h +8,1%→+1,1%; XRP 1h +5,0%→+1,8%).

Funding: irrelevante (±1–2% ao ano do nocional; SOL negativo). Leverage 2x:
nunca vinculante de forma material; zero liquidações. Decomposição do gap
short vs long (+0,52% vs -3,40% do robô): ~1/3 é só a fee menor do perp,
~2/3 é a direção short numa janela 100% bear — beta de regime.

### Auditorias do motor (2 auditores + verificações do inverso e do crítico)

Sem look-ahead (invariância por truncamento, corrupção do futuro, defasagem —
todos PASS); espelho short correto (PnL, trailing rachete, stop>TP, gap,
slippage, funding no candle certo, só com posição aberta); dados íntegros
(retângulo perfeito de 186 dias, funding 8/8h exato); WF replicado 108/108
células por dois agentes independentes. Achados menores (nenhum muda sinal de
conclusão): bug conhecido do MTM herdado da rodada long (só contamina
max_dd_pct — NÃO citar max_dd das tabelas); bordas de funding ±1 evento/trade;
stop gapado sem slippage extra (viés otimista ~0,2–1,8pp nas células top);
fechamentos forçados na borda de fold (42% do PnL do XRP 1h vem deles).

## Limitações obrigatórias

1. **Hipotético**: derivativos bloqueados para residente BR; fee de perp
   inatingível hoje; em fricção executável, medianas ≤ 0.
2. Janela 100% bear — o resultado short positivo é o espelho disso, e o
   veredito formal é: **sem edge short detectável ALÉM do beta da janela**.
3. `research/data_perp/` agora está QUEIMADO para seleção de estratégia (OOS
   inspecionado por ~9 agentes); hipótese nova exige dados novos.
4. Não citar: max_dd_pct (bug MTM), funding como "carry", comparações de
   mediana long-vs-short sem a nota da fee.
5. Nada foi alterado no robô/YAML — pesquisa pura em `research/`.

## Conclusão prática (decisão é do Lucas)

1. **Nada nesta rodada autoriza construir/promover estratégia short** — nem em
   venue legítima futura. Se a tese fosse "quero exposição short a cripto", o
   instrumento racional na janela era o short PASSIVO (e mesmo ele teria
   estreado em julho, um mês de alta nos 6 símbolos).
2. A leitura conjunta das duas rodadas (long + short) é uma só: **nesta janela
   nenhuma regra técnica simples tem edge sobre o próprio regime do mercado**;
   o que decide o resultado é a direção do mercado, que as regras não preveem.
3. O caminho registrado permanece: terminar a estrutura (Etapa B-spot), e a
   caça a edge fica para depois, com 2+ anos de dados, regime misto, e a
   pendência de executabilidade resolvida (saída por sinal/trailing/TP).

*Análise estatística sobre dados históricos para pesquisa do projeto; não é
recomendação de investimento. Desempenho passado não garante resultado futuro.*

## Arquivos

- Código: `research/{download_data_perp.py, harness_short.py, sweep_short.py}`
- Resultados: `research/results/short/{full_grid.csv, wf_results.csv,
  summary.json, verificacao_agentes.json}`
- Verificações: `research/scratch/short_*.py` (+ JSONs)
- Dados: `research/data_perp/*.csv` (perp mainnet + funding, 12/01–17/07/2026)
