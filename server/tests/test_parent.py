"""El orquestador se cierra solo si muere la app que lo lanzó (sonia/parent.py)."""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys

import pytest

from sonia.config import Settings
from sonia.parent import ParentProcess, watch_parent


class FakeParent:
    """Una app que sigue viva ``checks_alive`` comprobaciones y luego muere."""

    def __init__(self, checks_alive: int) -> None:
        self.remaining = checks_alive
        self.checks = 0
        self.closed = False

    def alive(self) -> bool:
        self.checks += 1
        if self.remaining <= 0:
            return False
        self.remaining -= 1
        return True

    def close(self) -> None:
        self.closed = True


async def test_avisa_cuando_muere_la_app() -> None:
    parent = FakeParent(checks_alive=2)
    gone: list[bool] = []
    await asyncio.wait_for(
        watch_parent(1234, lambda: gone.append(True), interval=0, process=parent), timeout=2
    )
    assert gone == [True]
    assert parent.checks == 3
    assert parent.closed


async def test_si_se_cancela_no_avisa() -> None:
    parent = FakeParent(checks_alive=10**9)
    gone: list[bool] = []
    task = asyncio.create_task(
        watch_parent(1234, lambda: gone.append(True), interval=0.01, process=parent)
    )
    await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert gone == []
    assert parent.closed


async def test_cancela_la_tarea_principal_como_ctrl_c() -> None:
    """Como en ``sonia run``: al morir la app se cancela la tarea que espera."""
    parent = FakeParent(checks_alive=1)

    async def main() -> str:
        me = asyncio.current_task()
        assert me is not None
        watcher = asyncio.create_task(watch_parent(1234, me.cancel, interval=0, process=parent))
        try:
            await asyncio.sleep(10)
        except asyncio.CancelledError:
            return "cerrado"
        finally:
            watcher.cancel()
        return "sigue"

    assert await asyncio.wait_for(main(), timeout=2) == "cerrado"


@pytest.mark.skipif(sys.platform == "win32", reason="procesos de macOS y Linux")
def test_procesos_de_verdad() -> None:
    assert ParentProcess(os.getpid()).alive()
    # pytest es hijo directo de su padre: ahí se vigila por getppid().
    assert ParentProcess(os.getppid()).alive()
    child = subprocess.Popen([sys.executable, "-c", "pass"])
    child.wait()
    assert not ParentProcess(child.pid).alive()


def test_el_pid_de_la_app_sale_del_entorno(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SONIA_PARENT_PID", raising=False)
    assert Settings(_env_file=None).sonia_parent_pid is None
    monkeypatch.setenv("SONIA_PARENT_PID", "4321")
    assert Settings(_env_file=None).sonia_parent_pid == 4321


@pytest.mark.parametrize("raw", ["no-es-un-pid", "0", "-5"])
def test_un_pid_raro_no_impide_arrancar(monkeypatch: pytest.MonkeyPatch, raw: str) -> None:
    monkeypatch.setenv("SONIA_PARENT_PID", raw)
    assert Settings(_env_file=None).sonia_parent_pid is None
