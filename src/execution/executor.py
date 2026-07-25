"""Execução de ordens APROVADAS pela camada de risco.

Toda entrada é acompanhada do seu stop de proteção na mesma operação — nunca
abre posição 'nua'. Em DRY_RUN não envia nada à exchange (apenas loga), o que
permite paper trading puro mesmo conectado à testnet.
"""
from __future__ import annotations

from src.execution import protection_state
from src.exchange.bybit_client import BybitClient
from src.logger import audit, get_logger
from src.risk.risk_manager import RiskDecision
from src.strategy.signal import Direction, Signal

log = get_logger("executor")


class Executor:
    def __init__(self, client: BybitClient, dry_run: bool = True,
                 market_type: str = "perp") -> None:
        self.client = client
        self.dry_run = dry_run
        # "perp" | "spot" (decisão #E). No spot: sem set_leverage (não existe),
        # entrada a mercado leva o preço de referência (contas clássicas da
        # Bybit exigem custo p/ market-buy) e proteções não levam reduceOnly.
        self.market_type = market_type
        if dry_run:
            log.info("Executor em DRY_RUN — nenhuma ordem real será enviada")

    def execute(self, signal: Signal, decision: RiskDecision) -> dict | None:
        if not decision.approved:
            return None

        side = "buy" if signal.direction == Direction.LONG else "sell"
        size = decision.position_size

        if self.dry_run:
            log.info(
                "[DRY_RUN] %s %.6f %s @~%.2f | stop=%.2f tp=%s lev=%dx",
                side, size, signal.symbol, signal.entry_price,
                decision.stop_price,
                f"{signal.take_profit:.2f}" if signal.take_profit else "-",
                decision.leverage,
            )
            audit("dry_run_order", symbol=signal.symbol, side=side, size=size,
                  stop=decision.stop_price, take_profit=signal.take_profit,
                  leverage=decision.leverage)
            return {"dry_run": True, "side": side, "size": size}

        # Execução real (testnet ou mainnet conforme config do client).
        if self.market_type != "spot":
            self.client.set_leverage(signal.symbol, decision.leverage)
        # Saldo base ANTES da compra — referência pra medir exatamente quanto
        # ESTA entrada credita (ver protect_size abaixo). Lido cedo, antes da
        # ordem, pra não competir com a própria compra por uma foto do saldo.
        free_before = None
        if self.market_type == "spot":
            try:
                free_before = self.client.fetch_free_base(signal.symbol)
            except Exception as exc:  # noqa: BLE001
                log.warning("Sem leitura de saldo base PRÉ-entrada em %s: %s "
                            "— proteção cai no clamp conservador (size teórico)",
                            signal.symbol, exc)

        # No spot, market-buy precisa do preço de referência para contas
        # clássicas (o ccxt calcula o custo amount*price); em conta unificada
        # ele apenas define o custo do mesmo jeito. Sem efeito em perp.
        entry_price = signal.entry_price if self.market_type == "spot" else None
        entry = self.client.create_order(signal.symbol, side, size,
                                         order_type="market", price=entry_price)
        # Preço médio de fill: alguns caminhos do ccxt não devolvem
        # average/price na resposta de CRIAÇÃO de ordem a mercado (visto ao
        # vivo em 17/07 e de novo em 19/07 — BTC e ETH, os dois com entry_price
        # aproximado em vez do fill real). Antes de cair no preço do sinal
        # (só um proxy, usado no próprio sizing — pode divergir >1% do fill
        # real quando o preço se move entre o sinal e a execução), tenta
        # confirmar o preço REAL reconsultando a própria ordem — mesma
        # técnica já usada em engine._resolve_entry_price/
        # _handle_spot_position_closed pra confirmar fills de stop. Uma
        # ordem a MERCADO já deve estar fechada por essa altura, então a
        # consulta tem alta chance de vir com average/price populado mesmo
        # quando a resposta de criação não trouxe.
        fill_price = entry.get("average") or entry.get("price")
        if not fill_price:
            try:
                confirmed = self.client.fetch_order(entry.get("id"), signal.symbol)
                fill_price = confirmed.get("average") or confirmed.get("price")
            except Exception as exc:  # noqa: BLE001
                log.warning("Sem confirmação do preço de entrada via fetch_order "
                            "de %s (%s): %s", signal.symbol, entry.get("id"), exc)
            fill_price = fill_price or signal.entry_price

        # Re-ancora stop/TP no preço REAL do fill (achado 20/07, visto ao
        # vivo num loop de reentrada): stop_price/take_profit são calculados
        # pela estratégia em cima de signal.entry_price — o close do último
        # candle FECHADO (market_data.build_snapshot), não o preço ao vivo. O
        # sinal só é recalculado quando o candle vira, então dentro do MESMO
        # candle o preço de referência fica parado enquanto o mercado se
        # move de verdade. Se o fill real vier bem diferente (visto ao vivo:
        # ~565 USDT de diferença em ~2s, logo após um TP disparar), o TP
        # calculado no preço velho podia ficar ABAIXO do próprio preço de
        # entrada real — a posição abria já "no alvo", fechava no ciclo
        # seguinte por um lucro de centavos e a taxa de ida+volta virava
        # prejuízo líquido, repetindo a cada ciclo enquanto o sinal
        # continuasse válido (3 rodadas seguidas ao vivo, só interrompido
        # por um kill switch manual). Desloca stop/TP pela MESMA distância
        # do desvio sinal->fill: preserva a distância de risco em USDT que o
        # RiskManager usou pra dimensionar a posição (o motivo original do
        # clamp), só re-centralizada no preço que realmente aconteceu —
        # garante TP sempre do lado lucrativo da entrada real.
        price_drift = fill_price - signal.entry_price
        stop_price = decision.stop_price + price_drift
        take_profit = signal.take_profit + price_drift if signal.take_profit else None

        # Quantidade a PROTEGER (revisão adversarial de 15/07 + achado 19/07):
        # no spot a compra credita uma quantidade DIFERENTE do size teórico —
        # pode ser MENOS (fee cobrada na moeda recebida) ou MAIS (o preço real
        # do fill veio melhor que o preço do sinal usado no sizing — compra por
        # CUSTO em USDT credita mais base quando o preço cai entre sinal e
        # fill; visto ao vivo em 19/07: ETH sizeu 1,07305 teórico mas o fill
        # real creditou 1,08310 — 0,01 ETH real ficando de fora do stop).
        # free_after - free_before é a quantidade REAL creditada por ESTA
        # entrada — ao contrário de usar free_after sozinho (achado da
        # revisão adversarial de 17/07: saldo alheio pré-existente, ex. dust
        # de brinde de testnet, não pode ser confundido com a posição do
        # bot), a DIFERENÇA cancela qualquer saldo que já estava lá antes,
        # então é seguro mesmo com dust de outra origem na mesma moeda-base.
        def _read_protect_size() -> float:
            """Lê o saldo base ATUAL e devolve quanto proteger desta entrada
            (free_after - free_before, imune a dust alheio pré-existente —
            mesma lógica de sempre). Isolada em função pra poder ser chamada
            de novo na reconfirmação abaixo, sem duplicar a conta."""
            try:
                free_now = self.client.fetch_free_base(signal.symbol)
            except Exception as exc:  # noqa: BLE001
                log.warning("Sem leitura de saldo base pós-entrada em %s: %s "
                            "— usando size teórico", signal.symbol, exc)
                return size
            if free_before is None:
                # Sem foto PRÉ-entrada: não dá pra isolar o que é desta
                # entrada do que já estava na carteira — cai no clamp antigo,
                # nunca protege mais que o teórico (conservador).
                return min(size, free_now)
            return max(0.0, free_now - free_before)

        protect_size = (self.client.amount_to_precision(signal.symbol, _read_protect_size())
                        if self.market_type == "spot" else size)

        # Até 2 tentativas em spot: a leitura de saldo logo após a compra pode
        # vir atrasada/racy na exchange sob reentrada rápida (achado ao vivo em
        # 21/07 — protect_size saindo 0 em rajadas de compra/stop de poucos
        # segundos, disparando naked_position_close_failed sem NUNCA
        # reconfirmar o saldo real antes de desistir — o "nunca posição nua"
        # tinha um furo: confiava cegamente na 1ª leitura). Perp não sofre
        # desse atraso (sem esse conceito de saldo-base) — mantém 1 tentativa,
        # comportamento idêntico ao de sempre.
        max_attempts = 2 if self.market_type == "spot" else 1
        stop = None
        last_exc: Exception | None = None
        for attempt in range(max_attempts):
            try:
                if protect_size <= 0:
                    raise RuntimeError(
                        f"saldo base insuficiente para proteger ({protect_size})")
                stop = self.client.set_stop_loss(signal.symbol, side, protect_size,
                                                 stop_price)
                last_exc = None
                break
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                if attempt + 1 < max_attempts:
                    log.warning("Stop falhou em %s (%s) — reconfirmando saldo "
                                "antes de declarar sem proteção", signal.symbol, exc)
                    protect_size = self.client.amount_to_precision(
                        signal.symbol, _read_protect_size())

        if last_exc is not None:
            exc = last_exc
            # Regra da casa: NUNCA posição nua. Se o stop falhou depois da
            # entrada preenchida (mesmo após reconfirmar o saldo), desfaz a
            # entrada na hora e escala o erro. O evento de auditoria só é
            # gravado se o fechamento SUCEDER — antes, a trilha registrava
            # naked_position_close mesmo quando a venda de emergência
            # falhava (mentira perigosa: dizia "fechado" com o holding
            # ainda nu).
            log.critical("Stop falhou após entrada em %s — fechando posição: %s",
                         signal.symbol, exc)
            close_side = "sell" if side == "buy" else "buy"
            close_size = protect_size if self.market_type == "spot" else size
            close_params = {} if self.market_type == "spot" else {"reduceOnly": True}
            try:
                if close_size <= 0:
                    raise RuntimeError("nada fechável (saldo base zerado)")
                self.client.create_order(signal.symbol, close_side, close_size,
                                         order_type="market", params=close_params)
            except Exception as close_exc:  # noqa: BLE001
                log.critical("FECHAMENTO DE EMERGÊNCIA FALHOU em %s — POSIÇÃO "
                             "NUA NA EXCHANGE, intervir manualmente: %s",
                             signal.symbol, close_exc)
                audit("naked_position_close_failed", symbol=signal.symbol,
                      side=side, size=close_size, stop_error=str(exc),
                      close_error=str(close_exc))
                raise
            audit("naked_position_close", symbol=signal.symbol, side=side,
                  size=close_size, error=str(exc))
            raise

        # Take-profit (decisão #F de 15/07/2026): a estratégia sempre emitiu TP,
        # o backtest sempre o honrou, mas o executor o ignorava. O TP é proteção
        # OPCIONAL: se falhar, a posição continua protegida pelo stop — loga/
        # audita e segue (contraste deliberado com o stop, que é obrigatório).
        # SPOT: TP não é colocado como ordem — o stop já OCUPOU o saldo base
        # na colocação (tpslOrder) e a Bybit spot não tem OCO; uma segunda
        # condicional seria rejeitada sempre. Registrado como
        # take_profit_skipped e o alvo é salvo em protection_state.py: o
        # engine confere o preço a cada ciclo e fecha por software quando
        # atingido (ver engine.py:_check_spot_exits, 17/07/2026).
        tp = None
        if self.market_type == "spot":
            if take_profit:
                log.info("TP não armado em spot (%s): sem OCO, o stop ocupa o "
                         "saldo — engine confere o alvo a cada ciclo (saída "
                         "por software, ver protection_state.py)",
                         signal.symbol)
                audit("take_profit_skipped", symbol=signal.symbol,
                      take_profit=take_profit,
                      reason="spot sem OCO — saldo base ocupado pelo stop")
            # A proteção é salva SEMPRE em spot (20/07) — não só quando há TP
            # fixo: com trailing a posição não tem alvo fixo, e a saída por
            # sinal também precisa do registro (profile). O arquivo é o
            # registro da posição, não só do alvo de TP.
            trail_distance = None
            peak_price = None
            if signal.trailing:
                # Distância do trailing = a distância de risco REAL no fill
                # (mesma que o stop re-ancorado usa) — o pico começa no
                # próprio fill; o engine sobe o stop conforme o pico avança.
                trail_distance = abs(fill_price - stop_price)
                peak_price = fill_price
            protection_state.set_protection(
                signal.symbol, entry_price=fill_price,
                take_profit=take_profit, stop_price=stop_price,
                size=protect_size, stop_id=stop.get("id"),
                # profile: a saída por SINAL (20/07) precisa saber qual
                # perfil abriu a posição pra consultar a estratégia e o
                # timeframe certos no ciclo de saída.
                profile=signal.profile,
                trailing=signal.trailing, trail_distance=trail_distance,
                peak_price=peak_price)
        elif take_profit:
            try:
                tp = self.client.set_take_profit(signal.symbol, side, size,
                                                 take_profit)
            except Exception as exc:  # noqa: BLE001
                log.warning("Take-profit falhou em %s (posição segue "
                            "protegida pelo stop): %s", signal.symbol, exc)
                audit("take_profit_failed", symbol=signal.symbol, side=side,
                      size=size, take_profit=take_profit,
                      error=str(exc))

        audit("order_executed", symbol=signal.symbol, side=side, size=size,
              protect_size=protect_size,
              entry_price=fill_price,
              stop_price=stop_price, take_profit=take_profit,
              entry_id=entry.get("id"), stop_id=stop.get("id"),
              tp_id=tp.get("id") if tp else None,
              # profile/trailing: backfill_from_audit reconstrói a proteção a
              # partir deste evento — sem os campos, uma posição recuperada
              # da trilha perderia a saída por sinal/trailing (20/07).
              profile=signal.profile,
              trailing=signal.trailing,
              trail_distance=(abs(fill_price - stop_price) if signal.trailing else None),
              peak_price=(fill_price if signal.trailing else None),
              testnet=self.client.is_testnet)
        log.info("Ordem executada %s %s (testnet=%s)", side, signal.symbol, self.client.is_testnet)
        return {"entry": entry, "stop": stop, "take_profit": tp}
