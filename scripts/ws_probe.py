#!/usr/bin/env python3
"""Test client for the Sonnia WebSocket.

Connects to the orchestrator as if it were a second avatar client, sends a
``text_input`` and logs the incoming messages with timestamps (states, utterances,
transcripts, images) until Sonnia goes back to ``idle``. Useful to line up
screenshots with what is happening and to debug the protocol.

Usage (from server/):
    uv run --no-sync python ../scripts/ws_probe.py "Hi Sonnia" --url ws://127.0.0.1:8765
"""

from __future__ import annotations

import argparse
import asyncio
import json
import struct
import time


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("text", nargs="?", default="Hi Sonnia, what can you do?")
    parser.add_argument("--url", default="ws://127.0.0.1:8765")
    parser.add_argument("--timeout", type=float, default=90.0)
    parser.add_argument("--no-send", action="store_true", help="only listen, send no text")
    args = parser.parse_args()

    import websockets

    t0 = time.monotonic()

    def stamp() -> str:
        return f"{time.monotonic() - t0:6.2f}s"

    async with websockets.connect(args.url, max_size=32 * 1024 * 1024) as ws:
        print(stamp(), "connected to", args.url)
        if not args.no_send:
            await ws.send(json.dumps({"type": "text_input", "text": args.text}))
            print(stamp(), "sent text_input:", args.text)
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
                            f"audio utterance {uid}: last chunk ({audio_bytes} bytes so far)",
                        )
                continue
            data = json.loads(msg)
            kind = data.get("type")
            if kind == "state":
                last_state = data.get("state")
                print(stamp(), "state ->", last_state)
                if last_state == "idle" and audio_bytes > 0:
                    print(stamp(), "turn finished")
                    break
            elif kind == "speech_start":
                print(stamp(), f"speech_start {data.get('utterance_id')}: {data.get('text')}")
            elif kind == "speech_end":
                print(stamp(), f"speech_end {data.get('utterance_id')}")
            elif kind == "transcript":
                print(stamp(), f"transcript {data.get('role')}: {data.get('text')}")
            elif kind == "show_image":
                print(stamp(), f"show_image {data.get('image_id')} ({data.get('mime')})")
            elif kind in ("hello", "hide_image", "stop_speaking", "error", "request_frame"):
                print(stamp(), kind, {k: v for k, v in data.items() if k != "type"})
        print(stamp(), "done; last state:", last_state)


if __name__ == "__main__":
    asyncio.run(main())
