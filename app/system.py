"""Alles wat per besturingssysteem verschilt: Linux (Ubuntu-kiosk met systemd) en Windows.

Lees IS_WINDOWS altijd via deze module (system.IS_WINDOWS) en niet als kopie, zodat
tests het Windows-pad ook op Linux kunnen nabootsen en andersom.
"""
from __future__ import annotations

import getpass
import glob
import os
import shlex
import shutil
import signal
import subprocess
import time

IS_WINDOWS = os.name == "nt"

CREATE_NEW_PROCESS_GROUP = 0x00000200
CREATE_NO_WINDOW = 0x08000000

WINDOWS_VLC_NAMES = {"vlc", "cvlc", "vlc.exe"}


def name() -> str:
    return "windows" if IS_WINDOWS else "linux"


def child_kwargs() -> dict:
    """Argumenten voor élk subproces dat Kiosk Player start (ffmpeg, taskkill, controles).

    stdin=DEVNULL is verplicht: onder run.py --supervise is onze stdin een pijp waarop
    een thread blijft lezen. Een kind dat die pijp erft, blijft op Windows bij het
    opstarten hangen. CREATE_NO_WINDOW voorkomt flitsende consolevensters.
    """
    kw = {"stdin": subprocess.DEVNULL}
    if IS_WINDOWS:
        kw["creationflags"] = CREATE_NO_WINDOW
    return kw


# --- programma's zoeken ------------------------------------------------------------
def _windows_program_dirs() -> list:
    dirs = [os.environ.get(k) for k in ("ProgramFiles", "ProgramFiles(x86)", "ProgramW6432")]
    local = os.environ.get("LOCALAPPDATA")
    if local:
        dirs.append(os.path.join(local, "Programs"))
    return [d for d in dict.fromkeys(dirs) if d]


def find_vlc() -> str | None:
    if not IS_WINDOWS:
        return shutil.which("cvlc") or shutil.which("vlc")
    found = shutil.which("vlc")
    if found:
        return found
    for base in _windows_program_dirs():
        path = os.path.join(base, "VideoLAN", "VLC", "vlc.exe")
        if os.path.isfile(path):
            return path
    return None


def find_tool(tool: str) -> str | None:
    """ffmpeg/ffprobe; op Windows ook in de map van winget, die pas na opnieuw inloggen in PATH staat."""
    found = shutil.which(tool)
    if found or not IS_WINDOWS:
        return found
    local = os.environ.get("LOCALAPPDATA")
    if not local:
        return None
    link = os.path.join(local, "Microsoft", "WinGet", "Links", f"{tool}.exe")
    if os.path.isfile(link):
        return link
    hits = sorted(glob.glob(os.path.join(local, "Microsoft", "WinGet", "Packages", "*FFmpeg*", "**", "bin",
                                         f"{tool}.exe"), recursive=True))
    return hits[-1] if hits else None


def windows_vlc_path_allowed(path: str) -> bool:
    """Alleen vlc.exe uit een normale programmamap, zodat de webinterface niets anders kan starten."""
    norm = os.path.normcase(os.path.normpath(path))
    if os.path.basename(norm) != "vlc.exe":
        return False
    return any(norm.startswith(os.path.normcase(os.path.normpath(d)) + os.sep) for d in _windows_program_dirs())


def vlc_base_command(setting: str) -> list:
    """Het begin van het VLC-commando: programma plus de interface zonder venster."""
    setting = (setting or "").strip()
    if not IS_WINDOWS:
        return shlex.split(setting or "cvlc")
    # Windows: één programma, eventueel met spaties in het pad; cvlc bestaat daar niet.
    prog = setting.strip('"')
    if not prog or prog.lower() in WINDOWS_VLC_NAMES:
        prog = find_vlc() or "vlc.exe"
    return [prog, "--intf=dummy", "--dummy-quiet"]


# --- processen ---------------------------------------------------------------------
def popen_kwargs() -> dict:
    """VLC in een eigen procesgroep starten, los van de webserver."""
    if IS_WINDOWS:
        return {"creationflags": CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW}
    return {"start_new_session": True}


