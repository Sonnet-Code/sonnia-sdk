#!/usr/bin/env bash
# Publica el panel de control de Sonia en https://sonia.sonnetcode.com.
#
# Arranca el conector de Cloudflare Tunnel ("sonia-panel", gestionado desde el
# dashboard de Cloudflare: el ingress manda sonia.sonnetcode.com a
# http://localhost:8780) y lo reinicia si se cae. El panel lo sirve el propio
# orquestador (`sonia run`); este script solo abre el camino desde internet.
#
# El token del conector vive FUERA del repo, en ~/.cloudflared/sonia-panel.token
# (permisos 600). Para llevarlo al equipo del stand, copia ese archivo.
# Ver docs/panel.md, "Publicación en internet".
#
# Uso: scripts/panel_tunnel.sh
set -uo pipefail

TOKEN_FILE="${SONIA_TUNNEL_TOKEN_FILE:-$HOME/.cloudflared/sonia-panel.token}"
RESTART_DELAY_S=5

if ! command -v cloudflared >/dev/null 2>&1; then
  echo "Falta cloudflared: brew install cloudflared (macOS) o winget install Cloudflare.cloudflared (Windows)." >&2
  exit 1
fi
if [[ ! -s "$TOKEN_FILE" ]]; then
  echo "No existe el token del túnel en $TOKEN_FILE (ver docs/panel.md)." >&2
  exit 1
fi

trap 'echo; echo "Túnel detenido."; exit 0' INT TERM

while true; do
  echo "$(date '+%H:%M:%S') conectando el túnel de sonia.sonnetcode.com"
  cloudflared tunnel --no-autoupdate run --token-file "$TOKEN_FILE"
  echo "$(date '+%H:%M:%S') el túnel se cerró (código $?); se reintenta en ${RESTART_DELAY_S}s" >&2
  sleep "$RESTART_DELAY_S"
done
