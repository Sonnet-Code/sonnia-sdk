"""Helpers shared by the tests: a fake camera and an avatar client that records what it gets."""

from __future__ import annotations

import asyncio
import contextlib
import json
from collections.abc import Callable
from typing import Any

from sonia.types import Frame
from sonia.ws import protocol as p


class FakeCamera:
    def __init__(self, data: bytes = b"\xff\xd8fake-jpeg", delay: float = 0.0) -> None:
        self.data = data
        self.delay = delay
        self.captures = 0

    async def capture(self) -> Frame | None:
        self.captures += 1
        if self.delay:
            await asyncio.sleep(self.delay)
        return Frame(data=self.data, mime="image/jpeg", width=4, height=3)


class Recorder:
    """Records everything the test WebSocket client receives."""

    def __init__(self, client: Any) -> None:
        self.messages: list[Any] = []
        self._event = asyncio.Event()
        self._task = asyncio.create_task(self._pump(client))

    async def _pump(self, client: Any) -> None:
        with contextlib.suppress(Exception):
            async for raw in client:
                if isinstance(raw, bytes | bytearray):
                    self.messages.append(("audio", *p.decode_audio_frame(bytes(raw))))
                else:
                    self.messages.append(json.loads(raw))
                self._event.set()

    async def wait_for(self, predicate: Callable[[list[Any]], bool], limit: float = 3.0) -> None:
        async with asyncio.timeout(limit):
            while not predicate(self.messages):
                self._event.clear()
                await self._event.wait()

    async def wait_state(self, state: str, count: int = 1, limit: float = 3.0) -> None:
        await self.wait_for(lambda msgs: self.states(msgs).count(state) >= count, limit)

    async def wait_type(self, kind: str, count: int = 1, limit: float = 3.0) -> None:
        await self.wait_for(lambda msgs: self.of_type(kind, msgs).__len__() >= count, limit)

    def json(self, msgs: list[Any] | None = None) -> list[dict[str, Any]]:
        return [m for m in (self.messages if msgs is None else msgs) if isinstance(m, dict)]

    def of_type(self, kind: str, msgs: list[Any] | None = None) -> list[dict[str, Any]]:
        return [m for m in self.json(msgs) if m["type"] == kind]

    def states(self, msgs: list[Any] | None = None) -> list[str]:
        return [m["state"] for m in self.of_type("state", msgs)]

    def audio(self, utterance_id: int | None = None) -> list[tuple[str, int, bool, bytes]]:
        frames = [m for m in self.messages if isinstance(m, tuple) and m[0] == "audio"]
        if utterance_id is None:
            return frames
        return [f for f in frames if f[1] == utterance_id]

    def kinds(self) -> list[str]:
        """Sequence of types, with the binary frames collapsed into ``audio``."""
        out: list[str] = []
        for m in self.messages:
            kind = m[0] if isinstance(m, tuple) else m["type"]
            if kind == "audio" and out and out[-1] == "audio":
                continue
            out.append(kind)
        return out

    async def close(self) -> None:
        self._task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self._task
