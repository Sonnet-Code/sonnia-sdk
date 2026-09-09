#!/usr/bin/env python3
"""Cliente de prueba del WebSocket de Sonia.

Se conecta al orquestador como si fuera un segundo Unity, envía un ``text_input``
y registra con marcas de tiempo los mensajes que llegan (estados, frases,
visemas, imágenes) hasta que Sonia vuelve a ``idle``. Sirve para sincronizar
capturas de pantalla con lo que está pasando y para depurar el protocolo.

Uso (desde server/):
    uv run --no-sync python ../scripts/ws_probe.py "Hola Sonia" --url ws://127.0.0.1:8765
"""

from __future__ import annotations

import argparse
import asyncio
import json
import struct
import time


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("text", nargs="?", default="Hola Sonia, ¿qué es Sonnet Code?")
    parser.add_argument("--url", default="ws://127.0.0.1:8765")
    parser.add_argument("--timeout", type=float, default=90.0)
    parser.add_argument("--no-send", action="store_true", help="solo escuchar, sin enviar texto")
    args = parser.parse_args()

    import websockets

    t0 = time.monotonic()

    def stamp() -> str:
        return f"{time.monotonic() - t0:6.2f}s"

    async with websockets.connect(args.url, max_size=32 * 1024 * 1024) as ws:
        print(stamp(), "conectado a", args.url)
        if not args.no_send:
            await ws.send(json.dumps({"type": "text_input", "text": args.text}))
            print(stamp(), "enviado text_input:", args.text)
        audio_bytes = 0
        last_state = None
        deadline = time.monotonic() + args.timeout
        while time.monotonic() < deadline:
            try:
                msg = await asyncio.wait_for(
                    ws.recv(), timeout=max(0.1, deadline - time.monotonic())
                )
            except TimeoutError:
                break
            if isinstance(msg, bytes):
                if len(msg) >= 12 and msg[:4] == b"SNIA":
                    uid, flags = struct.unpack_from("<II", msg, 4)
                    audio_bytes += len(msg) - 12
                    if flags & 1:
                        print(
                            stamp(),
                            f"audio frase {uid}: último chunk (acumulado {audio_bytes} bytes)",
                        )
                continue
            data = json.loads(msg)
            kind = data.get("type")
            if kind == "state":
                last_state = data.get("state")
                print(stamp(), "estado ->", last_state)
                if last_state == "idle" and audio_bytes > 0:
                    print(stamp(), "turno terminado")
                    break
            elif kind == "speech_start":
                print(stamp(), f"speech_start {data.get('utterance_id')}: {data.get('text')}")
            elif kind == "speech_end":
                print(stamp(), f"speech_end {data.get('utterance_id')}")
            elif kind == "visemes":
                print(
                    stamp(),
                    f"visemes {data.get('utterance_id')}: {len(data.get('frames', []))} frames",
                )
            elif kind == "envelope":
                print(
                    stamp(),
                    f"envelope {data.get('utterance_id')}: {len(data.get('values', []))} valores",
                )
            elif kind == "transcript":
                print(stamp(), f"transcript {data.get('role')}: {data.get('text')}")
            elif kind == "show_image":
                print(stamp(), f"show_image {data.get('image_id')} ({data.get('mime')})")
            elif kind in ("hello", "hide_image", "stop_speaking", "error", "request_frame"):
                print(stamp(), kind, {k: v for k, v in data.items() if k != "type"})
        print(stamp(), "fin; último estado:", last_state)


if __name__ == "__main__":
    asyncio.run(main())
