"""La visión de los juegos sin cámara ni modelos: nada disponible y nada que se rompa."""

from __future__ import annotations

import asyncio

import numpy as np

from sonia.vision.games import unavailable_game_vision


def test_sin_vision_no_se_ofrece_nada() -> None:
    vision = unavailable_game_vision()

    async def run() -> None:
        assert not vision.stream.active
        assert await vision.stream.acquire("prueba") is False
        assert vision.stream.latest() is None
        assert await vision.preview.start("prueba") is False
        assert not vision.poses.available
        assert vision.poses.latest() is None
        frame = await vision.poses.detect(np.zeros((360, 640, 3), dtype=np.uint8), 1.0)
        assert frame.people == () and (frame.width, frame.height) == (640, 360)
        assert not vision.hands.available
        assert not vision.judge.available
        assert await vision.judge.ask("¿hay algo azul?") is None
        await vision.close()

    asyncio.run(run())
