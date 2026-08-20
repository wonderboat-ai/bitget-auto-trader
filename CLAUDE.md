# CLAUDE.md — Bybit Auto Trader (handoff 2026-08-20, projeto PAUSADO — migrando pra Bitget)

Contexto vivo do projeto para agentes (Claude Code/Cowork). **Este projeto está
PAUSADO desde 20/08/2026** — ver "PRÓXIMA AÇÃO" abaixo antes de qualquer coisa;
o robô está sendo portado pra um projeto IRMÃO (Bitget, mainnet direto), e esta
pasta (Bybit) fica congelada como referência. Fonte completa de regras:
`INSTRUCOES-PROJETO-v2.md` v2 + `RASCUNHO-instrucoes-v12-colar-manualmente.md`
(v12, criado 20/08 — ver "Status atual" lá; ainda NÃO colada nas instruções
do Claude Project — substitui a v11, colada em 19/08). Guia operacional humano: `PASSO-A-PASSO.md`
(bootstrapping testnet — todas as etapas fechadas, ver seu próprio aviso de topo);
`PASSO-A-PASSO-18-08-2026.md` (as 3 ações manuais do Lucas). Idioma
de trabalho: português do Brasil. Comentários de código explicam causa raiz.

## PRÓXIMA AÇÃO (ler antes de qualquer outra coisa)

### Status verificado em 20/08/2026 ~14:00 UTC — PROJETO PAUSADO: conta Bybit em disputa de KYC, saldo já portado pra Bitget, motor parado

**ESTE PROJETO (Bybit) ESTÁ PAUSADO.** Não religar o motor nesta conta sem
decisão explícita nova do Lucas — o contexto operacional mudou de forma
estrutural nesta sessão (20/08). Se alguém pedir pra ligar/monitorar o motor
aqui, confirmar antes: a intenção pode ser sobre o projeto NOVO (Bitget), não
este.

**O que aconteceu, na ordem:**

1. **Conflito de identidade na Bybit.** O Lucas não consegue reautenticar o
   KYC da conta que o robô usava — a Bybit mostra outra pessoa associada ao
   CPF dele, com e-mail diferente. Isso é indício de possível fraude de
   identidade, fora do alcance de qualquer agente resolver: exige contato
   direto dele com o suporte da Bybit (documento + selfie + disputa formal
   por escrito) e, possivelmente, um Boletim de Ocorrência — alguém usando o
   CPF dele numa exchange pode estar usando em outros lugares também.
2. **Pesquisa confirmou que o problema é regulatório, não específico da
   Bybit.** A CVM/Bacen está forçando toda exchange com entidade registrada
   no Brasil a bloquear derivativos pra residentes BR — **a OKX já faz o
   mesmo** (só spot/P2P liberado). A Bybit anunciou liquidação forçada de
   posições incompatíveis a partir de **21/09/2026**. Binance e OKX saem de
   cogitação como destino pelo mesmo motivo — exchanges offshore sem
   entidade BR (Bitget, MEXC, Gate.io, KuCoin, BingX) ainda permitem
   derivativos hoje, mas exatamente por não seguirem esse mesmo arcabouço —
   risco aceito conscientemente pelo Lucas, não ausência de risco.
3. **O saldo real (~189 USDT) já foi retirado da Bybit e portado pra a
   Bitget** pelo Lucas, antes de qualquer bloqueio pior na conta.
4. **Motor parado de forma limpa** às 13:09:52 UTC de 20/08
   (`engine_stop`/manual) — `CTRL_C_EVENT` funcionou de primeira desta vez,
   porque o motor rodava num terminal externo com console real (ver item 6).
   Nenhuma posição aberta no momento.
