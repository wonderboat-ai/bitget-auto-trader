# Passo a passo — fechar a Fase 1 e rodar a Fase 2

Guia operacional, sem pressupor conhecimento de programação. Cada passo diz o que
digitar, o que deve aparecer na tela e o que fazer se não aparecer.

Regra geral: se aparecer texto vermelho (erro), copie a mensagem inteira e cole no
chat do Claude. Não tente "arrumar" mudando arquivos.

> **ATUALIZAÇÃO (23/07/2026): todas as etapas A-E abaixo estão CONCLUÍDAS.**
> Este guia documenta como cada uma foi validada (histórico útil), mas não é
> mais o roteiro do dia a dia — para o estado atual do projeto (o que está
> rodando, decisões em aberto, bugs recentes), leia `CLAUDE.md`, que é
> atualizado a cada sessão de trabalho. Resumo do que fechou depois da última
> atualização deste arquivo (16/07): Etapa B-spot fechou de verdade em 19/07
> (entrada + stop + saída lucrativa automática, tudo confirmado na exchange
> real); Etapa C (backtest/walk-forward) teve mais duas rodadas de pesquisa
> (21/07, 22/07) — o veredito final foi "sem edge, não promover" depois de
> uma verificação adversarial completa; Etapa D (MCP) segue fechada e ganhou
> supervisão adicional (watchdog agendado + restart automático do processo,
> ambos em uso ao vivo desde 22/07); Etapa E (dossiê diário) virou 3x/dia em
> vez de 1x. O motor hoje roda via `python supervisor.py --live` em vez de
> `python main.py --live` direto (religa sozinho se cair por crash).
>
> O conteúdo abaixo (a partir daqui) é a FOTO de 16/07 — mantido como
> registro de como cada etapa foi validada na época, não como instrução
> vigente.

---

## Preparação (toda vez que abrir o computador)

**1. Abrir o terminal na pasta do projeto.**
Abra a pasta `Projeto Auto-trader` no Explorador de Arquivos, clique na barra de
endereço (onde aparece o caminho), digite `powershell` e aperte Enter.
Deve abrir uma janela azul/preta já dentro da pasta certa.

**2. Ligar o ambiente Python do projeto.**
Digite:

```powershell
.venv\Scripts\activate
```

