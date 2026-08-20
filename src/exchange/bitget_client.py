"""Wrapper fino sobre o CCXT para a Bitget (perpétuos USDT, conta UTA).

Responsabilidades:
  - Expor leitura de mercado (OHLCV, ticker, funding) e conta (equity, posições).
  - Centralizar colocação/modificação/cancelamento de ordens com client order id
    idempotente.

NÃO contém lógica de risco nem de estratégia — só fala com a exchange.

------------------------------------------------------------------------------
LEIA ISTO ANTES DE MEXER — três fatos da Bitget que não têm análogo na Bybit e
que mudam o desenho inteiro. Todos foram MEDIDOS contra a conta real em
20/08/2026 (ver `probe_bitget.py` e o topo do CLAUDE.md), não inferidos:

1. **A conta é UTA e a API clássica é BLOQUEADA nela** (erro 40085). Toda rota
   vai por v3. `options['uta'] = True` no __init__ é a linha mais importante
   deste arquivo — ver o comentário lá.

2. **Stop e take-profit são UMA ordem só** (`type: "tpsl"`, um `orderId` com os
   dois gatilhos), criada ANEXADA à ordem de entrada. Consequências:
   - não existe "ordem irmã órfã" — o bug #49 da Bybit não é alcançável aqui;
   - a Bitget cancela a tpsl sozinha quando a posição zera (medido);
   - `set_stop_loss`/`set_take_profit` da Bybit NÃO têm equivalente e foram
     deliberadamente removidos: criar uma proteção "avulsa" na Bitget gera uma
     strategy order SEPARADA, que duplicaria a proteção já anexada.

3. **Mover o stop é atômico** (`move_stop_loss`): uma chamada que preserva o
   take-profit e não muda o `orderId`. Na Bybit era cancelar+recriar+re-armar,
   com uma janela real sem proteção no meio.
------------------------------------------------------------------------------
"""
from __future__ import annotations

import math
import time
import uuid
from typing import Any

import ccxt

from config.settings import ExchangeCredentials
from src.logger import audit, get_logger

log = get_logger("bitget_client")

# Categoria de produto da Bitget para perpétuos margeados em USDT. Passado
# explicitamente em toda chamada que o aceita: depender do `defaultSubType` do
# ccxt funciona por coincidência de default, não por contrato.
PRODUCT_TYPE = "USDT-FUTURES"

# Margem isolada por padrão. O default do ccxt é `cross` (bitget.py:5370-5373),
# e abrir em isolado para fechar em cross é receita de rejeição.
MARGIN_MODE = "isolated"

# Mantida só para compatibilidade de import com o caminho spot, que não é
# alcançável em perp (`engine.py:276-277` retorna antes). Ver os stubs no fim.
SPOT_DUST_USDT = 10.0

# "Order does not exist" — a Bitget levanta isto ao cancelar quando não há nada
# a cancelar. É resultado ESPERADO, não falha: tratar como erro geraria ruído
# permanente na trilha, que é exatamente a lição dos 13.759 `symbol_cycle_error`
# da Bybit.
ERR_ORDER_NOT_FOUND = "25204"


def _positive_float(value: Any) -> float | None:
    """Converte pra float só se o resultado for > 0; senão devolve None.

    Não é `if value:` nem `if value is not None:` — as duas classes de guard
    que este projeto já aprendeu que não bastam (bugs #20/#27). A Bitget
    devolve preço/quantidade ausente como a STRING `"0"`, que é truthy em
    Python e passaria pelos dois. Preço/quantidade zero nunca é um fill real
    — é ausência de dado disfarçada."""
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return f if f > 0 else None