5. **Decisão do Lucas: portar o robô pra Bitget, indo direto pra MAINNET**
   (sem fase de testnet antes — desvio deliberado da prática histórica do
   projeto). Avaliação técnica feita nesta sessão (via WebSearch, não só
   memória): Bitget é a candidata de MENOR esforço de porte entre as
   opções offshore — tem conta unificada (UTA) parecida com a da Bybit v5, e
   `create_order` aceita `presetStopLossPrice`/`presetTakeProfitPrice`
   nativamente (melhor que a Bybit, que não tem OCO real entre stop e TP).
   **Risco técnico identificado e AINDA NÃO validado na prática**: o modo
   one-way — do qual o projeto inteiro depende (bug #7) — tem gambiarras
   documentadas no ccxt especificamente pra Bitget (erro 40774 no
   `create_order` padrão, precisa do workaround `side: "buy_single"/
   "sell_single"`). Ver a conversa desta sessão (20/08) pro detalhe completo
   da pesquisa e a tabela comparativa (Bitget vs Gate.io vs KuCoin vs MEXC
   vs BingX).
6. **Nada foi portado ainda.** `bybit_client.py` e tudo que depende dele
   continuam 100% Bybit, sem nenhuma linha adaptada pra Bitget. O plano
   combinado com o Lucas: **clonar este projeto inteiro** (código como está,
   histórico preservado) num **diretório novo + repositório GitHub novo**,
   com seu próprio `CLAUDE.md`/`README.md`/instruções — preservando ESTE
   projeto intacto como referência/frozen, não alterado — e portar a partir
   de lá, numa **sessão nova dedicada a isso**. Antes de escrever
   `bitget_client.py` de verdade, validar manualmente as 4 operações
   críticas (saldo, ordem+SL/TP, cancelamento, one-way) — como vai direto
   pra mainnet, cada validação usa dinheiro real, ir com size mínimo.

**Lição operacional nova desta sessão**: religar o motor num **terminal
externo real** (`PowerShell Start-Process`, não `run_in_background` do Bash
tool) é o que torna o `CTRL_C_EVENT` confiável pra parar depois — processos
sem console real só param com `TaskStop`, que é kill forçado e não deixa
`engine_stop` limpo na trilha (aconteceu 1x nesta sessão, documentado sem
prejuízo real). Ver protocolo salvo em memória (`trader-status-command-
protocol`) pro fluxo completo do comando "trader status".

---

### (histórico) Status verificado em 19/08/2026 ~20:30 UTC — motor PARADO de propósito, PC2 sincronizado, pendências ZERADAS

**MOTOR PARADO.** `engine_stop`/`manual` auditado às **20:20:12 UTC**, a pedido
do Lucas, para poder atualizar o PC2. Parada LIMPA via `CTRL_C_EVENT` real no
console do supervisor (`AttachConsole` + `GenerateConsoleCtrlEvent` por ctypes) —
**nunca usar `taskkill /F`**: sem o `engine_stop` na trilha, a parada fica
indistinguível de crash numa auditoria futura. Zero processos restantes.

**Momento da parada foi seguro**: nenhuma posição aberta, zero ordens na Bybit,
nada exposto. Equity **188,86 USDT**. **Religar é decisão do Lucas** — nunca
inicio `--live` por conta própria.

**PC2 ATUALIZADO** para `c54bcf8` (`git pull` com o motor já parado, como manda
a regra). Código conferido idêntico entre PC1 e PC2 por hash em
`engine.py`/`risk_manager.py`/`risk_config.yaml`; `main.py` e `supervisor.py`
acusam diferença de md5 mas é **só fim de linha** (CRLF × LF), zero diferença de
conteúdo — verificado com `diff` normalizado. Estado (`cooldown_state`,
`kill_switch_state`, `spot_protections`) preservado; `git pull` não toca neles.
Config que o motor lerá no próximo boot: **perfis ativos = `['swing']`**, perp,
trailing true, BTC+ETH.

**AS DUAS PENDÊNCIAS DO LUCAS FORAM FECHADAS (19/08):**
1. **`RASCUNHO-instrucoes-v11` COLADA** nas instruções do Claude Project — a
   primeira desde a v7 (v8/v9/v10 foram criadas e nunca coladas).
2. **Bloco `permissions` aplicado** em `~/.claude/settings.json` (17:26).

**O que se aprendeu sobre o bug de permissão, e vale para qualquer tarefa
agendada futura:** o Lucas vinha clicando "permitir" a cada execução do dossiê,
e **cada clique virava uma regra nova no `.claude/settings.local.json` do
PROJETO** (69 → 76 regras). Isso não podia funcionar por dois motivos
independentes: (a) arquivo de PROJETO, e tarefa agendada roda com outro cwd, então
nunca o carrega; (b) as regras gravadas são **comandos literais com o UUID da
sessão e a DATA embutidos** (ex.: `...\45bac2b4-4419-.../scratchpad/gravar_contexto_2026-08-18.py`)
— casam exatamente uma vez e nunca mais. **Evidência do custo**: o dossiê deveria
rodar 3x/dia e os arquivos gerados mostram no máximo 1x/dia, com buracos (faltam
07-10, 12, 13, 15 e 16 de agosto) — o padrão de "só roda quando tem alguém para
clicar". A correção real é o bloco no `settings.json` GLOBAL, com padrões `**`
em vez de comandos literais.

**Ressalva sobre o bloco aplicado**: a versão colada ficou **mais ampla** que a
que propus — entraram `Read`, `Write` e `Edit` **sem escopo de caminho**, ou
seja, qualquer sessão nesta máquina escreve qualquer arquivo sem perguntar. A
proteção central sobrevive (`deny` tem precedência: `config/`, `state/` e
`logs/` do `C:\BybitAutoTrader` seguem bloqueados para escrita), mas duas
brechas ficam: a pasta do PC1 não está no `deny`, e o próprio `settings.json`
virou gravável sem prompt — a trava contra auto-concessão de permissão passa a
depender só do classificador de auto mode.

---

### (histórico) Status de 19/08/2026 ~20:00 UTC — motor 23,5h de pé, MELHOR DIA da história

**Motor VIVO no PC2** (`engine_start` 18/08 20:26:50 UTC, `dry_run: false`),
23,5 h contínuas, ciclos de ~62s, kill switch livre, **zero eventos críticos e 1
único erro de ciclo em 24h**. **Nenhuma posição aberta** neste instante — conta
100% em caixa, zero ordens pendentes na Bybit (checado na exchange, sem órfãs).
**Equity 188,87 USDT.** Cooldowns livres nos dois símbolos (contadores do dia
preservados: BTC 2 acionamentos, ETH 1 — próximo stop do BTC já escala pro teto).

**19/08 foi o melhor dia da história da conta: 9 trades (6 take-profit, 3 stop),
+7,054 brutos → +6,418 USDT LÍQUIDOS.** Sozinho, tirou o acumulado de −6,5 para
perto de zero.

**Mas o acumulado de 22 dias segue negativo: 53 trades, acerto 34,0%, +2,591
brutos, 2,951 de fee → −0,360 USDT líquido.** O número que resume o projeto:
**a fee acumulada é MAIOR que todo o lucro bruto** — 22 dias de operação ainda
não pagaram a corretora.

**Nada disso contradiz a pesquisa.** O dia foi um melt-up de +5,9% em BTC e
+8,8% em ETH (candle de 15m com +3,04% e volume 4-15x o normal — verificado no
OHLCV, não é anomalia de dado). Seguidor de tendência com alvo em 2R colhe
exatamente aí. **6 trades de 53 responderam por todo o movimento** — é a mesma
concentração que o painel adversarial apontou como fragilidade, agora aparecendo
a favor. Confirma a fragilidade da amostra, não estabelece edge.

**O que mudou de forma permanente foi o custo**, e é consequência direta de
desligar o 15m: as entradas novas do swing saem com `capped: false` e fee de
**~8-9% de 1R**, contra os ~27% que o perfil de 15m pagava. Confirmado trade a
trade ao vivo.

**MUDANÇAS DESTA SESSÃO (18-19/08), todas já em `main` e no PC2:**
1. **Perfil 15m desligado** (`daytrade.enabled: false`) — commit `e30a72b`,
   aplicado no PC2 via `git pull`. Confirmado ao vivo: só `swing` é avaliado.
2. **Cooldowns dos dois símbolos resetados manualmente** a pedido do Lucas
   (18/08 20:58 e 20:59 UTC), via `state/control.json` escrito à mão — o MCP do
   PC1 está em standby. **O engine aprovou entrada em ETH 3 segundos depois.**
3. **Bug #50 corrigido** (`tests/_guard.py`) — a suíte destruía a trilha.
4. **Trilha do PC1 restaurada pelo Lucas** via histórico do Dropbox (15.860
   linhas). Ver ressalva abaixo.

**PENDÊNCIAS DO LUCAS (2) — ambas FECHADAS em 19/08, ver o status no topo:**
1. ~~Colar o bloco `permissions` em `~/.claude/settings.json`~~ — **FEITO**
   (19/08 17:26), com escopo mais amplo que o proposto. Tentei aplicar eu mesmo
   e **o classificador de auto mode bloqueou, corretamente** — seria
   auto-concessão de permissão.
2. ~~`git pull` no PC2~~ — **FEITO** (19/08, com o motor já parado).

**Ressalva na trilha restaurada do PC1** (não urgente, PC1 não opera): a linha
15860 é um `audit_maintenance` com **JSON inválido** (`Invalid \escape`, provável
caminho Windows sem escapar) — consequência: o registro que documenta a
restauração é **pulado silenciosamente por todo leitor** (`_read_audit` e
`backfill_from_audit` capturam `JSONDecodeError` e seguem). E a linha 15859 é
resíduo de teste meu (`take_profit_skipped` sintético, tp=110.0). Ambos pedem
cirurgia de trilha, que neste projeto exige autorização explícita (3 precedentes).

**Supervisão:** o `trader-watchdog-pc2` agendado segue **EM STANDBY** — não há
supervisão automática fora de sessão. Dentro da sessão, `scratchpad/vigia.py`
monitora a trilha (eventos críticos + movimento de dinheiro + **ausência de
batimento**, que é o que pega o motor morrendo — um filtro que só procura erro
fica mudo nesse caso). Ele morre com a sessão. **Regra que continua valendo:
depois de qualquer intervalo sem sinal, reconciliar contra a trilha inteira.**

### (histórico) Status de 18/08/2026 ~21:30 UTC — config NOVA no ar (15m DESLIGADO), pesquisa 3 fechada

**Motor VIVO no PC2** (`engine_start` 20:26:50 UTC, `dry_run: false`), rodando a
config nova do commit `e30a72b`. Ciclos a cada 62s, zero erro, kill switch livre.
Árvore de processos confirmada única (lembrar: no Windows, cada processo via venv
aparece DOBRADO na lista — o do venv é launcher e spawna o interpretador base;
não é instância dupla).

**MUDANÇA OPERACIONAL DO DIA: `trading.profiles.daytrade.enabled: false`.** O
perfil de 15m foi desligado. Só `swing` (4h) opera agora — confirmado na trilha
(4/4 avaliações com `profile=swing`; antes cada símbolo era avaliado 2x).
**Espere MUITO menos trades — silêncio na trilha agora é o desenho, não falha.**

Causa raiz, porque importa mais que o número: com o teto de nocional de 50% do
equity MORDENDO em **90% dos sinais reais** (medido na trilha do PC2, campo
`capped`), o nocional fica constante e a fee vira fração fixa dele, enquanto 1R
encolhe junto com a distância do stop. A identidade é **`fee/R = 0,11% ÷ stop%`**.
Em 15m o stop mediano real é 0,40% → a fee come **~27% de cada 1R** antes de
qualquer consideração de estratégia. Em 4h o stop é ~1,55% → **~7%**. Medido
(BTC+ETH, últimos 12 meses): 15m dá mediana **−97,20%**, R/trade −0,3525, 9.401
trades, 1.317 USDT de fee sobre 2.000 de capital. Em 3 anos/8 símbolos: −98,00%,
0/8 positivos, t até −28,58. O perfil respondia por 16 dos 33 `order_executed`
reais do PC2 (48,5%). **Já validado ao vivo**: a 1ª entrada nova pós-mudança saiu
com `capped: false` e fee ≈ 7,9% de 1R, contra ~27% dos trades de 15m.

**Trailing NÃO foi alterado, de propósito.** Desligar ajuda em 3 anos (−32,20% →
−14,34%) mas **PIORA no semestre corrente** (−2,36% → −3,68%). Sem evidência
consistente na janela vigente, fica como está. Ver "Sessão 18/08" para o
desmonte da hipótese da "agulhada".

**Estado da conta agora:** equity ~182 USDT. **1 posição aberta**: ETH/USDT:USDT
**long** 0,03413 @ 1.912,08, stop 1.887,38 (já trailed 1x de 1.885,36), TP
1.965,51, perfil swing, trailing on. **Confirmado na Bybit** que as 2 ordens
condicionais existem de verdade, com IDs batendo com `state/spot_protections.json`.
Cooldowns dos dois símbolos **resetados manualmente** às 20:58/20:59 a pedido do
Lucas (contadores do dia preservados: BTC 2, ETH 3 — próximo stop já escala).

**PENDÊNCIAS DO LUCAS (2, ambas fora do meu alcance):**
1. **Restaurar `logs/audit.jsonl` do PC1 pelo histórico de versões do Dropbox**
   (versão anterior a 18/08 14:51 local). Eu destruí o arquivo rodando a suíte —
   ver bug #50. **PC2 intacto** (é a fonte de verdade desde 31/07); a perda é o
   histórico de 28-31/07 do PC1.
2. **Colar o bloco `permissions` em `~/.claude/settings.json`** (conteúdo pronto
   em `PASSO-A-PASSO-18-08-2026.md`). Tentei aplicar e **o classificador de auto
   mode bloqueou, corretamente** — eu estaria me auto-concedendo permissão. Sem
   isso, a tarefa do dossiê continua pedindo autorização a cada execução.

**Watchdog agendado (`trader-watchdog-pc2`): EM STANDBY** (`enabled: false`,
SKILL.md preservado), decisão do Lucas — ele prefere acompanhar por sessão de
Claude Code. **Consequência real: não há mais supervisão automática fora de
sessão.** O `dossie-cripto-pc2` segue ligado.

**Guia para o Lucas executar as pendências**: `PASSO-A-PASSO-18-08-2026.md`
(+ publicado como Artifact).

### (histórico) Status de 18/08/2026 ~13:55 UTC — motor VIVO no PC2, 18 dias de operação contínua

**O motor roda SOMENTE no PC2 (`C:\BybitAutoTrader`), mainnet, `--live`,
dinheiro real.** Esta pasta (PC1, Dropbox) é **só dev/documentação** — não
rodar `--live` daqui, nunca, sem parar o PC2 antes (mesma conta mainnet nos
dois; decisão de 31/07, ver seção histórica logo abaixo). O `logs/audit.jsonl`
DESTE PC1 está congelado desde 31/07 19:18:53 UTC (`engine_stop` manual) —
**a fonte de verdade da operação é `C:\BybitAutoTrader\logs\audit.jsonl`**.

**Processo confirmado ao vivo** (via `Get-CimInstance Win32_Process`): uma
única árvore `supervisor.py --live` → `main.py --interval 60 --live`, de pé
desde 18/08 05:11 local; último `engine_start` auditado 18/08 08:11:06 UTC
(`dry_run: false`). Trilha do PC2 com 107.024 linhas, último evento
13:53:35 UTC — ciclos normais de ~62s, sem buraco.

**Estado da conta neste instante:**
- Kill switch **livre** (`halted: false`).
- **1 posição aberta**: BTC/USDT:USDT **short**, entry 64.312,20, TP
  63.164,21, stop **já trailed 3x** (64.886,20 → 64.821,80 → 64.661,10),
  size 0,0014280806, perfil swing.
- **ETH/USDT:USDT em cooldown de 24h** até 19/08 13:39:53 UTC — 3º stop do
  dia, teto de 1440min atingido (mecanismo funcionando como desenhado).

**PnL real desde a migração pro PC2 (01/08 → 18/08): 32 trades fechados,
−2,92 USDT, 10 wins (31,3%).** 30 fecharam por `stop_loss`, 2 por
`take_profit`; 23 em ETH, 9 em BTC. Trades pequenos (perda média por trade
na casa de 0,1–0,5 USDT). **105 `trailing_stop_moved` reais** — o trailing
trabalha de verdade e vários fechamentos rotulados `stop_loss` saíram
POSITIVOS justamente por isso (ex.: hoje +0,088 e +0,122), comportamento
esperado em perp (não existe motivo de saída "trailing_stop" separado em
perp — ver Sessão 29-30/07). Análise de trader em cima desta amostra:
seção "Análise da amostra real de trades" no fim deste arquivo.

**Saúde mecânica nos 18 dias — limpa:** ZERO `kill_switch_tripped`, ZERO
`naked_position_close_failed`, ZERO `*_rearm_stop_failed`, ZERO
`external_close_unconfirmed`. Um único `engine_crash_restart` (12/08
20:33:08 UTC, `exit_code 1073807364` = 0xC000013A, encerramento de console;
`uptime_sec` 97.230 ≈ 27h) — o `supervisor.py` religou sozinho na 1ª
tentativa, exatamente o que ele existe pra fazer. 2 `cooldown_reset`
manuais (11/08 e 14/08). 8 `engine_start` / 3 `engine_stop` na trilha do
PC2 (a diferença são restarts pós-crash/desligamento, não instância dupla —
processo único confirmado agora).

**Ruído recorrente, não é bug (já documentado):** 13.759
`symbol_cycle_error`, **todos** a mesma linha ("amount of BTC/USDT:USDT must
be greater than minimum amount precision of 0.001") — nocional do BTC abaixo
do mínimo da Bybit com o teto de capital atual. **Zero ocorrências hoje**: o
nocional finalmente passou do mínimo e o BTC voltou a operar de verdade (a
posição short aberta agora é prova). 31 `cycle_error` de `wallet-balance`
(falha transitória da Bybit, autolimitada).

**Lacunas de supervisão do handoff anterior: RESOLVIDAS.** O
`C:\Users\lucas\.claude\scheduled-tasks\` deste PC2 tem hoje
`trader-watchdog-pc2` (a cada 30min, somente-leitura, lendo
`C:\BybitAutoTrader\logs\audit.jsonl`) e `dossie-cripto-pc2`. O `.mcp.json`
do PC2 aponta corretamente pra `C:\BybitAutoTrader\.venv\...\mcp_server.py`.

**MCP do PC1: EM STANDBY, deliberadamente (decisão do Lucas, 18/08).** O
`.mcp.json` desta pasta ainda aponta pra um caminho ANTIGO
(`C:\Users\lucas\OneDrive\Documentos\Claude\Projects\Projeto Auto-trader\...`)
que **não existe mais** — o projeto mudou pro Dropbox faz tempo. Não foi
consertado de propósito: quem está vivo é o PC2, e o MCP que importa é o de
lá. Consequência prática: **as ferramentas `trader_halt_status`/
`trader_realized_pnl`/etc. NÃO funcionam a partir desta pasta** — pra
consultar status/PnL reais, use o MCP do PC2 ou leia direto
`C:\BybitAutoTrader\logs\audit.jsonl`. Se um dia o PC1 voltar a ser
operacional, corrigir os dois caminhos do `.mcp.json` é o primeiro passo
(o arquivo está no `.gitignore` — é config local, não versionada).

**Código: PC1 e PC2 estão IDÊNTICOS** — comparei arquivo a arquivo
(`src/**/*.py`, `main.py`, `supervisor.py`, `config/*`, `tests/*`): as
únicas diferenças são de fim de linha (CRLF no Dropbox × LF no clone do
PC2), zero diferença de conteúdo. Ambos em `b528852`, sincronizado com
`origin/main`.

**Suíte de testes: 307/307 na última confirmação (30/07), NÃO re-rodada em
18/08** — o motor está ao vivo e o protocolo do projeto proíbe rodar a
suíte nessa condição (ela escreve/restaura `logs/audit.jsonl` e
`state/*.json` reais). Como nenhum código mudou desde então, a contagem
continua válida; se alguém precisar re-confirmar, parar o motor do PC2
primeiro.

**Branch `cooldown-3-niveis-reset-manual` APAGADA em 18/08** (local e
remota) — confirmada 100% mesclada em `main` antes (`git branch --merged
main` a listava; `git log main..cooldown-3-niveis-reset-manual` vazio). Os
commits dela (`8c71a19`, `5f281b9`) seguem no histórico de `main`.

### Sessão 31/07/2026 — a migração do PC1 para o PC2 (histórico)

**MUDANÇA GRANDE (31/07/2026): a operação 24h migrou deste PC (PC1) para o
PC2 — MESMA conta mainnet, decisão explícita do Lucas ("sim, pode ligar aqui
e deixar o PC1 parado").** Contexto: o Lucas estava configurando um PC2 novo
(`C:\BybitAutoTrader`, fora de qualquer pasta sincronizada — Python/Git/GitHub
CLI instalados via winget, repo clonado, venv criado, dependências instaladas)
pra ser o operador 24h, igual ao plano original do `PASSO-A-PASSO-PC2.md` —
só que esse guia foi escrito em 25/07, ainda em TESTNET com conta separada.
Como o projeto virou mainnet em 27/07, a pergunta foi refeita: que conta o
PC2 devia usar? O Lucas escolheu explicitamente **a MESMA chave de mainnet do
PC1** (não uma conta nova) — isso significa que **NUNCA pode haver `--live`
rodando nos dois PCs ao mesmo tempo** (mesma conta = mesmo saldo/posições;
dois motores independentes gerenciando isso ao mesmo tempo é exatamente o
cenário perigoso que o projeto sempre evitou). Por isso, **este PC (PC1) fica
PARADO PERMANENTEMENTE a partir de agora** — não é uma pausa temporária tipo
"aguardando o Lucas voltar" (como era até a sessão anterior), é a decisão
operacional definitiva: **PC2 = produção 24h; PC1 = só dev/testes, nunca
mais `--live` contínuo sem parar o PC2 antes**.

**Motor confirmado rodando ao vivo no PC2** desde 31/07 ~22:54:38 UTC
(`engine_start`, `dry_run: false`, auditado em `C:\BybitAutoTrader\logs\audit.jsonl`
— arquivo NOVO e LOCAL do PC2, não sincronizado com este `logs/audit.jsonl`
do PC1; a partir de agora, esse é o arquivo que importa para o estado real da
operação). Validado nos primeiros 2 ciclos: `signal_approved` short BTC
recorrente (mesmo "achado banal" já documentado — nocional abaixo do mínimo
de ordem da Bybit pra BTC perp com o teto de capital atual, `symbol_cycle_error`,
não é bug), símbolos ETH/BTC reconciliados corretamente como já abertos (sem
duplicar entrada). Único processo `supervisor.py`→`main.py` confirmado (sem
instância dupla). Um `Monitor` foi armado NESTA sessão observando
`C:\BybitAutoTrader\logs\audit.jsonl` para eventos críticos — mas isso morre
com a sessão (mesma limitação documentada antes pro `Monitor` do PC1); **não
existe hoje um watchdog agendado (`trader-watchdog`) apontando pro PC2** — o
`C:\Users\lucas\.claude\scheduled-tasks\` deste PC2 está VAZIO (confirmado),
ou seja, o `trader-watchdog`/`dossie-cripto-intraday` que já existiam
provavelmente só rodam de onde o Claude Desktop/Cowork do PC1 (ou de outra
máquina) está instalado — **isso é uma lacuna real de supervisão pro PC2 que
precisa de decisão do Lucas**: recriar o watchdog rodando a partir do PC2, ou
aceitar que a supervisão automática por ora só existe dentro de sessões ativas
de Claude Code no PC2. — **SUPERADO: em 18/08 confirmei `trader-watchdog-pc2`
e `dossie-cripto-pc2` já criados e agendados no PC2 (ver Status 18/08 no
topo). Esta lacuna não existe mais.**

**Se for investigar/continuar algo no PC1 (esta pasta), lembrar**: o
`logs/audit.jsonl` DESTE PC1 parou de ser a fonte de verdade da operação
em 31/07 ~22:54 UTC — ele registra o histórico até esse ponto (inclusive o
`engine_stop` manual das 16:58:39 UTC de 30/07, que era pra ter sido temporário
e virou definitivo). Todo evento novo de trading real está em
`C:\BybitAutoTrader\logs\audit.jsonl`, no PC2. As ferramentas MCP
(`trader_halt_status`, `trader_realized_pnl` etc.) deste PC1 continuam
configuradas pra ler os arquivos LOCAIS deste PC1 (`state/*.json`,
`logs/audit.jsonl`) — **elas não enxergam o PC2** a menos que alguém rode o
MCP a partir de lá ou reconfigure os caminhos. Isso também é uma lacuna a
resolver com o Lucas se ele quiser consultar status/PnL do PC2 por aqui. —
**RESOLVIDO POR DECISÃO em 18/08: o MCP do PC1 fica em STANDBY** (o
`.mcp.json` daqui aponta pra um caminho OneDrive que nem existe mais);
o MCP vivo é o do PC2, já configurado certo lá. Ver "MCP do PC1: EM
STANDBY" no Status 18/08 no topo.

**Sem pendência bloqueante de código** — a suíte 307/307 e a validação ao
vivo de perp (long/short, trailing, cooldown 3 níveis) da sessão 29-30/07
seguem válidas (ver "Sessão 29-30/07/2026" logo abaixo). Nenhuma posição
nova foi aberta pelo PC1 desde então; o PC2 herda/reconcilia o estado real
da conta a partir de agora.

**Rastreio da posição herdada RECONSTRUÍDO manualmente em `state/spot_protections.json`
do PC2 (31/07 ~23:57 UTC).** A única posição real aberta na migração —
ETH/USDT:USDT long 0.01, entry 1859,41, perfil swing, aberta pelo PC1 às
14:44:16 UTC do mesmo dia — não tinha nenhum registro local no PC2, porque
`protection_state.backfill_from_audit()` só relê a trilha LOCAL de cada
processo, e o `order_executed` dessa entrada está no `logs/audit.jsonl` do
PC1, nunca no do PC2. Sem esse registro, o PC2 não teria como mover o
trailing, auditar o fechamento, alimentar o cooldown nem cancelar a ordem
irmã órfã quando essa posição fechasse. Corrigido escrevendo o registro à
mão em `state/spot_protections.json`, usando dados confirmados DIRETO na
exchange (não a trilha antiga, que estava desatualizada — o PC1 já tinha
movido o trailing pelo menos uma vez antes de eu ligar o PC2):
`stop_id=46554f93-3b38-4d76-92b5-711bf270c3e5` (trigger real 1834,25 —
diferente do `stop_id`/preço originais da entrada, 0cffc4a4.../1817,64,
confirma que o PC1 já tinha trailed o stop pra cima antes da migração),
`tp_id=dc73a952-a054-47af-9c04-735de9cb0cd0` (trigger 1942,95, igual ao
original — nunca muda), `trail_distance=41,76857142857148` (constante desde
a entrada, único jeito de recalcular `peak_price=stop_price+trail_distance
=1876,0185714285715` com segurança). Verificado com
`protection_state.load()` direto (parseia certo) e confirmado que os
ciclos seguintes do motor rodaram normalmente sem erro depois da escrita.
**Lição pra qualquer migração de PC futura**: `state/spot_protections.json`
(e por extensão `cooldown_state.json`) NUNCA atravessam sozinhos entre
processos/máquinas — se houver posição real aberta no momento da virada,
reconstruir esse arquivo manualmente é um passo necessário, não opcional.

**Se for religar ou investigar algo, lição desta sessão primeiro:** o Lucas
religou o motor várias vezes direto no terminal externo sem sempre avisar
antes. Numa dessas vezes, o comando digitado foi `.venv\Scripts\activate`
seguido de `python supervisor.py --live` (sem o caminho completo) — isso
resolveu pro Python DE SISTEMA (sem as dependências do projeto, faltando
até o `pyyaml`), e o `main.py` crashou 6 vezes seguidas
(`ModuleNotFoundError: No module named 'yaml'`) até o supervisor desistir
sozinho (`engine_supervisor_giveup`, teto de 5 tentativas/30min). **NÃO é
bug de código** (confirmado rodando `main.py --once` direto, funcionou
perfeito) — é especificamente essa combinação de comandos neste ambiente.
**Sempre usar o caminho completo, `.venv\Scripts\python.exe supervisor.py
--live`, nunca `python` puro** (mesmo com o venv "ativado" — não é
confiável aqui). Fora isso, nada pendente: considerar reavaliar os números
de risco do YAML (cooldown 30/60/1440min, teto de capital 50%, alavancagem
2x) — já é pendência aberta desde a v9 das instruções (carregada pra v10), e agora já tem
operação real (long+short) suficiente pra dar ao Lucas uma base de decisão.

## Sessão 19/08/2026 — 15m desligado propagado, cooldowns resetados, melhor dia da conta

Continuação direta da sessão de 18/08. Quatro coisas aconteceram, nesta ordem.

### 1) O motor não subiu na 1ª tentativa — e a causa virou o comando padrão novo

O Lucas rodou o comando e reportou que tinha ligado. A trilha provou o contrário:
**nenhum `engine_start`, zero processos python, `audit.jsonl` sem escrita desde o
`engine_stop`**. Nem `engine_crash_restart` havia — ou seja, o `main.py` nunca
chegou a rodar; o comando não executou.

Confirmei que o boot estava saudável rodando `main.py --once` em **DRY-RUN**
(seguro, nenhuma ordem real): bootou limpo, exit 0, e de quebra **provou o 15m
desligado** (só o perfil `swing` foi avaliado, contra `daytrade`+`swing` antes).

**Achado que virou a correção**: `supervisor.py` resolve os caminhos sozinho
(`ROOT = Path(__file__).resolve().parent`, spawna `main.py` com `sys.executable`
e caminho ABSOLUTO, `cwd=ROOT`). **Não precisa de `cd`.** Comando novo, imune à
causa mais provável (o `cd` não pegar):

    C:\BybitAutoTrader\.venv\Scripts\python.exe C:\BybitAutoTrader\supervisor.py --live

Subiu de primeira. E como o supervisor usa `sys.executable`, **começar pelo
python do venv garante que o filho herde o venv** — é exatamente por isso que
`python` puro quebrava em 31/07: o filho nascia com o Python de sistema.

### 2) Reconciliação da posição herdada — o caminho bom funcionou

A posição BTC ficou aberta durante as ~3h15 de motor parado e **o stop disparou
na Bybit nesse meio-tempo** (as ordens são reais; a corretora executa sozinha).
No 1º ciclo após religar, `_check_perp_exits` detectou e apurou: entrada
64.723,20 → saída 64.553,20, **pnl −0,17 USDT**, `reason: stop_loss`,
**`exit_price_source: stop_order_fill`** — ou seja **confirmou o preenchimento
real** via `fetch_order`, não caiu no modo degradado `external_close_unconfirmed`.
Proteção limpa e **a ordem irmã (TP) cancelada** (0 ordens abertas na Bybit
confirmado) — o risco do bug #49 tratado corretamente. Perda de −0,70R em vez de
−1R porque o stop já tinha sido trailed: bate com a média histórica (−0,703R).

### 3) Reset manual de cooldown SEM o MCP — como fazer

O Lucas pediu para liberar os dois símbolos. **O MCP do PC1 está em standby**
(`.mcp.json` aponta pra um caminho OneDrive que não existe mais), então
`trader_reset_cooldown` não estava disponível. Escrevi `state/control.json` à
mão, no formato exato que `mcp_server._write_control_signal` produz:

```json
{"action":"reset_cooldown","reason":"...","environment":"mainnet",
 "ts":"<ISO UTC>","symbol":"BTC/USDT:USDT"}
```

**Três detalhes que importam:**
- O campo `environment` é **obrigatório na prática**: `_apply_control_signal`
  descarta o sinal (audita `control_signal_environment_mismatch`) se divergir do
  ambiente do processo. Bug #33.
- O engine **consome (unlink) o sinal a cada ciclo** e o arquivo aceita **UM
  símbolo por vez** — resetar dois exige duas escritas separadas por ~1 ciclo.
- Importar `config.settings` ANTES de qualquer coisa, senão `ENVIRONMENT` sai
  errado (lição do bug #47).

Funcionou nos dois: `cooldown_reset` auditado às 20:58:24 (BTC) e 20:59:26 (ETH).
**E o motor aprovou entrada em ETH 3 segundos depois** — mesmo padrão de 29-30/07.

### 4) O dia: 9 trades, +6,418 líquidos — e por que isso não é edge

Entre 14:55 e 17:17 UTC o mercado teve um melt-up (BTC +5,9%, ETH +8,8% em 24h;
um candle de 15m com **+3,04% e volume 22.954 contra os 1.300-6.500 típicos**).
**Verifiquei no OHLCV que era movimento real, não anomalia de dado** — o projeto
já teve um caso de anomalia de testnet (21/07) que custou 6 ciclos de perda.

Resultado: **6 take-profits seguidos** (+8,799) e **3 stops** (−1,745) →
**+6,418 USDT líquidos**. As duas perdas maiores foram reentradas perto do topo
do spike (BTC a 69.090,70 quando o candle bateu 69.893,20), ambas −1R cravado.

**Duas observações estruturais que valem mais que o número:**
- **O TP realiza e protege o ganho.** Cada take-profit embolsou o lucro, então
  quando o movimento reverteu a exposição era só o risco das posições abertas
  (~1,9 USDT), não o ganho do dia. É o que a decisão de 28/07 (trailing e TP
  fixo convivendo) comprou.
- **O cooldown fez exatamente o trabalho dele**: depois dos stops no topo, pausou
  os dois símbolos por 30min — impedindo a reentrada perseguindo uma reversão,
  que é literalmente o cenário do bug #30 que criou o mecanismo.

### 5) Lição de desenho de monitor: silêncio não é sucesso

O vigia armado nesta sessão (`scratchpad/vigia.py`) vigia **ausência de
batimento**, não só eventos ruins. Motivo: se o motor morre, a trilha só para de
crescer — um filtro que só procura erro ficaria **mudo**, e mudo é
indistinguível de "tudo bem". Como o ciclo é ~62s, silêncio acima de 5,5 min
vira alerta. Ele também avisa se a trilha **encolher** (truncamento).

Isso não é teórico: em 29-30/07 um monitor morreu silenciosamente num reconnect
e ~7h de eventos reais passaram sem aviso.

### 6) Correção de uma métrica minha — ver o aviso na seção do trailing

Afirmei que "`tp_rr: 2.0` nunca foi alcançável, MFE máximo +1,777R". **Errado, e
o erro era de MEDIÇÃO.** Detalhe completo no aviso ⚠️ dentro de "Sessão 18/08
(noite) — item 4". Resumo: MFE calculado do `peak_price` dos eventos
`trailing_stop_moved` subestima os trades que fecham no alvo, porque o campo só
atualiza quando o trailing MOVE. `tp_rr: 2.0` já foi atingido 4 vezes — duas
delas hoje, produzindo os melhores trades da conta.

## Sessão 18/08/2026 (noite) — pesquisa 3 (perp long+short), 15m desligado, trilha do PC1 destruída

Pedido do Lucas: "analise as outras 5 estratégias, qual podemos tentar rodar um
teste na mainnet agora" + "ajustar a margem do trailing stop para não ser fisgado
em cada agulhada no mercado lateral" + colocar o watchdog em standby.

### 1) O buraco que ninguém tinha visto: toda pesquisa anterior mediu METADE do sistema

`RELATORIO-2026-07-16.md` e `RELATORIO-2026-07-21-pesquisa-2b.md` mediram **SPOT
LONG-ONLY com fee 0,1%/lado**. A produção desde 28/07 é **PERP LONG+SHORT com fee
taker 0,055%**, alavancagem 2x e teto de nocional de 50%. Nenhuma rodada tinha
medido isso. Construído `research/harness_perp.py` (long e short no mesmo passe,
one-way mode como o live, funding real a cada 8h, teto de nocional, sizing por
risco) + dataset novo `research/data_3/` (8 símbolos, 1h/4h em 3 anos, 15m em 2,
+ funding; 849.841 linhas, zero gap, zero duplicata).

**Validação que o projeto nunca tinha feito: contra a REALIDADE, não contra outro
backtest.** `research/validate_harness_perp.py` roda a config exata de produção na
janela exata dos 43 trades reais. Perfil **swing bateu**: R/trade −0,397 simulado
× −0,466 real; WR 20,5% × 21,1%. Em **15m o simulado é bem pior** que o real
(−0,774 × −0,150) por dois motivos conhecidos e ambos CONSERVADORES (o live tem
cooldown filtrando reentrada, e amostra preço a cada ~62s = trailing mais fino que
o replay). **Números de 15m são PISO, não estimativa central.**
`research/selftest_harness_perp.py`: **35/35** em séries sintéticas com resposta
conhecida na mão.

### 2) Erro metodológico achado NO MEIO da rodada (não repetir)

A 1ª versão da varredura de saída segmentava o backtest em janelas de 18 dias e
**fechava a posição a mercado no fim de cada janela** (`eod`) — saída que não
existe na regra. Numa config isso era **26% de todos os fechamentos**, e essa
config aparecia como a MELHOR de toda a varredura. Refeito como rodada CONTÍNUA
(`eod` ≤0,5%), ela caiu para o meio da tabela. É a mesma classe de erro que já
contaminou o projeto 2x: **um número bom que vem do arcabouço de medição, não da
estratégia.** Qualquer análise nova tem que reportar o % de `eod`.

### 3) Veredito: NÃO promover nenhuma das 5 famílias (painel unânime, 9 agentes)

Rodado painel adversarial (6 lentes + 3 juízes, todos recomputando do zero).
Todos os números reproduziram dígito a dígito; motor auditado limpo (sem
look-ahead — teste de clarividência: dar 1 candle de futuro muda donchian de
+0,389 para +2,053 R/trade; identidade contábil fecha a 4,9e-12). **Os 3 juízes
decidiram por unanimidade e com confiança alta: não promover.** Cinco achados que
eu não tinha:

1. **O critério de aceitação não discrimina nada.** Uma grade INGÊNUA de **300
   configs** de tendência na mesma janela: **300/300 com mediana positiva**, 114
   (38%) com 8/8 símbolos positivos, 180 (60%) melhores que a minha candidata. As
   escolhidas estão no percentil 40-44 de um universo onde tudo ganha. "Mediana
   >0 com 8/8 símbolos" — o critério que o projeto vinha usando — **tem informação
   ZERO nesta janela**. Foi ele que aprovou os falsos positivos de 16/07 e 22/07.
2. **O edge já morreu na própria amostra.** Últimos 12 meses: −3,36% (2/8) e
   −0,30% (4/8). Semestre corrente: −2,86% (0/8) e −1,18% (2/8). Decaimento
   monótono em 6 semestres. **É a janela em que o robô opera hoje.**
3. **A premissa da rodada estava ERRADA.** long-only rende MAIS que long+short
   (+13,34% vs +9,86%), e **spot long-only com fee 0,1% rende ainda mais**
   (+14,77%) — exatamente o que as rodadas anteriores mediam. A diferença desta
   rodada **não é perp/short/fee**; é dado novo + regra de saída nova. O lado
   SHORT é dreno líquido em todos os candidatos (−53,4R, −36,6R).
4. **Estatística.** 0 de 16 séries atinge |t|≥2 (máx 1,44). Remover **1 único
   trade** por símbolo leva o melhor candidato de +336,65R para **−12,75R**.
   Permutação: p=0,0125 no total, mas **p=0,37/0,44 sem os 5 melhores** —
   indistinguível de seguidor de tendência com timing aleatório. Correlação entre
   símbolos dá ~**2,3 séries efetivamente independentes**, não 8.
   **E o contraste que decide a prioridade: a config EM PRODUÇÃO tem 4/8 séries
   com |t|≥2 — a evidência de que ela PERDE é estatisticamente mais forte que a
   de que qualquer candidata GANHA (0/8).**
5. **Ablação:** 80,5% do efeito vem de UM fator — remover o TP fixo (+0,2281 de
   +0,2834) — não da saída por sinal. As 5 diferenças isoladas somam só +0,0419
   (15% do necessário): a virada é **interação**, não soma. Não dá para colher os
   ganhos incrementalmente.

**Dois achados de engenharia, críticos, que valem para qualquer promoção futura:**

- **`_check_signal_exit` é CÓDIGO MORTO em perp.** Único callsite é
  `engine.py:412`, dentro de `_check_spot_exits()`, que retorna em
  `if self.market_type != "spot"` (linha 276). `_check_perp_exits()` nunca chama.
  **Ligar `exit_on_signal: true` no YAML hoje, em perp, não faz absolutamente
  nada.**
- **`engine.py:789` fixa `side="long"`** (`return should_exit(snap, {**protection,
  "side": "long"})`), sobrescrevendo o `side` real que o `protection_state` já
  persiste. Se alguém construir o caminho de saída por sinal em perp sem corrigir
  isso, o resultado medido vira **−20,59%** (14.309 trades, 2.165 USDT de fee). É
  bug de UMA LINHA com efeito de inverter o resultado.
- **O kill switch de 3% de drawdown diário (reset MANUAL) congela a estratégia
  candidata em 6 de 8 símbolos** na simulação (BTC para em 2024-03-05 com 27
  trades em vez de 187). O harness declara "sem kill switch"; o motor real tem.
  **O backtest não modela isso** — qualquer promoção precisa resolver antes.

Relatório completo: `research/RELATORIO-2026-08-18-pesquisa-3-perp.md`.

### 4) O trailing — a hipótese da "agulhada" NÃO se confirma

Medido nos **trades reais** (32 pareados com `trailing_stop_moved`): **90,6% das
saídas ocorreram com recuo de 0,95–1,05R do pico** — exatamente a distância do
trailing, toda vez. Se o stop estivesse sendo fisgado por agulhada curta, o recuo
seria MUITO menor que 1R. O stop está fazendo exatamente o que foi configurado; o
problema é que o preço raramente anda a favor: **MFE mediano +0,597R**. Só **31%**
dos trades chegam a MFE ≥1,00R, que é o mínimo para o stop movido passar do
breakeven — nos outros 69% o trailing **só reduz a perda** (perda média real
−0,703R em vez de −1R).

> ⚠️ **CORREÇÃO (19/08/2026): a afirmação "MFE máximo +1,777R, logo `tp_rr: 2.0`
> nunca foi alcançável" estava ERRADA — e o erro era de MEDIÇÃO, minha.** O MFE
> foi calculado a partir do `peak_price` dos eventos `trailing_stop_moved`, e
> esse campo **só atualiza quando o trailing MOVE**. Num fechamento por TP, o
> último movimento acontece ANTES do alvo ser tocado, então o MFE medido
> **subestima** justamente os trades que foram melhor. Verificado trade a trade:
> **nos 4 fechamentos por `take_profit` o R real superou o MFE medido** (+0,26R,
> +0,88R, +0,37R, +0,12R); em **todos** os 31 fechamentos por stop o R real ficou
> ≤ MFE, como tem que ser. Ou seja: `tp_rr: 2.0` **É alcançável e já foi atingido
> 4 vezes** (R real +1,954 / +2,048 / +1,991 / +1,995).
> **O que NÃO muda:** a recomendação de não baixar `tp_rr` continua de pé — ela
> vem do walk-forward (tp 0,75 → −36,90% vs tp 2,0 → −23,29%), não desta métrica.
> Se algo, ficou mais forte: em 19/08 os dois TPs produziram os dois melhores
> trades da história da conta.
> **Lição de método**: `peak_price` não serve como proxy de MFE para trades que
> fecham no alvo. Para MFE de verdade seria preciso reconstruir do OHLCV do
> período do trade, não da trilha.

**O dano real do trailing é CHURN, não agulhada:** quase dobra o número de trades
(donchian 781→1.401) e corta os poucos ganhadores grandes, derrubando R/trade de
+0,2025 para +0,0099.

**Três parâmetros se confundem sob o nome "margem do trailing" — não misturar:**
1. `trail_distance` (hoje amarrada ao stop inicial, 1,5×ATR) — é ESTA que decide
   se uma agulhada pega o stop.
2. `TRAIL_MIN_STEP_PCT` (0,1%) — só evita churn de ordem. **Praticamente não
   afeta ser fisgado**; mexer aqui achando que resolve agulhada é o erro clássico
   (medido: variar 0,1%→2,0% muda R/trade de −0,063 para −0,072).
3. `trail_start_r` (gatilho de ativação) — **NÃO EXISTE no motor**. Implementado
   e testado só no harness; melhora o retorno mas **por reduzir trades**, não por
   melhorar R/trade (que piora).

Ressalva medida por uma lente: o trailing tem **ambiguidade de caminho
intra-candle em 6-21% dos candles**, sistematicamente FAVORÁVEL às configs com
trailing (no limite pessimista a config de produção vai a −70,37%). Ou seja, todo
número publicado de config COM trailing carrega banda de dezenas de pp — e o
número real é provavelmente pior que o medido.

### 5) Correções ao que a análise da MANHÃ de 18/08 tinha afirmado

- **Duração mediana NÃO é 22h.** É **129 min** no total; **71 min** no daytrade e
  1.230 min (20,5h) no swing. O "1.336 min" da análise anterior sobreviveu da
  passada com pareamento FIFO bugado. Consequência: a recomendação #5 ("descasamento
  de horizonte") **não se sustenta** — 20,5h num perfil de 4h é coerente.
- **Baixar `tp_rr` para 0,6–0,75 (era a recomendação #1) PIORA.** No walk-forward:
  tp 0,75 → −36,90% contra tp 2,0 → −23,29%. Fecha cedo, reentra, multiplica fee.
  A simulação ingênua sobre MFE que sugeria o contrário não considerava reentrada
  nem custo.
- **Swing é MUITO pior que daytrade em R/trade** (−0,466 vs −0,150; payoff 0,58 vs
  1,36) — mas daytrade perde mais em DINHEIRO por causa da fee. São coisas
  diferentes e a análise anterior não separava.

### 6) Incidente: a suíte de testes DESTRUIU a trilha do PC1 (bug #50, corrigido)

Ver bug #50. Resumo: rodei a suíte com o motor parado (parecia seguro) e perdi
`logs/audit.jsonl` do PC1 (15.858 linhas → 1). **PC2 intacto.** Corrigido na
fonte com `tests/_guard.py`, testado contra o cenário exato. **Lição operacional
nova**: rodar a suíte a partir de uma CÓPIA fora da pasta sincronizada elimina a
classe inteira de problema (`os.replace` falha com o arquivo mapeado pelo
Dropbox). Foi assim que confirmei **307/307** (299 smoke + 8 ciclo).

### 7) Incidente operacional: "liguei o motor" mas o motor não subiu

O Lucas executou o comando e reportou que tinha ligado. A trilha provou o
contrário: **nenhum `engine_start`, zero processos python, `audit.jsonl` sem
escrita**. Confirmei que o boot estava saudável rodando `main.py --once` em
DRY-RUN (seguro, nenhuma ordem real) — bootou limpo, exit 0. Ou seja: o comando
não chegou a executar.

**Achado que virou a correção**: `supervisor.py` resolve os caminhos sozinho
(`ROOT = Path(__file__).resolve().parent`, spawna `main.py` com `sys.executable` e
caminho ABSOLUTO, `cwd=ROOT`). **Não precisa de `cd`.** Comando novo, imune à
causa mais provável (o `cd` não pegar):

    C:\BybitAutoTrader\.venv\Scripts\python.exe C:\BybitAutoTrader\supervisor.py --live

Com esse comando subiu de primeira. E como o supervisor usa `sys.executable`,
**começar pelo python do venv garante que o filho herde o venv** — é exatamente
por isso que `python` puro quebrava em 31/07: o filho nascia com o Python de
sistema, sem `pyyaml`.

### 8) Reconciliação da posição herdada — o caminho bom funcionou

A posição BTC ficou aberta durante as ~3h15 de motor parado e **o stop disparou na
Bybit nesse meio-tempo** (ordens são reais, a corretora executa sozinha). No 1º
ciclo após religar, `_check_perp_exits` detectou e apurou: entrada 64.723,20 →
saída 64.553,20, size 0,001, **pnl −0,17 USDT**, `reason: stop_loss`,
**`exit_price_source: stop_order_fill`** — ou seja **confirmou o preenchimento
real** via `fetch_order`, não caiu no modo degradado `external_close_unconfirmed`.
Proteção limpa, e **a ordem irmã (TP) foi cancelada** (confirmado: 0 ordens
abertas na Bybit) — o risco do bug #49 tratado corretamente. Perda de −0,70R em
vez de −1R porque o stop já tinha sido trailed: bate com a média histórica
(−0,703R).

### 9) Watchdog em standby + causa raiz do bug de permissão

`trader-watchdog-pc2` → `enabled: false` (decisão do Lucas; SKILL.md preservado).
**Causa do "pede autorização toda vez"**: as 69 regras de allowlist vivem em
`.claude/settings.local.json` **do projeto**, e `~/.claude/settings.json` **não
tinha bloco `permissions` nenhum**. Tarefa agendada roda com outro cwd → nada
pré-aprovado. Agrava: a maioria das regras são comandos literais de uma vez só,
com caminhos OneDrive que nem existem mais. Preparei o bloco corrigido (allow
escopado + **deny** em `config/`, `state/` e `logs/` como defesa em profundidade),
mas **o classificador de auto mode bloqueou eu mesmo aplicar — corretamente**, já
que seria auto-concessão de permissão. Pendente do Lucas.

## Sessão 29-30/07/2026 — suíte confirmada, perp validado ao vivo ponta a ponta (long E short)

Continuação direta da sessão anterior (28-29/07), que tinha encerrado com o
motor caído e a suíte pendente de rodar (ver "PRÓXIMA AÇÃO" da época). Nesta
sessão: suíte rodada e corrigida, código commitado e enviado pro GitHub, e —
o mais importante — TODA a superfície nova do trailing/fechamento/cooldown
em perp (bugs #48/#49, escritos mas nunca exercitados com dinheiro real) foi
validada ao vivo, incluindo o lado SHORT pela primeira vez na história do
projeto.

**1) Suíte completa rodada, achado e corrigido um bug — no fixture de
teste, não no motor.** Confirmado por `Get-CimInstance Win32_Process` que
nenhum `main.py`/`supervisor.py` estava rodando, então `test_smoke.py` +
`test_ciclo.py` rodaram: **297/299 na 1ª rodada** — as 2 falhas eram
exatamente na seção 31 (trailing perp), a seção que a sessão anterior
tinha deixado pendente. Investigado: `FakePerpExit.fetch_order`
(`tests/test_smoke.py`) lia o atributo `FakePerpExit.ORDER_RESPONSES` da
CLASSE-BASE, hardcoded, em vez de `type(self).ORDER_RESPONSES` — a
subclasse `FakePerpTrailing` (usada só na seção 31) reatribuía
`ORDER_RESPONSES` nela mesma sem nenhum efeito, então os dois testes mais
importantes da seção (curar um arquivo stale contra o gatilho REAL da
exchange; abortar sem tentar nada quando o stop já tinha fechado) caíam
num fallback genérico que mascarava exatamente o cenário que deveriam
provar. Corrigido trocando pra `type(self).ORDER_RESPONSES` — não mexe em
nenhum teste da seção 30 (que sempre usou a classe-base direto, `type(self)
== FakePerpExit` nesse caso, comportamento idêntico). Suíte final: **299/299
smoke + 8/8 ciclo = 307/307 verde**. A lógica real de
`_update_perp_trailing_stop` em `src/engine.py` nunca esteve errada — só
não tinha prova.

**2) Dois commits feitos e enviados pro GitHub, a pedido do Lucas**
("commita a correção do teste" → "commita as outras também" → "push pro
origin"): `548300d` (só o fix do fixture, mas como toda a seção 30/31 de
`tests/test_smoke.py` já estava uncommitted da sessão anterior, não dava
pra isolar só a linha da correção — o commit ficou com o arquivo inteiro,
mensagem deixa claro qual é a correção específica) e `b528852` (o resto:
`CLAUDE.md`, `config/risk_config.yaml`, `src/engine.py`,
`src/exchange/bybit_client.py`, `src/execution/executor.py`,
`src/execution/protection_state.py` — perp religado, teto de alavancagem/
capital, fechamento auditado, trailing real; bugs #48/#49 da sessão
anterior). `git push origin main`: `18b3e55..b528852`. Repositório
GitHub (`wonderboat-ai/bybit-auto-trader`) atualizado; PC2 pode puxar via
`git pull` quando religar (motor parado lá primeiro, mesma regra de
sempre).

**3) Motor religado — MUITAS vezes ao longo da sessão, num padrão caótico
de liga/desliga que vale registrar como lição.** Sequência real (todos os
horários UTC, 29-30/07): `engine_start` 03:52:41 → `trade_closed` real
03:55:59 (ETH long, stop_loss, -0,22 USDT — 1ª validação ao vivo do
fechamento auditado em perp, bug #49) → `engine_stop`/manual 03:58:45 (o
Lucas, direto no terminal, confirmado por ele no chat: "PAREI") →
crash-loop de 04:09 a 04:14 (6 tentativas, `engine_supervisor_giveup` —
ver lição do `python` sem caminho completo, "PRÓXIMA AÇÃO" acima) →
mais liga/desliga manual entre 04:15 e 04:41 (`engine_start`/`engine_stop`
alternando a cada poucos minutos, inclusive mais um crash-loop de 1
tentativa) → **04:41:20 estabilizou** e rodou contínuo por quase 7h.
Durante essa janela estável: 04:56:23 nova entrada ETH **SHORT** (primeira
posição short REAL de perp neste projeto, depois do religamento de
short/perp na sessão anterior) → 06:28:49 `trade_closed` (short,
stop_loss, entry 1.904,58 → exit 1.918,01, pnl -0,27 — confirma o fix do
PnL invertido pra short, bug #49, funcionando certo ao vivo) → esse foi o
**3º stop do dia no ETH/USDT:USDT, cooldown escalou pro teto de 24h**
(1440min) — primeira vez que o 3º nível é confirmado ao vivo (os níveis
1/2, 30/60min, já tinham sido confirmados em 22/07; o teto de 24h nunca
tinha dado esse 3º stop no mesmo dia até agora). Motor ficou rodando
estável (só BTC falhando no notional mínimo, esperado) até `engine_stop`
manual 11:30:21 (o Lucas de novo, sem avisar antes — só percebi
perguntando "posso ligar o motor" dele, depois reconstruindo a trilha).
Religado por mim 21:31:13 (a pedido explícito, "religa e rearma o
monitor") — rodando desde então, sem interrupção, até o fechamento deste
handoff.

**Lição operacional confirmada de novo nesta sessão**: o Lucas tem acesso
direto ao terminal externo que eu abro pra rodar o motor, e usa esse acesso
— religou/parou várias vezes sem sempre me avisar antes ou depois. Isso é
esperado e está dentro do previsto (ele tem controle total sobre `--live`,
por desenho), mas na prática significa que a trilha (`logs/audit.jsonl`) é
SEMPRE a fonte de verdade, nunca a suposição de "a última vez que eu chequei
estava rodando". Reconciliar contra a trilha inteira depois de qualquer
gap, não confiar só no que o monitor pegou (ver item 5 abaixo).

**4) Reset manual de cooldown via MCP, usado de verdade pela primeira
vez.** A pedido do Lucas ("resetar antes via trader_reset_cooldown"),
chamei `trader_reset_cooldown(symbol="ETH/USDT:USDT", confirm=True)` às
22:21:23 UTC (cooldown ainda tinha ~8h pro prazo natural, 30/07 06:28) —
`cooldown_reset` auditado corretamente, e o motor aprovou uma entrada nova
em ETH (short) só 3 segundos depois, no ciclo seguinte. Confirma que o
canal `state/control.json` → `_apply_control_signal` funciona ponta a
ponta pra esse tipo de sinal também (só tinha sido testado, nunca usado ao
vivo até agora).

**5) Trailing em perp validado ao vivo pela primeira vez — múltiplos
movimentos reais, e um fechamento pelo próprio stop trailed.** A posição
short aberta às 22:21:28 (entry 1.907,73, stop original 1.924,68) teve o
stop movido **5 vezes reais** conforme o preço caiu a favor (pico indo de
1.905,46 até 1.895,20), sempre auditado com `trailing_stop_moved` (old_stop/
new_stop/peak_price corretos, side=short). Às 01:33:02 UTC de 30/07 o
preço reverteu e bateu no stop JÁ MOVIDO (não no original) — fechou com
`pnl_usdt = -0,09`, MUITO menor do que teria sido no stop original
(1.924,68 vs o preço real de saída 1.912,21 — a diferença é exatamente o
que o trailing capturou de proteção extra). Em perp não existe um motivo
de fechamento "trailing_stop" separado do "stop_loss" (diferente do spot,
que tem `trailing_exit` pra quando o preço já rompeu o nível antes do
re-armamento conseguir acontecer) — o trailing em perp só move o MESMO
stop real, então o fechamento sempre audita como `stop_loss`, só que no
nível JÁ TRAILED. Essa era a última peça do bug #49 sem validação ao vivo
(ver "PRÓXIMA AÇÃO" da sessão anterior) — agora fechada, nos dois lados
(long confirmado 03:55:59, short confirmado ponta a ponta com trailing
completo aqui).

**6) Achado operacional novo: um `Monitor` persistente (armado na trilha)
se perdeu no meio da sessão, sem eu perceber na hora.** Entre checar o
estado por volta de 04:28 UTC e a pergunta seguinte do Lucas
("QUANDO TERMINA O COOLDOWN ETH?"), um reconnect de app/MCP aconteceu (via
notificações do sistema — servidores MCP caíram e voltaram) e o `Monitor`
que eu tinha armado (`bpxd9ih1k`) morreu sem deixar registro de conclusão
— só percebi porque o sistema avisou explicitamente ("No completion record
was found"). Resultado prático: ~7 horas de eventos reais (incluindo o 2º e
3º stop do dia, a entrada short, e a escalada do cooldown pro teto de 24h)
aconteceram SEM eu saber em tempo real — só reconstruí tudo depois, lendo a
trilha inteira (`tail`/`grep` em `logs/audit.jsonl`), quando o Lucas
perguntou sobre o cooldown. **Lição pra sessões futuras**: um `Monitor`
persistente pode morrer silenciosamente num reconnect/pausa de sessão longa
— depois de qualquer gap de tempo real, SEMPRE reconciliar contra a trilha
completa (`grep` pelos eventos críticos desde o último ponto confirmado)
antes de assumir que nada aconteceu, nunca confiar cegamente em "o monitor
teria me avisado". Um novo `Monitor` (`b4zc42168`) foi armado no restart das
21:31:13 e segue ativo no fechamento deste handoff.

**Estado da suíte de testes, atualizado**: **299/299 `test_smoke.py` + 8/8
`test_ciclo.py` = 307/307 verde** — cresceu de 288/288 (280+8) com a seção
31 (trailing perp) agora genuinamente executada e passando, mais o fix do
fixture. Ver seção "Testes" mais abaixo.

## Sessão 28-29/07/2026 — perp/short religados, dois bugs estruturais achados e corrigidos

A pedido explícito do Lucas ("habilita agora modo long e short futuros"),
depois de eu inicialmente recusar por causa do bloqueio de compliance de
15/07 (retCode 10024) — ele esclareceu que a conta configurada no `.env`
(mesma chave, não uma conta nova) já tinha permissão de derivativos, pedi
uma sonda só-leitura (`privateGetV5UserQueryApi`) que confirmou
`ContractTrade`/`Derivatives` habilitados na chave, KYC `LEVEL_2`,
`unifiedMarginStatus: 5` — e ele autorizou a virada. Decisões de risco
tomadas por ele, nomeadas explicitamente: alavancagem **2x** (teto, não
valor forçado — `risk_manager.evaluate()` calcula
`min(max_leverage, necessária)`) e depois, à parte, **teto de 50% do
equity por trade** ("equity 50% pra cada BTC e ETH" — não é uma reserva
rígida por símbolo, o código não tem isso; é o teto por-trade existente
baixado de 100% pra 50%, que na prática reparte razoavelmente entre os 2
símbolos configurados). `config/risk_config.yaml`: `market.type: "perp"`,
`per_trade.max_leverage: 2`, `per_trade.max_notional_pct_equity: 50.0`.

**Confirmado ao vivo: o bloqueio de compliance de 15/07 NÃO se repetiu.**
Primeira ordem real em perpétuo da história do projeto, ETH/USDT long,
22:41:04 UTC de 28/07, entrada 1.916,62 — aceita, com stop E take-profit
reais na exchange (perp tem os dois nativamente; diferente de spot, que
nunca teve TP real por falta de OCO). BTC continua falhando à parte —
motivo banal, não é bloqueio: com equity ~110 USDT e teto de 50%, o
nocional calculado (~55 USDT) fica abaixo do mínimo de ordem da Bybit pra
BTC perp (0,001 BTC ≈ 64 USDT no preço atual) — `symbol_cycle_error`
recorrente, "amount must be greater than minimum amount precision of
0.001". Não corrigido (é decisão de capital/teto, não bug).

**Incidente 1 — `InvalidNonce` (retCode 10002), ~5h23min de `cycle_error`
ininterrupto.** Achado pelo monitor da trilha que eu tinha armado no início
da sessão (mesmo padrão do `Monitor` de 19/07): entre 07:56 e 13:16 UTC de
28/07 (bem antes da virada pra perp — isso é bug antigo, não relacionado),
TODA chamada assinada à Bybit falhou com timestamp desatualizado. Causa
raiz: `BybitClient.__init__` mede o offset de relógio local↔servidor com
`load_time_difference()` **uma única vez no boot**; se essa medição pegar
uma requisição lenta/com jitter (rede, TLS, o Avast interceptando HTTPS —
já documentado como fonte de instabilidade neste projeto), o offset fica
errado e TODA chamada seguinte falha, pro resto da vida do processo. Corrigido
em `src/exchange/bybit_client.py`: `_with_retry` deixou de ser
`@staticmethod`, agora trata `ccxt.InvalidNonce` (subclasse de
`NetworkError`) como caso especial — re-sincroniza (`load_time_difference()`
de novo) antes de cada nova tentativa, em vez de repetir a mesma assinatura
ruim 3x e desistir. Confirmado reproduzindo o erro exato ao vivo (retCode
10002 batendo de novo minutos depois de um restart limpo) e corrigindo.

**Incidente 2 — duas instâncias do motor rodando ao mesmo tempo, ~57s de
sobreposição.** O Lucas religou o motor manualmente ("liguei o motor") sem
saber que eu já tinha religado ~1min antes (dois `engine_start` seguidos
sem `engine_stop` entre eles). Achado ao checar `Get-CimInstance
Win32_Process` — duas árvores `supervisor.py`→`main.py` completas e
independentes. Parei a mais nova, verifiquei `state/kill_switch_state.json`
/`cooldown_state.json`/`spot_protections.json` — nenhuma corrupção (só
vetos/pulos duplicados na sobreposição, nenhuma ordem real disparada duas
vezes). **Lição pra sessões futuras**: eu aviso quando ligo/desligo o motor
por aqui, mas se o Lucas mexer em paralelo sem eu saber, esse risco existe
de novo — vale confirmar "está rodando?" antes de religar manualmente.

**Achado operacional, reforça lição já documentada (26/07): `CTRL_C_EVENT`
via `AttachConsole`/`GenerateConsoleCtrlEvent` não é confiável pra parar um
processo que eu mesmo iniciei via `run_in_background` do Bash tool** — falhou
repetidas vezes nesta sessão especificamente pras árvores que eu tinha
subido assim (funcionou normalmente pra parar a árvore que o Lucas tinha
iniciado do jeito dele). Fallback usado: `TaskStop` no id da tarefa em
background — funciona, mas é um kill forçado (sem `engine_stop` limpo na
trilha, indistinguível de crash na auditoria). Usar com essa ressalva em
mente.

### Bug crítico achado e corrigido: fechamento de posição PERP nunca era auditado

Perp nunca tinha operado de verdade neste projeto antes de hoje (bloqueio de
compliance desde 15/07) — então o mecanismo equivalente ao `_check_spot_exits`
(que audita `trade_closed`, alimenta o cooldown, e cuida de órfãos) **nunca
tinha sido construído pro lado perp**. Descoberto ao vivo: a 1ª posição real
fechou pelo stop e nada foi auditado — nem `trade_closed`, nem cooldown — e
a ordem de TP irmã ficou **ativa e órfã** na exchange (Bybit não tem OCO
nativo entre duas condicionais criadas separadamente). Prova concreta: o
Lucas mandou print da tela "Open Orders" da Bybit mostrando **4 ordens
condicionais pro ETH quando só deveriam existir 2** — as outras 2 eram TPs
órfãos de posições já fechadas (uma de antes do fix existir, outra de
DEPOIS — ver ressalva abaixo). Ele cancelou as duas manualmente.

**Fix** (a pedido do Lucas, "corrige o fechamento auditado pro perp"):
- `src/execution/protection_state.py`: ganhou `tp_id` (só populado em
  perp — spot nunca arma TP real) e `side` (`"long"`/`"short"`,
  default `"long"`). Docstring atualizada — deixou de ser só sobre spot.
- `src/execution/executor.py`: agora persiste a proteção em **toda**
  entrada, spot E perp (antes só spot persistia, pro TP por software) —
  grava `stop_id`, `tp_id` e `side` reais.
- `src/exchange/bybit_client.py`: novo `cancel_order(order_id, symbol)`.
- `src/engine.py`: novo `_check_perp_exits()`/`_handle_perp_position_closed()`
  — a cada ciclo, detecta posição perp rastreada que sumiu, confirma via
  `fetch_order` qual das DUAS ordens reais (stop ou TP) disparou, audita
  `trade_closed` com o fill real e o `side` correto, alimenta o cooldown, e
  **cancela a ordem irmã órfã** (só quando confirma com certeza qual
  disparou — nunca cancela às cegas, mesmo risco aceito já documentado no
  caminho spot pra não derrubar a proteção de uma posição nova reaberta no
  meio). Backfill na primeira vez que vê uma posição perp sem registro
  (cobre a posição real que já estava aberta quando o fix foi escrito).
  Chamado em `run_once()` ao lado de `_check_spot_exits()` — cada um se
  auto-gate pelo `market_type` real, nunca os dois fazem trabalho no mesmo
  boot.

**Ressalva achada e NÃO resolvida — `external_close_unconfirmed` mesmo com
o fix ativo.** Um dos 2 TPs órfãos que o Lucas cancelou (`e34ff50c`) era de
uma posição que fechou DEPOIS do fix já estar rodando. Investigado: a
ordem de STOP dela **disparou de verdade** (`triggerPrice` bateu), mas a
Bybit **rejeitou a execução** (`status: "rejected"`, `filled: 0`,
`rejectReason: "EC_NoError"` — "sem erro", preenchimento zero mesmo assim).
A posição fechou por algum mecanismo que não deixou rastro confirmável em
nenhuma das duas ordens rastreadas. O fix se comportou como desenhado
(nunca inventa um fill que não confirmou — `reason="external_close_unconfirmed"`,
PnL aproximado) mas, como consequência do mesmo desenho conservador
("nunca cancela às cegas sem confirmar qual disparou"), a ordem órfã não
foi limpa automaticamente nesse caso. Não investigado mais fundo (provável
comportamento específico da Bybit pra ordem condicional rejeitada — sem
padrão anterior neste projeto pra comparar) nem corrigido — fica como risco
aceito e documentado, mesmo espírito de outras aproximações já aceitas no
caminho spot. Se voltar a acontecer, checar `Open Orders` na Bybit
periodicamente por enquanto.

### Bug relacionado achado e corrigido: PnL/side hardcoded como "long"

Ao investigar o trailing em perp (pedido seguinte do Lucas, "corrige o
trailing em perp também"), achei que `_handle_perp_position_closed`
hardcodeava `side="long"` no audit e usava `(exit_price - entry_price) *
size` sem inverter — fórmula ERRADA pra uma posição SHORT (que agora é
alcançável de verdade, já que o Lucas religou short em perp hoje; a
estratégia determinística já gera sinais SHORT, `deterministic.py`, e o
`risk_manager` não veta mais em perp). Nenhuma posição short abriu ainda
hoje (só LONG apareceu na prática), então o bug nunca chegou a produzir um
número errado ao vivo — mas era alcançável no próximo cruzamento EMA pra
baixo. Corrigido junto com o mesmo fix de proteção: `side` agora
rastreado ponta a ponta (`protection_state.set_protection`/
`backfill_from_audit` → `executor.py` grava a partir de
`signal.direction` → `engine.py` lê pra inverter o sinal do PnL e auditar
o `side` real, não mais fixo).

### Trailing em perp — implementado, testes ESCRITOS mas NÃO EXECUTADOS

A pedido do Lucas ("corrige o trailing em perp também" — os metadados
`trail_distance`/`peak_price` já eram gravados na entrada desde o fix
anterior, mas nada movia o stop de verdade). Novo
`engine._update_perp_trailing_stop(symbol, protection, price)`, chamado a
cada ciclo dentro de `_check_perp_exits()` pra todo símbolo rastreado ainda
aberto com `trailing=True`. Diferente do trailing spot
(`_update_trailing_stop`): perp nunca tem o problema de saldo ocupado —
mover é sempre cancelar a ordem de STOP antiga (por id, via o
`cancel_order` novo) e criar outra; **o TP nunca é tocado**, fica intacto o
tempo todo (diferença estrutural do spot, que precisa cancelar TUDO pra
liberar saldo). Suporta LONG e SHORT — a direção inverte a lógica inteira
(pico vira fundo, sobe vira desce, `origin_side` pro `set_stop_loss` também
inverte). Mesmas salvaguardas do trailing spot: cura de arquivo stale
(confere o gatilho REAL na exchange antes de mover), nunca tenta mover se o
nível já foi rompido (perp sempre tem stop real — quem dispara é a própria
ordem, não este método; `_check_perp_exits` do próximo ciclo reconcilia),
aborta sem crashar se o stop já fechou/o cancelamento falha, re-arma no
preço ANTIGO se o stop NOVO falhar depois do cancelamento (nunca deixa a
posição sem stop nenhum).

**Seção 31 de `tests/test_smoke.py` (9 sub-testes) escrita cobrindo**: move
LONG, move SHORT, melhora abaixo do passo mínimo (só persiste o pico),
nível já rompido (nenhuma chamada — deixa a ordem real disparar), cura de
arquivo stale, stop já confirmadamente fechado (aborta, deixa pro próximo
ciclo), falha ao cancelar o antigo (aborta sem crashar), falha ao armar o
novo (re-arma no antigo, audita `trailing_move_failed_stop_rearmed`), sem
stop_id/size rastreado (aborta). **NUNCA RODADA** — o Lucas pediu
explicitamente pra eu avisar e parar antes de rodar a suíte (sessão
anterior tinha rodado a suíte várias vezes com o motor AO VIVO por
descuido — sem dano confirmado, mas é exatamente o risco que o protocolo
"nunca rodar a suíte com o motor vivo" existe pra evitar), e a sessão foi
encerrada nesse ponto antes de eu conseguir confirmar "motor parado" com
ele. **Isso é a pendência #1 da próxima sessão — ver "PRÓXIMA AÇÃO" no
topo do arquivo.**

**27/07/2026 — O DIA DA TRANSIÇÃO DE TESTNET PARA MAINNET.** A pedido
explícito do Lucas ("vamos rodar na mainnet", chave de API de mainnet
gerada e preenchida por ele mesmo, autorização confirmada passo a passo),
o projeto operou pela primeira vez contra a conta REAL da Bybit (spot,
equity ~24 USDT — bem menor que a testnet, então o teto de capital por
trade em `config/risk_config.yaml` foi elevado de 20% para 100% do equity
na mesma sessão, decisão aprovada do Lucas, ver comentário no próprio YAML).
Confirmado funcionando: leitura de saldo real, um ciclo `--once` dry-run
que aprovaria uma entrada real em BTC/USDT. **Nenhuma ordem real foi
executada ainda** — o motor `--live` contínuo em mainnet é decisão que o
Lucas precisa disparar pessoalmente (regra de segurança do agente: nunca
inicio `--live` sozinho, é "executar operação financeira").

**Arquivamento da era testnet**: às 23:13:26 UTC, `logs/audit.jsonl` foi
zerado pra começar o PnL da mainnet do zero — as 35.479 linhas da era
testnet (19/07 a 27/07, ~8 dias corridos com pausas manuais, PnL fictício
final +90,37 USDT bruto sobre 39 trade_closed, 33,3% win rate) foram
preservadas em `Historico-Testnet-2026-07-27/audit-testnet-completo.jsonl`
(~6,4MB) + resumo em `Historico-Testnet-2026-07-27/RESULTADO-FINAL-TESTNET.md`.
**Nenhuma ferramenta MCP (`trader_realized_pnl` etc.) lê o arquivo
arquivado automaticamente** — qualquer pedido de "histórico/PnL completo
desde o início" precisa incluir esse arquivo explicitamente.

**Dois incidentes operacionais do próprio dia, ambos achados e corrigidos
na mesma sessão — lição pra qualquer auditoria/sessão multi-agente
futura neste projeto:**
1. **`.env` foi revertido pra `ENVIRONMENT=testnet` sozinho**, no meio da
   auditoria completa descrita abaixo — um dos agentes do workflow, ao
   investigar esse exato achado (ver bug #39), aparentemente reverteu a
   linha sem querer. Achado e corrigido de volta pra `mainnet` na mesma
   sessão (chaves de API não foram afetadas).
2. **Múltiplos agentes da mesma auditoria rodaram `tests/test_smoke.py`/
   `test_ciclo.py` CONCORRENTEMENTE contra os arquivos reais** —
   `logs/audit.jsonl`, `state/cooldown_state.json` e
   `state/spot_protections.json`. O backup/restauração desses testes
   (`atexit`, sobrescreve o arquivo inteiro) foi desenhado pra execução
   SERIAL, não concorrente: cada restauração sobrescrevia por cima do que
   a OUTRA sessão tinha acabado de escrever, deixando `logs/audit.jsonl`
   com eventos fabricados de teste (`llm_signal`/`signal_vetoed` sintéticos)
   no lugar do evento real de arquivamento, `state/cooldown_state.json` com
   símbolos de teste fantasma (`ZERO/USDT`, `NOENTRY/USDT`, `DOT/USDT` com
   cooldown ativo até o dia seguinte) e `state/spot_protections.json`
   zerado (perdeu o rastreio das 2 posições reais de testnet ainda abertas
   na conta). **Tudo restaurado manualmente pro estado correto** (o evento
   `audit_maintenance` original foi reconstituído com o texto/timestamp
   exatos; os dois arquivos de estado voltaram ao conteúdo real de antes).
   **Lição registrada para o futuro**: nunca deixar duas lentes/agentes de
   um mesmo workflow rodarem a suíte de testes ao mesmo tempo contra os
   arquivos reais — isolar por `AUDIT_PATH`/rodar serializado, mesmo que o
   objetivo de cada uma seja só validar uma correção pontual.

**Auditoria completa (pente-fino) rodada antes de considerar o dia
"fechado"**, a pedido do Lucas — workflow de 24 agentes (5 lentes de
revisão + verificação cética por achado + suíte de testes), 18 achados
únicos, 17 confirmados como reais. Resumo (detalhe completo nos bugs #33
a #41 abaixo):
- **7 bugs corrigidos diretamente pelo workflow** (pequenos, seguros,
  mesmo padrão "achado→confirmado→corrigido" de sempre): guarda de
  ambiente no canal MCP→engine (`control.json`), campo `environment` em
  todo evento auditado + breakdown por ambiente no `trader_realized_pnl`,
  rearm de stop mudo corrigido (agora sempre audita), mesma classe do bug
  #29 replicada e corrigida no caminho de SAÍDA (só existia na entrada),
  confirmação de fill=0 explícito na venda a mercado, `kill_switch_state.py`/
  `cooldown_state.py` não derrubam mais o boot por falha transitória de
  I/O, teste do teto de capital corrigido pro valor novo (100%).
- **4 achados exigiam decisão do Lucas** (não corrigidos pelo workflow,
  só documentados) — todos decididos e fechados na sequência, na mesma
  sessão: (1) `SPOT_DUST_USDT=10.0` colide com equity pequeno — Lucas vai
  resolver **aumentando o capital**, sem mudança de código; (2)
  `kill_switch_state.json`/`cooldown_state.json` não eram isolados por
  AMBIENTE (testnet e mainnet liam/gravavam o mesmo arquivo) — **corrigido**
  (bug #39); (3) rearm de stop em `_execute_spot_exit` sem fallback de
  liquidação de emergência — **corrigido** (bug #40); (4)
  `_update_trailing_stop` reconciliava posição como fechada sem confirmar
  se o stop real ainda estava ativo — **corrigido com aprovação explícita
  do Lucas** (bug #41, mexe na função do incidente de compliance abaixo,
  só depois de confirmação direta dele).
- Suíte final: **257/246 smoke + 8/8 ciclo = 265/265**, confirmado por mim
  de forma reproduzível (achei e corrigi 2 bugs de TESTE que só apareciam
  rodando com `.env` em mainnet pela primeira vez — ver bugs #44/#45).

**Incidente de compliance em aberto, NÃO resolvido (decisão deliberada do
Lucas de não mexer no código/config por enquanto)**: desde as 13:59 UTC de
hoje, a Bybit começou a bloquear o REARME do trailing stop em spot
(cancelar+recriar ordem condicional `tpslOrder`) com `retCode 10024`/
`KYC_PROMPT_TOAST` — o mesmo código historicamente associado a bloqueio de
DERIVATIVOS pra conta BR, agora aparentemente também atingindo ordem
condicional em SPOT. `trailing: true` continua ligado em
`config/risk_config.yaml`; o Lucas decidiu explicitamente "não mexer no
código, só limpar a falha" quando perguntado se quer desligar. Os bugs
#40/#41 tornam a RECONCILIAÇÃO em torno desse bloqueio mais segura (nunca
mais fabrica um `trade_closed` falso, e tenta liquidar a mercado antes de
desistir de proteger) — mas não resolvem o bloqueio em si. Se isso
persistir, qualquer posição real com trailing ativo pode precisar de
acompanhamento manual quando o preço se mover a favor o suficiente pra
tentar mover o stop.

**Novo (25-26/07): cooldown por símbolo ENDURECIDO pra 3 níveis + reset manual —
já mesclado em `main`.** A pedido do Lucas ("ele tomou um stop e entrou de novo
comprado agora. Não seria interessante acalmar e não comprar, porque está
perdendo?"), o cooldown pós-stop (bug #30, 21/07) ficou mais agressivo:
`consecutive_stops_trigger` foi de 2 pra **1** (cada stop ISOLADO já pausa o
símbolo, não precisa mais de 2 seguidos) e ganhou um 3º nível de escalada —
1º stop do dia (por símbolo, UTC) → 30min, 2º → 60min, **3º em diante → 24h**
(`cooldown_minutes_max`, chave nova em `config/risk_config.yaml`). TP no meio
continua quebrando a sequência (mesma lógica de sempre, só que agora sem
efeito prático já que 1 stop isolado já dispara — mantido por precaução caso
o gatilho suba de novo no futuro). **Novo: reset manual do cooldown antes do
prazo natural** — `RiskManager.reset_cooldown(symbol)` (mesma filosofia do
`reset_kill_switch`: nunca automático) + dois MCP tools novos,
`trader_cooldown_status` (leitura — por símbolo, ativo/até quando/quantos
acionamentos hoje) e `trader_reset_cooldown(symbol, confirm=True)` (canal
`state/control.json` → `engine._apply_control_signal`, mesmo padrão
desacoplado do halt/reset do kill switch). Suíte cresceu pra **252/252**
(244 smoke + 8 ciclo — 18 checks novos de cooldown: 3 níveis, TP reseta
`consecutive_stops`, reset manual libera antes do prazo, reset sem cooldown
ativo é no-op seguro sem evento fantasma). **Confirmado ao vivo no mesmo dia**:
1º acionamento real (ETH, 25/07 23:21 UTC) já disparou com 1 stop isolado
(exatamente o pedido do Lucas); escalada 30→60min também confirmada ao vivo
(ETH, 26/07 00:58 e 08:01 UTC). **Pendência**: as duas ferramentas MCP novas
só valem depois de reiniciar o Claude Desktop (não recarrega `mcp_server.py`
sozinho — mesma regra de sempre) — Lucas já reiniciou e confirmou as duas
funcionando.

**Incidente do mesmo dia (26/07, ~19h UTC), JÁ RESOLVIDO: crash-loop do
supervisor + quase-duas-instâncias — causa raiz foi um processo de
diagnóstico meu, não um bug no código.** Durante uma investigação de
`cycle_error` recorrente (falha intermitente da testnet ao ler
`wallet-balance` — populacional, autolimitada, não é bug), subi um `main.py
--live` manual (fora do `supervisor.py`) pra diagnosticar. Duas tentativas de
parar ele de forma limpa (`CTRL_C_EVENT` via ctypes, a técnica de sempre)
FALHARAM sem eu perceber na hora — o processo ficou vivo, órfão, sem
supervisão. Enquanto isso, o Lucas (ou o próprio supervisor, não confirmado
qual) tentou subir um `supervisor.py --live` novo — e cada tentativa dele de
spawnar `main.py` colidia com o processo órfão que eu tinha deixado pra trás
(disputa pelos mesmos arquivos de estado em `state/*.json`, sincronizados via
OneDrive), morrendo quase instantaneamente (`exit_code=1`, <0,2s de vida) —
visto na trilha como 6 `engine_crash_restart` seguidos até
`engine_supervisor_giveup` (teto de 5 tentativas/30min esgotado). **Rodar
`main.py`/`supervisor.py` isolados, sem o processo órfão por perto,
funcionou perfeitamente em todos os testes** — confirma que não é bug de
código. Resolvido derrubando o processo órfão à força (`Stop-Process
-Force`, já que o `CTRL_C_EVENT` remoto não estava alcançando esse processo
específico — não fica claro por quê; pode ser por ele ter sido iniciado via
job em background do Bash/git-bash em vez de uma janela de console real
como o método normal usa) — depois disso, a tentativa seguinte do
`supervisor.py` subiu limpo na hora. **Lição pra sessões futuras**: se um
processo de diagnóstico `main.py --live` avulso for iniciado fora do
`supervisor.py` pra investigar algo, CONFIRMAR que ele realmente morreu
(checar processo, não só assumir que o `CTRL_C_EVENT` funcionou) antes de
seguir em frente — um órfão vivo pode causar exatamente este tipo de
crash-loop confuso em qualquer tentativa de restart subsequente, sua ou do
Lucas. Estado ao final: uma única instância rodando, via `supervisor.py`,
saudável.

**Novo (25/07): repositório GitHub PRIVADO dedicado criado — `wonderboat-ai/bybit-auto-trader`
— para viabilizar um 2º PC rodando o motor 24h.** A pedido do Lucas ("configurar
outro PC pra rodar 24h enquanto uso este pra fazer upgrades"), inicializado git
nesta pasta (`git init`, identidade configurada só LOCALMENTE neste repositório,
não na global) e feito o push inicial (commit `b1095d1`, 69 arquivos). Fora do
repositório de propósito: `.env` (segredos), `state/*.json` (kill switch/
cooldown/proteções — estado local, cada máquina cria o seu do zero), `logs/*.jsonl`
(trilha de auditoria), `data/`/`research/data*`/`research/results*`/`scratch`
(dados de mercado/pesquisa regeneráveis via script, não são código),
`Dossie Cripto/` (arquivo gerado), `.claude/`/`.mcp.json` (config específica
desta máquina — caminho absoluto do venv daqui), e a pasta `repo/` (um
repositório git ANINHADO não relacionado — é o `dashboard-cripto` clonado à
parte; teria virado gitlink/submódulo quebrado se não tivesse sido excluído
explicitamente no `.gitignore`). Antes do push, auditoria manual (grep por
padrões de chave/segredo — `_KEY=`/`_SECRET=` com valor, prefixos `sk-ant-`/
`ghp_`/`AKIA`, blocos `BEGIN PRIVATE KEY`) em todos os 69 arquivos rastreados
não achou nenhum segredo real — só um placeholder óbvio (`README.md`, texto
literal "seu_secret").

**Decisão do Lucas sobre a arquitetura dos dois PCs, revista no mesmo dia
depois de eu explicar o risco da 1ª versão**: a ideia inicial era o PC novo
("PC2") usar uma chave de API de testnet NOVA mas na MESMA conta que este PC
(PC1) usa — o que criaria risco real (os dois motores gerenciando a MESMA
posição/saldo, cada um com seu próprio kill switch/cooldown/proteções local,
inteiramente independente um do outro). O Lucas perguntou explicitamente "mas
se eu usar api de outra conta vai rodar?" e, confirmado que sim, decidiu por
uma **CONTA de testnet SEPARADA para o PC2** (cadastro novo, e-mail diferente
em testnet.bybit.com, chave de API própria) — não é só uma chave nova, é uma
conta nova mesmo. Isso isola completamente o saldo/posições dos dois PCs na
raiz do problema: não existe mais "a mesma posição sendo gerenciada duas
vezes", porque não é mais a mesma posição. **Com contas separadas, a regra
"nunca duas instâncias" do projeto (que sempre foi sobre estado/CONTA
compartilhado) deixa de restringir PC1×PC2 especificamente** — mas a prática
recomendada continua sendo PC2 = operação contínua 24h, PC1 = ambiente de
dev (pode rodar `--live` pontual pra teste sem risco pro PC2, mas evitar
deixar um loop esquecido rodando por muito tempo sem acompanhar, por ser
dinheiro de teste sendo movimentado sem supervisão). Pasta do PC2
deliberadamente FORA do OneDrive (decisão do Lucas) — clone local dedicado,
sem sincronização. Guia completo de setup do PC2 entregue ao Lucas em dois
formatos, ambos versionados no repositório: `PASSO-A-PASSO-PC2.md` (texto) e
`guia-pc2.html` (página visual, também publicada como Artifact) — cobrem
Python/Git/GitHub CLI, clonar o repo, criar a conta+chave nova na Bybit,
criar o `.env`, validar com `diag_saldo.py`/`--once` antes do `--live`,
deixar o PC sem suspensão, e como puxar atualizações futuras via `git pull`.

**Fluxo de atualização de código daqui pra frente**: dev/testes continuam
neste PC (PC1, pasta OneDrive) como sempre; quando uma mudança for testada e
aprovada, `git push` pro repositório (`origin/main`) a partir daqui. No PC2,
atualizar exige parar o motor de forma limpa (Ctrl+C, deixa o `engine_stop`
ser auditado) → `git pull` → religar (`python supervisor.py --live`) — nunca
`git pull` com o motor rodando (mesma razão de sempre: `engine.py`/
`risk_manager.py` só recarregam num processo novo).

**Fase 3 (LLMStrategy) endurecida, ainda DESLIGADA (22-23/07 ~00:31 UTC)**:
a pedido do Lucas ("explorar Fase 3" → "fazer tudo"), a camada de decisão
por LLM — implementada há tempos mas NUNCA testada nem revisada — passou
por revisão adversarial completa (6 lentes, 15 achados, os 15 confirmados)
antes de qualquer teste ao vivo. Achado CRÍTICO real: NaN em
`stop_price`/`entry_price` passava por TODAS as barreiras (LLMStrategy E
RiskManager compartilhavam o mesmo ponto cego — comparação Python com NaN
é sempre `False`) até chegar sem guarda nenhuma na criação da ordem;
achado ALTO: NaN em `conviction` virava `1.0` (confiança MÁXIMA) em vez de
`FLAT`. Ambos corrigidos com `math.isfinite()` nos dois pontos
independentes (defesa em profundidade real, não só declarada). Também
corrigido: `entry_price` do modelo agora validado contra o preço real
(>2% de divergência → `FLAT` — única fronteira de confiança GENUINAMENTE
NOVA que a Fase 3 introduz); prompt agora avisa que `context` é dado
externo, nunca instrução (mitigação de prompt injection); fallback de
modo de mercado desconhecido virou fail-CLOSED (spot) em vez de
fail-aberto (perp); nome de modelo atualizado
(`claude-sonnet-4-6`→`claude-sonnet-5`); + 5 achados de qualidade de
teste corrigidos. Suíte 246/246 confirmada com o motor parado. Continua
INERTE em produção (`decision.strategy: deterministic`) — ligar é decisão
futura do Lucas. Teste isolado com chamada REAL à API do Claude ficou
pendente (`ANTHROPIC_API_KEY` ausente no `.env` — decisão do Lucas:
deixar assim por ora).

**Dossiê diário virou 3x/dia (22/07 ~23:50 UTC)**: a pedido do Lucas,
tarefa nova `dossie-cripto-intraday` (07h/13h/19h horário local) substitui
a antiga "Dossie cripto diário" (1x/dia, ~7h — desativada pelo Lucas no
painel do Cowork). Achado colateral relevante: as duas tarefas viviam em
sistemas DIFERENTES sem visibilidade cruzada — ver "Dossiê diário" mais
abaixo pro detalhe completo (evitar reinvestigar isso de novo).

**Nova capacidade (22/07 ~23:22 UTC): decisão #G implementada —
`BybitDerivativesProvider` (funding rate/open interest/long-short ratio
direto da Bybit, decisão de 18/07).** A pedido do Lucas, construído e
revisado adversarialmente (11 achados, os 11 confirmados e corrigidos — o
mais grave: sem gate, fazia até 12 chamadas de rede reais por ciclo mesmo
com a estratégia determinística nunca lendo o resultado; corrigido com o
mesmo gate que já existia pro re-chamado da LLM). Genuinamente INERTE hoje
(zero chamada de rede) — só ativa quando `decision.strategy: llm` ligar no
YAML (Fase 3, decisão futura do Lucas). Suíte 207/207 confirmada com o
motor parado. Detalhe completo na seção "Próximos passos", item 4 (#G).

**Nova capacidade (22/07 ~21:58 UTC): restart automático do processo —
`supervisor.py` (novo, raiz do projeto).** A pedido do Lucas ("aplicar
restart automático"), fecha a metade pendente do item `[ALVO]` do charter
("processo supervisionado com restart automático + alerta ativo") — a
metade "alerta" já existia desde 21/07 (`trader-watchdog`, ver seção
própria), só o restart faltava. `python supervisor.py [--live]
[--interval N]` substitui `python main.py [--live]` como forma de rodar o
motor: spawna `main.py` como subprocesso e o religa automaticamente se ele
cair sozinho (crash — Task Manager, falha de energia/SO, exceção fatal fora
do try/except do próprio `run_once`/`run_forever`), mas NUNCA religa numa
parada deliberada (Ctrl+C no terminal chega nos dois processos ao mesmo
tempo, pois compartilham o console — o supervisor só espera `main.py`
terminar sozinho, que audita `engine_stop` por conta própria como sempre
fez, e encerra junto sem restart). Teto de 5 restarts por 30min (janela
desliza; reseta se o processo ficar de pé por ≥10min antes de cair de novo)
— ao exceder, desiste e audita `engine_supervisor_giveup` (crítico: motor
PARADO, ninguém religa sozinho) em vez de entrar num loop de restart
infinito; cada restart individual audita `engine_crash_restart`. Backoff
exponencial entre tentativas (10s, 20s, 40s... até 5min). Lógica pura de
janela/backoff isolada em `src/supervision/restart_policy.py`
(`RestartPolicy`/`backoff_seconds`, zero I/O — testável com timestamps
sintéticos), 9 checks novos na seção 26 de `test_smoke.py` + validação
adicional em scripts isolados fora da suíte (ver nota de suíte abaixo).
`trader-watchdog` (SKILL.md fora do repo) atualizado pra tratar
`engine_supervisor_giveup`/`engine_crash_restart` como eventos críticos —
sem isso o watchdog não saberia diferenciar "motor rodando bem" de "motor
caiu e o supervisor desistiu de religar" (o último `engine_start`/
`engine_stop` da trilha continua parecendo "rodando" nesse caso, porque não
há `engine_stop` num crash). **Nunca toca risco/execução/ordem** — só
spawna/observa o processo e audita o próprio ciclo de vida.
**Em uso desde 22/07 ~22:43 UTC**: a pedido do Lucas ("troca pra rodar via
supervisor.py da próxima vez"), o motor foi parado de novo (mesma técnica
limpa — `CTRL_C_EVENT` real via ctypes, `engine_stop`/`manual` auditado às
22:42:32 UTC) e religado via `python supervisor.py --live` em vez de
`python main.py --live` direto. Confirmado na prática: `supervisor.py`
spawnou `main.py --interval 60 --live` como filho (PIDs verificados via
`Get-CimInstance Win32_Process`), `engine_start` auditado normalmente às
22:42:59 UTC, primeiro ciclo (22:43:10) reconciliou as 2 posições sem erro.
Dali em diante, um Ctrl+C na janela do supervisor (ou outro
`CTRL_C_EVENT` no mesmo console — todo o grupo supervisor+main.py
compartilha um console só) para os dois de propósito, sem restart; se
`main.py` cair sozinho, o supervisor religa automaticamente.

**Suíte CONFIRMADA de ponta a ponta em seguida, a pedido do Lucas ("pare o
motor e roda a suíte completa pra confirmar")**: parei o motor de forma
LIMPA sem acesso físico ao terminal — enviei um `CTRL_C_EVENT` real pro
console do processo (`AttachConsole`+`GenerateConsoleCtrlEvent` via
ctypes, equivalente a apertar Ctrl+C na janela dele), então o próprio
`main.py` tratou como sempre trata: `engine_stop`/`reason="manual"`
auditado por ele mesmo às 22:13:59 UTC, nada forçado (`TerminateProcess`
teria deixado a trilha sem esse evento, indistinguível de crash — por isso
não usei `taskkill /F`). **174/174 em `test_smoke.py`** (165 pré-existentes
+ 9 novos da seção 26, zero regressão) **+ 8/8 em `test_ciclo.py` = 182/182
verde**. Um `PermissionError` transitório apareceu na 1ª tentativa
(`kill_switch_state.json.tmp`, lock do OneDrive reassentando logo após o
processo morrer — mesma classe de instabilidade de sempre, não bug de
código) — `.tmp` removido, suíte rodou limpa na 2ª tentativa. Motor religado
logo em seguida (`python main.py --live`, mesmo comando de antes, novo
processo detached) — `engine_start` 22:15:54 UTC, primeiro ciclo (22:16:09)
reconciliou as 2 posições abertas normalmente, sem erro.

**Fio de pesquisa donchian/4h ENCERRADO (22/07 ~20:20 UTC)**: painel
adversarial de 9 agentes (6 lentes + 3 juízes) pedido pelo Lucas votou
UNÂNIME não promover — os únicos resultados "positivos" eram sorte de um
único evento de calendário (crash de 10/10/2025 caindo na mesma janela
OOS dos 5 símbolos), não edge real. Detalhe completo em "Estado exato —
22/07 ~20:20 UTC" logo abaixo. De quebra, achou e corrigiu um bug real
(recorrente desde 16/07, nunca corrigido na fonte) em
`research/harness.py`/`harness_short.py`. Nenhuma mudança no motor ao
vivo — só pesquisa.

**Decisão nova (22/07/2026 ~20:13 UTC): trailing stop LIGADO em produção**
(`config/risk_config.yaml`, `decision.deterministic.trailing: true` —
chave nova, não existia antes; feature já implementada/testada em 21/07
mas nunca ativada). A pedido explícito do Lucas, depois de discutir o
achado mais forte da pesquisa 2b (`research/RELATORIO-2026-07-21-pesquisa-2b.md`):
a estratégia atual do robô (EMA20/50+RSI, stop/TP fixos) confirmou DE NOVO
ser a pior família testada, em 2 datasets independentes — não há
alternativa validada (donchian/ema_cross) pra promover ainda, então a
melhoria aplicável agora é de GESTÃO DE SAÍDA na mesma estratégia, não
troca de família. Motor reiniciado pra a mudança valer (YAML só é lido no
boot) — `engine_stop` manual 20:12:57 UTC → `engine_start` 20:13:11 UTC,
as 2 posições já abertas (BTC/USDT, ETH/USDT) reconciliaram normalmente
(mantêm o stop/TP FIXO com que foram abertas — trailing só vale pra
entradas novas a partir deste boot). **Deliberadamente NÃO fiz**: (a)
trocar de família de estratégia (donchian/4h) — a própria pesquisa
recomenda NÃO promover isso sem uma rodada de verificação adversarial
completa (como 16/07, 9 agentes), que não foi pedida; (b) mudar qualquer
parâmetro de `risk_config.yaml` além do trailing (risk_pct, tetos,
drawdown) — mudança de parâmetro de risco exige aprovação explícita de UM
valor específico, "melhorar a estratégia" sozinho não é isso; (c) ligar
`exit_on_signal` (feature irmã, também pronta) — não foi pedida
explicitamente, só mencionada como opção complementar. Suíte NÃO re-rodada
pra este fix (é só um toggle de config; o código de trailing já tem
cobertura de teste própria desde 21/07, seções 20-21 de `test_smoke.py`,
173/173 confirmados nesta mesma sessão antes do toggle).

**Estado: motor RODANDO ao vivo**, `engine_start` 22/07 20:13:11 UTC (o
boot mais recente — ver "Decisão nova" acima, restart deliberado pra
ligar o trailing). O boot ANTERIOR (01:11:32 UTC) durou o dia inteiro sem
cair, sobrevivendo inclusive a uma virada de sessão de madrugada (ver bug
#31/#32 pro histórico de liga/desliga daquela janela) — só foi derrubado
agora, de propósito, pra aplicar o YAML novo. **2 posições abertas**
(BTC/USDT, ETH/USDT), reconciliadas normalmente no restart, ambas com
stop/TP FIXO (abertas antes do trailing entrar em vigor) — nenhuma posição
nua, nenhum erro, kill switch livre o tempo todo.

**Confirmação importante desta janela: bug #30 (cooldown) disparou de
verdade em produção pela primeira vez** — 3 acionamentos reais na
madrugada de 22/07 (ETH 30min, BTC 30min, ETH 60min escalado no 2º
acionamento do dia), todos batendo exatamente com o desenho, incluindo o
TP quebrando a sequência de stops ao vivo. Relato completo na seção de
bugs, logo após o bug #30. **Bug #29 (reconfirmação de saldo) segue SEM
validação ao vivo** — nenhum cenário de saldo atrasado ocorreu, só
fechamentos normais.

**PnL realizado total (corrigido, bug #31): 30 trades fechados, +182,04
USDT, win rate 33,3%** — caiu de +233,95 depois da sequência de stops
desta madrugada (destaque: -32,52 USDT isolado no BTC/USDT, a maior perda
individual até agora). Equity atual ~10.051 USDT. **Suíte 173/173 verde**
(165+8), confirmada com o motor parado antes deste boot (ver bugs
#31/#32).

**O watchdog agendado provou seu valor no primeiro dia**: pegou um achado
real (ver bug #29 abaixo) que eu não tinha visto — `naked_position_close_failed`
disparando 3x numa rajada de reentrada rápida ETH/BTC. Investigado (workflow
com comparação testnet vs mainnet — ver "Estado exato — 21/07 ~21:25 UTC"
abaixo): o ETH real não se moveu, foi anomalia de dado da testnet, mas
expôs uma lacuna de arquitetura real (sem cooldown) — daí o bug #30.
Watchdog reconfigurado de hora em hora pra 30 em 30 minutos. Suíte 164/164
verde (156+8), rodada com o motor parado antes deste restart.

**Fix da persistência do kill switch (bug #28) CONFIRMADO ao vivo, ponta a
ponta, mais cedo hoje**: `state/kill_switch_state.json` existe e reflete a
realidade (`halted: false`); o MCP `trader_halt_status` parou de reportar o
trip de 20/07 como ativo.

**Achado operacional novo, importante pra qualquer sessão futura**: o
`mcp_server.py` TAMBÉM não recarrega código — mesma regra de sempre pro
`engine.py`/`risk_manager.py` (Python não recarrega módulo em processo já
rodando), só que ninguém tinha documentado isso pro lado do MCP até hoje.
O fix de `state_reader.py` só passou a valer de verdade depois que o Lucas
reiniciou o Claude Desktop (que mata e reabre o `mcp_server.py`) — reiniciar
só o motor não bastava. **Regra nova: qualquer mudança em
`src/supervision/state_reader.py` (ou outro módulo que o `mcp_server.py`
importa) exige reiniciar o Claude Desktop pra valer, não só o `main.py`** —
ver seção Operacional no fim do arquivo. Efeito colateral notado e já
resolvido: reconexões do Desktop ao longo do dia tinham deixado 3 processos
`mcp_server.py` órfãos rodando em paralelo (todos read-only, sem risco de
execução, mas bagunçado) — o restart do Desktop limpou todos, sobrou só 1.

**Nova capacidade de supervisão, já validada na prática**: tarefa agendada
`trader-watchdog` (ver seção própria abaixo) — roda de hora em hora, checa
kill switch/erros críticos via MCP + trilha, e só notifica (`PushNotification`,
desktop + celular se Remote Control conectado) se achar problema real; fica
em silêncio se o motor estiver parado de propósito ou rodando bem. Achou o
bug #29 na 3ª execução (19:06 UTC) — a notificação em si não chegou (a
ferramenta julgou o terminal "ativo" e suprimiu), mas o relatório ficou
registrado na sessão da tarefa e foi lido manualmente. Cobre PARCIALMENTE o
item `[ALVO]` do charter "processo supervisionado com restart automático +
alerta ativo" — a parte de ALERTA está coberta (com essa ressalva de
supressão a investigar); RESTART AUTOMÁTICO do processo (se `main.py` cair
sozinho, ninguém religa) ainda não existe — ver "Próximos passos".

**Item 3b dos Próximos
passos: PRIMEIRA RODADA FEITA em 21/07 ~16:00 UTC** (a pedido do Lucas,
versão ENXUTA — sem painel adversarial multi-agente, ele optou
explicitamente por isso e sem teto de token). Dataset novo baixado
(`research/data_2b/`, 2024-04→2026-07, ~2,25 anos, regime misto confirmado —
nada de 100% bear como o de 16/07) e walk-forward rodado só nas famílias
donchian/ema_cross (+ robot_baseline de controle) em 1h/4h. **Veredito: ainda
SEM edge validado** — donchian mediana -3,43% (3/10 séries positivas),
ema_cross -6,54% (1/10); robot_baseline confirma DE NOVO ser a pior opção,
e piorou bastante no dataset novo (-29,82% mediana vs -3,40% em 16/07) — a
hierarquia relativa (robô atual = pior) já apareceu 2x em datasets
independentes. Relatório completo: `research/RELATORIO-2026-07-21-pesquisa-2b.md`
— **se alguém for promover donchian/4h (o "menos pior") pra uso real, rodar
a verificação adversarial completa antes, mesmo padrão de 16/07; esta rodada
não teve isso de propósito.**
21/07 (cedo): implementadas as TRÊS capacidades novas de execução que essa
pesquisa exigia — saída por SINAL, trailing stop e paridade do backtester —
tudo DESLIGADO por default (ligar = decisão do Lucas via YAML, chaves novas
`decision.deterministic.exit_on_signal/trailing`). Revisão adversarial
rodada (parcial por limite de sessão — ver "Estado exato — 21/07"): 3
achados confirmados + 2 HIGH verificados inline, TODOS corrigidos.
Dias 19-20/07: 4 bugs reais de produção achados e corrigidos ao vivo (ver
seções respectivas).
Suíte de testes 164/164 verde (`python tests\test_smoke.py` [156] +
`test_ciclo.py` [8]) — cresceu de 93 (início de 19/07) pra 164 (+9 do fix de
persistência do kill switch, seção 22; +2 do fix de reconfirmação de saldo,
seção 17b; +12 do cooldown pós-stops-consecutivos, seção 23).
**Protocolo reforçado: NUNCA rodar a suíte com o motor vivo** — em 21/07 a
suíte rodou uma vez com o loop ativo por descuido (sem dano: só ruído de
`symbol_skipped` perdido na janela; verificado), mas o risco é real.

**21/07, 2ª rodada da sessão (madrugada de 22/07 em UTC) — resposta a
"qual o status/PnL/histórico?" virou sessão de 2 bugs reais de supervisão.**
Pedido simples do Lucas ("qual o status do trader? PnL? histórico?")
expôs que `trader_realized_pnl` (MCP) mentia PnL agregado (reportava 1
trade/-5,81 USDT quando o real era 20 trades/+233,95 USDT — bug #31, causa
raiz num corte por linha bruta antes de filtrar por tipo de evento).
Investigando a correção, achei uma segunda lacuna real (bug #32): o
backtester oficial grava — não só lê — em `kill_switch_state.json`/
`cooldown_state.json` reais, então um trip/cooldown SIMULADO num backtest
podia sobrescrever o estado do motor ao vivo silenciosamente. Os dois
corrigidos com o mesmo padrão de isolamento por env var que `AUDIT_PATH`
já usa (fix #14, 15/07). Suíte confirmada 173/173 verde (relato completo
nos bugs #31/#32 abaixo). **Dois achados colaterais da própria sessão de
verificação, ambos sem dano real, ambos documentados em detalhe nos bugs
#31/#32**: (a) um script de teste meu contaminou `logs/audit.jsonl` com 2
linhas de teste por esquecer de isolar `AUDIT_PATH` — autorizado pelo
Lucas, já limpo (2º `audit_maintenance` da história do projeto); (b) o
motor foi religado pelo Lucas no meio de uma rodada da suíte — sem perda
aparente, mas é exatamente o risco que o protocolo acima tenta evitar.
**Lição pra próxima sessão**: qualquer script AVULSO (fora da suíte) que
instancie `RiskManager` de verdade precisa isolar `AUDIT_PATH` JUNTO com
`KILL_SWITCH_STATE_PATH`/`COOLDOWN_STATE_PATH` — isolar só os arquivos de
estado não basta, o `RiskManager` também audita na trilha.

## Regras inegociáveis (resumo — o charter manda)

1. O LLM NUNCA cria/altera/cancela ordem, nem via tool-call, nem via MCP. Ele só
   produz `Signal{direção, convicção, stop, racional}`. Risco e execução são
   determinísticos em Python.
2. A camada de risco (`src/risk/risk_manager.py` + `config/risk_config.yaml`) tem
   veto absoluto. Limites NÃO são negociáveis em runtime e mudança de parâmetro de
   risco exige aprovação humana explícita — nunca mude o YAML por conta própria.
3. Fases sequenciais: só se avança quando a anterior fechou. **Atualizado
   27/07/2026**: a pendência regulatória de derivativos (perp) para conta BR
   segue de pé — perpétuos continuam bloqueados. Mas SPOT deixou de ser
   bloqueado: o Lucas decidiu explicitamente migrar da testnet pra mainnet
   SPOT em 27/07/2026 (ver "Novo (27/07)" no topo deste arquivo) — o motor
   já rodou (dry-run/`--once`) contra a conta real, com chave de API de
   mainnet válida. Fase 5 (mainnet) NÃO está mais bloqueada para spot;
   segue bloqueada para perp/derivativos.
4. Testnet por padrão continua sendo a regra de CÓDIGO (`ENVIRONMENT=testnet`
   é o default de `config/settings.py` se a variável não estiver setada) —
   mas o `.env` REAL desta máquina está deliberadamente em
   `ENVIRONMENT=mainnet` desde 27/07/2026, decisão explícita do Lucas. DRY_RUN
   por padrão (`--live` desativa). NUNCA preencher/trocar chaves de mainnet
   sem decisão do Lucas — a troca de 27/07 foi feita por mim SÓ depois dele
   pedir explicitamente ("pode trocar você mesmo") após ele mesmo ter
   preenchido as chaves.

## Estado exato — 22/07 ~20:20 UTC (verificação adversarial donchian/4h — fio ENCERRADO)

A pedido do Lucas ("sim, verifique"), rodado o painel adversarial que a
pesquisa 2b pedia antes de qualquer decisão de capital sobre donchian/4h
(o "menos pior" achado em 21/07). Workflow com 9 agentes: 6 lentes
independentes em paralelo (look-ahead/metodologia, concentração de
retorno, significância estatística, benchmark ajustado a risco, robustez
de parâmetro, integridade de dados), cada uma recomputando os números
direto de `research/results_2b/{full_grid,wf_results}.csv` e
`research/data_2b/` (nunca confiando no relatório em prosa) — depois 3
juízes independentes (conservador, cético-de-metodologia, pragmático de
produto), cada um vendo as 6 lentes e dando veredito próprio sem
conversar entre si.

**Veredito UNÂNIME dos 3 juízes: NÃO PROMOVER.** O achado mais decisivo
(lentes de concentração + integridade de dados, por caminhos
independentes): os únicos 2 resultados nominalmente positivos do
walk-forward (ETH +0,33%, BNB +0,62%, de 5 símbolos) dependem
INTEIRAMENTE de um único trade/fold cada — o fold que contém o crash de
liquidação em cascata de 10/10/2025, que caiu na MESMA janela OOS de 18
dias pros 5 símbolos simultaneamente (o walk-forward usa cortes de
calendário idênticos entre símbolos, não escalonados por símbolo). Sem
esse único fold, ETH cai pra -1,37% e BNB pra -1,36% — as 5 séries ficam
negativas, no mesmo patamar da estratégia atual do robô (~-3%). Reforçado
por: nenhuma das 12 combinações fixas de parâmetro donchian/4h fecha
positiva num split estático (o "menos pior" só existe via a re-seleção
adaptativa do walk-forward a cada 18 dias — viés de seleção); e nenhuma
das 5 séries passa de \|t\|=1 (estatisticamente indistinguível de ruído,
a barra de referência do projeto é 2). A única lente que não fechou
"sem edge" foi a de risco ajustado (drawdown 5-11x menor que buy&hold,
consistente nos 5 símbolos) — mas ela mesma se classificou como
"inconclusiva": pode ser só o efeito mecânico de ficar fora do mercado
70-80% do tempo (sem teste de placebo pra descartar isso), e XRP perdeu
um rali de +93% inteiro.

**Achado colateral, corrigido na mesma sessão**: a lente de significância
estatística achou um bug real em `research/harness.py`
(`RunResult.total_return_pct` dividia pelo `START_EQUITY` GLOBAL fixo em
vez do `start_equity` real daquela chamada — contamina o campo por-fold
`oos_ret_pct`/`pos_folds` sempre que o walk-forward carrega equity entre
folds, mas NÃO afeta o retorno total agregado por série, que é calculado
à parte em `sweep_2b.py` e bate certinho). **Este mesmo bug já tinha sido
achado uma vez, em 16/07** (`research/results/verificacao_agentes.json`,
achado "BUG DE REPORTE em sweep.py"), inclusive já documentado neste
CLAUDE.md como ressalva aceita ("pos_folds de wf_results.csv tem bug"),
mas nunca foi corrigido NA FONTE (`harness.py`) — só contornado
localmente em `sweep_short.py` (que calcula `fold_ret_pct` à parte,
correto, comentário próprio no topo do arquivo já citava esse fix).
Sem o fix na fonte, o bug reapareceu silenciosamente na pesquisa 2b.
Corrigido agora em `research/harness.py` (campo `start_equity` novo em
`RunResult`, propriedade `total_return_pct` usa ele em vez da constante
global) e replicado em `research/harness_short.py` (classe `RunResult`
duplicada, mesmo bug independente, mesmo fix). Verificado: reconstruindo
o retorno total a partir da composição dos retornos ISOLADOS por fold
(pós-fix) bate exato com o retorno agregado oficial (diferença
0,000000pp, BTC/USDT donchian/4h) — antes do fix isso não fechava.
`pos_folds` de BTC corrigido de 17/36 (bugado) pra 12/36 (real). CSVs de
resultado (`full_grid.csv`/`wf_results.csv` de 2b e da pesquisa original
de 16/07) NÃO foram regerados — o bug não muda o veredito agregado
("sem edge"), só a granularidade por-fold; regenerar é opcional, só vale
a pena se alguém for reabrir uma investigação nova em cima do
`fold_detail`.

**Não mudou nada no motor ao vivo nem em `config/risk_config.yaml`** —
isto é só pesquisa. O robô continua com a estratégia atual (EMA/RSI, já
confirmada a pior em 2 datasets) + trailing stop (ligado mais cedo hoje).

## Estado exato — 21/07 ~16:00 UTC (pesquisa 2b: donchian/ema_cross, dado novo, ainda sem edge)

A pedido do Lucas, item 3b dos Próximos passos executado: "pesquisa de
estratégia com dados novos (2+ anos, regime misto), famílias de tendência
(donchian, ema_cross) em 1h/4h, agora com saída por sinal/trailing
simuláveis". Antes de começar, o Lucas perguntou explicitamente se isso ia
consumir todos os tokens dele — resposta: a computação do walk-forward em si
é Python puro (quase zero token), o que escala é verificação
multi-agente. Ele escolheu **passo enxuto** (eu mesmo rodo e reviso, sem
fan-out de agentes) e **sem teto de token explícito** — registrado aqui
porque muda o padrão de rigor esperado desta rodada vs a de 16/07.

**O que foi feito:**
- `research/download_data_2b.py` (novo, separado de `download_data.py` que
  baixa só os 6 meses já queimados): 2024-04-22 → 2026-07-21 (~2,25 anos),
  1h + 4h, spot mainnet pública Bybit, BTC/ETH/SOL/XRP/BNB (MNT fora desta
  rodada — foco é família, não símbolo). 100% do alvo baixado, 0 falhas.
  Confirmado regime MISTO por blocos trimestrais (ex.: XRP teve um bloco de
  +475,6% e blocos de -20 a -32% no mesmo dataset) — bem diferente dos 6
  meses 100% bear de 16/07.
- `research/sweep_2b.py` (novo, separado de `sweep.py`): reusa
  `research/harness.py` (mesmo motor, mesmas regras anti-look-ahead,
  paridade já validada em 16/07), grade de 77 combinações (64 ema_cross —
  incl. variante TRAILING que não existia na grade de 16/07 — + 12 donchian
  + 1 robot_baseline de controle) × 5 símbolos × 2 timeframes (15m não
  retestado — já inviabilizado por fricção em 16/07). Walk-forward mesma
  metodologia (t-stat de seleção, IS 90d/OOS 18d, 40 folds por série — mais
  que os 5 de 16/07 por o dataset ser maior). Rodou em 54s (`AUDIT_PATH`
  isolado por precaução, mas o harness de pesquisa nunca tocou
  `logs/audit.jsonl` mesmo — motor real ficou 100% intacto, confirmado
  depois pela trilha sem gap).
- **Novo nesta rodada**: benchmark de buy-and-hold sobre a MESMA janela que
  o walk-forward testa, pra nunca confundir "perdeu menos" com "tem edge" —
  lição direta da pesquisa short de 16/07.

**Veredito (detalhe completo em `research/RELATORIO-2026-07-21-pesquisa-2b.md`):**
ainda SEM edge validado em nenhuma das duas famílias. donchian mediana
-3,43% (3/10 séries positivas, pior -14,94%, melhor +18,04%); ema_cross
mediana -6,54% (1/10, essencialmente flat na melhor). As 4 séries com WF
positivo não batem o buy&hold da própria janela em nenhum caso onde o
mercado subiu forte (XRP 1h: WF +18% vs buy&hold +95% na mesma janela —
capturou ~19% do rali). **robot_baseline (a estratégia atual do robô)
confirmou DE NOVO ser a pior opção — mediana -29,82%, 0/10 positivas, pior
-52,65% — e piorou bastante vs os -3,40%/0-18 de 16/07** (dataset novo tem
quedas mais extremas e o robô não tem saída por sinal pra escapar delas).
Essa hierarquia (robô atual = pior família, reproduzida em 2 datasets
independentes) é o achado mais sólido da rodada — mais sólido que qualquer
dos 4 resultados "positivos" de donchian/ema_cross, que são pequenos e não
foram adversarialmente verificados.

**Sanity check feito (não é o painel completo de 16/07)**: concentração de
retorno por fold checada nos 4 resultados WF positivos — nenhum tem >50% do
retorno somado num único fold (máx. 33%), picks variados entre folds (não
travado numa única combinação) — não tem a cara óbvia de "1 trade de sorte"
que a pesquisa de 16/07 tinha achado e refutado nos seus positivos. Mas isso
é um check solo, não uma verificação adversarial — não tratar como prova.

**Pendência explícita se alguém quiser promover algo**: donchian em 4h é o
"menos pior" (mediana -2,88% nesse recorte) — NÃO é recomendação de uso, é
só onde investigar primeiro. Rodar o painel adversarial completo (como
16/07, 9 agentes) ANTES de qualquer decisão de capital em cima disso.

## Estado exato — 21/07 ~15:25 UTC (saída por sinal + trailing + paridade do backtester)

A pedido do Lucas ("vamos fazer 1, 2 e 3 em sequência"), implementado o
pré-requisito de engenharia da pesquisa de estratégia (item 3a dos Próximos
passos). Tudo atrás de defaults DESLIGADOS — o live é idêntico ao validado
até o Lucas ligar no YAML (`decision.deterministic.exit_on_signal: true` e/ou
`decision.deterministic.trailing: true`, chaves NOVAS, lidas em
`engine._build_strategy`; ausentes = comportamento antigo).

**1) Saída por SINAL** (`src/strategy/deterministic.py`,
`src/engine.py:_check_signal_exit`): `should_exit(snap, position)` na
estratégia (long sai quando EMA descruza; short simétrico, perp-only);
`wants_exit_signals` evita o fetch de OHLCV quando desligado (custo zero por
ciclo). O engine consulta a estratégia do PERFIL que abriu a posição (campo
novo `profile` em `state/spot_protections.json` e no `order_executed`) e
fecha a mercado reusando a mecânica do TP (`_execute_spot_exit`,
generalização do caminho validado ao vivo — kind="take_profit" mantém os
nomes históricos de evento; kind="signal_exit" ganha espelhos:
`dry_run_signal_exit`, `signal_exit_failed`, `signal_exit_rearm_stop_failed`,
`signal_exit_executed`, `trade_closed` com `reason="signal_exit"`/
`exit_price_source="exit_order_fill"`). Saída NUNCA passa pelo veto de risco
(reduz risco — mesma filosofia do stop/kill switch, decisão #B). Prioridade
no ciclo: TP primeiro (preço já no alvo é estritamente melhor), sinal depois.

**2) Trailing stop** (`Signal.trailing`, `executor.py`,
`engine._update_trailing_stop`): com trailing, a estratégia emite
`take_profit=None` (o stop que sobe É a realização) e o executor grava
`trail_distance` (=|fill − stop re-ancorado|, a distância PURA de risco) e
`peak_price` (=fill) na proteção. A cada ciclo o engine sobe o pico e, quando
o stop trailed melhora além de `TRAIL_MIN_STEP_PCT` (0,1%, constante em
`src/strategy/signal.py` — compartilhada com o backtester por paridade),
cancela e re-arma o stop real (não há "modify" em spot). Salvaguardas:
(a) preço JÁ abaixo do nível trailed → NÃO tenta armar stop acima do
mercado (Bybit rejeitaria; viraria loop de cancel/rearm com janela sem stop
a cada ciclo) — sai a MERCADO via kind="trailing_exit" (`trade_closed`
`reason="trailing_stop"`, paridade com o replay); (b) antes de mover, lê o
gatilho REAL vigente na exchange (`fetch_open_stop_orders`, categoria
tpslOrder) — arquivo stale (persistência falhou/restart no meio) nunca
rebaixa um stop real mais alto, o registro é CURADO com o valor real;
(c) falha ao armar o stop novo → re-arma o ANTIGO → se falhar,
`trailing_rearm_stop_failed` (intervenção manual); (d) dry_run audita
`dry_run_trailing_stop_move` sem tocar exchange nem arquivo.

**3) Paridade do backtester** (`src/backtest/backtester.py`): simula os dois
mecanismos com as MESMAS convenções do live — saída por sinal decidida no
candle FECHADO i e preenchida no open de i+1 (com slippage/fee); trailing
checa o stop trailed ANTES de subir o pico com o high do candle (sem
look-ahead intra-candle); `TRAIL_MIN_STEP_PCT` idêntico; e (fix da revisão)
stop/TP re-ancorados no fill como o executor faz desde o fix #26 — R:R
efetivo dos trades do replay agora é EXATAMENTE o tp_rr do sinal.
`Trade` ganhou `trailing/trail_distance/peak_price` e `exit_reason`
`signal_exit`/`trailing_stop`.

**Revisão adversarial (21/07) — PARCIAL por limite de sessão, completada
inline.** 5 lentes rodaram completas (13 agentes, ~1,7M tokens); a fase de
verificação morreu no meio (28 verificadores caíram no limite de sessão do
plano — lição: painéis de verificação 2x por achado em workflow são caros;
verificar inline quando o limite estiver próximo). 3 achados confirmados
por 2 céticos cada ANTES do limite + 2 HIGH verificados inline por leitura
de código — TODOS corrigidos:
- (confirmado) backfill/persistência exigiam `take_profit` — posição
  trailing (tp=None por design) era irrecuperável se o arquivo se perdesse;
- (confirmado) persistência falha após move bem-sucedido → arquivo stale →
  próximo ciclo REBAIXAVA o stop real (fix: gatilho real da exchange, item
  2b acima);
- (confirmado) backtester sem a re-ancoragem do fix #26 (item 3 acima);
- (HIGH, verificado inline; pré-existente de 18/07) saldo-zero na saída com
  cancel_all falho fabricava `trade_closed` de "fechamento concorrente" pra
  posição AINDA VIVA e apagava a proteção — agora confirma via
  `fetch_order(stop_id)` que o stop NÃO está mais ativo antes de reconciliar
  (stop ativo → `*_exit_failed` + proteção mantida + retry);
- (HIGH, verificado inline) trailing com pico stale podia armar stop com
  gatilho ACIMA do preço (item 2a acima);
- (menores) audit de sucesso do trailing em try próprio (falha de trilha não
  dispara re-arm falso); persistência do re-arm parcial fora do try do stop
  (falha de I/O não vira alarme "sem proteção" falso); `clear_protection`
  pós-venda contido com `symbol_cycle_error` best-effort; rótulos de
  log/evento kind-aware; guard de `should_exit` no backtester.
Não corrigidos (documentados como aceitos): replay usa o high do candle
como pico vs. live amostrando 1x/~65s (aproximação otimista pequena, mesma
classe das aproximações da régua já documentadas na Fase 2); backtester
simula saída por sinal/trailing também em perp/short (pesquisa futura — o
LIVE só implementa em spot; `Signal.trailing` é ignorado em perp).

## Estado exato — 20/07 ~23:20 UTC (loop de reentrada + pesquisa de estratégia revisitada)

Continuação do monitoramento ao vivo (`Monitor` persistente na trilha,
armado em 19/07). Achado real novo, mais uma rodada de fixes já corrigidos
e testados. Também: o Lucas pediu uma análise honesta do PnL do dia e da
estratégia atual — resposta registrada abaixo porque muda o que "próxima
etapa" significa daqui pra frente.

**26. MÉDIO/ALTO — `executor.py`: stop/TP calculados no preço do SINAL
(candle fechado), não no preço real do fill — causava loop de reentrada
drenando taxa.** `market_data.build_snapshot` usa `last_price = close do
último candle FECHADO` (fix #10, 15/07) — correto pra evitar candle em
formação, mas isso significa que `signal.entry_price`/`stop_price`/
`take_profit` ficam CONGELADOS até o candle virar. Se o preço real se mover
bastante DENTRO do mesmo candle (visto ao vivo: ~565 USDT de diferença numa
janela de ~2 segundos, logo depois de um TP disparar — provável momentum
da própria venda), a ordem a mercado preenche num preço bem diferente do
que a estratégia usou pra calcular o alvo. Consequência real, 20/07
~18:12-18:16 UTC: uma posição BTC abriu com o TP calculado (64.609,60) já
ABAIXO do preço real de entrada (64.774,40) — ou seja, nasceu "no alvo".
No ciclo seguinte (`_check_spot_exits`), vendeu de novo no mesmo preço,
`pnl_usdt` audita 0,00 mas o custo REAL foi a taxa de ida+volta (~4 USDT,
não descontada nesse campo). Como o sinal EMA/RSI continuava válido, o
motor reabriu a MESMA posição instantaneamente — 3 ciclos seguidos
(abrir→fechar→abrir→fechar→abrir→fechar) só interrompidos por um kill
switch manual via MCP (`trader_request_halt`) enquanto o fix era
escrito/testado. Corrigido: `executor.py` agora mede `price_drift =
fill_price - signal.entry_price` e desloca `stop_price`/`take_profit` por
essa mesma distância antes de armar o stop e salvar a proteção — preserva a
distância de risco em USDT que o `RiskManager` usou pra dimensionar a
posição (o motivo do sizing), só re-centralizada no preço que realmente
aconteceu. Garante que o TP sempre fica do lado lucrativo da entrada real,
elimina o loop. **Achado colateral, não corrigido**: reiniciar o processo
zera o kill switch em memória SEM gerar `kill_switch_reset` na trilha nem
persistir em disco (`RiskManager._kill_switch` só existe em RAM) — depois
de um restart, `trader_halt_status` (MCP) continua reportando o último
`kill_switch_tripped` como se ainda valesse, mesmo o motor já estando livre
de novo. Ferramenta de status ficou desatualizada num caso real; não
corrigido ainda, só documentado aqui.

**Pesquisa de estratégia revisitada — resposta a "qual a melhor estratégia
pra construir com o que já temos?"** Reli `research/RELATORIO-2026-07-16.md`
pra responder com rigor em vez de opinião: nenhuma das 6 famílias testadas
(108 combinações, walk-forward, 9 agentes verificando) mostrou edge
negociável na janela de 6 meses testada (100% bear) — nem a estratégia
atual do robô, que é literalmente a PIOR das 6 (mediana WF -3,40%, 0/18
séries positivas). A "menos pior" (bollinger_mr, -0,02%) ainda é negativa.
Esse dataset está queimado pra seleção (~9 agentes já inspecionaram o OOS).
Caminho recomendado pelo próprio relatório, repassado ao Lucas: (1)
resolver primeiro a lacuna de executabilidade — o contrato
`Signal`/`RiskManager`/`Executor` atual só sabe fazer stop fixo + TP fixo
por software, famílias com saída por SINAL/trailing (as que teriam mais
chance de edge) não são nem operáveis hoje; (2) só depois, re-testar
famílias de tendência (donchian/ema_cross) em 1h/4h com dado NOVO (2+ anos,
regime misto) — o dataset atual não serve mais pra isso. 15m descartado de
vez (0/108 combinações positivas, fee come 60-95% da perda). Nada
implementado ainda — é a próxima etapa de verdade do projeto, ver
"Próximos passos" abaixo.

## Estado exato — 19/07 ~15:55 UTC (3 bugs reais achados monitorando ao vivo)

A pedido do Lucas: "monitore em tempo real o motor" — um `Monitor` persistente
foi armado na trilha (`logs/audit.jsonl`), filtrando só eventos que importam
(ordens, fechamentos, erros, kill switch). Isso pegou, em tempo real, o
primeiro teste ao vivo do take-profit por software (a posição BTC de 17/07
finalmente bateu o alvo) — e ele estava quebrado. Três bugs reais achados e
corrigidos nesta sessão, do mais grave pro mais leve:

**23. CRÍTICO — `bybit_client.cancel_all()` nunca cancelava o stop real em
spot; TP por software ficava preso num loop infinito.** A Bybit v5 usa o
campo `orderFilter` pra escolher a categoria no cancelamento em massa; sem
ele, o ccxt manda o default `"Order"` (ordens comuns). Mas o próprio ccxt
CRIA as ordens de stop/take-profit em spot com `orderFilter="tpslOrder"`
sempre que a chamada usa `stopLossPrice`/`takeProfitPrice` (nosso
`set_stop_loss`/`set_take_profit`) — categoria DIFERENTE da que o
cancelamento sem filtro atinge. `cancel_all()` "cancelava com sucesso" sem
cancelar nada; o saldo-base continuava preso no stop original,
`fetch_free_base` devolvia quase zero, e toda venda de TP falhava pra
sempre com `"amount of BTC/USDT must be greater than minimum amount
precision of 0.000001"` — inclusive o RE-ARMAMENTO de emergência (mesmo
cálculo, mesmo erro), deixando `take_profit_rearm_stop_failed` na trilha a
cada ciclo por ~20min ao vivo (posição BTC real de 17/07, confirmada na UI
da Bybit: o stop ORIGINAL continuava ativo o tempo todo — não era uma
posição nua, só o TP que nunca conseguia executar). Corrigido:
`cancel_all()` agora faz DUAS chamadas em spot — a default (ordens comuns)
e uma com `params={"orderFilter": "tpslOrder"}` (cancela o stop real).
Perp/swap não muda (só uma chamada, `tpslOrder` é conceito exclusivo de
spot). **Validado ao vivo no primeiro ciclo após o restart**: TP do BTC
executou de verdade (cancelou o stop, vendeu a mercado), auditado com
`trade_closed`/`reason="take_profit"`, entry 63.620,40 → exit 64.476,00,
**pnl_usdt = +56,51** — primeiro fechamento lucrativo automático de toda a
história do projeto. Confirmado 1:1 contra o histórico de ordens da própria
Bybit (print do Lucas): mesmo preço, mesmo tamanho (0,066047 BTC).

**24. MÉDIO — `executor.py`: `protect_size = min(size, free)` não cobria
fill FAVORÁVEL (preço melhor que o do sinal).** O clamp original (revisão de
15/07) existia pra nunca proteger MAIS do que a compra realmente creditou
(fee reduz o saldo recebido). Mas quando o preço cai entre o sinal e o fill
de uma compra por CUSTO em USDT, a MESMA notional credita MAIS base — visto
ao vivo no ETH de hoje (size teórico 1,07305, saldo livre real pós-compra
1,08310, `min()` escolheu o menor). Resultado: ~0,009-0,01 ETH (~17 USD)
comprados de verdade e nunca cobertos por nenhum stop. Corrigido: mede o
saldo base ANTES da compra (`free_before`) e DEPOIS (`free_after`), protege
a DIFERENÇA (`free_after - free_before`) em vez de `min(size, free_after)`
— cobre os dois sentidos (fill melhor OU pior que o teórico) e continua
imune a saldo alheio pré-existente na mesma moeda-base (a diferença cancela
qualquer dust que já estivesse lá, mesma proteção que o `min()` original
buscava). Fallback em cascata se `free_before` ou `free_after` falharem:
sem `free_after` → usa o size teórico puro (comportamento mais antigo); com
`free_after` mas sem `free_before` → cai no `min(size, free_after)` de
antes (conservador, nunca superestima). A posição ETH já aberta (size
1,07304 salvo) não foi corrigida pelo código — precisou de ação manual do
Lucas na exchange (ver abaixo).

**25. MÉDIO — `executor.py`: `entry_price` caía direto no preço do SINAL sem
tentar confirmar o fill real.** Quando `create_order` não devolve
`average`/`price` (ccxt, visto ao vivo 2x hoje — BTC e ETH), o código usava
`signal.entry_price` como aproximação permanente — pode divergir >1% do
fill real se o preço se mover entre o sinal e a execução (foi exatamente o
caso das duas entradas de hoje). Corrigido: antes desse fallback, tenta
confirmar via `fetch_order(entry_id, symbol)` — mesma técnica já usada em
`engine._resolve_entry_price`/`_handle_spot_position_closed` pra confirmar
fills de stop. Só cai no preço do sinal se essa reconsulta TAMBÉM falhar.

Suíte cresceu de 93 pra **102/102** (94 smoke + 8 ciclo) com 9 testes novos
cobrindo os 3 achados acima (spot cancela 2x no `cancel_all`; perp não
duplica; fill favorável protege o saldo real; dust alheio não é absorvido;
sem leitura pré-entrada cai no clamp conservador; `entry_price` confirma via
`fetch_order`; fallback pro preço do sinal quando a reconsulta também
falha).

**Correção manual das duas posições já abertas** (o fix #24/#25 só vale pra
entradas NOVAS, não corrige retroativamente o que já estava salvo):
`entry_price` de ambas atualizado em `state/spot_protections.json` via
`fetch_order` nos `entry_id` reais (só leitura, confirmado 1:1 contra os
prints da Bybit do Lucas) — ETH 1.871,97→1.854,56, BTC (posição nova aberta
hoje 15:16:55 UTC, depois que a antiga fechou pelo TP) 64.326,80→64.476,00.
O gap de proteção do ETH (achado #24) na posição JÁ aberta exigia cancelar
e re-armar o stop de verdade — ação exclusiva do Lucas (regra inegociável
#1: LLM nunca toca ordem). Ele cancelou o stop antigo e armou um novo
cobrindo o saldo real (1,08201 ETH, mesmo `stop_price` de antes); `size` e
`stop_id` em `state/spot_protections.json` atualizados pra bater com o
`stop_id` real da nova ordem (confirmado via `fetch_open_orders` — o ID que
a UI mostra, ex. `86145536`, é só a cauda do ID completo,
`2262743569486145536`).

**Efeito colateral observado, não bug**: com o BTC liberado pelo TP, o
motor aprovou uma entrada NOVA em BTC/USDT ~1min depois (cruzamento EMA/RSI
novo) — a posição BTC atual não é mais a de 17/07, é uma nova, menor
(capada pelo teto de 20%).

## Estado exato — 18/07 ~18:45 UTC (trade_closed também no fechamento por stop)

A pedido do Lucas: até hoje, `trade_closed` (com `pnl_usdt`) só saía quando a
posição fechava pelo TAKE-PROFIT por software. Se fechasse pelo STOP — o
caminho mais comum, é a proteção contra perda — a trilha ficava muda: nenhum
`trade_closed`, só um evento genérico de "proteção órfã". Descoberto
justamente enquanto o Lucas esperava a saída da posição BTC/USDT real
aberta em 17/07. Implementado, testado (93/93) e revisado adversarialmente
(17 achados, todos confirmados — ver abaixo) antes de reportar como pronto.

**Mecânica nova** (`src/engine.py`, `src/execution/protection_state.py`,
`src/execution/executor.py`, `src/exchange/bybit_client.py`):
- `bybit_client.fetch_order(order_id, symbol)`: consulta uma ordem específica
  (`params={"acknowledged": True}`, exigido pela Bybit v5 — validado com
  sonda somente-leitura contra a conta real antes de escrever o código).
- `protection_state`: `set_protection()`/`backfill_from_audit()` agora também
  guardam/leem `stop_id` (e `backfill_from_audit` também `entry_id`, usado só
  transitoriamente pra resolver `entry_price`).
- `engine._handle_spot_position_closed(symbol, protection)`: quando uma
  proteção salva não corresponde mais a posição aberta na exchange, tenta
  confirmar o fill REAL da ordem de stop via `fetch_order(stop_id)`.
  Confirmado (`status=="closed"` e `filled>0` **e** `average`/`price`
  truthy — um valor `0` não conta como confirmado) → audita `trade_closed`
  com `reason="stop_loss"`, preço e tamanho REAIS do fill. Sem confirmação
  → `reason="external_close_unconfirmed"`, `exit_price=stop_price` (o alvo,
  nunca o ticker atual). `pnl_usdt` fica `None` quando qualquer componente
  (entry_price, exit_price, size) é desconhecido — nunca inventa número.
- `engine._check_spot_exits()`: loop novo no topo trata todo símbolo com
  proteção no ARQUIVO sem posição correspondente (stop disparou ou
  fechamento manual) — sempre limpa a proteção no `finally`, mesmo se a
  apuração falhar. Loop de TP (já existia) agora PERSISTE no arquivo a
  proteção backfilled na primeira vez que vê a posição — resolve
  `entry_price` nulo (bug pré-fix #17) via `fetch_order(entry_id)` ANTES de
  persistir. Isto já rodou contra a posição BTC real: recuperou o
  `entry_price` verdadeiro (63.620,40 — bate com a compra confirmada pelo
  Lucas na UI) a partir do `entry_id` da trilha.
- `engine._execute_spot_take_profit()`: agora trata preenchimento PARCIAL da
  venda (usa `order.get("filled")`, nunca o tamanho pedido, pro pnl/size
  auditados) e RE-ARMA um stop pro restante se sobrar mais que poeira
  (`SPOT_DUST_USDT`) em vez de limpar a proteção como se tivesse fechado
  inteira. Os `audit()` finais (sucesso) ficam num try/except: falha de
  I/O não impede a limpeza/re-armamento da proteção logo depois (prioriza
  nunca deixar o PRÓXIMO ciclo reconciliar a posição como "fechamento
  externo" com o `stop_price` — um alvo de PERDA — pra um trade que na
  verdade foi lucrativo).

**Revisão adversarial (18/07, 5 lentes independentes + verificação cética
de cada achado) — 17 achados, os 17 confirmados.** Todos os de correção
real já corrigidos e cobertos por teste novo; dois (baixa severidade,
raros) documentados como risco aceito, não corrigidos:

- CRÍTICO — venda do TP tratada como sempre 100% preenchida (nunca conferia
  `filled`, nunca reconsultava saldo, limpava a proteção incondicional).
  Corrigido (ver "mecânica nova" acima).
- CRÍTICO (achado por 3 lentes independentes) — quando o stop disparava
  CONCORRENTE ao TP (saldo zera após `cancel_all`), o código só limpava a
  proteção sem auditar nada — esse fechamento real ficava mudo PRA SEMPRE.
  Corrigido: esse branch agora delega pra `_handle_spot_position_closed`.
- ALTO — `average`/`price` da ordem do stop podiam vir `0` (não `None`) e
  passavam pelo guard `is None` como "confirmado", virando
  `reason="stop_loss"` com pnl fabricado. Corrigido: guard truthy, mesmo
  padrão já usado em `_resolve_entry_price`.
- ALTO — pnl sempre usava o tamanho RASTREADO, nunca o `filled` real da
  ordem (inflava o pnl em preenchimento parcial do stop). Corrigido nos
  dois caminhos de fechamento.
- ALTO — se `clear_protection()`/`audit()` falhassem (I/O, lock do
  OneDrive) DEPOIS de uma venda de TP bem-sucedida, o ciclo seguinte
  reprocessava a mesma posição como "fechamento externo" usando o
  `stop_price` (alvo de PERDA) — um pnl CONTRADITÓRIO pra um trade
  lucrativo. Corrigido: audits do sucesso envoltos em try/except, proteção
  sempre limpa/re-armada depois independente do resultado do audit.
- MÉDIO — `protection_state.load()` só cobria `JSONDecodeError`/`OSError`;
  um `UnicodeDecodeError` (bytes inválidos) escapava e derrubava
  `run_once()` inteiro (crash real de `--once`). Corrigido: `except
  (OSError, ValueError)` cobre os dois.
- MÉDIO — limiar de poeira (`SPOT_DUST_USDT`) podia esconder fechamento
  parcial (saldo residual some de `_open_symbols`, tratado como fechamento
  total com pnl calculado sobre o tamanho CHEIO). Mitigado pelo fix de
  "usa o filled real" acima; resíduo abaixo da poeira ficando sem proteção
  continua sendo um risco aceito e documentado (ver abaixo).
- BAIXO — `pnl_usdt` não guardava `exit_price=0.0` (fallback de
  `stop_price` ausente) como desconhecido — mesma classe "0 tratado como
  confirmado" já corrigida 2x neste projeto. Corrigido: `exit_price` entra
  no guard também.
- BAIXO (cobertura de teste) — só o caminho de STOP tinha teste provando
  "sempre audita `trade_closed` mesmo com `entry_price` desconhecido"; o
  caminho de TP tinha o mesmo comportamento no código, mas nada provava.
  Teste novo adicionado.
- BAIXO — `_resolve_entry_price` tenta `fetch_order(entry_id)` só UMA vez;
  falha (não-transitória) trava `entry_price=0.0` PRA SEMPRE nessa posição
  (pnl sempre `None`). Já era documentado como tradeoff deliberado no
  próprio docstring — confirmado como intencional, não corrigido.
- **Risco aceito e documentado, NÃO corrigido** (custo de mitigar
  desproporcional ao cenário, mesmo espírito da janela-sem-stop já aceita
  em `_execute_spot_take_profit`): se a MESMA posição fechar e uma posição
  NOVA abrir no MESMO símbolo dentro da janela de ~65s entre polls
  (recompra manual, ou segunda instância do engine — proibida mas já
  documentada como risco real de confusão de processos no Windows), o
  loop de fechados não detecta e o loop de TP herda a proteção STALE da
  posição antiga — um TP antigo pode cancelar o stop REAL da posição nova.
  Comentado em código no ponto exato do risco.
- **Achado não-acionável agora, mas ficou registrado**: a posição BTC real
  motivadora desta sessão estava, no momento da revisão, rodando sob um
  processo com o código de ONTEM (ver PRÓXIMA AÇÃO no topo) — é esse
  achado que virou a urgência do restart.

Suíte de testes: **85/85 em test_smoke.py + 8/8 em test_ciclo.py = 93/93**
(cresceu de 69 pra 93 — 16 testes novos cobrindo os achados acima).
`tests/test_ciclo.py` também ganhou o mesmo backup/restore de
`state/spot_protections.json` que `test_smoke.py` já tinha (ficou mais
importante porque o arquivo agora é escrito com mais frequência —
persistência no primeiro avistamento de toda posição).

**Catálogo de eventos atualizado**: `trade_closed` agora sai em TRÊS
caminhos — TP (`reason="take_profit"`, `exit_price_source="tp_order_fill"`),
stop confirmado (`reason="stop_loss"`, `exit_price_source="stop_order_fill"`)
e fechamento sem confirmação (`reason="external_close_unconfirmed"`,
`exit_price_source="stop_price_target_approx"`). `pnl_usdt` pode ser `None`
em qualquer um dos três quando algum componente é desconhecido — não é bug,
é a trilha sendo honesta sobre o que não sabe. O evento
`take_profit_protection_orphaned` (17/07) foi SUBSTITUÍDO por `trade_closed`
com `reason="external_close_unconfirmed"` — não existe mais.

## Decisão #G (18/07/2026): fonte on-chain real-time

A pedido do Lucas: dado derivado da própria Bybit (funding rate, open
interest, long/short ratio), sem contratar API paga por ora — ver decisão
completa na seção "Próximos passos, na ordem", item 4.

## Estado exato — 17/07 ~17:00 UTC (Etapa B-spot fechada)

**Etapa B-spot do PASSO-A-PASSO validada de ponta a ponta, com confirmação
cruzada trilha ↔ exchange (não só a trilha interna):**

- **16:51:27 UTC** `signal_approved` BTC/USDT long, perfil daytrade,
  rationale "EMA_fast>EMA_slow e RSI=61.3<70", size 0,06609434, notional
  4.206,31 USDT, risk_usdt 24,97.
- **16:51:29 UTC** `order_executed` BTC/USDT buy — `entry_id
  2261326190147364864`, `stop_id 2261326196304603136`, stop_price 63.263,18,
  `tp_id: null` (esperado em spot, ver decisão #E ressalva b).
- **Confirmado pelo Lucas na UI da Bybit testnet** (screenshots desta sessão):
  - Ordem de compra a MERCADO, BTC/USDT, executada 2026-07-17 13:51:28 BRT
    (= 16:51:28 UTC — mesmo segundo do evento), 0,066114 BTC brutos, fee
    0,000066114 BTC → líquido 0,066047 BTC = bate exato com o
    `protect_size` da trilha. Valor 4.206,20 USDT ≈ notional aprovado.
    ID da transação 85386743.
  - Stop TP/SL visível em "Ordens em aberto", venda, gatilho ≤63.263,2, qtd
    0,066047 BTC, ID de ordem `04603136` (cauda do `stop_id` da trilha),
    status "Não disparadas".
  - **Ambos os IDs, valores e timestamps (com o offset UTC-3 correto) batem
    entre trilha e exchange** — não é mais reconciliação de saldo, é o motor
    abrindo e protegendo uma posição real por conta própria.
- Isso resolve a hipótese aberta em 16/07 (saldo de brinde virando
  pseudo-posição): o `signal_approved` explícito antes do `order_executed`
  mostra que essa entrada foi decisão do motor, não reconciliação de saldo
  pré-existente. `diag_saldo.py` não chegou a ser rodado — deixou de ser
  bloqueante.
- Logo em seguida, ETH/USDT foi vetado duas vezes (comportamento correto,
  não bug): perfil daytrade por "Spot: short não suportado" (regra do modo
  spot) e perfil swing por "Exposição nocional total excederia o limite"
  (o BTC sozinho já consumiu ~4.206 dos ~4.992 USDT de equity — risco
  bloqueando exposição agregada como desenhado).
- Status da conta no momento da checagem: equity 4.992,06 USDT, 1 posição
  aberta (BTC/USDT long), PnL não realizado 0, kill switch não disparado,
  0 trades fechados/PnL realizado ainda (posição segue aberta).
- **Ainda NÃO validado:** a ponta de SAÍDA (stop disparando de verdade ou
  saída por sinal) — só a entrada+proteção foram confirmadas ao vivo.

## Estado exato — 17/07 (parte 2): take-profit em spot + teto de capital

A pedido do Lucas, depois de ver que (a) a posição aberta hoje não tinha
nenhuma saída lucrativa automática (só stop) e (b) o trade de hoje consumiu
~84% do equity numa entrada só. Duas features novas, código escrito e
testado; **ainda NÃO deployadas** — precisam do loop reiniciado (ver PRÓXIMA
AÇÃO no topo).

**1) Teto de capital por trade individual — decisão do Lucas: 20% do
equity, CLAMPA (nunca veta).**
- `config/risk_config.yaml`: novo `per_trade.max_notional_pct_equity: 20.0`.
- `src/risk/risk_manager.py` (seção "6b" do `evaluate()`): se o notional
  calculado pelo sizing normal (risco_usdt / distância do stop) excede 20%
  do equity, o `position_size` é REDUZIDO pra caber no teto — nunca aumenta
  risco, só diminui; a entrada acontece, só menor. Auditado com
  `capped: true/false` no evento `signal_approved`.
- Causa raiz do problema original: o sizing por risco fixo não tinha teto
  próprio, só o agregado de portfólio (1x equity em spot); com stop
  apertado, um trade sozinho podia consumir quase tudo.

**2) Take-profit em spot — a Bybit NÃO tem OCO, então é "TP por software".**
- Problema: em spot, o stop já ocupa o saldo-base na colocação (ver bug
  documentado no executor desde 15/07); colocar uma segunda condicional (TP)
  seria sempre rejeitada por saldo insuficiente. Sem OCO na API da Bybit,
  não existe alternativa "só na exchange".
- Solução: `src/execution/protection_state.py` (NOVO) guarda o alvo de TP
  de cada símbolo em `state/spot_protections.json`, escrito pelo executor no
  momento da entrada (`executor.py`, dentro do bloco que já pulava o TP em
  spot). A cada ciclo, `engine.py:_check_spot_exits()` confere o preço atual
  contra o alvo salvo; se atingido, `_execute_spot_take_profit()` cancela o
  stop (libera o saldo) e vende a mercado, audita `take_profit_executed` +
  `trade_closed` (com `pnl_usdt`), e limpa o estado.
- **O stop nunca depende deste mecanismo** — continua sendo sempre uma
  ordem real na exchange, ativa mesmo com o engine parado. Só a saída
  LUCRATIVA depende do loop estar rodando (checagem a cada ~65s).
- Roda mesmo com kill switch ativo (`_check_spot_exits()` chamado ANTES do
  `if self.risk.halted: return` em `run_once()`) — kill switch bloqueia só
  entradas novas, igual à decisão #B de 16/07 sobre o stop.
- `protection_state.backfill_from_audit()`: se a posição foi aberta ANTES
  desta feature existir (caso da posição BTC de hoje) ou o arquivo de
  estado for perdido, reconstrói o alvo a partir do último `order_executed`
  da própria trilha — nunca inventa dado. A posição BTC aberta hoje às
  16:51 UTC já tem TP em 64.396,64 registrado na trilha, então o backfill
  cobre ela automaticamente assim que o loop reiniciar.
- Tradeoff aceito e documentado: janela breve sem stop entre cancelar a
  condicional e vender (sem alternativa na API atual da Bybit spot). Se a
  VENDA falhar depois do cancelamento, o engine tenta RE-ARMAR o stop
  original na hora (mesma regra "nunca posição nua" do resto do executor) —
  só fica sem proteção nenhuma se ATÉ o re-armamento falhar
  (`take_profit_rearm_stop_failed`, intervenção manual imediata).

**Revisão adversarial de 17/07 (18 agentes, 15 achados verificados) — achou
um bug CRÍTICO real antes de qualquer coisa ir pra produção.** Rodada
completa DEPOIS do código acima estar "pronto", ANTES de reportar como
concluído. Achados confirmados e corrigidos, do mais grave pro mais leve:

- **CRÍTICO — bypass de DRY_RUN no TP por software.** `_check_spot_exits`/
  `_execute_spot_take_profit` chamavam `self.client` (a exchange) DIRETO,
  sem nunca checar `dry_run` — só o `Executor` checava, e esse caminho não
  passa pelo `Executor`. Consequência real: `python main.py` **sem**
  `--live` (o modo seguro padrão, só pra observar) ainda cancelava o stop
  real e vendia a mercado assim que o preço batesse o alvo salvo. Corrigido:
  `Engine` agora guarda `self.dry_run` e `_execute_spot_take_profit` retorna
  cedo (audita `dry_run_take_profit`) sem tocar a exchange quando `dry_run`.
- **HIGH — `fetch_spot_holdings` sumia com posição real na falha do ticker.**
  Um blip de rede ao buscar o preço fazia o símbolo inteiro desaparecer de
  `_open_symbols`, mesmo com saldo aberto de verdade — abria brecha pra
  entrada DUPLICADA no mesmo símbolo (nenhum outro veto no `risk_manager`
  pega isso) e apagava a proteção de TP de uma posição ainda aberta.
  Corrigido: nunca descarta por falha de preço — mantém o símbolo com
  `notional=0.0` nesse caso (só filtra poeira quando o preço vem certo).
- **HIGH — sem isolamento de erro por símbolo em `_check_spot_exits`.** Uma
  falha de I/O depois de uma venda BEM-SUCEDIDA (gravando a trilha ou
  limpando o estado — risco real dado que a pasta sincroniza via OneDrive)
  derrubava o ciclo inteiro e crashava `--once` sem tratamento nenhum —
  exatamente o bug #1 de 15/07, reintroduzido neste caminho novo. Corrigido
  com try/except por símbolo, auditando `symbol_cycle_error`.
- **HIGH — preço NaN do ticker furava o guard do TP.** `preço < alvo` é
  sempre `False` para NaN em Python, então um preço corrompido passava
  direto e disparava venda real com dado inválido. Corrigido com
  `math.isfinite()`.
- **MEDIUM — TP vendia o saldo LIVRE inteiro, não só a posição do bot.**
  Sem clamp (diferente da entrada, que sempre usa `min(size, free)`) —
  saldo alheio da mesma moeda (ex.: o brinde de testnet documentado no topo
  deste arquivo) seria vendido junto, corrompendo o `pnl_usdt` auditado.
  Corrigido: `protection_state` agora guarda o `size` real protegido na
  entrada; a venda (e o re-armamento do stop em caso de falha) clampam a
  `min(tamanho_rastreado, saldo_livre)`.
- **MEDIUM — teto de capital com `0` explícito virava "sem teto".**
  `if max_notional_pct:` trata `0.0` como falsy, igual a "chave ausente" —
  o oposto do que configurar um teto zero deveria significar. Corrigido
  para `is not None`. Não afeta o valor atual (20.0), mas era uma armadilha
  latente. Ver #1 na tabela de decisões abaixo.
- **MEDIUM — escrita não-atômica + corrupção silenciosa em
  `protection_state.py`.** `_save()` agora escreve em `.tmp` e faz
  `replace()` atômico; `load()` loga um aviso quando encontra JSON
  corrompido em vez de engolir em silêncio (o stop nunca depende deste
  arquivo, então o pior efeito sempre foi só perder a oportunidade de TP —
  agora pelo menos fica visível).
- **LOW — `protection_state.py` ignorava o override de `AUDIT_PATH`** que o
  resto do projeto usa pra não contaminar a trilha live em backtests (fix
  #14 de 15/07). Corrigido: `backfill_from_audit` agora usa a mesma função
  de `src/logger.py`.

Todos os 8 confirmados por verificação adversarial independente (não só
pelo revisor que achou).

**Segunda rodada de revisão (11 agentes), focada só nas correções acima —
os 8 fixes da 1ª rodada foram todos CONFIRMADOS corretos, mas apareceram
mais 4 problemas reais nas correções em si (nenhum novo problema de negócio,
tudo em código escrito nesta mesma sessão), todos já corrigidos:**

- **HIGH — o loop de limpeza de proteção órfã (código NOVO da 1ª rodada,
  linhas ~161-164) ficou de FORA do try/except por símbolo** que a própria
  1ª rodada tinha acabado de adicionar ao loop vizinho. A escrita atômica
  nova de `protection_state._save()` podia falhar (lock do OneDrive) e
  derrubar o ciclo inteiro / crashar `--once` — exatamente o que o fix
  vizinho tinha acabado de resolver, só que não pra este loop. Corrigido com
  o mesmo padrão try/except.
- **MEDIUM — `if tracked else free` (clamp de venda) reintroduziu o mesmo
  bug de "0 tratado como ausente"** que o fix do teto de capital (item
  anterior) tinha acabado de eliminar em outro arquivo. `size=0.0`
  legitimamente rastreado cairia no fallback "sem teto" (venderia o saldo
  livre inteiro). Corrigido para `is not None` nos dois pontos (venda e
  re-armamento do stop). Latente hoje (o executor nunca grava size=0), mas
  inconsistente e corrigido por precaução.
- **MEDIUM — o clamp do teto de capital podia aprovar um trade de tamanho
  ZERO** em vez de vetar (ex.: `max_notional_pct_equity: 0` configurado).
  `RiskDecision(approved=True, position_size=0.0)` chegava ao executor, que
  não tem guard de `size==0` — um "veto disfarçado de aprovação". Corrigido:
  `risk_manager.evaluate()` agora veta explicitamente
  ("Teto de capital por trade zerou o tamanho — sem entrada") quando o
  clamp zera o tamanho. Não afeta o valor atual do YAML (20.0).
- **LOW — `fetch_spot_holdings` com notional degradado (fix HIGH da 1ª
  rodada) não deixava rastro na trilha**, só um `log.warning`. Isso
  subestima silenciosamente a exposição agregada que o risco usa pro veto
  absoluto naquele ciclo. Corrigido: audita `spot_holding_notional_degraded`.

Mais 3 achados de COBERTURA DE TESTE (não bugs de produção, mas testes que
não provavam de verdade o que diziam provar) — todos corrigidos: (a) nenhum
teste exercitava o isolamento de erro por símbolo com uma falha DEPOIS de
uma venda bem-sucedida (o cenário real do fix) nem com 2+ símbolos — teste
novo adicionado simulando falha de `clear_protection` só num símbolo,
provando que o outro continua sendo processado; (b) o teste de backfill
usava `saldo_livre == tamanho_rastreado`, incapaz de distinguir um clamp
correto de um bug — corrigido pra usar valores diferentes (1.5 vs 1.0); (c)
os testes da seção 12 dependiam do YAML real estar em `spot` sem checar
isso explicitamente — adicionada asserção de pré-requisito no início da
seção. Suíte final: **61/61 em test_smoke.py + 8/8 em test_ciclo.py = 69/69.**

Duas rodadas de revisão adversarial (29 agentes no total) e nenhum achado
novo na 2ª rodada além dos 7 listados acima — considero o código fechado
pra este escopo. Qualquer revisão futura que mexer nestes arquivos deveria
rodar pelo menos mais uma rodada antes de confiar no `--live`.

**Bug preexistente encontrado e corrigido nesta sessão** (não causado por
mim, mas bloqueava testar as duas features acima): a suíte de testes
(`tests/test_smoke.py`, `tests/test_ciclo.py`) estava QUEBRADA desde a
virada pra spot — os fakes de exchange usados nos testes de `Engine`
completo não implementavam `fetch_spot_holdings`, e como `market.type` real
já é `"spot"`, `_portfolio_state()` sempre lançava exceção. Ou seja: desde
16/07, ninguém tinha uma suíte de testes funcional pra validar mudanças em
`engine.py`/`risk_manager.py`. Corrigido adicionando o método aos fakes.
Suíte agora: **56/56 em test_smoke.py + 8/8 em test_ciclo.py = 64/64**
(cresceu de 54 pra 64 com os testes de regressão dos 8 achados acima).

## Estado exato — 16/07 ~20:35 UTC (sessão de organização do projeto)

**Aviso de frescor:** `src/engine.py` e `src/risk/risk_manager.py` foram editados
e recompilados por volta de 20:39 UTC de hoje — DEPOIS do corte de leitura da
trilha abaixo. O código pode já ter mudado desde este parágrafo. Não trate isto
como verdade permanente; é uma foto. Releia `logs/audit.jsonl` antes de agir.

- **O motor rodou AO VIVO hoje, em loop contínuo, não só `--once` como o guia
  previa.** Quatro sessões com `dry_run: False` em testnet: 15:36–15:51,
  15:51–16:23, 16:23–16:30, e 17:05 até pelo menos 20:35 (sem `engine_stop`
  registrado até o corte de leitura — ~3h30 contínuas).
- **Spot confirmado ativo:** toda tentativa de short hoje é vetada com
  "Spot: short não suportado — sem entrada" (`market.type: "spot"` no YAML,
  decisão #E). Etapa B-spot do PASSO-A-PASSO está em andamento.
- **Zero `signal_approved` hoje.** Todo o volume de eventos do dia é
  `signal_vetoed` / "Sinal FLAT — sem entrada" (EMA/RSI não cruzou) — o sistema
  funcionando como desenhado, não é bug.
- **BTC/USDT travado por posição já aberta desde 19:29 UTC**, sem nenhum
  `signal_approved` hoje que explique — ou seja, o motor está reconciliando uma
  posição que já existia na exchange, não uma entrada que ele mesmo abriu.
  Combina exatamente com o pré-requisito B1 do PASSO-A-PASSO ("a testnet dá
  BTC/ETH de brinde — saldo >10 USDT vira pseudo-posição e o símbolo inteiro é
  PULADO"). Ainda NÃO confirmado com `diag_saldo.py` — é hipótese, não fato.
- **Nenhum `order_executed` na trilha hoje.** Consequência prática: mesmo com
  o motor rodando ao vivo por horas, o objetivo real da Etapa B-spot (compra +
  stop reais visíveis na auditoria) continua NÃO validado — ou o sinal ficou
  FLAT, ou BTC ficou preso na pseudo-posição.
- **1 `cycle_error` isolado:** 19:39:43 UTC, Bybit devolveu 503 (Service
  Unavailable) numa consulta de saldo. Ciclo seguinte normalizou sozinho. Sem
  kill switch, sem posição nua.
- **Kill switch:** não disparou hoje nem no soak de 15/07.
- **Limpeza do contexto do projeto (Claude Projects) feita nesta sessão:**
  removidos 7 docs `__init__.py` vazios/duplicados e `COMISSIONAMENTO.md`
  (órfão — não existe mais localmente, superseded por este guia +
  PASSO-A-PASSO.md). `risk_config.yaml` e `README.md` re-sincronizados com o
  conteúdo local atual (o anexado estava de antes do pivô pra spot). Faltam
  anexar `CLAUDE.md` e `PASSO-A-PASSO.md` — fazer isso na mesma sessão.
  Descrição e instruções do projeto (campos do Claude Projects) NÃO são
  editáveis por ferramenta — precisam ser coladas manualmente por você nas
  configurações do projeto; rascunho entregue no chat/arquivo separado.

## Estado exato em 2026-07-15 ~23:00 UTC (última sessão do dia anterior)

- Projeto transferido do Google Drive para esta pasta hoje; venv recriado; roda.
- **Etapa B (`--once --live`) BLOQUEADA POR COMPLIANCE DA BYBIT — não é bug.**
  Histórico das 2 tentativas de 15/07 (zero posição aberta em ambas; proteções
  funcionaram — erros isolados por símbolo, ciclo seguiu):
  1ª (14:58 UTC): retCode 10005 — chave de testnet sem permissão de trade.
  RESOLVIDO pelo Lucas na UI da testnet (Read-Write + trade); o warning de
  `set_leverage` também sumiu.
  2ª (15:08 UTC): retCode 10024 "Compliance rules triggered" +
  `KYC_PROMPT_TOAST` no `/v5/order/create` — a Bybit bloqueia DERIVATIVOS para
  contas de residentes no Brasil, e a testnet aplica o mesmo gating. Contexto
  (notícias 05/2026): migração compulsória para a entidade Bybit Brasil —
  derivativos/margem/empréstimos descontinuados para brasileiros; ~20/07/2026
  modo close-only; 21/09/2026 liquidação forçada de posições; 24/09/2026
  migração. Ou seja: perpétuos na Bybit ficam inviáveis para residente BR
  TAMBÉM em mainnet — a pendência regulatória da Fase 5 virou bloqueio de
  produto. O fix #11 foi visto funcionando ao vivo nessa tentativa (após a
  falha do 1º perfil, o 2º foi PULADO em vez de aprovar direção oposta).
  NUNCA sugerir/aceitar contorno de bloqueio regional (VPN, KYC de outro país).
- **Correção do candle em formação VALIDADA em produção** (`df.iloc[:-1]` em
  `src/data/market_data.py`). Soak de 14:01:49 UTC, auditado às ~14:50 por
  análise multi-agente + painel adversarial (3/3 sustentaram): 8/8 janelas
  símbolo×candle 15m com exatamente 1 stop distinto (BTC 65351.34 → 65360.93 →
  65173.79 → 65530.90), mudança sempre no 1º ciclo pós-virada (+20,8s a +46,3s),
  zero mudanças intra-candle, zero inversões de direção intra-candle, zero
  erros/kill switch, cadência 64,9–68,8s sem buracos, equity implícito estável
  ~4.995 USDT. Contraste (mesmo mercado, código velho, sessão 13:29): 14 stops
  distintos em 14 ciclos do MESMO candle, com buy+sell intra-candle.
- Ressalvas do soak (nenhuma bloqueia a Fase 1):
  a) kline do ETH na testnet congelou/foi revisado num spike (13:45–14:15) e o
     stop ETH atravessou a virada 14:15 sem mudar — qualidade de dado da
     TESTNET, não bug do bot (BTC atualizou nos mesmos ciclos; não recorreu
     nas viradas 14:30/14:45);
  b) ETH short saiu com stop a 7,8% do entry (risco USDT correto = 0,5%; efeito
     é só nocional pequeno) — conferir se a distância máxima de stop pretendida
     no YAML contempla isso (decisão do Lucas, item 4 dos próximos passos);
  c) ~~`signal_vetoed` não loga o campo `profile`~~ — **RESOLVIDO em algum
     momento entre 15/07 e 17/07** (não documentado na hora): o `_veto()` do
     `risk_manager.py` já grava `profile=profile` há pelo menos um dia; a
     trilha real de 17/07 confirma (`"event": "signal_vetoed", "profile":
     "daytrade", ...`). Ressalva mantida aqui só como histórico.
- Loop do soak parado limpo às 14:57:22 UTC (`engine_stop` manual).
- **Fase 2 EXECUTADA em 15/07 (~20:15 UTC), dados públicos da MAINNET.**
  Veredito out-of-sample: SEM EDGE em TODOS os cenários — o esperado; a régua
  foi validada (e consertada — ver seção Fase 2 abaixo e fixes #12–#15).
  BTC 15m WF (16 folds): OOS -30,9%, PF 0,42, 167 trades, degradação +1,12;
  ETH 15m WF: OOS -24,1%, PF 0,54, 158 trades (fold 14 pulado honesto);
  BTC 4h backtest deu "EDGE FRACO" (PF 1,03) mas o WF 4h derrubou (OOS -2,0%,
  PF 0,87, degradação +1,64) — o processo pegou o overfit, como devia.
  Backtests 15m saem "AMOSTRA PEQUENA" com causa visível: kill switch simulado
  em 01/07 13:30 UTC censura o resto da janela (comportamento correto do risco).
- **Avast HTTPS scanning: RESOLVIDO em 15/07 (~21:15 UTC)** com autorização do
  Lucas: `pip-system-certs 5.3` instalado no venv — o Python passa a confiar na
  loja de certificados do Windows (onde o Avast injeta a raiz dele; as CAs
  públicas continuam lá, então remover o Avast não quebra nada). Verificado sem
  env var nenhuma: requests 200, ccxt mainnet e TESTNET ok, httpx/Anthropic ok;
  smoke 17/17 + ciclo 8/8 depois do hook. Contexto: às ~20:00 UTC o Avast ligou
  varredura HTTPS (MITM com certificado próprio) e TODO Python quebrava com
  CERTIFICATE_VERIFY_FAILED — ccxt usa trust_env=False e nem REQUESTS_CA_BUNDLE
  resolvia. Se o venv for RECRIADO um dia, reinstalar pip-system-certs.
- LLMStrategy: implementada, desligada (`decision.strategy: deterministic`).
- MCP (`mcp_server.py`): registrado via `.mcp.json` na raiz do projeto e
  validado em 16/07 (ver "Etapa D" no histórico de decisões).

## Bugs corrigidos em 15/07 (não reintroduzir)

1. `engine.run_once`: erro em um símbolo/perfil não derruba mais o ciclo
   (try/except por iteração + `symbol_cycle_error` na auditoria).
2. `engine._portfolio_state`: marco do drawdown DIÁRIO reseta na virada do dia UTC
   (antes ficava preso no equity do boot). Kill switch continua com reset manual.
3. `bybit_client.fetch_balance_usdt`: equity = totalEquity → total → free (antes
   usava `free`; margem travada virava drawdown fantasma).
4. `executor`: stop falhou após entrada → fecha posição na hora (reduceOnly) +
   `naked_position_close` na auditoria + re-raise. Nunca posição nua.
5. `bybit_client.create_order`: clientOrderId com sufixo uuid (colisão no mesmo ms).
6. `risk_manager` + YAML: `max_abs_funding_rate_testnet: 0.01` vale SÓ em testnet
   (funding da testnet vive no clamp ±0.005; mainnet segue 0.003).
7. Exclusividade por símbolo por ciclo (`busy` set + `symbol_skipped`): elimina
   LONG+SHORT simultâneos do mesmo ativo (one-way mode).
8. Limites agregados valem INTRA-ciclo: cada aprovação soma posição/nocional/risco
   ao `state` antes da próxima avaliação.
9. `backtester`: day_start avança por dia UTC (ts//86_400_000) + ponto final da
   curva de equity registrado.
10. `market_data.build_snapshot`: descarta candle em formação (ver Estado acima).
11. `engine.run_once`: exclusividade por símbolo agora é FAIL-CLOSED — o símbolo
    entra no `busy` na APROVAÇÃO, antes da execução. Antes, execução falhada
    deixava o perfil seguinte aprovar a direção OPOSTA no mesmo ciclo (visto em
    15/07 14:58 na testnet: 10005 → ETH aprovado long E short no mesmo run).
    Estado agregado (posições/nocional) segue condicionado ao sucesso, de
    propósito. Regressão coberta: `test_ciclo.py` bloco D (8/8 + smoke 17/17).
12. `backtester._close_at`: fee de ENTRADA agora entra no `pnl_usdt` do trade
    (era debitada só do equity) — expectancy/profit factor/win rate saíam
    inflados ~1 fee por trade, exatamente as métricas do veredito "SEM EDGE" e
    da função-objetivo do walk-forward. Identidade sum(pnl)==Δequity fecha
    (verificado a 1e-13). Achado da auditoria multi-agente de 15/07.
13. `data_loader.fetch_history`: (a) cache agora CHECA a contagem — re-baixa se
    menor que o pedido, recorta os últimos N se maior (antes o walk-forward do
    guia rodava silencioso com metade dos dados: 6 folds em vez de 16);
    (b) descarta o candle EM FORMAÇÃO antes de salvar o CSV (espelha o live —
    antes congelava candle parcial no cache para sempre); (c) paginação mira
    candles+1 por causa do descarte.
14. `run_backtest.py`/`run_walkforward.py`: `AUDIT_PATH=logs/audit-backtest.jsonl`
    ANTES dos imports (o RiskManager audita toda decisão; uma rodada de
    walk-forward despejava ~40k eventos SIMULADOS na trilha do LIVE) +
    `stdout` UTF-8 (console cp1252 quebrava o relatório depois do cálculo).
    `src/logger.py` ganhou o override por env var.
15. `BacktestResult.kill_switch_ts` + linha "⚠ Kill switch" no relatório: o
    trip censurava o resto da janela sem causa visível ("AMOSTRA PEQUENA"
    misteriosa — no BTC 15m era um trip em 01/07 13:30 UTC censurando 2 semanas).

## Bugs corrigidos em 17/07 (não reintroduzir)

16. Suíte de testes quebrada desde a virada pra spot (16/07): `FakeSaudavel`/
    `FakeEthQuebrado` em `test_smoke.py`/`test_ciclo.py` não implementavam
    `fetch_spot_holdings`, e como `market.type` real é `"spot"`,
    `Engine._portfolio_state()` lançava exceção em qualquer teste que
    instanciasse `Engine()` completo. Corrigido adicionando o método (devolve
    `[]`) aos fakes. Ver "Estado exato — 17/07 (parte 2)".
17. `executor.execute`: `entry_price` no evento `order_executed` podia gravar
    `null` na trilha (visto ao vivo no trade de 17/07 16:51 UTC — o ccxt nem
    sempre devolve `average`/`price` na resposta de criação de ordem a
    mercado). Corrigido com fallback pra `signal.entry_price` (o mesmo preço
    já usado no sizing) — necessário pro cálculo de `pnl_usdt` do take-profit
    por software ter um preço de entrada confiável.

## Bugs corrigidos em 18/07 (não reintroduzir)

18. `engine._execute_spot_take_profit`: venda do TP tratada como sempre
    100% preenchida — nunca conferia `order.get("filled")` nem detectava
    preenchimento parcial; pnl/audit usavam o tamanho PEDIDO, não o
    vendido de fato. Corrigido: usa `filled` real; se sobrar mais que
    poeira (`SPOT_DUST_USDT`), RE-ARMA um stop pro restante em vez de
    limpar a proteção como se a posição tivesse fechado inteira.
19. `engine._execute_spot_take_profit`: quando o stop disparava CONCORRENTE
    ao TP (saldo zera após `cancel_all`), o código só limpava a proteção
    sem auditar nada — achado por 3 lentes independentes na revisão
    adversarial de 18/07, o fechamento real ficava mudo PRA SEMPRE (exata
    lacuna que a sessão de 18/07 foi criada pra fechar, reintroduzida por
    um caminho diferente). Corrigido: esse branch delega pra
    `_handle_spot_position_closed`, que confirma o fill via `fetch_order`.
20. `engine._handle_spot_position_closed`: `average`/`price` da ordem do
    stop podiam vir `0` (não `None`) e passavam pelo guard `is None` como
    "confirmado", virando `reason="stop_loss"` com `pnl_usdt` fabricado.
    Corrigido: guard truthy, mesmo padrão de `_resolve_entry_price`.
21. `engine._execute_spot_take_profit`/`_handle_spot_position_closed`: se
    `audit()`/`clear_protection()` falhassem (I/O, lock do OneDrive) DEPOIS
    de uma venda de TP bem-sucedida, o ciclo seguinte reprocessava a mesma
    posição como "fechamento externo" usando `stop_price` (alvo de PERDA)
    — pnl CONTRADITÓRIO pra um trade que foi lucro. Corrigido: audits do
    sucesso envoltos em try/except; proteção sempre limpa/re-armada depois,
    independente do audit ter funcionado.
22. `protection_state.load()`: só cobria `json.JSONDecodeError`/`OSError`;
    um `UnicodeDecodeError` (bytes inválidos em UTF-8) escapava sem
    tratamento e derrubava `run_once()` inteiro — crash real de `--once`.
    Corrigido: `except (OSError, ValueError)` cobre os dois (JSONDecodeError
    e UnicodeDecodeError são ambos ValueError).

## Bugs corrigidos em 19/07 (não reintroduzir)

23. `bybit_client.cancel_all()`: nunca cancelava a categoria `tpslOrder` da
    Bybit v5 (onde o stop real de spot vive) — só a categoria default
    `"Order"` (comuns). TP por software ficava preso pra sempre tentando
    vender sem nunca liberar o saldo preso no stop original. CRÍTICO, achado
    monitorando o primeiro teste ao vivo do TP. Corrigido: em spot, faz 2
    chamadas (`cancel_all_orders` default + `params={"orderFilter":
    "tpslOrder"}`). Ver "Estado exato — 19/07" pro relato completo.
24. `executor.py`: `protect_size = min(size, free)` não cobria fill
    FAVORÁVEL (preço melhor que o do sinal credita MAIS base que o
    teórico) — sobra real sem proteção nenhuma. Corrigido: mede saldo
    ANTES/DEPOIS da compra e protege a DIFERENÇA (imune a saldo alheio
    pré-existente, cobre os dois sentidos de divergência).
25. `executor.py`: `entry_price` caía direto no preço do SINAL sem tentar
    confirmar o fill real quando `create_order` não devolvia
    `average`/`price`. Corrigido: tenta `fetch_order(entry_id)` antes desse
    fallback (mesma técnica de `engine._resolve_entry_price`).

## Bugs corrigidos em 20/07 (não reintroduzir)

26. `executor.py`: `stop_price`/`take_profit` calculados no preço do SINAL
    (close do último candle fechado) e nunca reajustados pro preço real do
    fill — se o mercado se movesse bastante dentro do mesmo candle (visto
    ao vivo: ~565 USDT em ~2s, logo após um TP disparar), o TP podia nascer
    ABAIXO do próprio preço de entrada real, causando loop de reentrada
    (abre→fecha por centavos→reabre) que drena taxa a cada ciclo. Contido
    na hora com kill switch manual (MCP), corrigido depois: desloca
    `stop_price`/`take_profit` pela mesma distância entre o preço do sinal
    e o fill real (`price_drift`), preservando a distância de risco que o
    `RiskManager` usou pro sizing. Ver "Estado exato — 20/07".

## Bugs corrigidos em 21/07 (não reintroduzir)

27. `engine._execute_spot_exit` (pré-existente desde 18/07 no caminho de
    TP): saldo-base zero após o `cancel_all` era SEMPRE tratado como "stop
    disparou concorrente" — mas se o `cancel_all` tivesse FALHADO (rede), o
    saldo continuava preso na ordem de stop AINDA VIVA e o código fabricava
    um `trade_closed` (external_close_unconfirmed) pra uma posição aberta,
    apagando a proteção. Achado por 2 lentes independentes da revisão de
    21/07, verificado inline. Corrigido: antes de reconciliar, consulta
    `fetch_order(stop_id)` — status open/untriggered → `*_exit_failed` +
    proteção MANTIDA + retry no próximo ciclo.
28. `risk_manager.RiskManager._kill_switch` só existia em RAM — reiniciar o
    processo zerava o halt SEM gerar evento na trilha (achado ao vivo em
    20/07, documentado, não corrigido até agora). Duas consequências reais:
    um kill switch disparado por drawdown "resetava" sozinho num restart
    (violando a regra de reset SEMPRE manual), e `state_reader.read_halt_status`
    (usado pelo MCP `trader_halt_status`) ficava reportando um trip antigo
    como ativo pra sempre, mesmo com o motor livre de novo — visto ao vivo
    nesta sessão (21/07, ~15h-16h UTC): status dizia `halted: true` enquanto
    o motor operava e fechava trades normalmente. Corrigido: novo módulo
    `src/risk/kill_switch_state.py` persiste `{halted, reason}` em
    `state/kill_switch_state.json` (escrita atômica, mesmo padrão de
    `protection_state.py`) — `RiskManager.__init__` carrega o estado real na
    inicialização (halted persistido → motor INICIA halted, reset continua
    exclusivamente manual); `trip_kill_switch`/`reset_kill_switch` persistem
    a cada chamada. `state_reader.read_halt_status()` agora lê esse arquivo
    como fonte primária (fallback pra inferência da trilha só se o arquivo
    nunca existiu). Testes: guarda de backup/restore do novo arquivo
    adicionada em `test_smoke.py`/`test_ciclo.py` (mesmo padrão de
    `spot_protections.json` — sem isto, instanciar `RiskManager()` nos
    testes sobrescreveria o estado real do motor) + 9 testes novos (seção 22
    de `test_smoke.py`) cobrindo boot sem arquivo, trip/reset persistindo e
    sobrevivendo a um "restart" simulado (RiskManager novo), arquivo
    corrompido, e `state_reader.read_halt_status()` lendo o arquivo como
    fonte primária. Suíte 150/150 verde após o fix (142+8), rodada com o
    motor parado. **CONFIRMADO ao vivo, ponta a ponta, ainda em 21/07**: o
    Lucas religou o motor (`engine_start` 18:04:40 UTC) e
    `state/kill_switch_state.json` passou a existir gravado como não-halted
    — mas o `trader_halt_status` do MCP continuou preso no trip de 20/07 por
    mais um tempo, porque o `mcp_server.py` (processo separado) também não
    recarrega código, e não tinha sido reiniciado. Só corrigiu de verdade
    depois que o Lucas reiniciou o Claude Desktop (mata/reabre o
    `mcp_server.py`) — ver "Achado operacional novo" no topo do arquivo e a
    entrada nova na seção Operacional. Lição: um fix em código que o MCP
    importa (`state_reader.py` aqui) exige restart do Desktop, não só do
    motor, pra valer — fácil de esquecer.
29. `executor.py`: `protect_size` (e o `close_size` do caminho de emergência)
    eram calculados com UMA ÚNICA leitura de `fetch_free_base` logo após a
    compra — se essa leitura viesse atrasada/racy na exchange (saldo ainda
    não assentado), `protect_size` saía 0 e o código desistia de
    proteger/fechar SEM NUNCA reconfirmar o saldo real, auditando
    `naked_position_close_failed` (o evento mais grave do catálogo) mesmo
    quando a compra podia ter creditado base de verdade. **Achado pelo
    watchdog agendado (`trader-watchdog`), não por mim** — rodou às 19:06
    UTC e reportou 3 ocorrências reais (ETH 18:49:50, ETH 18:50:55, BTC
    19:01:35) numa rajada de reentrada rápida (compra→stop em ~60-70s,
    repetida 6x em 8 minutos no ETH, preço oscilando ~5% entre ciclos).
    Investiguei: no momento do achado, os saldos reais na exchange batiam
    com o que estava protegido (`state/spot_protections.json`) — ou seja,
    não havia posição nua ATIVA quando cheguei a olhar, mas o MECANISMO
    tinha um furo genuíno que podia morder num dia de mais volatilidade.
    Corrigido: até 2 tentativas em spot antes de declarar sem proteção —
    se a 1ª leitura pós-compra der `protect_size<=0`, reconfirma
    `fetch_free_base` UMA vez (reusando o mesmo `free_before` de sempre,
    imune a dust alheio) antes de desistir. Perp não é afetado (sem esse
    conceito de saldo-base; mantém 1 tentativa, comportamento idêntico).
    Testes novos (seção 17b de `test_smoke.py`): saldo atrasado na 1ª
    leitura reconfirma e arma o stop na 2ª tentativa (nunca desiste sem
    reconfirmar); saldo zero CONFIRMADO em 2 leituras continua declarando
    `naked_position_close_failed` corretamente (não inventa proteção pra
    dinheiro que não existe). Suíte 152/152 verde (150+2), rodada com o
    motor parado. **Pendência da sessão anterior, INVESTIGADA e RESOLVIDA
    em seguida** (ver "Estado exato — 21/07 ~21:25 UTC" abaixo e bug #30):
    o salto de ~5% do ETH foi anomalia de dado da testnet (mainnet real
    ficou lateral no mesmo período), mas expôs uma lacuna de arquitetura
    real — sem cooldown, nada impedia reentrada imediata no mesmo sinal.
30. **Lacuna de arquitetura: sem cooldown após stops seguidos no mesmo
    símbolo** — nada impedia o motor reabrir a MESMA entrada repetidamente
    enquanto o sinal (candle de 15m) continuasse válido, mesmo após
    stop-loss consecutivo. Achado investigando o bug #29 (ver "Estado exato"
    abaixo): 1 evento de dado ruim virou 6 ciclos de perda (~53 USDT) em 8
    minutos no ETH/USDT, ao invés de 1. Decisão do Lucas: 2 stops seguidos
    no mesmo símbolo aciona cooldown — 30min no 1º acionamento do dia
    (UTC), 60min do 2º em diante. Implementado: `config/risk_config.yaml`
    (nova seção `cooldown`), `src/risk/cooldown_state.py` (persistência em
    disco, mesmo padrão atômico de `kill_switch_state.py` — sobrevive a
    restart, senão um restart no meio de um cooldown ativo apagaria a
    proteção silenciosamente), `RiskManager.record_trade_close()` (chamado
    pelo engine nos dois pontos onde `trade_closed` é auditado — incrementa
    a sequência em `stop_loss`, QUEBRA a sequência em qualquer outro motivo)
    + veto em `evaluate()` logo após o kill switch. Sem a chave `cooldown`
    no YAML, a feature fica desligada (nunca veta) — mesmo padrão de
    `exit_on_signal`/`trailing`. 12 testes novos (seção 23 de
    `test_smoke.py`): sem histórico aprova normal, 1 stop não aciona, 2º
    stop aciona e veta, outro símbolo não é afetado, sobrevive a "restart"
    simulado, TP no meio quebra a sequência, escalonamento 30→60min no
    mesmo dia, expira naturalmente (mesma instância, tempo real passando —
    não só via restart), arquivo corrompido tratado como vazio, feature
    desligada sem a chave no YAML. Suíte 164/164 verde (156+8), rodada com
    o motor parado. **Ressalva encontrada no caminho, NÃO corrigida**: nem
    `kill_switch_state.json` nem `cooldown_state.json` têm o mesmo
    isolamento que `logs/audit.jsonl` tem via `AUDIT_PATH` (fix #14, 15/07)
    — o backtester oficial (`src/backtest/backtester.py`) instancia
    `RiskManager` de verdade e herdaria o estado REAL de kill switch/
    cooldown se alguém rodasse um backtest enquanto o motor ao vivo
    estivesse halted ou com um símbolo em cooldown. Risco baixo (produz um
    resultado obviamente estranho — tudo vetado —, não um dano silencioso),
    mas é uma lacuna real de isolamento. Documentado aqui, não corrigido —
    fixaria com o mesmo padrão de override por env var que `AUDIT_PATH` já
    usa, se algum dia incomodar de verdade.

**CONFIRMADO ao vivo em 22/07/2026, madrugada — primeira vez que o
mecanismo disparou de verdade em produção** (até então só validado em
teste). Três acionamentos reais na mesma madrugada, todos batendo
exatamente com o desenho: (1) ETH/USDT, 2 stops seguidos
(21/07 23:49 → 22/07 02:51 BRT — 2 stops separados por essa distância
ainda contam como "seguidos", já que nada entre eles quebrou a sequência),
`cooldown_triggered` às 01:51:58 UTC, 30min, 1º acionamento do dia; (2)
BTC/USDT, 2 stops seguidos (06:19 → 06:20 BRT, perdas de -32,52 e -13,08
USDT), `cooldown_triggered` às 09:20:38 UTC, 30min, 1º acionamento do dia
pra esse símbolo; (3) ETH/USDT de novo (05:16 → 06:24 BRT — o stop de
04:53 tinha sido resetado por um take-profit de +3,59 às 05:07, prova ao
vivo de que "TP quebra a sequência" funciona de verdade, não só em teste),
`cooldown_triggered` às 09:24:54 UTC, **60min** (2º acionamento do dia pra
ETH, confirma a escalada 30→60min ao vivo). Nenhum kill switch disparou,
nenhum erro, nenhuma posição nua — só o cooldown fazendo exatamente o que
foi desenhado pra fazer. PnL realizado total caiu de +233,95 pra
**+182,04 USDT** (30 trades, win rate 33,3%) nessa sequência — a maior
perda individual foi o stop do BTC de -32,52 USDT. **Bug #29 (reconfirmação
de saldo) segue SEM validação ao vivo** — nenhum cenário de saldo
atrasado/nu ocorreu nesta janela, só fechamentos normais confirmados via
`fetch_order`.

## Bugs corrigidos em 21/07, 2ª rodada (não reintroduzir)

Achados numa sessão de supervisão pura (Lucas pediu status/PnL/histórico),
sem nenhuma mudança de risco/execução — os dois em módulos read-only
(`state_reader.py`) ou de isolamento de teste (`kill_switch_state.py`/
`cooldown_state.py`), nunca tocados antes hoje.

31. **`state_reader._read_audit(limit=N)` cortava as últimas N LINHAS
    BRUTAS do `audit.jsonl` ANTES de filtrar por tipo de evento —
    `trader_realized_pnl` (MCP) relatava um agregado gravemente errado.**
    Achado ao vivo: o Lucas pediu o PnL de um trade fechado; `trader_realized_pnl`
    (MCP, `limit=500` default) reportou `closed_trades: 1,
    realized_pnl_usdt: -5.81` — quando a trilha real tinha **20**
    `trade_closed` somando **+233,95 USDT** (10 take_profit = +316,05; 10
    stop_loss = -82,10). Causa: a trilha é dominada por
    `signal_vetoed`/`symbol_skipped` repetitivos (a cada ciclo, ~60-65s);
    com o corte por LINHA feito antes do filtro por tipo, as últimas 500
    linhas cruas viravam quase só ruído recente, empurrando `trade_closed`
    (evento raro) pra fora da janela — o bug piora sozinho quanto mais
    tempo o motor roda. `recent_decisions()` tinha o mesmo padrão de fundo
    (paliativo `limit*3`, insuficiente). Corrigido: `_read_audit()` agora
    sempre lê o arquivo inteiro (barato — poucos ms mesmo com dezenas de
    milhares de linhas); `realized_pnl`/`recent_decisions` filtram por tipo
    de evento PRIMEIRO e só aplicam `limit` DEPOIS, sobre a lista já
    filtrada. Verificado contra a trilha real (script isolado, só leitura,
    sem tocar o motor ao vivo): `realized_pnl(limit=500)` bate exatamente
    com a contagem manual (20 trades, +233,95 USDT); `realized_pnl(limit=3)`
    traz os 3 MAIS RECENTES de verdade. 3 testes novos (seção 24 de
    `test_smoke.py`, reprodução sintética do cenário: trade raro atrás de
    600 linhas de ruído). **Exigiu restart do Claude Desktop pra valer no
    MCP** (mesma regra de sempre, `mcp_server.py` não recarrega código) —
    Lucas reiniciou logo depois do fix; **reconfirmado ao vivo na mesma
    sessão**: `trader_realized_pnl`/`trader_recent_decisions` voltaram a
    responder corretamente depois do restart.

32. **Isolamento de `kill_switch_state.json`/`cooldown_state.json` via env
    var** — completa a ressalva deixada em aberto no bug #30, e é mais
    grave do que aquela nota registrava ("risco baixo, resultado estranho,
    não dano silencioso"). O backtester oficial (`src/backtest/backtester.py`)
    instancia um `RiskManager` DE VERDADE, que GRAVA (não só lê) em
    `state/kill_switch_state.json`/`state/cooldown_state.json` — os MESMOS
    arquivos do motor ao vivo — toda vez que é instanciado (`__init__`
    sempre chama `kill_switch_state.save()`) e de novo a cada
    `trip_kill_switch()`/`record_trade_close()` simulado durante o
    backtest. Ou seja: um trip/cooldown SIMULADO podia sobrescrever o
    arquivo REAL silenciosamente — o `kill_switch_tripped` correspondente
    vai pro `AUDIT_PATH` isolado do backtest (fix #14), nunca pra
    `logs/audit.jsonl`, então nada explicaria pro Lucas por que o motor ao
    vivo passou a rejeitar entradas do nada. Corrigido com o mesmo padrão
    do `AUDIT_PATH`: `src/risk/kill_switch_state.py`/
    `src/risk/cooldown_state.py` ganharam override por env var
    (`KILL_SWITCH_STATE_PATH`/`COOLDOWN_STATE_PATH`, lido ANTES do import,
    resolvido uma vez em `STATE_PATH`); os 3 pontos que instanciam
    `RiskManager` real fora do motor — `run_backtest.py`,
    `run_walkforward.py`, `research/parity_check.py` — agora setam as duas
    env vars com `os.environ.setdefault(...)` antes de importar `src.*`,
    apontando pra arquivos isolados (`*-backtest.json`/`*-research.json`).
    Verificado ponta a ponta: subprocesso com as env vars setadas (mesmo
    jeito que os runners fazem) disparou kill switch + cooldown de
    verdade — gravou só nos arquivos isolados; os arquivos reais ficaram
    byte-a-byte idênticos antes/depois. Sem a env var (motor ao vivo, MCP —
    nenhum dos dois a seta), `STATE_PATH` continua apontando pros arquivos
    reais de sempre — **zero mudança de comportamento pro motor ao vivo,
    não precisa restart nenhum pra este fix específico** (só afeta
    execuções futuras de backtest/walk-forward/parity check). 4 testes
    novos (seção 25 de `test_smoke.py`, com subprocesso isolado — isola
    `AUDIT_PATH` além dos dois arquivos de estado, ver "Achado colateral"
    abaixo pro motivo).

**Suíte CONFIRMADA verde**: assim que o motor parou (`engine_stop` manual
21:02:58 UTC), rodei `test_smoke.py` + `test_ciclo.py` de ponta a ponta —
**173/173** (165 + 8, cresceu de 164 com os 9 checks novos das seções
24-25). Sem regressão em nenhum dos 163 checks pré-existentes.

**Achado colateral desta verificação (não é bug de produção, é erro meu
nesta sessão) — documentado porque deixou 2 linhas de teste na trilha
real, já limpas**: meu primeiro script de verificação manual do bug #32
(fora da suíte, um `.py` avulso rodado direto) isolou
`KILL_SWITCH_STATE_PATH`/`COOLDOWN_STATE_PATH` mas esqueceu de isolar
`AUDIT_PATH` — gravou um `kill_switch_tripped` e um `cooldown_triggered`
de teste em `logs/audit.jsonl` de verdade (~00:54:38 UTC, 22/07). Impacto
real: ZERO — `state/kill_switch_state.json` real ficou confirmadamente
intocado (`halted: false` o tempo todo), só a TRILHA ficou com 2 linhas
de ruído (o `trader_halt_status` chegou a mostrar o texto de teste no
`last_reason` por alguns minutos, via fallback pra trilha — não afetou
`halted`). **Autorizado pelo Lucas no chat** ("Sim, autorizo limpar a
trilha"), as 2 linhas foram movidas (nada apagado) pra
`logs/audit-teste-contaminacao-2026-07-21.jsonl`, com um evento
`audit_maintenance` novo registrando a operação — 2º evento desse tipo na
história do projeto (1º foi 15/07, ver seção "Analisar a trilha"
abaixo). Corrigido pra não repetir: seção 25 de `test_smoke.py` agora
isola `AUDIT_PATH` também (defesa em profundidade, mesmo se um script
avulso futuro esquecer de novo).

**Segundo achado colateral, mais preocupante**: durante essa MESMA janela,
o Lucas religou o motor (`engine_start` 01:11:32 UTC) enquanto eu ainda
tinha um `test_smoke.py` rodando (eu tinha checado "motor parado" ANTES de
começar, mas ele foi religado no meio) — exatamente o cenário que o
protocolo "nunca rodar a suíte com o motor vivo" tenta evitar. Verificado
depois: nenhum evento real parece ter sido perdido (a contagem de linhas
fecha exatamente com os eventos reais esperados na janela, sem gaps
óbvios de timestamp), mas não é uma garantia absoluta, só uma boa
evidência circunstancial. O motor foi parado de novo pouco depois
(01:14:19 UTC) e a suíte final (a que deu 173/173 acima) rodou inteira
com ele parado, sem esse risco. **Lição pra próxima sessão**: checar
"motor parado" não é garantia que continua parado — se possível, pedir
confirmação explícita ao Lucas de que ele não vai religar durante a
janela da suíte, ou aceitar o risco residual pequeno e sempre reconferir
a trilha depois (como fiz aqui).

## Bugs corrigidos em 27/07 (não reintroduzir)

Achados pela auditoria completa (pente-fino) rodada na transição pra
mainnet — 24 agentes, 5 lentes + verificação cética por achado. Ver "27/07
— O DIA DA TRANSIÇÃO" no topo do arquivo pro contexto completo. Os 4
últimos (#39-#41, #44-#45) foram decididos/corrigidos por mim DEPOIS do
workflow, não pelo workflow em si (o workflow só documentou, sem aplicar,
por exigirem decisão do Lucas ou terem sido achados só depois).

33. `mcp_server.py`/`src/engine.py`: sinal de controle (`state/control.json`,
    canal MCP→engine pra halt/reset/reset_cooldown) não tinha isolamento
    nem rótulo de ambiente — um pedido feito com o MCP apontando pra
    testnet podia ficar parado no arquivo e ser aplicado cegamente por um
    engine já reiniciado em mainnet (ou vice-versa), sem nenhum registro de
    pra qual ambiente o pedido era. Achado plausível dado que processos
    `mcp_server.py` órfãos (não recarregam `.env`) já são um padrão
    documentado neste projeto. Corrigido: `_write_control_signal` agora
    grava `environment` no payload; `_apply_control_signal` descarta
    (audita `control_signal_environment_mismatch`) qualquer sinal cujo
    ambiente gravado DIVIRJA do ambiente real do processo atual. Sinal sem
    o campo (legado) continua sendo aplicado como sempre.
34. `src/logger.py`/`src/supervision/state_reader.py`: nenhum evento
    auditado (exceto `engine_start`) carregava um campo `environment` —
    se `logs/audit.jsonl` algum dia voltasse a acumular eventos de dois
    ambientes (exatamente o que aconteceu horas depois, ver incidente de
    contaminação concorrente no topo do arquivo), `trader_realized_pnl`/
    `trader_recent_decisions` (MCP) misturariam os dois sem aviso nenhum.
    Corrigido, aditivo (não muda nenhum valor já consumido): `audit()`
    grava `environment` em todo evento; `realized_pnl()` ganhou um campo
    novo `environments` (contagem de `trade_closed` por ambiente) sem
    filtrar/alterar os totais agregados existentes.
35. `src/engine.py` (`_execute_spot_exit`): quando a leitura de saldo pro
    rearm do stop antigo vinha zerada/insuficiente SEM lançar exceção
    (`rearm_size <= 0`), a função caía num `return` mudo — nem `log.critical`
    nem evento de auditoria. Quem monitora a trilha (inclusive o
    `trader-watchdog`) não teria NENHUM evento pra reagir a uma posição
    potencialmente sem proteção. Corrigido: adicionado o `else` que
    faltava, auditando o mesmo evento crítico (`*_rearm_stop_failed`) já
    usado no ramo de exceção vizinho.
36. `src/engine.py` (`_execute_spot_exit`): a leitura de saldo logo após o
    `cancel_all()` (pra saber quanto vender) era ÚNICA — se viesse
    atrasada/racy (mesma classe do bug #29, 21/07, lá era a leitura
    PÓS-COMPRA, aqui é a PÓS-CANCELAMENTO), o código confundia "posição
    ainda aberta, leitura atrasada" com "fechamento concorrente
    confirmado", fabricava um `trade_closed` e apagava o rastreio de uma
    posição real e agora desprotegida. Corrigido: reconfirma a leitura
    UMA vez (mesmo padrão do bug #29) antes de diagnosticar via `stop_id`.
37. `src/engine.py` (`_execute_spot_exit`): `filled` vindo `0` EXPLÍCITO
    (diferente de ausente/`None`, que já tinha fallback seguro) na resposta
    da venda a mercado fazia `sold=0.0` e o bloco de "fill parcial" tentava
    re-armar um stop pro tamanho INTEIRO de uma posição já vendida —
    disparando um alarme crítico FALSO de "posição sem proteção" pra uma
    venda que teve sucesso (mesma classe de resposta incompleta do ccxt já
    documentada nos bugs #17/#19/#25, nunca tratada neste caminho de
    saída). Corrigido: reconfirma via `fetch_order` (mesma técnica já usada
    em `executor.py`) antes de aceitar um `0` explícito como venda zerada.
38. `src/risk/kill_switch_state.py`/`cooldown_state.py`: `save()` não tinha
    nenhum try/except — uma falha transitória de I/O (lock do OneDrive, já
    visto neste projeto, inclusive nestes MESMOS arquivos, bugs #31/#32)
    propagava sem barreira, derrubando `RiskManager.__init__` e o `Engine`
    inteiro — inclusive tentativas de restart do `supervisor.py`, podendo
    esgotar as 5 tentativas/30min e virar `engine_supervisor_giveup` por
    causa de um obstáculo de I/O passageiro, não um problema real. Corrigido:
    `save()` nos dois arquivos agora captura `OSError` e loga aviso, mesmo
    padrão já usado pelas funções `load()` irmãs.
39. `src/risk/kill_switch_state.py`/`cooldown_state.py`: **testnet e mainnet
    liam/gravavam o MESMO arquivo de estado** — `_resolve_state_path()` só
    isolava backtest/pesquisa do motor ao vivo (override por env var,
    bug #32), nunca testnet de mainnet. Achado ao vivo: `cooldown_state.json`
    tinha `ETH/USDT` com `triggers_date` de HOJE (atividade de testnet),
    que faria um stop real em mainnet ser tratado como o 2º acionamento do
    dia (60min) em vez do 1º (30min) — enviesando pro lado mais cauteloso,
    mas ainda um bug real de contabilidade. Corrigido (decisão do Lucas,
    "ok" — ver pergunta feita a ele): `_resolve_state_path()` agora também
    consulta `ENVIRONMENT` quando não há override explícito — mainnet
    mantém o nome canônico de sempre (`kill_switch_state.json`/
    `cooldown_state.json`); testnet ganha arquivo dedicado
    (`kill_switch_state-testnet.json`/`cooldown_state-testnet.json`). Dados
    de testnet existentes MIGRADOS pro arquivo novo (não perdidos); os
    arquivos canônicos (mainnet) resetados limpos. 2 testes novos
    (`test_smoke.py`) provam a resolução correta nos dois ramos.
40. `src/engine.py` (`_execute_spot_exit`): os dois pontos de re-arm do
    stop (após venda falhar; após preenchimento parcial) chamam
    `set_stop_loss` — a MESMA chamada condicional (`tpslOrder` em spot) que
    o incidente de compliance de hoje (ver topo do arquivo) confirma sujeita
    a bloqueio da Bybit. Diferente da ENTRADA (`executor.py`), que quando o
    stop falha fecha a posição a MERCADO (ordem comum, imune ao bloqueio),
    estes dois pontos não tinham fallback nenhum — só alertavam e deixavam
    a posição exposta. Corrigido (decisão do Lucas, "reatm de stop" —
    aprovado): novo método `_emergency_liquidate()` — última tentativa
    antes de desistir, vende a mercado (sem `stopLossPrice`, não passa pela
    categoria bloqueada); se aceita, audita `naked_position_close` (o
    próximo ciclo reconcilia via `_handle_spot_position_closed`, sem
    duplicar lógica de PnL aqui); se também falhar,
    `naked_position_close_failed` + o alerta crítico de sempre. 4 testes
    novos (sucesso e falha da liquidação, nos dois pontos de rearm).
41. `src/engine.py` (`_update_trailing_stop`): quando o saldo base vinha
    zerado após `cancel_all()` (`rearm_size <= 0`), o código SEMPRE assumia
    fechamento concorrente pelo stop e reconciliava — sem confirmar se o
    stop real ainda estava ativo (o fix #27 de 21/07, que faz exatamente
    essa confirmação, nunca tinha sido propagado deste caminho irmão, só
    existia em `_execute_spot_exit`). Se o `cancel_all()` tivesse falhado
    silenciosamente (rede), o código fabricaria um `trade_closed` falso pra
    uma posição real e protegida. Corrigido (decisão do Lucas, aprovação
    explícita depois de eu explicar o que a correção faz e não faz — NÃO
    resolve o bloqueio de compliance em si, só corrige o diagnóstico):
    mesma confirmação via `fetch_order(stop_id)` do fix #27, agora também
    aqui. Novo evento `trailing_move_stop_still_active` quando a
    reconciliação é abortada por falta de confirmação. 3 testes novos
    (saldo zero + stop ainda ativo → mantém proteção; saldo zero + stop
    confirmadamente fechado → reconcilia normal, provando que a correção
    não quebrou o caminho de fechamento genuíno).
42-43. (números pulados de propósito — os dois incidentes operacionais do
    dia, .env revertido e contaminação por testes concorrentes, não são
    bugs de CÓDIGO; documentados em prosa no topo do arquivo, não aqui.)
44. `tests/test_smoke.py`/`test_ciclo.py`: o fake de exchange usado nos
    testes de exclusividade por símbolo (`FakeSaudavel` e equivalentes)
    devolvia `fetch_funding_rate = -0.005` fixo — valor que só passa no
    clamp FROUXO da testnet (`max_abs_funding_rate_testnet: 0.01`), nunca
    testado contra o clamp apertado de mainnet (`max_abs_funding_rate:
    0.003`) porque `.env` sempre esteve em testnet durante o
    desenvolvimento. Rodar a suíte pela primeira vez com `.env=mainnet`
    (27/07) vetava toda entrada destes testes por "Funding anômalo", sem
    relação nenhuma com o que a seção realmente testa. Corrigido: valor
    fixo trocado pra `0.001`, seguro nos dois clamps.
45. `tests/test_smoke.py`/`test_ciclo.py`: o guard de
    `state/spot_protections.json` (backup no import + restauração via
    `atexit`) nunca LIMPAVA o arquivo antes de rodar os testes — só
    garantia restaurar o conteúdo real no final. Com proteções reais
    persistidas (posições reais de swing, ETH/BTC), qualquer `Engine()`
    instanciado por um teste cujo fake não implementa `fetch_order`
    (`FakeSaudavel`) herdava essas entradas e travava tentando reconciliá-las
    como "fechadas externamente" — contaminando testes de exclusividade por
    símbolo que nada têm a ver com proteção de posição. Corrigido: os dois
    arquivos agora zeram `state/spot_protections.json` pra `{}` logo após o
    backup, ANTES de qualquer teste rodar (restaurado ao final como
    sempre).

## Decisão nova (28/07/2026 ~02:20 UTC): trailing e take-profit fixo passam a conviver

A pedido explícito do Lucas ("eu quero os dois" — depois de eu explicar que
`trailing: true` zerava o take-profit fixo por design desde 22/07), o
**único** ponto do código que forçava exclusividade entre os dois mecanismos
foi removido: `src/strategy/deterministic.py` calculava `tp = None if
p.trailing else price + p.tp_rr * (price - stop)` — agora sempre calcula o
`tp` (mesma fórmula de sempre, `tp_rr` do YAML/default 2.0), com ou sem
trailing. **Nenhuma outra mudança foi necessária**: `engine.py`
(`_check_spot_exits`, linha ~404: `tp = protection.get("take_profit"); if tp
and price >= tp: ...`) e `backtester.py` (`_try_close`, linha ~282) já
checavam `take_profit` e `trailing` de forma totalmente independente —
bastava a estratégia parar de zerar o `tp`. Efeito prático: a posição sai
pelo que disparar primeiro — TP fixo (cancela o stop, vende a mercado) se o
preço subir até o alvo `tp_rr`, ou o stop móvel se reverter antes disso.
Validado com um backtest sintético isolado (candle onduladO, mesmo cenário
já usado na seção 20g de `tests/test_smoke.py`): de 10 trades com trailing,
4 fecharam via `take_profit` (lucro travado no alvo) e 6 via `trailing_stop`
— confirma os dois mecanismos coexistindo de ponta a ponta. **Achado
colateral, não é bug, só efeito emergente esperado**: como o TP agora
realiza lucro mais cedo em pernas de alta, o motor reentra com mais
frequência nas oscilações — alguns dos fechamentos por `trailing_stop`
nesse cenário sintético foram pequenas perdas nos vaivéns entre entradas
(sem o TP, uma única posição teria "surfado" a alta inteira até a reversão
final). Isso é o comportamento literalmente pedido (realizar no alvo em vez
de sempre deixar correr), não uma regressão. **Exige restart do motor pra
valer** (Python não recarrega módulo em processo já rodando) — a posição
ETH/USDT já aberta nasceu sem TP (`take_profit: null`, trailing=True) e foi
atualizada MANUALMENTE na sequência (ver bug #47 abaixo) a pedido do Lucas;
só entradas NOVAS a partir do próximo restart calculam os dois sozinhas.

**Suíte completa RODADA em seguida, motor parado (a pedido do Lucas: "roda
a suíte completa quando o motor parar")** — achou e corrigiu uma REGRESSÃO
real de teste antes de fechar como validado: o próprio backtest sintético
da seção 20g (candle ondulado, usado pra provar trailing+TP convivendo)
passou a fechar trades agressivo o suficiente para cruzar o limite de
drawdown diário (3,20% ≥ 3,0%) e disparar o kill switch DE VERDADE —
`Backtester.__init__` instancia um `RiskManager` real sem isolar
`KILL_SWITCH_STATE_PATH`, então esse trip persistia em
`state/kill_switch_state.json` de verdade e vazava pro PRÓXIMO teste que
instancia `RiskManager`/`Backtester` (seção 21e, sem nenhuma relação com
trailing/TP) — reproduzia sempre, não intermitente: `Backtester(cfg,
profile="daytrade").run(...)` da seção 21e passou a dar 0 trades (kill
switch herdado bloqueando tudo) em vez do 1 trade esperado. Causa raiz: uma
lacuna de isolamento PRÉ-EXISTENTE na suíte (só backup/restore uma vez no
início/fim do arquivo inteiro via atexit, nunca por seção) que nunca tinha
se manifestado porque o cenário ondulado antigo (trailing sem TP) nunca
cruzava o limite de drawdown. Corrigido com um reset pontual do kill switch
real (`kill_switch_state.save(False, "")`) logo após o backtest da seção
20g — mais simples e seguro que isolar toda a suíte por env var, e
suficiente pra parar de vazar pro teste seguinte. **Suíte final: 261/261 em
`test_smoke.py` (257 pré-existentes + 4 novos da seção 29) + 8/8 em
`test_ciclo.py` = 269/269 verde**, confirmado com o motor genuinamente
parado (checado via lista de processos, não só a trilha). Arquivos reais
(`state/spot_protections.json` com o TP aplicado no bug #47,
`state/kill_switch_state.json`, `state/cooldown_state.json`,
`logs/audit.jsonl`) verificados intactos e corretamente restaurados depois
da suíte — nenhuma contaminação residual.

## Bug corrigido em 27/07 (madrugada de 28/07 UTC, primeiro boot `--live` em mainnet — não reintroduzir)

46. `src/execution/protection_state.py`: **`state/spot_protections.json` não
    era isolado por AMBIENTE** — mesma classe do bug #39 (kill_switch/
    cooldown), mas nunca estendida a este arquivo. Achado AO VIVO no
    primeiro `engine_start` real em mainnet (2026-07-28 01:53:11 UTC,
    `supervisor.py --live`): o arquivo ainda tinha 2 proteções RESIDUAIS da
    era testnet (ETH/USDT entry_price=1910,31; BTC/USDT entry_price=66106,10
    — valores incompatíveis com a equity real de mainnet, ~24 USDT). O
    engine tentou confirmar o fill dessas ordens de stop contra a exchange
    MAINNET, recebeu "order not found" (correto — nunca existiram lá) e
    reconciliou as duas como fechadas (`reason="external_close_unconfirmed"`),
    fabricando 2 `trade_closed` com PnL negativo total de **-62,73 USDT**
    que nunca aconteceram em mainnet — no mesmo dia em que `logs/audit.jsonl`
    tinha sido zerado pra começar o PnL de mainnet do zero. **Nenhum
    dinheiro real foi afetado** (as ordens não existiam pra cancelar nem
    vender); só a trilha/PnL relatado ficou poluído. Corrigido na fonte, a
    pedido do Lucas ("pode limpar a trilha e corrigir o isolamento por
    ambiente"): `_resolve_state_path()` novo, mesmo padrão de
    `kill_switch_state.py` — override por `PROTECTION_STATE_PATH` +
    resolução por `ENVIRONMENT` (mainnet mantém `spot_protections.json`;
    testnet ganha `spot_protections-testnet.json`). **Exige restart do
    motor pra valer** (Python não recarrega módulo em processo já rodando)
    — não aplicado ainda ao processo `--live` corrente (só mainnet ativo
    neste PC agora, risco baixo até o próximo restart natural). Trilha
    corrigida: os 2 `trade_closed` fabricados foram movidos (não apagados)
    pra `Historico-Testnet-2026-07-27/audit-fabricado-boot-mainnet-2026-07-27.jsonl`,
    com um `audit_maintenance` novo (3º da história do projeto, mesmo
    padrão de 15/07 e 21/07) documentando a correção — `trader_realized_pnl`
    voltou a reportar 0 trades fechados/0 USDT em mainnet, refletindo a
    realidade (só a posição ETH/USDT real, aberta às 01:53:26 UTC, segue
    ativa). **Lição**: qualquer arquivo de estado local novo (`state/*.json`)
    precisa do MESMO isolamento por ambiente desde o início — este e o #39
    já são 2 casos do mesmo padrão de bug.

47. Aplicação manual do take-profit retroativo na posição ETH/USDT real
    (28/07/2026 ~02:53 UTC, a pedido explícito do Lucas: "sim, aplica o TP
    na posição atual"). Calculado com a MESMA fórmula da estratégia
    (`entry_price + tp_rr * trail_distance` — usa `trail_distance`, a
    distância de risco ORIGINAL fixa desde a entrada, não o `stop_price`
    atual que já subiu com o trailing): `1875,64 + 2,0 × 41,74714... =
    1959,134285714286`. Aplicado direto em `state/spot_protections.json`
    via script isolado (só leitura/escrita do JSON — não passa pelo
    `Executor`, não cria/cancela nenhuma ordem real, só o alvo que o
    `_check_spot_exits` do engine já confere a cada ciclo). **Erro meu,
    achado e corrigido na mesma sessão**: o script importou `src.logger`
    direto sem passar por `config.settings` antes — como `load_dotenv()`
    só roda no import de `config.settings` (`src/logger.py` lê
    `os.environ.get("ENVIRONMENT", "testnet")` cru, sem carregar o `.env`
    sozinho), o evento de auditoria `protection_take_profit_manually_set`
    saiu gravado com `environment: testnet` — o TP em si estava certo
    (aplicado de verdade na posição real de mainnet), só o RÓTULO do
    evento. Corrigido in-place (não é evento fabricado, só metadado
    errado) + `audit_maintenance` documentando a causa e a correção.
    **Lição**: qualquer script avulso que chame `audit()`/leia `ENVIRONMENT`
    precisa importar `config.settings` (ou rodar via um entry point que já
    o importe) ANTES de qualquer outra coisa — `src/logger.py` sozinho não
    carrega o `.env`.

## Bugs corrigidos em 28-29/07 (sessão perp, não reintroduzir)

48. `src/exchange/bybit_client.py` (`_with_retry`): `retCode 10002` da
    Bybit (`ccxt.InvalidNonce`, subclasse de `NetworkError` — já caía no
    retry existente, mas sem nunca re-sincronizar) fazia TODA chamada
    assinada falhar pro resto da vida do processo, uma vez que
    `load_time_difference()` (medido só uma vez no boot) pegasse uma
    medição ruim. Achado ao vivo: ~5h23min de `cycle_error` ininterrupto
    (07:56-13:16 UTC de 28/07). Corrigido: `_with_retry` deixou de ser
    `@staticmethod`, re-sincroniza o relógio (`self.exchange.load_time_difference()`)
    antes de cada nova tentativa quando o erro é `InvalidNonce`, em vez de
    repetir a mesma assinatura ruim 3x. Ver "Sessão 28-29/07" no topo do
    arquivo pro relato completo.
49. `src/engine.py`: **fechamento de posição PERP nunca era auditado** —
    perp nunca tinha operado de verdade neste projeto (bloqueio de
    compliance desde 15/07), então o equivalente de `_check_spot_exits`
    nunca tinha sido construído pro lado perp. Sem isto: nenhum
    `trade_closed` saía quando o stop/TP real disparava, o cooldown por
    símbolo nunca era alimentado, e a ordem IRMÃ (stop ou TP) que não
    disparou ficava ATIVA E ÓRFÃ na exchange — risco real confirmado ao
    vivo (2 TPs órfãos encontrados na conta real, um deles capaz de
    executar contra uma posição nova não relacionada se o preço voltasse
    ao alvo antigo). Corrigido: `protection_state.py` ganhou `tp_id`/`side`;
    `executor.py` persiste a proteção em toda entrada agora (spot E perp,
    antes só spot); `bybit_client.py` ganhou `cancel_order`; `engine.py`
    ganhou `_check_perp_exits`/`_handle_perp_position_closed` (confirma via
    `fetch_order` qual das duas ordens disparou, audita `trade_closed` com
    o fill real e o `side` correto — PnL tinha fórmula fixa de LONG, errada
    pra SHORT, corrigido junto —, alimenta o cooldown, cancela a órfã só
    quando confirma com certeza qual disparou). Suíte 288/288 confirmada
    (280 smoke + 8 ciclo), deployado e validado ao vivo (backfill recuperou
    a posição real que já estava aberta antes do fix existir). **Ressalva
    NÃO resolvida**: um caso real onde o stop disparou mas a Bybit
    REJEITOU a execução (`status=rejected`, `filled=0`) deixou uma ordem
    órfã escapar da limpeza automática (o fix corretamente não confirmou o
    fechamento nesse caso, então não cancelou nada às cegas) — ver "Sessão
    28-29/07" no topo pro relato completo. Trailing real pra perp
    (`_update_perp_trailing_stop`, mesma sessão) tem testes ESCRITOS
    (seção 31) mas NUNCA RODADOS — ver "PRÓXIMA AÇÃO" no topo do arquivo.

## Bug corrigido em 18/08 (não reintroduzir)

50. **`tests/test_smoke.py` + `tests/test_ciclo.py` gravavam o backup da trilha
    no MESMO nome (`logs/audit.jsonl.bak-teste`) — e a combinação disso com uma
    falha de restauração DESTRUIU a trilha real do PC1.** Sequência exata:
    (a) o smoke copia a trilha REAL para o `.bak-teste`; (b) escreve eventos de
    teste na trilha; (c) o `atexit` do smoke tenta restaurar e FALHA — no Windows
    a pasta sincroniza (Dropbox/OneDrive) e `os.replace`/`copy2` sobre arquivo com
    seção mapeada aberta dá `PermissionError`/`WinError 1224`; essa falha já era
    conhecida e considerada inofensiva ("é só rodar de novo"); (d) **o ciclo roda
    em seguida e copia a trilha JÁ CONTAMINADA por cima do único backup**;
    (e) o `atexit` do ciclo consegue restaurar e grava a versão contaminada.
    A falha do passo (c) sozinha era recuperável; combinada com (d) virou perda
    definitiva — 15.858 linhas → 1. **Aconteceu de verdade em 18/08/2026.**
    Impacto real: PC1 apenas (histórico de 28-31/07); **PC2 intacto** (107.773
    linhas) e é a fonte de verdade desde 31/07; `state/*.json` do PC1 foram
    restaurados corretamente.
    **Corrigido** com `tests/_guard.py` (novo), que garante duas invariantes:
    (A) **nunca sobrescrever um backup pendente de QUALQUER suíte** — olhar só o
    próprio sufixo não basta, e foi exatamente esse o buraco (quem contaminou foi
    a suíte A e quem rodou em seguida foi a B, com nome diferente); no import,
    havendo `.bak-*` pendente, restaura a partir do MAIS ANTIGO e só então remove;
    (B) **restaurar escrevendo DENTRO do arquivo** (`open(...,"wb")`, não troca o
    inode), que é o que funciona com o arquivo mapeado pelo sync, com retentativas.
    Provado contra o cenário exato (suíte A falha ao restaurar + suíte B roda em
    seguida → original sobrevive).
    **Lição operacional que vale mais que o fix**: rodar a suíte a partir de uma
    CÓPIA fora da pasta sincronizada elimina a classe inteira de problema. Foi
    assim que 307/307 foi confirmado nesta sessão. Também ficou no `.gitignore`
    `state/*.tmp` — a escrita atômica deixa órfãos quando o `replace` falha.

## Estado exato — 21/07 ~21:25 UTC (investigação do whipsaw ETH + cooldown)

A pedido do Lucas ("vamos resolver essa pendência" + "configurar o watchdog
para 30 min"), a pendência do bug #29 foi investigada com um workflow
multi-agente (3 frentes em paralelo + síntese): candles de 1m/15m da
TESTNET no período do incidente (18:00-19:15 UTC), candles de 1m do
MAINNET público no MESMO período (pra comparação com o mercado real), e a
timeline completa da trilha de auditoria do robô.

**Achado principal: o ETH real NÃO se moveu.** Mainnet ficou lateral
(-0,11% na janela crítica, amplitude total de ~0,43% no período inteiro).
A testnet mostrou uma subida de +7,66% concentrada em 2 candles de 1m
(volume 250x-1000x acima do normal) seguida de uma queda de -4,72%/-5,0%
concentrada em UM candle de 1m (18:55:00 UTC) — assinatura clássica de
glitch de dado/liquidez fina de testnet, não descoberta de preço orgânica.
Nenhum timestamp duplicado no período do incidente (o padrão de "kline
congelada" existe no dataset, mas num trecho anterior sem relação direta).

**As 6 aprovações do robô usaram o MESMO sinal literal** (`rationale`
idêntico: `"EMA_fast>EMA_slow e RSI=38.8<70"`) — o candle de 15m não tinha
virado durante todo o episódio, então cada stop disparado era seguido de
reentrada imediata no ciclo seguinte (~60-70s depois). Sem bug de código
(sem race condition, sem timestamp inconsistente) — a lógica funcionou como
desenhada; o problema é a AUSÊNCIA de um cooldown pós-stop. Dano real na
janela: ~53 USDT em ~8 minutos (parcialmente amortecido porque 3 das 6
entradas ficaram quase-poeira — saldo ainda se recompondo entre ciclos,
nenhuma posição ficou nua em nenhum momento).

**Decisão e implementação**: ver bug #30 acima. Cooldown de 2 stops
seguidos → 30/60min, escalando por dia, por símbolo — decisão do Lucas.

**Watchdog reconfigurado**: de hora em hora para **30 em 30 minutos**
(`mcp__scheduled-tasks__update_scheduled_task`, `cronExpression: "*/30 * * * *"`)
— a pedido do Lucas na mesma sessão.

## Dossiê diário — contexto macro/on-chain (novo, 2026-07-15)

`dossier_fetch.py` (raiz) roda 1x/dia (não no loop de 60s): pesquisa via Claude +
web search o dossiê de mercado (calendário, macro, técnico, on-chain, radar de 20
moedas, posicionamento — mesmo conteúdo do `Dossie-Cripto-Prompt-Template-v2.html`),
extrai os dados em formato estruturado (chamada separada com `tool_choice`
forçado, nunca parsing manual) e grava três coisas: `Dossie Cripto\Historico\
{data}.md`, `Dossie Cripto\importar-no-dashboard-{data}.json` (mesmo schema que já
era usado manualmente) e `data\context\{latest.json, history.jsonl}`.

`src/context/providers.py` ganhou `DossierMacroProvider`/`DossierOnChainProvider`,
que só LEEM `data/context/latest.json` (com checagem de frescor: `date` != hoje
UTC → `{}`, nunca dado velho). `src/engine.py` linha ~40 já usa esses providers em
vez dos `Null*` — mudança de 2 linhas, sem tocar risco/execução/`state/control.json`.

**Status: roda de verdade, 3x/dia desde 22/07/2026** (07h/13h/19h horário
local), via a tarefa agendada `dossie-cripto-intraday` (`mcp__scheduled-tasks`
— mesmo sistema do `trader-watchdog`, `cronExpression: "0 7,13,19 * * *"`),
instruída como "versão-ponte" do `dossier_fetch.py` — grava nos MESMOS
caminhos/formato para serem intercambiáveis. Continua inerte para o robô
enquanto `decision.strategy` for `"deterministic"` (não lê `snap.context`) — só
ganha efeito quando a Fase 3 ligar.

**Histórico da mudança (22/07/2026, a pedido do Lucas — "reconfigurar a
rotina do Dossie para atualizar durante o dia 2 ou 3 vezes")**: existia uma
tarefa ANTERIOR, "Dossie cripto diário" (rodava 1x/dia, ~7h), criada
direto no painel do Cowork — **desativada pelo Lucas nesta mesma sessão**,
substituída pela nova de 3x/dia. Prompt idêntico ao original (o Lucas
colou o texto completo no chat pra garantir fidelidade), com duas
adaptações técnicas necessárias: (a) removido o "PASSO 0" original
(`mcp__cowork__request_cowork_directory`, específico de como o painel do
Cowork concede acesso a uma pasta de Projeto) — substituído por acesso
direto a caminhos absolutos, mesmo padrão do `trader-watchdog`; (b) os 3
caminhos de gravação (Passo 4) viraram absolutos. O contrato de arquivo
(`dossier_fetch.py`, lido antes de mexer em qualquer coisa) já é seguro
pra rodar várias vezes/dia: `Historico/{data}.md`,
`importar-no-dashboard-{data}.json` e `latest.json` são sobrescritos a
cada rodada (cada uma vira "a versão mais fresca do dia"); só
`history.jsonl` é append-only, então 3 rodadas/dia viram 3 entradas/dia em
vez de 1 — ganho de granularidade intraday, não bug.

**Achado operacional importante pra sessões futuras**: existem HOJE dois
sistemas de tarefa agendada distintos e SEM visibilidade cruzada — (1)
tarefas criadas direto no painel do Cowork (ex.: a "Dossie cripto diário"
antiga) NÃO aparecem em `mcp__scheduled-tasks__list_scheduled_tasks` nem
têm pasta correspondente em `C:\Users\lucas\.claude\scheduled-tasks\`; só
são visíveis/editáveis pelo próprio painel do Cowork (o Lucas precisa
fazer isso manualmente, nenhuma ferramenta minha alcança); (2) tarefas
criadas via `mcp__scheduled-tasks__create_scheduled_task` (ex.:
`trader-watchdog`, `dossie-cripto-intraday`) aparecem no `list` e têm
`SKILL.md` próprio no caminho acima — essas eu leio/edito/crio livremente.
**Antes de assumir que uma automação "não existe" só porque não aparece em
`list_scheduled_tasks`, perguntar ao Lucas pra conferir no painel do
Cowork** — foi exatamente esse engano que quase levou a duplicar o dossiê
nesta sessão.

## Watchdog agendado — EM STANDBY desde 18/08/2026

> ⚠️ **`trader-watchdog-pc2` está com `enabled: false` desde 18/08/2026**, a
> pedido do Lucas ("prefiro acompanhar no monitor aqui no Claude Code"). O
> `SKILL.md` foi preservado — religar é um `update_scheduled_task` com
> `enabled: true`. O `dossie-cripto-pc2` segue LIGADO.
>
> **Consequência real: não existe mais supervisão automática fora de sessão.**
> Dentro de uma sessão dá para armar um `Monitor` na trilha (feito em 18/08:
> filtra eventos críticos, aberturas/fechamentos, E vigia AUSÊNCIA de batimento —
> se o motor morre a trilha só para de crescer, e um filtro que só procura erro
> ficaria mudo, indistinguível de "tudo bem"). Mas isso morre com a sessão, e já
> morreu silenciosamente antes (29-30/07, ~7h de eventos perdidos). **Regra que
> continua valendo: depois de qualquer intervalo sem sinal, reconciliar contra a
> trilha completa em vez de assumir que nada aconteceu.**
>
> **Motivo do bug de permissão que levou ao standby** (vale para qualquer tarefa
> agendada futura): as regras de allowlist do projeto vivem em
> `.claude/settings.local.json`, que é PROJECT-scoped; tarefa agendada roda com
> outro cwd e não as enxerga. `~/.claude/settings.json` não tinha bloco
> `permissions`. A correção (bloco `allow` escopado + `deny` em `config/`,
> `state/`, `logs/`) está pronta em `PASSO-A-PASSO-18-08-2026.md` e **só o Lucas
> pode aplicar** — o classificador de auto mode bloqueia o agente de se
> auto-conceder permissão, corretamente.

### Como era (histórico, 2026-07-21)

A pedido do Lucas ("o alerta pode vir pela própria notificação do Claude?"),
tarefa agendada `trader-watchdog` criada via `mcp__scheduled-tasks`, mesmo
mecanismo do dossiê diário acima. Roda de hora em hora (`cronExpression: "0
* * * *"`, decisão do Lucas — topou até 1h de atraso pra minimizar overhead
em vez de 5-15min). Cada execução, sem memória de sessão nenhuma (prompt
completo e autocontido em
`C:\Users\lucas\.claude\scheduled-tasks\trader-watchdog\SKILL.md`):

1. Lê o fim de `logs/audit.jsonl`: se o último `engine_start`/`engine_stop`
   for `engine_stop`, o motor está parado DE PROPÓSITO — não notifica nada
   (decisão explícita do Lucas: motor parado é estado esperado, não falha).
2. Se estiver rodando: chama `trader_halt_status` (MCP `wonder_trader`) e
   varre a última 1h da trilha por `kill_switch_tripped`,
   `naked_position_close_failed`, `take_profit_rearm_stop_failed` (críticos,
   qualquer um dispara alerta), ou 3+ `cycle_error`/`symbol_cycle_error`
   (indício de problema de conexão persistente).
3. Só chama `PushNotification` (desktop + celular, se Remote Control
   conectado) se algo do passo 2 foi encontrado. Rotina normal fica
   SILENCIOSA de propósito — err toward not sending, mesma filosofia da
   ferramenta.

É SOMENTE LEITURA por regra explícita no próprio prompt — nunca cria/cancela
ordem, nunca escreve em `risk_config.yaml`/`state/control.json`, nunca chama
`trader_request_halt`/`reset`. Cobre a metade "alerta" do item `[ALVO]`
"processo supervisionado com restart automático + alerta ativo"; a metade
"restart automático" continua não implementada.

**Limitação real, contada ao Lucas**: só roda enquanto o Claude
Desktop/Cowork estiver aberto — se fechado na hora marcada, roda no próximo
lançamento do app, não é daemon independente do app. **Pendência
operacional**: recomendado rodar "Run now" manual uma vez pra pré-aprovar as
ferramentas (`wonder_trader`, `PushNotification`), senão a 1ª execução
automática pode pausar pedindo aprovação sem ninguém ali pra responder.
Primeira rodada real confirmada: 18:06 UTC de 21/07, sem alertas (motor
saudável). Detalhe completo em memória:
`watchdog-agendado-bybit.md` (fora do repositório, no diretório de memória
do agente).

## Próximos passos, na ordem

1. ~~Confirmar/resolver o saldo de brinde travando BTC/USDT~~ — **RESOLVIDO
   por evidência em 17/07** (ver "Estado exato — 17/07"): o `signal_approved`
   explícito antes do `order_executed` mostra que não era pseudo-posição de
   brinde. `diag_saldo.py` não precisou rodar.
2. ~~Fechar a Etapa B-spot de verdade~~ — **FECHADA e SAÍDA validada em
   19/07 15:15:51 UTC**: TP por software da posição BTC de 17/07 executou
   ao vivo, `trade_closed` com `pnl_usdt=+56,51` confirmado 1:1 contra o
   histórico de ordens da Bybit (ver "Estado exato — 19/07"). Etapa B-spot
   totalmente fechada — entrada, proteção E saída lucrativa automática, tudo
   confirmado na exchange real.
3. **Estratégia: revisitada em 20/07 a pedido do Lucas ("qual a melhor
   estratégia pra montar um robô foda com o que já temos?").** Resposta
   honesta, baseada em `research/RELATORIO-2026-07-16.md` (108 combinações,
   6 famílias, walk-forward, verificado por 9 agentes): NENHUMA família
   testada tem edge validado — nem a atual, que é a PIOR das 6 (mediana WF
   -3,40%, 0/18 séries positivas); a "menos pior" (bollinger_mr) ainda é
   negativa (-0,02%). Janela testada foi 100% bear (6 meses), então não dá
   pra saber se alguma família teria ido bem numa alta — e o dataset está
   queimado pra seleção (já foi inspecionado demais). Caminho recomendado,
   NA ORDEM (nada implementado ainda):
   a) ~~**Pré-requisito de engenharia**: construir saída por SINAL/trailing
      stop~~ — **FEITO em 21/07** (ver "Estado exato — 21/07"): saída por
      sinal + trailing implementados, testados (141/141) e revisados
      adversarialmente; backtester em paridade. Desligados por default —
      ligar é decisão do Lucas via YAML.
   b) ~~Baixar histórico novo (2+ anos, regime misto) e re-rodar o
      walk-forward nas famílias de tendência (donchian, ema_cross) em
      1h/4h, agora COM saída por sinal/trailing~~ — **PRIMEIRA RODADA FEITA
      em 21/07** (ver "Estado exato — 21/07 ~16:00 UTC" e
      `research/RELATORIO-2026-07-21-pesquisa-2b.md`): ainda SEM edge
      validado (donchian mediana -3,43%, ema_cross -6,54%); robot_baseline
      confirmou DE NOVO ser a pior opção (mediana -29,82%, piorou vs
      16/07). Rodada enxuta (decisão do Lucas) — sem painel adversarial.
      ~~PRÓXIMO PASSO, se alguém quiser continuar puxando este fio: rodar
      verificação adversarial completa (como 16/07) em cima de donchian/4h
      especificamente ANTES de qualquer decisão de capital~~ — **FEITO em
      22/07** (ver "Estado exato — 22/07 ~20:20 UTC" abaixo): painel de 9
      agentes (6 lentes + 3 juízes), veredito UNÂNIME **não promover** —
      os únicos 2 resultados "positivos" (ETH, BNB) dependem inteiramente
      de um único fold coincidindo com o crash de 10/10/2025 nos 5 símbolos
      ao mesmo tempo (falha de desenho: janelas OOS sincronizadas por
      calendário entre símbolos), não de edge repetível. **Este fio
      específico (donchian/4h neste universo de 5 símbolos) está
      encerrado.** Quem quiser continuar investigando estratégia, a
      recomendação dos 3 juízes é considerar a alternativa já registrada
      abaixo — universo fixo de 5-6 símbolos pode não ser onde o edge está
      (visão de produto original é varredura de universo + ranking, não
      símbolo fixo) — ou redesenhar o walk-forward com janelas OOS
      dessincronizadas por símbolo antes de testar qualquer família nova.
   c) Dia-trade 15m: descartado de vez, matematicamente inviável em spot
      (fee come 60-95% da perda, 0/108 combinações positivas).
      **Fechado na prática em 18/08/2026**: o perfil `daytrade` (15m) foi
      DESLIGADO no YAML. Confirmado inviável também em PERP long+short com fee
      de 0,055% (mediana −97,20% em BTC+ETH nos últimos 12 meses) — ou seja, não
      era efeito da fee de spot, é fricção estrutural do timeframe contra o teto
      de nocional. Ver "Sessão 18/08/2026 (noite)".
   d) **Rodada 3 EXECUTADA em 18/08/2026** (perp long+short, dado novo, 8
      símbolos, painel adversarial de 9 agentes): **veredito unânime NÃO
      PROMOVER** nenhuma das 5 famílias. Ver
      `research/RELATORIO-2026-08-18-pesquisa-3-perp.md`.
      **O que a rodada 3 mudou para as PRÓXIMAS**, e é o item mais importante
      deste bloco: **o critério de aceitação que o projeto vinha usando não
      discrimina nada.** Uma grade ingênua de 300 configs de tendência dá
      100% de medianas positivas na mesma janela, e 38% com 8/8 símbolos
      positivos. Foi esse critério que aprovou os falsos positivos de 16/07 e
      22/07, e foi ele que aprovou as candidatas de 18/08 antes do painel
      derrubar. **Antes de testar qualquer família nova, trocar o critério** —
      exigir: (i) sobreviver à remoção do melhor trade de CADA símbolo;
      (ii) p permutacional ajustado para multiplicidade E para a correlação
      entre símbolos (~2,3 séries efetivamente independentes, não 8);
      (iii) resultado positivo num recorte de regime PARECIDO COM O ATUAL, não
      só no histórico completo; (iv) bater o benchmark certo (para long+short o
      benchmark é 0%/caixa, não o buy&hold).
      **`research/data_3/` já está QUEIMADO para seleção** — foi varrido por 6
      lentes, vizinhança de 172 combos, placebo e permutação.
   e) **Pré-condição de engenharia para QUALQUER promoção futura** (achada em
      18/08, ver sessão): a saída por sinal é código morto em perp e
      `engine.py:789` fixa `side="long"`. Construir esse caminho — com teste
      cobrindo os DOIS lados — vem ANTES de qualquer teste de família nova.
      E resolver o conflito com o kill switch de 3% (reset manual), que congela
      a estratégia candidata em 6 de 8 símbolos na simulação.
