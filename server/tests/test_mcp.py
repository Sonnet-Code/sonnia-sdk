"""Pruebas del servidor MCP que expone las acciones de Sonia.

No se llama a ningún servicio externo: el cliente MCP se conecta en proceso y,
en la prueba de transporte, a un uvicorn efímero en localhost.
"""

from __future__ import annotations

import base64
import socket
from typing import Any

import pytest

from sonia.config import MCPSettings
from sonia.mcp.server import MCPServer, is_available, tool_definitions
from sonia.types import ActionContext, ActionResult, ActionSpec, Frame

LOOK_SCHEMA: dict[str, Any] = {"type": "object", "properties": {}}
SHOW_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "image_id": {"type": "string", "description": "Id de la galería o 'camera'."},
        "caption": {"type": "string"},
    },
    "required": ["image_id"],
}


def _text(block: Any) -> str:
    """Texto de un bloque de contenido MCP, comprobando antes que lo es.

    El cliente devuelve una unión de tipos de contenido; estos ayudantes la
    estrechan para que las aserciones sean claras y el tipado no proteste.
    """
    from mcp.types import TextContent

    assert isinstance(block, TextContent), f"se esperaba texto, llegó {block!r}"
    return block.text


def _image(block: Any) -> tuple[bytes, str | None]:
    """Datos ya decodificados y mime de un bloque de imagen MCP."""
    from mcp.types import ImageContent

    assert isinstance(block, ImageContent), f"se esperaba imagen, llegó {block!r}"
    return base64.b64decode(block.data), block.mime_type


async def _look(ctx: ActionContext, args: dict[str, Any]) -> ActionResult:
    return ActionResult(
        text="Captura tomada.",
        image=Frame(data=b"\x89PNG\r\n", mime="image/png", width=4, height=2),
    )


async def _show_image(ctx: ActionContext, args: dict[str, Any]) -> ActionResult:
    return ActionResult(text=f"Mostrando {args['image_id']}.")


class FakeRegistry:
    """Registro mínimo con la misma superficie que ``ActionRegistry``."""

    def __init__(self) -> None:
        self.specs = [
            ActionSpec("look", "Mira por la cámara.", LOOK_SCHEMA, _look),
            ActionSpec("show_image", "Muestra una imagen.", SHOW_SCHEMA, _show_image),
        ]
        self.calls: list[tuple[str, dict[str, Any], ActionContext]] = []
        self.fail = False

    async def execute(self, name: str, args: dict[str, Any], ctx: ActionContext) -> ActionResult:
        self.calls.append((name, args, ctx))
        if self.fail:
            raise RuntimeError("registro roto")
        for spec in self.specs:
            if spec.name == name:
                return await spec.handler(ctx, args)
        return ActionResult(text=f"Error: la acción '{name}' no existe.")


class OpenAIOnlyRegistry:
    """Registro que solo sabe hablar el formato de OpenAI."""

    def to_openai_tools(self) -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": "hide_image",
                    "description": "Retira el panel.",
                    "parameters": LOOK_SCHEMA,
                },
            }
        ]

    async def execute(
        self, name: str, args: dict[str, Any], ctx: ActionContext
    ) -> ActionResult:  # pragma: no cover - no se ejecuta aquí
        return ActionResult(text="ok")


def _context() -> ActionContext:
    return ActionContext(camera=None, avatar=None, gallery_dir="/tmp/gallery")


def _server(registry: Any) -> MCPServer:
    return MCPServer(registry, _context, MCPSettings(host="127.0.0.1", port=0))


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


# ---------------------------------------------------------------------------
# Definición de tools (sin depender de la librería mcp)
# ---------------------------------------------------------------------------


def test_tool_definitions_desde_specs() -> None:
    tools = _server(FakeRegistry()).tool_definitions()
    assert [t["name"] for t in tools] == ["look", "show_image"]
    assert tools[0] == {
        "name": "look",
        "description": "Mira por la cámara.",
        "inputSchema": {"type": "object", "properties": {}},
    }
    assert tools[1]["inputSchema"]["required"] == ["image_id"]
    assert set(tools[1]["inputSchema"]["properties"]) == {"image_id", "caption"}


def test_tool_definitions_desde_registro_real() -> None:
    """El ``ActionRegistry`` del proyecto expone ``to_mcp_tools``."""
    modulo = pytest.importorskip("sonia.actions.registry")
    ActionRegistry = getattr(modulo, "ActionRegistry", None)
    if ActionRegistry is None:  # pragma: no cover - el módulo aún no existe
        pytest.skip("sonia.actions.registry todavía no expone ActionRegistry")

    registry = ActionRegistry()
    registry.register(ActionSpec("look", "Mira.", LOOK_SCHEMA, _look))
    assert tool_definitions(registry) == [
        {"name": "look", "description": "Mira.", "inputSchema": LOOK_SCHEMA}
    ]


