#!/usr/bin/env bash
# Levanta un servidor HTTP de OmniVoice, compatible con POST /v1/audio/speech,
# para usarlo con TTS_BACKEND=http en .env.
#
# Por defecto Sonia usa TTS_BACKEND=omnivoice: el modelo se carga en el mismo
# proceso del orquestador (server/sonia/tts/omnivoice.py) y este script NO
# hace falta. Usa este servidor aparte solo si prefieres el TTS en un proceso
# independiente, por ejemplo para reiniciarlo sin tocar el orquestador o para
# liberar memoria de vídeo del proceso principal.
#
# El paquete `omnivoice-server` es independiente del entorno de `server/`
# (arrastra su propio torch/transformers), así que se instala aparte:
#   - con uvx (no necesita entorno propio): uvx omnivoice-server
#   - o en un virtualenv dedicado:
#       python3 -m venv .venv-tts
#       source .venv-tts/bin/activate
#       pip install omnivoice-server
#       omnivoice-server --port 8880
#
# Variables:
#   PORT   Puerto donde escucha el servidor (por defecto 8880, igual que
#          TTS_BASE_URL=http://127.0.0.1:8880/v1 en .env.example).
set -euo pipefail

PORT="${PORT:-8880}"

echo "Arrancando el servidor HTTP de OmniVoice en el puerto $PORT..."
echo "Con TTS_BACKEND=http, apunta TTS_BASE_URL a http://127.0.0.1:$PORT/v1 en .env."

if command -v uvx >/dev/null 2>&1; then
  exec uvx omnivoice-server --port "$PORT"
fi

if command -v omnivoice-server >/dev/null 2>&1; then
  exec omnivoice-server --port "$PORT"
fi

echo "ERROR: no se encontró 'uvx' ni 'omnivoice-server' en el PATH." >&2
echo "Instala uno de los dos:" >&2
echo "  - uvx (viene con uv): uvx omnivoice-server --port $PORT" >&2
echo "  - o en un entorno virtual propio:" >&2
echo "      python3 -m venv .venv-tts && source .venv-tts/bin/activate" >&2
echo "      pip install omnivoice-server && omnivoice-server --port $PORT" >&2
exit 1
