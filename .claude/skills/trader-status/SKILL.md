---
name: trader-status
description: >
  Use sempre que o usuário disser "trader status" (ou variações próximas como
  "status do trader", "como está o motor", "status do bot") no contexto do
  projeto Bitget Auto Trader (C:\BitgetAutoTrader). Este é o comando-padrão de
  checagem do motor de trading real — trate como o gatilho principal, mesmo
  que a frase venha sozinha e sem mais contexto. Confere se o motor de
  trading ao vivo (supervisor.py --live) está rodando; se estiver DESLIGADO,
  informa isso e entrega o comando exato pra ligar — NUNCA liga sozinho,
  mesmo executando sem supervisão direta no momento, porque `--live` move
  dinheiro real e essa decisão é sempre do usuário, no momento em que ele
  decide. Se estiver LIGADO, reporta status completo (equity, posições
  abertas, kill switch, cooldown, resumo do histórico de trades/PnL) e arma
  um monitor em tempo real observando a trilha de auditoria pra entradas,
  saídas, PnL, movimentos de trailing stop e erros.
---

# trader status

Automação de checagem do motor de trading da Bitget. Existe pra responder
uma pergunta que se repete todo dia sem o usuário ter que descrever de novo o
que quer saber — e pra manter uma linha vermelha que nenhuma automação deste
projeto pode cruzar: **iniciar `--live` é sempre um ato humano, no momento em
que acontece.**

`ROOT = C:\BitgetAutoTrader`

## Por que a linha vermelha existe

Ligar o motor em `--live` é o que faz o sistema começar a abrir posições com
dinheiro real, sem confirmação por trade. Um pedido de "toda vez que eu disser
X, ligue o motor se estiver desligado" parece razoável na hora em que é dado —
mas essa automação sobrevive à conversa: uma sessão futura, meses depois, sem
ninguém olhando o mercado naquele instante, veria "motor desligado" e ligaria
sozinha. Isso é diferente de responder um pedido pontual ("pode ligar agora") —
é abrir mão da confirmação humana justamente no momento em que ela mais
importa. Por isso este ramo do fluxo NUNCA inicia o `--live`; sempre devolve o
comando pra o usuário rodar ele mesmo.

## Passo 1 — o motor está rodando?

Confirme pela árvore de processos, não só pela trilha (a trilha pode estar
desatualizada se o processo morreu sem auditar `engine_stop`):

```powershell
Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Where-Object { $_.CommandLine -like '*supervisor.py*' -or $_.CommandLine -like '*main.py*' } | Select-Object ProcessId, ParentProcessId, CommandLine, CreationDate
```

Uma árvore saudável mostra 4 processos (2 por nível — o do venv é lançador e
spawna o interpretador base como filho; isso é normal no Windows, não é
instância duplicada): `supervisor.py --live` (x2) → `main.py --interval 60
--live` (x2). Zero resultados = motor desligado.

Cheque também o fim de `logs\audit.jsonl` pra saber COMO ele chegou nesse
estado: `engine_stop` como último evento é parada limpa e deliberada;
ausência de `engine_stop` depois do último `engine_start` sugere crash ou
`taskkill` forçado — vale mencionar essa diferença no relatório, não só
"está desligado".

## Passo 2A — se estiver DESLIGADO

Informe isso claramente e entregue o comando exato, num bloco de código
próprio (o usuário roda num terminal PowerShell aberto por ele mesmo, não em
background por você — é isso que garante um console real e um Ctrl+C
confiável depois):

```powershell
C:\BitgetAutoTrader\.venv\Scripts\python.exe C:\BitgetAutoTrader\supervisor.py --live
```

Explique em uma frase por que você não roda esse comando por conta própria
(a mesma razão da seção acima) e pare por aí — não ofereça alternativas que
contornem isso.

## Passo 2B — se estiver LIGADO

### Status completo

Reúna e apresente, nessa ordem:

1. **Desde quando** — `engine_start` mais recente na trilha, ambiente
   (`mainnet`/testnet — hoje só existe mainnet nesta exchange), `dry_run`.
