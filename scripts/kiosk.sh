#!/usr/bin/env bash
# Modo kiosco para el stand: arranca `sonia run` en bucle y lo reinicia solo
# si el proceso muere, para que la demo se recupere sola sin teclado ni
# intervención de nadie del equipo durante las ocho horas del evento.
#
# Uso: scripts/kiosk.sh
# Parar: Ctrl+C (cierra a Sonia limpiamente, no reinicia después).
#
# Variables:
#   RESTART_DELAY_S   Segundos de espera entre un fallo y el reintento
#                      (por defecto 3).
set -uo pipefail
# Sin `-e`: este script ES el bucle de supervisión, así que un `sonia run`
# que termina con error es esperado y se maneja explícitamente, no debe
# tumbar el script.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
SERVER_DIR="$REPO_ROOT/server"
LOG_DIR="$REPO_ROOT/logs"
RESTART_DELAY_S="${RESTART_DELAY_S:-3}"

mkdir -p "$LOG_DIR"

STOP=0
CHILD_PID=""

on_interrupt() {
  echo
  echo "Señal de parada recibida, cerrando Sonia..."
  STOP=1
  if [[ -n "$CHILD_PID" ]] && kill -0 "$CHILD_PID" 2>/dev/null; then
    kill -TERM "$CHILD_PID" 2>/dev/null || true
    wait "$CHILD_PID" 2>/dev/null || true
  fi
}
trap on_interrupt INT TERM

cd "$SERVER_DIR"

echo "Modo kiosco activo. Sonia se reiniciará sola si el proceso termina."
echo "Logs en: $LOG_DIR"
echo "Ctrl+C para parar de forma definitiva."
echo

while [[ "$STOP" -eq 0 ]]; do
  TIMESTAMP="$(date '+%Y%m%d-%H%M%S')"
  LOG_FILE="$LOG_DIR/sonia-$TIMESTAMP.log"

  echo "$(date '+%Y-%m-%d %H:%M:%S') arrancando 'uv run sonia run' (log: $LOG_FILE)" | tee -a "$LOG_FILE"

  uv run --no-sync sonia run >>"$LOG_FILE" 2>&1 &
  CHILD_PID=$!
  wait "$CHILD_PID"
  EXIT_CODE=$?
  CHILD_PID=""

  if [[ "$STOP" -eq 1 ]]; then
    break
  fi

  echo "$(date '+%Y-%m-%d %H:%M:%S') 'sonia run' terminó con código $EXIT_CODE. Reiniciando en ${RESTART_DELAY_S}s..." | tee -a "$LOG_FILE"
  sleep "$RESTART_DELAY_S"
done

echo "Modo kiosco detenido."
