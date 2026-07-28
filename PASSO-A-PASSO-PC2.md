# PASSO A PASSO — rodar o motor 24h num segundo PC

Criado em 25/07/2026. Objetivo: o PC NOVO ("PC2") roda o motor de trading
sozinho, 24 horas por dia, testnet, enquanto este PC ("PC1") fica livre para
desenvolvimento/upgrades sem interferir no que está rodando ao vivo.

Repositório do código (privado): https://github.com/wonderboat-ai/bybit-auto-trader

## Como funciona a separação de contas — leia antes de tudo

O PC2 vai usar uma **conta de testnet separada** da que este PC (PC1) usa —
não é só uma chave nova, é um **cadastro novo** mesmo (e-mail diferente em
testnet.bybit.com). Isso significa que o saldo e as posições do PC2 ficam
**completamente independentes** dos deste PC: cada motor só enxerga e
gerencia a própria conta.

Na prática, isso elimina o risco que existiria se os dois PCs
compartilhassem a mesma conta (os dois motores tentando gerenciar a mesma
posição ao mesmo tempo, cada um com seu próprio kill switch/cooldown local).
Com contas separadas:

- **PC2** = roda `python supervisor.py --live` continuamente, 24h, na
  conta dele.
- **PC1** (este PC) = fica livre para desenvolvimento e testes — inclusive
  com `--live` pontual, se precisar — sem nenhum risco pra operação do
  PC2, porque são contas diferentes.

Mesmo assim, é bom hábito não deixar um `--live` esquecido rodando aqui por
longos períodos sem acompanhar — não por risco de conflito com o PC2, mas
porque é dinheiro (de teste) sendo movimentado sem supervisão.

## O que você vai precisar

- O PC novo, com Windows, ligado na internet.
- Uns 30–40 minutos.
- Sua conta do GitHub (a mesma que já foi usada para criar o repositório —
  usuário `wonderboat-ai`).
- Um e-mail que você ainda não usou em testnet.bybit.com, para cadastrar a
  conta nova do PC2 (pode ser um alias/"+" do seu e-mail atual, se o seu
  provedor suportar, ou outro e-mail que você tenha).

Todos os comandos abaixo são para o **PowerShell** do Windows (o programa
"Windows PowerShell", vem instalado por padrão — procure no menu Iniciar).

---

## Passo 1 — Instalar o Python

1. No PC novo, abra o navegador e vá em: https://www.python.org/downloads/
2. Clique no botão amarelo "Download Python 3.x.x" (a versão mais recente).
3. Rode o instalador baixado.
4. **MUITO IMPORTANTE**: na primeira tela do instalador, marque a caixinha
   **"Add python.exe to PATH"** (fica embaixo, antes do botão instalar).
5. Clique em "Install Now" e espere terminar.
6. Feche e abra o PowerShell de novo (precisa reabrir para reconhecer o
   Python). Digite para confirmar:

```powershell
python --version
```

Deve aparecer algo como `Python 3.12.x`. Se aparecer erro "não é
reconhecido", o PATH não foi marcado — reinstale repetindo o passo 4.

## Passo 2 — Instalar o Git

1. Vá em: https://git-scm.com/download/win
2. Baixe e rode o instalador.
3. Pode ir clicando "Next" em tudo (as opções padrão servem).
4. Feche e abra o PowerShell de novo. Confirme:

```powershell
git --version
```

## Passo 3 — Instalar o GitHub CLI e entrar na conta

Isso vai permitir baixar o código do repositório privado sem complicação.

1. Vá em: https://cli.github.com/ e baixe o instalador do Windows (ou, se
   preferir, abra o PowerShell e rode: `winget install --id GitHub.cli`).
2. Depois de instalar, feche e abra o PowerShell de novo. Rode:

```powershell
gh auth login
```

3. Responda as perguntas que aparecerem, nesta ordem:
   - "What account do you want to log into?" → **GitHub.com**
   - "What is your preferred protocol...?" → **HTTPS**
   - "Authenticate Git with your GitHub credentials?" → **Yes**
   - "How would you like to authenticate?" → **Login with a web browser**
4. Ele vai mostrar um código de 8 caracteres e abrir o navegador sozinho
   (se não abrir, copie o link mostrado e cole no navegador). Faça login
   com a MESMA conta do GitHub que já é dona do repositório
   (`wonderboat-ai`) e cole o código quando pedir.
5. Volte pro PowerShell — deve aparecer "Logged in as wonderboat-ai".

## Passo 4 — Baixar (clonar) o código

Vamos colocar o projeto direto na raiz do disco C:, **fora de qualquer
pasta do OneDrive** (nem Documentos, nem Área de Trabalho, se essas
pastas estiverem configuradas para sincronizar no PC novo).

```powershell
cd C:\
gh repo clone wonderboat-ai/bybit-auto-trader BybitAutoTrader
cd C:\BybitAutoTrader
```

Confira que os arquivos apareceram:

```powershell
dir
```

## Passo 5 — Criar o ambiente virtual e instalar as dependências

