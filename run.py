#!/usr/bin/env python3
"""Start Kiosk Player.

  run.py                 de webinterface en planner starten (zo start systemd hem op Linux)
  run.py --supervise     Windows: Kiosk Player starten en na afsluiten opnieuw starten
  run.py set-password    het wachtwoord van de webinterface wijzigen

Dit bestand wordt alleen door install.sh/install.ps1 bijgewerkt, nooit door de update
via de website. Daardoor kan het een update die niet start veilig terugzetten: start een
nieuwe versie MAX_ATTEMPTS keer niet goed op, dan komt de vorige versie terug.
Houd dit bestand daarom klein en alleen afhankelijk van de standaardbibliotheek.
"""
import json
import os
import shutil
import subprocess
import sys
import threading
import time
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
MAX_ATTEMPTS = 3
HEALTHY_AFTER = 30  # seconden dat een nieuwe versie moet blijven draaien
CREATE_NO_WINDOW = 0x08000000


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


def _rename(src, dst):
    for i in range(10):  # Windows: een virusscanner kan de map even vasthouden
        try:
            os.rename(src, dst)
            return
        except PermissionError:
            if os.name != "nt" or i == 9:
                raise
            time.sleep(0.3)


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
    _rename(app, failed)
    _rename(prev, app)
    version_path = os.path.join(base, "VERSION.json")
    previous = (_read(version_path) or {}).get("previous") or {"source": "onbekend"}
    previous = dict(previous, installed_at=datetime.now().isoformat(timespec="seconds"), previous=None)
    _write(version_path, previous)
    _write(state_path, {"status": "rolled_back", "failed_branch": state.get("branch"),
                        "failed_sha": state.get("sha"), "at": datetime.now().isoformat(timespec="seconds")})
    print("Kiosk Player: de nieuwe versie startte niet; de vorige versie is teruggezet.", file=sys.stderr)
    return "rolled_back"


# --- supervisor (Windows) ------------------------------------------------------------
def _lock_single_instance(path):
    """Houd een vergrendeld bestand open; None als een andere supervisor al draait."""
    f = open(path, "a+b")
    try:
        if os.name == "nt":
            import msvcrt
            f.seek(0)
            msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        f.close()
        return None
    return f


def _child_python():
    """python.exe in plaats van pythonw.exe: het kind heeft een echte stdin nodig."""
    exe = sys.executable
    if os.name == "nt" and os.path.basename(exe).lower() == "pythonw.exe":
        cand = os.path.join(os.path.dirname(exe), "python.exe")
        if os.path.isfile(cand):
            return cand
    return exe


def supervise():
    """Start Kiosk Player als kindproces en start hem opnieuw na afsluiten (update, crash).

    Het kind krijgt een pijp als stdin. Stopt de supervisor, dan sluit die pijp en stopt
    het kind vanzelf, samen met VLC (zie watch_supervisor in app/server.py).
    """
    data_dir = os.path.abspath(os.environ.get("KIOSK_DATA_DIR") or os.path.expanduser("~/kiosk-player"))
    logs = os.path.join(data_dir, "logs")
    os.makedirs(logs, exist_ok=True)
    lock = _lock_single_instance(os.path.join(HERE, "supervisor.lock"))
    if lock is None:
        sys.exit("Kiosk Player draait al.")
    env = dict(os.environ, KIOSK_SUPERVISED="1", KIOSK_DATA_DIR=data_dir, PYTHONUNBUFFERED="1")
    flags = CREATE_NO_WINDOW if os.name == "nt" else 0
    err_path = os.path.join(logs, "stderr.log")
    quick_fails = 0
    while True:
        try:
            if os.path.getsize(err_path) > 1_000_000:
                os.replace(err_path, err_path + ".1")
        except OSError:
            pass
        started = time.time()
        with open(err_path, "ab") as err:
            err.write(f"--- {datetime.now().isoformat(timespec='seconds')} start\n".encode())
            err.flush()
            proc = subprocess.Popen([_child_python(), os.path.abspath(__file__)], env=env, cwd=HERE,
                                    stdin=subprocess.PIPE, stdout=err, stderr=err, creationflags=flags)
            proc.wait()
        quick_fails = quick_fails + 1 if time.time() - started < 60 else 0
        time.sleep(min(30, 2 * max(1, quick_fails)))  # 2, 4, 6 ... s; terugzetten na 3 pogingen gaat dus snel


if __name__ == "__main__":
    if sys.argv[1:2] == ["--supervise"]:
        supervise()
        sys.exit(0)
    if sys.argv[1:2] != ["set-password"]:
        try:
            guard_update()
        except Exception as exc:  # noqa: BLE001 - opstarten mag hier nooit op vastlopen
            print(f"Kiosk Player: controle na update mislukt: {exc}", file=sys.stderr)
    sys.path.insert(0, HERE)
    from app.server import main

    main()