4. **#G fonte on-chain real-time: DECIDIDA em 18/07/2026, IMPLEMENTADA em
   22/07/2026** (a pedido do Lucas, opção 1 — dado derivado da própria
   Bybit: funding rate, open interest, long/short ratio; sem contratar API
   paga). Contexto original: o dossiê diário já cobre on-chain, mas é foto
   1x/dia (`data/context/latest.json`, `DossierOnChainProvider` descarta se
   `date` ≠ hoje UTC); a lacuna era real-time intra-dia. Bybit API não tem
   dado on-chain de verdade (não lê blockchain) — o que ela dá é sentimento
   de DERIVATIVOS (funding, OI, long/short ratio dos usuários dela), não
   fluxo de exchange/MVRV/SOPR — por isso o provider novo se chama
   `BybitDerivativesProvider` (nome deliberadamente diferente de
   `DossierOnChainProvider`, tanto pela precisão semântica quanto para não
   colidir a mesma chave `"onchain"` no dict de contexto agregado — a chave
   nova é `"derivatives"`). Esses endpoints são de mercado PÚBLICO (funding
   history, open interest, account-ratio) — leitura, não trade; não
   dependem da conta estar em modo spot nem esbarram no bloqueio de
   derivativos pra residente BR (que é só sobre EXECUTAR ordem).

   **Implementação**: `src/exchange/bybit_client.py` ganhou 3 métodos novos
   (`fetch_derivatives_funding_rate`, `fetch_open_interest`,
   `fetch_long_short_ratio` — este último via
   `fetch_long_short_ratio_history(limit=1)`, porque o ccxt não suporta
   `fetchLongShortRatio` de "valor atual" pra Bybit, só o histórico;
   confirmado com sonda ao vivo contra a mainnet pública antes de
   escrever o código) — todos SEMPRE consultam o PERPÉTUO do símbolo,
   independente do modo de conta ativo (nunca usados pelo `RiskManager`;
   `fetch_funding_rate` original, usado pelo circuit breaker de risco e que
   retorna `None` em modo spot por decisão deliberada, ficou intocado).
   `src/context/providers.py` ganhou `BybitDerivativesProvider`, fiado no
   `ContextAggregator` do `Engine.__init__` junto dos providers do dossiê.

   **Revisão adversarial no mesmo dia (5 lentes + verificação cética de
   cada achado) — 11 achados, os 11 confirmados, todos corrigidos:**
   - (ALTO — achado por 3 lentes independentes, o mais grave) `context.build()`
     rodava SEM GATE nenhum, todo ciclo (~65s), pra TODO símbolo×perfil não
     ocupado — mesmo com `decision.strategy: deterministic` (o real da
     produção) nunca lendo `snap.context`. Como `BybitDerivativesProvider`
     faz 3 chamadas de rede REAIS por invocação (ao contrário dos
     providers do dossiê, que só leem um arquivo local), isso significava
     até 12 chamadas HTTP reais à Bybit por ciclo — custo de latência/
     rate-limit genuíno na produção viva, por um dado 100% descartado, sem
     nenhuma chave de YAML pra desligar (quebrando o padrão que
     `exit_on_signal`/`trailing`/`cooldown` já estabeleceram: toda
     capacidade nova vem com on/off). Corrigido: `engine.py` agora só
     chama `self.context.build(symbol)` quando `llm_gate` (
     `decision.strategy == "llm"`) está ligado — mesmo gate que já existia
     pro re-chamado da LLM em candle repetido, só que agora também cobre a
     construção do contexto. Com `decision.strategy: deterministic` (hoje),
     ZERO chamadas de rede do provider novo — genuinamente inerte, não só
     "o resultado é descartado".
   - (MÉDIO) `BybitDerivativesProvider.fetch()` não isolava cada uma das 3
     chamadas — uma exceção não tratada em UM endpoint (hoje impossível,
     os 3 métodos do client sempre capturam a própria falha, mas nada
     garantia isso pra sempre) apagaria os resultados dos OUTROS dois que
     já tinham vindo certos, porque só o `ContextAggregator` (uma camada
     acima) tinha proteção. Corrigido: cada uma das 3 chamadas agora tem
     seu próprio try/except dentro de `fetch()`.
   - (BAIXO) os 3 métodos do client devolviam um dict "verdadeiro" mesmo
     quando o campo extraído vinha `None` (ccxt pode responder com sucesso
     mas com o campo ausente) — um dict de 3 chaves todas `None` ainda
     passa no `if funding:` de quem chama, mesma classe dos bugs #20/#27
     já corrigidos aqui. Corrigido: cada método só devolve dict se o campo
     principal veio preenchido de verdade; senão `None`.
   - (BAIXO) `next_funding_rate` era campo morto — verificado direto no
     pacote ccxt instalado (`.venv/Lib/site-packages/ccxt/bybit.py`): é
     `None` hardcoded no parser da Bybit para QUALQUER símbolo, nunca vem
     da API de verdade. Removido do retorno.
   - (BAIXO) `fetch_long_short_ratio` era chamado sem passar `timeframe`
     explícito, dependendo do default do client (`"1h"`) coincidir — se um
     dia só um lado mudasse, divergiria em silêncio. Corrigido: `providers.py`
     passa `timeframe="1h"` explícito.
   - (MÉDIO) os testes originais faziam fake do CLIENT inteiro (uma camada
     acima do parsing real), nunca exercitando o `.get("fundingRate")`/
     `.get("openInterestAmount")`/`rows[-1]` de verdade em `bybit_client.py`
     — corrigido com uma seção nova de testes no nível do `self.exchange`
     (mesmo padrão de `FakeCcxtBalance` já usado no arquivo), cobrindo
     sucesso, campos `None`, histórico vazio e falha de rede.
   - (BAIXO) um `assert` cru dentro de uma fake de teste (não o helper
     `ok(...)` do arquivo) abortaria o script inteiro de ~2300 linhas se um
     dia falhasse, em vez de reportar 1 FAIL isolado — corrigido pra
     capturar e checar depois, como todo resto do arquivo faz.
   - (BAIXO) o teste "`run_once` não quebra com client incompleto" só
     provava que ALGUMA camada engolia o erro, não especificamente o
     `ContextAggregator` (o catch genérico do `engine.run_once()` também
     mascararia uma regressão ali) — corrigido com um teste direto no
     `fetch()`/`ContextAggregator.build()`, sem o engine no meio.
   - (MÉDIO, meta) este próprio parágrafo do `CLAUDE.md` — corrigido agora.

   Suíte: 199/199 em `test_smoke.py` (191 + 8 novos checks da seção 27,
   incl. 2 provando o gate na prática: zero chamadas com
   `decision.strategy: deterministic`, chamadas reais só com o gate
   aberto) + 8/8 em `test_ciclo.py` = **207/207 verde**, confirmados numa
   rodada oficial com o motor parado (parada limpa via `CTRL_C_EVENT`
   real, mesma técnica de sempre — `engine_stop`/manual às 23:20:56 UTC;
   `engine_start` 23:22:38 UTC religou via `supervisor.py`, 1º ciclo
   reconciliou as 2 posições sem erro).

   **Status real de uso**: fiado no `Engine` ao vivo, mas genuinamente
   INERTE hoje (zero chamada de rede) — só passa a fazer as 3 chamadas por
   símbolo×perfil quando `decision.strategy: llm` for ligado no YAML
   (decisão futura do Lucas, Fase 3). Quando isso acontecer, vale revisitar
   o achado de duplicação (`context.build()` roda uma vez por PERFIL, não
   uma vez por símbolo — dois perfis ativos no mesmo símbolo duplicam a
   consulta de derivativos desnecessariamente) — não corrigido de propósito
   nesta rodada, porque só importa quando a Fase 3 realmente ligar (e essa
   ativação já vai merecer sua própria revisão). Ver seção 10 do v2 pro
   pano de fundo original da decisão #G.
   **#A canal de confirmação do swing: DECIDIDO em 16/07 — autônomo, sem
   portão de confirmação.** Swing já roda assim hoje na prática (perfil
   determinístico, sem gate nenhum); a decisão fixa que continua assim quando
   a Fase 3 (LLM) ligar — sem construir o mecanismo de aprovação humana do
   charter original. Rede de segurança continua sendo só a camada de risco
   determinística, igual ao daytrade. Pode ser revisto depois de ver o LLM
   funcionando na prática, se fizer sentido.
   **#B kill switch flatten: DECIDIDO em 16/07 — manter SEM flatten (atual).**
   Kill switch continua só bloqueando entradas novas; não fecha posições
   abertas à força. Cada posição já tem stop obrigatório cuidando dela
   individualmente; flatten a mercado no meio do evento que causou o
   drawdown arriscaria realizar preço pior que o próprio stop pegaria.
   Nenhuma mudança de código para nenhuma das duas.
   **Distância máxima de stop: DECIDIDA em 16/07 — opção (a), manter como está.**
   O sizing por risco fixo (`risco_usdt / distância_do_stop`) já se autoprotege:
   stop largo → nocional menor, risco em USDT nunca muda. Nenhum teto adicional
   no YAML. Testamos e revertemos uma ideia alternativa (stop de estrutura —
   fundo/topo dos últimos 20 candles, em vez de ATR×mult) — sanity-check em BTC
   15m deu PF 1,63 vs 0,67 do ATR, mas é amostra pequena (9 trades), não
   validada por walk-forward. Lucas decidiu adiar qualquer ajuste de parâmetro/
   estratégia para depois que o robô estiver todo estruturado e funcionando —
   ideia fica registrada aqui para retomar nos ajustes finos futuros.
