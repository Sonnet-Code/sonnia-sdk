#!/usr/bin/env bash
# Comprobación completa antes de abrir el stand: valida lo que ya cubre
# `sonia check` (con GPT-Live: audio, cámara, una sesión de GPT-Live, modelo
# de visión y galería; con el motor pipeline: además VAD, STT, LLM y TTS) y
# además cosas que están fuera del proceso del orquestador: que el endpoint
# del LLM responde de verdad, que la galería tiene contenido y que el puerto
# del WebSocket está libre para que Sonia pueda arrancar.
#
# Uso: scripts/check_stand.sh
#
# Importante: este script lee .env pero NUNCA imprime el valor de variables
# cuyo nombre contenga "KEY" (por ejemplo LLM_API_KEY). Solo se usan para
# construir peticiones, nunca se muestran por pantalla ni se guardan en logs.
set -uo pipefail
# Sin `-e`: queremos que se ejecuten todas las comprobaciones aunque una
# falle, y dar un resumen al final en vez de cortar en la primera.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
SERVER_DIR="$REPO_ROOT/server"
ENV_FILE="$REPO_ROOT/.env"
GALLERY_DIR="$REPO_ROOT/assets/gallery"

FAILURES=0
ok()   { echo "  OK    - $1"; }
fail() { echo "  FALLO - $1"; FAILURES=$((FAILURES + 1)); }
warn() { echo "  AVISO - $1"; }

echo "== 1/4: sonia check (audio, cámara, voz, modelo, galería) =="
if ( cd "$SERVER_DIR" && uv run --no-sync sonia check ); then
  ok "uv run sonia check terminó sin errores"
else
  fail "uv run sonia check reportó fallos (ver arriba)"
fi
echo

echo "== 2/4: variables de entorno =="
if [[ -f "$ENV_FILE" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "$ENV_FILE"
  set +a
  ok "Variables cargadas desde $ENV_FILE"
else
  fail "No existe $ENV_FILE (copia .env.example a .env y ajústalo)"
fi
echo

echo "== 3/4: endpoint del LLM (\$LLM_BASE_URL/models) =="
# Con GPT-Live (VOICE_ENGINE=live, el valor por defecto) LLM_* solo describe
# la cámara: si falla, Sonia habla igual pero sin ojos, así que es un aviso.
if [[ "${VOICE_ENGINE:-live}" == "live" ]]; then
  llm_fail() { warn "$1 (con GPT-Live solo afecta a la cámara)"; }
else
  llm_fail() { fail "$1"; }
fi
if [[ -z "${LLM_BASE_URL:-}" ]]; then
  llm_fail "LLM_BASE_URL no está definida"
else
  # Se usa LLM_API_KEY para la petición pero su valor nunca se imprime.
  # curl ya escribe "000" con -w si no logra conectar, así que no hace falta
  # (ni conviene) un "|| echo" que lo duplicaría.
  HTTP_CODE="$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 \
    -H "Authorization: Bearer ${LLM_API_KEY:-}" \
    "${LLM_BASE_URL%/}/models" 2>/dev/null)"
  HTTP_CODE="${HTTP_CODE:-000}"
  if [[ "$HTTP_CODE" == "200" ]]; then
    ok "El endpoint respondió en ${LLM_BASE_URL%/}/models (200)"
  else
    llm_fail "El endpoint en ${LLM_BASE_URL%/}/models no respondió 200 (código: $HTTP_CODE). ¿Está el servidor del LLM levantado (scripts/run_llm_server.sh)?"
  fi
fi
echo

echo "== 4/4: galería y puerto WS =="
if [[ -d "$GALLERY_DIR" ]] && find "$GALLERY_DIR" -maxdepth 1 -type f \( -iname '*.png' -o -iname '*.jpg' -o -iname '*.jpeg' \) 2>/dev/null | grep -q .; then
  ok "La galería tiene al menos una imagen ($GALLERY_DIR)"
else
  fail "La galería en $GALLERY_DIR no tiene ninguna imagen png/jpg/jpeg"
fi

WS_PORT="${WS_PORT:-8765}"
if command -v lsof >/dev/null 2>&1; then
  if lsof -iTCP:"$WS_PORT" -sTCP:LISTEN >/dev/null 2>&1; then
    fail "El puerto $WS_PORT ya está en uso (¿otra instancia de Sonia corriendo?)"
  else
    ok "El puerto $WS_PORT está libre"
  fi
else
  warn "No se encontró 'lsof': no se pudo comprobar si el puerto $WS_PORT está libre"
fi
echo

if [[ "$FAILURES" -eq 0 ]]; then
  echo "Todo listo: puedes arrancar Sonia."
  exit 0
else
  echo "$FAILURES comprobación(es) fallaron. Revisa los mensajes de FALLO arriba antes de abrir el stand."
  exit 1
fi
