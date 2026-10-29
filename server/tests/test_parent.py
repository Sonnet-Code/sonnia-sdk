"""The orchestrator shuts itself down if the app that launched it dies (sonia/parent.py)."""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys

import pytest

from sonia.config import Settings
from sonia.parent import ParentProcess, watch_parent


class FakeParent:
    """An app that stays alive for ``checks_alive`` checks and then dies."""

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


async def test_notifies_when_the_app_dies() -> None:
    parent = FakeParent(checks_alive=2)
    gone: list[bool] = []
    await asyncio.wait_for(
        watch_parent(1234, lambda: gone.append(True), interval=0, process=parent), timeout=2
    )
    assert gone == [True]
    assert parent.checks == 3
    assert parent.closed


async def test_does_not_notify_if_cancelled() -> None:
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


async def test_cancels_the_main_task_like_ctrl_c() -> None:
    """As in ``sonia run``: when the app dies, the waiting task is cancelled."""
    parent = FakeParent(checks_alive=1)

    async def main() -> str:
        me = asyncio.current_task()
        assert me is not None
        watcher = asyncio.create_task(watch_parent(1234, me.cancel, interval=0, process=parent))
        try:
            await asyncio.sleep(10)
        except asyncio.CancelledError:
            return "closed"
        finally:
            watcher.cancel()
        return "still running"

    assert await asyncio.wait_for(main(), timeout=2) == "closed"


@pytest.mark.skipif(sys.platform == "win32", reason="macOS and Linux processes")
def test_real_processes() -> None:
    assert ParentProcess(os.getpid()).alive()
    # pytest is a direct child of its parent: there it is watched through getppid().
    assert ParentProcess(os.getppid()).alive()
    child = subprocess.Popen([sys.executable, "-c", "pass"])
    child.wait()
    assert not ParentProcess(child.pid).alive()


def test_app_pid_comes_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SONIA_PARENT_PID", raising=False)
    assert Settings(_env_file=None).sonia_parent_pid is None
    monkeypatch.setenv("SONIA_PARENT_PID", "4321")
    assert Settings(_env_file=None).sonia_parent_pid == 4321


@pytest.mark.parametrize("raw", ["not-a-pid", "0", "-5"])
def test_invalid_pid_does_not_prevent_startup(monkeypatch: pytest.MonkeyPatch, raw: str) -> None:
    monkeypatch.setenv("SONIA_PARENT_PID", raw)
    assert Settings(_env_file=None).sonia_parent_pid is None