2. **Kill switch** — `state\kill_switch_state.json` (`halted`/`reason`).
3. **Cooldown** — `state\cooldown_state.json` (símbolos pausados e até
   quando, se houver).
4. **Conta real** — equity e posições abertas, lidos direto da exchange
   (nunca confie em cache/arquivo local pra isto):
   ```python
   import config.settings as s
   from src.exchange.bitget_client import BitgetClient
   c = BitgetClient(s.get_bitget_credentials())
   print(c.fetch_balance_usdt())
   print(c.fetch_open_positions())
   ```
5. **Eventos críticos desde o último `engine_start`** — varra
   `logs\audit.jsonl` por `kill_switch_tripped`, `naked_position_close`,
   `naked_position_close_failed`, `symbol_cycle_error`, `cycle_error`,
   `engine_crash_restart`, `engine_supervisor_giveup`,
   `portfolio_state_read_failed`, `protection_reanchor_failed`,
   `tpsl_ambigua`, `position_notional_unresolved`,
   `equity_zero_confirmado`. Zero é bom sinal — diga isso explicitamente,
   não deixe a ausência de menção parecer que você não checou.
6. **Resumo do histórico de trades** — percorra `logs\audit.jsonl` inteiro
   (não só desde o boot atual) por eventos `trade_closed`: quantos, quantos
   `take_profit` vs `stop_loss` vs `external_close_unconfirmed`, soma de
   `pnl_usdt` (ignorando `null`), win rate. Se a trilha for nova/vazia (comum
   logo após ligar pela primeira vez), diga isso em vez de reportar "0 trades"
   como se fosse um resultado.

Reporte isso num formato direto (tabela ou lista curta) — não precisa de
prosa longa pra cada item.

### Arma o monitor em tempo real

Depois do relatório, inicie um monitor persistente observando a trilha ao
vivo. Cada linha nova que casar com os eventos abaixo vira uma notificação —
é a parte "entradas, saídas, PnL, trailing stop, erros" do pedido:

```
Monitor({
  command: "tail -f -n 0 'C:/BitgetAutoTrader/logs/audit.jsonl' | grep --line-buffered -E '\"event\": \"(order_executed|trade_closed|trailing_stop_moved|cooldown_triggered|cooldown_reset|kill_switch_tripped|kill_switch_reset|naked_position_close|naked_position_close_failed|symbol_cycle_error|cycle_error|engine_crash_restart|engine_supervisor_giveup|portfolio_state_read_failed|protection_reanchor_failed|tpsl_ambigua|position_notional_unresolved|equity_zero_confirmado|engine_stop)\"'",
  description: "trilha Bitget: entradas/saídas/PnL/trailing/erros",
  persistent: true
})
```

Note o que este filtro deliberadamente OMITE: `signal_vetoed`/`signal_approved`
de rotina (ruído — a cada ~60s, todo ciclo produz um desses por símbolo) e
`engine_start` (você já confirmou isso no passo 1). Se algum desses vier a
faltar da lista acima num achado futuro, adicione — a lição deste projeto
(documentada extensivamente no `CLAUDE.md`) é que um filtro estreito demais
fica mudo justamente no caso que mais importa pegar.

**Isto sozinho não basta.** Um monitor que só reage a PALAVRAS específicas
fica em silêncio se o motor inteiro morrer sem gerar nenhuma linha nova — e
silêncio é indistinguível de "tudo bem" pra quem só olha o monitor. Complete
com uma verificação de ausência de batimento: agende um `ScheduleWakeup` de
~20-30 min que relê a trilha inteira desde a última checagem e confirma que
ela cresceu (o motor faz um ciclo a cada ~60s; várias dezenas de minutos sem
NENHUMA linha nova, nem `signal_vetoed`, é sinal de motor morto, não de
mercado parado).

## Notas

- Isto é leitura pura até o Passo 2B/monitor — nada aqui cria, cancela ou
  modifica ordem.
- Se o usuário pedir "trader status" de novo na MESMA sessão e o monitor já
  estiver armado, não duplique — apenas refaça o relatório de status e
  confirme que o monitor anterior segue de pé.
