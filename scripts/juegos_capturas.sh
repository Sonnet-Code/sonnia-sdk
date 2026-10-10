#!/usr/bin/env bash
# Capturas 9:16 de las pantallas de los juegos con Unity en batch, sobre un clon
# del proyecto, conducidas por el orquestador falso (docs/juegos-unity.md).
#
# Uso (desde cualquier sitio de tu worktree):
#   scripts/juegos_capturas.sh --juego wordle --salida /ruta/capturas [--puerto 8791]
#   scripts/juegos_capturas.sh --hud-check --salida /ruta/capturas [--foto foto16x9.jpg]
#
# Pasos: coge turno de Unity (candado), clona el proyecto de la copia principal con
# APFS si no lo estaba, borra Library/ilpp.pid del clon, le copia los scripts de tu
# worktree, arranca el orquestador falso (scripts/juegos_demo.py), lanza Unity en
# batch con SoniaGameCapture y espera a dev_done. Al salir (también con error o
# Ctrl+C) cierra por PID el orquestador y Unity y suelta el candado.
#
# Variables:
#   SONIA_UNITY_LOCKS   carpeta de los candados (como mucho dos Unity en batch a la
#                       vez en la máquina). Sin ella no se coge turno (aviso).
#   SONIA_UNITY_SOURCE  proyecto Unity a clonar (por defecto, el de la copia
#                       principal del repo: tiene los assets de Genies que git ignora).
#   UNITY_EDITOR_PATH   ejecutable de Unity 6000.6.0f1.
set -uo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
UNITY="${UNITY_EDITOR_PATH:-/Applications/Unity/Hub/Editor/6000.6.0f1/Unity.app/Contents/MacOS/Unity}"
LOCKS="${SONIA_UNITY_LOCKS:-}"

JUEGO=""
PUERTO=8791
SALIDA=""
CLON=""
FOTO=""
HUD_CHECK=0
TIMEOUT=600
AVATAR_TIMEOUT=60
ORQ_CMD=""

usage() {
  sed -n '2,23p' "$0" | sed 's/^# \{0,1\}//'
  cat <<'EOF'
Opciones:
  --juego ID          juego de scripts/juegos_demo.py (ruleta, poses, akinator,
                      piedra_papel_tijera, wordle, busqueda)
  --salida DIR        carpeta de las capturas (obligatoria; fuera de unity/Temp)
  --puerto N          puerto del orquestador falso (8791; uno distinto por agente)
  --orquestador CMD   otra orden para el orquestador falso (se lanza desde server/)
  --hud-check         sin orquestador: comprobación de la pantalla común
  --foto RUTA         foto 16:9 (JPEG) para la vista en vivo de --hud-check
  --clon DIR          carpeta del clon (por defecto, una por worktree en $TMPDIR)
  --timeout S         segundos como mucho para Unity (600)
  --avatar-timeout S  segundos como mucho esperando al avatar de Genies (60)
EOF
}

while [ $# -gt 0 ]; do
  case "$1" in
    --juego) JUEGO="$2"; shift 2 ;;
    --puerto) PUERTO="$2"; shift 2 ;;
    --salida) SALIDA="$2"; shift 2 ;;
    --clon) CLON="$2"; shift 2 ;;
    --foto) FOTO="$2"; shift 2 ;;
    --orquestador) ORQ_CMD="$2"; shift 2 ;;
    --hud-check) HUD_CHECK=1; shift ;;
    --timeout) TIMEOUT="$2"; shift 2 ;;
    --avatar-timeout) AVATAR_TIMEOUT="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "opción desconocida: $1" >&2; usage >&2; exit 2 ;;
  esac
done

if [ -z "$SALIDA" ]; then
  echo "falta --salida" >&2
  exit 2
fi
if [ $HUD_CHECK -eq 0 ] && [ -z "$JUEGO" ] && [ -z "$ORQ_CMD" ]; then
  echo "falta --juego (o --hud-check, o --orquestador)" >&2
  exit 2
fi
if [ ! -x "$UNITY" ]; then
  echo "no encuentro Unity en $UNITY (UNITY_EDITOR_PATH)" >&2
  exit 2
fi

mkdir -p "$SALIDA"
SALIDA="$(cd "$SALIDA" && pwd)"
case "$SALIDA" in
  */unity/Temp*) echo "las capturas van fuera de unity/Temp" >&2; exit 2 ;;
esac

if [ -z "${SONIA_UNITY_SOURCE:-}" ]; then
  COMMON="$(git -C "$ROOT" rev-parse --path-format=absolute --git-common-dir 2>/dev/null || true)"
  if [ -n "$COMMON" ]; then
    SONIA_UNITY_SOURCE="$(dirname "$COMMON")/unity"
  fi
fi
SOURCE="${SONIA_UNITY_SOURCE:-}"
if [ -z "$SOURCE" ] || [ ! -d "$SOURCE/Library" ]; then
  echo "no encuentro el proyecto a clonar (SONIA_UNITY_SOURCE): $SOURCE" >&2
  exit 2
fi

if [ -z "$CLON" ]; then
  CLON="${TMPDIR:-/tmp}/sonia-clon-$(basename "$ROOT")"
fi
mkdir -p "$CLON"
CLON="$(cd "$CLON" && pwd)"
PROJECT="$CLON/unity"
if [ "$PROJECT" = "$SOURCE" ]; then
  echo "el clon no puede ser el proyecto de la copia principal" >&2
  exit 2
