"""The orchestrator shuts itself down when the app that launched it dies.

In the all-in-one app, Unity (``OrchestratorProcess``) launches the orchestrator
and passes it its PID in ``SONIA_PARENT_PID`` (``Settings.sonia_parent_pid``). On a
clean exit the app sends it SIGINT; but if the app dies abruptly (it hangs, a
forced quit, a ``kill``) nobody sends it, and the orchestrator used to be left
orphaned: with the microphone open and, while conversing, the GPT-Live session
still running up costs.

:func:`watch_parent` checks every few seconds that the app is still alive and, if
not, calls ``on_gone``; ``sonia run`` then cancels its main task and exits just as
with Ctrl+C (it closes the GPT-Live session, the panel and the WebSocket).
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

#: How often to check that the app is still alive (s).
CHECK_INTERVAL_S = 2.0

# Windows: access right to wait on a process, and WaitForSingleObject results.
_SYNCHRONIZE = 0x0010_0000
_WAIT_OBJECT_0 = 0x0000_0000


class _Liveness(Protocol):
    def alive(self) -> bool: ...

    def close(self) -> None: ...


class ParentProcess:
    """The app that launched the orchestrator, not another process that reused its PID.

    On macOS and Linux, if the orchestrator is a direct child of the app, the app's
    death shows in ``os.getppid()`` (it becomes launchd or init); otherwise the PID
    is queried. On Windows the app is opened once and its process is checked for
    termination. If it cannot be watched, it is assumed alive: Sonnia is never shut
    down because of an error.
    """

    def __init__(self, pid: int) -> None:
        self.pid = pid
        self._handle: int | None = None
        self._direct_child = False
        if sys.platform == "win32":
            self._handle = _open_process(pid)
            if self._handle is None:
                logger.warning(
                    "Cannot watch the app (PID %d): the orchestrator will not exit on its own.", pid
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
    """Calls ``on_gone`` when the app ``pid`` no longer exists (not if cancelled first)."""
    parent = process if process is not None else ParentProcess(pid)
    try:
        # Deliberate polling: the OS does not notify us when another process dies.
        while parent.alive():  # noqa: ASYNC110 - deliberate polling
            await asyncio.sleep(interval)
    finally:
        parent.close()
    logger.warning(
        "The app that launched the orchestrator (PID %d) is gone: shutting down the orchestrator.",
        pid,
    )
    on_gone()


def _pid_exists(pid: int) -> bool:
    """Whether process ``pid`` exists (macOS and Linux; on Windows ``os.kill`` would kill it)."""
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
        # It has only "ended" if the process is signaled; an error counts as alive.
        return int(_kernel32.WaitForSingleObject(handle, 0)) == _WAIT_OBJECT_0

    def _close_handle(handle: int) -> None:
        _kernel32.CloseHandle(handle)
