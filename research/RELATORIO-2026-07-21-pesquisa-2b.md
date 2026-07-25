# Pesquisa 2b — donchian/ema_cross com dado novo (2+ anos, regime misto), 1h/4h (21/07/2026)

**Pergunta:** com o pré-requisito de engenharia resolvido (saída por sinal e
trailing stop agora existem e são simuláveis pela régua), as famílias de
TENDÊNCIA (donchian, ema_cross) mostram edge real quando testadas num período
mais longo e com regime misto — em vez dos 6 meses 100% bear de 16/07, que já
estão queimados para seleção?

**Resposta curta: ainda não. Nenhuma das duas famílias mostrou edge validado
em walk-forward, mesmo com dado novo, janela 5,6× maior, regime misto
(altas de +50-475% e quedas de -20-50% no mesmo dataset) e a capacidade de
saída por sinal/trailing habilitada. Donchian é a "menos pior" (mediana
-3,43%, 3/10 séries positivas), ema_cross continua fraca (mediana -6,54%,
1/10). A ÚNICA confirmação forte e reproduzida: a estratégia atual do robô
(EMA20/50+RSI, stop+TP fixos) é, de novo, a PIOR opção testada — mediana
-29,82%, 0/10 séries positivas, pior caso -52,65%. Esse achado se repete
identicamente ao de 16/07, agora num dataset completamente diferente —
deixou de ser "pode ser sorte do período" e virou padrão consistente.**

## Metodologia

- Dados NOVOS: `research/data_2b/`, 2024-04-22 a 2026-07-21 (~2,25 anos),
  spot mainnet pública Bybit, 1h e 4h, baixados por
  `research/download_data_2b.py` (mesma regra anti-look-ahead do resto do
  projeto: candle em formação sempre descartado). 15m não testado de novo —
  já descartado em 16/07 por fricção (fee come 60-95% da perda em day trade).
- 5 símbolos: BTC, ETH, SOL, XRP, BNB (MNT fora desta rodada — sem necessidade
  de reconfirmar, já era o pior símbolo em 16/07 e o foco agora é família, não
  símbolo).
- Motor: mesmo `research/harness.py` de 16/07 (fill no open do candle
  seguinte, stop prioritário sobre TP, gap-through no stop, fee 0,1%/lado +
  slippage 0,02%/lado, risco 0,5%/trade). Famílias donchian e ema_cross JÁ
  suportavam saída por sinal desde 16/07 (perda de canal / perda de regime);
  o que é novo nesta rodada é a grade de TRAILING para ema_cross (não existia
  em 16/07 — só donchian tinha variante trailing).
- 77 combinações (64 ema_cross incl. trailing + 12 donchian + 1
  robot_baseline de controle) × 5 símbolos × 2 timeframes.
- Validação: walk-forward por família, IS 90d → opera 18d às cegas, seleção
  por t-stat do R-múltiplo (mín. 8 trades no IS) — mesma metodologia de
  16/07, 40 folds por série (dataset maior = mais folds que os 5 de 16/07).
- **Novo nesta rodada**: benchmark de buy-and-hold sobre a MESMA janela que o
  walk-forward testa (barra 90d → fim), para nunca confundir "perdeu menos"
  com "tem edge" — lição direta da pesquisa short de 16/07 (38/108 células
  "positivas" que eram 100% beta do mercado, 0/38 batiam o passivo).
- Sanity check de concentração: nenhum dos 4 resultados WF positivos tem>50%
  do retorno somado num único fold (máx. observado 33%, a maioria 5-27%) —
  não são "1 trade de sorte carregando a série", diferente do padrão que
  a pesquisa de 16/07 tinha encontrado e refutado.

## O regime: agora genuinamente misto (a diferença central vs 16/07)

Retorno buy&hold total no dataset inteiro (2024-04→2026-07):
BTC +0,5%, ETH -39,2%, SOL -48,9%, XRP **+110,9%**, BNB -3,0%. Dividido em
9 blocos trimestrais, todos os 5 símbolos passaram por altas de +14% a +475%
E quedas de -8% a -52% dentro do mesmo período — bem diferente dos 6 meses
100% bear de 16/07. XRP em particular teve um bloco de **+475,6%**
(out/2024-jan/2025) que domina o buy&hold do símbolo inteiro.

## Resultados principais — walk-forward por família (10 séries: 5 símbolos × 2 timeframes)

| Família | Mediana WF | Média WF | Séries positivas | Pior | Melhor |
|---|---:|---:|---:|---:|---:|
| donchian | -3,43% | -2,87% | 3/10 | -14,94% | +18,04% |
| ema_cross | -6,54% | -10,08% | 1/10 | -24,03% | +0,05% |
| **robot_baseline (atual)** | **-29,82%** | **-29,07%** | **0/10** | **-52,65%** | **-6,57%** |

Por timeframe (mediana WF): 1h donchian -8,66% / ema_cross -16,63% —
4h donchian -2,88% / ema_cross -4,02%. **4h consistentemente menos ruim que
1h nas duas famílias** — mesmo padrão de 16/07 (fee/whipsaw pesam mais em
timeframe curto).

### As 4 séries com WF positivo — nenhuma bate o buy&hold da própria janela

