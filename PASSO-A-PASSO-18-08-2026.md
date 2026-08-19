# Passo a passo — 3 coisas para você fazer (18/08/2026)

Guia para executar sem precisar entender o código. Tempo total: ~10 minutos.

---

## Antes de começar: respire, nada está em risco agora

**O motor está desligado desde 17:09 (UTC) de hoje.** Isso é seguro:

- Você tem **1 posição aberta** (BTC, comprada a 64.723,20).
- Essa posição tem **stop e take-profit como ordens REAIS lá na Bybit**. Elas
  funcionam com o motor ligado ou desligado — a corretora executa sozinha.
- O que o motor desligado NÃO faz: mover o stop para cima conforme o preço
  sobe (trailing), e registrar o fechamento na trilha de auditoria. Quando você
  religar, ele reconcilia tudo sozinho.

Ou seja: **não há emergência**. Faça na ordem abaixo, com calma.

| # | O quê | Tempo | Urgência |
|---|---|---|---|
| 1 | Religar o motor no PC2 | 2 min | é o que faz o robô voltar a operar |
| 2 | Recuperar um arquivo pelo Dropbox | 3 min | recuperação de histórico |
| 3 | Parar o dossiê de pedir autorização | 2 min | comodidade |

---

# PARTE 1 — Religar o motor (no PC2)

> ⚠️ **Faça isto SOMENTE no PC2** (o computador onde existe a pasta
> `C:\BybitAutoTrader`). Nunca ligue o motor no PC1 (a pasta do Dropbox) ao
> mesmo tempo: os dois usam **a mesma conta da Bybit**, e dois motores mexendo
> na mesma posição é o cenário perigoso que o projeto sempre evitou.

### Passo 1.1 — Abrir o PowerShell

1. Aperte a tecla **Windows** do teclado.
2. Digite `powershell`.
3. Aperte **Enter**.

Vai abrir uma janela preta ou azul-escura com um cursor piscando.

### Passo 1.2 — Ir até a pasta do robô

Digite exatamente a linha abaixo e aperte **Enter**:

```powershell
cd C:\BybitAutoTrader
```

Se der certo, o texto antes do cursor muda para `PS C:\BybitAutoTrader>`.

### Passo 1.3 — Ligar o motor

Digite exatamente esta linha e aperte **Enter**:

```powershell
.venv\Scripts\python.exe supervisor.py --live
```

> 🔴 **Copie essa linha exatamente como está.** Em especial o começo:
> `.venv\Scripts\python.exe`. **Não** digite só `python`. Já aconteceu de usar
> `python` puro aqui e o robô entrar em ciclo de falha 6 vezes seguidas até
> desistir sozinho — porque o `python` puro é outro Python, sem as bibliotecas
> do projeto. O caminho completo evita isso.
>
> O `--live` no final significa **dinheiro real**. É intencional.

### Passo 1.4 — Confirmar que ligou

Em poucos segundos devem começar a aparecer linhas parecidas com estas:

```
2026-08-18 18:20:11,123 | INFO | engine | Ciclo iniciado
2026-08-18 18:20:12,456 | INFO | engine | BTC/USDT:USDT ...
```

**Sinais de que deu certo:**
- ✅ Linhas novas aparecem a cada ~1 minuto, sem parar.
- ✅ Você vê a palavra `INFO` na maioria das linhas.

**Sinais de que deu errado:**
- ❌ Aparece `ModuleNotFoundError` → você digitou `python` em vez do caminho
  completo. Feche a janela, volte ao Passo 1.2 e repita com atenção.
- ❌ A janela fecha sozinha na hora → algo falhou. Me avise e eu investigo.

### Passo 1.5 — DEIXAR A JANELA ABERTA

> 🔴 **Não feche essa janela.** Ela É o robô. Fechar a janela = desligar o robô.
>
> Pode minimizar à vontade. Pode usar o computador normalmente.
> Só não feche, e não deixe o PC suspender/hibernar.

**Quando quiser desligar o robô de propósito:** clique dentro da janela e
aperte **Ctrl + C**. Isso desliga de forma limpa (o robô registra o
desligamento na auditoria). Não use o "X" da janela nem o Gerenciador de
Tarefas — desligar assim fica indistinguível de uma queda, na hora de investigar.

### O que mudou nesta atualização

O robô agora opera **só no perfil de 4 horas (swing)**. O perfil de 15 minutos
(daytrade) foi desligado — ele media −97% nos últimos 12 meses e era metade dos
trades. Você vai notar que o robô abre **bem menos operações** do que antes.
Isso é o esperado, não é defeito.

---

# PARTE 2 — Recuperar o arquivo de histórico (no PC1)

**O que aconteceu:** rodei a suíte de testes e ela destruiu o arquivo de
histórico do PC1 (`logs/audit.jsonl`). Foi um defeito nos próprios testes, que
eu já corrigi — mas o arquivo precisa vir de volta pelo Dropbox.

