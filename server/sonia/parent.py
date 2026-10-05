"""El orquestador se cierra solo cuando muere la app que lo lanzó.

En la app todo en uno, Unity (``OrchestratorProcess``) lanza el orquestador y le
pasa su PID en ``SONIA_PARENT_PID`` (``Settings.sonia_parent_pid``). Al salir bien,
la app le manda SIGINT; pero si muere de golpe (se cuelga, salida forzada, un
``kill``) nadie se lo manda y el orquestador se quedaba huérfano: con el micrófono
abierto y, en «Conversando», la sesión de GPT-Live gastando. Jean: «que cierre
solo cuando muera la app».

:func:`watch_parent` comprueba cada pocos segundos que la app sigue viva y, si no,
llama a ``on_gone``; ``sonia run`` cancela entonces su tarea principal y sale igual
que con Ctrl+C (cierra la sesión de GPT-Live, el panel y el WebSocket).
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from collections.abc import Callable
from typing import Protocol

__all__ = ["CHECK_INTERVAL_S", "ParentProcess", "watch_parent"]

logger = logging.getLogger(__name__)

#: Cada cuánto se comprueba que la app sigue viva (s).
CHECK_INTERVAL_S = 2.0

# Windows: derecho para esperar a un proceso y respuestas de WaitForSingleObject.
_SYNCHRONIZE = 0x0010_0000
_WAIT_OBJECT_0 = 0x0000_0000


class _Liveness(Protocol):
    def alive(self) -> bool: ...

    def close(self) -> None: ...


class ParentProcess:
    """La app que lanzó el orquestador, sin confundirla con otra que herede su PID.

    En macOS y Linux, si el orquestador es hijo directo de la app, que la app muera
    se ve en ``os.getppid()`` (pasa a ser launchd o init); si no, se pregunta por
    el PID. En Windows se abre la app una vez y se mira si su proceso terminó.
    Si no se puede vigilar, se da por viva: nunca se cierra Sonia por un error.
    """

    def __init__(self, pid: int) -> None:
        self.pid = pid
        self._handle: int | None = None
        self._direct_child = False
        if sys.platform == "win32":
            self._handle = _open_process(pid)
            if self._handle is None:
                logger.warning(
                    "No se puede vigilar la app (PID %d): el orquestador no se cerrará solo.", pid
                )
        else:
            self._direct_child = os.getppid() == pid

    def alive(self) -> bool:
        if sys.platform == "win32":
            return self._handle is None or not _process_ended(self._handle)
        if self._direct_child:
            return os.getppid() == self.pid
        return _pid_exists(self.pid)

    def close(self) -> None:
        if sys.platform == "win32" and self._handle is not None:
            _close_handle(self._handle)
            self._handle = None


async def watch_parent(
    pid: int,
    on_gone: Callable[[], object],
    *,
    interval: float = CHECK_INTERVAL_S,
    process: _Liveness | None = None,
) -> None:
    """Llama a ``on_gone`` cuando la app ``pid`` deja de existir (si se cancela antes, no)."""
    parent = process if process is not None else ParentProcess(pid)
    try:
        # Sondeo deliberado: el sistema no avisa de que muere otro proceso.
        while parent.alive():  # noqa: ASYNC110 - sondeo deliberado
            await asyncio.sleep(interval)
    finally:
        parent.close()
    logger.warning(
        "La app que lanzó el orquestador (PID %d) ya no está: se cierra el orquestador.", pid
    )
    on_gone()


def _pid_exists(pid: int) -> bool:
    """Si existe el proceso ``pid`` (macOS y Linux; en Windows ``os.kill`` lo mataría)."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes

    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _kernel32.OpenProcess.restype = wintypes.HANDLE
    _kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    _kernel32.WaitForSingleObject.restype = wintypes.DWORD
    _kernel32.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
    _kernel32.CloseHandle.restype = wintypes.BOOL
    _kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)

    def _open_process(pid: int) -> int | None:
        handle = _kernel32.OpenProcess(_SYNCHRONIZE, False, pid)
        return int(handle) if handle else None

    def _process_ended(handle: int) -> bool:
        # Solo «terminó» si el proceso está señalado; un error se toma por vivo.
        return int(_kernel32.WaitForSingleObject(handle, 0)) == _WAIT_OBJECT_0

    def _close_handle(handle: int) -> None:
        _kernel32.CloseHandle(handle)
