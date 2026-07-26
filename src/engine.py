"""Loop principal — integra dados -> estratégia -> risco -> execução.

Fluxo de cada ciclo:
  1. Reconcilia estado da conta a partir da EXCHANGE (fonte da verdade).
  2. Avalia saúde do portfólio (drawdown / kill switch).
  3. Para cada símbolo/perfil: monta snapshot, gera sinal, valida no risco, executa.

Fase 1: estratégia determinística + DRY_RUN por padrão. Trocar para execução real
e plugar o Claude na geração de sinal são passos posteriores e deliberados.
"""
from __future__ import annotations

import math
import time
from datetime import datetime, timezone

from config.settings import (
    get_credentials,
    get_environment,
    get_log_level,
    get_market_type,
    load_risk_config,
)
from src.context.providers import (
    BybitDerivativesProvider,
    ContextAggregator,
    DossierMacroProvider,
    DossierOnChainProvider,
)
from src.data.market_data import build_snapshot
from src.exchange.bybit_client import SPOT_DUST_USDT, BybitClient
from src.execution import protection_state
from src.execution.executor import Executor
from src.logger import audit, get_logger
from src.risk.risk_manager import PortfolioState, RiskManager
from src.strategy.deterministic import DeterministicStrategy, StrategyParams
from src.strategy.signal import TRAIL_MIN_STEP_PCT

log = get_logger("engine", get_log_level())