fi

LOCK=""
ORQ_PID=""
UNITY_PID=""
WATCHDOG_PID=""

cleanup() {
  local rc=$?
  for pid in $WATCHDOG_PID $ORQ_PID $UNITY_PID; do
    if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
      kill "$pid" 2>/dev/null
    fi
  done
  sleep 1
  for pid in $ORQ_PID $UNITY_PID; do
    if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
      kill -9 "$pid" 2>/dev/null
    fi
  done
  # Lo que Unity lanzó para este clon: importadores de assets y el relay del
  # asistente de IA (bun, con --log-dir en los Logs del clon; si no, sigue 180 s).
  pkill -f -- "-projectPath $PROJECT" 2>/dev/null
  pkill -f -- "$PROJECT/Logs" 2>/dev/null
  if [ -n "$LOCK" ]; then
    rmdir "$LOCK" 2>/dev/null
  fi
  exit $rc
}
trap cleanup EXIT
trap 'exit 130' INT TERM

# 1. Turno de Unity.
if [ -n "$LOCKS" ]; then
  mkdir -p "$LOCKS"
  echo "· esperando turno de Unity en $LOCKS"
  while [ -z "$LOCK" ]; do
    for n in 1 2; do
      if mkdir "$LOCKS/$n" 2>/dev/null; then
        LOCK="$LOCKS/$n"
        break
      fi
    done
    [ -z "$LOCK" ] && sleep 30
  done
  echo "· turno $LOCK"
else
  echo "· aviso: sin SONIA_UNITY_LOCKS no se coge turno (como mucho dos Unity en batch a la vez)"
fi

# 2. Clon APFS (instantáneo, sin Temp ni Logs) y tus scripts encima.
if [ ! -d "$PROJECT/Library" ]; then
  echo "· clonando $SOURCE en $PROJECT"
  rm -rf "$PROJECT"
  cp -cR "$SOURCE" "$PROJECT" || { echo "falló el clon" >&2; exit 1; }
  rm -rf "$PROJECT/Temp" "$PROJECT/Logs"
fi
# Sin esto, el Unity del clon mata el compilador del editor de verdad.
rm -f "$PROJECT/Library/ilpp.pid"
rsync -a --delete --exclude '*.meta' "$ROOT/unity/Assets/Scripts/" "$PROJECT/Assets/Scripts/" \
  || { echo "falló la copia de los scripts" >&2; exit 1; }
echo "· scripts de $ROOT copiados al clon"

# 3. Orquestador falso.
METHOD="Sonia.EditorTools.SoniaGameCapture.Run"
EXTRA=()
if [ $HUD_CHECK -eq 1 ]; then
  METHOD="Sonia.EditorTools.SoniaGameCapture.RunHudCheck"
  if [ -n "$FOTO" ]; then
    EXTRA+=(-sonia-preview-image "$(cd "$(dirname "$FOTO")" && pwd)/$(basename "$FOTO")")
  fi
else
  if [ -z "$ORQ_CMD" ]; then
    ORQ_CMD="uv run --no-sync python ../scripts/juegos_demo.py --juego $JUEGO --puerto $PUERTO"
  fi
  if nc -z 127.0.0.1 "$PUERTO" 2>/dev/null; then
    echo "el puerto $PUERTO ya está ocupado: elige otro con --puerto" >&2
    exit 1
  fi
  echo "· orquestador falso: $ORQ_CMD"
  (cd "$ROOT/server" && exec bash -c "$ORQ_CMD") > "$SALIDA/orquestador.log" 2>&1 &
  ORQ_PID=$!
  for _ in $(seq 1 60); do
    if nc -z 127.0.0.1 "$PUERTO" 2>/dev/null; then
      break
    fi
    if ! kill -0 "$ORQ_PID" 2>/dev/null; then
      echo "el orquestador falso se cerró al arrancar:" >&2
      tail -20 "$SALIDA/orquestador.log" >&2
      exit 1
    fi
    sleep 0.5
  done
  if ! nc -z 127.0.0.1 "$PUERTO" 2>/dev/null; then
    echo "el orquestador falso no escucha en el puerto $PUERTO" >&2
    exit 1
  fi
  EXTRA+=(-sonia-ws "ws://127.0.0.1:$PUERTO")
fi

# 4. Unity en batch (sin -nographics: hace falta GPU para renderizar).
echo "· Unity en batch ($METHOD), registro en $SALIDA/unity.log"
UNITY_MCP_DISABLE_BATCH=1 "$UNITY" -batchmode -projectPath "$PROJECT" \
  -executeMethod "$METHOD" \
  -sonia-captures "$SALIDA" \
  -sonia-capture-timeout "$TIMEOUT" \
  -sonia-avatar-timeout "$AVATAR_TIMEOUT" \
  ${EXTRA[@]+"${EXTRA[@]}"} \
  -logFile "$SALIDA/unity.log" &
UNITY_PID=$!
( sleep $((TIMEOUT + 180)); kill "$UNITY_PID" 2>/dev/null ) &
WATCHDOG_PID=$!

wait "$UNITY_PID"
RC=$?
UNITY_PID=""
echo "· Unity terminó con código $RC"
if [ -f "$SALIDA/capturas.txt" ]; then
  cat "$SALIDA/capturas.txt"
fi
grep -E 'error CS|Scripts have compiler errors|\[Capturas\]' "$SALIDA/unity.log" | grep -v '^\[Capturas\] \[' | tail -5
exit $RC
