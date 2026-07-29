"""Wrapper fino sobre o CCXT para a Bybit (derivativos USDT-perp).

Responsabilidades:
  - Abstrair testnet vs mainnet (a corretora é a única fonte da verdade).
  - Expor leitura de mercado (OHLCV, ticker, funding) e conta (saldo, posições).
  - Centralizar colocação/cancelamento de ordens com client order id idempotente.

NÃO contém lógica de risco nem de estratégia — só fala com a exchange.
"""
from __future__ import annotations

import ssl
import time
import uuid
from typing import Any

import ccxt
from requests.adapters import HTTPAdapter
from urllib3.util.ssl_ import create_urllib3_context

from config.settings import ExchangeCredentials
from src.logger import audit, get_logger

log = get_logger("bybit_client")


class _Tls12Adapter(HTTPAdapter):
    """Força o handshake a negociar no máximo TLS 1.2.

    Motivo: alguns endpoints da Bybit (atrás de CloudFront) pedem renegociação
    TLS no meio da conexão. TLS 1.3 não suporta renegociação — quando o OpenSSL
    do Python negocia 1.3, essa renegociação derruba a conexão com
    `SSLEOFError: UNEXPECTED_EOF_WHILE_READING`. Ferramentas que usam o TLS
    nativo do Windows (curl/schannel) não têm esse problema porque negociam
    1.2 por padrão nesse cenário. Travar em 1.2 aqui replica esse comportamento.
    """

    def init_poolmanager(self, *args: Any, **kwargs: Any) -> None:
        context = create_urllib3_context()
        context.maximum_version = ssl.TLSVersion.TLSv1_2
        kwargs["ssl_context"] = context
        return super().init_poolmanager(*args, **kwargs)


# Saldo de moeda-base abaixo disto (em USDT) é poeira, não posição — evita que
# resíduo de arredondamento de uma venda conte como "posição aberta" e trave o
# símbolo para sempre via exclusividade. ~mínimo de ordem spot da Bybit.
SPOT_DUST_USDT = 10.0