def terminate(proc: subprocess.Popen, timeout: float = 5) -> None:
    """Stop VLC netjes, en hard als dat niet binnen `timeout` seconden lukt."""
    if proc.poll() is not None:
        return
    if IS_WINDOWS:
        proc.terminate()
        try:
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=timeout)
        return
    try:
        os.killpg(proc.pid, signal.SIGTERM)
        proc.wait(timeout=timeout)
    except ProcessLookupError:
        pass
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        proc.wait(timeout=timeout)


def kill_other_vlc() -> None:
    """Sluit andere VLC-processen van deze gebruiker, zodat er geen twee video's over elkaar komen."""
    if IS_WINDOWS:
        subprocess.run(["taskkill", "/F", "/IM", "vlc.exe", "/FI", f"USERNAME eq {getpass.getuser()}"],
                       capture_output=True, **child_kwargs())
    else:
        subprocess.run(["pkill", "-u", str(os.getuid()), "-x", "vlc"], capture_output=True, **child_kwargs())
    time.sleep(0.4)


def player_environment(display: str) -> dict:
    """Omgeving voor VLC. Op Linux: X11/XWayland, geluid en D-Bus van de ingelogde sessie."""
    env = dict(os.environ)
    if IS_WINDOWS:
        return env
    env.pop("WAYLAND_DISPLAY", None)  # VLC 3 via X11/XWayland, net als met DISPLAY=:0
    env.setdefault("PATH", "/usr/local/bin:/usr/bin:/bin")
    env["DISPLAY"] = display or ":0"
    runtime = f"/run/user/{os.getuid()}"
    if os.path.isdir(runtime):
        env["XDG_RUNTIME_DIR"] = runtime          # geluid via PipeWire/Pulse
        if os.path.exists(os.path.join(runtime, "bus")):
            env["DBUS_SESSION_BUS_ADDRESS"] = f"unix:path={runtime}/bus"  # schermbeveiliging blokkeren
        xauth = os.path.join(runtime, "gdm", "Xauthority")
        mutter = sorted(glob.glob(os.path.join(runtime, ".mutter-Xwaylandauth.*")), key=os.path.getmtime)
        if os.path.exists(xauth):
            env["XAUTHORITY"] = xauth
        elif mutter:
            env["XAUTHORITY"] = mutter[-1]
    if "XAUTHORITY" not in env:
        home_auth = os.path.expanduser("~/.Xauthority")
        if os.path.exists(home_auth):
            env["XAUTHORITY"] = home_auth
    return env


# --- dienst ------------------------------------------------------------------------
def is_root() -> bool:
    return not IS_WINDOWS and os.geteuid() == 0


def supervised() -> bool:
    """Draait er iets dat ons na afsluiten opnieuw start? systemd op Linux, run.py --supervise op Windows."""
    return "INVOCATION_ID" in os.environ or os.environ.get("KIOSK_SUPERVISED") == "1"


def not_supervised_message() -> str:
    if IS_WINDOWS:
        return ("Kiosk Player draait niet via de Windows-taak 'Kiosk Player' (run.py --supervise) "
                "en kan zichzelf daarom niet herstarten.")
    return "Kiosk Player draait niet als systemd-dienst en kan zichzelf daarom niet herstarten."


def reinstall_hint() -> str:
    return "Voer op de kiosk eenmalig install.ps1 opnieuw uit." if IS_WINDOWS else \
        "Voer op de kiosk eenmalig sudo ./install.sh opnieuw uit."


def rename(src: str, dst: str, attempts: int = 10) -> None:
    """os.rename, maar op Windows een paar keer opnieuw als een virusscanner of indexer de map vasthoudt."""
    for i in range(attempts):
        try:
            os.rename(src, dst)
            return
        except PermissionError:
            if not IS_WINDOWS or i == attempts - 1:
                raise
            time.sleep(0.3)
