Sistema de decisão assistida por IA com execução automatizada e supervisão humana, para day trade + swing trade de cripto na Bitget (perpétuos, conta UTA). Full-auto com guardrails, direto em mainnet — a Bitget não tem testnet via ccxt, então validação de size mínimo é a rede de segurança, não uma fase separada.

Princípio de design (a causa raiz): separação rígida entre quem decide direção e quem controla risco e executa. O LLM (Claude) nunca toca na ordem diretamente — produz um sinal estruturado (direção, convicção 0–1, racional, nível de invalidação). Um motor determinístico em Python recebe esse sinal, valida contra regras de risco hard-coded, e só então executa via CCXT. Sinal que viola qualquer guardrail é descartado silenciosamente — sem "negociar" com o modelo.

As seis camadas:
1. Ingestão de dados — mercado em tempo real, macro (calendário, DXY, juros), on-chain, indicadores técnicos calculados localmente (nunca pelo modelo).
2. Feature engineering — snapshot de estado normalizado e versionado; mesma estrutura no live e no backtest.
3. Camada de decisão (Claude) — sintetiza macro + on-chain + técnico num sinal estruturado; daytrade e swing como perfis separados, pesos diferentes.
4. Camada de risco — o coração do sistema, poder de veto absoluto: risco fixo por trade (nunca calculado pelo LLM), sizing derivado do stop, stop-loss obrigatório, kill switch por drawdown, limites de posição/exposição/alavancagem, circuit breakers em condição anômala.
5. Execução — CCXT/Bitget, conta UTA, stop e take-profit como uma única ordem anexada à entrada (sem OCO manual, sem ordem irmã órfã), trailing por modificação atômica. Ordens idempotentes, reconciliação a cada ciclo com a corretora como fonte da verdade, retry com backoff.
6. Supervisão — MCP read-only pra conversar com o sistema rodando ("qual o PnL hoje? por que entrou nesse short?"), mais log estruturado de toda decisão pra auditoria.

Onde "full-auto" precisa do Lucas por cima, mesmo com o sistema rodando sozinho: o kill switch manual, a aprovação de mudança de parâmetro de risco (o sistema não reescreve os próprios limites), e o gatilho de ligar o motor com dinheiro real — nenhum agente ou automação inicia isso por conta própria, nunca.

Status do dia a dia, decisões tomadas e pendências abertas ficam nas Instruções do Projeto — esta descrição é a visão estável do que o sistema É por design, não muda com frequência.
