"""Estado local de posições protegidas — spot E perp (nome/arquivo herdados
de quando isto só existia pra spot; não renomeado pra não perder o rastreio
de posições já persistidas ao vivo, ver comentário em _resolve_state_path).

Origem SPOT: por causa de uma limitação real da Bybit, em spot a ordem
condicional do stop OCUPA o saldo-base na colocação (ver executor.py) e não
há OCO — colocar uma segunda condicional (o TP) como ordem na exchange seria
sempre rejeitada por saldo insuficiente. A saída lucrativa em spot passa a
ser SOFTWARE: o engine confere o preço a cada ciclo e, ao atingir o alvo,
cancela o stop e vende a mercado (ver engine.py:_check_spot_exits). O STOP
em si nunca depende deste arquivo em spot — é sempre uma ordem real na
exchange, ativa mesmo se o engine cair.

Estendido pra PERP em 28/07/2026 (Lucas religou perp/short em produção pela
primeira vez): em perp, TANTO o stop quanto o TP já são ordens reais na
exchange desde sempre (sem OCO nativo entre elas) — o problema aqui não é
"como realizar lucro", é que nada detectava quando uma das duas disparava:
nenhum trade_closed era auditado, e a ordem IRMÃ que não disparou ficava
órfã e ativa, podendo executar contra uma posição futura não relacionada no
mesmo símbolo. Ver engine.py:_check_perp_exits/_handle_perp_position_closed.
`tp_id` (novo campo) só é usado por este caminho perp — spot nunca arma TP
como ordem real, então fica sempre None lá."""
from __future__ import annotations

import json
import os
from pathlib import Path

from src.logger import _audit_path, get_logger

log = get_logger("protection_state")

ROOT = Path(__file__).resolve().parent.parent.parent


def _resolve_state_path() -> Path:
    """Destino do arquivo, com override por PROTECTION_STATE_PATH (relativo à
    raiz) e isolamento por AMBIENTE — mesmo padrão de
    `src/risk/kill_switch_state.py` (bug #39, 27/07/2026).

    Achado ao vivo em 27/07/2026, no primeiro boot em mainnet: sem isto,
    testnet e mainnet liam/gravavam o MESMO `state/spot_protections.json` —
    proteções ANTIGAS de testnet (ETH/USDT, BTC/USDT) ainda estavam no
    arquivo quando o motor subiu em mainnet pela primeira vez. O engine
    tentou confirmar o fill dessas ordens (`stop_id`) contra a exchange
    MAINNET, recebeu "order not found" (correto — essas ordens nunca
    existiram lá) e reconciliou as duas como fechadas
    (`reason="external_close_unconfirmed"`), fabricando 2 `trade_closed`
    com PnL negativo (-62,73 USDT) que nunca aconteceram em mainnet —
    justamente no dia em que a trilha foi zerada pra começar o PnL do zero.
    Nenhum dinheiro real foi afetado (as ordens não existiam pra cancelar
    nem vender), só a auditoria/PnL relatado ficou poluído. Corrigido com o
    mesmo padrão: mainnet mantém o nome canônico (`spot_protections.json`);
    testnet ganha arquivo próprio (`spot_protections-testnet.json`). Import
    tardio de `config.settings` para evitar import circular, igual ao
    módulo irmão."""
    override = os.environ.get("PROTECTION_STATE_PATH")
    if override:
        p = Path(override)
        return p if p.is_absolute() else ROOT / p
    from config.settings import get_environment
    if get_environment() == "testnet":
        return ROOT / "state" / "spot_protections-testnet.json"
    return ROOT / "state" / "spot_protections.json"


STATE_PATH = _resolve_state_path()


def load() -> dict[str, dict]:
    if not STATE_PATH.exists():
        return {}
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        # ValueError cobre json.JSONDecodeError E UnicodeDecodeError (bytes
        # inválidos em UTF-8) — o except antigo só listava JSONDecodeError
        # explicitamente e deixava UnicodeDecodeError escapar sem tratamento,
        # derrubando _check_spot_exits()/run_once() inteiro (crash real de
        # `--once`; ciclo inteiro falhando em loop contínuo) — achado da
        # revisão adversarial de 18/07.
        # Corrupção aqui NUNCA compromete o stop (sempre ordem real na
        # exchange, nunca lido deste arquivo) — só a oportunidade de TP.
        # Ainda assim precisa ficar visível: antes engolia em silêncio.
        log.warning("state/spot_protections.json corrompido/ilegível (%s) — "
                    "tratando como vazio; posições abertas se recuperam via "
                    "backfill_from_audit() no próximo ciclo", exc)
        return {}


def _save(protections: dict[str, dict]) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    # Escrita ATÔMICA (tmp + replace): write_text direto podia deixar o
    # arquivo truncado/inválido se o processo morresse no meio da escrita
    # (achado da revisão adversarial de 17/07) — os.replace é atômico no
    # mesmo filesystem, inclusive Windows/NTFS.
    tmp = STATE_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(protections, indent=2), encoding="utf-8")
    tmp.replace(STATE_PATH)


