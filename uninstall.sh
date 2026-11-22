#!/usr/bin/env bash
# Kiosk Player verwijderen.
#
#   sudo ./uninstall.sh          # verwijdert het programma, bewaart media en instellingen
#   sudo ./uninstall.sh --alles  # verwijdert ook de gegevensmap met alle media
set -euo pipefail

if [[ $EUID -ne 0 ]]; then
  echo "Start dit script met sudo:  sudo ./uninstall.sh" >&2
  exit 1
fi

UNIT=/etc/systemd/system/kiosk-player.service
DATA_DIR=""
if [[ -f "$UNIT" ]]; then
  DATA_DIR="$(sed -n 's/^Environment=KIOSK_DATA_DIR=//p' "$UNIT")"
fi

systemctl disable --now kiosk-player 2>/dev/null || true
rm -f "$UNIT"
systemctl daemon-reload
rm -rf /opt/kiosk-player
echo "Programma verwijderd."

if [[ "${1:-}" == "--alles" && -n "$DATA_DIR" && -d "$DATA_DIR" ]]; then
  read -rp "Ook $DATA_DIR met alle media verwijderen? Dit kan niet ongedaan worden. [j/N] " ANSWER
  if [[ "${ANSWER,,}" == j* ]]; then
    rm -rf "$DATA_DIR"
    echo "Gegevensmap verwijderd."
  fi
elif [[ -n "$DATA_DIR" ]]; then
  echo "Media en instellingen staan nog in $DATA_DIR"
fi