**O que se perdeu:** o histórico de 28 a 31 de julho do PC1. O histórico do
**PC2 está inteiro** (107 mil linhas), e é ele que vale como registro oficial da
operação desde 31/07. Então isto é recuperação de arquivo antigo, não perda de
dado crítico.

### Opção A — pelo Windows Explorer (mais fácil)

1. Abra o **Explorador de Arquivos** (tecla Windows + E).
2. Navegue até:

```
C:\Users\lucas\Wonder BOAT Dropbox\Lucas Souza\PC\Documents\Projects\Projeto Auto-trader\logs
```

3. Clique com o **botão direito** no arquivo `audit.jsonl`.
4. No menu, procure **Dropbox** → **Histórico de versões**
   (ou *Version history*). O navegador vai abrir.
5. Na lista de versões, escolha uma com data/hora **anterior a
   hoje (18/08) às 14:51**.
6. Clique em **Restaurar**.

### Opção B — pelo site do Dropbox

1. Entre em [dropbox.com](https://dropbox.com) com sua conta.
2. Use a busca e procure por `audit.jsonl`.
3. Escolha o que está dentro de `.../Projeto Auto-trader/logs/`.
4. Clique nos **três pontinhos (…)** → **Histórico de versões**.
5. Escolha uma versão **anterior a 18/08 às 14:51** → **Restaurar**.

### Como saber que deu certo

O arquivo deve voltar a ter alguns **megabytes** de tamanho (hoje ele está com
204 bytes). Clique com o botão direito → Propriedades para conferir o tamanho.

> Se o Dropbox não mostrar versões antigas o suficiente, me avise. O prejuízo é
> limitado (histórico de 4 dias de um PC que não opera mais), e a análise que
> fizemos em cima desses dados já está preservada no relatório.

---

# PARTE 3 — Parar o dossiê de pedir autorização toda vez

**O que acontece hoje:** toda vez que a tarefa do dossiê roda, ela para e pede
sua autorização. Isso porque as permissões estão salvas só dentro da pasta do
projeto, e a tarefa agendada roda de outro lugar — então não encontra nenhuma
permissão pré-aprovada.

> Eu tentei fazer essa alteração sozinho e o sistema **me bloqueou** — com razão:
> eu estaria concedendo permissões a mim mesmo. Por isso precisa ser você.

### Passo 3.1 — Abrir o arquivo

1. Aperte **Windows + R**.
2. Cole isto e aperte **Enter**:

```
notepad C:\Users\lucas\.claude\settings.json
```

O Bloco de Notas abre com um texto curto, parecido com isto:

```json
{
  "agentPushNotifEnabled": true,
  "inputNeededNotifEnabled": true,
  "skipWorkflowUsageWarning": true
}
```

### Passo 3.2 — Substituir todo o conteúdo

1. Aperte **Ctrl + A** (seleciona tudo).
2. Aperte **Delete**.
3. **Cole** o texto abaixo inteiro:

```json
{
  "agentPushNotifEnabled": true,
  "inputNeededNotifEnabled": true,
  "skipWorkflowUsageWarning": true,
  "permissions": {
    "allow": [
      "WebSearch",
      "WebFetch",
      "PushNotification",
      "Read(//c/BybitAutoTrader/**)",
      "Write(//c/BybitAutoTrader/Dossie Cripto/**)",
      "Edit(//c/BybitAutoTrader/Dossie Cripto/**)",
      "Write(//c/BybitAutoTrader/data/**)",
      "Edit(//c/BybitAutoTrader/data/**)"
    ],
    "deny": [
      "Write(//c/BybitAutoTrader/config/**)",
      "Edit(//c/BybitAutoTrader/config/**)",
      "Write(//c/BybitAutoTrader/state/**)",
      "Edit(//c/BybitAutoTrader/state/**)",
      "Write(//c/BybitAutoTrader/logs/**)",
      "Edit(//c/BybitAutoTrader/logs/**)"
    ]
  }
}
```

4. Aperte **Ctrl + S** (salvar) e feche o Bloco de Notas.

### O que esse texto faz, em português

- **`allow`** = o que o dossiê pode fazer sem perguntar: pesquisar na internet,
  e escrever **só** nas pastas do dossiê e de contexto.
- **`deny`** = o que fica **proibido**, mesmo que alguém peça: mexer nas
  configurações de risco, no estado do robô ou na trilha de auditoria. As
  instruções do dossiê já proibiam isso em texto — aqui vira trava de verdade.

### Passo 3.3 — Reiniciar

As permissões só valem em sessões novas. **Feche e abra o Claude Code** (ou o
app) uma vez.

---

## Resumo — marque conforme for fazendo

- [ ] **Parte 1** — motor religado no PC2, janela aberta e minimizada
- [ ] **Parte 2** — `audit.jsonl` restaurado pelo Dropbox (voltou a ter MBs)
- [ ] **Parte 3** — `settings.json` salvo e app reiniciado

Quando terminar, me avise que eu confiro a trilha e confirmo que o motor subiu
limpo, que a posição BTC foi reconciliada e que só o perfil de 4h está ativo.