def set_protection(symbol: str, *, entry_price: float, take_profit: float,
                    stop_price: float, size: float | None = None,
                    stop_id: str | None = None, tp_id: str | None = None,
                    side: str = "long", profile: str | None = None,
                    trailing: bool = False, trail_distance: float | None = None,
                    peak_price: float | None = None) -> None:
    protections = load()
    protections[symbol] = {
        "entry_price": entry_price,
        "take_profit": take_profit,
        "stop_price": stop_price,
        # Direção da posição (28/07/2026, "long"/"short") — default "long"
        # por compatibilidade (spot só teve long até hoje; toda entrada
        # perp anterior a este campo também era long, já que short só foi
        # habilitado em perp na mesma sessão deste campo). Necessário pro
        # PnL e pro trailing terem o SINAL certo em short (preço caindo é
        # lucro, o stop desce em vez de subir) — sem isto,
        # _handle_perp_position_closed calcularia PnL invertido pra short.
        "side": side,
        # Tamanho REALMENTE protegido nesta entrada (protect_size do
        # executor) — sem isto, a saída de TP não tinha como distinguir a
        # posição do bot de saldo alheio da mesma moeda-base na carteira, e
        # vendia o saldo livre inteiro (achado da revisão de 17/07).
        "size": size,
        # ID da ordem condicional do stop na exchange (18/07/2026). Permite
        # confirmar o fill REAL quando a posição some da reconciliação sem
        # passar pelo fluxo de TP por software — stop disparou, ou
        # fechamento manual (ver engine.py:_handle_spot_position_closed).
        # Sem isto não dá para distinguir "stop confirmado" de "sumiu por
        # algum motivo desconhecido".
        "stop_id": stop_id,
        # ID da ordem condicional do TP na exchange (28/07/2026, só usado em
        # PERP — spot nunca arma TP como ordem real, fica sempre None lá).
        # Permite ao caminho perp confirmar qual das DUAS ordens reais
        # (stop ou TP) foi a que disparou, e cancelar a irmã órfã.
        "tp_id": tp_id,
        # Perfil que ABRIU a posição (20/07/2026): a saída por sinal precisa
        # consultar a estratégia/timeframe do perfil certo. Posições antigas
        # sem o campo (arquivo pré-existente) simplesmente não têm saída por
        # sinal — degrada pro comportamento antigo, nunca quebra.
        "profile": profile,
        # Trailing stop (20/07/2026): distância fixa (em preço) mantida entre
        # o pico e o stop, e o pico de preço visto desde a entrada. Só
        # populados quando o Signal pediu trailing; ausentes = sem trailing.
        "trailing": trailing,
        "trail_distance": trail_distance,
        "peak_price": peak_price,
    }
    _save(protections)


def clear_protection(symbol: str) -> None:
    protections = load()
    if symbol in protections:
        del protections[symbol]
        _save(protections)


def backfill_from_audit(symbol: str) -> dict | None:
    """Reconstrói a proteção a partir do último `order_executed` da trilha.

    Cobre posições abertas ANTES desta feature existir (ou perda do arquivo
    de estado) — nunca inventa dado, só relê o que a própria trilha já
    registrou no momento da entrada real. Usa o mesmo override de
    `AUDIT_PATH` do `src/logger.py` (fix #14 do projeto) para nunca ler o
    arquivo errado quando a trilha estiver redirecionada (ex.: backtest)."""
    audit_path = _audit_path()
    if not audit_path.exists():
        return None
    last = None
    with open(audit_path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if event.get("event") == "order_executed" and event.get("symbol") == symbol:
                last = event
    # Posição com TRAILING não tem take_profit (deliberado — o stop que sobe
    # é o mecanismo de realização): o gate antigo `not take_profit` tornava
    # TODA posição trailing irrecuperável do arquivo perdido, contradizendo o
    # próprio motivo de o executor gravar trailing/profile no evento (achado
    # confirmado da revisão adversarial de 20/07).
    if last is None or not (last.get("take_profit") or last.get("trailing")):
        return None
    return {
        "entry_price": last.get("entry_price") or 0.0,
        "take_profit": last.get("take_profit"),
        "stop_price": last.get("stop_price") or 0.0,
        "size": last.get("protect_size"),
        # side (28/07/2026): order_executed audita o lado da ORDEM de
        # entrada ("buy"/"sell", já existia desde sempre) — deriva a
        # direção da POSIÇÃO a partir dele. Só "sell" explícito vira
        # "short"; qualquer outra coisa (incl. ausente) cai em "long" —
        # mesmo default seguro de set_protection (spot/perp pré-short só
        # tinham long; nunca inverter o sinal do PnL por engano num campo
        # ausente).
        "side": "short" if last.get("side") == "sell" else "long",
        # stop_id: usado por engine.py pra confirmar o fill real do stop
        # quando a posição some sem passar pelo TP por software (18/07/2026).
        "stop_id": last.get("stop_id"),
        # tp_id (28/07/2026): só populado em PERP (spot nunca arma TP real).
        # Necessário pro backfill de uma posição perp aberta ANTES deste
        # campo existir/ser persistido continuar detectável no fechamento.
        "tp_id": last.get("tp_id"),
        # entry_id: só serve pra RECUPERAR o entry_price quando ele veio null
        # na trilha (trades anteriores ao fix #17) — engine.py consulta a
        # exchange sob demanda (_resolve_entry_price); este módulo continua
        # sem falar com a exchange, só relendo a trilha.
        "entry_id": last.get("entry_id"),
        # profile/trailing (20/07/2026): eventos antigos não têm os campos —
        # get() devolve None/False e a posição backfilled degrada pro
        # comportamento antigo (sem saída por sinal, sem trailing).
        "profile": last.get("profile"),
        "trailing": bool(last.get("trailing")),
        "trail_distance": last.get("trail_distance"),
        "peak_price": last.get("peak_price"),
    }
