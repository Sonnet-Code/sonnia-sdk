#!/usr/bin/env bash
# Instala Sonnia Video en este Mac para usarlo desde la terminal (docs/video.md):
#   - copia unity/Build/macOS-video/Sonnia Video.app a /Applications (la de antes se sustituye);
#   - deja el comando `sonnia-video` en ~/.local/bin, que llama al que va dentro de la app.
#
# Antes: scripts/build_sonnia_video.sh y Sonia > Build macOS (vídeo para redes)
# (SoniaBuild.BuildMacVideo). La app no tiene ventana: se usa solo con `sonnia-video`.
#
# Uso: scripts/instala_sonnia_video.sh [carpeta de destino de la app, por defecto /Applications]
set -euo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
SOURCE="$REPO/unity/Build/macOS-video/Sonnia Video.app"
DEST_DIR="${1:-/Applications}"
DEST="$DEST_DIR/Sonnia Video.app"
BIN="$HOME/.local/bin"

if [ ! -x "$SOURCE/Contents/Resources/sonnia-video/sonnia-video" ]; then
  echo "error: falta $SOURCE con sonnia-video dentro (compila la app de vídeo primero)" >&2
  exit 1
fi

# Que no quede abierta la versión vieja: sigue sirviendo trabajos con el código de antes.
if curl -s -m 2 -X POST -H "Content-Length: 0" "http://127.0.0.1:${SONNIA_VIDEO_PORT:-8795}/quit" >/dev/null 2>&1; then
  echo "cerrada la app de vídeo que estaba abierta"
  sleep 2
fi

rm -rf "$DEST"
ditto "$SOURCE" "$DEST"
# Sin la cuarentena (copiada en el propio equipo) ni la traslocación de macOS.
xattr -dr com.apple.quarantine "$DEST" 2>/dev/null || true
/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister -f "$DEST" || true

mkdir -p "$BIN"
cat > "$BIN/sonnia-video" <<EOF
#!/usr/bin/env bash
# Sonnia Video (instalado por scripts/instala_sonnia_video.sh del repo sonia).
exec "$DEST/Contents/Resources/sonnia-video/sonnia-video" "\$@"
EOF
chmod +x "$BIN/sonnia-video"

version="$(/usr/libexec/PlistBuddy -c 'Print :CFBundleShortVersionString' "$DEST/Contents/Info.plist" 2>/dev/null || echo '?')"
echo "listo: $DEST ($version) y $BIN/sonnia-video"
case ":$PATH:" in
  *":$BIN:"*) ;;
  *) echo "aviso: $BIN no está en el PATH; añádelo a ~/.zshrc" >&2 ;;
esac
