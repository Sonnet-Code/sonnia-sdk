#!/usr/bin/env bash
# Levanta un servidor local con API compatible con OpenAI (/v1/chat/completions)
# para que el orquestador de Sonia hable con él vía LLM_BASE_URL, LLM_MODEL y
# LLM_API_KEY (ver .env.example). Ninguno de estos backends lo instala `uv`:
# cada uno se instala aparte, según sus propias instrucciones.
#
# Selecciona el backend con la variable BACKEND=llamacpp|vllm|ollama
# (por defecto llamacpp). Ejemplo:
#
#   BACKEND=llamacpp MODEL_PATH=/ruta/al/modelo.gguf scripts/run_llm_server.sh
#
# Este script no inventa rutas de modelo: si falta la variable que le
# corresponde al backend elegido, falla con un mensaje explicando qué definir.
set -euo pipefail

BACKEND="${BACKEND:-llamacpp}"
PORT="${PORT:-8000}"

case "$BACKEND" in
  llamacpp)
    # --- llama.cpp ---
    # Necesita el binario `llama-server` compilado o instalado en el PATH
    # (https://github.com/ggml-org/llama.cpp). MODEL_PATH apunta a un .gguf.
    #
    #   MODEL_PATH=/ruta/kimi-k3.Q4_K_M.gguf scripts/run_llm_server.sh
    : "${MODEL_PATH:?Define MODEL_PATH con la ruta al archivo .gguf del modelo. Ejemplo: MODEL_PATH=/ruta/al/modelo.gguf scripts/run_llm_server.sh}"
    if [[ ! -f "$MODEL_PATH" ]]; then
      echo "ERROR: no existe el archivo MODEL_PATH='$MODEL_PATH'" >&2
      exit 1
    fi
    if ! command -v llama-server >/dev/null 2>&1; then
      echo "ERROR: no se encontró el binario 'llama-server' en el PATH." >&2
      echo "Instala llama.cpp: https://github.com/ggml-org/llama.cpp" >&2
      exit 1
    fi
    echo "Arrancando llama.cpp (llama-server) con '$MODEL_PATH' en el puerto $PORT..."
    # --jinja aplica la plantilla de chat propia del modelo, que es lo que
    # habilita el tool calling nativo (formato OpenAI) en llama.cpp.
    # Si el modelo es multimodal (visión), añade también --mmproj con la ruta
    # al proyector de visión del mismo modelo, por ejemplo:
    #   MMPROJ_PATH=/ruta/al/mmproj.gguf scripts/run_llm_server.sh
    CMD=(llama-server -m "$MODEL_PATH" --port "$PORT" --host 127.0.0.1 -c 8192 --jinja)
    if [[ -n "${MMPROJ_PATH:-}" ]]; then
      CMD+=(--mmproj "$MMPROJ_PATH")
    fi
    exec "${CMD[@]}"
    ;;

  vllm)
    # --- vLLM ---
    # Se instala normalmente en un entorno propio (no en server/.venv, porque
    # arrastra dependencias pesadas y a veces incompatibles con las de Sonia):
    #   pip install vllm
    # MODEL_NAME es un id de Hugging Face o una ruta local al modelo.
    # TOOL_CALL_PARSER depende del modelo (por ejemplo: hermes, mistral,
    # llama3_json...); revisa la documentación de vLLM para el que corresponda
    # al modelo elegido.
    #
    #   MODEL_NAME=modelo/en-hf TOOL_CALL_PARSER=hermes scripts/run_llm_server.sh
    : "${MODEL_NAME:?Define MODEL_NAME con el id de Hugging Face o la ruta local del modelo}"
    : "${TOOL_CALL_PARSER:?Define TOOL_CALL_PARSER según el modelo (ver documentación de vLLM: --tool-call-parser)}"
    if ! command -v vllm >/dev/null 2>&1; then
      echo "ERROR: no se encontró el comando 'vllm' en el PATH." >&2
      echo "Instálalo (normalmente en un entorno propio): pip install vllm" >&2
      exit 1
    fi
    echo "Arrancando vLLM con '$MODEL_NAME' en el puerto $PORT..."
    exec vllm serve "$MODEL_NAME" \
      --port "$PORT" \
      --enable-auto-tool-choice \
      --tool-call-parser "$TOOL_CALL_PARSER"
    ;;

  ollama)
    # --- Ollama ---
    # Necesita Ollama instalado (https://ollama.com) y el modelo ya descargado
    # con `ollama pull <MODEL_NAME>`. Ollama sirve su API compatible con
    # OpenAI en un puerto fijo, no en PORT/8000:
    #
    #   LLM_BASE_URL=http://localhost:11434/v1
    #
    # Ajusta esa variable en .env si usas este backend.
    : "${MODEL_NAME:?Define MODEL_NAME con el nombre del modelo ya descargado con 'ollama pull'}"
    if ! command -v ollama >/dev/null 2>&1; then
      echo "ERROR: no se encontró el comando 'ollama' en el PATH." >&2
      echo "Instálalo desde https://ollama.com" >&2
      exit 1
    fi
    echo "Arrancando Ollama. Modelo esperado: '$MODEL_NAME' (descárgalo antes con 'ollama pull $MODEL_NAME' si no lo has hecho)."
    echo "El endpoint compatible con OpenAI queda en http://localhost:11434/v1 (ajusta LLM_BASE_URL en .env)."
    exec ollama serve
    ;;

  *)
    echo "ERROR: BACKEND='$BACKEND' no reconocido. Usa llamacpp, vllm u ollama." >&2
    exit 1
    ;;
esac
