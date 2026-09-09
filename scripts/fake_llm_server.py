#!/usr/bin/env python3
"""Servidor falso compatible con OpenAI para probar Sonia sin nube ni GPU.

Responde a ``POST /v1/chat/completions`` con un stream SSE de frases fijas
(o de un guion pasado por ``--script``), respetando el formato que espera
``sonia.llm.client``. Sirve para ensayar el avatar, el lip-sync y los estados
en Unity sin gastar tokens.

Uso:
    uv run --no-sync python ../scripts/fake_llm_server.py --port 8000   # desde server/
    LLM_BASE_URL=http://127.0.0.1:8000/v1 uv run --no-sync sonia run --no-mic
"""

from __future__ import annotations

import argparse
import contextlib
import json
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

DEFAULT_REPLY = (
    "¡Hola! Qué bonita esa camisa azul que llevas hoy. "
    "Soy Sonia, del staff del DevFest Santo Domingo dos mil veintiséis. "
    "Estamos en la Biblioteca Nacional Pedro Henríquez Ureña, la casa de los libros del país. "
    "¿Quieres que te cuente qué hay hoy en la agenda, o prefieres saber cómo funciono por dentro?"
)


class Handler(BaseHTTPRequestHandler):
    reply: str = DEFAULT_REPLY
    model: str = "fake-model"
    delay: float = 0.03

    def log_message(self, fmt: str, *args: object) -> None:  # menos ruido
        print("[fake-llm]", fmt % args)

    def do_GET(self) -> None:  # noqa: N802
        if self.path.rstrip("/").endswith("/models"):
            body = json.dumps({"object": "list", "data": [{"id": self.model, "object": "model"}]})
            self._send_json(body)
        else:
            self.send_error(404)

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            request = json.loads(raw)
        except json.JSONDecodeError:
            self.send_error(400, "JSON inválido")
            return
        if not self.path.rstrip("/").endswith("/chat/completions"):
            self.send_error(404)
            return
        if request.get("stream"):
            self._stream(request)
        else:
            body = json.dumps(
                {
                    "id": "chatcmpl-fake",
                    "object": "chat.completion",
                    "model": self.model,
                    "choices": [
                        {
                            "index": 0,
                            "message": {"role": "assistant", "content": "ok"},
                            "finish_reason": "stop",
                        }
                    ],
                }
            )
            self._send_json(body)

    def _send_json(self, body: str) -> None:
        data = body.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    @staticmethod
    def _last_user_text(request: dict) -> str:
        for msg in reversed(request.get("messages", [])):
            if msg.get("role") == "user":
                content = msg.get("content")
                if isinstance(content, list):
                    return " ".join(p.get("text", "") for p in content if p.get("type") == "text")
                return str(content or "")
        return ""

    @staticmethod
    def _last_role(request: dict) -> str:
        messages = request.get("messages", [])
        return str(messages[-1].get("role")) if messages else ""

    def _stream(self, request: dict) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Transfer-Encoding", "chunked")
        self.end_headers()

        # Acciones simuladas: "logo"/"imagen" pide show_image; "quita" pide hide_image.
        # Tras recibir el resultado de la herramienta (último mensaje role=tool),
        # se responde con texto normal.
        text = self._last_user_text(request).lower()
        tools = {
            t["function"]["name"] for t in request.get("tools", []) if t.get("type") == "function"
        }
        if self._last_role(request) != "tool":
            call = None
            if "quita" in text and "hide_image" in tools:
                call = ("hide_image", "{}")
            elif ("logo" in text or "imagen" in text) and "show_image" in tools:
                call = (
                    "show_image",
                    json.dumps({"image_id": "logo-sonnet", "caption": "Sonnet Code"}),
                )
            if call is not None:
                self._stream_tool_call(call[0], call[1])
                return

        def chunk(delta: dict, finish: str | None = None) -> None:
            payload = {
                "id": "chatcmpl-fake",
                "object": "chat.completion.chunk",
                "model": self.model,
                "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
            }
            line = f"data: {json.dumps(payload, ensure_ascii=False)}\n\n".encode()
            self.wfile.write(f"{len(line):x}\r\n".encode("ascii") + line + b"\r\n")
            self.wfile.flush()

        chunk({"role": "assistant", "content": ""})
        reply = self.reply
        if self._last_role(request) == "tool":
            reply = "Listo, ahí la tienes en mi pantalla. Es el logo de Sonnet Code, la empresa que me creó."
        # Se emite palabra a palabra para que el splitter y el TTS trabajen en streaming.
        for word in reply.split(" "):
            chunk({"content": word + " "})
            time.sleep(self.delay)
        chunk({}, finish="stop")
        done = b"data: [DONE]\n\n"
        self.wfile.write(f"{len(done):x}\r\n".encode("ascii") + done + b"\r\n0\r\n\r\n")
        self.wfile.flush()

    def _stream_tool_call(self, name: str, arguments: str) -> None:
        """Emite una tool call fragmentada como hacen los servidores reales."""

        def chunk(delta: dict, finish: str | None = None) -> None:
            payload = {
                "id": "chatcmpl-fake",
                "object": "chat.completion.chunk",
                "model": self.model,
                "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
            }
            line = f"data: {json.dumps(payload, ensure_ascii=False)}\n\n".encode()
            self.wfile.write(f"{len(line):x}\r\n".encode("ascii") + line + b"\r\n")
            self.wfile.flush()

        chunk({"role": "assistant", "content": ""})
        chunk(
            {
                "tool_calls": [
                    {
                        "index": 0,
                        "id": "call_fake_1",
                        "type": "function",
                        "function": {"name": name, "arguments": ""},
                    }
                ]
            }
        )
        half = max(1, len(arguments) // 2)
        chunk({"tool_calls": [{"index": 0, "function": {"arguments": arguments[:half]}}]})
        chunk({"tool_calls": [{"index": 0, "function": {"arguments": arguments[half:]}}]})
        chunk({}, finish="tool_calls")
        done = b"data: [DONE]\n\n"
        self.wfile.write(f"{len(done):x}\r\n".encode("ascii") + done + b"\r\n0\r\n\r\n")
        self.wfile.flush()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--reply", default=DEFAULT_REPLY, help="texto que responde siempre")
    parser.add_argument("--delay", type=float, default=0.03, help="segundos entre palabras")
    args = parser.parse_args()
    Handler.reply = args.reply
    Handler.delay = args.delay
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"[fake-llm] escuchando en http://{args.host}:{args.port}/v1  (Ctrl+C para salir)")
    with contextlib.suppress(KeyboardInterrupt):
        server.serve_forever()


if __name__ == "__main__":
    main()