class BitgetClient:
    def __init__(self, creds: ExchangeCredentials, default_type: str = "swap") -> None:
        if default_type != "swap":
            raise ValueError(
                f"BitgetClient só suporta perpétuos ('swap'), recebido {default_type!r}. "
                "O caminho spot não foi portado — ver os stubs no fim deste arquivo."
            )
        self.exchange = ccxt.bitget({
            "apiKey": creds.api_key,
            "secret": creds.api_secret,
            # A Bitget exige um terceiro segredo que a Bybit não tem: a
            # passphrase escolhida na criação da chave.
            "password": creds.passphrase,
            "enableRateLimit": True,
            "options": {
                "defaultType": default_type,
                # ---------------------------------------------------------
                # A LINHA MAIS IMPORTANTE DESTE ARQUIVO.
                # Sem ela, `handle_uta_and_params` (bitget.py:1936-1951)
                # descobre o tipo da conta fazendo uma chamada de rede e, num
                # `except Exception` genérico, assume NÃO-UTA e CACHEIA isso em
                # options['uta'] para o resto da vida do processo. Um único blip
                # de rede no boot roteia todas as chamadas seguintes para a API
                # clássica — que nesta conta responde 40085 em TUDO, até
                # reiniciar. É o bug #48 (medição única no boot envenenando o
                # processo inteiro) com outra roupa.
                # Com o bool fixo, a função retorna cedo e o autodetector nunca
                # roda.
                # ---------------------------------------------------------
                "uta": True,
                "adjustForTimeDifference": True,
            },
        })
        # NÃO chamar set_sandbox_mode: a Bitget não tem testnet via ccxt
        # (`urls['test']` é None) e a chamada levantaria NotSupported.
        # Sem isto, `amount_to_precision` cai no fallback "devolve cru" nos
        # primeiros ciclos, e um tamanho fora do step é rejeitado pela exchange.
        self.exchange.load_markets()
        try:
            self.exchange.load_time_difference()
        except Exception as exc:  # noqa: BLE001
            log.warning("Não foi possível medir a diferença de horário com o servidor: %s", exc)
        log.info("BitgetClient iniciado (MAINNET — DINHEIRO REAL)")

    @property
    def is_testnet(self) -> bool:
        """Sempre False: a Bitget não tem testnet via ccxt. Existe porque
        `executor.py` grava este valor no `order_executed` e o `state_reader`
        o converte no rótulo de ambiente da trilha."""
        return False

    @property
    def is_spot(self) -> bool:
        """Sempre False — ver o guard de `default_type` no __init__."""
        return False

    def _with_retry(self, fn: Any, *args: Any, retries: int = 3,
                    backoff: float = 1.0, **kwargs: Any) -> Any:
        """Reexecuta `fn` em erro de rede transitório ou timestamp desatualizado.

        NÃO retenta erro de negócio (credencial, parâmetro, saldo) — só falha de
        transporte. Alargar este `except` para `Exception` duplicaria ordem.

        `InvalidNonce` ganha tratamento especial, herdado do bug #48 da Bybit e
        igualmente aplicável aqui: `load_time_difference()` mede o offset
        local↔servidor com UMA requisição, só no boot; se essa medição pegar
        jitter, toda chamada assinada falha pelo resto da vida do processo.
        Re-sincronizar entre tentativas conserta de verdade — a Bitget mapeia
        40004/40005/40008 e "req_time is too much difference from server time"
        para InvalidNonce (bitget.py:1313-1317), e `nonce()` consome
        `options['timeDifference']` (10784-10785)."""
        last_exc: Exception | None = None
        for attempt in range(1, retries + 1):
            try:
                return fn(*args, **kwargs)
            except (ccxt.NetworkError, ccxt.RequestTimeout) as exc:
                last_exc = exc
                if attempt == retries:
                    break
                wait = backoff * (2 ** (attempt - 1))
                if isinstance(exc, ccxt.InvalidNonce):
                    log.warning(
                        "Timestamp desatualizado (tentativa %d/%d): %s — "
                        "re-sincronizando relógio antes de tentar de novo em %.1fs",
                        attempt, retries, exc, wait,
                    )
                    try:
                        self.exchange.load_time_difference()
                    except Exception as resync_exc:  # noqa: BLE001
                        log.warning("Falha ao re-sincronizar relógio: %s", resync_exc)
                else:
                    log.warning(
                        "Erro de rede transitório (tentativa %d/%d): %s — nova tentativa em %.1fs",
                        attempt, retries, exc, wait,
                    )
                time.sleep(wait)
        raise last_exc  # type: ignore[misc]

    # ----------------------- Mercado (leitura) -----------------------
    def fetch_ohlcv(self, symbol: str, timeframe: str, limit: int = 200) -> list[list[float]]:
        """Candles [timestamp, open, high, low, close, volume].

        `market_data.build_snapshot` faz `df.iloc[:-1]` para descartar o candle
        EM FORMAÇÃO (fix #10) — o que pressupõe que a exchange devolve o parcial
        na última posição. **VALIDADO na Bitget em 20/08**: às 19:30 UTC o último
        candle de 4h veio como 16:00 UTC, ou seja o ainda aberto. O corte segue
        correto. Se algum dia isso mudar, o sintoma é mudo e caro: todo sinal
        atrasaria um período inteiro (4h no swing) sem erro nenhum."""
        return self._with_retry(self.exchange.fetch_ohlcv, symbol,
                                timeframe=timeframe, limit=limit)

    def fetch_ticker(self, symbol: str) -> dict[str, Any]:
        """Ticker com `last` GARANTIDO.

        Levanta se não conseguir um preço, de propósito: `engine.py:611-612` faz
        `continue` mudo quando o preço vem None, então um ticker sem `last`
        pararia o trailing de andar sem deixar UM evento na trilha. Exceção pelo
        menos vira warning visível."""
        t = self._with_retry(self.exchange.fetch_ticker, symbol)
        if not t.get("last"):
            # Guard truthy: `0` aqui é dado ausente disfarçado, não preço.
            fallback = t.get("close") or (t.get("info") or {}).get("lastPr")
            if not fallback:
                raise ccxt.ExchangeError(f"ticker de {symbol} sem preço utilizável: {t!r}")
            t["last"] = float(fallback)
        return t

    def fetch_funding_rate(self, symbol: str) -> float | None:
        """Funding para o circuit breaker de RISCO. Nunca levanta: `None` faz o
        veto de funding simplesmente não se aplicar (semântica de "sem dado")."""
        try:
            fr = self._with_retry(self.exchange.fetch_funding_rate, symbol)
            return fr.get("fundingRate")
        except Exception as exc:  # noqa: BLE001
            log.warning("Falha ao buscar funding de %s: %s", symbol, exc)
            return None

    # ------------- Derivativos para CONTEXTO (decisão #G) -------------
    # Inertes hoje: só são chamados com `decision.strategy: llm` (o YAML está em
    # `deterministic`), então fazem ZERO chamada de rede na configuração atual.
    # Cada um trata a própria falha e devolve None — nunca levanta.
    # O guard "só devolve dict se o campo veio preenchido" é obrigatório e não é
    # zelo: um dict com valores None é truthy e passaria pelo `if funding:` de
    # quem chama como se fosse dado confirmado (classe dos bugs #20/#27).
    def fetch_derivatives_funding_rate(self, symbol: str) -> dict[str, Any] | None:
        try:
            fr = self._with_retry(self.exchange.fetch_funding_rate, symbol)
            rate = fr.get("fundingRate")
            if rate is None:
                return None
            return {"funding_rate": rate, "timestamp": fr.get("fundingDatetime")}
        except Exception as exc:  # noqa: BLE001
            log.warning("Falha ao buscar funding (contexto) de %s: %s", symbol, exc)
            return None

    def fetch_open_interest(self, symbol: str) -> dict[str, Any] | None:
        try:
            oi = self._with_retry(self.exchange.fetch_open_interest, symbol)
            amount = oi.get("openInterestAmount")
            if amount is None:
                return None
            return {"open_interest": amount, "timestamp": oi.get("datetime")}
        except Exception as exc:  # noqa: BLE001
            log.warning("Falha ao buscar open interest de %s: %s", symbol, exc)
            return None

    def fetch_long_short_ratio(self, symbol: str, timeframe: str = "1h") -> dict[str, Any] | None:
        """O ccxt não suporta `fetchLongShortRatio` para a Bitget (has[] é
        False) — só o histórico; pedimos limit=1 e usamos o ponto mais recente."""
        try:
            rows = self._with_retry(
                self.exchange.fetch_long_short_ratio_history,
                symbol, timeframe=timeframe, limit=1,
            )
            if not rows:
                return None
            ratio = rows[-1].get("longShortRatio")
            if ratio is None:
                return None
            return {"long_short_ratio": ratio, "timestamp": rows[-1].get("datetime")}
        except Exception as exc:  # noqa: BLE001
            log.warning("Falha ao buscar long/short ratio de %s: %s", symbol, exc)
            return None

    # ----------------------- Conta (leitura) -----------------------
    def fetch_balance_usdt(self) -> float:
        """Equity em USDT — com margem travada em posição E PnL não realizado.

        **NÃO usar `fetch_balance()` aqui, por mais tentador que pareça.** Na
        rota UTA o ccxt lê `data`, extrai só a lista `assets` e joga fora o
        bloco de equity (bitget.py:4380-4385); depois `parse_uta_balance` mapeia
        `total <- asset.balance` e ignora o campo `equity` de cada asset
        (4568-4570). Resultado: `fetch_balance()['USDT']['total']` devolve o
        saldo LIVRE — sem a margem presa na posição e sem o PnL aberto.
        MEDIDO em 20/08 com posição aberta: livre 286,7798 + margem 7,2617 +
        uPnL 0,0036 = 294,0451 = `usdtEquity`. Usar o `total` daria 286,78, e
        a diferença apareceria como drawdown FANTASMA — disparando o kill
        switch de 3% (cujo reset é MANUAL) sem nenhuma perda real. É exatamente
        o bug #3 da Bybit renascendo por outra porta.

        Levanta se o equity não vier: devolver 0.0 seria drawdown de 100%, e
        cair para o saldo livre é o próprio bug que este docstring evita.

        Dois cuidados que uma auditoria adversarial achou depois da 1ª versão
        (achado real, confirmado por verificação cética):
        (a) o guard `not in (None, "")` deixa passar `"0"`/`0` — que é dado
            AUSENTE disfarçado, não equity zero de verdade — e a função
            devolveria 0.0 contradizendo o próprio parágrafo acima. Trocado
            por guard POSITIVO.
        (b) o fallback antigo (`assets[].equity`) NÃO é a mesma grandeza que
            `usdtEquity`: no payload documentado do ccxt, `usdtEquity` é o
            equity TOTAL da conta convertido pra USDT (soma de todas as
            moedas), e `assets[coin=USDT].equity` é só a perna em USDT —
            divergem sempre que há saldo em outra moeda (ex.: BGB de desconto
            de fee, comum na Bitget). O fallback correto é `accountEquity`
            (mesma grandeza que `usdtEquity`, só a denominação difere)."""
        resp = self._with_retry(self.exchange.privateUtaGetV3AccountAssets, {})
        data = (resp or {}).get("data") or {}
        usdt_eq = _positive_float(data.get("usdtEquity"))
        if usdt_eq is not None:
            return usdt_eq
        account_eq = _positive_float(data.get("accountEquity"))
        if account_eq is not None:
            return account_eq
        # Zero só é aceito quando CONFIRMADO por duas fontes independentes —
        # senão "conta genuinamente vazia" fica indistinguível de "payload
        # degradado", que é exatamente o caso que este método existe pra evitar.
        if data.get("usdtEquity") in ("0", 0) and data.get("accountEquity") in ("0", 0):
            audit("equity_zero_confirmado", fonte="usdtEquity+accountEquity")
            return 0.0
        raise ccxt.ExchangeError(f"equity USDT ausente ou degradado: {data!r}")

    def fetch_open_positions(self) -> list[dict[str, Any]]:
        """Posições abertas — reconciliação de estado vem daqui, não da memória.

        O filtro de posição zerada fica AQUI (o engine não refaz)."""
        positions = self._with_retry(
            self.exchange.fetch_positions, None, {"category": PRODUCT_TYPE})
        out: list[dict[str, Any]] = []
        for p in positions:
            contracts = float(p.get("contracts") or 0)
            if contracts == 0:
                continue
            if not p.get("notional"):
                # `parse_position` calcula notional = qty * markPrice e deixa
                # vazio quando o markPrice não vem — e quando isso acontece,
                # `p["markPrice"]` e `p["info"]["markPrice"]` estão vazios pela
                # MESMA razão (é o mesmo dict cru), então o resgate por
                # markPrice abaixo era código morto: o único desfecho possível
                # era sempre `notional = 0.0`. Notional ausente SUBESTIMA a
                # exposição agregada que o risco usa no veto absoluto — com a
                # posição contando como exposição ZERO, o risco aprovaria uma
                # entrada nova que deveria vetar. Nunca devolver 0.0 em
                # silêncio: usar uma fonte de preço genuinamente independente
                # (entryPrice, sempre presente) antes de recorrer ao ticker.
                symbol = p.get("symbol")
                price = _positive_float(p.get("entryPrice"))
                fonte = "entry_price"
                if price is None:
                    try:
                        price = _positive_float(self.fetch_ticker(symbol)["last"])
                        fonte = "ticker_last"
                    except Exception as exc:  # noqa: BLE001
                        # NÃO pode propagar: fetch_open_positions roda dentro de
                        # _portfolio_state, no início do ciclo — uma exceção
                        # aqui abortaria a reconciliação de fechamento e o
                        # trailing da MESMA posição que estamos tentando medir.
                        log.warning("Sem preço para calcular notional de %s: %s",
                                    symbol, exc)
                if price is None:
                    p["notional"] = 0.0
                    audit("position_notional_unresolved", symbol=symbol,
                          contracts=contracts)
                else:
                    p["notional"] = contracts * price
                    audit("position_notional_degraded", symbol=symbol, fonte=fonte,
                          notional=p["notional"])
            out.append(p)
        return out

    # ----------------------- Ordens (escrita) -----------------------
    def create_order(
        self,
        symbol: str,
        side: str,
        amount: float,
        order_type: str = "market",
        price: float | None = None,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Cria ordem. Para ENTRADA COM PROTEÇÃO, passe os gatilhos como DICTS:

            params={"stopLoss":   {"triggerPrice": 71637.4},
                    "takeProfit": {"triggerPrice": 73808.2}}

        e mantenha `price=None`. Isso anexa as duas pernas à própria ordem de
        entrada, produzindo UMA ordem `tpsl`.

        **Nunca passe `stopLossPrice`/`takeProfitPrice` PLANOS aqui.** Eles caem
        noutro branch do ccxt (bitget.py:5083-5092) que cria uma strategy order
        SEPARADA e — pior — usa `if stop / elif takeProfit` (5158/5167),
        **descartando a segunda perna em silêncio**. A convenção é oposta à de
        `move_stop_loss`, que exige o param plano; é o erro mais fácil de
        cometer neste arquivo.

        `price` também não é inocente numa entrada protegida: com ele, a perna
        vira `slLimitPrice` + `slOrderType='limit'` (5162-5166), e stop limit
        não preenche num gap.

        O retorno traz `id`, mas NÃO traz preço de fill: a Bitget responde só
        `{orderId, clientOid}` (bitget.py:5116-5119), então `average`/`price`
        saem None SEMPRE. Quem precisa do preço real chama `fetch_order`."""
        params = dict(params or {})
        # A regra do parágrafo acima virou guard, não só comentário: passar os
        # planos aqui cairia num branch do ccxt que DESCARTA a segunda perna em
        # silêncio — abriria posição sem stop, ou sem TP, sem nenhum erro.
        if "stopLossPrice" in params or "takeProfitPrice" in params:
            raise ValueError(
                "create_order: use params['stopLoss']/['takeProfit'] como "
                "dicts, nunca 'stopLossPrice'/'takeProfitPrice' planos — "
                "a Bitget descarta a segunda perna em silêncio nesse branch."
            )
        for perna in ("stopLoss", "takeProfit"):
            leg = params.get(perna)
            if leg is None:
                continue
            trigger = leg.get("triggerPrice") if isinstance(leg, dict) else None
            if trigger is None or not math.isfinite(trigger) or trigger <= 0:
                raise ValueError(
                    f"create_order: params['{perna}'] precisa de "
                    f"{{'triggerPrice': <positivo>}}, recebido {leg!r}")
        if price is not None and ("stopLoss" in params or "takeProfit" in params):
            # Com price, a perna vira stop LIMIT (slLimitPrice/slOrderType=
            # 'limit') — não preenche num gap. Entrada protegida é sempre a
            # mercado.
            raise ValueError(
                "create_order: price deve ser None numa entrada com proteção "
                "anexada — caso contrário a perna vira stop limit.")
        params.setdefault("marginMode", MARGIN_MODE)
        # clientOrderId idempotente: evita ordem duplicada em reconexão/retry.
        # O sufixo aleatório importa — duas ordens no mesmo milissegundo
        # colidiriam no mesmo id e a segunda seria rejeitada.
        # O ccxt traduz `clientOrderId` para `clientOid` sozinho; não renomear.
        # E injetar isto SÓ aqui: `fetch_order`, `cancel_order` e `edit_order`
        # IGNORAM o argumento `id` quando `clientOrderId` aparece nos params.
        params.setdefault("clientOrderId", f"bat-{int(time.time() * 1000)}-{uuid.uuid4().hex[:6]}")
        amount = self.amount_to_precision(symbol, amount)
        log.info("Enviando ordem %s %s %s (%s)", side, amount, symbol, order_type)
        return self.exchange.create_order(symbol, order_type, side, amount, price, params)

    def fetch_order(self, order_id: str, symbol: str) -> dict[str, Any]:
        """Consulta uma ordem por id, com gatilho E preço de fill NORMALIZADOS.

        (1) Gatilho: `parse_order` da Bitget põe o gatilho de stop em
        `stopLossPrice` e deixa `triggerPrice`/`stopPrice` vazios
        (bitget.py:4993-4995; `stopPrice` é só alias de `triggerPrice` na base do
        ccxt). Sem normalizar, a "cura de arquivo stale" do trailing seria
        pulada em silêncio.

        (2) Preço de fill — a normalização mais importante deste método.
        `parse_order` só lê `average` de `priceAvg` (bitget.py:4941), campo que
        existe na rota CLÁSSICA; a rota UTA (a desta conta) usa `avgPrice`, que
        o ccxt NUNCA lê — `average` sai `None` sempre aqui. Sobra `price`, que
        pode vir a STRING `"0"` (medido no payload real de ordem preenchida em
        UTA) — e `"0"` é TRUTHY em Python. Um guard `if not fill_price:` no
        chamador NÃO pega isso, e `fill_price - signal.entry_price` duas linhas
        adiante quebraria com TypeError (str - float) em toda entrada real.
        Por isso normalizamos aqui para float com guard POSITIVO — nunca
        truthy simples — e nunca None vira 0.0 nem "0" vira preço real.

        Sem `params={'acknowledged': True}`: aquilo era exigência da Bybit v5 e
        aqui seria repassado cru no request."""
        o = self._with_retry(self.exchange.fetch_order, order_id, symbol)
        trigger = o.get("stopLossPrice") or o.get("triggerPrice")
        o["triggerPrice"] = trigger
        o["stopPrice"] = trigger

        info = o.get("info") or {}
        o["average"] = _positive_float(o.get("average")) or _positive_float(info.get("avgPrice"))
        o["price"] = _positive_float(o.get("price")) or _positive_float(info.get("priceAvg"))
        filled = _positive_float(o.get("filled")) or _positive_float(info.get("cumExecQty"))
        if filled is not None:
            o["filled"] = filled
        return o

    def amount_to_precision(self, symbol: str, amount: float) -> float:
        """Arredonda a quantidade para o step aceito no par.

        A falha é RUIDOSA de propósito: com `load_markets()` no __init__ ela
        deixou de ser caminho esperado, e devolver o valor cru em silêncio faz
        a exchange rejeitar a ordem duas linhas adiante — onde `0` é
        interpretado como "posição fechada" (`engine.py:901`, `executor.py:175`)."""
        try:
            return float(self.exchange.amount_to_precision(symbol, amount))
        except Exception as exc:  # noqa: BLE001
            log.warning("amount_to_precision falhou para %s (%s): %s — usando valor cru",
                        symbol, amount, exc)
            audit("amount_precision_failed", symbol=symbol, amount=amount, error=str(exc))
            return amount

    def fetch_position_tpsl(self, symbol: str) -> dict[str, Any] | None:
        """A ordem `tpsl` viva do símbolo — as DUAS pernas num id só.

        Usos: o executor descobre o `tpsl_id` logo após a entrada, e o engine
        recupera a proteção se esse id se perder.

        O filtro por símbolo é feito em Python de propósito: em UTA o
        `planType` trafega no request mas NÃO filtra nada (bitget.py:6413 omite
        só type/stop/trigger/trailing), então a consulta devolve as strategy
        orders de todos os símbolos — inclusive `track_plan` (trailing) e
        `normal_plan`, que não são a proteção que este método promete.

        Guard TRUTHY em `stop_trigger`, não presença de linha: uma strategy
        order sem gatilho de stop de verdade (`stopLossPrice` vazio) não é
        proteção, mesmo que a consulta tenha devolvido uma linha — devolver um
        dict truthy nesse caso faria o chamador acreditar que há stop quando
        não há. Com mais de um candidato válido, a ambiguidade é auditada em
        vez de resolvida por índice em silêncio."""
        rows = self._with_retry(
            self.exchange.fetch_open_orders, symbol,
            params={"stop": True, "planType": "profit_loss"})
        candidatos = [
            r for r in rows
            if r.get("symbol") == symbol and _positive_float(r.get("stopLossPrice")) is not None
        ]
        if not candidatos:
            return None
        if len(candidatos) > 1:
            audit("tpsl_ambigua", symbol=symbol,
                  ids=[r.get("id") for r in candidatos])
        r = candidatos[-1]
        return {
            "id": r.get("id"),
            "stop_trigger": _positive_float(r.get("stopLossPrice")),
            "tp_trigger": _positive_float(r.get("takeProfitPrice")),
            "status": r.get("status"),
        }

    def move_stop_loss(self, order_id: str, symbol: str, new_stop: float) -> dict[str, Any]:
        """Move o stop de uma posição ABERTA. Uma chamada, atômica.

        VALIDADO ao vivo em 20/08: o take-profit é preservado e o `orderId` NÃO
        muda entre movimentos. Não há cancelar+recriar, não há janela sem
        proteção, não há re-arm de emergência — todo o aparato que o trailing da
        Bybit exigia (bug #49) some aqui.

        **O param é `stopLossPrice` PLANO** — convenção OPOSTA à de
        `create_order`, que exige o dict `stopLoss={'triggerPrice': ...}`. Está
        assim porque o ccxt roteia por essa diferença: plano vai para
        `ModifyStrategyOrder` (bitget.py:5678), dict não.

        `amount=None` para não reenviar `qty`; `price=None` para o stop
        continuar a MERCADO em vez de virar limit (5663-5667)."""
        r = self._with_retry(
            self.exchange.edit_order, order_id, symbol, "market", None, None, None,
            {"stopLossPrice": new_stop},
        )
        if not (r or {}).get("id"):
            # O chamador persiste `id` como o novo tpsl_id; um None ali mataria
            # o trailing E o fechamento auditado da posição inteira. Como a
            # Bitget preserva o orderId na modificação, reinjetar é correto —
            # não é chute.
            r = dict(r or {})
            r["id"] = order_id
        return r

    def move_take_profit(self, order_id: str, symbol: str, new_tp: float) -> dict[str, Any]:
        """Move o take-profit. Mesmo padrão de `move_stop_loss`.

        Chamada SEPARADA é obrigatória: `edit_order` levanta se receber mais de
        um entre triggerPrice/stopLossPrice/takeProfitPrice (bitget.py:5647).

        HIPÓTESE NÃO VALIDADA ao vivo — o que foi medido em 20/08 foi mover o
        STOP (e confirmar que o TP sobrevive). O caminho simétrico é o mesmo no
        código do ccxt, mas o motor não depende dele hoje: o TP é fixo desde a
        entrada. Validar antes de usar."""
        r = self._with_retry(
            self.exchange.edit_order, order_id, symbol, "market", None, None, None,
            {"takeProfitPrice": new_tp},
        )
        if not (r or {}).get("id"):
            r = dict(r or {})
            r["id"] = order_id
        return r

    def fetch_last_close_fill(self, symbol: str, since_ms: int | None,
                              side: str) -> dict[str, Any] | None:
        """O preenchimento que FECHOU a posição, procurado nos trades da conta.

        Existe porque, na Bitget, consultar a ordem de proteção quase nunca
        responde essa pergunta: quando a posição zera, a exchange CANCELA a
        tpsl — ela vira `canceled` com filled=0 e não guarda preço de saída.
        Sem esta segunda fonte, todo fechamento cairia em
        `external_close_unconfirmed` e o PnL de cada trade da trilha seria uma
        aproximação pelo alvo do stop, nunca o preço real.

        `side` é o lado da POSIÇÃO ("long"/"short"); o trade de fechamento tem
        o lado oposto. Devolve o shape que `_handle_perp_position_closed` já
        sabe ler, ou None quando não há evidência — nunca um preço inventado.

        `since_ms` é OBRIGATÓRIO na prática: sem âncora temporal, um trade
        'buy'/'sell' do símbolo pode ser tanto o FECHAMENTO desta posição
        quanto a ABERTURA de uma anterior (o filtro por `side` sozinho não
        distingue as duas), e escolher errado marcaria um trade como fechado
        com o preço de um evento não relacionado. Sem `since_ms`, recusar em
        vez de adivinhar — o chamador cai no alvo do stop, que é honesto sobre
        ser aproximado."""
        if since_ms is None:
            log.warning("fetch_last_close_fill(%s) sem âncora temporal — "
                        "recusando (posição sem opened_ts registrado)", symbol)
            return None
        close_side = "sell" if side == "long" else "buy"
        try:
            trades = self._with_retry(self.exchange.fetch_my_trades, symbol, since_ms)
        except Exception as exc:  # noqa: BLE001
            log.warning("Sem trades para apurar o fechamento de %s: %s", symbol, exc)
            return None
        fechamentos = [t for t in trades if t.get("side") == close_side and t.get("price")]
        if not fechamentos:
            return None
        # O mais recente. Se o fechamento foi parcelado em vários fills, esta é
        # uma aproximação — assumida conscientemente, e melhor que o alvo do
        # stop, que é a alternativa.
        t = fechamentos[-1]
        return {
            "average": float(t["price"]),
            "filled": float(t.get("amount") or 0),
            "status": "closed",
        }

    def cancel_order(self, order_id: str, symbol: str, *, is_strategy: bool) -> Any:
        """Cancela UMA ordem. `is_strategy` decide a ROTA, e é obrigatório.

        `is_strategy=True` para uma `tpsl`/plan order, False para ordem comum:
        o ccxt roteia por aí (`if trigger: CancelStrategyOrder else:
        CancelOrder`, bitget.py:5841-5843). Cancelar uma tpsl pela rota errada
        falha — e os call sites herdados da Bybit engolem a exceção
        (`engine.py:524-535`), o que tornaria o erro 100% silencioso. Por isso é
        keyword-only e sem default: quem chama tem que ter pensado no assunto.

        `25204` ("Order does not exist") é tratado como sucesso: significa que
        não há o que cancelar."""
        params = {"stop": True} if is_strategy else {}
        try:
            return self._with_retry(self.exchange.cancel_order, order_id, symbol, params)
        except ccxt.ExchangeError as exc:
            if ERR_ORDER_NOT_FOUND in str(exc):
                log.info("cancel_order: %s já não existe (benigno)", order_id)
                return {"id": order_id, "status": "canceled"}
            raise

    def cancel_all(self, symbol: str) -> Any:
        """Cancela toda ordem aberta do símbolo. UMA chamada.

        Diferente da Bybit (bug #23), aqui não há categorias a varrer: em UTA o
        ccxt manda tudo para `CancelSymbolOrder` e ignora `trigger`/`planType`
        (bitget.py:6084-6089).

        A lição do bug #23 continua valendo, ainda que a causa tenha sumido:
        **depois de cancelar, verifique o efeito — não confie no retorno.** O
        retorno concatena sucessos e falhas, então lista vazia é ambígua.

        `except` casa pelo código 25204 e não é cego: falha REAL de cancelamento
        precisa propagar, senão vira silêncio."""
        try:
            return self._with_retry(self.exchange.cancel_all_orders, symbol)
        except ccxt.ExchangeError as exc:
            if ERR_ORDER_NOT_FOUND in str(exc):
                log.info("cancel_all: nada a cancelar em %s (benigno)", symbol)
                return []
            raise

    def set_leverage(self, symbol: str, leverage: int) -> None:
        """Define a alavancagem do símbolo, nos dois lados.

        A falha NÃO é silenciosa aqui, ao contrário da versão Bybit: se esta
        chamada falhar sempre, o `RiskManager` dimensiona assumindo a
        alavancagem que pediu enquanto a exchange usa a default da conta — o
        sizing descola do risco e nada na trilha denuncia. O executor chama isto
        ANTES da entrada, então abortar é seguro.

        Duas chamadas, uma por lado — não uma. O docstring do ccxt
        (bitget.py:8797) documenta `posSide` como OBRIGATÓRIO para margem
        isolada em UTA; sem ele a chamada nunca é consumida corretamente na
        rota UTA (o ramo `if uta:` do ccxt nem lê `marginMode`, só `productType`
        — a constante MARGIN_MODE que este método passava antes não fazia
        nada). E a leitura da conta em 20/08 confirmou que isolado tem
        alavancagem SEPARADA por lado (`longLeverage`/`shortLeverage` na
        mesma config), então "definir a alavancagem do símbolo" sem dizer de
        qual lado é uma operação mal definida em UTA isolado — daí as duas
        chamadas, não uma só."""
        for pos_side in ("long", "short"):
            try:
                self._with_retry(self.exchange.set_leverage, leverage, symbol,
                                 {"category": PRODUCT_TYPE, "posSide": pos_side})
            except Exception as exc:  # noqa: BLE001
                log.critical("set_leverage falhou para %s %s (%sx): %s",
                             symbol, pos_side, leverage, exc)
                audit("set_leverage_failed", symbol=symbol, side=pos_side,
                      leverage=leverage, error=str(exc))
                raise

    # ----------------------- Caminho SPOT: não portado -----------------------
    # `market.type: "spot"` não foi portado para a Bitget. Todos os call sites
    # destes dois métodos estão atrás de um guard de market_type
    # (`engine.py:276-277`, `executor.py:57`), então são inalcançáveis em perp.
    # São stubs que LEVANTAM em vez de devolver vazio: um `[]`/`0.0` silencioso
    # aqui seria lido como "nenhuma posição" / "sem saldo" e levaria a decisões
    # erradas — falhar alto é a única opção honesta.
    def fetch_spot_holdings(self, symbols: list[str]) -> list[dict[str, Any]]:
        raise NotImplementedError(
            "caminho spot não portado para a Bitget — use market.type: perp")

    def fetch_free_base(self, symbol: str) -> float:
        raise NotImplementedError(
            "caminho spot não portado para a Bitget — use market.type: perp")