| Símbolo/TF | Família | WF | Buy&hold da mesma janela | Observação |
|---|---|---:|---:|---|
| XRP 1h | donchian | +18,04% | +95,31% | Capturou ~19% do que segurar teria dado |
| ETH 4h | donchian | +0,33% | -44,68% | "Menos pior" que segurar um ativo em queda — não é edge, é ficar em caixa a maior parte do tempo |
| BNB 4h | donchian | +0,62% | -3,70% | Idem — praticamente neutro |
| XRP 1h | ema_cross | +0,05% | +95,31% | Essencialmente flat; capturou ~0% do rali |

Ou seja: o único caso "positivo e bateu o buy&hold" (XRP 1h donchian) só
bate porque nesse caso o buy&hold monitorado é NEGATIVO nas frações da
janela onde a estratégia operou — não há nenhum caso de família batendo um
buy&hold POSITIVO. Nos dois casos onde o mercado subiu MUITO (XRP,
+95% na janela testada), as duas famílias de tendência capturaram uma fração
pequena (0-19%) do movimento — atraso de confirmação de sinal é o
suspeito óbvio, coerente com o desenho (donchian/ema_cross entram DEPOIS do
rompimento/cruzamento, nunca no início do movimento).

## Comparação direta com 16/07 (mesmas famílias, dataset diferente)

| | 16/07 (6 meses, 100% bear) | 21/07 (2,25 anos, regime misto) |
|---|---:|---:|
| donchian | -1,42% mediana, 4/18 positivas | -3,43% mediana, 3/10 positivas |
| ema_cross | -2,94% mediana, 3/18 positivas | -6,54% mediana, 1/10 positivas |
| robot_baseline | **-3,40% mediana, 0/18 positivas** | **-29,82% mediana, 0/10 positivas** |

**O robô atual piorou MUITO no dataset novo** (de -3,40% para -29,82%
mediana) — não é inconsistência, é o dataset novo tendo blocos de queda mais
extremos e mais long e o robô (stop+TP fixos, sem saída por sinal) sofrendo
mais nesse regime. Donchian/ema_cross pioraram um pouco também (janela mais
longa = mais chances de fold ruim), mas continuam MUITO menos ruins que o
robô atual nos dois datasets — essa hierarquia relativa é o achado mais
sólido desta pesquisa, reproduzido em dois datasets independentes.

## Veredito honesto

1. **Ainda não existe edge validado em nenhuma das duas famílias de
   tendência testadas.** Mediana negativa nas duas, poucas séries positivas,
   e mesmo as positivas capturam só uma fração pequena do que segurar o
   ativo teria dado quando o mercado sobe forte.
2. **A estratégia atual do robô continua sendo a pior opção, e isso já
   apareceu 2 vezes em datasets diferentes** — não é mais "pode ser o
   período", é padrão. Não escalar capital nela.
3. **Donchian em 4h é o candidato "menos pior"** entre os quatro testados
   (mediana -2,88% nesse recorte específico) — ainda negativo, mas o mais
   perto de zero e o único com mais de 1 série de fato positiva por
   timeframe. Não é recomendação de uso, é onde investigar primeiro se
   alguém quiser continuar puxando este fio.
4. **A engenharia nova (saída por sinal/trailing) funcionou como esperado no
   teste** — não gerou nenhum bug estrutural aparente nesta rodada (picks
   variados por fold, sem concentração suspeita) — mas não resolveu o
   problema real, que é a AUSÊNCIA de edge nas regras testadas, não a falta
   de mecanismo de saída.

## Limitações desta rodada (documentadas, não escondidas)

- Rodada "enxuta" a pedido do Lucas: eu mesmo rodei e revisei os números,
  sem o painel adversarial multi-agente de 16/07 (9 agentes) nem os
  refutadores dedicados. O sanity check de concentração por fold foi feito,
  mas é mais raso que aquela verificação.
  **Se qualquer resultado aqui for usado pra decisão de capital, merece pelo
  menos uma passada adversarial antes — mesmo padrão que 16/07 já vinha
  seguindo.**
- MNT fora desta rodada (não é reconfirmação de símbolo, é foco em família).
- T-stat agregado por família/série não foi recalculado nesta rodada (só o
  t-stat de SELEÇÃO por fold, já embutido no walk-forward) — os números de
  significância estatística formal (como os "0 t-stat≥2" do relatório
  short de 16/07) não foram refeitos aqui.
- Nenhuma das famílias testadas usa contexto macro/on-chain (Fase 3 segue
  desligada) — é puramente técnico, como toda a pesquisa até agora.

## Próximos passos sugeridos

- Se valer a pena continuar puxando este fio: aprofundar donchian 4h
  especificamente — variar canal (n maior, tipo 100/200) e comparar com um
  filtro de tendência de prazo mais longo (ex.: só operar na direção do
  EMA200 semanal), já que o problema aparente é ENTRADA tardia, não saída.
- Considerar que o universo de 5-6 símbolos manualmente escolhidos pode não
  ser onde o edge (se existir) está — a visão de produto original (seção 1
  do charter) sempre foi varredura de universo + ranking, não símbolo fixo.
- Rodar a verificação adversarial completa (como 16/07) SE e SOMENTE SE
  alguém quiser promover donchian/4h como candidato real — não gastar essa
  rodada agora que o veredito é "ainda negativo".