5. ~~`RASCUNHO-instrucoes-v6-colar-manualmente.md` criado (21/07) — o Lucas
   precisa colar manualmente nas instruções do Claude Project~~ — **FEITO
   pelo Lucas, confirmado em 22/07** (substituiu a v5, que nunca chegou a
   ser colada). **`RASCUNHO-instrucoes-v7-colar-manualmente.md` criado em
   23/07** (a pedido do Lucas, "atualize os documentos necessários do
   roadmap" — fecha o fio da noite: restart automático, #G, Fase 3
   endurecida, fio donchian/4h encerrado, dossiê 3x/dia, bugs #31/#32) —
   **o Lucas ainda precisa colar a v7 manualmente** nas instruções do
   Claude Project, substituindo a v6. A descrição v2 continua válida
   (visão estável por design, nada mudou) — não precisa recolar.
   ~~Colar no Claude Projects (claude.ai) a descrição e as instruções
   atualizadas~~ — **FEITO pelo Lucas em 18/07** (descrição v2 + instruções
   v4 coladas na UI). Os arquivos `RASCUNHO-*-colar-manualmente.md` ficam
   como registro do que foi colado; próxima atualização só quando o estado
   do projeto mudar de fase. **Desde então, v8 (27/07), v9 (28/07) e v10
   (30/07) foram criadas mas NUNCA coladas** (cada uma superseded pela
   seguinte antes do Lucas colar — mesmo padrão da v6→v7).
   **`RASCUNHO-instrucoes-v11-colar-manualmente.md` criado em 19/08/2026**
   (a pedido do Lucas, "atualiza o claudemd readme instruções push e commit"),
   substitui a v10. O que a v11 traz de novo em relação à v10: perfil de 15m
   desligado com a causa raiz (`fee/R = 0,11% ÷ stop%`); a TERCEIRA rodada de
   pesquisa e seu veredito unânime; **o achado de que o critério de aceitação
   não discrimina nada** (300/300 configs ingênuas passam); as duas
   pré-condições de engenharia (saída por sinal é código morto em perp;
   `side="long"` fixo inverteria o short); o conflito não resolvido com o kill
   switch; o watchdog em standby; o comando novo sem `cd`; e a lição de que
   `peak_price` não serve como proxy de MFE.
   **A descrição (`RASCUNHO-descricao-v2-colar-manualmente.md`) foi revisada e
   continua válida sem mudança** — descreve a arquitetura/filosofia estável do
   sistema; nada que mudou desde então altera esse texto. **A v11 FOI COLADA
   pelo Lucas em 19/08/2026** — primeira atualização das instruções do Claude
   Project desde a v7 (22/07); v8, v9 e v10 foram criadas e nunca chegaram a ser
   coladas. **Duas frases da v11 já nasceram desatualizadas** (as duas
   pendências que ela lista foram fechadas horas depois de ela ser colada):
   corrigidas no arquivo, mas o texto dentro do Claude Project só fica fiel se
   o Lucas recolar. A diferença é pequena e o `CLAUDE.md` cobre — recolar é
   opcional.
6. **Engenharia (21/07): resposta à pergunta "o que fazer pra evoluir a
   engenharia do projeto?"** Duas frentes identificadas, fora da linha de
   pesquisa de estratégia: (a) ~~persistência do kill switch~~ — **FEITA e
   CONFIRMADA ao vivo** (bug #28, ver "Estado" no topo); (b) ~~supervisão
   `[ALVO]` do charter (processo supervisionado com restart automático +
   alerta ativo)~~ — **FEITA em 22/07** (ver "Nova capacidade" no topo do
   arquivo): alerta ativo via tarefa agendada `trader-watchdog`
   (`PushNotification`, decisão do Lucas de reaproveitar a notificação do
   próprio Claude em vez de Telegram/e-mail) + restart automático via
   `supervisor.py` (novo, spawna/religa `main.py`, teto de tentativas por
   janela, nunca religa em parada deliberada). **Em uso ao vivo desde
   22/07 ~22:43 UTC** (troca pedida pelo Lucas na mesma sessão) — ver
   "Nova capacidade" no topo do arquivo pro relato completo da troca.

### Decisões tomadas pelo Lucas em 15/07 (fim do dia)

- **#F DECIDIDA: TP no executor** (opção 1). Implementado em 15/07: o executor
  coloca o take-profit que a estratégia emite. Semântica deliberada: stop é
  OBRIGATÓRIO (falhou → desfaz entrada + naked_position_close + raise); TP é
  OPCIONAL (falhou → warn + evento `take_profit_failed`, posição segue
  protegida pelo stop — fechar aqui seria pior que o problema).
- **#E DECIDIDA: migrar para SPOT (Bybit Brasil).** Contexto adicional: o KYC
  da testnet do Lucas travou com erro + limite de tentativas estourado (10024
  segue de pé para derivativos). Implementado em 15/07 atrás de
  `market.type` no YAML (default "perp" — NADA muda até a virada manual):
  short vetado no risco, leverage 1, exposição ≤1x equity, holdings de saldo
  como pseudo-posições (dust <10 USDT ignorado), executor spot sem
  set_leverage e MCP ciente da modalidade. **Status 17/07: CONFIRMADO —
  executor real disparou (compra + stop) na testnet spot, validado na
  exchange pelo Lucas (ver "Estado exato — 17/07").**
  Após revisão adversarial (4 problemas confirmados, todos corrigidos + testes
  29/29):
  a) proteções spot são CLAMPADAS ao saldo-base REAL pós-compra (a fee vem na
     moeda recebida; size teórico era rejeitado e o nunca-nua falhava junto);
  b) em spot o executor arma SÓ O STOP como ordem real — a condicional
     tpslOrder OCUPA o saldo na colocação e não há OCO, então o TP não vai
     como ordem pra exchange (evento `take_profit_skipped`). **Atualizado
     17/07: a saída lucrativa deixou de ser "decisão futura" — implementada
     como TP por software** (`protection_state.py` +
     `engine._check_spot_exits`, ver "Estado exato — 17/07 (parte 2)"); o
     backtest segue medindo o sistema COM TP — ressalva de paridade
     PARCIALMENTE fechada (o backtest ainda assume fill exato no preço do
     TP, sem o atraso de até ~65s do polling nem o cancelamento do stop);
  c) `naked_position_close` só é auditado se o fechamento SUCEDEU; falha vira
     `naked_position_close_failed` (trilha não mente mais);
  d) fee default do backtester acompanha a modalidade (spot taker 0,1%).
