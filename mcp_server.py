"""Servidor MCP de supervisão do Bybit Auto Trader (Fase 4).

Expõe o estado do sistema ao Claude via MCP (stdio local), para você perguntar
em linguagem natural: "como está o PnL?", "quais posições estão abertas?",
"por que entrou nesse short?", "o kill switch disparou?".

FRONTEIRA DE SEGURANÇA (deliberada):
  - Tools de LEITURA: status, posições, PnL, decisões, explicação — read-only.
  - Tools de CONTROLE: apenas PARAR (halt) e RESETAR o kill switch. São ações do
    operador sobre a segurança do sistema, não sobre o mercado.
  - NÃO existe tool para abrir/fechar posição, enviar ordem ou mover fundos. Por
    princípio, execução de trade nunca passa por aqui.

Execução:
    pip install "mcp[cli]"
    python mcp_server.py
Registro no Claude Desktop: ver README (seção "Supervisão via MCP").
"""
from __future__ import annotations

import json
import os

from mcp.server.fastmcp import FastMCP

from config.settings import get_credentials, get_market_type, load_risk_config
from src.exchange.bybit_client import BybitClient
from src.supervision.state_reader import StateReader

mcp = FastMCP("wonder_trader_mcp")


def _reader() -> StateReader:
    """Cria o leitor de estado. Tenta conectar à exchange; se faltar chave,
    opera em modo offline (só a trilha de auditoria fica disponível).

    Lê market.type do YAML para o supervisor enxergar a MESMA modalidade que o
    engine: em spot, "posição" é saldo de moeda (fetch_spot_holdings) — sem
    isto o MCP respondia "sem posições" com exposição real na conta."""
    try:
        cfg = load_risk_config()
        market_type = get_market_type(cfg)
        symbols = [s.split(":")[0] if market_type == "spot" else s
                   for s in cfg["trading"]["symbols"]]
        client = BybitClient(
            get_credentials(),
            default_type="spot" if market_type == "spot" else "swap",
        )
        return StateReader(client, market_type=market_type, symbols=symbols)
    except Exception:  # noqa: BLE001 — sem chave/erro de conexão -> modo offline
        return StateReader(None)


def _json(data) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2, default=str)


@mcp.tool(
    name="trader_get_status",
    annotations={"title": "Status da conta", "readOnlyHint": True,
                 "destructiveHint": False, "idempotentHint": True, "openWorldHint": True},
)
def trader_get_status() -> str:
    """Resumo da conta: ambiente (testnet/mainnet), equity, nº de posições e PnL
    não realizado. Use para responder 'como está a banca / o PnL agora?'."""
    return _json(_reader().read_account())


@mcp.tool(
    name="trader_get_positions",
    annotations={"title": "Posições abertas", "readOnlyHint": True,
                 "destructiveHint": False, "idempotentHint": True, "openWorldHint": True},
)
def trader_get_positions() -> str:
    """Lista as posições abertas (símbolo, lado, contratos, preço de entrada, PnL,
    alavancagem). Use para 'quais trades estão abertos?'."""
    return _json(_reader().read_positions())