def test_tool_definitions_desde_openai_tools() -> None:
    tools = tool_definitions(OpenAIOnlyRegistry())
    assert tools == [
        {"name": "hide_image", "description": "Retira el panel.", "inputSchema": LOOK_SCHEMA}
    ]


def test_url_y_disponibilidad() -> None:
    server = MCPServer(FakeRegistry(), _context, MCPSettings(host="127.0.0.1", port=8766))
    assert server.url == "http://127.0.0.1:8766/mcp"
    assert isinstance(is_available(), bool)


# ---------------------------------------------------------------------------
# Ejecución de acciones
# ---------------------------------------------------------------------------


async def test_execute_usa_un_contexto_fresco() -> None:
    registry = FakeRegistry()
    server = _server(registry)

    result = await server.execute("show_image", {"image_id": "logo-sonnet"})
    assert result.text == "Mostrando logo-sonnet."
    assert registry.calls[0][0] == "show_image"
    assert registry.calls[0][2].gallery_dir == "/tmp/gallery"

    await server.execute("show_image", {"image_id": "otra"})
    # Un contexto nuevo por llamada (el ``last_frame`` no se arrastra).
    assert registry.calls[0][2] is not registry.calls[1][2]


# ---------------------------------------------------------------------------
# Servidor MCP en proceso
# ---------------------------------------------------------------------------

mcp_instalado = pytest.mark.skipif(not is_available(), reason="el extra mcp no está instalado")


@mcp_instalado
async def test_list_tools_por_mcp() -> None:
    from mcp.client import Client

    server = _server(FakeRegistry())
    async with Client(server.build_server(), raise_exceptions=True) as client:
        listed = await client.list_tools()

    dumped = [t.model_dump(by_alias=True, exclude_none=True) for t in listed.tools]
    assert [t["name"] for t in dumped] == ["look", "show_image"]
    assert dumped[0]["inputSchema"] == LOOK_SCHEMA
    assert dumped[1]["inputSchema"] == SHOW_SCHEMA
    assert dumped[1]["description"] == "Muestra una imagen."


@mcp_instalado
async def test_call_tool_devuelve_texto_e_imagen() -> None:
    from mcp.client import Client

    registry = FakeRegistry()
    server = _server(registry)
    async with Client(server.build_server(), raise_exceptions=True) as client:
        solo_texto = await client.call_tool("show_image", {"image_id": "logo-sonnet"})
        con_imagen = await client.call_tool("look", {})

    assert not solo_texto.is_error
    assert [c.type for c in solo_texto.content] == ["text"]
    assert _text(solo_texto.content[0]) == "Mostrando logo-sonnet."
    assert registry.calls[0][1] == {"image_id": "logo-sonnet"}

    assert [c.type for c in con_imagen.content] == ["text", "image"]
    assert _text(con_imagen.content[0]) == "Captura tomada."
    assert _image(con_imagen.content[1]) == (b"\x89PNG\r\n", "image/png")


@mcp_instalado
async def test_call_tool_marca_error_si_el_registro_lanza() -> None:
    from mcp.client import Client

    registry = FakeRegistry()
    registry.fail = True
    server = _server(registry)
    async with Client(server.build_server()) as client:
        result = await client.call_tool("look", {})

    assert result.is_error
    assert "registro roto" in _text(result.content[0])


@mcp_instalado
def test_build_server_es_idempotente() -> None:
    server = _server(FakeRegistry())
    assert server.build_server() is server.build_server()


@mcp_instalado
async def test_start_y_stop_sirven_por_http() -> None:
    """Arranca uvicorn de verdad en un puerto libre de localhost."""
    from mcp.client import Client

    registry = FakeRegistry()
    server = MCPServer(registry, _context, MCPSettings(host="127.0.0.1", port=_free_port()))
    await server.start()
    await server.start()  # idempotente
    try:
        async with Client(server.url) as client:
            listed = await client.list_tools()
            result = await client.call_tool("show_image", {"image_id": "camera"})
    finally:
        await server.stop()
        await server.stop()  # idempotente

    assert [t.name for t in listed.tools] == ["look", "show_image"]
    assert _text(result.content[0]) == "Mostrando camera."
