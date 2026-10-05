#!/usr/bin/env bash
# Compila el puente de NAF (libSoniaNafShim.dylib) que usa la build de macOS.
# Hace falta Xcode (clang) y el editor de Unity instalado (cabeceras PluginAPI).
# Solo se recompila si cambia SoniaNafShim.mm o el SDK de Genies; el resultado
# se sube al repo y lo copia SoniaMacBuildFixes en cada build.
#
# Uso: unity/NativeSource/SoniaNafShim/build.sh [ruta del editor de Unity]
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
UNITY_APP="${1:-/Applications/Unity/Hub/Editor/6000.6.0f1/Unity.app}"
API="$UNITY_APP/Contents/Resources/PluginAPI"
REAL_SRC="$HERE/../../Packages/com.genies.avatar-sdk.client/Internal/NAF Plugin/Runtime/Plugins/macOS/libgnUnityPlugin.dylib"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

# El puente se enlaza contra el plugin real con el nombre que tendrá en la app,
# para reexportar todos sus símbolos.
cp "$REAL_SRC" "$TMP/libgnUnityPluginReal.dylib"
install_name_tool -id @rpath/libgnUnityPluginReal.dylib "$TMP/libgnUnityPluginReal.dylib" 2>/dev/null

clang++ -std=c++17 -fobjc-arc -O2 -dynamiclib -arch arm64 -mmacosx-version-min=15.0 \
  -I "$API" -framework Metal -framework Foundation \
  -install_name @rpath/libgnUnityPlugin.dylib \
  -Wl,-rpath,@loader_path \
  -Wl,-reexport_library,"$TMP/libgnUnityPluginReal.dylib" \
  -o "$HERE/libSoniaNafShim.dylib" "$HERE/SoniaNafShim.mm"
codesign -f -s - "$HERE/libSoniaNafShim.dylib" >/dev/null 2>&1
echo "listo: $HERE/libSoniaNafShim.dylib"
otool -L "$HERE/libSoniaNafShim.dylib" | grep -i gnUnity
