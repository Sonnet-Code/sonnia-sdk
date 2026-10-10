#!/usr/bin/env bash
# Congela el orquestador (Python) en una carpeta autocontenida con PyInstaller,
# para meterlo dentro de la app de Unity (lo copia el post-proceso de la build).
#
# Resultado: unity/Build/orquestador/<plataforma>/sonia-orquestador/
#   sonia-orquestador(.exe)   ejecutable (`sonia-orquestador run`)
#   _internal/                Python, dependencias, assets/ y estáticos del panel
#
# No lleva claves ni el estado de cada equipo: el .env lo pone la build de Unity
# junto al ejecutable y cache/ va en SONIA_HOME, fuera de la app (ver
# sonia/paths.py y docs/stand.md). Sí lleva las frases ya grabadas de este equipo
# (cache/voice), que la app copia a SONIA_HOME si faltan: así «Solo saludos»
# funciona sin red desde la primera vez. Hay que congelarlo en cada sistema: en
# macOS sale para macOS y en Windows para Windows.
#
# En Windows se ejecuta desde Git Bash (viene con Git para Windows) con uv
# instalado, o en el runner de GitHub (.github/workflows/orquestador-windows.yml).
#
# Uso: scripts/build_orquestador.sh
set -euo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
case "$(uname -s)" in
  Darwin) PLATFORM=macOS; SEP=":" ;;
  MINGW*|MSYS*|CYGWIN*)
    PLATFORM=Windows; SEP=";"
    # PyInstaller es un programa de Windows: rutas C:/... y sin que Git Bash
    # las reescriba (las de --add-data llevan «;» y las estropeaba).
    REPO="$(cd "$REPO" && pwd -W)"
    export MSYS_NO_PATHCONV=1 ;;
  *) PLATFORM=Linux; SEP=":" ;;
esac
OUT="$REPO/unity/Build/orquestador/$PLATFORM"
WORK="$REPO/unity/Build/orquestador/.pyinstaller-$PLATFORM"

# Frases ya grabadas (no están en git): van si este equipo las tiene.
EXTRA=()
if [ -d "$REPO/cache/voice" ]; then
  EXTRA+=(--add-data "$REPO/cache/voice${SEP}cache/voice")
else
  echo "aviso: sin cache/voice; la app grabará las frases al conectar" >&2
fi
# Caras conocidas (docs/caras.md): modelos y huellas, nunca las fotos de cache/faces/fotos.
for faces in modelos huellas; do
  if [ -d "$REPO/cache/faces/$faces" ]; then
    EXTRA+=(--add-data "$REPO/cache/faces/$faces${SEP}cache/faces/$faces")
  fi
done
if [ ! -d "$REPO/cache/faces/huellas" ]; then
  echo "aviso: sin cache/faces; la app preparará las caras al arrancar (sonia caras para hacerlo antes)" >&2
fi

cd "$REPO/server"
uv sync --group dev --extra audio --extra camera --extra panel >/dev/null
# Modelos de poses y manos de los juegos (docs/plan-juegos.md, sección 6): se bajan si
# faltan (revisión fijada y SHA-256) y van dentro, como los de caras.
uv run --no-sync python -m sonia.vision.models "$REPO/cache/games/modelos" \
  || echo "aviso: sin los modelos de los juegos; la app los bajará al arrancar" >&2
if [ -d "$REPO/cache/games/modelos" ]; then
  EXTRA+=(--add-data "$REPO/cache/games/modelos${SEP}cache/games/modelos")
fi
# Bancos de los juegos (assets/games/<juego>/*.md, docs/juegos.md): cada partida lee el suyo.
# Sin ellos, en la app congelada ningún juego arranca («banco vacío»).
if [ -d "$REPO/assets/games" ]; then
  EXTRA+=(--add-data "$REPO/assets/games${SEP}assets/games")
fi
rm -rf "$OUT"
uv run --no-sync pyinstaller --noconfirm --clean --log-level WARN \
  --name sonia-orquestador --onedir --console \
  --distpath "$OUT" --workpath "$WORK" --specpath "$WORK" \
  --paths "$REPO/server" \
  --collect-submodules sonia \
  --add-data "$REPO/assets/knowledge${SEP}assets/knowledge" \
  --add-data "$REPO/assets/gallery${SEP}assets/gallery" \
  --add-data "$REPO/assets/showcase${SEP}assets/showcase" \
  --add-data "$REPO/assets/trivia${SEP}assets/trivia" \
  --add-data "$REPO/assets/agenda${SEP}assets/agenda" \
  --add-data "$REPO/assets/faces${SEP}assets/faces" \
  --add-data "$REPO/assets/fonts${SEP}assets/fonts" \
  --add-data "$REPO/server/sonia/panel/static${SEP}sonia/panel/static" \
  ${EXTRA[@]+"${EXTRA[@]}"} \
  "$REPO/server/sonia/__main__.py"
# Runtime de Visual C++ para la app de Windows: lo necesitan las DLL nativas de Genies
# y Windows no lo trae de serie (7 de octubre de 2026: sin él no se montaba el avatar).
# Van las de este Windows (en el runner de GitHub, las del Visual Studio instalado) y
# la build de Unity las pone junto a Sonnia.exe y a los plugins (SoniaPlayerBuildFixes).
if [ "$PLATFORM" = Windows ]; then
  SYS="$(printf '%s' "${SYSTEMROOT:-C:/Windows}" | tr '\\' '/')/System32"
  VCREDIST="$OUT/sonia-orquestador/vcredist"
  mkdir -p "$VCREDIST"
  for dll in msvcp140 msvcp140_1 msvcp140_2 msvcp140_atomic_wait msvcp140_codecvt_ids \
             vcruntime140 vcruntime140_1 concrt140; do
    if [ -f "$SYS/$dll.dll" ]; then
      cp "$SYS/$dll.dll" "$VCREDIST/"
    else
      echo "aviso: no está $SYS/$dll.dll" >&2
    fi
  done
  for dll in msvcp140 vcruntime140 vcruntime140_1 concrt140; do
    if [ ! -f "$VCREDIST/$dll.dll" ]; then
      echo "error: falta $dll.dll del runtime de Visual C++ para la app de Windows" >&2
      exit 1
    fi
  done
fi
du -sh "$OUT/sonia-orquestador"
echo "listo: $OUT/sonia-orquestador"