Deve aparecer `(.venv)` no começo da linha. É o sinal de que o ambiente está ativo.
Se der erro falando de "execução de scripts desabilitada", digite antes:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
```

e tente o `activate` de novo.

---

## Etapa A — Paper trading em loop (hoje, sem risco nenhum)

**3. Ligar o robô em modo simulação.**

```powershell
python main.py
```

O que deve aparecer: `Engine iniciando em TESTNET | DRY_RUN=True` e, a cada
~60 segundos, novas linhas (APROVADO, VETO, PULADO ou nada quando não há sinal).
Nenhuma ordem é enviada — é só simulação com dados reais.

**4. Deixar rodando.** Algumas horas, idealmente um dia. Pode minimizar a janela.
Não pode: fechar a janela, desligar o PC, deixar hibernar.

**5. Desligar quando quiser.** Clique na janela e aperte `Ctrl+C`.
Deve aparecer: `Interrompido pelo operador (Ctrl+C). Encerrando.`

**6. Conferir o diário de bordo.** Todas as decisões ficam em `logs\audit.jsonl`.
Não precisa ler na mão: abra o Claude, aponte a pasta do projeto e pergunte
"analisa o audit.jsonl e me diz se o loop rodou limpo". O que interessa:

- `symbol_skipped` — BOM, é a trava de um-símbolo-uma-entrada funcionando.
- `signal_vetoed` — BOM, é o risco vetando; o motivo diz o porquê.
- `cycle_error` ou `symbol_cycle_error` — anotar e mandar no chat.
- `kill_switch_tripped` — o robô se pausou; mandar no chat antes de religar.

**Critério para seguir adiante:** loop rodou horas sem `cycle_error` repetido e
sem kill switch injustificado.

---

## Etapa B — Uma ordem DE VERDADE na testnet (dinheiro de mentira)

Isso testa o único trecho que a simulação não cobre: enviar ordem, colocar o
stop-loss e a proteção contra "posição sem stop". `--live` aqui é seguro porque o
`.env` está com `ENVIRONMENT=testnet` — é a exchange de brinquedo.

**7. Rodar um ciclo real:**

```powershell
python main.py --once --live
```

O que deve aparecer: em vez de `[DRY_RUN]`, linhas `Enviando ordem buy/sell ...`
e `Ordem executada ... (testnet=True)`. Se não houver sinal no momento, pode
terminar sem ordem nenhuma — normal; tente de novo mais tarde.

**8. Conferir na Bybit testnet.** Entre em https://testnet.bybit.com → Derivatives
→ aba **Positions**. Deve existir a posição aberta e, na linha dela, o campo
TP/SL preenchido (o stop). Posição SEM stop = problema grave: copie a tela e
mande no chat.

**9. Fechar a posição de teste.** Na própria testnet, botão **Close** (Market)
na linha da posição. É dinheiro fictício, não custa nada.

**10. Mandar a saída do passo 7 no chat** para conferência contra o log.

**Critério para seguir adiante:** ordem + stop apareceram na exchange e o
`audit.jsonl` registrou `order_executed`.

---

## Etapa B-spot — Uma ordem real no SPOT da testnet (novo caminho, 15/07)

A Bybit bloqueou derivativos para contas do Brasil (não é culpa sua), então a
Etapa B migrou para o mercado À VISTA (spot) — decisão #E. Diferenças: só
compra (nunca venda a descoberto), sem alavancagem, e o robô coloca só o stop
(o alvo de lucro no spot fica para uma fase futura — limitação da exchange).

**B1. Limpar as moedas de brinde.** A testnet dá BTC/ETH grátis, e o robô
trata qualquer moeda sua como "posição já aberta" (proteção). Entre em
https://testnet.bybit.com → aba **Spot** (Trade → Spot) e VENDA para USDT todo
BTC e ETH que aparecer no saldo. Precisa sobrar só USDT.

**B2. Virar a chave para spot.** Abra `config\risk_config.yaml` com o Bloco de
Notas e mude a linha `type: "perp"` para `type: "spot"` (bloco `market:`, no
topo). Salve. (Essa mudança é sua por regra — o robô nunca mexe nesse arquivo.)

**B3. Rodar um ciclo real:**

```powershell
python main.py --once --live
```

O que deve aparecer: `Ordem executada buy ... (testnet=True)`. Sinais de venda
vão aparecer como `VETO ... Spot: short não suportado` — é o esperado, não é
erro. Se aparecer o erro 10024 de novo (compliance), copie e cole aqui — aí
nem o spot da testnet libera e a validação fica para a conta real da Bybit
Brasil.

**B4. Conferir na testnet:** aba Spot → seus ativos devem mostrar a moeda
comprada, e em **Orders** deve existir UMA ordem condicional de venda (o stop,
tipo TP/SL). Não vai existir ordem de alvo de lucro — é assim mesmo no spot.

**B5. Desfazer o teste:** cancele a ordem condicional (Orders → Cancel) e
venda a moeda de volta para USDT. Depois volte `type:` para `"perp"` no YAML
se quiser continuar os soaks no modo antigo, ou deixe `"spot"` se o plano é
seguir no spot.

**B6. Colar a saída do passo B3 aqui no chat** para conferência contra a trilha.

**Critério de sucesso:** compra + stop visíveis no spot da testnet e
`order_executed` na trilha (com `protect_size` um tiquinho menor que o size —
é a taxa cobrada em moeda, está certo).

---

## Etapa C — Backtest e walk-forward (Fase 2)

Valida o processo de teste histórico. Não precisa de chave — usa dados públicos.

**11. Backtest simples** (1–2 minutos):

```powershell
python run_backtest.py --symbol "BTC/USDT:USDT" --timeframe 15m --candles 1500
```

Deve aparecer um relatório com retorno, drawdown, win rate e um **Veredito**.

**12. Walk-forward** (demora alguns minutos — é normal):

```powershell
python run_walkforward.py --symbol "BTC/USDT:USDT" --timeframe 15m --candles 3000
```

**Importante:** veredito "SEM EDGE" ou "EDGE FRACO" é o resultado ESPERADO.
A estratégia atual (EMA+RSI) é um trilho de teste, não uma tese de lucro. O que
está sendo validado é a régua de medição — é ela que vai julgar a estratégia do
Claude na Fase 3. Cole os dois relatórios no chat para leitura conjunta.

---

## Etapa D — Supervisão pelo Claude Desktop (opcional, pode fazer quando quiser)

Permite perguntar em linguagem natural: "como está o PnL?", "por que vetou aquele
short?". É só leitura — não existe comando de abrir/fechar posição por aqui.

> **Atualização 16/07: Etapa D FECHADA.** O registro não foi pelo
> `claude_desktop_config.json` (passos 13–14 abaixo) — você usa Cowork/Claude
> Code, que registra MCP por projeto via `.mcp.json` na raiz da pasta. Esse
> arquivo já existe e aponta pro `.venv` local. Validado ponta a ponta em
> 16/07: `trader_get_status`/`trader_halt_status`/`trader_get_positions`
> responderam com dados reais batendo com a trilha. Os passos 13–14 abaixo
> ficam como referência só se um dia você registrar no Claude Desktop clássico
> também — não é necessário pra continuar usando o supervisor.

**13.** Abra o Claude Desktop → Settings → Developer → **Edit Config**. No arquivo
que abrir (`claude_desktop_config.json`), adicione:

```json
{
  "mcpServers": {
    "wonder_trader": {
      "command": "C:/Users/lucas/OneDrive/Documentos/Claude/Projects/Projeto Auto-trader/.venv/Scripts/python.exe",
      "args": ["C:/Users/lucas/OneDrive/Documentos/Claude/Projects/Projeto Auto-trader/mcp_server.py"]
    }
  }
}
```

(Se o arquivo já tiver um bloco `mcpServers`, adicione só a parte do
`wonder_trader` dentro dele, separada por vírgula do que já existe.)

**14.** Feche e abra o Claude Desktop. Pergunte: *"qual o status do trader?"*.

---

## Etapa E — Automatizar o dossiê diário (pode fazer a qualquer momento)

Gera todo dia, antes da abertura do mercado americano, o dossiê de mercado
(calendário, macro, on-chain, radar de 20 moedas etc.) e grava três coisas:
`Dossie Cripto\Historico\{data}.md` (leitura humana), `Dossie Cripto\importar-no-
dashboard-{data}.json` (mesmo formato que você já usava manualmente) e
`data\context\latest.json` (o que `DossierMacroProvider`/`DossierOnChainProvider`
leem para alimentar a Camada 3 — hoje inerte, porque a Fase 3 ainda está
desligada, mas já fica pronto e com histórico acumulado em `data\context\history.jsonl`).

**15. Preencher a chave da Anthropic.** Abra o `.env` (mesmo arquivo das chaves
da Bybit) e preencha `ANTHROPIC_API_KEY=` com uma chave gerada em
console.anthropic.com. Sem isso o passo 16 falha com uma mensagem clara
("ANTHROPIC_API_KEY ausente") em vez de travar sem explicação.

**16. Testar uma vez na mão antes de agendar:**

```powershell
python dossier_fetch.py
```

Deve aparecer `Dossiê de AAAA-MM-DD salvo (Historico/, importar-no-dashboard,
data/context/).` e os três arquivos devem existir nas pastas acima. Se aparecer
`Falha no dossiê`, copie a mensagem inteira e cole no chat do Claude — não tente
adivinhar o conserto.

**17. Agendar no Windows Task Scheduler** (roda sozinho todo dia, mesmo com o
terminal fechado — só precisa o computador ligado). Ainda na janela do
PowerShell dentro da pasta do projeto:

```powershell
$venvPython = (Resolve-Path ".venv\Scripts\python.exe").Path
$script = (Resolve-Path "dossier_fetch.py").Path
$action = New-ScheduledTaskAction -Execute $venvPython -Argument "`"$script`"" -WorkingDirectory (Get-Location)
$trigger = New-ScheduledTaskTrigger -Daily -At 7:00AM
Register-ScheduledTask -TaskName "AutoTrade-DossieDiario" -Action $action -Trigger $trigger -Description "Dossie cripto diario para o Auto-Trade"
```

