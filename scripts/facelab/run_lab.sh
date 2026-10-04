#!/bin/zsh
# Laboratorio de cara: lanza Unity en batchmode con un guion y espera a que acabe.
#
#   scripts/facelab/run_lab.sh scripts/facelab/guion_ejemplo.json
#
# Unity no abre dos veces el mismo proyecto: con el editor abierto sobre unity/,
# lanzarlo sobre un worktree con su propia Library (docs/cara-y-lipsync.md).
# FACELAB_PROJECT elige el proyecto; por defecto, el unity/ de este checkout.
CONFIG=${1:?falta el guion JSON}
CONFIG=$(cd "$(dirname "$CONFIG")" && pwd)/$(basename "$CONFIG")
PROJECT=${FACELAB_PROJECT:-$(cd "$(dirname "$0")/../../unity" && pwd)}
UNITY=${UNITY:-/Applications/Unity/Hub/Editor/6000.6.0f1/Unity.app/Contents/MacOS/Unity}
OUT=$(python3 -c "import json,os,sys; o=json.load(open(sys.argv[1]))['outputDir']; print(o if os.path.isabs(o) else os.path.join(sys.argv[2], o))" "$CONFIG" "$PROJECT")
mkdir -p "$OUT"
rm -rf "$OUT/stand" "$OUT/closeup" "$OUT/done.txt"
start=$(date +%s)
# Sin el puente MCP: si arrancara, competiría con el del editor abierto.
UNITY_MCP_DISABLE_BATCH=1 "$UNITY" -batchmode -projectPath "$PROJECT" \
  -executeMethod Sonia.EditorTools.SoniaFaceLab.RunFromCommandLine \
  -facelab-config "$CONFIG" -logFile "$OUT/unity.log" &
PID=$!
for i in $(seq 1 900); do
  kill -0 $PID 2>/dev/null || break
  sleep 1
done
if kill -0 $PID 2>/dev/null; then
  echo "Más de 15 minutos: se corta."
  kill $PID; sleep 3; kill -9 $PID 2>/dev/null
fi
wait $PID 2>/dev/null
echo "Terminado en $(( $(date +%s) - start )) s: $OUT"
grep -h "error CS\|\[FaceLab\] terminado" "$OUT/unity.log" | head -20
