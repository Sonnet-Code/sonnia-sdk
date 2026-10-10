"""El orquestador falso de las pantallas (``scripts/juegos_demo.py``): una Unity de mentira
se conecta, anuncia sus juegos y recibe la secuencia, las capturas y ``dev_done``."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import numpy as np
import pytest

from sonia.games.demo import (
    EXAMPLE,
    MSG_DEV_CAPTURE,
    MSG_DEV_DONE,
    Capture,
    GameMsg,
    Preview,
    Send,
    Step,
    Wait,
    WaitEvent,
    capture_name,
    example_steps,
    load_demo,
    serve_demo,
)
from sonia.ws import protocol as p


async def _fake_unity(
    steps: list[Step], *, events: list[dict[str, Any]] | None = None, hello: bool = True
) -> tuple[int, list[Any]]:
    """Corre ``serve_demo`` y una Unity de mentira; devuelve el código y lo que recibió."""
    from websockets.asyncio.client import connect

    ready: asyncio.Future[int] = asyncio.get_running_loop().create_future()
    logs: list[str] = []
    server = asyncio.create_task(
        serve_demo(
            steps,
            game="ruleta",
            port=0,
            connect_timeout=2.0,
            after_capture_s=0.0,
            on_ready=ready.set_result,
            log=logs.append,
        )
    )
    port = await asyncio.wait_for(ready, 2.0)
    received: list[Any] = []
    async with connect(f"ws://127.0.0.1:{port}/") as unity:
        if hello:
            await unity.send(
                json.dumps(
                    {
                        "type": "client_hello",
                        "client": "unity",
                        "version": "test",
                        "games": ["ruleta"],
                        "features": ["camera_preview"],
                    }
                )
            )
        for event in events or []:
            await unity.send(json.dumps(event))
        try:
            async with asyncio.timeout(10.0):
                async for raw in unity:
                    received.append(raw if isinstance(raw, bytes) else json.loads(raw))
                    if isinstance(received[-1], dict) and received[-1]["type"] == MSG_DEV_DONE:
                        break
        except Exception:  # noqa: BLE001 - el servidor puede cerrar al acabar
            pass
    code = await asyncio.wait_for(server, 5.0)
    return code, received


async def test_la_secuencia_llega_con_su_sobre_capturas_y_dev_done() -> None:
    pytest.importorskip("cv2")
    drawn: list[bool] = []

    def draw(frame: np.ndarray, mirrored: bool) -> None:
        drawn.append(mirrored)
        frame[0:4, 0:4] = 255

    steps: list[Step] = [
        GameMsg("start", {"title": "Ruleta"}),
        Send({"type": "state", "state": "speaking"}),
        Capture("ruleta 1/empezar", settle_s=0.0),
        Preview(0.35, fps=20.0, draw=draw, off=True),
        Wait(0.5),
        GameMsg("end", {"result": "win"}),
    ]
    code, received = await _fake_unity(steps)
    assert code == 0
    texts = [m for m in received if isinstance(m, dict)]
    kinds = [m["type"] for m in texts]
    # Al conectar: hello y volumen a cero (las pruebas van en silencio).
    assert kinds[:2] == ["hello", "set_volume"] and texts[1]["value"] == 0.0
    games = [m for m in texts if m["type"] == "game"]
    assert [g["event"] for g in games] == ["start", "end"]
    assert games[0]["game"] == "ruleta" and games[0]["data"] == {"title": "Ruleta"}
    assert games[1]["seq"] > games[0]["seq"]
    assert {"type": "state", "state": "speaking"} in texts
    assert {"type": MSG_DEV_CAPTURE, "name": "ruleta_1_empezar"} in texts
    previews = [m for m in texts if m["type"] == "camera_preview"]
    assert [m["on"] for m in previews] == [True, False]
    frames = [p.decode_preview_frame(b) for b in received if isinstance(b, bytes)]
    assert frames and all(f[1:4] == (640, 360, True) for f in frames)
    assert [f[0] for f in frames] == sorted(f[0] for f in frames)
    assert frames[0][4][:2] == b"\xff\xd8"  # JPEG
    assert drawn and all(drawn)
    assert kinds[-1] == MSG_DEV_DONE


async def test_espera_el_game_event_de_unity() -> None:
    steps: list[Step] = [WaitEvent("wheel_stopped", timeout=2.0), GameMsg("prize", {"n": 1})]
    event = {"type": "game_event", "game": "ruleta", "event": "wheel_stopped", "data": {}}
    code, received = await _fake_unity(steps, events=[event])
    assert code == 0
    assert [m["event"] for m in received if isinstance(m, dict) and m["type"] == "game"] == [
        "prize"
    ]


async def test_sin_unity_no_se_queda_colgado() -> None:
    logs: list[str] = []
    code = await serve_demo(
        [Wait(0.1)], game="ruleta", port=0, connect_timeout=0.2, log=logs.append
    )
    assert code == 1


def test_secuencias() -> None:
    assert load_demo(EXAMPLE) == example_steps()
    with pytest.raises(LookupError, match="no hay ningún juego"):
        load_demo("no_existe")
    assert capture_name(" wordle 2/jugada ") == "wordle_2_jugada"
