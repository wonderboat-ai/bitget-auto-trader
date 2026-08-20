# Projeto Bitget Auto-Trader — Instruções de Projeto (v1 — 2026-08-20)

Documento de referência para qualquer chat/agente que trabalhe neste projeto.
Se um passo proposto violar alguma regra aqui, o passo está errado — não a
regra. É a primeira versão deste documento nesta pasta (clone do projeto
`bybit-auto-trader`, cujas instruções chegaram até a v12 — ver
`INSTRUCOES-PROJETO-v2.md`/histórico se precisar do contexto completo da
migração). Detalhe minuto a minuto vive em `CLAUDE.md`, que muda mais rápido
do que este documento deveria.

## Status atual (fatos verificados em 2026-08-20)

- **O port do código Bybit → Bitget está CONCLUÍDO.** `src/exchange/bitget_client.py`
  substitui o client antigo; `engine.py`/`executor.py` adaptados pro modelo
  de proteção da Bitget; suíte de testes reescrita — **188/188 verde**.
- **A conta é UTA (Unified Account)** — a API clássica da Bitget é bloqueada
  nela; tudo fala v3/UTA. **Stop e take-profit são UMA ordem só** (`tpsl`,
  criada anexada à entrada) — não existe "ordem irmã órfã" nesta exchange,
  ao contrário da Bybit. **Trailing é atômico** (uma chamada, `move_stop_loss`)
  — sem a janela sem proteção que o cancelar+recriar da Bybit exigia.
- **A Bitget não tem testnet via ccxt** (`urls['test']` é `None`) — decisão
  do Lucas, confirmada tecnicamente: operar direto em mainnet, dinheiro real
  desde a primeira ordem. `get_bitget_credentials()` recusa qualquer
  `ENVIRONMENT` diferente de `mainnet`.
- **Motor já ligou `--live` uma vez** (20/08/2026, ~16min, mainnet), rodou
  limpo, zero trades (perfil swing/4h não gerou sinal na janela), parado a
  pedido do Lucas de forma limpa (`engine_stop`/manual auditado, zero eventos
  críticos). **Motor PARADO no momento.**
- **A estratégia é a MESMA usada por último na Bybit, sem alteração** —
  decisão explícita do Lucas. `config/risk_config.yaml` não foi tocado no
  port: determinística (sem LLM), perp, alavancagem 2x, teto de capital 50%
  do equity por trade, cooldown 30/60/1440min, só perfil `swing` (4h) ativo.
  **Isso é uma decisão consciente, não uma omissão**: na Bybit, 22 dias e 53
  trades reais terminaram com a fee acumulada MAIOR que o lucro bruto
  (+2,59 bruto / −0,36 líquido), e um painel adversarial de 9 agentes (18/08)
  concluiu que esta família de estratégia não tem edge validado. Migrar de
  exchange resolve o bloqueio de KYC da Bybit; não resolve isso — e a fee da
  Bitget é ligeiramente maior (0,06% vs 0,055%).
- **Skill `.claude/skills/trader-status/SKILL.md`** cobre o comando "trader
  status": reporta estado completo e arma monitor em tempo real quando o
  motor está ligado; quando está desligado, entrega o comando exato pro
  Lucas rodar — **nunca liga o motor sozinha**, mesmo sendo automação.

## 1. Objetivo do projeto

Sistema de trading automatizado com execução full-auto sob guardrails de
risco e supervisão humana, para perpétuos cripto (hoje BTC/USDT, ETH/USDT) na
Bitget. Full-auto não significa "sem operador": kill switch manual, mudança
de parâmetro de risco e o gatilho de ligar `--live` continuam decisões
humanas, sempre.

## 2. Princípio de design — inegociável

Separação rígida entre quem decide direção e quem controla risco e executa.
O LLM (Claude, Fase 3 — hoje desligada) nunca toca na ordem diretamente:
produz um `Signal` estruturado (direção, convicção, stop, racional). Um
motor determinístico em Python recebe esse sinal, valida contra regras de
risco hard-coded, e só então executa via CCXT. Sinal que viola qualquer
guardrail é descartado — sem negociar com o modelo, nunca.

## 3. Arquitetura — o que mudou de fato na Bitget (vs. Bybit)

| | Bybit | Bitget |
|---|---|---|
| Conta | v5, clássica | UTA (v3) |
| Stop + TP | duas ordens separadas, sem OCO nativo | **uma ordem só** (`tpsl`), anexada à entrada |
| Ordem irmã órfã | risco real (bug #49) | **não existe** — não há irmã |
| Trailing | cancelar + recriar + re-armar em falha | **`move_stop_loss`, uma chamada atômica** |
| Testnet | sim, usada por padrão até 27/07 | **não existe via ccxt** |
| Passphrase | não tem | **obrigatória**, escolhida na criação da chave, não recuperável |

O resto (6 camadas — ingestão de dados, snapshot, decisão, risco, execução,
supervisão MCP) é idêntico em filosofia ao projeto original. Ver
`README.md` pro diagrama e detalhe de cada camada.

## 4. Papel do MCP — só camada de supervisão, só leitura

Nenhuma tool do MCP abre, fecha ou modifica ordem. As únicas ações de
controle (`trader_request_halt`/`trader_request_reset`) gravam um sinal em
`state/control.json` que o engine lê e aplica no próprio ciclo — o MCP nunca
fala direto com o processo do engine nem com a exchange para executar.

## 5. Checklist de segurança de chaves (Bitget)

- Chave com permissão de **leitura + trade de contratos**. NUNCA saque.
- A **passphrase** escolhida na criação não é recuperável — perdê-la exige
  gerar chave nova.
- `.env` nunca commitado (`.gitignore` cobre `.env`); `.env.example` só com
  placeholders.
- `ENVIRONMENT=mainnet` é o único valor aceito — não existe testnet pra
  "testar seguro" aqui. Validação com size mínimo é a rede de segurança.

## 6. O que permanece sob controle humano mesmo em full-auto

- **Ligar `--live` é sempre ação do Lucas, no momento em que decide.** Nenhum
  agente, nenhuma skill, nenhuma automação agendada inicia trading real por
  conta própria — nem quando o pedido de construir essa automação vem do
  próprio Lucas. A skill `trader-status` encarna essa regra: informa e
  entrega o comando, nunca executa.
- Kill switch: reset sempre manual, nunca automático.
- Mudança de parâmetro de risco (`config/risk_config.yaml`): sempre decisão
  explícita e nomeada do Lucas, nunca ajuste silencioso de um agente.
- Parar o motor (diferente de ligar) não move dinheiro — é seguro fazer
  quando pedido, via `CTRL_C_EVENT` real (nunca `taskkill /F`, que deixa a
  trilha sem `engine_stop` e parece crash numa auditoria futura).

## 7. Pendências e decisões em aberto

1. **Estratégia sem edge validado** — decisão consciente de operar mesmo
   assim (ver "Status atual"). Se isso mudar, é decisão do Lucas, não
   iniciativa de um agente.
2. **Sem supervisão 24h fora de sessão** — diferente do estágio final da
   Bybit (PC2 + watchdog agendado), esta pasta hoje só tem supervisão
   dentro de sessões ativas (skill `trader-status` + Monitor + checagem
   periódica). Replicar a infra de PC2/watchdog é trabalho futuro, não
   feito ainda.
3. **`research/` (backtester/data_loader) não foi portado** — ainda busca
   dados históricos públicos da Bybit, não da Bitget. Separado do client de
   trading real; não bloqueia operação ao vivo, mas backtest novo precisaria
   desse ajuste primeiro.
