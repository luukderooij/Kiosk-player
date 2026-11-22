#!/usr/bin/env python3
"""Start Kiosk Player. Gebruik `run.py set-password` om het wachtwoord te wijzigen.

Dit bestand wordt alleen door install.sh bijgewerkt, nooit door de update via de
website. Daardoor kan het een update die niet start veilig terugzetten: start een
nieuwe versie MAX_ATTEMPTS keer niet goed op, dan komt de vorige versie terug.
Houd dit bestand daarom klein en alleen afhankelijk van de standaardbibliotheek.
"""
import json
import os
import shutil
import sys
import threading
import time
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
MAX_ATTEMPTS = 3
HEALTHY_AFTER = 30  # seconden dat een nieuwe versie moet blijven draaien


def _read(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _write(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(tmp, path)


def guard_update(base=HERE, healthy_after=HEALTHY_AFTER):
    """Tel opstartpogingen na een update en zet terug als de nieuwe versie niet start."""
    state_path = os.path.join(base, "update-state.json")
    state = _read(state_path)
    if not state or state.get("status") != "trial":
        return None
    state["attempts"] = int(state.get("attempts", 0)) + 1
    if state["attempts"] <= MAX_ATTEMPTS:
        _write(state_path, state)

        def mark_healthy():
            time.sleep(healthy_after)
            cur = _read(state_path)
            if cur and cur.get("status") == "trial" and cur.get("sha") == state.get("sha"):
                cur.update(status="ok", ok_at=datetime.now().isoformat(timespec="seconds"))
                _write(state_path, cur)

        threading.Thread(target=mark_healthy, name="update-check", daemon=True).start()
        return "trial"

    app, prev, failed = (os.path.join(base, n) for n in ("app", "app.prev", "app.failed"))
    if not os.path.isdir(prev):
        state["status"] = "failed_no_backup"
        _write(state_path, state)
        return "failed_no_backup"
    shutil.rmtree(failed, ignore_errors=True)
    os.rename(app, failed)
    os.rename(prev, app)
    version_path = os.path.join(base, "VERSION.json")
    previous = (_read(version_path) or {}).get("previous") or {"source": "onbekend"}
    previous = dict(previous, installed_at=datetime.now().isoformat(timespec="seconds"), previous=None)
    _write(version_path, previous)
    _write(state_path, {"status": "rolled_back", "failed_branch": state.get("branch"),
                        "failed_sha": state.get("sha"), "at": datetime.now().isoformat(timespec="seconds")})
    print("Kiosk Player: de nieuwe versie startte niet; de vorige versie is teruggezet.", file=sys.stderr)
    return "rolled_back"


if __name__ == "__main__":
    if sys.argv[1:2] != ["set-password"]:
        try:
            guard_update()
        except Exception as exc:  # noqa: BLE001 - opstarten mag hier nooit op vastlopen
            print(f"Kiosk Player: controle na update mislukt: {exc}", file=sys.stderr)
    sys.path.insert(0, HERE)
    from app.server import main

    main()
