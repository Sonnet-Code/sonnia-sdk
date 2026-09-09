#!/usr/bin/env bash
# Descarga a la caché local los modelos que usa Sonia para correr sin conexión
# el día del evento. Ejecutar una vez (o cuando cambie STT_MODEL) con conexión
# a internet disponible; después el stand funciona sin red.
#
# Uso:
#   scripts/download_models.sh
#
# Variables opcionales:
#   HF_HOME     Ruta de la caché de Hugging Face (por defecto ~/.cache/huggingface).
#               Útil si el disco del sistema tiene poco espacio y quieres los
#               pesos en otra unidad.
#   STT_MODEL   Tamaño del modelo de faster-whisper a descargar (por defecto
#               "small", igual que en .env.example).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
SERVER_DIR="$REPO_ROOT/server"

if [[ -n "${HF_HOME:-}" ]]; then
  export HF_HOME
  echo "Usando HF_HOME=$HF_HOME como caché de Hugging Face."
fi

# STT_MODEL puede venir del entorno o del .env de la raíz del proyecto.
if [[ -z "${STT_MODEL:-}" && -f "$REPO_ROOT/.env" ]]; then
  STT_MODEL="$(grep -E '^STT_MODEL=' "$REPO_ROOT/.env" | tail -n1 | cut -d= -f2-)"
fi
STT_MODEL="${STT_MODEL:-small}"

cd "$SERVER_DIR"

echo "=== [1/3] faster-whisper (STT), modelo '${STT_MODEL}' ==="
if ! uv run --no-sync python -c "import faster_whisper" >/dev/null 2>&1; then
  echo "ERROR: falta la dependencia 'faster-whisper'." >&2
  echo "Instálala desde server/ con: uv sync --extra stt (o --extra all)" >&2
  exit 1
fi
uv run --no-sync python -c "
from faster_whisper import WhisperModel
WhisperModel('${STT_MODEL}', device='cpu', compute_type='int8')
"
echo "OK: modelo de faster-whisper '${STT_MODEL}' descargado en la caché de Hugging Face."
echo

echo "=== [2/3] Silero VAD ==="
if ! uv run --no-sync python -c "import silero_vad" >/dev/null 2>&1; then
  echo "ERROR: falta la dependencia 'silero-vad'." >&2
  echo "Instálala desde server/ con: uv sync --extra audio (o --extra all)" >&2
  exit 1
fi
# El paquete silero-vad trae los pesos empaquetados, no hace falta descargar
# nada de red: esta llamada solo confirma que el modelo carga correctamente.
uv run --no-sync python -c "
from silero_vad import load_silero_vad
load_silero_vad()
"
echo "OK: Silero VAD carga correctamente (el paquete ya incluye los pesos)."
echo

echo "=== [3/3] OmniVoice (TTS) ==="
if uv run --no-sync python -c "import omnivoice" >/dev/null 2>&1; then
  uv run --no-sync python -c "
from huggingface_hub import snapshot_download
snapshot_download('k2-fsa/OmniVoice')
"
  echo "OK: pesos de OmniVoice descargados en la caché de Hugging Face."
else
  echo "AVISO: el extra 'omnivoice' no está instalado, se omite la descarga de sus pesos."
  echo "Instálalo desde server/ con: uv sync --extra omnivoice (o --extra all)"
  echo "y vuelve a ejecutar este script para descargar los pesos del modelo."
fi
echo

echo "Descarga de modelos completada."
