# CLAUDE.md — Bybit Auto Trader (handoff 2026-07-26, ~19:5x UTC)

Contexto vivo do projeto para agentes (Claude Code/Cowork). Fonte completa de
regras: `INSTRUCOES-PROJETO-v2.md` v2 + `RASCUNHO-instrucoes-v8-colar-manualmente.md`
(v8, 26/07 — atualiza fatos, não regra; ver seção "Status atual" lá; ainda NÃO
colada nas instruções do Claude Project — substitui a v7, colada em 22/07).
Guia operacional humano: `PASSO-A-PASSO.md` (bootstrapping — todas as etapas
fechadas, ver seu próprio aviso de topo). Idioma de trabalho: português do
Brasil. Comentários de código explicam causa raiz.

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

**Decisão do Lucas sobre a arquitetura dos dois PCs, com uma regra nova e
importante para qualquer sessão futura**: o PC novo ("PC2") vai rodar
`supervisor.py --live` 24h/dia, autenticado com uma chave de API de testnet
NOVA e SEPARADA da que este PC (PC1) usa — mas as duas chaves autenticam a
MESMA conta/saldo da testnet Bybit (chave nova ≠ conta nova; não existe
conceito de sub-conta em uso aqui). **Por causa disso, PC1 NUNCA deve rodar
`main.py --live`/`supervisor.py --live` em loop contínuo ao mesmo tempo que o
PC2 estiver rodando** — os dois processos gerenciariam a MESMA posição/saldo
na exchange com estado local (kill switch, cooldown, proteções) inteiramente
independente um do outro, quebrando a garantia de "nunca duas instâncias" que
o projeto já tinha (antes cobria só duas instâncias na MESMA máquina/pasta
OneDrive — agora se estende a duas MÁQUINAS diferentes na mesma conta). PC1
segue livre para `--once` (dry-run, sem `--live`) e pesquisa/backtest — nunca
um loop `--live` contínuo enquanto o PC2 estiver de pé. Pasta do PC2
deliberadamente FORA do OneDrive (decisão do Lucas) — clone local dedicado,
sem sincronização. Guia completo de setup do PC2 entregue ao Lucas no chat
desta sessão (Python/Git/GitHub CLI, clonar o repo, criar `.env` com a chave
nova gerada por ELE na Bybit, validar com `diag_saldo.py`/`--once` antes do
`--live`, deixar o PC sem suspensão, e como puxar atualizações futuras).

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
3. Fases sequenciais: só se avança quando a anterior fechou. Hoje: Fase 1 em
   fechamento. Mainnet (Fase 5) bloqueada por pendência regulatória.
4. Testnet por padrão (`ENVIRONMENT=testnet` no `.env`). DRY_RUN por padrão
   (`--live` desativa). NUNCA preencher chaves de mainnet sem decisão do Lucas.

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

## Watchdog agendado — alerta ativo (novo, 2026-07-21)

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
   do projeto mudar de fase.
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
na marra — confirmado) — ignorar em métricas de sessão. Há 2 eventos
`audit_maintenance`: (21:35Z de 15/07) documentando a remoção dos ~40k eventos
simulados de backtest para `audit-backtest-contaminacao-2026-07-15.jsonl`
(gravados antes do fix #14; nada foi apagado); e (~01:10Z de 22/07,
madrugada — ver bug #31/#32) documentando a remoção de 2 linhas de teste
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
intra-ciclo). **Total 252/252**, confirmado com o motor parado antes do
restart que ligou a feature. Rodar da RAIZ:

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
