"""Servidor MCP local que expone las mismas acciones que el tool calling.

Una única definición de acciones (``sonia.actions``) alimenta las dos vías: el
tool calling nativo del modelo y este servidor MCP, pensado para modelos o
servidores que no soportan tool calling.

Transporte: streamable HTTP servido con uvicorn en ``MCP_HOST``/``MCP_PORT``.
Todos los imports de ``mcp`` y ``uvicorn`` son perezosos: el paquete se puede
importar aunque el extra no esté instalado.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Callable, Mapping
from typing import TYPE_CHECKING, Any, Protocol

from sonia.config import MCPSettings
from sonia.types import ActionContext, ActionResult

if TYPE_CHECKING:  # pragma: no cover - solo para tipado
    from mcp.server.lowlevel import Server as LowLevelServer

logger = logging.getLogger(__name__)

#: Esquema vacío por defecto para acciones sin argumentos.
_EMPTY_SCHEMA: dict[str, Any] = {"type": "object", "properties": {}}


class ActionRegistryLike(Protocol):
    """Lo que el servidor MCP necesita del registro de acciones."""

    async def execute(
        self, name: str, args: dict[str, Any], ctx: ActionContext
    ) -> ActionResult: ...


def is_available() -> bool:
    """¿Están instalados los extras necesarios (``mcp`` y ``uvicorn``)?"""
    from importlib.util import find_spec

    try:
        return find_spec("mcp") is not None and find_spec("uvicorn") is not None
    except (ImportError, ValueError):  # pragma: no cover - entornos raros
        return False


def tool_definitions(registry: Any) -> list[dict[str, Any]]:
    """Traduce las acciones del registro a definiciones de tool MCP.

    Devuelve diccionarios ``{"name", "description", "inputSchema"}`` sin tocar
    la librería ``mcp``, para poder inspeccionarlos en tests sin el extra.
    """
    # 1) El registro ya sabe hablar MCP.
    to_mcp = getattr(registry, "to_mcp_tools", None)
    if callable(to_mcp):
        return [
            {
                "name": tool["name"],
                "description": tool.get("description", ""),
                "inputSchema": dict(tool.get("inputSchema") or _EMPTY_SCHEMA),
            }
            for tool in to_mcp()
        ]
    # 2) Los ``ActionSpec`` en crudo.
    specs = _iter_specs(registry)
    if specs is not None:
        return [
            {
                "name": spec.name,
                "description": spec.description,
                "inputSchema": dict(spec.parameters or _EMPTY_SCHEMA),
            }
            for spec in specs
        ]
    # 3) Último recurso: derivarlas del formato OpenAI.
    tools: list[dict[str, Any]] = []
    for tool in registry.to_openai_tools():
        function = tool.get("function", tool)
        tools.append(
            {
                "name": function["name"],
                "description": function.get("description", ""),
                "inputSchema": dict(function.get("parameters") or _EMPTY_SCHEMA),
            }
        )
    return tools


def _iter_specs(registry: Any) -> list[Any] | None:
    """Obtiene los ``ActionSpec`` del registro, sea cual sea su forma."""
    for attribute in ("specs", "actions"):
        value = getattr(registry, attribute, None)
        if value is None:
            continue
        if callable(value):
            value = value()
        if isinstance(value, Mapping):
            return list(value.values())
        return list(value)
    if hasattr(registry, "__iter__"):
        return list(registry)
    return None


class MCPServer:
    """Expone un ``ActionRegistry`` como servidor MCP por HTTP."""

    #: Nombre y versión que anuncia el servidor en el handshake.
    NAME = "sonia"
    VERSION = "1.0.0"
    #: Ruta del endpoint streamable HTTP.
    PATH = "/mcp"

    def __init__(
        self,
        registry: ActionRegistryLike,
        ctx_factory: Callable[[], ActionContext],
        settings: MCPSettings,
    ) -> None:
        self._registry = registry
        self._ctx_factory = ctx_factory
        self._settings = settings
        self._server: LowLevelServer[Any] | None = None
        self._uvicorn: Any | None = None
        self._task: asyncio.Task[None] | None = None

    # -- definición de tools ------------------------------------------------

    @property
    def url(self) -> str:
        return f"http://{self._settings.host}:{self._settings.port}{self.PATH}"

    def tool_definitions(self) -> list[dict[str, Any]]:
        """Definiciones de las tools tal como se anuncian por MCP."""
        return tool_definitions(self._registry)

    def build_server(self) -> LowLevelServer[Any]:
        """Construye (una vez) el servidor MCP de bajo nivel.

        Se usa la API de bajo nivel a propósito: los esquemas de argumentos son
        los JSON Schema de las acciones, no se infieren de firmas de funciones.
        """
        if self._server is not None:
            return self._server
        from mcp.server.lowlevel import Server

        self._server = Server(
            self.NAME,
            version=self.VERSION,
            instructions="Acciones de Sonia: mirar por la cámara y mostrar u ocultar imágenes.",
            on_list_tools=self._handle_list_tools,
            on_call_tool=self._handle_call_tool,
        )
        return self._server

    # -- handlers MCP -------------------------------------------------------

    async def _handle_list_tools(self, ctx: Any, params: Any) -> Any:
        import mcp.types as types

        tools = [
            types.Tool(
                name=t["name"],
                description=t["description"],
                input_schema=t["inputSchema"],
            )
            for t in self.tool_definitions()
        ]
        return types.ListToolsResult(tools=tools)

    async def _handle_call_tool(self, ctx: Any, params: Any) -> Any:
        import mcp.types as types

        name = params.name
        arguments = dict(params.arguments or {})
        try:
            result = await self.execute(name, arguments)
        except Exception as exc:  # noqa: BLE001 - el error vuelve al modelo
            logger.exception("Error ejecutando la acción %r por MCP", name)
            return types.CallToolResult(
                content=[types.TextContent(type="text", text=f"Error: {exc}")],
                is_error=True,
            )
        return types.CallToolResult(content=self._to_content(result))

    def _to_content(self, result: ActionResult) -> list[Any]:
        """Convierte un ``ActionResult`` en contenidos MCP (texto e imagen)."""
        import base64

        import mcp.types as types

        content: list[Any] = [types.TextContent(type="text", text=result.text)]
        if result.image is not None:
            content.append(
                types.ImageContent(
                    type="image",
                    data=base64.b64encode(result.image.data).decode("ascii"),
                    mime_type=result.image.mime,
                )
            )
        return content

    async def execute(self, name: str, arguments: dict[str, Any]) -> ActionResult:
        """Ejecuta una acción del registro con un contexto fresco."""
        ctx = self._ctx_factory()
        return await self._registry.execute(name, arguments, ctx)

    # -- ciclo de vida ------------------------------------------------------

    async def start(self) -> None:
        """Arranca uvicorn en una tarea de fondo. Idempotente."""
        if self._task is not None:
            return
        import uvicorn

        app = self.build_server().streamable_http_app(
            streamable_http_path=self.PATH,
            host=self._settings.host,
            stateless_http=True,
        )
        config = uvicorn.Config(
            app,
            host=self._settings.host,
            port=self._settings.port,
            log_level="warning",
            access_log=False,
        )
        self._uvicorn = uvicorn.Server(config)
        # ``_serve`` en vez de ``serve`` para no secuestrar las señales del
        # proceso: el orquestador gestiona su propio Ctrl-C.
        run = getattr(self._uvicorn, "_serve", None) or self._uvicorn.serve
        self._task = asyncio.create_task(run(), name="mcp-server")
        await self._wait_until_listening()
        logger.info("Servidor MCP escuchando en %s", self.url)

    async def _wait_until_listening(self, limite: float = 10.0) -> None:
        """Espera a que uvicorn acepte conexiones (o a que falle al arrancar)."""
        assert self._task is not None
        loop = asyncio.get_running_loop()
        deadline = loop.time() + limite
        while not getattr(self._uvicorn, "started", False):
            if self._task.done():
                # Propaga el error de arranque (puerto ocupado, por ejemplo).
                self._task.result()
                return
            if loop.time() > deadline:  # pragma: no cover - solo si algo va muy mal
                logger.warning("El servidor MCP no arrancó en %.0f s", limite)
                return
            await asyncio.sleep(0.02)

    async def stop(self) -> None:
        """Para uvicorn y espera a que termine. Idempotente."""
        task, self._task = self._task, None
        server, self._uvicorn = self._uvicorn, None
        if task is None:
            return
        if server is not None:
            server.should_exit = True
        try:
            await asyncio.wait_for(asyncio.shield(task), timeout=5.0)
        except (TimeoutError, asyncio.CancelledError):
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
        except Exception:  # noqa: BLE001 - apagar nunca debe lanzar
            logger.exception("Error al parar el servidor MCP")
        logger.info("Servidor MCP detenido")
