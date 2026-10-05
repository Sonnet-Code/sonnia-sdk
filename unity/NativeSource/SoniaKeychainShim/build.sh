#!/usr/bin/env bash
# Compila el puente del llavero (libSoniaKeychainShim.dylib) que usa la build de
# macOS para que las librerías de Genies no toquen el llavero (ver
# SoniaKeychainShim.c). Hace falta Xcode (clang). Solo se recompila si cambia
# SoniaKeychainShim.c; el resultado se sube al repo y lo copia
# SoniaPlayerBuildFixes en cada build.
#
# Uso: unity/NativeSource/SoniaKeychainShim/build.sh
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"

# Universal, para cualquier Mac. El resto de Security se reexporta: las
# librerías de Genies siguen encontrando sus constantes kSec... aquí. Versión de
# compatibilidad 1.0.0, la que esas librerías exigen a Security.
clang -std=c11 -O2 -Wall -dynamiclib -arch arm64 -arch x86_64 -mmacosx-version-min=12.0 \
  -framework CoreFoundation \
  -Wl,-reexport_framework,Security \
  -install_name @loader_path/libSoniaKeychainShim.dylib \
  -compatibility_version 1.0.0 -current_version 1.0.0 \
  -o "$HERE/libSoniaKeychainShim.dylib" "$HERE/SoniaKeychainShim.c"
codesign -f -s - "$HERE/libSoniaKeychainShim.dylib" >/dev/null 2>&1
echo "listo: $HERE/libSoniaKeychainShim.dylib"
nm -gU "$HERE/libSoniaKeychainShim.dylib" | grep SecItem
