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
# Uso: scripts/build_orquestador.sh
set -euo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
case "$(uname -s)" in
  Darwin) PLATFORM=macOS; SEP=":" ;;
  MINGW*|MSYS*|CYGWIN*) PLATFORM=Windows; SEP=";" ;;
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

cd "$REPO/server"
uv sync --group dev --extra audio --extra camera --extra panel >/dev/null
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
  --add-data "$REPO/server/sonia/panel/static${SEP}sonia/panel/static" \
  ${EXTRA[@]+"${EXTRA[@]}"} \
  "$REPO/server/sonia/__main__.py"
du -sh "$OUT/sonia-orquestador"
echo "listo: $OUT/sonia-orquestador"