class Engine:
    def __init__(self, dry_run: bool = True) -> None:
        # Guardado aqui (não só repassado ao Executor) porque _check_spot_exits
        # fala direto com self.client, fora do Executor — precisa do próprio
        # gate de dry_run pra nunca mandar ordem real fora do fluxo --live.
        self.dry_run = dry_run
        self.cfg = load_risk_config()
        # "perp" | "spot" (decisão #E de 15/07/2026). Uma única leitura aqui
        # governa client (endpoints), executor (mecânica de ordem) e mapeamento
        # de símbolos; o RiskManager lê a MESMA chave do YAML por conta própria.
        self.market_type = get_market_type(self.cfg)
        self.client = BybitClient(
            get_credentials(),
            default_type="spot" if self.market_type == "spot" else "swap",
        )
        # environment= habilita limiares específicos de testnet no risco (YAML).
        self.risk = RiskManager(self.cfg, environment=get_environment())
        self.executor = Executor(self.client, dry_run=dry_run,
                                 market_type=self.market_type)
        # macro/on-chain vindo do dossiê diário (dossier_fetch.py) + derivativos
        # em tempo real direto da Bybit (decisão #G, 18/07 — implementado
        # 22/07). Se uma fonte estiver ausente/desatualizada/fora do ar, o
        # provider volta {} sozinho — nunca derruba o ciclo. Hoje isso é
        # inerte: decision.strategy ainda é "deterministic" (não lê
        # snap.context); só passa a valer quando a Fase 3 (LLMStrategy) for
        # ligada no YAML.
        self.context = ContextAggregator([
            DossierMacroProvider(),
            DossierOnChainProvider(),
            BybitDerivativesProvider(self.client),
        ])

        # Camada de decisão escolhida no config: "deterministic" ou "llm".
        self._decision_cfg = self.cfg.get("decision", {"strategy": "deterministic"})
        self._llm_client_fn = None  # criado sob demanda quando strategy=llm
        self._strategies: dict[str, object] = {}

        self._day_start_equity: float | None = None
        self._day_start_date = None  # dia UTC a que o day_start_equity se refere
        self._peak_equity: float = 0.0
        self._open_symbols: set[str] = set()  # símbolos com posição na exchange
        # Gate de candle da camada LLM (preparo da Fase 3): guarda o ts do
        # último candle FECHADO já decidido por (símbolo, perfil). Com a
        # correção do candle em formação, a decisão só muda na virada — chamar
        # o Claude a cada ciclo de ~65s desperdiçaria ~14 de 15 chamadas pagas
        # devolvendo o mesmo sinal. A estratégia determinística NÃO usa o gate
        # (barata, e o comportamento por ciclo é o validado no soak de 15/07).
        self._last_decided_candle: dict[tuple[str, str], int] = {}

    def _market_symbol(self, symbol: str) -> str:
        """Mapeia o símbolo do YAML para a modalidade ativa.

        O YAML guarda o formato de perpétuo ("BTC/USDT:USDT"); em spot o par
        CCXT é só "BTC/USDT". Mapear aqui evita manter duas listas de símbolos
        que poderiam divergir."""
        return symbol.split(":")[0] if self.market_type == "spot" else symbol

    def _build_strategy(self, profile_name: str):
        """Cria (uma vez por perfil) a estratégia conforme o config."""
        if profile_name in self._strategies:
            return self._strategies[profile_name]

        mode = self._decision_cfg.get("strategy", "deterministic")
        if mode == "llm":
            from src.strategy.llm_strategy import LLMStrategy, anthropic_client_fn
            llm_cfg = self._decision_cfg.get("llm", {})
            if self._llm_client_fn is None:
                self._llm_client_fn = anthropic_client_fn(
                    model=llm_cfg.get("model", "claude-sonnet-5"),
                    temperature=float(llm_cfg.get("temperature", 0.2)),
                )
            strat = LLMStrategy(
                profile_name,
                client_fn=self._llm_client_fn,
                min_conviction=float(llm_cfg.get("min_conviction", 0.6)),
                market_type=self.market_type,
            )
        else:
            # Chaves OPCIONAIS de decision.deterministic no YAML (20/07/2026):
            # exit_on_signal/trailing. Ausentes -> defaults (False) -> live
            # idêntico ao validado. Ligar é decisão do Lucas via YAML, nunca
            # default de código.
            det_cfg = self._decision_cfg.get("deterministic") or {}
            strat = DeterministicStrategy(profile_name, params=StrategyParams(
                exit_on_signal=bool(det_cfg.get("exit_on_signal", False)),
                trailing=bool(det_cfg.get("trailing", False)),
            ))

        self._strategies[profile_name] = strat
        return strat

    def _portfolio_state(self) -> PortfolioState:
        equity = self.client.fetch_balance_usdt()
        if self.market_type == "spot":
            # Spot não tem posições — tem saldo de moeda. O client devolve os
            # holdings no MESMO shape de posição para o resto do fluxo
            # (exclusividade, limites, notional) não precisar de dois caminhos.
            symbols = [self._market_symbol(s) for s in self.cfg["trading"]["symbols"]]
            positions = self.client.fetch_spot_holdings(symbols)
        else:
            positions = self.client.fetch_open_positions()
        self._open_symbols = {str(p.get("symbol")) for p in positions if p.get("symbol")}

        # 'Diário' de verdade: na virada do dia UTC, o marco zero do drawdown
        # diário é refeito. Antes, o marco ficava preso no equity do BOOT do
        # engine — depois de dias rodando, o limite 'diário' virava um stop
        # ancorado no passado. Kill switch disparado continua exigindo reset MANUAL.
        today = datetime.now(timezone.utc).date()
        if self._day_start_equity is None or self._day_start_date != today:
            self._day_start_equity = equity
            self._day_start_date = today
        self._peak_equity = max(self._peak_equity, equity)

        total_notional = sum(abs(float(p.get("notional") or 0)) for p in positions)
        return PortfolioState(
            equity_usdt=equity,
            day_start_equity=self._day_start_equity,
            peak_equity=self._peak_equity,
            open_positions=len(positions),
            total_notional=total_notional,
            aggregate_risk_pct=len(positions) * self.cfg["per_trade"]["risk_pct"],
        )

    # ---------------------- Saída por take-profit (SPOT) ----------------------
    def _resolve_entry_price(self, symbol: str, protection: dict) -> float:
        """entry_price pode ter vindo null da trilha (bug pré-fix #17: o ccxt
        às vezes não devolve average/price na criação da ordem a mercado).
        Quando isso acontece e temos o entry_id do order_executed original,
        consulta a ordem na exchange para recuperar o preço REAL de fill —
        sem isto, esses trades nunca calculam pnl_usdt em nenhum fechamento
        (nem por TP, nem por stop). Chamado só UMA vez por posição, na
        primeira vez que ela é vista sem entrada no arquivo de proteção (ver
        _check_spot_exits) — o valor resolvido é persistido, não recalculado
        a cada ciclo. Falha aqui mantém 0.0 (desconhecido) PARA SEMPRE nesta
        posição — nunca inventa um número, mas também não reage sozinho."""
        entry_price = protection.get("entry_price") or 0.0
        entry_id = protection.get("entry_id")
        if entry_price or not entry_id:
            return entry_price
        try:
            order = self.client.fetch_order(entry_id, symbol)
            avg = order.get("average") or order.get("price")
            if avg:
                return float(avg)
        except Exception as exc:  # noqa: BLE001
            log.warning("Sem confirmação do preço de entrada via ordem %s (%s): %s",
                        entry_id, symbol, exc)
        return entry_price

    def _handle_spot_position_closed(self, symbol: str, protection: dict) -> None:
        """Uma proteção salva no arquivo não corresponde mais a uma posição
        aberta na exchange — ou o stop disparou, ou foi fechamento manual.
        Antes disto (18/07/2026), só o caminho de TP por software emitia
        `trade_closed`: a maioria das saídas reais (via stop, o caminho mais
        comum) ficava muda na trilha, mesmo com o alvo de TP arquivado.
        Confirma o fill REAL da ordem de stop quando possível (fetch_order);
        sem confirmação, audita como aproximado em vez de fingir uma precisão
        que não tem — nunca usa o preço de ticker atual como proxy (pode já
        ter se movido bem longe do fill de verdade)."""
        if not protection:
            return

        entry_price = protection.get("entry_price") or 0.0
        size = protection.get("size")
        stop_id = protection.get("stop_id")

        exit_price = None
        exit_source = "unknown"
        if stop_id:
            try:
                order = self.client.fetch_order(stop_id, symbol)
                if order.get("status") == "closed" and float(order.get("filled") or 0) > 0:
                    fill_price = order.get("average") or order.get("price")
                    # "if fill_price", não "is None": average/price podem vir
                    # 0 (não None) num status=closed+filled>0 legítimo — 0
                    # não é um fill confirmado, é dado ausente disfarçado de
                    # confirmado (mesma classe de bug já corrigida em
                    # _resolve_entry_price; achado da revisão adversarial de
                    # 18/07 — sem este guard, um average=0 virava
                    # reason="stop_loss" com pnl_usdt fabricado).
                    if fill_price:
                        exit_price = fill_price
                        exit_source = "stop_order_fill"
                        # Usa o quanto a ordem REALMENTE preencheu, não o
                        # tamanho rastreado original — um preenchimento
                        # parcial (livro raso) infla o pnl_usdt se
                        # calculado sobre o tamanho cheio (achado da revisão
                        # de 18/07). Resíduo abaixo do fill confirmado pode
                        # sobrar sem proteção — limitação aceita e
                        # documentada no CLAUDE.md (não há como re-armar
                        # stop pra sobra aqui: ao contrário do caminho de
                        # TP, aqui o fechamento já é externo/consumado).
                        filled_qty = float(order.get("filled"))
                        if size is None or filled_qty < size:
                            size = filled_qty
            except Exception as exc:  # noqa: BLE001
                log.warning("Sem confirmação da ordem de stop %s (%s): %s",
                            stop_id, symbol, exc)

        if exit_price is None:
            # Sem confirmação do fill real: o alvo configurado do stop é a
            # melhor aproximação disponível — nunca o preço de ticker atual.
            exit_price = protection.get("stop_price") or 0.0
            exit_source = "stop_price_target_approx"
        exit_price = float(exit_price)

        reason = "stop_loss" if exit_source == "stop_order_fill" else "external_close_unconfirmed"
        # exit_price também entra no guard (não só entry_price/size): um
        # exit_price=0.0 (stop_price ausente no fallback acima, ex. arquivo
        # corrompido) não pode virar pnl_usdt fabricado — mesma classe de
        # bug "0 tratado como confirmado" já corrigida 2x neste projeto
        # (achado da revisão adversarial de 18/07).
        pnl_usdt = ((exit_price - entry_price) * size
                    if entry_price and exit_price and size is not None else None)

        audit("trade_closed", symbol=symbol, side="long", entry_price=entry_price or None,
              exit_price=exit_price, size=size, pnl_usdt=pnl_usdt, reason=reason,
              exit_price_source=exit_source)
        log.info("Posição %s fechada fora do fluxo de TP (%s, exit~%.2f)",
                 symbol, reason, exit_price)
        # Cooldown por símbolo (21/07): só reason="stop_loss" (confirmado via
        # fetch_order) incrementa a sequência — "external_close_unconfirmed"
        # é tratado como reset (não dá pra confirmar que foi perda), mesma
        # postura conservadora do resto deste método (nunca afirma o que não
        # confirmou). Ver RiskManager.record_trade_close.
        self.risk.record_trade_close(symbol, reason)

    def _check_spot_exits(self) -> None:
        """A cada ciclo, para símbolos SPOT já com posição: confere se o preço
        atingiu o take-profit salvo e, se sim, fecha a mercado (a Bybit spot
        não tem OCO — ver executor.py e protection_state.py). O STOP em si
        NUNCA depende disto — é sempre uma ordem real na exchange, ativa
        mesmo com o engine parado; só a saída LUCRATIVA depende do loop
        rodando."""
        if self.market_type != "spot":
            return

        # `protections` é lido UMA vez aqui e usado pelos dois loops abaixo
        # sem recarregar — só é seguro porque os dois operam sobre conjuntos
        # de símbolos MUTUAMENTE EXCLUSIVOS por construção (loop de fechados
        # só toca símbolo AUSENTE de self._open_symbols; loop de TP só toca
        # símbolo PRESENTE nele) — nunca há overlap dentro de uma mesma
        # chamada. Precondição implícita, não garantida por tipo: se um dia
        # os dois loops passarem a poder tocar o MESMO símbolo na mesma
        # chamada, esta leitura única volta a ficar desatualizada em
        # relação às escritas feitas pelo loop de TP (achado da revisão
        # adversarial de 18/07 — não é bug hoje, mas fica documentado aqui
        # porque não seria óbvio numa mudança futura).
        protections = protection_state.load()

        # Proteção salva sem posição correspondente na exchange: ou o stop
        # disparou, ou foi fechamento manual. Roda ANTES do loop de TP pra
        # não tentar checar preço de algo que já não existe mais. Cobre
        # reinícios do engine (o arquivo sobrevive; memória de processo não)
        # — toda posição rastreada acaba com uma entrada aqui, inclusive as
        # abertas antes desta função existir (ver persistência no loop de TP
        # abaixo).
        #
        # Limitação aceita e NÃO mitigada (achado da revisão adversarial de
        # 18/07): se a MESMA posição fechar e uma posição NOVA reabrir no
        # MESMO símbolo dentro da janela de ~65s entre polls (recompra
        # manual na testnet, ou uma segunda instância do engine — proibida,
        # mas já documentada como risco real de confusão de processos no
        # Windows), este loop nunca vê o fechamento (o símbolo volta a
        # aparecer em self._open_symbols antes do próximo ciclo) e o loop
        # de TP herda a proteção STALE da posição antiga para a posição
        # nova — um TP antigo pode cancelar o stop real da posição nova e
        # vender um tamanho errado. Mitigar exigiria alguma forma de
        # identidade de posição que o spot não tem (só saldo, sem ID) ou
        # uma chamada extra de saldo a cada ciclo para todo símbolo aberto
        # — custo considerado desproporcional a um cenário estreito; risco
        # aceito, mesmo espírito da janela sem stop já documentada em
        # _execute_spot_take_profit.
        for symbol in list(protections):
            if symbol in self._open_symbols:
                continue
            try:
                self._handle_spot_position_closed(symbol, protections[symbol])
            except Exception as exc:  # noqa: BLE001
                log.exception("Erro apurando fechamento de %s: %s", symbol, exc)
                audit("symbol_cycle_error", symbol=symbol,
                      profile="position_closed_reconcile", error=str(exc))
            finally:
                # Limpa mesmo se a apuração falhou: o símbolo já não está
                # aberto e manter a entrada faria o próximo ciclo tentar TP
                # numa posição que não existe mais.
                try:
                    protection_state.clear_protection(symbol)
                except Exception as exc:  # noqa: BLE001
                    log.warning("Falha ao limpar proteção de %s pós-fechamento: %s",
                                symbol, exc)

        for symbol in list(self._open_symbols):
            try:
                protection = protections.get(symbol)
                if protection is None:
                    protection = protection_state.backfill_from_audit(symbol)
                    # trailing conta como proteção rastreável mesmo sem TP
                    # (achado confirmado da revisão de 20/07 — sem isto, uma
                    # posição trailing recuperada do backfill nunca era
                    # re-persistida e o trailing morria em silêncio).
                    if protection and (protection.get("take_profit")
                                       or protection.get("trailing")):
                        # Persiste assim que vista: posições abertas ANTES
                        # desta função existir (ex.: BTC de 17/07) só tinham
                        # proteção via backfill em memória, nunca gravada no
                        # arquivo — se fechassem com o engine DESLIGADO entre
                        # ciclos, o loop de cima (que só olha o ARQUIVO) nunca
                        # saberia que existiram (a lacuna que motivou esta
                        # função, 18/07/2026). Resolve o entry_price (pode vir
                        # null na trilha — fix #17) UMA vez, aqui, e persiste
                        # já resolvido: depois disto o arquivo é a fonte da
                        # verdade, sem precisar consultar a exchange de novo.
                        resolved_entry = self._resolve_entry_price(symbol, protection)
                        protection_state.set_protection(
                            symbol, entry_price=resolved_entry,
                            take_profit=protection["take_profit"],
                            stop_price=protection.get("stop_price") or 0.0,
                            size=protection.get("size"), stop_id=protection.get("stop_id"),
                            # 20/07: sem repassar profile/trailing, a
                            # persistência do backfill APAGARIA a saída por
                            # sinal/trailing de uma posição recuperada.
                            profile=protection.get("profile"),
                            trailing=bool(protection.get("trailing")),
                            trail_distance=protection.get("trail_distance"),
                            peak_price=protection.get("peak_price"))
                        protection = {**protection, "entry_price": resolved_entry}
                if not protection:
                    continue
                try:
                    price = self.client.fetch_ticker(symbol).get("last")
                except Exception as exc:  # noqa: BLE001
                    log.warning("Sem preço pra checar saída de %s: %s", symbol, exc)
                    continue
                if price is None:
                    continue
                price = float(price)
                # math.isfinite descarta NaN/inf: `nan < alvo` é sempre False em
                # Python, então sem essa checagem um preço corrompido passava
                # direto pelo guard abaixo e disparava venda real (achado da
                # revisão adversarial de 17/07).
                if not math.isfinite(price):
                    continue
                # Trailing PRIMEIRO (20/07): sobe o stop antes de qualquer
                # decisão de saída — se a posição fechar neste mesmo ciclo
                # (TP/sinal), o trailing foi um no-op inofensivo; se não
                # fechar, o stop já está no lugar certo.
                if protection.get("trailing") and protection.get("trail_distance"):
                    protection = self._update_trailing_stop(symbol, protection, price)
                    if protection is None:
                        continue  # posição reconciliada como fechada no meio
                    if protection.pop("_trailing_exit_now", False):
                        # Preço já rompeu o nível trailed (ver comentário em
                        # _update_trailing_stop) — o disparo acontece por
                        # software, a mercado, agora.
                        self._execute_spot_exit(
                            symbol, protection, price, kind="trailing_exit",
                            rationale="nível do trailing rompido entre ciclos")
                        continue
                # TP primeiro: quando TP e saída por sinal dispararem no mesmo
                # ciclo, o TP é estritamente melhor (o preço já está no alvo
                # lucrativo) — e evita consultar OHLCV à toa.
                tp = protection.get("take_profit")
                if tp and price >= tp:
                    self._execute_spot_take_profit(symbol, protection, price)
                    continue
                # Saída por SINAL (20/07/2026): a estratégia do perfil que
                # abriu a posição pode mandar fechar (ex.: EMA descruzou).
                # Nunca passa pelo veto de risco — fechar reduz risco, mesma
                # filosofia do stop/kill switch (decisão #B).
                exit_rationale = self._check_signal_exit(symbol, protection)
                if exit_rationale:
                    self._execute_spot_signal_exit(symbol, protection, price,
                                                   exit_rationale)
            except Exception as exc:  # noqa: BLE001
                # Isola por símbolo — mesma regra do loop de entrada (fix #1 de
                # 15/07): um erro aqui não pode derrubar o ciclo inteiro nem
                # travar --once com traceback (achado da revisão de 17/07).
                log.exception("Erro checando saída de TP em %s: %s", symbol, exc)
                audit("symbol_cycle_error", symbol=symbol,
                      profile="take_profit_exit", error=str(exc))

    def _check_signal_exit(self, symbol: str, protection: dict) -> str | None:
        """Consulta a estratégia do perfil que ABRIU a posição pra saber se
        ela manda fechar agora (20/07/2026). Devolve o racional ou None.

        Custo zero enquanto desligado: o snapshot (1 fetch de OHLCV por
        símbolo/ciclo) só é montado se a estratégia declarar
        `wants_exit_signals` — com `exit_on_signal` no default (False),
        nenhum tráfego novo é gerado. Posição sem `profile` gravado
        (aberta antes desta feature) degrada pro comportamento antigo."""
        profile = protection.get("profile")
        if not profile:
            return None
        pcfg = self.cfg["trading"]["profiles"].get(profile)
        if not pcfg:
            return None
        strategy = self._build_strategy(profile)
        if not getattr(strategy, "wants_exit_signals", False):
            return None
        should_exit = getattr(strategy, "should_exit", None)
        if should_exit is None:
            return None
        snap = build_snapshot(self.client, symbol, pcfg["timeframe"])
        return should_exit(snap, {**protection, "side": "long"})

    def _update_trailing_stop(self, symbol: str, protection: dict,
                              price: float) -> dict | None:
        """Sobe o stop de uma posição spot com trailing ativo (20/07/2026).

        Mantém `trail_distance` entre o PICO de preço visto e o stop: preço
        avança -> pico avança -> stop sobe junto (nunca desce). Mover o stop
        em spot é cancelar a ordem condicional e criar outra (não há "modify")
        — por isso o passo mínimo TRAIL_MIN_STEP_PCT e o mesmo padrão
        nunca-nua do caminho de saída: se a criação do stop NOVO falhar
        depois do cancelamento, re-arma no preço ANTIGO; se até isso falhar,
        audita `trailing_rearm_stop_failed` (intervenção manual).

        Devolve a proteção atualizada, ou None se a posição foi reconciliada
        como fechada no meio do caminho (stop disparou concorrente)."""
        trail = float(protection["trail_distance"])
        stored_peak = float(protection.get("peak_price") or
                            protection.get("entry_price") or 0.0)
        peak = max(stored_peak, price)
        new_stop = peak - trail
        cur_stop = float(protection.get("stop_price") or 0.0)
        # Preço atual JÁ rompeu o nível trailed (pico stale de um move que
        # falhou/não persistiu, ou queda forte entre ciclos): armar stop com
        # gatilho >= preço atual é REJEITADO pela Bybit (trigger de descida
        # precisa estar abaixo do last) e viraria um loop de cancelar/
        # re-armar a cada ciclo, com janela sem stop toda vez (achado da
        # revisão adversarial de 20/07). O nível trailed foi rompido — o
        # disparo do trailing acontece por SOFTWARE: sai a mercado agora
        # (o chamador roteia pra _execute_spot_exit, que já cobre dry_run,
        # nunca-nua e auditoria).
        if price <= new_stop:
            return {**protection, "peak_price": peak, "_trailing_exit_now": True}
        if new_stop <= cur_stop + price * TRAIL_MIN_STEP_PCT:
            # Melhora insuficiente — não mexe na exchange. Persiste só o pico
            # quando avançou (sobrevive a restart; sem isto o trailing
            # "esqueceria" o high entre ciclos e nunca subiria o stop num
            # mercado que sobe devagar).
            if peak > stored_peak and not self.dry_run:
                try:
                    protection_state.set_protection(
                        symbol, entry_price=protection.get("entry_price") or 0.0,
                        take_profit=protection.get("take_profit"),
                        stop_price=cur_stop, size=protection.get("size"),
                        stop_id=protection.get("stop_id"),
                        profile=protection.get("profile"),
                        trailing=True, trail_distance=trail, peak_price=peak)
                except Exception as exc:  # noqa: BLE001
                    log.warning("Falha ao persistir pico do trailing de %s: %s",
                                symbol, exc)
            return {**protection, "peak_price": peak}

        if self.dry_run:
            # NUNCA toca a exchange fora de --live (mesma regra do caminho de
            # saída — achado crítico da revisão de 17/07 nesse caminho irmão).
            log.info("[DRY_RUN] TRAILING teria movido stop de %s: %.2f -> %.2f "
                     "(pico %.2f)", symbol, cur_stop, new_stop, peak)
            audit("dry_run_trailing_stop_move", symbol=symbol,
                  old_stop=cur_stop, new_stop=new_stop, peak_price=peak)
            return {**protection, "peak_price": peak}

        # Antes de mover, confirma o gatilho REAL vigente na exchange: o
        # arquivo pode estar stale (persistência do move anterior falhou por
        # lock do OneDrive, ou o processo caiu entre armar e persistir) — e
        # mover com base no valor velho CANCELARIA um stop mais alto pra
        # re-armar mais baixo, rebaixando a proteção real (achado confirmado
        # da revisão adversarial de 20/07). Falha nesta leitura -> aborta o
        # move deste ciclo (conservador: manter o stop atual é sempre seguro).
        try:
            real_orders = self.client.fetch_open_stop_orders(symbol)
        except Exception as exc:  # noqa: BLE001
            log.warning("Sem leitura das ordens de stop reais de %s (%s) — "
                        "trailing move adiado pro próximo ciclo", symbol, exc)
            return {**protection, "peak_price": peak}
        real_trigger, real_id = None, None
        for order in real_orders or []:
            trig = order.get("triggerPrice") or order.get("stopPrice") or \
                (order.get("info") or {}).get("triggerPrice")
            if trig and (real_trigger is None or float(trig) > real_trigger):
                real_trigger, real_id = float(trig), order.get("id")
        if real_trigger is not None and real_trigger > cur_stop:
            # Arquivo stale confirmado: cura o registro com o gatilho real e
            # reavalia o passo mínimo contra ELE.
            log.warning("Trailing de %s: arquivo stale (stop %.2f < gatilho real "
                        "%.2f) — curando registro", symbol, cur_stop, real_trigger)
            cur_stop = real_trigger
            protection = {**protection, "stop_price": cur_stop,
                          "stop_id": real_id or protection.get("stop_id")}
            if new_stop <= cur_stop + price * TRAIL_MIN_STEP_PCT:
                try:
                    protection_state.set_protection(
                        symbol, entry_price=protection.get("entry_price") or 0.0,
                        take_profit=protection.get("take_profit"),
                        stop_price=cur_stop, size=protection.get("size"),
                        stop_id=protection.get("stop_id"),
                        profile=protection.get("profile"),
                        trailing=True, trail_distance=trail, peak_price=peak)
                except Exception as exc:  # noqa: BLE001
                    log.warning("Falha ao persistir cura do trailing de %s: %s",
                                symbol, exc)
                return {**protection, "peak_price": peak}

        try:
            self.client.cancel_all(symbol)
        except Exception as exc:  # noqa: BLE001
            log.warning("cancel_all falhou pra %s antes do trailing move: %s",
                        symbol, exc)
        try:
            free = self.client.fetch_free_base(symbol)
            tracked = protection.get("size")
            amount = min(free, tracked) if tracked is not None else free
            rearm_size = self.client.amount_to_precision(symbol, amount)
            if rearm_size <= 0:
                # Saldo zerado após cancelar: o stop antigo disparou
                # CONCORRENTE ao trailing move — mesma reconciliação do
                # caminho de saída (nunca deixar fechamento mudo na trilha).
                log.info("Trailing de %s: saldo base zerado após cancelar — "
                         "provável fechamento concorrente pelo stop; "
                         "reconciliando", symbol)
                try:
                    self._handle_spot_position_closed(symbol, protection)
                except Exception as exc:  # noqa: BLE001
                    log.exception("Erro reconciliando fechamento concorrente "
                                  "de %s: %s", symbol, exc)
                    audit("symbol_cycle_error", symbol=symbol,
                          profile="trailing_stop_move", error=str(exc))
                finally:
                    try:
                        protection_state.clear_protection(symbol)
                    except Exception as exc:  # noqa: BLE001
                        log.warning("Falha ao limpar proteção de %s: %s",
                                    symbol, exc)
                return None
            new_order = self.client.set_stop_loss(symbol, "buy", rearm_size,
                                                  new_stop)
            # Audit do sucesso em try PRÓPRIO: se a escrita da trilha falhar
            # (lock do OneDrive) DEPOIS do stop novo já armado, cair no
            # except principal re-armaria o stop ANTIGO — que falharia
            # (saldo já preso no novo) e auditaria trailing_rearm_stop_failed
            # FALSO com a posição perfeitamente protegida (achado da revisão
            # adversarial de 20/07).
            try:
                audit("trailing_stop_moved", symbol=symbol, old_stop=cur_stop,
                      new_stop=new_stop, peak_price=peak, size=rearm_size,
                      stop_id=new_order.get("id"))
                log.info("TRAILING moveu stop de %s: %.2f -> %.2f (pico %.2f)",
                         symbol, cur_stop, new_stop, peak)
            except Exception as audit_exc:  # noqa: BLE001
                log.critical("Trailing moveu o stop de %s mas FALHA ao auditar "
                             "(trilha pode não refletir): %s", symbol, audit_exc)
            try:
                protection_state.set_protection(
                    symbol, entry_price=protection.get("entry_price") or 0.0,
                    take_profit=protection.get("take_profit"),
                    stop_price=new_stop, size=rearm_size,
                    stop_id=new_order.get("id"),
                    profile=protection.get("profile"),
                    trailing=True, trail_distance=trail, peak_price=peak)
            except Exception as save_exc:  # noqa: BLE001
                log.warning("Trailing moveu o stop mas falhou ao persistir "
                            "novo stop_id de %s: %s", symbol, save_exc)
            return {**protection, "stop_price": new_stop, "size": rearm_size,
                    "stop_id": new_order.get("id"), "peak_price": peak}
        except Exception as exc:  # noqa: BLE001
            # NUNCA posição nua: o cancel_all pode ter derrubado o stop
            # antigo — re-arma no preço ANTIGO antes de desistir.
            log.error("Trailing move falhou em %s (%s) — re-armando stop "
                      "antigo em %.2f", symbol, exc, cur_stop)
            try:
                free_now = self.client.fetch_free_base(symbol)
                tracked = protection.get("size")
                amount = min(free_now, tracked) if tracked is not None else free_now
                rearm_size = self.client.amount_to_precision(symbol, amount)
                if rearm_size > 0:
                    old_order = self.client.set_stop_loss(symbol, "buy",
                                                          rearm_size, cur_stop)
                    audit("trailing_move_failed_stop_rearmed", symbol=symbol,
                          stop_price=cur_stop, error=str(exc),
                          stop_id=old_order.get("id"))
                    try:
                        protection_state.set_protection(
                            symbol,
                            entry_price=protection.get("entry_price") or 0.0,
                            take_profit=protection.get("take_profit"),
                            stop_price=cur_stop, size=rearm_size,
                            stop_id=old_order.get("id"),
                            profile=protection.get("profile"),
                            trailing=True, trail_distance=trail,
                            peak_price=peak)
                    except Exception as save_exc:  # noqa: BLE001
                        log.warning("Stop antigo re-armado mas falha ao "
                                    "persistir stop_id de %s: %s",
                                    symbol, save_exc)
            except Exception as rearm_exc:  # noqa: BLE001
                log.critical("FALHA AO RE-ARMAR STOP de %s apos trailing move "
                             "falhar — POSICAO SEM PROTECAO NENHUMA, intervir "
                             "manualmente: %s", symbol, rearm_exc)
                audit("trailing_rearm_stop_failed", symbol=symbol,
                      move_error=str(exc), rearm_error=str(rearm_exc))
            return {**protection, "peak_price": peak}

    def _execute_spot_take_profit(self, symbol: str, protection: dict, price: float) -> None:
        self._execute_spot_exit(symbol, protection, price, kind="take_profit")

    def _execute_spot_signal_exit(self, symbol: str, protection: dict, price: float,
                                  rationale: str) -> None:
        self._execute_spot_exit(symbol, protection, price, kind="signal_exit",
                                rationale=rationale)

    def _execute_spot_exit(self, symbol: str, protection: dict, price: float,
                           kind: str, rationale: str | None = None) -> None:
        """Fecha uma posição spot a mercado — caminho ÚNICO pra TP por
        software e saída por SINAL (20/07/2026). A mecânica é idêntica
        (cancelar o stop pra liberar o saldo, vender, auditar, re-armar em
        falha/parcial); só os nomes de evento e o `reason` do trade_closed
        mudam por `kind`. Generalizado a partir do caminho de TP já validado
        ao vivo — qualquer mudança aqui afeta os DOIS caminhos, testar ambos."""
        # target: alvo numérico do TP, ou o preço corrente na saída por sinal
        # (não existe "alvo" — o sinal mandou sair agora, no preço que tiver).
        target = protection.get("take_profit") if kind == "take_profit" else price
        # Nomes de evento por tipo de saída. take_profit mantém os nomes
        # históricos (catálogo documentado no CLAUDE.md, monitorados desde
        # 17/07); signal_exit ganha os espelhos com o mesmo shape.
        ev = {
            "take_profit": {
                "dry_run": "dry_run_take_profit",
                "exit_failed": "take_profit_exit_failed",
                "rearm_failed": "take_profit_rearm_stop_failed",
                "executed": "take_profit_executed",
                "closed_reason": "take_profit",
                "price_source": "tp_order_fill",
            },
            "signal_exit": {
                "dry_run": "dry_run_signal_exit",
                "exit_failed": "signal_exit_failed",
                "rearm_failed": "signal_exit_rearm_stop_failed",
                "executed": "signal_exit_executed",
                "closed_reason": "signal_exit",
                "price_source": "exit_order_fill",
            },
            # Disparo do trailing por software (20/07): o preço rompeu o
            # nível trailed entre ciclos — mesma semântica de fechamento do
            # trailing_stop do backtester (paridade de exit_reason).
            "trailing_exit": {
                "dry_run": "dry_run_trailing_exit",
                "exit_failed": "trailing_exit_failed",
                "rearm_failed": "trailing_exit_rearm_stop_failed",
                "executed": "trailing_exit_executed",
                "closed_reason": "trailing_stop",
                "price_source": "exit_order_fill",
            },
        }[kind]

        if self.dry_run:
            # NUNCA toca a exchange fora de --live — achado crítico da revisão
            # adversarial de 17/07: antes disto, este caminho ignorava
            # self.dry_run completamente (só o Executor checava), então rodar
            # `python main.py` sem --live ainda cancelava o stop e vendia de
            # verdade assim que o preço batesse o alvo salvo.
            log.info("[DRY_RUN] %s teria executado %s @ %.2f (alvo %.2f)",
                     kind.upper(), symbol, price, target or 0.0)
            audit(ev["dry_run"], symbol=symbol, target=target, price=price,
                  rationale=rationale)
            return

        # Cancela a condicional do stop ANTES de vender: em spot ela ocupa o
        # saldo-base (ver executor.py), então vender antes de liberar seria
        # rejeitado por saldo insuficiente. Janela breve sem stop entre os
        # dois passos — risco aceito e documentado, sem alternativa na API
        # atual da Bybit spot (sem OCO).
        try:
            self.client.cancel_all(symbol)
        except Exception as exc:  # noqa: BLE001
            log.warning("cancel_all falhou pra %s antes da saída (%s) — pode já "
                        "ter sido preenchido pelo stop: %s", symbol, kind, exc)

        try:
            free = self.client.fetch_free_base(symbol)
            # Nunca vende mais que a posição RASTREADA (mesmo padrão de
            # min(size, free) da entrada — executor.py): saldo extra da mesma
            # moeda-base (dust de outra origem, depósito manual) não pertence
            # a este trade e não deve ser liquidado junto (achado da revisão
            # adversarial de 17/07 — antes vendia `free` inteiro sem clamp).
            tracked = protection.get("size")
            # "is not None", não truthy: um tamanho rastreado de 0.0 (ex.:
            # state/spot_protections.json editado manualmente) não pode cair
            # no fallback "sem teto" — mesma classe de bug do teto de capital
            # (achado da 2ª rodada de revisão de 17/07).
            sell_amount = min(free, tracked) if tracked is not None else free
            size = self.client.amount_to_precision(symbol, sell_amount)
            if size <= 0:
                # Saldo zerado após cancelar tem DUAS causas possíveis:
                # (a) o stop real disparou CONCORRENTE à saída (cancel_all só
                #     libera o saldo depois de rodar) — fechamento real;
                # (b) o cancel_all FALHOU (rede) e o saldo continua preso na
                #     ordem de stop AINDA VIVA — a posição está aberta.
                # Tratar (b) como (a) fabricaria um trade_closed pra uma
                # posição viva e apagaria a proteção (achado da revisão
                # adversarial de 20/07, por 2 lentes independentes). Antes de
                # reconciliar, confirma que o stop NÃO está mais ativo.
                stop_id = protection.get("stop_id")
                if stop_id:
                    try:
                        stop_order = self.client.fetch_order(stop_id, symbol)
                        if (stop_order or {}).get("status") in ("open", "untriggered"):
                            log.error("%s de %s: saldo zerado mas o stop %s "
                                      "AINDA está ativo — cancel_all deve ter "
                                      "falhado; proteção mantida, retry no "
                                      "próximo ciclo", kind, symbol, stop_id)
                            audit(ev["exit_failed"], symbol=symbol, target=target,
                                  error="saldo base preso em stop ainda ativo "
                                        "(cancel_all provavelmente falhou)")
                            return
                    except Exception as exc:  # noqa: BLE001
                        # Sem confirmação -> segue o fluxo antigo (reconciliar
                        # é melhor que silenciar; _handle_spot_position_closed
                        # ainda tenta confirmar o fill por conta própria).
                        log.warning("Sem consulta do stop %s de %s: %s",
                                    stop_id, symbol, exc)
                # Fechamento concorrente confirmado (ou inconfirmável):
                # delega pra mesma reconciliação do loop de fechados —
                # confirma o fill via fetch_order(stop_id) quando possível,
                # em vez de silenciar (achado 3x independente, 18/07).
                log.info("%s de %s: saldo base zerado após cancelar — provável "
                         "fechamento concorrente pelo stop; reconciliando",
                         kind, symbol)
                try:
                    self._handle_spot_position_closed(symbol, protection)
                except Exception as exc:  # noqa: BLE001
                    log.exception("Erro reconciliando fechamento concorrente "
                                  "de %s: %s", symbol, exc)
                    audit("symbol_cycle_error", symbol=symbol,
                          profile=("take_profit_exit" if kind == "take_profit"
                                   else kind), error=str(exc))
                finally:
                    try:
                        protection_state.clear_protection(symbol)
                    except Exception as exc:  # noqa: BLE001
                        log.warning("Falha ao limpar proteção de %s: %s",
                                    symbol, exc)
                return
            order = self.client.create_order(symbol, "sell", size, order_type="market")
        except Exception as exc:  # noqa: BLE001
            log.error("Falha ao executar %s de %s (alvo %.2f): %s",
                      kind, symbol, target or 0.0, exc)
            audit(ev["exit_failed"], symbol=symbol,
                  target=target, error=str(exc))
            # Regra da casa: NUNCA posição nua. O cancel_all liberou o saldo
            # antes da venda (necessário pra ela não ser rejeitada) — se a
            # venda falhou, a posição ficou sem proteção. Tenta re-armar o
            # stop ORIGINAL agora, em vez de esperar até ~65s pelo próximo
            # ciclo (o alvo de TP continua salvo — o próximo ciclo tenta a
            # saída lucrativa de novo).
            try:
                free_now = self.client.fetch_free_base(symbol)
                tracked = protection.get("size")
                rearm_amount = min(free_now, tracked) if tracked is not None else free_now
                rearm_size = self.client.amount_to_precision(symbol, rearm_amount)
                if rearm_size > 0:
                    new_stop = self.client.set_stop_loss(symbol, "buy", rearm_size,
                                                         protection["stop_price"])
                    log.warning("Stop RE-ARMADO em %s (%.2f) apos falha na venda (%s)",
                               symbol, protection["stop_price"], kind)
                    # O stop re-armado tem um ID NOVO na exchange — sem
                    # atualizar o arquivo, a confirmação de fechamento
                    # (_handle_spot_position_closed) consultaria o ID antigo
                    # (já cancelado, nunca mais dispara) e nunca confirmaria
                    # o fill de verdade quando esta posição eventualmente
                    # fechar (achado ao implementar a confirmação de stop,
                    # 18/07/2026). Falha aqui não é crítica: a proteção
                    # continua válida na exchange, só a futura auditoria de
                    # fechamento cairia no caminho aproximado. profile/
                    # trailing preservados (20/07) — sem eles o re-arm
                    # apagaria a saída por sinal/trailing da posição.
                    try:
                        protection_state.set_protection(
                            symbol, entry_price=protection.get("entry_price") or 0.0,
                            take_profit=protection.get("take_profit"),
                            stop_price=protection["stop_price"],
                            size=rearm_size, stop_id=new_stop.get("id"),
                            profile=protection.get("profile"),
                            trailing=bool(protection.get("trailing")),
                            trail_distance=protection.get("trail_distance"),
                            peak_price=protection.get("peak_price"))
                    except Exception as save_exc:  # noqa: BLE001
                        log.warning("Stop re-armado mas falha ao persistir novo "
                                    "stop_id de %s: %s", symbol, save_exc)
            except Exception as rearm_exc:  # noqa: BLE001
                log.critical("FALHA AO RE-ARMAR STOP de %s apos %s falhar — "
                             "POSICAO SEM PROTECAO NENHUMA, intervir manualmente: %s",
                             symbol, kind, rearm_exc)
                audit(ev["rearm_failed"], symbol=symbol,
                      exit_error=str(exc), rearm_error=str(rearm_exc))
            return

        # Confere quanto REALMENTE foi vendido: uma ordem a mercado pode
        # preencher só parcialmente num livro raso (achado da revisão
        # adversarial de 18/07) — usar o `size` PEDIDO como se fosse o
        # vendido superestimaria o pnl_usdt e, pior, deixaria sobra de
        # posição real sem proteção (o stop original já foi cancelado) sem
        # ninguém perceber, já que a proteção era limpa incondicionalmente.
        filled = order.get("filled")
        sold = float(filled) if filled is not None else size
        fill_price = order.get("average") or order.get("price") or price
        entry_price = protection.get("entry_price") or 0.0

        try:
            audit(ev["executed"], symbol=symbol, target=target,
                  fill_price=fill_price, size=sold, order_id=order.get("id"),
                  rationale=rationale)
            # Sempre audita trade_closed, mesmo sem entry_price conhecido
            # (pnl fica None em vez do evento simplesmente não sair —
            # mesma filosofia do fechamento por stop em
            # _handle_spot_position_closed: a trilha registra QUE fechou
            # mesmo quando não dá pra confirmar o QUANTO).
            pnl_usdt = (fill_price - entry_price) * sold if entry_price else None
            audit("trade_closed", symbol=symbol, side="long", entry_price=entry_price or None,
                  exit_price=fill_price, size=sold, pnl_usdt=pnl_usdt,
                  reason=ev["closed_reason"], exit_price_source=ev["price_source"])
            log.info("%s executado %s @ %.2f (alvo %.2f)",
                     kind.upper(), symbol, fill_price, target or 0.0)
            # Cooldown por símbolo (21/07): este caminho é sempre TP/saída por
            # sinal/trailing (nunca stop_loss) — sempre QUEBRA a sequência de
            # stops seguidos, ver RiskManager.record_trade_close.
            self.risk.record_trade_close(symbol, ev["closed_reason"])
        except Exception as exc:  # noqa: BLE001
            # Dinheiro JÁ mudou de mãos (a venda foi aceita pela exchange) —
            # a falha aqui é só a ESCRITA na trilha (I/O, provável lock do
            # OneDrive — risco documentado em todo o projeto), nunca a
            # operação em si. A proteção é limpa/re-armada de qualquer
            # forma logo abaixo: preferir perder este evento específico
            # (raro) a deixar o PRÓXIMO ciclo reconciliar esta posição como
            # "fechamento externo" usando o stop_price (alvo de PERDA) —
            # inventaria um pnl com sinal errado pra um trade que na
            # verdade foi lucrativo (achado da revisão adversarial de
            # 18/07: reprocessamento duplicado/contraditório se a proteção
            # não for limpa aqui).
            log.critical("Venda (%s) de %s executada (%.8f @ %.2f) mas FALHA "
                         "ao auditar — dinheiro já mudou de mão, trilha pode "
                         "não refletir: %s", kind, symbol, sold, fill_price, exc)

        # Nunca posição nua: se a venda só preencheu PARCIALMENTE (sobra
        # acima do limiar de poeira), o stop original já foi cancelado —
        # re-arma um novo pro restante em vez de limpar a proteção como se
        # a posição tivesse fechado inteira (achado da revisão adversarial
        # de 18/07). Deliberadamente NÃO reconsulta fetch_free_base() aqui:
        # a sobra é `size PEDIDO - sold PREENCHIDO` (derivado da própria
        # resposta da ordem), não uma nova leitura de saldo — reconsultar o
        # saldo livre confundiria a sobra desta venda com saldo alheio na
        # mesma moeda-base (dust de outra origem, depósito manual), a MESMA
        # classe de bug que este arquivo já corrige em outros pontos com
        # `min(free, tracked)`.
        remaining = max(0.0, size - sold)
        remaining_notional = remaining * fill_price if fill_price else 0.0
        if remaining > 0 and remaining_notional >= SPOT_DUST_USDT:
            try:
                rearm_size = self.client.amount_to_precision(symbol, remaining)
                new_stop = self.client.set_stop_loss(symbol, "buy", rearm_size,
                                                      protection["stop_price"])
            except Exception as rearm_exc:  # noqa: BLE001
                log.critical("%s parcial em %s e FALHA ao re-armar stop do "
                             "restante — POSIÇÃO SEM PROTEÇÃO, intervir "
                             "manualmente: %s", kind, symbol, rearm_exc)
                audit(ev["rearm_failed"], symbol=symbol,
                      error=str(rearm_exc))
                return
            # Persistência FORA do try do re-arm (achado da revisão de
            # 20/07): com o stop do restante JÁ armado, uma falha só de I/O
            # aqui não pode virar o alarme crítico de "posição sem proteção".
            try:
                protection_state.set_protection(
                    symbol, entry_price=entry_price,
                    take_profit=protection.get("take_profit"),
                    stop_price=protection["stop_price"], size=rearm_size,
                    stop_id=new_stop.get("id"),
                    profile=protection.get("profile"),
                    trailing=bool(protection.get("trailing")),
                    trail_distance=protection.get("trail_distance"),
                    peak_price=protection.get("peak_price"))
            except Exception as save_exc:  # noqa: BLE001
                log.warning("Stop do restante re-armado mas falha ao persistir "
                            "protecao de %s: %s", symbol, save_exc)
            log.warning("%s de %s preencheu so parcialmente (vendeu %.8f) "
                       "— stop RE-ARMADO pro restante (%.8f)",
                       kind, symbol, sold, rearm_size)
        else:
            # try/except próprio (achado da revisão de 20/07): a venda JÁ
            # aconteceu — uma falha de I/O na limpeza não pode propagar e
            # derrubar o processamento dos DEMAIS símbolos do ciclo. Mantém
            # o symbol_cycle_error na trilha (visibilidade, best-effort) —
            # o reprocessamento contraditório do próximo ciclo continua
            # possível se a limpeza falhar de verdade (mesma classe de
            # resíduo aceito do fix #21; raro, exige lock persistente).
            try:
                protection_state.clear_protection(symbol)
            except Exception as exc:  # noqa: BLE001
                log.critical("Venda (%s) de %s concluída mas FALHA ao limpar a "
                             "proteção — próximo ciclo pode reprocessar como "
                             "fechamento externo: %s", kind, symbol, exc)
                try:
                    audit("symbol_cycle_error", symbol=symbol,
                          profile=("take_profit_exit" if kind == "take_profit"
                                   else kind),
                          error=f"clear_protection falhou pós-venda: {exc}")
                except Exception:  # noqa: BLE001
                    pass

    def _apply_control_signal(self) -> None:
        """Lê sinais de controle deixados pelo MCP (state/control.json) e age.

        Mantém o MCP desacoplado do processo do engine: o MCP só grava o pedido;
        o engine decide. Halt trava novas entradas; reset (deliberado) retoma."""
        import json
        from pathlib import Path

        ctrl = Path(__file__).resolve().parent.parent / "state" / "control.json"
        if not ctrl.exists():
            return
        try:
            data = json.loads(ctrl.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return
        action = data.get("action")
        if action == "halt" and not self.risk.halted:
            self.risk.trip_kill_switch(f"MCP: {data.get('reason', 'halt manual')}")
        elif action == "reset" and self.risk.halted:
            self.risk.reset_kill_switch()
        elif action == "reset_cooldown":
            # Reset manual de cooldown por símbolo (25/07/2026) — mesmo canal
            # desacoplado MCP->control.json->engine do halt/reset do kill
            # switch. Symbol ausente/vazio: ignora (sem símbolo não há o que
            # liberar); reset_cooldown() já trata símbolo sem cooldown ativo
            # como no-op (só loga aviso).
            symbol = data.get("symbol")
            if symbol:
                self.risk.reset_cooldown(symbol)
        # consome o sinal para não reaplicar todo ciclo
        try:
            ctrl.unlink()
        except OSError:
            pass

    def run_once(self) -> None:
        self._apply_control_signal()
        state = self._portfolio_state()
        self.risk.check_portfolio_health(state)

        # TP em spot roda mesmo com kill switch ativo: não é entrada nova,
        # é saída de uma posição já existente (mesma lógica do stop, que
        # também nunca é bloqueado pelo kill switch — decisão #B de 16/07).
        self._check_spot_exits()

        if self.risk.halted:
            log.error("Engine pausado pelo kill switch. Aguardando reset manual.")
            return

        profiles = self.cfg["trading"]["profiles"]
        # Símbolos "ocupados": já têm posição na exchange OU entrada aprovada
        # NESTE ciclo. Sem isto, daytrade e swing podiam aprovar LONG e SHORT
        # do mesmo símbolo no mesmo ciclo — em modo one-way da Bybit, a segunda
        # ordem não abre hedge: ela reduz/inverte a primeira.
        busy: set[str] = set(self._open_symbols)
        for cfg_symbol in self.cfg["trading"]["symbols"]:
            symbol = self._market_symbol(cfg_symbol)
            for profile_name, pcfg in profiles.items():
                if not pcfg.get("enabled", False):
                    continue
                if symbol in busy:
                    log.info("PULADO %s/%s: símbolo já com posição/entrada neste ciclo",
                             symbol, profile_name)
                    audit("symbol_skipped", symbol=symbol, profile=profile_name,
                          reason="posição já aberta ou entrada aprovada neste ciclo")
                    continue
                try:
                    snap = build_snapshot(self.client, symbol, pcfg["timeframe"])

                    # Gate de candle (só na camada LLM): o snapshot decide sobre
                    # o último candle FECHADO; se ele é o mesmo da última
                    # decisão deste símbolo/perfil, o sinal seria idêntico —
                    # não paga uma chamada de Claude para reouvir a mesma
                    # resposta. Determinística fica fora do gate de propósito.
                    llm_gate = self._decision_cfg.get("strategy") == "llm"
                    candle_ts = int(snap.candles.iloc[-1]["ts"])
                    gate_key = (symbol, profile_name)
                    if llm_gate and self._last_decided_candle.get(gate_key) == candle_ts:
                        log.debug("Candle %s inalterado p/ %s/%s — LLM não é rechamado",
                                  candle_ts, symbol, profile_name)
                        continue

                    if llm_gate:
                        # Só constrói contexto quando alguém de fato vai lê-lo.
                        # Achado da revisão adversarial de 22/07/2026 (decisão
                        # #G): sem este gate, o BybitDerivativesProvider novo
                        # (funding/open interest/long-short ratio da Bybit)
                        # fazia até 3 chamadas de rede REAIS por símbolo×perfil
                        # em TODO ciclo (~65s), mesmo com a estratégia
                        # determinística (que nunca lê snap.context) — custo
                        # de latência/rate-limit real na produção viva por um
                        # dado 100% descartado. DossierMacroProvider/
                        # DossierOnChainProvider são baratos (leitura de
                        # arquivo local) e toleravam isso; o provider novo não.
                        snap.context = self.context.build(symbol)  # macro/on-chain/derivativos p/ o Claude
                    strategy = self._build_strategy(profile_name)
                    signal = strategy.generate(snap)
                    if llm_gate:
                        # Marca DEPOIS do sinal sair: falha na chamada (rede/
                        # LLM) cai no except abaixo sem marcar, e o próximo
                        # ciclo (~65s) tenta o MESMO candle de novo em vez de
                        # perder a janela inteira de 15 minutos.
                        self._last_decided_candle[gate_key] = candle_ts

                    decision = self.risk.evaluate(
                        signal,
                        state,
                        funding_rate=snap.funding_rate,
                        data_age_sec=snap.age_sec(),
                        profile=profile_name,
                    )
                    if decision.approved:
                        # Fail-closed: o símbolo fica ocupado JÁ na aprovação,
                        # ANTES da execução. Quando a execução falhava (visto na
                        # testnet em 15/07: PermissionDenied na 1ª entrada do
                        # ETH), o símbolo não era marcado e o perfil seguinte
                        # aprovava a direção OPOSTA no mesmo ciclo — em one-way,
                        # a 2ª ordem não abre hedge: reduz/inverte a 1ª. Custo do
                        # fail-closed: uma falha bloqueia o símbolo só até o
                        # próximo ciclo (busy é reconstruído da exchange).
                        busy.add(symbol)
                    result = self.executor.execute(signal, decision)
                    if decision.approved and result is not None:
                        # Reflete a entrada recém-aprovada no estado usado pelas
                        # PRÓXIMAS avaliações deste mesmo ciclo. Sem isto, os
                        # limites agregados (posições, nocional, risco somado)
                        # só valiam entre ciclos: num único ciclo era possível
                        # aprovar 4 entradas cheias e estourar o teto de exposição.
                        # (Fica condicionado ao SUCESSO da execução de propósito:
                        # entrada que falhou não existe na exchange, não deve
                        # consumir teto de posições/nocional.)
                        state.open_positions += 1
                        state.total_notional += decision.position_size * signal.entry_price
                        state.aggregate_risk_pct += self.cfg["per_trade"]["risk_pct"]
                except Exception as exc:  # noqa: BLE001
                    # Falha num símbolo/perfil NÃO derruba o resto do ciclo.
                    # Antes, um erro de rede no 1º símbolo abortava a avaliação
                    # dos demais (e, em --once, matava o processo com traceback).
                    log.exception("Erro em %s/%s: %s", symbol, profile_name, exc)
                    audit("symbol_cycle_error", symbol=symbol,
                          profile=profile_name, error=str(exc))

    def run_forever(self, interval_sec: int = 60) -> None:
        env = get_environment()
        log.info("Engine iniciando em %s | DRY_RUN=%s", env.upper(), self.executor.dry_run)
        audit("engine_start", environment=env, dry_run=self.executor.dry_run)
        try:
            while True:
                try:
                    self.run_once()
                except Exception as exc:  # noqa: BLE001
                    # Erro num ciclo não derruba o loop; é logado e o ciclo é pulado.
                    log.exception("Erro no ciclo: %s", exc)
                    audit("cycle_error", error=str(exc))
                time.sleep(interval_sec)
        except KeyboardInterrupt:
            log.warning("Interrompido pelo operador (Ctrl+C). Encerrando.")
            audit("engine_stop", reason="manual")