class BybitClient:
    def __init__(self, creds: ExchangeCredentials, default_type: str = "swap") -> None:
        self._testnet = creds.testnet
        # "swap" = perpétuos USDT (original) | "spot" = à vista (decisão #E).
        self._default_type = default_type
        self.exchange = ccxt.bybit(
            {
                "apiKey": creds.api_key,
                "secret": creds.api_secret,
                "enableRateLimit": True,
                "options": {
                    "defaultType": default_type,  # swap = perpétuos USDT
                    # Corrige a assinatura das requisições pela diferença real de
                    # horário com o servidor da Bybit, em vez de confiar cegamente
                    # no relógio local (que pode ter deriva/drift).
                    "adjustForTimeDifference": True,
                },
            }
        )
        # CCXT alterna para os endpoints de testnet quando sandbox = True.
        self.exchange.set_sandbox_mode(self._testnet)
        # Contorna incompatibilidade de renegociação TLS 1.3 vs endpoints Bybit/CloudFront.
        session = getattr(self.exchange, "session", None)
        if session is None:
            # Versões do CCXT que criam a session sob demanda: sem isto, o mount
            # abaixo virava um no-op silencioso e o workaround TLS não se aplicava.
            import requests
            session = requests.Session()
            self.exchange.session = session
        session.mount("https://", _Tls12Adapter())
        try:
            # Mede a diferença local↔servidor uma vez na inicialização e passa
            # a compensar automaticamente em toda requisição assinada.
            self.exchange.load_time_difference()
        except Exception as exc:  # noqa: BLE001
            log.warning("Não foi possível medir a diferença de horário com o servidor: %s", exc)
        log.info(
            "BybitClient iniciado (%s)",
            "TESTNET" if self._testnet else "MAINNET — DINHEIRO REAL",
        )

    @property
    def is_testnet(self) -> bool:
        return self._testnet

    @property
    def is_spot(self) -> bool:
        return self._default_type == "spot"

    def _with_retry(self, fn: Any, *args: Any, retries: int = 3, backoff: float = 1.0, **kwargs: Any) -> Any:
        """Reexecuta `fn` em caso de erro de rede transitório (timeout, SSL EOF,
        conexão recusada) ou de timestamp desatualizado (retCode 10002 da Bybit
        -> `ccxt.InvalidNonce`, subclasse de `NetworkError`), com backoff
        exponencial. Não retenta erros de negócio (credencial inválida,
        parâmetro errado etc.) — só falha de transporte.

        InvalidNonce ganha tratamento especial (achado ao vivo em 28/07/2026:
        ~5h23min de `cycle_error` ininterrupto até o processo ser reiniciado
        manualmente, reproduzido de novo minutos depois de um restart limpo —
        não era drift de relógio real, `local vs servidor` medido na hora
        ficou em <1s). Causa raiz: `load_time_difference()` mede o offset
        local<->servidor com UMA ÚNICA requisição, só no boot (`__init__`) —
        se essa medição pegar uma requisição lenta/com jitter (rede, TLS, o
        próprio Avast interceptando HTTPS, já documentado como fonte de
        instabilidade neste projeto), o offset fica errado e TODA chamada
        assinada subsequente falha, pro resto da vida do processo, até
        reiniciar. Sem re-sincronizar aqui, as 3 tentativas de retry
        repetem a mesma assinatura ruim e sempre falham do mesmo jeito."""
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
                        "re-sincronizando relógio com o servidor antes de "
                        "tentar de novo em %.1fs",
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
        """Candles [timestamp, open, high, low, close, volume]."""
        return self._with_retry(self.exchange.fetch_ohlcv, symbol, timeframe=timeframe, limit=limit)

    def fetch_ticker(self, symbol: str) -> dict[str, Any]:
        return self._with_retry(self.exchange.fetch_ticker, symbol)

    def fetch_funding_rate(self, symbol: str) -> float | None:
        if self.is_spot:
            # Spot não tem funding — None faz o circuit breaker de funding do
            # risco simplesmente não se aplicar (mesma semântica de "sem dado").
            return None
        try:
            fr = self._with_retry(self.exchange.fetch_funding_rate, symbol)
            return fr.get("fundingRate")
        except Exception as exc:  # noqa: BLE001
            log.warning("Falha ao buscar funding de %s: %s", symbol, exc)
            return None

    # ------------- Derivativos p/ CONTEXTO (decisão #G, 18/07/2026) -------------
    # Os três métodos abaixo são para o BybitDerivativesProvider
    # (src/context/providers.py) — NUNCA para o RiskManager. Diferença chave
    # de fetch_funding_rate acima: aquele é gate de RISCO e retorna None em
    # modo spot por decisão deliberada (não dá pra vetar por funding numa
    # modalidade sem funding). Estes três sempre consultam o PERPÉTUO do
    # símbolo, independente do modo de conta ativo — funding/open interest/
    # razão long-short só existem para derivativos, mas são endpoints de
    # mercado PÚBLICOS (leitura, não ordem): não dependem da conta operar em
    # modo spot/perp nem esbarram no bloqueio de EXECUÇÃO de derivativos para
    # residente BR (que é só sobre criar ordem — nunca sobre ler dado público
    # de mercado). Cada um trata a própria falha e retorna None (nunca
    # levanta) — mesma disciplina "dado ausente é dado ausente" dos outros
    # provedores de contexto.
    def fetch_derivatives_funding_rate(self, symbol: str) -> dict[str, Any] | None:
        """Funding rate do perpétuo para CONTEXTO — NÃO confundir com
        fetch_funding_rate acima (aquele alimenta o circuit breaker de
        risco). Só devolve dict se `fundingRate` veio preenchido de verdade —
        um dict com valores None passaria pelo `if funding:` de quem chama
        (dict não-vazio é sempre truthy) como se fosse dado confirmado,
        mesma classe de bug já corrigida 2x neste projeto (#20, #27) pra
        outros campos. `nextFundingRate` NUNCA vem preenchido nesta versão
        do ccxt para a Bybit (checado direto no pacote instalado — é
        hardcoded None no parser, não falta de dado real), então nem
        incluímos esse campo morto no retorno."""
        try:
            fr = self._with_retry(self.exchange.fetch_funding_rate, symbol)
            rate = fr.get("fundingRate")
            if rate is None:
                return None
            return {
                "funding_rate": rate,
                "timestamp": fr.get("fundingDatetime"),
            }
        except Exception as exc:  # noqa: BLE001
            log.warning("Falha ao buscar funding (contexto) de %s: %s", symbol, exc)
            return None

    def fetch_open_interest(self, symbol: str) -> dict[str, Any] | None:
        """Open interest do perpétuo (contratos em aberto) — sentimento de
        posicionamento agregado dos usuários da Bybit. Só devolve dict se o
        valor veio preenchido (mesmo motivo do guard em
        fetch_derivatives_funding_rate acima)."""
        try:
            oi = self._with_retry(self.exchange.fetch_open_interest, symbol)
            amount = oi.get("openInterestAmount")
            if amount is None:
                return None
            return {
                "open_interest": amount,
                "timestamp": oi.get("datetime"),
            }
        except Exception as exc:  # noqa: BLE001
            log.warning("Falha ao buscar open interest de %s: %s", symbol, exc)
            return None

    def fetch_long_short_ratio(self, symbol: str, timeframe: str = "1h") -> dict[str, Any] | None:
        """Razão long/short (contas) do perpétuo. CCXT/Bybit só expõe isto
        via o endpoint de HISTÓRICO (fetch_long_short_ratio_history) — o
        fetch de "valor atual" não é suportado (validado com sonda
        somente-leitura contra o mercado público antes de escrever isto);
        pedimos limit=1 e usamos só o ponto mais recente. Só devolve dict se
        o valor veio preenchido (mesmo motivo do guard acima)."""
        try:
            rows = self._with_retry(
                self.exchange.fetch_long_short_ratio_history,
                symbol, timeframe=timeframe, limit=1,
            )
            if not rows:
                return None
            latest = rows[-1]
            ratio = latest.get("longShortRatio")
            if ratio is None:
                return None
            return {
                "long_short_ratio": ratio,
                "timestamp": latest.get("datetime"),
            }
        except Exception as exc:  # noqa: BLE001
            log.warning("Falha ao buscar long/short ratio de %s: %s", symbol, exc)
            return None

    # ----------------------- Conta (leitura) -----------------------
    def fetch_balance_usdt(self) -> float:
        """Equity em USDT — NÃO o saldo 'free'.

        'free' cai quando margem é travada por posição aberta: usado como equity,
        gerava drawdown FANTASMA e disparava o kill switch sem perda real. Ordem
        de preferência: totalEquity da conta unificada (inclui PnL não realizado)
        -> total da carteira -> free (último recurso)."""
        bal = self._with_retry(self.exchange.fetch_balance)
        try:
            for acct in bal["info"]["result"]["list"]:
                te = acct.get("totalEquity")
                if te not in (None, ""):
                    return float(te)
        except (KeyError, TypeError, ValueError):
            pass
        usdt = bal.get("USDT", {}) or {}
        total = usdt.get("total")
        if total is not None:
            return float(total)
        return float(usdt.get("free", 0.0) or 0.0)

    def fetch_open_positions(self) -> list[dict[str, Any]]:
        """Posições abertas — reconciliação de estado vem daqui, não da memória local."""
        positions = self._with_retry(self.exchange.fetch_positions)
        return [p for p in positions if float(p.get("contracts") or 0) != 0]

    def fetch_spot_holdings(self, symbols: list[str]) -> list[dict[str, Any]]:
        """Equivalente de fetch_open_positions para SPOT: quanto de cada
        moeda-base dos símbolos configurados a conta segura agora.

        Spot não tem 'posição' — tem saldo. Para o resto do sistema (busy set,
        limites de nocional, MCP) continuar enxergando um formato único, devolve
        pseudo-posições no MESMO shape usado pelos perpétuos. Saldo abaixo de
        SPOT_DUST_USDT é ignorado (resíduo de arredondamento de venda não pode
        travar o símbolo como 'posição aberta' para sempre)."""
        bal = self._with_retry(self.exchange.fetch_balance)
        out: list[dict[str, Any]] = []
        for symbol in symbols:
            base = symbol.split("/")[0]
            qty = float((bal.get(base) or {}).get("total") or 0.0)
            if qty <= 0:
                continue
            try:
                price = float(self.fetch_ticker(symbol).get("last") or 0.0)
                notional = qty * price
                if notional < SPOT_DUST_USDT:
                    continue
            except Exception as exc:  # noqa: BLE001
                # NUNCA descarta um saldo REAL (qty>0) por falha de preço
                # (revisão adversarial de 17/07): antes, um blip de rede aqui
                # fazia o símbolo sumir de fetch_spot_holdings inteiro, que é
                # a única fonte de _open_symbols no engine — abria brecha para
                # entrada DUPLICADA no mesmo símbolo (sem veto de "já aberto"
                # em nenhum outro lugar do risk_manager) e apagava a proteção
                # de TP de uma posição que continua de fato aberta. notional=0
                # é desconhecido (não filtra por poeira), mas o símbolo
                # PERMANECE na lista — errar pro lado de "tratar como aberto"
                # é sempre mais seguro que "tratar como fechado" aqui.
                log.warning("Sem preço para avaliar holding de %s: %s — mantendo "
                            "como posição aberta (fail-safe)", symbol, exc)
                notional = 0.0
                # Notional=0.0 aqui SUBESTIMA a exposição agregada que o
                # risk_manager usa pro veto absoluto (state.total_notional) —
                # sem isto na trilha, uma aprovação nesse ciclo fica com a
                # decisão gravada mas não o dado degradado por trás dela
                # (achado da 2ª rodada de revisão adversarial de 17/07).
                audit("spot_holding_notional_degraded", symbol=symbol, error=str(exc))
            out.append({
                "symbol": symbol,
                "side": "long",           # spot só compra
                "contracts": qty,
                "notional": notional,
                "entryPrice": None,       # exchange não guarda custo médio aqui
                "unrealizedPnl": 0.0,     # sem custo médio não há PnL confiável
                "leverage": 1,
            })
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
        params = params or {}
        # client order id idempotente: evita ordem duplicada em reconexão/retry.
        # Sufixo aleatório: duas ordens no mesmo milissegundo (ex.: entrada + stop)
        # colidiriam no mesmo orderLinkId e a segunda seria rejeitada pela exchange.
        params.setdefault("clientOrderId", f"bat-{int(time.time() * 1000)}-{uuid.uuid4().hex[:6]}")
        log.info("Enviando ordem %s %s %s (%s)", side, amount, symbol, order_type)
        return self.exchange.create_order(symbol, order_type, side, amount, price, params)

    def fetch_order(self, order_id: str, symbol: str) -> dict[str, Any]:
        """Consulta uma ordem específica por id (18/07/2026) — usada para
        confirmar o fill REAL de uma ordem condicional (stop) já disparada, ou
        recuperar o preço de entrada quando a resposta de criação não trouxe
        average/price (fix #17). 'acknowledged' é exigido pela Bybit v5 no
        ccxt para aceitar a consulta fora da paginação padrão de ordens
        abertas/recentes (validado com sonda somente-leitura contra a conta
        real de testnet antes de usar aqui)."""
        return self._with_retry(self.exchange.fetch_order, order_id, symbol,
                                params={"acknowledged": True})

    def fetch_free_base(self, symbol: str) -> float:
        """Saldo LIVRE da moeda-base de um par spot (ex.: BTC de "BTC/USDT").

        Motivo (revisão de 15/07): a compra spot a mercado credita MENOS base
        que o size teórico (a taxa é cobrada na moeda recebida, e o custo em
        quote diverge com o preço). Proteções dimensionadas pelo size teórico
        seriam rejeitadas por saldo insuficiente — a condicional tpslOrder
        ocupa o saldo já na colocação. Quem protege usa o saldo REAL."""
        base = symbol.split("/")[0]
        bal = self._with_retry(self.exchange.fetch_balance)
        return float((bal.get(base) or {}).get("free") or 0.0)

    def amount_to_precision(self, symbol: str, amount: float) -> float:
        """Arredonda quantidade para a precisão aceita pela exchange no par."""
        try:
            return float(self.exchange.amount_to_precision(symbol, amount))
        except Exception:  # noqa: BLE001 — mercado não carregado: usa cru
            return amount

    def set_stop_loss(self, symbol: str, side: str, amount: float, stop_price: float) -> dict[str, Any]:
        """Cria stop de proteção. Lado oposto ao da posição/holding.

        Perp: ordem condicional reduceOnly. Spot: ordem condicional tpslOrder
        (o ccxt marca reduceOnly sozinho no caminho condicional; spot não tem o
        conceito, mas a rota é a mesma)."""
        close_side = "sell" if side == "buy" else "buy"
        params: dict[str, Any] = {"stopLossPrice": stop_price}
        if not self.is_spot:
            params["reduceOnly"] = True
        # Passa pelo wrapper para ganhar clientOrderId único + log, como toda ordem.
        return self.create_order(symbol, close_side, amount, order_type="market", params=params)

    def set_take_profit(self, symbol: str, side: str, amount: float, tp_price: float) -> dict[str, Any]:
        """Cria o take-profit (decisão #F de 15/07/2026: o executor passa a
        colocar o TP que a estratégia emite — antes só o backtest o honrava).

        Mesma mecânica do stop, gatilho no lado lucrativo. ATENÇÃO (spot): stop
        e TP são ordens condicionais SEPARADAS sem OCO — quando uma executa, a
        irmã fica órfã no livro (venda sem saldo é rejeitada pela exchange, sem
        risco de posição, mas suja a lista de ordens; limpeza é manual por ora)."""
        close_side = "sell" if side == "buy" else "buy"
        params: dict[str, Any] = {"takeProfitPrice": tp_price}
        if not self.is_spot:
            params["reduceOnly"] = True
        return self.create_order(symbol, close_side, amount, order_type="market", params=params)

    def fetch_open_stop_orders(self, symbol: str) -> list[dict[str, Any]]:
        """Ordens condicionais TP/SL ATIVAS do símbolo (spot: categoria
        tpslOrder — a mesma do fix do cancel_all de 19/07).

        Usado pelo trailing (20/07) pra nunca confiar SÓ no arquivo local: se
        a persistência do último move falhou (lock do OneDrive) ou o processo
        reiniciou entre armar e persistir, o arquivo fica com o gatilho velho
        — e mover o stop com base nele REBAIXARIA a proteção real. A exchange
        é a fonte da verdade do gatilho vigente."""
        params = {"orderFilter": "tpslOrder"} if self.is_spot else {"trigger": True}
        return self._with_retry(self.exchange.fetch_open_orders, symbol, params=params)

    def cancel_order(self, order_id: str, symbol: str) -> Any:
        """Cancela UMA ordem específica (28/07/2026) — usado pra derrubar a
        ordem IRMÃ (stop ou TP) que fica órfã em perp quando a outra dispara
        (Bybit não tem OCO nativo entre duas condicionais criadas
        separadamente; ver engine.py:_handle_perp_position_closed)."""
        return self._with_retry(self.exchange.cancel_order, order_id, symbol)

    def cancel_all(self, symbol: str) -> Any:
        """Cancela toda ordem aberta do símbolo — precisa cobrir a categoria
        das ordens condicionais TP/SL, não só as comuns.

        Achado 19/07: a Bybit v5 usa `orderFilter` pra escolher a categoria no
        cancelamento em massa; sem ele, o ccxt manda o default "Order" (comuns)
        e NUNCA toca o stop real — o próprio ccxt cria as ordens de
        stop/take-profit em spot com `orderFilter="tpslOrder"` sempre que
        `stopLossPrice`/`takeProfitPrice` são usados (ver `set_stop_loss`/
        `set_take_profit` acima), categoria diferente da que o cancelamento
        sem filtro atinge. Sem este fix, `_execute_spot_take_profit`
        "cancelava com sucesso" sem cancelar nada: o saldo-base continuava
        preso no stop, `fetch_free_base` devolvia quase zero, e a venda do TP
        falhava pra sempre com erro de precisão mínima — visto ao vivo em
        19/07/2026, retry idêntico a cada ciclo por ~20min sem nunca vender."""
        results = [self.exchange.cancel_all_orders(symbol)]
        if self.is_spot:
            results.append(
                self.exchange.cancel_all_orders(symbol, params={"orderFilter": "tpslOrder"}))
        return results

    def set_leverage(self, symbol: str, leverage: int) -> None:
        try:
            self.exchange.set_leverage(leverage, symbol)
        except Exception as exc:  # noqa: BLE001
            log.warning("set_leverage falhou para %s: %s", symbol, exc)
