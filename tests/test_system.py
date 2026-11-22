"""Tests voor de platformlaag (Linux/Windows) en de supervisor in run.py."""
import importlib.util
import os
import subprocess
import sys
import threading
import time

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from app import system  # noqa: E402
from app.player import Player, PlaySpec  # noqa: E402


def spec(**settings):
    return PlaySpec(key="k", source="schedule", queue_id="q", queue_name="Q",
                    items=[("/m/film.mp4", "video", None), ("/m/foto.png", "image", 15)],
                    settings={"default_image_duration": 10, **settings})


def test_linux_command(monkeypatch):
    monkeypatch.setattr(system, "IS_WINDOWS", False)
    cmd = Player("/tmp/vlc.log").build_command(spec(vlc_command="cvlc --no-xlib", extra_args="--no-osd"))
    assert cmd[:2] == ["cvlc", "--no-xlib"] and "--fullscreen" in cmd
    assert cmd[-3:] == ["/m/film.mp4", "/m/foto.png", ":image-duration=15"]


def test_windows_command_finds_vlc_exe(monkeypatch):
    monkeypatch.setattr(system, "IS_WINDOWS", True)
    exe = r"C:\Program Files\VideoLAN\VLC\vlc.exe"
    monkeypatch.setattr(system, "find_vlc", lambda: exe)
    for setting in ("cvlc", "vlc", ""):
        cmd = Player("vlc.log").build_command(spec(vlc_command=setting))
        assert cmd[:3] == [exe, "--intf=dummy", "--dummy-quiet"]
    # een opgegeven pad met spaties blijft heel, ook tussen aanhalingstekens
    cmd = Player("vlc.log").build_command(spec(vlc_command=f'"{exe}"'))
    assert cmd[0] == exe


def test_windows_environment_has_no_display(monkeypatch):
    monkeypatch.setattr(system, "IS_WINDOWS", True)
    monkeypatch.delenv("DISPLAY", raising=False)
    assert "DISPLAY" not in system.player_environment(":0")


def test_supervised_detection(monkeypatch):
    monkeypatch.delenv("INVOCATION_ID", raising=False)
    monkeypatch.delenv("KIOSK_SUPERVISED", raising=False)
    assert not system.supervised()
    monkeypatch.setenv("KIOSK_SUPERVISED", "1")
    assert system.supervised()


def test_terminate_stops_a_real_process():
    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"], **system.popen_kwargs())
    t0 = time.time()
    system.terminate(proc)
    assert proc.poll() is not None and time.time() - t0 < 10


CHILD = r"""
import subprocess, sys, threading, time
sys.path.insert(0, sys.argv[1])
from app import system
threading.Thread(target=sys.stdin.buffer.read, daemon=True).start()  # zoals watch_supervisor
time.sleep(0.3)
kw = system.child_kwargs() if sys.argv[2] == "fix" else {}
subprocess.run([sys.executable, "-c", "pass"], timeout=15, **kw)
print("klaar")
"""


def run_child(mode: str, timeout: float) -> bytes:
    proc = subprocess.Popen([sys.executable, "-c", CHILD, ROOT, mode], stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    lines = []
    reader = threading.Thread(target=lambda: lines.append(proc.stdout.readline()), daemon=True)
    reader.start()
    reader.join(timeout)
    proc.kill()
    proc.wait()
    return lines[0] if lines else b""


def test_subprocess_under_supervisor_pipe_does_not_hang():
    """Onder run.py --supervise leest een thread op stdin; een subproces mag die pijp niet erven."""
    assert b"klaar" in run_child("fix", timeout=30)


@pytest.mark.skipif(os.name != "nt", reason="de hang zit in synchrone pijpen van Windows")
def test_without_devnull_it_hangs_on_windows():
    """Bewijst dat de test hierboven het echte probleem dekt."""
    assert b"klaar" not in run_child("zonder", timeout=8)


def test_find_tool_uses_winget_links(monkeypatch, tmp_path):
    monkeypatch.setattr(system, "IS_WINDOWS", True)
    monkeypatch.setattr(system.shutil, "which", lambda name: None)
    links = tmp_path / "Microsoft" / "WinGet" / "Links"
    links.mkdir(parents=True)
    (links / "ffprobe.exe").write_bytes(b"")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    assert system.find_tool("ffprobe") == str(links / "ffprobe.exe")
    assert system.find_tool("ffmpeg") is None


def load_run():
    spec_ = importlib.util.spec_from_file_location("kiosk_run_sys", os.path.join(ROOT, "run.py"))
    mod = importlib.util.module_from_spec(spec_)
    spec_.loader.exec_module(mod)
    return mod


def test_supervisor_lock_allows_one_instance(tmp_path):
    run = load_run()
    path = str(tmp_path / "supervisor.lock")
    first = run._lock_single_instance(path)
    assert first is not None
    code = ("import importlib.util, sys; s = importlib.util.spec_from_file_location('r', sys.argv[1]); "
            "m = importlib.util.module_from_spec(s); s.loader.exec_module(m); "
            "sys.exit(0 if m._lock_single_instance(sys.argv[2]) is None else 1)")
    assert subprocess.run([sys.executable, "-c", code, os.path.join(ROOT, "run.py"), path]).returncode == 0
    first.close()
    assert subprocess.run([sys.executable, "-c", code, os.path.join(ROOT, "run.py"), path]).returncode == 1


@pytest.mark.skipif(os.name != "nt", reason="pythonw.exe bestaat alleen op Windows")
def test_child_python_avoids_pythonw(monkeypatch):
    run = load_run()
    pythonw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    monkeypatch.setattr(run.sys, "executable", pythonw)
    assert os.path.basename(run._child_python()).lower() == "python.exe"
