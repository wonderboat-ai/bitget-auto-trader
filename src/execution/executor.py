"""Execução de ordens APROVADAS pela camada de risco.

Toda entrada é acompanhada do seu stop de proteção na mesma operação — nunca
abre posição 'nua'. Em DRY_RUN não envia nada à exchange (apenas loga), o que
permite paper trading puro mesmo conectado à testnet.
"""
from __future__ import annotations

import time

from src.execution import protection_state
from src.exchange.bitget_client import BitgetClient
from src.logger import audit, get_logger
from src.risk.risk_manager import RiskDecision
from src.strategy.signal import Direction, Signal

log = get_logger("executor")


class Executor:
    def __init__(self, client: BitgetClient, dry_run: bool = True,
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
        # A PROTEÇÃO NASCE JUNTO COM A ENTRADA (Bitget, 20/08/2026).
        # Isto substitui o `set_stop_loss` separado da era Bybit e é a única
        # forma de criar a proteção aqui: na Bitget, stop e take-profit são UMA
        # ordem (`type: "tpsl"`, um orderId com os dois gatilhos) e ela só é
        # criável ANEXADA à ordem de entrada — não existe caminho no ccxt para
        # criar uma tpsl de duas pernas depois do fill.
        # Consequência boa: some a janela entre "posição aberta" e "stop armado"
        # que obrigava o fechamento de emergência a existir na Bybit. Ela não
        # some de vez (a tpsl pode não aparecer — ver a checagem adiante), mas
        # deixa de ser o caminho normal.
        # Os gatilhos vão como DICTS de propósito: `stopLossPrice`/
        # `takeProfitPrice` PLANOS caem noutro branch do ccxt que usa
        # `if stop / elif takeProfit` e DESCARTA a segunda perna em silêncio —
        # a posição nasceria sem TP, ou sem stop, sem erro nenhum.
        # `price=None` também importa: com preço, a perna vira stop LIMIT, que
        # não preenche num gap.
        entry_params: dict = {}
        if self.market_type != "spot":
            entry_params["stopLoss"] = {"triggerPrice": decision.stop_price}
            if signal.take_profit:
                entry_params["takeProfit"] = {"triggerPrice": signal.take_profit}
        entry = self.client.create_order(signal.symbol, side, size,
                                         order_type="market", price=entry_price,
                                         params=entry_params or None)
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
            if not fill_price:
                # Na Bitget este fallback deixou de ser raro: `create_order`
                # responde só {orderId, clientOid}, então average/price vêm
                # SEMPRE vazios e o `fetch_order` acima é o único caminho para o
                # preço real. Cair aqui significa usar o close do último candle
                # fechado como se fosse o fill — é o insumo do drift logo abaixo
                # e do PnL de todo o trade. Antes isso era 100% mudo.
                audit("entry_price_unconfirmed", symbol=signal.symbol,
                      entry_id=entry.get("id"), fallback_price=signal.entry_price)
                fill_price = signal.entry_price

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

        # amount_to_precision também em PERP (antes só spot passava por aqui):
        # o step do BTC na Bitget é 0.0001 e um tamanho fora do step é
        # rejeitado. Sem isto, o `size` cru do RiskManager chega à exchange.
        protect_size = self.client.amount_to_precision(
            signal.symbol,
            _read_protect_size() if self.market_type == "spot" else size)

        # Até 2 tentativas em spot: a leitura de saldo logo após a compra pode
        # vir atrasada/racy na exchange sob reentrada rápida (achado ao vivo em
        # 21/07 — protect_size saindo 0 em rajadas de compra/stop de poucos
        # segundos, disparando naked_position_close_failed sem NUNCA
        # reconfirmar o saldo real antes de desistir — o "nunca posição nua"
        # tinha um furo: confiava cegamente na 1ª leitura). Perp não sofre
        # desse atraso (sem esse conceito de saldo-base) — mantém 1 tentativa,
        # comportamento idêntico ao de sempre.
        # Nota (27/07, achado durante a transição pra mainnet): este retry
        # trata QUALQUER exceção de set_stop_loss como se fosse a race de
        # saldo acima — mas a partir de 13:59 UTC de hoje a Bybit passou a
        # bloquear a criação de condicional (stopLossPrice/tpslOrder) em spot
        # por compliance (retCode 10024/KYC_PROMPT_TOAST, mesmo código já
        # visto no rearm do trailing — ver CLAUDE.md). Se for essa a causa,
        # a reconfirmação de saldo é inócua e a 2ª tentativa falha pelo MESMO
        # motivo (determinístico, não uma race) — sem gap de proteção real,
        # já que o fechamento de emergência abaixo usa ordem a MERCADO
        # simples (sem stopLossPrice/tpslOrder), não afetada por esse
        # bloqueio. Não corrigido (nenhum comportamento muda) — só
        # documentado aqui e no log de retry abaixo pra não confundir quem
        # diagnosticar um caso assim ao vivo.
        # A proteção já foi PEDIDA junto com a entrada. O que falta é CONFIRMAR
        # que ela existe de verdade na exchange e descobrir o id dela — o
        # `tpsl_id`, que o engine vai usar para mover o stop e para apurar o
        # fechamento. Confirmar por leitura, nunca pela resposta do POST, é a
        # lição do bug #23.
        #
        # Duas tentativas com pausa no meio: uma leitura única logo após a ordem
        # pode vir atrasada e a tpsl ainda não estar indexada — é exatamente o
        # bug #29 (declarar "sem proteção" sem nunca reconfirmar), que na Bybit
        # gerou `naked_position_close_failed` com a posição na verdade protegida.
        max_attempts = 2
        tpsl: dict | None = None
        last_exc: Exception | None = None
        for attempt in range(max_attempts):
            try:
                if protect_size <= 0:
                    raise RuntimeError(
                        f"tamanho insuficiente para proteger ({protect_size})")
                found = self.client.fetch_position_tpsl(signal.symbol)
                if not found or not found.get("id"):
                    raise RuntimeError("proteção tpsl não encontrada após a entrada")
                if not found.get("stop_trigger"):
                    # Guard truthy: uma tpsl só com a perna de TP deixa a
                    # posição sem stop — pior que não ter proteção nenhuma,
                    # porque PARECE protegida.
                    raise RuntimeError(f"tpsl {found['id']} sem perna de stop-loss")
                tpsl = found
                last_exc = None
                break
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                if attempt + 1 < max_attempts:
                    log.warning("Proteção não confirmada em %s (%s) — "
                                "reconsultando antes de declarar sem proteção",
                                signal.symbol, exc)
                    time.sleep(1.5)
                    if self.market_type == "spot":
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

        # O take-profit NÃO é armado aqui — ele nasceu junto com a entrada, na
        # mesma ordem tpsl. Todo o bloco `set_take_profit` da era Bybit saiu, e
        # com ele os eventos `take_profit_failed`/`take_profit_skipped`: não há
        # mais um passo separado que possa falhar sozinho.
        tp = None

        # RE-ANCORAGEM PÓS-FATO (bug #26, adaptado).
        # A tpsl foi criada com os preços calculados sobre `signal.entry_price`
        # — o close do último candle FECHADO —, porque o fill real só é
        # conhecido depois. Se o mercado andou dentro do mesmo candle (visto ao
        # vivo na Bybit: ~565 USDT em ~2s), o TP pode nascer do lado errado da
        # entrada real e a posição abre já "no alvo", fecha por centavos no
        # ciclo seguinte e a fee de ida+volta vira prejuízo — repetindo
        # enquanto o sinal continuar válido.
        # Na Bybit isso era corrigido ANTES de armar; aqui a proteção já existe,
        # então corrigimos por modificação. Falhar aqui NÃO é motivo para fechar
        # a posição: ela está protegida, só com os gatilhos deslocados pelo
        # drift. Audita e segue — fechar seria pior que o problema.
        if self.market_type != "spot" and price_drift:
            for rotulo, mover, alvo in (
                ("stop", self.client.move_stop_loss, stop_price),
                ("take_profit", self.client.move_take_profit, take_profit),
            ):
                if alvo is None:
                    continue
                try:
                    mover(tpsl["id"], signal.symbol, alvo)
                except Exception as exc:  # noqa: BLE001
                    log.warning("Re-ancoragem do %s falhou em %s (posição segue "
                                "protegida, gatilho deslocado pelo drift): %s",
                                rotulo, signal.symbol, exc)
                    audit("protection_reanchor_failed", symbol=signal.symbol,
                          leg=rotulo, target=alvo, price_drift=price_drift,
                          tpsl_id=tpsl["id"], error=str(exc))

        # Proteção persistida SEMPRE, spot e perp (28/07/2026 — antes só
        # spot persistia aqui, pro TP por software). Perp precisa igualmente:
        # sem isto, engine.py não tem como detectar/auditar quando o stop ou
        # o TP real dispara, nem cancelar a ordem irmã que fica órfã (achado
        # ao vivo em 28/07/2026, primeira vez que perp operou de verdade
        # neste projeto — ver engine.py:_check_perp_exits). trail_distance/
        # peak_price também servem aos dois modos: começam no próprio fill;
        # quem sobe/desce o stop com o preço é o engine (spot desde 20/07;
        # perp desde 28/07 — ver engine.py:_update_perp_trailing_stop).
        trail_distance = None
        peak_price = None
        if signal.trailing:
            trail_distance = abs(fill_price - stop_price)
            peak_price = fill_price
        protection_state.set_protection(
            signal.symbol, entry_price=fill_price,
            take_profit=take_profit, stop_price=stop_price,
            # stop_id guarda o TPSL_ID — na Bitget stop e take-profit são a
            # mesma ordem, então há um id só. `tp_id` fica None por construção
            # (o campo sobrevive no schema por compatibilidade com arquivos
            # antigos e com backfill_from_audit, não porque exista uma 2ª ordem).
            size=protect_size, stop_id=tpsl["id"],
            tp_id=None,
            # side (28/07/2026): "long"/"short" — necessário pro PnL e pro
            # trailing terem o sinal certo (short lucra com o preço caindo;
            # o stop desce em vez de subir). Perp agora suporta os dois.
            side="long" if signal.direction == Direction.LONG else "short",
            # profile: a saída por SINAL (20/07, spot) precisa saber qual
            # perfil abriu a posição pra consultar a estratégia/timeframe
            # certos no ciclo de saída.
            profile=signal.profile,
            trailing=signal.trailing, trail_distance=trail_distance,
            peak_price=peak_price,
            # opened_ts: âncora temporal pra fetch_last_close_fill (engine.py)
            # não consultar fetch_my_trades sem janela nenhuma — o timestamp
            # da própria ordem de entrada quando disponível, senão o instante
            # local (aproximação aceitável: um fill de ordem ANTERIOR nunca
            # fica mais recente que "agora").
            opened_ts=entry.get("timestamp") or int(time.time() * 1000))

        audit("order_executed", symbol=signal.symbol, side=side, size=size,
              protect_size=protect_size,
              entry_price=fill_price,
              stop_price=stop_price, take_profit=take_profit,
              entry_id=entry.get("id"), stop_id=tpsl["id"],
              tp_id=None,
              # profile/trailing: backfill_from_audit reconstrói a proteção a
              # partir deste evento — sem os campos, uma posição recuperada
              # da trilha perderia a saída por sinal/trailing (20/07).
              profile=signal.profile,
              trailing=signal.trailing,
              trail_distance=(abs(fill_price - stop_price) if signal.trailing else None),
              peak_price=(fill_price if signal.trailing else None),
              # opened_ts: sem isto na trilha, uma posição recuperada via
              # backfill_from_audit (arquivo de estado perdido) voltaria a
              # rodar sem âncora temporal — fetch_last_close_fill recusaria
              # responder por segurança, mas não precisa.
              opened_ts=entry.get("timestamp") or int(time.time() * 1000),
              testnet=self.client.is_testnet)
        log.info("Ordem executada %s %s (testnet=%s)", side, signal.symbol, self.client.is_testnet)
        # `stop`/`tp` da era Bybit eram ordens separadas; na Bitget a proteção
        # inteira é `tpsl` (uma ordem, dois gatilhos) — devolvida nas duas
        # chaves porque nenhum chamador (engine.py:1652) olha o conteúdo, só
        # `result is not None`.
        return {"entry": entry, "stop": tpsl, "take_profit": tpsl}
