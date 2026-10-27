#!/usr/bin/env bash
# Congela sonnia-video (docs/video.md) con PyInstaller en una carpeta autocontenida,
# para meterla dentro de «Sonnia Video.app» (Contents/Resources/sonnia-video/) o
# usarla suelta.
#
# Resultado: unity/Build/sonnia-video/<plataforma>/sonnia-video/
#   sonnia-video(.exe)   ejecutable (`sonnia-video render guion.toml`)
#   _internal/           Python, dependencias y el ffmpeg de imageio-ffmpeg
#
# A diferencia de scripts/build_orquestador.sh no lleva todo el paquete sonia
# (--collect-submodules): PyInstaller sigue los imports desde sonia/video/__main__.py
# y se quitan a mano lo que solo usa el stand (cámara, micrófono, GPT-Live...). No
# lleva claves: el .env va junto al ejecutable (lo pone quien empaqueta) o en la
# carpeta de datos (sonia/video/home.py). Hay que congelarlo en cada sistema.
#
# Uso: scripts/build_sonnia_video.sh
set -euo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
case "$(uname -s)" in
  Darwin) PLATFORM=macOS; SEP=":" ;;
  MINGW*|MSYS*|CYGWIN*)
    PLATFORM=Windows; SEP=";"
    REPO="$(cd "$REPO" && pwd -W)"
    export MSYS_NO_PATHCONV=1 ;;
  *) PLATFORM=Linux; SEP=":" ;;
esac
OUT="$REPO/unity/Build/sonnia-video/$PLATFORM"
WORK="$REPO/unity/Build/sonnia-video/.pyinstaller-$PLATFORM"

cd "$REPO/server"
# Los mismos extras que el resto del repo más «video» (uv sync quita lo que no se pide).
uv sync --group dev --extra audio --extra camera --extra panel --extra video >/dev/null
rm -rf "$OUT"
uv run --no-sync pyinstaller --noconfirm --clean --log-level WARN \
  --name sonnia-video --onedir --console \
  --distpath "$OUT" --workpath "$WORK" --specpath "$WORK" \
  --paths "$REPO/server" \
  --collect-data imageio_ffmpeg \
  --exclude-module cv2 \
  --exclude-module sounddevice \
  --exclude-module mss \
  --exclude-module jwt \
  --exclude-module sonia.live \
  --exclude-module sonia.vision \
  --exclude-module sonia.faces \
  --exclude-module sonia.games \
  --exclude-module sonia.panel \
  --exclude-module sonia.audio \
  --exclude-module tkinter \
  "$REPO/server/sonia/video/__main__.py"
du -sh "$OUT/sonnia-video"
echo "listo: $OUT/sonnia-video"
