#!/usr/bin/env bash
# Comprobación completa antes de abrir el stand: valida lo que ya cubre
# `sonia check` (micrófono, cámara, una sesión de GPT-Live que se abre y se
# cierra, modelo de visión y galería) y además cosas que están fuera del
# proceso del orquestador: que el endpoint del modelo de visión responde, que
# la galería tiene contenido y que el puerto del WebSocket está libre para que
# Sonia pueda arrancar.
#
# Uso: scripts/check_stand.sh
#
# Gasta: `sonia check` abre una sesión de GPT-Live de unos segundos y manda
# dos peticiones mínimas al modelo de visión (texto e imagen). No lo uses en
# bucle ni en tests.
#
# Importante: este script lee .env pero NUNCA imprime el valor de variables
# cuyo nombre contenga "KEY" o "TOKEN" (por ejemplo LLM_API_KEY). Solo se
# usan para construir peticiones, nunca se muestran por pantalla ni se
# guardan en logs.
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

echo "== 1/4: sonia check (micrófono, cámara, GPT-Live, modelo de visión, galería) =="
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

echo "== 3/4: modelo de visión (\$LLM_BASE_URL/models) =="
# LLM_* solo describe la cámara (GPT-Live no acepta imágenes): si falla, Sonia
# conversa igual pero sin ojos, así que es un aviso y no un fallo.
llm_fail() { warn "$1 (Sonia conversa igual, pero sin ver la cámara)"; }
LLM_BASE_URL="${LLM_BASE_URL:-https://api.openai.com/v1}"  # el mismo valor por defecto que el orquestador
if [[ "${LLM_SUPPORTS_VISION:-true}" == "false" || "${VISION_SOURCE:-opencv}" == "none" ]]; then
  ok "Visión desactivada (LLM_SUPPORTS_VISION=false o VISION_SOURCE=none): no se comprueba"
else
  # Se usa LLM_API_KEY (o, si falta, OPENAI_API_KEY, igual que el
  # orquestador) para la petición, pero su valor nunca se imprime.
  # curl ya escribe "000" con -w si no logra conectar, así que no hace falta
  # (ni conviene) un "|| echo" que lo duplicaría.
  HTTP_CODE="$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 \
    -H "Authorization: Bearer ${LLM_API_KEY:-${OPENAI_API_KEY:-}}" \
    "${LLM_BASE_URL%/}/models" 2>/dev/null)"
  HTTP_CODE="${HTTP_CODE:-000}"
  if [[ "$HTTP_CODE" == "200" ]]; then
    ok "El endpoint respondió en ${LLM_BASE_URL%/}/models (200)"
  else
    llm_fail "El endpoint en ${LLM_BASE_URL%/}/models no respondió 200 (código: $HTTP_CODE). Revisa LLM_BASE_URL, la clave (LLM_API_KEY u OPENAI_API_KEY) y la conexión a internet"
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