- **Preparo da Fase 3 (autorizado): gate de candle para a camada LLM** —
  implementado em 15/07: com `decision.strategy: llm`, o engine só chama o
  Claude quando o candle FECHADO muda para (símbolo, perfil); erro na chamada
  permite retry no ciclo seguinte (marca depois do sinal). Determinística fica
  FORA do gate (comportamento validado no soak preservado). Economia: ~14/15
  das chamadas em perfil 15m. Ligar a Fase 3 continua sendo mudança de YAML
  do Lucas (decision.strategy) — conferir também `decision.llm.model` antes
  (valor atual no YAML é antigo).
6. **NOVA decisão aberta #E (15/07): venue/produto.** Perpétuos Bybit estão
   bloqueados para residente BR (ver Estado). Opções mapeadas: (i) tentar o
   Demo Trading da Bybit (`api-demo.bybit.com`, chave própria gerada na UI de
   demo) só para validar o executor — expectativa baixa, mesmo compliance;
   (ii) abrir ticket no suporte Bybit (o erro 10024 aponta o webform);
   (iii) repensar produto/venue: spot na entidade Bybit Brasil (sem short/
   alavancagem — muda a estratégia), futuros de cripto regulados na B3 via
   corretora, ou outra venue legítima. **Status 16/07: opção (iii)/spot já
   escolhida e em teste ao vivo** — as outras opções ficam de lado enquanto
   o spot não se provar inviável.

