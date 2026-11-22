#!/usr/bin/env bash
# Kiosk Player installeren of bijwerken op Ubuntu 24.04.
#
#   sudo ./install.sh                  # vraagt naar de kioskgebruiker als dat nodig is
#   sudo ./install.sh protectiepartners
#   sudo KIOSK_PORT=8090 ./install.sh  # andere webpoort (standaard 8080)
#
# Opnieuw draaien werkt het programma bij; media, wachtrijen en planning blijven bewaard.
set -euo pipefail

if [[ $EUID -ne 0 ]]; then
  echo "Start dit script met sudo:  sudo ./install.sh" >&2
  exit 1
fi

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
KIOSK_USER="${1:-${SUDO_USER:-}}"
if [[ -z "$KIOSK_USER" || "$KIOSK_USER" == "root" ]]; then
  read -rp "Onder welke gebruiker draait het scherm (de gebruiker die automatisch inlogt)? " KIOSK_USER
fi
if ! id "$KIOSK_USER" >/dev/null 2>&1; then
  echo "Gebruiker '$KIOSK_USER' bestaat niet." >&2
  exit 1
fi
KIOSK_GROUP="$(id -gn "$KIOSK_USER")"
KIOSK_HOME="$(getent passwd "$KIOSK_USER" | cut -d: -f6)"
APP_DIR=/opt/kiosk-player
DATA_DIR="$KIOSK_HOME/kiosk-player"
PORT="${KIOSK_PORT:-8080}"
as_user() { sudo -u "$KIOSK_USER" -H env KIOSK_DATA_DIR="$DATA_DIR" "$@"; }

echo "==> Pakketten installeren (Flask, VLC, ffmpeg)"
apt-get update -qq
apt-get install -y python3-flask vlc ffmpeg
if ! apt-get install -y python3-waitress; then
  echo "    Let op: python3-waitress is niet beschikbaar; Kiosk Player gebruikt dan de ingebouwde webserver."
fi

echo "==> Programma kopiëren naar $APP_DIR"
mkdir -p "$APP_DIR"
rm -rf "$APP_DIR/app" "$APP_DIR/app.prev" "$APP_DIR/app.failed" "$APP_DIR/app.swap" "$APP_DIR/.staging"
rm -f "$APP_DIR/update-state.json"
cp -r "$SRC/app" "$SRC/run.py" "$APP_DIR/"
if [[ -f "$SRC/CHANGELOG.md" ]]; then cp "$SRC/CHANGELOG.md" "$APP_DIR/app/"; fi  # getoond in de webinterface
find "$APP_DIR" -name __pycache__ -prune -exec rm -rf {} +
# Welke versie dit is: uit een git-checkout, of doorgegeven door get.sh. Uit een zip weten we het niet.
GIT_SHA="$(git -C "$SRC" rev-parse HEAD 2>/dev/null || true)"
GIT_BRANCH="$(git -C "$SRC" rev-parse --abbrev-ref HEAD 2>/dev/null || true)"
GIT_SHA="${GIT_SHA:-${KIOSK_GIT_SHA:-}}"
GIT_BRANCH="${GIT_BRANCH:-${KIOSK_GIT_BRANCH:-}}"
python3 - "$APP_DIR/VERSION.json" "$GIT_BRANCH" "$GIT_SHA" <<'PY'
import datetime, json, sys
path, branch, sha = sys.argv[1:4]
with open(path, "w") as f:
    json.dump({"source": "install.sh", "branch": branch or None, "sha": sha or None,
               "installed_at": datetime.datetime.now().isoformat(timespec="seconds"),
               "previous": None}, f, indent=2)
PY
# Verwijderscript buiten de programmamap en van root: het draait met sudo, dus de kioskgebruiker
# (eigenaar van $APP_DIR) mag het niet kunnen aanpassen.
install -o root -g root -m 755 "$SRC/uninstall.sh" /usr/local/sbin/kiosk-player-uninstall
# De kioskgebruiker is eigenaar, zodat de update via de website app/ kan vervangen.
chown -R "$KIOSK_USER:$KIOSK_GROUP" "$APP_DIR"
chmod -R u+rwX,go+rX "$APP_DIR"

