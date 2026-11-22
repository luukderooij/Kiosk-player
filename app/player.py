"""VLC starten, stoppen en besturen via de lokale HTTP-interface van VLC."""
from __future__ import annotations

import base64
import glob
import json
import logging
import os
import secrets
import shlex
import signal
import socket
import subprocess
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass, field

log = logging.getLogger("kiosk.player")

_no_proxy = urllib.request.build_opener(urllib.request.ProxyHandler({}))


@dataclass
class PlaySpec:
    """Alles wat nodig is om één wachtrij in VLC te starten."""
    key: str                 # tijdvak/override-sleutel waarvoor dit speelt
    source: str              # schedule | default | manual | idle
    queue_id: str | None
    queue_name: str
    items: list              # [(pad, kind, image_duration|None)]
    loop: bool = True
    shuffle: bool = False
    mute: bool = False
    settings: dict = field(default_factory=dict)

    def signature(self) -> tuple:
        s = self.settings
        return (tuple(self.items), self.loop, self.shuffle, self.mute,
                s.get("vlc_command"), s.get("display"), s.get("extra_args"),
                s.get("default_image_duration"))


class Player:
    def __init__(self, log_path: str):
        self.log_path = log_path
        self.proc: subprocess.Popen | None = None
        self.spec: PlaySpec | None = None
        self.sig: tuple | None = None
        self.started_at: float | None = None
        self.cmd: list = []
        self.http_port = 18080
        self.http_password = ""
        self._stopping = False
        self._reported = True

    # --- omgeving ------------------------------------------------------------
    @staticmethod
    def environment(display: str) -> dict:
        env = dict(os.environ)
        env.pop("WAYLAND_DISPLAY", None)  # VLC 3 via X11/XWayland, net als met DISPLAY=:0
        env.setdefault("PATH", "/usr/local/bin:/usr/bin:/bin")
        env["DISPLAY"] = display or ":0"
        runtime = f"/run/user/{os.getuid()}"
        if os.path.isdir(runtime):
            env["XDG_RUNTIME_DIR"] = runtime          # geluid via PipeWire/Pulse
            if os.path.exists(os.path.join(runtime, "bus")):
                env["DBUS_SESSION_BUS_ADDRESS"] = f"unix:path={runtime}/bus"  # schermbeveiliging blokkeren
            xauth = os.path.join(runtime, "gdm", "Xauthority")
            mutter = sorted(glob.glob(os.path.join(runtime, ".mutter-Xwaylandauth.*")),
                            key=os.path.getmtime)
            if os.path.exists(xauth):
                env["XAUTHORITY"] = xauth
            elif mutter:
                env["XAUTHORITY"] = mutter[-1]
        if "XAUTHORITY" not in env:
            home_auth = os.path.expanduser("~/.Xauthority")
            if os.path.exists(home_auth):
                env["XAUTHORITY"] = home_auth
        return env

    def build_command(self, spec: PlaySpec) -> list:
        s = spec.settings
        cmd = shlex.split(s.get("vlc_command") or "cvlc")
        cmd += ["--fullscreen", "--no-video-title-show", "--no-osd",
                f"--image-duration={int(s.get('default_image_duration') or 10)}"]
        cmd += ["--loop"] if spec.loop else ["--no-loop", "--play-and-exit"]
        if spec.shuffle:
            cmd.append("--random")
        if spec.mute:
            cmd.append("--no-audio")
        cmd += ["--extraintf=http", "--http-host=127.0.0.1",
                f"--http-port={self.http_port}", f"--http-password={self.http_password}"]
        if s.get("extra_args"):
            cmd += shlex.split(s["extra_args"])
        for path, kind, duration in spec.items:
            cmd.append(path)
            if kind == "image" and duration:
                cmd.append(f":image-duration={int(duration)}")
        return cmd

    @staticmethod
    def _free_port(preferred: int) -> int:
        """De ingestelde poort, of een vrije als die al bezet is (bijv. door een oude VLC)."""
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            try:
                sock.bind(("127.0.0.1", preferred))
                return preferred
            except OSError:
                pass
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        log.warning("Poort %s is bezet; VLC-bediening gebruikt poort %s", preferred, port)
        return port

    def display_command(self) -> str:
        return shlex.join(self.cmd).replace(self.http_password, "••••") if self.cmd else ""

    # --- proces ---------------------------------------------------------------
    @property
    def running(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def start(self, spec: PlaySpec) -> None:
        self.stop()
        s = spec.settings
        if s.get("kill_other_vlc", True):
            subprocess.run(["pkill", "-u", str(os.getuid()), "-x", "vlc"],
                           capture_output=True)
            time.sleep(0.4)
        self.http_port = self._free_port(int(s.get("vlc_http_port") or 18080))
        self.http_password = secrets.token_urlsafe(12)
        self.cmd = self.build_command(spec)
        os.makedirs(os.path.dirname(self.log_path), exist_ok=True)
        with open(self.log_path, "wb") as logf:
            logf.write(f"$ {self.display_command()}\n".encode())
            logf.flush()
            self.proc = subprocess.Popen(
                self.cmd, env=self.environment(s.get("display", ":0")),
                stdin=subprocess.DEVNULL, stdout=logf, stderr=subprocess.STDOUT,
                start_new_session=True, cwd=os.path.expanduser("~"))
        self.spec = spec
        self.sig = spec.signature()
        self.started_at = time.time()
        self._reported = False
        log.info("VLC gestart (pid %s) voor %s", self.proc.pid, spec.queue_name)

    def stop(self) -> None:
        proc = self.proc
        if proc is not None and proc.poll() is None:
            self._stopping = True
            try:
                os.killpg(proc.pid, signal.SIGTERM)
                proc.wait(timeout=5)
            except ProcessLookupError:
                pass
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                proc.wait(timeout=5)
            finally:
                self._stopping = False
        self.proc = None
        self.spec = None
        self.sig = None
        self.started_at = None
        self.cmd = []
        self._reported = True

    def poll_exit(self):
        """Geeft (returncode, looptijd) één keer terug als VLC uit zichzelf stopte."""
        if self.proc is None or self._reported or self._stopping:
            return None
        rc = self.proc.poll()
        if rc is None:
            return None
        self._reported = True
        return rc, time.time() - (self.started_at or time.time())

    def log_tail(self, lines: int = 15) -> str:
        try:
            with open(self.log_path, "rb") as f:
                f.seek(0, os.SEEK_END)
                f.seek(max(0, f.tell() - 8000))
                data = f.read().decode("utf-8", "replace")
        except OSError:
            return ""
        return "\n".join(data.splitlines()[-lines:])

    # --- HTTP-besturing ---------------------------------------------------------
    def http(self, command: str | None = None, **params):
        if not self.running:
            return None
        if command:
            params["command"] = command
        url = f"http://127.0.0.1:{self.http_port}/requests/status.json"
        if params:
            url += "?" + urllib.parse.urlencode(params)
        token = base64.b64encode(f":{self.http_password}".encode()).decode()
        req = urllib.request.Request(url, headers={"Authorization": f"Basic {token}"})
        try:
            with _no_proxy.open(req, timeout=1.5) as resp:
                return json.loads(resp.read().decode("utf-8", "replace"))
        except (OSError, ValueError):
            return None

    def status(self) -> dict | None:
        data = self.http()
        if not data:
            return None
        meta = ((data.get("information") or {}).get("category") or {}).get("meta") or {}
        return {
            "state": data.get("state"),
            "time": data.get("time"),
            "length": data.get("length"),
            "position": data.get("position"),
            "filename": meta.get("filename"),
            "title": meta.get("title"),
        }