## Comandos

```powershell
.venv\Scripts\activate
python main.py            # loop DRY_RUN (paper)
python main.py --once     # um ciclo
python main.py --once --live   # ordens REAIS na testnet (ENVIRONMENT=testnet)
python supervisor.py            # loop DRY_RUN, com restart automático em crash (novo, 22/07)
python supervisor.py --live     # idem, ordens REAIS na testnet
python diag_saldo.py      # diagnóstico de saldo/carteira
python -m pytest ...      # não há pytest; testes são scripts (ver Testes)
```

## Fase 2 — o que a auditoria da régua deixou registrado (15/07)

Auditoria multi-agente (5 lentes + verificação adversarial, 0 refutados) do
backtest/walk-forward. Corrigido no código: fixes #12–#15. **Pendências:**

- **Decisão aberta #F (do Lucas): take-profit.** JÁ DECIDIDA (ver acima) —
  TP no executor, opção 1. Ver ressalva (b) sobre spot pular o TP.
- Aproximações CONHECIDAS da régua (documentadas, não corrigidas): saídas sem
  slippage e sem gap-through no stop (viés otimista; stop gapado preenche no
  preço exato); curva de equity sem mark-to-market de posição aberta (drawdown
  intra-trade invisível; kill switch do backtest dispara mais tarde que o live
  dispararia); vetos de funding/staleness estruturalmente desligados no replay
  (funding_rate=0 hardcoded); EMA com seed diferente do live (janela ~199 vs
  histórico inteiro — divergência residual perto de cruzamentos); degradação
  IS→OOS compara bases de capital diferentes (IS em 1000 fixo, OOS em equity
  costurado) e a média não pondera por nº de trades.
