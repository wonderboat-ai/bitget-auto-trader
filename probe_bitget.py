"""Sonda de validação da Bitget — passo 1 do port (20/08/2026).

Existe para responder, CONTRA A CONTA REAL, o que a leitura do código do ccxt
não responde sozinha, ANTES de escrever `src/exchange/bitget_client.py`.

NÃO é o motor. Não lê `config/risk_config.yaml`, não escreve em
`logs/audit.jsonl` nem em `state/`, não importa `src/`. É deliberadamente
autônomo: uma falha aqui não pode contaminar a trilha de auditoria, que começa
vazia nesta pasta.

A Bitget não tem testnet via ccxt (`urls['test']` é None), então as fases 2 e 4
movem DINHEIRO REAL em mainnet. Cada uma exige flag própria; nenhuma roda por
padrão.

    python probe_bitget.py                 # fase 0: só leitura, zero risco
    python probe_bitget.py --set-oneway    # fase 1: muda config da conta
    python probe_bitget.py --open          # fase 2: ORDEM REAL (size mínimo)
    python probe_bitget.py --inspect       # fase 3: confere proteções + equity
    python probe_bitget.py --close         # fase 4: fecha e limpa órfãs

Esta versão incorpora uma revisão adversarial (5 lentes + verificação cética,
14 achados confirmados). O defeito central da 1ª versão era de uma classe só e
vale lembrar dela ao mexer aqui: **a sonda IMPRIMIA onde deveria VERIFICAR**.
Ausência de sinal não é sucesso.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

import ccxt
from dotenv import load_dotenv

# Resolve o .env a partir do PRÓPRIO arquivo, não do diretório atual — mesma
# disciplina do supervisor.py (`ROOT = Path(__file__).resolve().parent`). Com
# `load_dotenv()` puro, rodar de outra pasta encontrava o script mas não as
# chaves, e o erro saía como "faltam variáveis no .env" — mensagem que aponta
# para o lugar errado. É a lição de 19/08/2026: não depender de `cd`.
ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")

SYMBOL = "BTC/USDT:USDT"
PRODUCT_TYPE = "USDT-FUTURES"
MARGIN_MODE = "isolated"

# Teto de alavancagem que a sonda aceita antes de abrir posição. O stop dela é
# 1% do preço; com alavancagem alta, 1% pode cair dentro da faixa de liquidação.
MAX_LEV_SONDA = 10

# CONSULTA e CANCELAMENTO usam taxonomias DIFERENTES nesta versão do ccxt, e
# confundi-las é o bug #23 renascido:
#   consulta     (bitget.py:6354): normal_plan | profit_loss | track_plan
#   cancelamento (bitget.py:5799): profit_plan | loss_plan | normal_plan |
#                                  pos_profit | pos_loss | moving_plan | track_plan
# `profit_loss` NÃO consta do enum de cancelamento, e `cancel_all_orders`
# (6050-6165) sequer LÊ `planType` — ele só chega ao corpo por passthrough no
# extend da linha 6140. E `{'trigger': True}` NÃO é catch-all na consulta:
# a linha 6444 crava `normal_plan`.
# São as gavetas CONHECIDAS — não afirmo completude, justamente porque afirmar
# completude sem medir foi o que criou o bug #23.
FETCH_VIEWS: tuple[tuple[str, dict[str, Any]], ...] = (
    ("comuns", {}),
    ("condicionais", {"trigger": True, "planType": "normal_plan"}),
    ("preset TP/SL", {"stop": True, "planType": "profit_loss"}),
    # `planType` explícito também aqui: em UTA o roteamento para a gaveta de
    # strategy orders depende de `stop`/`trigger`/`planType` (bitget.py:6062-6064
    # -> 6420-6422), e `trailing` sozinho NÃO liga essa flag — a consulta cairia
    # nas ordens comuns e devolveria 0 sem erro nenhum.
    ("trailing", {"trailing": True, "trigger": True, "planType": "track_plan"}),
)

# Ordem IMPORTA: as duas gavetas de PROTEÇÃO vêm por último, porque só podem ser
# canceladas depois de a posição estar comprovadamente zerada (ver _flat_confirmado).
CANCEL_VIEWS_CLASSIC: tuple[tuple[str, dict[str, Any]], ...] = (
    ("comuns", {}),
    ("normal_plan", {"trigger": True, "planType": "normal_plan"}),
    ("track_plan", {"trigger": True, "planType": "track_plan"}),
    ("moving_plan", {"trigger": True, "planType": "moving_plan"}),
    ("pos_loss [PROTEÇÃO]", {"trigger": True, "planType": "pos_loss"}),
    ("pos_profit [PROTEÇÃO]", {"trigger": True, "planType": "pos_profit"}),
)
# Na rota UTA o ccxt manda tudo para CancelSymbolOrder e a flag `trigger` nunca
# é usada (bitget.py:6084-6089) — as views colapsam numa chamada só.
CANCEL_VIEWS_UTA: tuple[tuple[str, dict[str, Any]], ...] = (
    ("tudo [rota UTA ignora trigger/planType] [PROTEÇÃO]", {}),
)


def out(label: str, value: Any = "") -> None:
    print(f"{label:<40} {value}")


def section(title: str) -> None:
    print(f"\n{'=' * 74}\n{title}\n{'=' * 74}")


def confirmar() -> None:
    """Barreira humana antes de cada passo que gasta dinheiro real.

    A fricção pretendida é ter de digitar uma palavra inteira — não acertar a
    caixa. Exigir maiúscula só produzia aborto por erro de digitação, e um
    "abortado" seco parece falha do script em vez de recusa do humano."""
    resposta = input("Confirmar? (digite SIM, ou qualquer outra coisa para abortar) ").strip()
    if resposta.upper() != "SIM":
        sys.exit(f"abortado — você digitou {resposta!r}; nada foi enviado à exchange.")


def is_uta(ex: ccxt.bitget) -> bool:
    return bool(ex.options.get("uta"))


def cancel_views(ex: ccxt.bitget) -> tuple[tuple[str, dict[str, Any]], ...]:
    return CANCEL_VIEWS_UTA if is_uta(ex) else CANCEL_VIEWS_CLASSIC


def resolve_uta_route(ex: ccxt.bitget) -> bool:
    """Decide UTA x clássica e GRAVA a decisão, ANTES de qualquer chamada
    uta-aware.

    Sem isto, o ccxt descobre sozinho: `handle_uta_and_params`
    (bitget.py:1936-1951) faz uma chamada de sonda e, num `except Exception`
    genérico, assume NÃO-UTA e cacheia isso em `self.options['uta']` para o
    resto do processo. Ou seja: um blip de rede no boot roteia todas as
    chamadas seguintes para a API clássica — que nesta conta responde 40085 em
    tudo. É exatamente o bug #48 (medição única no boot envenenando o processo
    inteiro), com outra roupa.

    Com um bool em `options['uta']`, a função retorna cedo (linha 1939-1940) e
    o autodetector nunca roda. E falha de REDE aqui nunca vira veredito: rede
    não prova nada sobre o tipo da conta."""
    last: Exception | None = None
    for _ in range(3):
        try:
            ex.privateUtaGetV3AccountSettings({})
            return True
        except ccxt.AuthenticationError as exc:
            sys.exit(f"Credenciais recusadas pela Bitget: {exc}")
        except ccxt.NetworkError as exc:  # rede não decide nada
            last = exc
            continue
        except ccxt.ExchangeError:
            # Rejeição de NEGÓCIO (a conta não é UTA) — isto sim é veredito.
            return False
    sys.exit(f"INDETERMINADO: falha de rede ao sondar a rota UTA ({last}). "
             "NÃO seguir — rotear ordem às cegas é pior que não rodar.")


def build_exchange() -> ccxt.bitget:
    key = os.getenv("BITGET_MAINNET_API_KEY", "").strip()
    secret = os.getenv("BITGET_MAINNET_API_SECRET", "").strip()
    # A Bitget exige um terceiro segredo que a Bybit não tem: a passphrase
    # escolhida na criação da chave (o ccxt chama de `password`).
    password = os.getenv("BITGET_MAINNET_API_PASSPHRASE", "").strip()
    missing = [n for n, v in (
        ("BITGET_MAINNET_API_KEY", key),
        ("BITGET_MAINNET_API_SECRET", secret),
        ("BITGET_MAINNET_API_PASSPHRASE", password),
    ) if not v]
    if missing:
        sys.exit(f"Faltam variáveis no .env: {', '.join(missing)}")
    ex = ccxt.bitget({
        "apiKey": key, "secret": secret, "password": password,
        "enableRateLimit": True,
        "options": {"defaultType": "swap"},
    })
    # ANTES de load_markets(): ele próprio é uta-aware (bitget.py:1992) e
    # dispararia o autodetector descrito em resolve_uta_route.
    ex.options["uta"] = resolve_uta_route(ex)
    out("ROTA FIXADA", "UTA (v3)" if is_uta(ex) else "clássica (mix v2)")
    return ex


# --------------------------------------------------------------------------
# Verificações compartilhadas
# --------------------------------------------------------------------------
def read_positions(ex: ccxt.bitget) -> tuple[list[dict[str, Any]], bool]:
    """(posições abertas, leitura_ok). O segundo valor existe porque "não
    consegui ler" e "não há posição" produzem a MESMA lista vazia — e tratar
    falha como flat é o caminho para cancelar a proteção de uma posição viva."""
    try:
        pos = ex.fetch_positions([SYMBOL])
        return [p for p in pos if float(p.get("contracts") or 0) != 0], True
    except Exception as exc:  # noqa: BLE001
        out("fetch_positions", f"FALHOU — {type(exc).__name__}: {exc}")
        return [], False


def flat_confirmado(ex: ccxt.bitget, leituras: int = 2, delay_s: float = 2.0) -> bool | None:
    """True = flat comprovado. False = ainda há posição. None = NÃO consegui ler.

    Duas leituras porque uma só, logo após uma ordem a mercado, é o bug #29
    (saldo/estado ainda não assentado na exchange)."""
    for i in range(leituras):
        pos, ok = read_positions(ex)
        if not ok:
            return None  # nunca tratar falha de leitura como flat
        if pos:
            return False
        if i + 1 < leituras:
            ex.sleep(int(delay_s * 1000))
    return True


def dump_orders(ex: ccxt.bitget, header: str = "ordens abertas") -> dict[str, int | None]:
    """Lista cada gaveta. None = falhou (≠ 0, que é 'gaveta vazia')."""
    counts: dict[str, int | None] = {}
    for label, params in FETCH_VIEWS:
        try:
            orders = ex.fetch_open_orders(SYMBOL, params=dict(params))
            counts[label] = len(orders)
            out(f"{header} ({label})", len(orders))
            for o in orders:
                print(f"    {json.dumps(o.get('info'), ensure_ascii=False)}")
        except Exception as exc:  # noqa: BLE001
            counts[label] = None
            out(f"{header} ({label})", f"FALHOU — {type(exc).__name__}: {exc}")
    return counts


def read_leverage(ex: ccxt.bitget) -> dict[str, Any]:
    """Config de alavancagem/margem do símbolo, CRUA.

    Em UTA não dá para usar `fetch_leverage`: ele roteia para a API clássica e
    esta conta responde 40085 ("Classic Account API is not supported"). O
    caminho é `AccountSettings` COM `symbol` — sem o símbolo, `symbolConfigList`
    volta preenchido do mesmo jeito, mas é por sorte, não por contrato.

    Lemos o cru e sem `or` mascarando ausência de propósito: na rota clássica,
    `parse_leverage` escolhe a chave pelo marginMode DA CONTA
    (bitget.py:8774-8776) enquanto a sonda FORÇA `isolated` na ordem — numa
    conta em cross, o campo parseado devolveria o número de cross e a
    alavancagem realmente usada nunca apareceria."""
    try:
        if is_uta(ex):
            d = (ex.privateUtaGetV3AccountSettings(
                {"symbol": ex.market(SYMBOL)["id"], "category": PRODUCT_TYPE}) or {}).get("data") or {}
            for cfg in (d.get("symbolConfigList") or []):
                if cfg.get("symbol") == ex.market(SYMBOL)["id"]:
                    return cfg
            return {}
        lev = ex.fetch_leverage(SYMBOL)
        return lev.get("info") or {}
    except Exception as exc:  # noqa: BLE001
        out("leitura de alavancagem", f"FALHOU — {type(exc).__name__}: {exc}")
        return {}


def isolated_leverage(raw: dict[str, Any]) -> Any:
    """A alavancagem que a ordem ISOLADA vai realmente usar, nas duas rotas."""
    return raw.get("longLeverage") or raw.get("isolatedLongLever")


def read_hold_mode(ex: ccxt.bitget) -> str | None:
    """Modo de posição. `fetchPositionMode` não existe para a bitget no ccxt, e
    `fetch_positions` só revelaria o modo se JÁ houvesse posição aberta —
    inútil no boot com a conta limpa."""
    try:
        if is_uta(ex):
            d = (ex.privateUtaGetV3AccountSettings({}) or {}).get("data") or {}
            out("accountMode / assetMode", f"{d.get('accountMode')} / {d.get('assetMode')}")
            out("holdMode [uta v3]", d.get("holdMode"))
            out("accountLevel", d.get("accountLevel"))
            return d.get("holdMode")
        raw = ex.privateMixGetV2MixAccountAccount({
            "symbol": ex.market(SYMBOL)["id"], "productType": PRODUCT_TYPE,
            "marginCoin": "USDT"})
        d = raw.get("data") or {}
        out("posMode [mix v2]", d.get("posMode"))
        return d.get("posMode")
    except Exception as exc:  # noqa: BLE001
        out("modo de posição", f"FALHOU — {type(exc).__name__}: {exc}")
        return None


def dump_equity(ex: ccxt.bitget, tag: str = "") -> None:
    """Imprime equity e saldo como STRING CRUA.

    A distinção importa mais do que parece: em UTA o ccxt DESCARTA o bloco de
    equity antes do parse (bitget.py:4382-4385) e mapeia
    `total <- asset.balance` (4569), não `equity`. Na clássica mapeia
    `total <- accountEquity` (4640). Ou seja, em UTA o `fetch_balance()` do
    ccxt NÃO entrega equity com PnL não realizado — e ler equity do campo
    errado é literalmente o bug #3 (drawdown fantasma disparando kill switch).
    String crua e não float porque, com size mínimo, o uPnL é de centavos e
    sumiria num arredondamento — e um `0.00` seria lido como "são o mesmo campo"."""
    suffix = f" {tag}" if tag else ""
    try:
        if is_uta(ex):
            d = (ex.privateUtaGetV3AccountAssets({}) or {}).get("data") or {}
            out(f"accountEquity{suffix}", d.get("accountEquity"))
            out(f"unrealisedPnl{suffix}", d.get("unrealisedPnl"))
            out(f"usdtEquity / effEquity{suffix}", f"{d.get('usdtEquity')} / {d.get('effEquity')}")
            for a in (d.get("assets") or []):
                out(f"  asset {a.get('coin')}{suffix}",
                    f"equity={a.get('equity')} balance={a.get('balance')} "
                    f"available={a.get('available')} locked={a.get('locked')}")
        else:
            raw = ex.privateMixGetV2MixAccountAccounts({"productType": PRODUCT_TYPE})
            for a in (raw.get("data") or []):
                out(f"  {a.get('marginCoin')}{suffix}",
                    f"accountEquity={a.get('accountEquity')} "
                    f"unrealizedPL={a.get('unrealizedPL')} "
                    f"available={a.get('available')}")
    except Exception as exc:  # noqa: BLE001
        out(f"equity{suffix}", f"FALHOU — {type(exc).__name__}: {exc}")


# --------------------------------------------------------------------------
# Fases
# --------------------------------------------------------------------------
def phase0(ex: ccxt.bitget) -> None:
    section("FASE 0 — leitura (zero risco, nenhuma ordem)")
    ex.load_markets()
    m = ex.market(SYMBOL)
    out("símbolo", f"{SYMBOL} (id={m['id']})")
    out("precisão amount/price", f"{m['precision']['amount']} / {m['precision']['price']}")
    out("mínimo amount / custo", f"{m['limits']['amount']['min']} / {m['limits']['cost']['min']} USDT")
    out("fee taker / maker", f"{m.get('taker')} / {m.get('maker')}")

    print("\n-- conta e equity --")
    dump_equity(ex)

    print("\n-- modo de posição (one-way é premissa do projeto, bug #7) --")
    mode = read_hold_mode(ex)
    if mode and mode != "one_way_mode":
        out("!! ATENÇÃO", f"modo é {mode!r} — o robô PRESSUPÕE one_way_mode")

    print("\n-- alavancagem --")
    raw = read_leverage(ex)
    if raw:
        out("marginMode do símbolo", raw.get("marginMode"))
        out("alavancagem isolada (a que vale)", isolated_leverage(raw))
        print(f"  config crua: {json.dumps(raw, ensure_ascii=False)}")
    else:
        out("!! ATENÇÃO", "não consegui ler a alavancagem — a fase 2 vai abortar")

    print("\n-- posições e ordens abertas --")
    pos, ok = read_positions(ex)
    out("posições abertas", len(pos) if ok else "LEITURA FALHOU (≠ zero posições)")
    for p in pos:
        out("  ", f"{p['symbol']} {p.get('side')} {p.get('contracts')} @ {p.get('entryPrice')}")
    dump_orders(ex)


def phase1(ex: ccxt.bitget) -> None:
    section("FASE 1 — definir modo one-way")
    ex.load_markets()
    atual = read_hold_mode(ex)
    if atual == "one_way_mode":
        out("nada a fazer", "já está em one_way_mode")
        return
    pos, ok = read_positions(ex)
    if not ok:
        sys.exit("não consegui ler posições — não mudo config sem saber o estado.")
    counts = dump_orders(ex, "ordens")
    if pos or any(c for c in counts.values() if c):
        sys.exit("Há posição ou ordem aberta. A Bitget recusa a troca de modo "
                 "nessa condição — limpe a conta antes.")
    print(f"\nMuda CONFIGURAÇÃO da conta ({atual!r} -> 'one_way_mode').\n"
          "Não move dinheiro e não toca em saldo.")
    confirmar()
    r = ex.set_position_mode(False, SYMBOL, {"productType": PRODUCT_TYPE})
    print(json.dumps(r, ensure_ascii=False, indent=2)[:800])
    # Reler PELA MESMA ROTA que escreveu. A resposta do POST diz "success" sem
    # provar o estado final — e "cancelou com sucesso sem cancelar nada" já foi
    # o bug #23 deste projeto. Estado final se verifica lendo.
    print("\n-- confirmação por releitura --")
    final = read_hold_mode(ex)
    if final != "one_way_mode":
        sys.exit(f"FALHOU: após a escrita o modo é {final!r}, não 'one_way_mode'.")
    out("CONFIRMADO", "one_way_mode")


def phase2(ex: ccxt.bitget) -> None:
    section("FASE 2 — ORDEM REAL com SL/TP anexados (DINHEIRO REAL)")
    ex.load_markets()
    m = ex.market(SYMBOL)

    mode = read_hold_mode(ex)
    if mode != "one_way_mode":
        sys.exit(f"modo é {mode!r}. Rode --set-oneway antes: em hedge o ccxt "
                 "manda a ordem sem posSide e o resultado é indefinido.")

    raw = read_leverage(ex)
    lev_iso = isolated_leverage(raw)
    if not lev_iso:  # truthy: None e "" abortam
        sys.exit("não consegui ler a alavancagem isolada — e a ordem vai ISOLATED. Abortando.")
    if float(lev_iso) > MAX_LEV_SONDA:
        sys.exit(f"alavancagem isolada {lev_iso}x acima do teto {MAX_LEV_SONDA}x da "
                 f"sonda (o stop dela é 1%). Ajuste na Bitget antes de abrir.")

    price = float(ex.fetch_ticker(SYMBOL)["last"])
    amount = float(m["limits"]["amount"]["min"])
    min_cost = float(m["limits"]["cost"]["min"] or 0)
    if amount * price < min_cost:
        # Mínimo de QUANTIDADE e mínimo de CUSTO são limites independentes;
        # satisfazer um não garante o outro. Arredonda para CIMA de propósito:
        # amount_to_precision trunca, e truncar aqui reprovaria no custo mínimo.
        amount = float(ex.amount_to_precision(SYMBOL, (min_cost * 1.05) / price))
        if amount * price < min_cost:
            amount += float(m["precision"]["amount"])
    notional = amount * price
    # 1% e 2%: distâncias arbitrárias de SONDA, longe o bastante para não
    # disparar durante o teste. Não têm relação com o sizing de risco do motor.
    stop = float(ex.price_to_precision(SYMBOL, price * 0.99))
    tp = float(ex.price_to_precision(SYMBOL, price * 1.02))

    out("lado / tamanho", f"buy {amount}")
    out("preço / nocional", f"{price} / ~{notional:.2f} USDT")
    out("stop / take-profit", f"{stop} / {tp}")
    out("alavancagem isolada", f"{lev_iso}x")
    out("margem exigida", f"~{notional / float(lev_iso):.2f} USDT")
    print("\nISTO CRIA UMA POSIÇÃO REAL COM DINHEIRO REAL.")
    confirmar()

    # `stopLoss`/`takeProfit` como DICTS aninhados: é o que faz o ccxt anexar as
    # proteções à PRÓPRIA ordem de entrada (bitget.py:5350-5368 na clássica,
    # create_uta_order_request na UTA). Passar `stopLossPrice`/`takeProfitPrice`
    # planos cai noutro branch, cria ordens SEPARADAS e recusa os dois juntos.
    order = ex.create_order(
        SYMBOL, "market", "buy", amount, None,
        {"stopLoss": {"triggerPrice": stop},
         "takeProfit": {"triggerPrice": tp},
         "marginMode": MARGIN_MODE},
    )
    entry_id = order.get("id")
    out("ordem enviada, id", entry_id)
    # Não leia stopLossPrice/filled/status DESTA resposta: a Bitget devolve só
    # {orderId, clientOid} (bitget.py:4675-4678), então parse_order preenche
    # esses campos com null SEMPRE — inclusive quando tudo funcionou.
    print(f"  resposta crua: {json.dumps(order.get('info'), ensure_ascii=False)}")

    print("\n-- reconciliação: o stop existe MESMO? --")
    protegido = confirm_protection(ex, entry_id)
    if protegido is True:
        out("VEREDITO", "protegida — rode --inspect e depois --close")
        return
    if protegido is None:
        sys.exit("INDETERMINADO (falha de leitura). NÃO fecho automaticamente às "
                 "cegas. Rode --inspect e confira na tela da Bitget AGORA.")
    # Regra #4 do projeto, "nunca posição nua": stop não confirmado com posição
    # aberta não espera confirmação humana — fecha.
    print("STOP NÃO CONFIRMADO com posição aberta — fechando de emergência.", file=sys.stderr)
    emergency_close(ex, entry_id)


def confirm_protection(ex: ccxt.bitget, entry_id: str | None) -> bool | None:
    """True = protegida. False = leituras OK e nenhum stop encontrado.
    None = não consegui ler.

    Três vias, porque nenhuma sozinha é confiável."""
    leu_algo = False
    # (a) a ordem de entrada — os presets ficam no `info` cru dela.
    if entry_id:
        try:
            o = ex.fetch_order(entry_id, SYMBOL)
            info = o.get("info") or {}
            leu_algo = True
            sl = info.get("presetStopLossPrice") or info.get("stopLoss")
            tp = info.get("presetStopSurplusPrice") or info.get("takeProfit")
            out("  via ordem: sl / tp", f"{sl!r} / {tp!r}")
            # Guard TRUTHY, nunca `is None`: a Bitget devolve "" quando não há
            # preset, e "" é falsy mas não é None (bugs #20/#27).
            if sl:
                return True
        except Exception as exc:  # noqa: BLE001
            out("  via ordem", f"FALHOU — {type(exc).__name__}: {exc}")
    # (b) a gaveta de proteção.
    try:
        orders = ex.fetch_open_orders(SYMBOL, params={"stop": True, "planType": "profit_loss"})
        leu_algo = True
        out("  via gaveta preset", f"{len(orders)} ordem(ns)")
        for o in orders:
            print(f"    {json.dumps(o.get('info'), ensure_ascii=False)}")
        if orders:
            return True
    except Exception as exc:  # noqa: BLE001
        out("  via gaveta preset", f"FALHOU — {type(exc).__name__}: {exc}")
    # (c) exploratória: a posição. NUNCA é fonte de veredito — o payload
    # documentado de AllPosition (bitget.py:7786-7813) não traz os presets, e
    # concluir "desprotegida" por aqui fecharia uma posição bem protegida.
    pos, ok = read_positions(ex)
    if ok and pos:
        print(f"  via posição (exploratória): {json.dumps(pos[0].get('info'), ensure_ascii=False)}")
    return False if leu_algo else None


def emergency_close(ex: ccxt.bitget, entry_id: str | None) -> None:
    pos, ok = read_positions(ex)
    if not ok:
        sys.exit(f"NÃO consegui ler a posição para fechar. entry_id={entry_id}. "
                 "FECHE NA MÃO NA BITGET AGORA.")
    for p in pos:
        side = "sell" if p.get("side") == "long" else "buy"
        try:
            r = ex.create_order(SYMBOL, "market", side, float(p["contracts"]), None,
                                {"reduceOnly": True, "marginMode": MARGIN_MODE})
            out("fechamento de emergência", r.get("id"))
        except Exception as exc:  # noqa: BLE001
            sys.exit(f"POSIÇÃO NUA: falha ao fechar ({exc}). entry_id={entry_id}. "
                     "FECHE NA MÃO NA BITGET AGORA.")
    sys.exit(1)


def phase3(ex: ccxt.bitget) -> None:
    section("FASE 3 — proteções e origem do equity (com posição aberta)")
    ex.load_markets()
    pos, ok = read_positions(ex)
    out("posições", len(pos) if ok else "LEITURA FALHOU")
    for p in pos:
        out("  ", f"{p.get('side')} {p.get('contracts')} @ {p.get('entryPrice')} "
                  f"uPnL={p.get('unrealizedPnl')} liq={p.get('liquidationPrice')}")
        print(f"  info cru: {json.dumps(p.get('info'), ensure_ascii=False)}")
    dump_orders(ex, "ordens")
    # A medição que decide de qual campo o client vai tirar o equity. Só faz
    # sentido AQUI: com a conta chapada, equity e balance são numericamente
    # iguais e não se distinguem. Duas amostras porque o uPnL se move.
    print("\n-- equity vs balance, com posição aberta (2 amostras) --")
    dump_equity(ex, "[t0]")
    ex.sleep(5000)
    dump_equity(ex, "[t1]")
    print("\nSe só `equity`/`accountEquity` se mexer entre t0 e t1 e `balance`\n"
          "ficar parado, está provado: em UTA o equity com PnL não realizado é\n"
          "`accountEquity`, e `fetch_balance()['USDT']['total']` NÃO serve.")


def phase4(ex: ccxt.bitget) -> None:
    section("FASE 4 — fechar posição e cancelar o que sobrar")
    ex.load_markets()
    pos, ok = read_positions(ex)
    if not ok:
        sys.exit("não consegui ler posições — não cancelo nada às cegas.")
    if not pos:
        out("posições", "nenhuma")
    for p in pos:
        side = "sell" if p.get("side") == "long" else "buy"
        amount = float(p["contracts"])
        out("fechar", f"{side} {amount} (reduceOnly)")
        # Em one-way o ccxt manda `reduceOnly: 'YES'` PRESERVANDO o side — por
        # isso o side já vem invertido a partir do lado real da posição.
        # `marginMode` explícito porque o default do ccxt é `cross`.
        confirmar()
        r = ex.create_order(SYMBOL, "market", side, amount, None,
                            {"reduceOnly": True, "marginMode": MARGIN_MODE})
        print(json.dumps(r.get("info"), ensure_ascii=False)[:400])

    # BARREIRA — sempre executada, inclusive quando `pos` veio vazio.
    # Cancelar a gaveta de proteção com posição ainda viva é a única forma de
    # esta sonda produzir uma posição DESPROTEGIDA. Não é hipotética: a lista
    # vazia de `pos` pode ser leitura transitória, não ausência de posição.
    print("\n-- barreira antes de cancelar --")
    flat = flat_confirmado(ex)
    views = cancel_views(ex)
    if flat is True:
        out("BARREIRA", "flat confirmado — pode cancelar tudo")
        # Responde de graça a pergunta do bug #49: proteção que SOBREVIVE à
        # posição zerar é órfã real, e aí o client PRECISA cancelar a irmã.
        print("\n-- gavetas com a posição já zerada (isto responde o bug #49) --")
        antes = dump_orders(ex, "órfãs?")
        if any(c for c in antes.values() if c):
            out("!! ACHADO", "proteção sobreviveu à posição zerar -> ÓRFÃ REAL")
        else:
            out("indício", "gavetas vazias -> a Bitget parece cancelar sozinha")
    else:
        motivo = "não consegui ler" if flat is None else "AINDA HÁ POSIÇÃO"
        out("BARREIRA", f"{motivo} — NÃO vou tocar na gaveta de PROTEÇÃO")
        views = tuple(v for v in views if "PROTEÇÃO" not in v[0])

    for label, params in views:
        try:
            r = ex.cancel_all_orders(SYMBOL, params=dict(params))
            # Lista vazia é ambígua: `cancel_all_orders` concatena sucessos E
            # falhas (bitget.py:6157-6165), então `[]` pode ser "gaveta vazia"
            # ou "não cancelou nada". Só a reconsulta abaixo decide.
            out(f"cancel_all ({label})", json.dumps(r, ensure_ascii=False)[:200])
        except Exception as exc:  # noqa: BLE001
            out(f"cancel_all ({label})", f"FALHOU — {type(exc).__name__}: {exc}")

    print("\n-- reconsulta pós-cancelamento (a resposta acima não é prova) --")
    depois = dump_orders(ex, "restantes")
    if any(c for c in depois.values() if c):
        out("!! ATENÇÃO", "ainda há ordem aberta — CANCELE NA MÃO na Bitget")
        sys.exit(1)
    if any(c is None for c in depois.values()):
        out("!! ATENÇÃO", "alguma gaveta não pôde ser lida — CONFIRA na Bitget")
        sys.exit(1)
    out("CONFIRMADO", "nenhuma ordem restante")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--set-oneway", action="store_true")
    ap.add_argument("--open", action="store_true")
    ap.add_argument("--inspect", action="store_true")
    ap.add_argument("--close", action="store_true")
    args = ap.parse_args()

    ex = build_exchange()
    if args.set_oneway:
        phase1(ex)
    elif args.open:
        phase2(ex)
    elif args.inspect:
        phase3(ex)
    elif args.close:
        phase4(ex)
    else:
        phase0(ex)


if __name__ == "__main__":
    main()
