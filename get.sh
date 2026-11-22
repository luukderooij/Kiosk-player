#!/usr/bin/env bash
# Kiosk Player in één keer downloaden en installeren op Ubuntu 24.04.
#
#   curl -fsSL https://raw.githubusercontent.com/luukderooij/Kiosk-player/main/get.sh | bash
#
# Opties via omgevingsvariabelen:
#   KIOSK_BRANCH=test-branch   een andere branch installeren (standaard main)
#   KIOSK_PORT=8090            een andere webpoort (standaard 8080)
#   KIOSK_USER=naam            de kioskgebruiker (standaard: wie dit uitvoert)
#
# Dit script haalt de versie op van GitHub en start daarna install.sh daaruit.
set -euo pipefail

REPO="luukderooij/Kiosk-player"
BRANCH="${KIOSK_BRANCH:-main}"
KIOSK_USER="${KIOSK_USER:-${SUDO_USER:-$(id -un)}}"

if command -v curl >/dev/null; then
  fetch() { curl -fsSL ${2:+-H "$2"} "$1"; }
elif command -v wget >/dev/null; then
  fetch() { wget -qO- ${2:+--header="$2"} "$1"; }
else
  echo "curl of wget is nodig. Installeer het met: sudo apt install curl" >&2
  exit 1
fi

echo "==> Versie opzoeken: $REPO, branch $BRANCH"
SHA="$(fetch "https://api.github.com/repos/$REPO/commits/$BRANCH" 'Accept: application/vnd.github.sha' || true)"
if [[ ! "$SHA" =~ ^[0-9a-f]{40}$ ]]; then
  echo "Branch '$BRANCH' niet gevonden op GitHub." >&2
  exit 1
fi

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
echo "==> Downloaden (${SHA:0:7})"
fetch "https://codeload.github.com/$REPO/tar.gz/$SHA" | tar -xz -C "$TMP"
SRC="$(find "$TMP" -mindepth 1 -maxdepth 1 -type d | head -n1)"

ENVVARS=(KIOSK_GIT_SHA="$SHA" KIOSK_GIT_BRANCH="$BRANCH")
[[ -n "${KIOSK_PORT:-}" ]] && ENVVARS+=(KIOSK_PORT="$KIOSK_PORT")

# install.sh stelt vragen (wachtwoord, media overnemen). Bij `curl | bash` is stdin het
# script zelf, dus lees de antwoorden van de terminal als die er is.
INPUT=/dev/null
if [[ -r /dev/tty ]] && { : < /dev/tty; } 2>/dev/null; then INPUT=/dev/tty; fi

if [[ $EUID -eq 0 ]]; then
  env "${ENVVARS[@]}" bash "$SRC/install.sh" "$KIOSK_USER" < "$INPUT"
else
  echo "==> Installeren (sudo vraagt om je wachtwoord)"
  sudo env "${ENVVARS[@]}" bash "$SRC/install.sh" "$KIOSK_USER" < "$INPUT"
fi