echo "==> Gegevensmap $DATA_DIR"
as_user mkdir -p "$DATA_DIR/media"
if [[ ! -f "$DATA_DIR/config.json" ]]; then
  as_user python3 -c 'import json, os, sys; json.dump({"port": int(sys.argv[1])}, open(os.path.join(os.environ["KIOSK_DATA_DIR"], "config.json"), "w"))' "$PORT"
elif [[ -n "${KIOSK_PORT:-}" ]]; then
  as_user python3 -c 'import json, os, sys; p = os.path.join(os.environ["KIOSK_DATA_DIR"], "config.json"); c = json.load(open(p)); c["port"] = int(sys.argv[1]); json.dump(c, open(p, "w"), indent=2)' "$PORT"
fi
PORT="$(as_user python3 -c 'import json, os; print(json.load(open(os.path.join(os.environ["KIOSK_DATA_DIR"], "config.json"))).get("port", 8080))')"

HAS_PW="$(as_user python3 -c 'import json, os; print("ja" if json.load(open(os.path.join(os.environ["KIOSK_DATA_DIR"], "config.json"))).get("password_hash") else "nee")')"
if [[ "$HAS_PW" == "nee" ]]; then
  if [[ -t 0 ]]; then
    while true; do
      read -rsp "Kies een wachtwoord voor de webinterface (minstens 8 tekens): " PW1; echo
      read -rsp "Nogmaals: " PW2; echo
      if [[ "$PW1" == "$PW2" && ${#PW1} -ge 8 ]]; then break; fi
      echo "Niet gelijk of te kort. Probeer het opnieuw."
    done
  else
    PW1="$(python3 -c 'import secrets; print(secrets.token_urlsafe(10))')"
    echo "    Gegenereerd wachtwoord: $PW1   (wijzig het later onder Instellingen)"
  fi
  printf '%s\n' "$PW1" | as_user python3 "$APP_DIR/run.py" set-password
  unset PW1 PW2
fi

# Bestaande media uit Documenten overnemen (alleen de eerste keer, en alleen als je dat wilt)
if [[ -t 0 && -d "$KIOSK_HOME/Documents" && -z "$(ls -A "$DATA_DIR/media" 2>/dev/null)" ]]; then
  mapfile -t FOUND < <(find "$KIOSK_HOME/Documents" -maxdepth 1 -type f \
    \( -iname '*.mp4' -o -iname '*.mkv' -o -iname '*.mov' -o -iname '*.avi' -o -iname '*.webm' -o -iname '*.m4v' \
       -o -iname '*.png' -o -iname '*.jpg' -o -iname '*.jpeg' \) | sort)
  if (( ${#FOUND[@]} )); then
    echo "Gevonden in $KIOSK_HOME/Documents:"
    printf '    %s\n' "${FOUND[@]##*/}"
    read -rp "Deze bestanden kopiëren naar de mediabibliotheek? [j/N] " ANSWER
    if [[ "${ANSWER,,}" == j* ]]; then
      for f in "${FOUND[@]}"; do as_user cp "$f" "$DATA_DIR/media/"; done
      echo "    Gekopieerd. De originelen blijven staan."
    fi
  fi
fi

echo "==> Dienst kiosk-player instellen"
cat > /etc/systemd/system/kiosk-player.service <<EOF
[Unit]
Description=Kiosk Player (webinterface om VLC op het scherm te beheren)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$KIOSK_USER
Group=$KIOSK_GROUP
Environment=KIOSK_DATA_DIR=$DATA_DIR
Environment=PYTHONUNBUFFERED=1
WorkingDirectory=$KIOSK_HOME
ExecStart=/usr/bin/python3 $APP_DIR/run.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable kiosk-player >/dev/null
systemctl restart kiosk-player

if command -v ufw >/dev/null && ufw status 2>/dev/null | grep -q "Status: active"; then
  echo "==> Firewall: poort $PORT openzetten"
  ufw allow "$PORT"/tcp comment "Kiosk Player" >/dev/null
fi

sleep 2
IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
echo
if systemctl is-active --quiet kiosk-player; then
  echo "Klaar. Open in je browser:  http://${IP:-<ip-van-de-kiosk>}:$PORT"
else
  echo "De dienst draait niet. Bekijk de foutmelding met:  journalctl -u kiosk-player -n 50" >&2
  exit 1
fi
echo "Media, wachtrijen en planning staan in $DATA_DIR"
echo "Verwijderen kan later met:  sudo kiosk-player-uninstall"
