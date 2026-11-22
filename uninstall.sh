#!/usr/bin/env bash
# Kiosk Player verwijderen. install.sh zet dit script ook neer als kiosk-player-uninstall.
#
#   sudo kiosk-player-uninstall           # verwijdert het programma, bewaart media en instellingen
#   sudo kiosk-player-uninstall --alles   # verwijdert ook de gegevensmap met alle media
#   sudo ./uninstall.sh [--alles]         # hetzelfde, vanuit de uitgepakte map
set -euo pipefail

if [[ $EUID -ne 0 ]]; then
  echo "Start dit script met sudo:  sudo kiosk-player-uninstall" >&2
  exit 1
fi

UNIT=/etc/systemd/system/kiosk-player.service
DATA_DIR=""
if [[ -f "$UNIT" ]]; then
  DATA_DIR="$(sed -n 's/^Environment=KIOSK_DATA_DIR=//p' "$UNIT")"
fi
PORT=""
if [[ -n "$DATA_DIR" && -f "$DATA_DIR/config.json" ]]; then
  PORT="$(python3 -c 'import json, sys; print(json.load(open(sys.argv[1])).get("port", 8080))' "$DATA_DIR/config.json" 2>/dev/null || true)"
fi

systemctl disable --now kiosk-player 2>/dev/null || true
rm -f "$UNIT"
systemctl daemon-reload
rm -rf /opt/kiosk-player
if [[ -n "$PORT" ]] && command -v ufw >/dev/null && ufw status 2>/dev/null | grep -q "Status: active"; then
  ufw delete allow "$PORT"/tcp >/dev/null 2>&1 || true
  echo "Firewall: poort $PORT weer gesloten."
fi
rm -f /usr/local/sbin/kiosk-player-uninstall
echo "Programma verwijderd."

if [[ "${1:-}" == "--alles" && -n "$DATA_DIR" && -d "$DATA_DIR" ]]; then
  # Van de terminal lezen: bij `curl ... | sudo bash` is stdin het script zelf.
  INPUT=/dev/stdin
  if [[ -r /dev/tty ]] && { : < /dev/tty; } 2>/dev/null; then INPUT=/dev/tty; fi
  read -rp "Ook $DATA_DIR met alle media verwijderen? Dit kan niet ongedaan worden. [j/N] " ANSWER < "$INPUT" || ANSWER=""
  if [[ "${ANSWER,,}" == j* ]]; then
    rm -rf "$DATA_DIR"
    echo "Gegevensmap verwijderd."
  fi
elif [[ -n "$DATA_DIR" ]]; then
  echo "Media en instellingen staan nog in $DATA_DIR"
fi
