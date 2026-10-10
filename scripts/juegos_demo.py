#!/usr/bin/env python3
"""Orquestador falso para probar las pantallas de los juegos sin Sonia (docs/juegos.md).

Un servidor WebSocket en su propio puerto que habla el protocolo con Unity y le manda,
paso a paso, la secuencia de un juego (``sonia/games/<paquete>/demo.py``) o la de
ejemplo (``--juego ejemplo``). Al conectar manda ``hello`` y ``set_volume`` a 0, espera
el ``client_hello`` de Unity, pide las capturas con ``dev_capture`` y al acabar manda
``dev_done``. No llama a ninguna API ni abre ninguna cámara.

Uso (desde server/):
    uv run --no-sync python ../scripts/juegos_demo.py --juego wordle --puerto 8791
    uv run --no-sync python ../scripts/juegos_demo.py --juego ejemplo --como ruleta

Y Unity, apuntada a él: ``-sonia-ws ws://127.0.0.1:8791`` (docs/juegos-unity.md).
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--juego", required=True, help="id del juego, o «ejemplo»")
    parser.add_argument(
        "--como",
        default="ruleta",
        help="con --juego ejemplo: el id de juego con el que van los mensajes (ruleta)",
    )
    parser.add_argument("--puerto", type=int, default=8791)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument(
        "--espera", type=float, default=180.0, help="segundos esperando a que Unity se conecte"
    )
    parser.add_argument(
        "--tras-captura",
        type=float,
        default=0.5,
        help="segundos que se deja a Unity tras pedir cada captura",
    )
    parser.add_argument(
        "--quedarse",
        action="store_true",
        help="no manda dev_done al acabar: sigue sirviendo hasta Ctrl+C",
    )
    parser.add_argument("--sample-rate", type=int, default=24_000)
    args = parser.parse_args()

    from sonia.games.demo import EXAMPLE, load_demo, serve_demo

    try:
        steps = load_demo(args.juego)
    except LookupError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    game = args.como if args.juego == EXAMPLE else args.juego
    started = time.monotonic()

    def log(text: str) -> None:
        print(f"[{time.monotonic() - started:7.2f}] {text}", flush=True)

    try:
        return asyncio.run(
            serve_demo(
                steps,
                game=game,
                host=args.host,
                port=args.puerto,
                sample_rate=args.sample_rate,
                connect_timeout=args.espera,
                after_capture_s=args.tras_captura,
                stay=args.quedarse,
                log=log,
            )
        )
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