07:00 dá margem antes da abertura americana (9h30 ET ≈ 10h30 de Brasília) e antes
dos indicadores econômicos do dia, que costumam sair nesse horário. Pode ajustar
o `-At` para o horário que preferir.

**18. Conferir se o agendamento pegou:**

```powershell
Get-ScheduledTask -TaskName "AutoTrade-DossieDiario"
```

Deve aparecer `State: Ready`. Para rodar manualmente e testar o agendamento sem
esperar até amanhã: `Start-ScheduledTask -TaskName "AutoTrade-DossieDiario"`.
Para desligar: `Disable-ScheduledTask -TaskName "AutoTrade-DossieDiario"`.

**Critério para seguir adiante:** rodou uma vez na mão (passo 16) sem erro, e
`Get-ScheduledTask` mostra `Ready`.

Esta etapa é independente das A–D — pode fazer antes, durante ou depois delas.

---

## O que NÃO fazer nesta fase

- Não mudar `config\risk_config.yaml` sem decidir conscientemente — é o coração
  do sistema. Mudança lá é sempre manual e deliberada, nunca "para testar".
- Não preencher as chaves de MAINNET no `.env`. Fase 5 está bloqueada até
  resolver a situação regulatória da Bybit para residentes no Brasil.
- Não rodar duas cópias do `main.py` ao mesmo tempo.

## Ordem das etapas

A (loop simulado) → B (ordem real na testnet) → C (backtest/walk-forward) →
D (a qualquer momento). Só se avança quando a etapa anterior fechou limpa.
E (dossiê diário) é independente — não bloqueia nem depende de A–D.