- **Trilha LIMPA em 15/07 ~21:35 UTC, autorizada pelo Lucas** ("autorizo limpar
  a trilha audit.jsonl"): 39.832 eventos simulados (todos de 19:59–20:05Z,
  só signal_approved/vetoed/kill_switch_tripped) MOVIDOS para
  `logs/audit-backtest-contaminacao-2026-07-15.jsonl` — nada apagado; evento
  `audit_maintenance` registra a operação na própria trilha. Restaram 637
  linhas legítimas, 100% JSON válido, ordem cronológica OK, e o
  `trader_halt_status` do MCP voltou a responder `halted: false` (verificado).
  A cirurgia preservou também a sessão engine DRY_RUN real de 11min
  (engine_start 17:44:23Z → último ciclo 17:55:14Z, SEM engine_stop) —
  CONFIRMADO pelo Lucas em 15/07: foi ele testando; janela fechada na marra.
  Não indica loop rodando (zero processos python às 21:30Z).

## Pesquisa de estratégia — 6 meses spot, 6 pares (16/07 ~noite, a pedido do Lucas)

Relatório completo: `research/RELATORIO-2026-07-16.md` (metodologia, números,
refutações e limitações — LER antes de citar qualquer número daqui). Resumo:
108 combinações × 6 famílias × BTC/ETH/SOL/XRP/MNT/BNB × 15m/1h/4h, dados spot
mainnet 12/01–16/07/2026, walk-forward honesto + verificação adversarial de 9
agentes (3 auditorias, 4 refutações, benchmark, crítico). **Veredito: sem edge
long-only detectável nesta janela (100% bear); 15m inviável por fricção (0/108
positivas; 60–95% da perda do robô em 15m é fee); a estratégia atual do robô é
a PIOR família testada (mediana WF -3,4%, 0/18). Todos os positivos foram
refutados (concentração em 1–2 trades).** Nada foi alterado no robô/YAML.
Avisos: o dataset de research/data/ está QUEIMADO para seleção de estratégia
(OOS inspecionado — hipótese nova exige dados novos); `pos_folds` de
wf_results.csv tem bug (66/108 errados; demais métricas reverificadas ok) —
**causa raiz achada e corrigida em 22/07/2026** (ver "Estado exato — 22/07
~20:20 UTC"): `RunResult.total_return_pct` em `research/harness.py`
dividia pelo capital global fixo em vez do capital real do fold; CSVs
antigos não foram regerados, mas qualquer análise NOVA por-fold já usa o
código corrigido; famílias com saída por sinal/trailing NÃO são executáveis no contrato
Signal/executor atual (TP é pulado em spot) — pré-condição de engenharia antes
de promover qualquer estratégia.

**Rodada 2 — SHORT hipotético com alavancagem 2x em perp (16/07 ~madrugada,
a pedido do Lucas).** Relatório: `research/RELATORIO-SHORT-2026-07-16.md` (LER
antes de citar números). Mesma metodologia sobre PERPÉTUOS + funding real, fee
0,055%/lado (HIPOTÉTICA — derivativos bloqueados p/ residente BR; nunca
contornar). Bruto: 38/108 células WF positivas. **Veredito verificado (9
agentes): é 100% beta do bear market, não edge — 0/38 células batem o
short-and-hold passivo do próprio símbolo (melhor célula captura 43% do
passivo); zero t-stat ≥2; sem crash-alpha; seleção ex-ante falha (top-3 IS →
OOS negativo); com fee de spot a "melhor família" (o espelho short do robô)
vira mediana -0,79%.** 15m segue inviável (mediana -4,84% mesmo com fee perp).
Zero liquidações; funding = ruído (±2%/ano). `data_perp/` também QUEIMADO.
`fold_ret_pct`/`pos_folds` do sweep_short estão CORRETOS (fix verificado
108/108 por 4 vias). Não citar max_dd_pct (bug MTM conhecido, herdado). Nada
alterado no robô/YAML.

## Analisar a trilha de auditoria

`logs/audit.jsonl` — JSONL, um evento por linha. Eventos: `engine_start/stop`,
`signal_approved` (desde 17/07 inclui `capped: true/false` — teto de capital
por trade acionado ou não), `signal_vetoed` (com reason), `symbol_skipped`,
`symbol_cycle_error`, `cycle_error`, `dry_run_order` (desde 15/07 inclui
`take_profit`), `order_executed` (desde 15/07 inclui `protect_size`,
`entry_price`, `stop_price`, `take_profit`, `tp_id` — ZERO ocorrências até
16/07 ~20:35, primeira ocorrência real 17/07 16:51:29 UTC, confirmada na
exchange), `take_profit_failed`, `take_profit_skipped` (spot — desde 17/07 o
alvo é salvo em `state/spot_protections.json` nesse mesmo momento, ver
"Estado exato — 17/07 (parte 2)"), `take_profit_executed` (NOVO 17/07 — TP
por software em spot disparou: cancelou o stop e vendeu a mercado),
`take_profit_exit_failed` (NOVO 17/07 — TP disparou mas a venda falhou; alvo
continua salvo, próximo ciclo tenta de novo; o engine tenta RE-ARMAR o stop
original na hora, pra nunca deixar a posição sem proteção nenhuma — se até
isso falhar, `take_profit_rearm_stop_failed`, POSIÇÃO SEM PROTEÇÃO REAL,
intervenção manual imediata),
`trade_closed` (17/07: só saía no caminho de TP por software. **Desde 18/07,
sai nos TRÊS caminhos de fechamento em spot**: TP [`reason="take_profit"`],
stop confirmado via `fetch_order` [`reason="stop_loss"`, preço/tamanho
REAIS do fill] e fechamento sem confirmação [`reason=
"external_close_unconfirmed"`, `exit_price` aproximado = alvo do stop].
Todos têm `exit_price_source` e podem ter `pnl_usdt: null` quando algum
componente é desconhecido — nunca inventa número. O evento
`take_profit_protection_orphaned` foi substituído por isto e não existe
mais), `naked_position_close` (SÓ quando o fechamento de emergência
SUCEDEU), `naked_position_close_failed` (fechamento falhou — POSIÇÃO NUA
REAL, intervenção manual), `kill_switch_tripped/reset`, `cooldown_triggered`
(NOVO 21/07 — `symbol`, `consecutive_stops`, `cooldown_minutes`,
`cooldown_until`, `trigger_number_today`; desde 25/07 dispara já no 1º stop
isolado do símbolo, ver bug #30 e a entrada "cooldown ENDURECIDO" no topo
do arquivo), `cooldown_reset` (NOVO 25/07 — `symbol`,
`previous_cooldown_until`; reset MANUAL antes do prazo natural, via MCP
`trader_reset_cooldown`, nunca automático), `engine_crash_restart` (NOVO
22/07 — só aparece se rodando via
`supervisor.py`; `exit_code`, `uptime_sec`, `attempt_in_window` — processo
caiu sozinho e foi religado automaticamente), `engine_supervisor_giveup`
(NOVO 22/07 — idem; supervisor excedeu o teto de restarts na janela e
desistiu, motor PARADO de verdade, crítico), `audit_maintenance`.
Quando
a Fase 3 ligar (strategy=llm), o gate de candle SILENCIA os ciclos com candle
repetido (zero eventos) — cadência de aprovações/vetos passa a ser por VIRADA
de candle, não por ciclo de ~65s; ajustar as checagens abaixo nesse dia.
Checagens padrão: último `engine_start`; cadência entre aprovações (~65s,
buracos >3min = suspeito); contagem de erros; equity implícito =
`risk_usdt × 200`; stops BTC distintos (1 por candle 15m = código novo OK; 1
por ciclo = candle em formação, bug).
Avisos ao analisar: o arquivo tem 14 eventos órfãos pré-13:16 de 15/07 (runs
`--once` avulsos; incluem o antigo bug long+short às 12:46, pré-fix #7), 2
ciclos órfãos entre as sessões 13:16 e 13:29, e uma sessão engine de 11min
(17:44–17:55Z de 15/07) SEM engine_stop (teste manual do Lucas, janela fechada
na marra — confirmado) — ignorar em métricas de sessão. **Atenção
(27/07/2026): `logs/audit.jsonl` foi ZERADO na transição pra mainnet** (ver
"27/07 — O DIA DA TRANSIÇÃO" no topo do arquivo) — os eventos abaixo desta
nota, incluindo os 2 `audit_maintenance` históricos descritos a seguir, NÃO
estão mais no arquivo real; vivem só em
`Historico-Testnet-2026-07-27/audit-testnet-completo.jsonl` (histórico
completo, preservado). O `logs/audit.jsonl` ATUAL tem, na ordem, **2 eventos
`audit_maintenance` próprios de hoje**: o primeiro documenta o arquivamento
em si (`archived_testnet_history_for_mainnet_transition`, 35.479 linhas
movidas); o segundo (`moved_concurrent_test_contamination`) documenta a
limpeza de uma contaminação por testes concorrentes rodados durante a
auditoria da mesma sessão (ver topo do arquivo) — ambos preservam o que foi
movido, nada foi apagado, mesmo padrão de sempre. Histórico anterior a
27/07, preservado no arquivo de testnet: 2 eventos `audit_maintenance` —
(21:35Z de 15/07) documentando a remoção dos ~40k eventos simulados de
backtest para `audit-backtest-contaminacao-2026-07-15.jsonl` (gravados
antes do fix #14; nada foi apagado); e (~01:10Z de 22/07, madrugada — ver
bug #31/#32) documentando a remoção de 2 linhas de teste
(`kill_switch_tripped`/`cooldown_triggered` com texto óbvio de teste) pra
`audit-teste-contaminacao-2026-07-21.jsonl` — engano de um script de
verificação manual que esqueceu de isolar `AUDIT_PATH`, autorizado pelo
Lucas, nada apagado.
"Sinal FLAT — sem entrada" é signal_vetoed mas NÃO é veto de risco (separar na
contagem). Klines da testnet podem congelar/ser revisados em spikes (visto no
ETH 13:45–14:15) — stop que não muda na virada pede checagem de OHLCV antes de
concluir bug. `symbol_skipped` com motivo "posição já aberta ou entrada
aprovada neste ciclo" pode vir de DUAS fontes distintas — exclusividade
intra-ciclo (perfil 2 pulado porque o perfil 1 já aprovou no mesmo ciclo) OU
reconciliação com posição pré-existente na exchange (visto 16/07, BTC preso
desde 19:29Z sem `signal_approved` correspondente) — cheque se houve
`signal_approved` no mesmo ciclo antes de assumir que foi a primeira causa.

## Testes (em `tests/`)

**Atualização 18/08/2026 — guarda de backup reescrita (bug #50) e COMO rodar.**
`tests/_guard.py` (novo) passou a ser o único dono do backup/restauração dos
arquivos reais que a suíte escreve. `test_smoke.py` e `test_ciclo.py` usam
`FileGuard(path, "<suite>")` — nome de backup POR SUÍTE, e nunca sobrescreve um
`.bak-*` pendente de qualquer suíte (antes os dois usavam o mesmo nome, e isso
destruiu a trilha real do PC1 — ver bug #50).

**Rodar a partir de uma CÓPIA fora da pasta sincronizada.** É o que elimina a
classe inteira de falha: em pasta Dropbox/OneDrive, `os.replace` sobre arquivo
mapeado dá `PermissionError` (atinge inclusive `protection_state._save()`, que é
código de PRODUÇÃO — inofensivo no PC2, que está fora de sync por desenho, mas
quebra a suíte no PC1). Receita usada em 18/08:

```bash
W=/c/Users/lucas/AppData/Local/Temp/claude/.../suiterun
mkdir -p "$W" && cp -r src config tests main.py supervisor.py .env "$W"/
mkdir -p "$W/logs" "$W/state" && cp logs/audit.jsonl "$W/logs/" && cp state/*.json "$W/state/"
cd "$W" && <venv>/python.exe tests/test_smoke.py && <venv>/python.exe tests/test_ciclo.py
```

**Contagem CONFIRMADA em 18/08: 299 smoke + 8 ciclo = 307/307**, com o guard novo,
motor do PC2 parado e rodando fora do Dropbox. Não subiu de 307 porque o fix do
guard é infraestrutura de teste, não comportamento do motor. **NÃO tentar redirecionar
`AUDIT_PATH` para isolar a suíte** — os testes leem o caminho fixo `ROOT/logs/audit.jsonl`
e quebram (tentado e revertido em 18/08).

**Atualização 29-30/07/2026 (suíte confirmada + fix de fixture)**: contagem
CONFIRMADA mais recente é **299/299 `test_smoke.py` + 8/8 `test_ciclo.py`
= 307/307** — cresceu de 288/288 com a seção 31 (9 sub-testes, trailing
real em perp) agora genuinamente EXECUTADA e passando. Na 1ª rodada desta
sessão, 2 dos 9 sub-testes da seção 31 falharam — não por bug no motor,
mas por um bug no PRÓPRIO fixture de teste (`FakePerpExit.fetch_order`
lia `FakePerpExit.ORDER_RESPONSES` da classe-base em vez de
`type(self).ORDER_RESPONSES`, mascarando os cenários de cura de arquivo
stale e de abortar com stop já fechado — ver "Sessão 29-30/07/2026" acima
pro relato completo). Corrigido, suíte 100% verde na 2ª rodada. Validado
ao vivo na sequência: trailing moveu de verdade 5x numa posição short real
e fechou pelo stop já trailed — a última peça do bug #49 que faltava
confirmação fora de teste. O resto desta seção (contagens antigas,
165/199/265/288 etc.) é histórico — não reflete o estado atual do arquivo
de testes.

`tests/test_smoke.py` (165 checks — 156 + 9 novos das seções 24-25,
CONFIRMADOS verdes numa rodada completa com o motor parado (ver bug #31/#32
pro relato): risco, funding por ambiente, sizing, teto de
capital por trade incl. caso 0 explícito, engine com exchange fake,
executor/posição nua, take-profit em spot por software incl. dry_run,
NaN, clamp de saldo alheio e re-armar stop se a venda falhar,
`fetch_spot_holdings` resiliente a falha de ticker, backtest sintético,
**+ 18/07: `trade_closed` no fechamento por stop confirmado/aproximado,
recuperação de `entry_price` via `fetch_order`, persistência on-sight de
proteção backfilled, venda de TP parcialmente preenchida com re-arm do
restante, corrida stop-vs-TP, `protection_state.load()` contra
UnicodeDecodeError**, **+ 19/07: `cancel_all` cobre a categoria `tpslOrder`
em spot (não duplica em perp), `protect_size` cobre fill favorável e ignora
saldo alheio pré-existente, `entry_price` confirma via `fetch_order` antes
de cair no preço do sinal**, **+ 20/07: stop/TP re-ancorados no preço real
do fill (desloca pela mesma distância sinal→fill, preserva a distância de
risco do sizing)**, **+ 21/07 (seções 20-21): should_exit da estratégia,
saída por sinal no engine (executa/prioridade do TP/dry_run/sem profile),
trailing no engine (move/passo mínimo/dry_run/re-arm em falha/exit-now
quando o nível já rompeu/cura de arquivo stale pelo gatilho real), entrada
trailing no executor (proteção sem TP), backtester (saída por sinal on/off,
trailing trava lucro, nunca desce, R:R re-ancorado exato), backfill de
posição trailing, saldo-zero com stop ainda ativo não fabrica
fechamento**, **+ 21/07 (seção 22): persistência do kill switch em disco —
boot sem arquivo prévio, trip/reset sobrevivendo a um "restart" simulado
(RiskManager novo lendo o mesmo arquivo), arquivo corrompido tratado como
não-halted, `state_reader.read_halt_status()` usando o arquivo como fonte
primária em vez de só inferir da trilha**, **+ 21/07 (seção 17b): executor
reconfirma o saldo base antes de declarar `naked_position_close_failed` —
saldo atrasado/racy na 1ª leitura recupera na reconfirmação e arma o stop;
saldo zero confirmado em 2 leituras continua declarando corretamente, sem
inventar proteção**, **+ 21/07 (seção 23): cooldown por símbolo após stops
seguidos — sem histórico aprova normal, 1 stop não aciona, 2º stop aciona e
veta, outro símbolo não afetado, sobrevive a "restart" simulado, TP quebra
a sequência, escalonamento 30→60min no mesmo dia, expira naturalmente,
arquivo corrompido tratado como vazio, feature desligada sem a chave no
YAML**, **+ 21/07 2ª rodada (seção 24, bug #31): `realized_pnl`/
`recent_decisions` não perdem `trade_closed`/eventos raros atrás de ruído
repetitivo, `limit` corta pelos N mais recentes DO TIPO certo (não pelas
últimas linhas cruas)**, **+ 21/07 2ª rodada (seção 25, bug #32):
isolamento de `kill_switch_state.json`/`cooldown_state.json` por env var —
sem override aponta pro arquivo real, com override (subprocesso, mesmo
jeito que os runners de backtest fazem) o `RiskManager` real grava só no
arquivo isolado e o arquivo real fica intocado**, **+ 22/07 (seção 26):
`RestartPolicy`/`backoff_seconds` do `supervisor.py` — janela
deslizante de crashes aprova/recusa restart corretamente, crash fora da
janela some da contagem, backoff exponencial cresce e satura no teto,
`supervisor.py` parseia sem erro de sintaxe**, **+ 22/07 (seção 27,
`BybitDerivativesProvider`/decisão #G — ver "Nova capacidade" no topo do
arquivo pro relato completo da revisão adversarial que gerou boa parte
destes checks): conversão spot→perpétuo, agregação dos 3 endpoints,
isolamento POR CHAMADA dentro de `fetch()` [exceção em um endpoint não
apaga os outros dois já certos], client sem os 3 métodos novos não
quebra, colisão de nome com `DossierOnChainProvider` evitada, parsing
REAL contra respostas no formato do ccxt [não só o client já convertido]
incl. campos `None` não passando como confirmados e histórico vazio sem
`IndexError`, e o GATE em si — zero chamada de rede com
`decision.strategy: deterministic`, chamada real só com o gate aberto**)
CONFIRMADOS 199/199 numa rodada oficial da suíte com o motor parado — **+ 25-26/07
(seção 23 reescrita, cooldown endurecido pra 3 níveis): 1 stop isolado já
aciona (30min), 2º stop do dia escala pra 60min, 3º pra 1440min/24h, TP
zera `consecutive_stops`, reset manual (`reset_cooldown`) libera antes do
prazo e audita `cooldown_reset`, reset sem cooldown ativo é no-op sem
evento fantasma — suíte final 244/244 smoke** — e
`tests/test_ciclo.py` (8 checks: exclusividade por símbolo, limites
intra-ciclo). **+ 27/07/2026 (bugs #33-#41, #44-#45, dia da transição pra
mainnet): 13 checks novos** — isolamento de ambiente no sinal de controle
MCP, campo `environment` em todo evento + breakdown no `realized_pnl`,
rearm mudo corrigido, race de saldo pós-cancelamento espelhada do bug #29,
confirmação de fill=0 explícito, `kill_switch_state`/`cooldown_state`
resolvendo caminho por AMBIENTE (2 checks), liquidação de emergência no
rearm de `_execute_spot_exit` (4 checks: sucesso/falha nos 2 pontos),
`_update_trailing_stop` confirmando o stop real antes de reconciliar como
fechado (3 checks) — **suíte final 257/257 smoke**. `test_ciclo.py` sem
mudança de contagem (8/8), mas com o mesmo fix de isolamento de
`spot_protections.json` (zera pra baseline limpo antes de rodar, não só
restaura no final — bug #45) e do funding rate seguro nos dois clamps
(bug #44). **Total 265/265**, confirmado por mim de forma reproduzível
(motor parado, `.env` real em mainnet) depois de descontaminar os efeitos
colaterais de rodar a auditoria com múltiplos agentes concorrentes (ver
topo do arquivo). Rodar da RAIZ:

```powershell
python tests\test_smoke.py
python tests\test_ciclo.py
```

Ambos fazem backup/restauração automática de `logs/audit.jsonl` e do
`risk_config.yaml` (via atexit); ambos também fazem o mesmo com
`state/spot_protections.json` desde 18/07 (guardado em memória, não em
arquivo-irmão — ver comentário no topo do arquivo; `test_ciclo.py` ganhou
essa proteção em 18/07 porque o arquivo passou a ser escrito com mais
frequência — persistência no primeiro avistamento de toda posição) e com
`state/kill_switch_state.json` e `state/cooldown_state.json` desde 21/07
(mesmo padrão — todo `RiskManager()` novo lê E grava os dois na
inicialização).
**Preferir SEMPRE rodar com o loop parado**: os testes escrevem/restauram a
trilha real, e um `main.py` ao vivo gravando eventos no meio da janela do
teste corre risco de ter esse evento perdido no restore (checado
manualmente em 17/07 e novamente em 18/07 sem perda, mas é sorte, não
garantia — não repetir).

**21/07 (2ª rodada) — RESOLVIDO**: as seções 24 e 25 (bugs #31/#32) foram
escritas com o motor ao vivo, mas confirmadas com uma rodada completa da
suíte (`test_smoke.py` + `test_ciclo.py`) assim que o motor parou —
**173/173 verde**, zero regressão. Ver bug #31/#32 pro relato completo,
incluindo dois achados colaterais da própria verificação (contaminação
pequena e já limpa da trilha; um restart do motor no meio de uma rodada
anterior da suíte, sem perda aparente).

## Operacional

- Pasta sincroniza via OneDrive; `.env` contém chaves de TESTNET (sem saque).
  Antes de mainnet: tirar segredos do OneDrive (variável de ambiente/secrets).
- Não rodar duas instâncias de `main.py` ao mesmo tempo. Atenção: no Windows,
  UM `main.py` via venv aparece como DOIS `python.exe` (o do venv é launcher e
  spawna o interpretador base como filho) — não é instância dupla; confirme
  instâncias reais pela trilha (engine_start sem engine_stop) e pelo pai do
  processo, não pela contagem de processos.
- O engine lê `state/control.json` (halt/reset) — é o único canal de controle
  externo; o MCP só grava esse arquivo, nunca ordem.
- Backup antigo do projeto (pré-correções de 15/07) permanece em
  `G:\Meu Drive\...\bybit-auto-trader` — não editar lá; esta pasta é a canônica.
- Se editar `src/engine.py` ou `src/risk/risk_manager.py` com o loop rodando,
  a mudança só entra em vigor no próximo `engine_start` (Python não recarrega
  módulo em processo já rodando) — pare o loop antes de editar risco, sempre.
- **Mesma regra vale pro `mcp_server.py`** (achado em 21/07, ver "Watchdog
  agendado"/bug #28): editar `src/supervision/state_reader.py` ou qualquer
  módulo que o servidor MCP importa só entra em vigor depois de reiniciar o
  Claude Desktop (é isso que mata e reabre o `mcp_server.py` — não existe
  hoje um jeito de reiniciar só o processo do MCP sem reiniciar o app
  inteiro). Ferramentas do MCP (`trader_halt_status` etc.) podem continuar
  reportando comportamento ANTIGO por horas se isso for esquecido.

## Análise da amostra real de trades (18/08/2026 manhã) — o motor funciona, a estratégia não

> ⚠️ **CORRIGIDO na sessão da NOITE de 18/08 — leia antes de citar qualquer coisa
> daqui.** Três pontos desta seção não sobreviveram à verificação:
> 1. **"Duração mediana 1.336 min (22h)" está ERRADO.** O real é **129 min** no
>    total (71 min daytrade, 1.230 min swing). O número velho sobreviveu da
>    passada com pareamento FIFO bugado, que a própria seção admite ter refeito.
>    Como consequência, a **recomendação #5 ("descasamento de horizonte") cai** —
>    20,5h de duração num perfil de 4h é coerente, não descasado.
> 2. **A recomendação #1 (baixar `tp_rr` para ~0,6–0,75) está REFUTADA.** Medida
>    em walk-forward, ela **piora**: tp 0,75 → −36,90% contra tp 2,0 → −23,29%.
>    Fecha cedo, reentra e multiplica fee. A simulação sobre MFE que sugeria o
>    contrário (a tabela "e se TP fosse X R?") não considerava reentrada nem custo.
> 3. **A recomendação #2 (alargar o stop) está CERTA e agora tem mecanismo:** com
>    o teto de nocional mordendo em 90% dos sinais, `fee/R = 0,11% ÷ stop%`. Foi
>    o que motivou desligar o 15m.
>
> O restante da seção (payoff 1,11 vs 2,58 necessário, MFE mediano 0,65R, 88% de
> fechamentos por stop, PnL líquido ≈ −6,54 USDT) foi reconfirmado. Ver
> "Sessão 18/08/2026 (noite)" e `research/RELATORIO-2026-08-18-pesquisa-3-perp.md`.

Feita a pedido do Lucas ("estudo pra melhorar o PnL"). Amostra: **os 43
`trade_closed` de MAINNET com dinheiro real**, 28/07 → 18/08 (os 11 do PC1
+ os 32 do PC2 — a trilha do PC1 tem os 4 primeiros dias de perp, a do PC2
o resto). Metodologia: cada `trade_closed` pareado com o `order_executed`
imediatamente anterior do mesmo símbolo (one-way mode: nunca há duas
posições abertas no mesmo símbolo — confirmado lendo a trilha crua). R
calculado com o risco REAL do trade (`trail_distance` × tamanho realmente
preenchido), não com o risco teórico do YAML. **Ressalva de método**: uma
primeira passada usou pareamento FIFO e produziu um MFE absurdo (+8,14R) —
era artefato de posições herdadas sem `order_executed` na mesma trilha.
Refeito e conferido contra a trilha crua antes de reportar. Nenhum número
aqui vem de estimativa, exceto a fee (ver abaixo).

### Os números

| Métrica | Valor |
|---|---|
| Trades | 43 (28/07→18/08) |
| PnL bruto (como a trilha reporta) | **−4,29 USDT** |
| Fee estimada (taker 0,055%/lado × 2) | **−2,24 USDT** |
| **PnL líquido real** | **≈ −6,54 USDT** |
| Em R: bruto / líquido | **−12,46R / −21,73R** |
| Win rate | **28%** (12/43) |
| Ganho médio / perda média | +0,78R / −0,70R |
| **Payoff ratio** | **1,11** |
| **Payoff necessário pro break-even** | **2,58** |
| Fechamentos por `stop_loss` | 38/43 (88%) — só 3 por `take_profit` |
| Duração mediana | 1.336 min (**22h**) |
| Stop inicial mediano | **0,58% do preço** |

**A trilha reporta PnL BRUTO — `trade_closed.pnl_usdt` é `(exit−entry)×size`,
sem fee.** Isso não é bug (o campo sempre foi assim), mas significa que todo
número de PnL já reportado neste projeto está otimista. Com nocional médio
de 47 USDT e fee taker de 0,055%/lado, cada trade paga ~0,052 USDT ida+volta
= **22% de 1R**. A fee sozinha responde por ~43% do prejuízo líquido.

### Os quatro achados que explicam o resultado

**1. A matemática não fecha, por larga margem.** Win rate 28% com payoff
1,11 é estruturalmente perdedor: precisaria de payoff **2,58** só pra
empatar (antes da fee). Não é azar nem amostra pequena demais — é o desenho.
Profit factor 0,37.

**2. O sistema entrega 79% dos trades a favor e converte quase nada.** 34
dos 43 trades chegaram a mover o trailing (ou seja: ficaram lucrativos em
algum momento) — e **65% desses fecharam no vermelho**. MFE (máximo
movimento a favor) mediano: **+0,65R**. O mercado dá ~0,65R e tira de volta.
Casos concretos: 17/08 ETH short chegou a +0,80R com 12 movimentos de
trailing e fechou −0,23R; 07/08 ETH short +0,79R (8 movimentos) → −0,21R.

**3. O `tp_rr: 2.0` é inalcançável no comportamento observado.** O MFE
**máximo de toda a amostra foi +1,78R** — nenhum trade em 43 chegou perto de
2R. Por isso só 3 fecharam por `take_profit`. O alvo está fora do alcance do
que este mercado/estratégia entrega, então na prática **todo trade termina
no stop**, e o trailing decide se é um stop pequeno ou um lucro raspado.

**4. Stop dentro do ruído.** Stop mediano de **0,58% do preço** numa posição
que dura **22h de mediana**. A oscilação normal de ETH/BTC em 22h é
múltiplas vezes isso — o stop é atingido por ruído, não por invalidação de
tese. Consequência secundária: stop apertado → nocional grande pro mesmo
risco em USDT → **fee proporcionalmente enorme (22% de 1R)**.

**Achado colateral, novo, não é bug**: o tamanho pedido é truncado pelo
step da exchange (ETH 0,01; BTC 0,001) — na média, **26% menor** que o
calculado pelo `RiskManager` (ex.: pede 0,0486 ETH, preenche 0,04). Erra
pro lado conservador (risco real menor que o planejado), mas distorce o
sizing e piora a fee relativa. Com equity pequeno, o arredondamento é
grosseiro.

### O que os dados sugerem (nenhuma dessas mudanças foi aplicada)

Ordenado por força da evidência. **Nada aqui é mudança de parâmetro de
risco autorizada** — todas exigem decisão explícita do Lucas (regra
inegociável #2).

1. **Baixar `tp_rr` de 2.0 pra ~0,6–0,75.** É a mudança mais direta e mais
   sustentada pelos dados: a mediana do que o mercado oferece é 0,65R e
   22 trades morreram depois de estarem a favor. Um alvo dentro do alcance
   converteria boa parte deles. Testável no backtester antes de ir ao vivo.
2. **Alargar o stop (multiplicador de ATR maior).** Ataca a causa raiz de
   (4) e, de quebra, derruba a fee relativa: stop 3x mais largo = nocional
   3x menor pro mesmo risco em USDT = fee cai de 22% pra ~7% de 1R.
   Contrapartida: menos trades, e cada perda continua valendo 1R.
3. **Trocar entrada a mercado por ordem limit (maker).** A fee é 43% do
   prejuízo. Maker na Bybit é ~0,02% (vs 0,055% taker). Mudança de
   arquitetura no `executor.py`, com risco novo real (ordem que não
   preenche), não é toggle de YAML — projeto próprio.
4. **Reduzir frequência.** 43 trades em 21 dias com edge negativo é
   sangramento por fricção. Menos entradas e mais seletivas.
5. **Descasamento de horizonte**: o perfil `daytrade` produz trades que
   duram 22h de mediana. Ou o perfil vira swing de fato, ou o timeframe de
   decisão precisa ser coerente com o tempo de vida real da posição.

**A conclusão honesta, e ela é maior que qualquer ajuste de parâmetro:**
estes 43 trades reais **confirmam o que a pesquisa já dizia**. As duas
rodadas de walk-forward (`research/RELATORIO-2026-07-16.md` e
`RELATORIO-2026-07-21-pesquisa-2b.md`, datasets independentes) concluíram
que a família EMA20/50+RSI — a que o robô usa — é a **PIOR das 6 testadas**
(mediana WF −3,40% e −29,82%, 0/18 e 0/10 séries positivas). O resultado ao
vivo é exatamente isso, agora com dinheiro real. Os itens 1–5 acima são
otimizações de gestão de saída numa estratégia sem edge comprovado: podem
levar de −0,29R/trade pra perto de zero, dificilmente a lucro consistente.
**O trabalho pesado que o Lucas mencionou é encontrar uma fonte de edge —
não afinar stop e TP.** O caminho já registrado nos "Próximos passos"
(item 3) continua valendo: dado novo, famílias novas, e verificação
adversarial antes de promover qualquer coisa a capital real.

**O que NÃO está quebrado**: o motor. 18 dias de operação contínua, zero
kill switch, zero posição nua, zero falha de fechamento, trailing movendo
105 vezes de verdade, cooldown escalando pelos 3 níveis, supervisor
religando sozinho depois de um crash de console. A engenharia está pronta
pra rodar uma estratégia boa — só não tem uma ainda.
