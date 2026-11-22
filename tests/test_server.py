"""Tests voor login, sessies en validatie van de webinterface."""
import os
import sys

import pytest

pytest.importorskip("flask")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from werkzeug.security import generate_password_hash  # noqa: E402

from app.server import ApiError, create_app, validate_extra_args, validate_vlc_command  # noqa: E402
from app import system  # noqa: E402
from app.store import Config  # noqa: E402

H = {"X-Requested-With": "kiosk"}
PW = "geheim-wachtwoord"
ON_WINDOWS = pytest.mark.skipif(os.name != "nt", reason="Windows-paden worden met ntpath vergeleken")


@pytest.fixture
def linux(monkeypatch):
    monkeypatch.setattr(system, "IS_WINDOWS", False)


@pytest.fixture
def windows(monkeypatch):
    monkeypatch.setattr(system, "IS_WINDOWS", True)
    monkeypatch.setenv("ProgramFiles", r"C:\Program Files")
    monkeypatch.setenv("ProgramFiles(x86)", r"C:\Program Files (x86)")
    monkeypatch.delenv("ProgramW6432", raising=False)
    monkeypatch.setenv("LOCALAPPDATA", r"C:\Users\kiosk\AppData\Local")


@pytest.fixture
def app(tmp_path):
    cfg = Config(str(tmp_path))
    cfg["password_hash"] = generate_password_hash(PW)
    cfg.save()
    app = create_app(str(tmp_path))
    app.config["TESTING"] = True
    return app


def login(client, pw=PW):
    return client.post("/api/login", json={"password": pw})


def test_api_requires_login(app):
    assert app.test_client().get("/api/state").status_code == 401


def test_login_and_csrf_header(app):
    c = app.test_client()
    assert login(c).status_code == 200
    assert c.get("/api/state").status_code == 200
    assert c.post("/api/player/resume").status_code == 403
    assert c.post("/api/player/resume", headers=H).status_code == 200


def test_password_change_logs_out_other_sessions(app):
    me, other = app.test_client(), app.test_client()
    login(me)
    login(other)
    r = me.post("/api/password", headers=H, json={"current": PW, "new": "nieuw-wachtwoord"})
    assert r.status_code == 200
    assert me.get("/api/state").status_code == 200
    assert other.get("/api/state").status_code == 401
    assert login(app.test_client(), "nieuw-wachtwoord").status_code == 200


@pytest.mark.parametrize("cmd", ["cvlc", "vlc", "/usr/bin/cvlc", "cvlc --no-xlib", "/snap/bin/vlc --vout=x11"])
def test_vlc_command_allowed(cmd, linux):
    validate_vlc_command(cmd)


@pytest.mark.parametrize("cmd", ["bash -c 'rm -rf ~'", "/tmp/cvlc", "python3", "cvlc /etc/passwd",
                                 "cvlc --lua-intf=x", "cvlc --sout=file/ts:/home/x"])
def test_vlc_command_blocked(cmd, linux):
    with pytest.raises(ApiError):
        validate_vlc_command(cmd)


@ON_WINDOWS
@pytest.mark.parametrize("cmd", ["vlc", "cvlc", "VLC.exe", r'"C:\Program Files\VideoLAN\VLC\vlc.exe"',
                                 r"C:\Program Files (x86)\VideoLAN\VLC\vlc.exe",
                                 r"C:\Users\kiosk\AppData\Local\Programs\VideoLAN\VLC\vlc.exe"])
def test_vlc_command_allowed_windows(cmd, windows):
    validate_vlc_command(cmd)


@ON_WINDOWS
@pytest.mark.parametrize("cmd", [r"C:\Windows\System32\cmd.exe", r"C:\Temp\vlc.exe", "powershell",
                                 r"C:\Program Files\VideoLAN\VLC\..\..\..\Temp\vlc.exe",
                                 r"C:\Program Files\VideoLAN\VLC\vlc.exe --lua-intf=x"])
def test_vlc_command_blocked_windows(cmd, windows):
    with pytest.raises(ApiError):
        validate_vlc_command(cmd)


@pytest.mark.parametrize("extra", ["", "--no-audio --aspect-ratio=16:9", "--no-sub-autodetect-file"])
def test_extra_args_allowed(extra):
    validate_extra_args(extra)


@pytest.mark.parametrize("extra", ["--extraintf=telnet", "--http-port=80", "-I lua", "/home/x.mp4",
                                   "--config=/tmp/x", "--no-http-password", "--snapshot-path=/tmp"])
def test_extra_args_blocked(extra):
    with pytest.raises(ApiError):
        validate_extra_args(extra)


@pytest.mark.parametrize("raw", ["wachtwoord-é-test\n".encode(), "﻿wachtwoord-é-test\r\n".encode()])
def test_set_password_from_pipe_handles_bom_and_crlf(tmp_path, raw):
    import json
    import subprocess

    from werkzeug.security import check_password_hash
    env = dict(os.environ, KIOSK_DATA_DIR=str(tmp_path))
    run_py = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "run.py")
    subprocess.run([sys.executable, run_py, "set-password"], input=raw, env=env, check=True, capture_output=True)
    h = json.load(open(tmp_path / "config.json"))["password_hash"]
    assert check_password_hash(h, "wachtwoord-é-test")


@pytest.mark.parametrize("with_waitress", [True, False])
def test_main_starts_the_web_server(tmp_path, monkeypatch, with_waitress):
    """main() moet tot aan het starten van de webserver komen, met en zonder waitress."""
    import types

    from app import server
    calls = {}
    if with_waitress:
        fake = types.ModuleType("waitress")
        fake.serve = lambda app, **kw: calls.update(kind="waitress", **kw)
        monkeypatch.setitem(sys.modules, "waitress", fake)
    else:
        monkeypatch.setitem(sys.modules, "waitress", None)  # import faalt
        monkeypatch.setattr(server.Flask, "run", lambda self, **kw: calls.update(kind="flask", **kw))
    cfg = Config(str(tmp_path))
    cfg["password_hash"] = generate_password_hash(PW)
    cfg["host"], cfg["port"] = "127.0.0.1", 0
    cfg.save()
    monkeypatch.setenv("KIOSK_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("KIOSK_SUPERVISED", raising=False)
    monkeypatch.setattr(sys, "argv", ["run.py"])
    monkeypatch.setattr(server, "setup_logging", lambda data_dir: None)
    server.main()
    assert calls["kind"] == ("waitress" if with_waitress else "flask")
    if with_waitress:
        assert calls["max_request_body_size"] > 1024 ** 3


def test_changelog_endpoint(app):
    c = app.test_client()
    assert c.get("/api/changelog").status_code == 401
    login(c)
    r = c.get("/api/changelog").get_json()
    assert r["text"] and r["text"].startswith("# Changelog")  # in een ontwikkelmap: CHANGELOG.md naast app/


def test_update_status_and_refusal_in_dev_checkout(app):
    c = app.test_client()
    login(c)
    st = c.get("/api/update").get_json()
    assert st["job"]["status"] == "idle" and st["problem"]  # git-checkout of geen systemd
    r = c.post("/api/update", headers=H, json={"branch": "main"})
    assert r.status_code in (400, 409) and r.get_json()["error"]
    assert c.post("/api/update", json={"branch": "main"}).status_code == 403


def test_settings_endpoint_rejects_bad_vlc_command(app, linux):
    c = app.test_client()
    login(c)
    r = c.put("/api/settings", headers=H, json={"vlc_command": "bash"})
    assert r.status_code == 400 and "vlc of cvlc" in r.get_json()["error"]