```powershell
cd C:\BybitAutoTrader
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

Quando o ambiente virtual está ativo, o início da linha do PowerShell
mostra `(.venv)`. **Sempre que for usar comandos `python` neste projeto,
confira que está com `(.venv)` ativo** — se fechar e abrir o PowerShell de
novo, tem que rodar `.venv\Scripts\activate` de novo antes.

Se aparecer erro de certificado/SSL durante o `pip install` (comum se o PC
tiver Avast ou outro antivírus que inspeciona HTTPS), rode isto e tente de
novo:

```powershell
pip install pip-system-certs
```

## Passo 6 — Criar uma conta de testnet separada e gerar a chave de API

Esta parte é só sua — eu não tenho como fazer por você (conta e chave de
API são credenciais, é você quem precisa criar).

1. No PC novo, abra uma janela **anônima/privada** do navegador
   (Ctrl+Shift+N no Chrome/Edge) — assim você não usa por engano a sessão
   já logada da sua conta atual.
2. Vá em https://testnet.bybit.com e cadastre uma conta **nova**, com um
   e-mail diferente do que você já usa lá.
3. Confirme o cadastro (verificação por e-mail, se pedir) e faça login na
   conta nova.
4. Vá em Gerenciamento de API (API Management / ícone de perfil → API).
5. Crie uma chave (dê um nome que ajude a lembrar depois, tipo
   `PC2-motor-24h`).
6. Permissões: marque **leitura e negociação** (Read-Write + Trade) — sem
   isso o motor não consegue colocar ordem nem stop. **Nunca** habilite
   permissão de saque (Withdraw) — não precisa e não é seguro.
7. Copie a **API Key** e o **API Secret** mostrados na tela (o Secret só
   aparece uma vez — guarde antes de fechar a tela).

A testnet costuma dar um saldo de brinde automaticamente pra conta nova —
você confirma isso no Passo 8, com `diag_saldo.py`.

## Passo 7 — Criar o arquivo `.env` com a chave nova

Ainda no PowerShell, dentro de `C:\BybitAutoTrader`:

```powershell
copy .env.example .env
notepad .env
```

O Bloco de Notas vai abrir. Preencha assim (cole a Key e o Secret que você
copiou no passo 6):

```
ENVIRONMENT=testnet
BYBIT_TESTNET_API_KEY=cole_a_key_aqui
BYBIT_TESTNET_API_SECRET=cole_o_secret_aqui
BYBIT_MAINNET_API_KEY=
BYBIT_MAINNET_API_SECRET=
ANTHROPIC_API_KEY=
LOG_LEVEL=INFO
```

Salve (Ctrl+S) e feche o Bloco de Notas.

## Passo 8 — Testar ANTES de ligar de vez

Nunca pule esta parte. Ainda com `(.venv)` ativo:

```powershell
python diag_saldo.py
```

Isso deve mostrar o saldo da conta testnet sem erro — confirma que a chave
nova está funcionando. Se der erro, revise o `.env` (Key/Secret colados
certos, sem espaço sobrando).

Depois, rode um ciclo de teste SEM mandar ordem real:

```powershell
python main.py --once
```

Isso roda uma vez só, em modo seguro (não manda ordem nenhuma). Confira que
não deu erro no final.

## Passo 9 — Deixar o PC sem suspender/dormir

Como o motor vai ficar rodando 24h, o PC não pode dormir sozinho:

1. Menu Iniciar → Configurações → Sistema → Energia e bateria.
2. Em "Suspensão de tela e do dispositivo" (ou "Tela e suspensão"), mude
   tudo para **Nunca** (tanto na tela quanto no modo suspensão do PC).

Se for notebook, faça isso também para o modo "com bateria", não só
"conectado na tomada" — ou simplesmente deixe sempre no carregador.

## Passo 10 — Ligar de vez, 24h

```powershell
cd C:\BybitAutoTrader
.venv\Scripts\activate
python supervisor.py --live
```

Isso é o comando definitivo: roda o motor de verdade (ordens reais na
testnet) e se o processo cair sozinho por algum motivo, o `supervisor.py`
religa automaticamente. **Deixe essa janela do PowerShell aberta** (pode
minimizar, não pode fechar) — é nela que o motor está rodando.

## Como parar com segurança

Clique na janela do PowerShell onde o motor está rodando e aperte
**Ctrl+C uma vez só**. Isso avisa o motor para fechar de forma limpa
(ele termina o que está fazendo e registra o encerramento). Nunca feche a
janela no X nem mate o processo pelo Gerenciador de Tarefas — isso conta
como queda/crash, não como parada de propósito.

## Como atualizar o código do PC2 no futuro

Quando eu (Claude, aqui no PC1) terminar e testar alguma melhoria, eu vou
mandar (`git push`) pro mesmo repositório. Para trazer essa atualização
pro PC2:

1. Pare o motor com segurança (Ctrl+C, como acima) — **nunca** atualize o
   código com o motor rodando.
2. No PowerShell, dentro de `C:\BybitAutoTrader`:

```powershell
git pull
```

3. Religue: `python supervisor.py --live` de novo.

---

## Resumo rápido de comandos (depois que tudo já estiver instalado)

```powershell
cd C:\BybitAutoTrader
.venv\Scripts\activate
python supervisor.py --live
```

Para parar: Ctrl+C na mesma janela.

## Problemas comuns

- **"python não é reconhecido como comando"** → o Python foi instalado sem
  marcar "Add to PATH". Reinstale marcando a caixinha (Passo 1).
- **Erro de certificado/SSL no `pip install` ou ao rodar o motor** → rode
  `pip install pip-system-certs` dentro do ambiente virtual ativo e tente
  de novo (acontece com antivírus tipo Avast que inspeciona HTTPS).
- **`gh repo clone` pede senha e não aceita** → provavelmente o
  `gh auth login` do Passo 3 não terminou certo. Rode `gh auth status`
  para conferir se está logado; se não estiver, repita o Passo 3.
- **Motor não abre posição nenhuma depois de horas rodando** → não é bug
  na maioria das vezes — pode simplesmente não ter tido sinal de entrada
  ainda. Isso é esperado.