@mcp.tool(
    name="trader_recent_decisions",
    annotations={"title": "Decisões recentes", "readOnlyHint": True,
                 "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
)
def trader_recent_decisions(limit: int = 20) -> str:
    """Últimas decisões do sistema (aprovado, vetado, executado, sinal do LLM,
    kill switch), do mais recente ao mais antigo. Use para 'o que rolou agora?'.

    Args:
        limit: quantos eventos retornar (1-100).
    """
    limit = max(1, min(100, int(limit)))
    return _json(_reader().recent_decisions(limit=limit))


@mcp.tool(
    name="trader_explain_symbol",
    annotations={"title": "Explicar decisões de um símbolo", "readOnlyHint": True,
                 "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
)
def trader_explain_symbol(symbol: str, limit: int = 10) -> str:
    """Mostra as últimas decisões de um símbolo COM o racional — o 'por quê' de ter
    entrado, vetado ou ficado de fora. Use para 'por que entrou nesse short de ETH?'.

    Args:
        symbol: par no formato CCXT, ex. 'BTC/USDT:USDT'.
        limit: quantas decisões retornar (1-50).
    """
    limit = max(1, min(50, int(limit)))
    return _json(_reader().explain_symbol(symbol, limit=limit))


@mcp.tool(
    name="trader_halt_status",
    annotations={"title": "Status do kill switch", "readOnlyHint": True,
                 "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
)
def trader_halt_status() -> str:
    """Diz se o kill switch está ativo e por quê (última razão). Use para
    'o sistema está pausado? por quê?'."""
    return _json(_reader().read_halt_status())


@mcp.tool(
    name="trader_realized_pnl",
    annotations={"title": "PnL realizado (trilha)", "readOnlyHint": True,
                 "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
)
def trader_realized_pnl(limit: int = 500) -> str:
    """PnL realizado agregado pelos fechamentos registrados na trilha (visão rápida;
    o exato vem da exchange). Use para 'quanto realizei até agora?'.

    Args:
        limit: quantos eventos recentes considerar.
    """
    return _json(_reader().realized_pnl(limit=max(1, int(limit))))


@mcp.tool(
    name="trader_request_halt",
    annotations={"title": "Sinalizar parada (kill switch manual)", "readOnlyHint": False,
                 "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
)
def trader_request_halt(reason: str = "parada manual via MCP") -> str:
    """Grava um pedido de PARADA para o engine (kill switch manual). O engine lê o
    arquivo de sinal a cada ciclo e pausa novas entradas. NÃO fecha posições nem
    envia ordens — apenas interrompe novas entradas até reset.

    Args:
        reason: motivo registrado para auditoria.
    """
    _write_control_signal("halt", reason)
    return _json({"ok": True, "action": "halt_requested", "reason": reason})


@mcp.tool(
    name="trader_request_reset",
    annotations={"title": "Resetar kill switch", "readOnlyHint": False,
                 "destructiveHint": False, "idempotentHint": False, "openWorldHint": False},
)
def trader_request_reset(confirm: bool = False) -> str:
    """Solicita o reset do kill switch (retomar novas entradas). Exige confirm=True
    para evitar reset acidental. Ação deliberada do operador.

    Args:
        confirm: precisa ser True para efetivar.
    """
    if not confirm:
        return _json({"ok": False, "error": "reset requer confirm=True (ação deliberada)"})
    _write_control_signal("reset", "reset manual via MCP")
    return _json({"ok": True, "action": "reset_requested"})


@mcp.tool(
    name="trader_cooldown_status",
    annotations={"title": "Status de cooldown por símbolo", "readOnlyHint": True,
                 "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
)
def trader_cooldown_status() -> str:
    """Mostra, por símbolo, se há cooldown ativo agora (pausa de entrada após
    stop, escalando 30min/60min/24h no 1º/2º/3º+ do dia), até quando, e
    quantas vezes já acionou hoje. Use para 'algum símbolo está em cooldown?'
    ou 'quando o ETH volta a poder operar?'."""
    return _json(_reader().read_cooldown_status())


@mcp.tool(
    name="trader_reset_cooldown",
    annotations={"title": "Liberar cooldown manualmente", "readOnlyHint": False,
                 "destructiveHint": False, "idempotentHint": False, "openWorldHint": False},
)
def trader_reset_cooldown(symbol: str, confirm: bool = False) -> str:
    """Solicita a liberação manual do cooldown ativo de um símbolo, antes do
    prazo natural (ex.: a pausa de 24h do 3º stop do dia). Exige confirm=True.
    Ação deliberada do operador — mesma filosofia do reset do kill switch.

    Args:
        symbol: par no formato CCXT, ex. 'BTC/USDT:USDT'.
        confirm: precisa ser True para efetivar.
    """
    if not confirm:
        return _json({"ok": False, "error": "reset requer confirm=True (ação deliberada)"})
    _write_control_signal("reset_cooldown", f"reset manual de cooldown via MCP: {symbol}", symbol=symbol)
    return _json({"ok": True, "action": "cooldown_reset_requested", "symbol": symbol})


def _write_control_signal(action: str, reason: str, symbol: str | None = None) -> None:
    """Escreve um sinal de controle que o engine lê no próximo ciclo.

    Desacopla o MCP do engine: o MCP não controla o processo do engine diretamente,
    só deixa um sinal em disco. O engine decide como agir — mantém a fronteira limpa."""
    from pathlib import Path
    from datetime import datetime, timezone
    ctrl_dir = Path(__file__).resolve().parent / "state"
    ctrl_dir.mkdir(exist_ok=True)
    payload = {"action": action, "reason": reason,
               "ts": datetime.now(timezone.utc).isoformat()}
    if symbol is not None:
        payload["symbol"] = symbol
    with open(ctrl_dir / "control.json", "w", encoding="utf-8") as fh:
        json.dump(payload, fh)


if __name__ == "__main__":
    mcp.run()
