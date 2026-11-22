"""Tests voor login, sessies en validatie van de webinterface."""
import os
import sys

import pytest

pytest.importorskip("flask")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from werkzeug.security import generate_password_hash  # noqa: E402

from app.server import ApiError, create_app, validate_extra_args, validate_vlc_command  # noqa: E402
from app.store import Config  # noqa: E402

H = {"X-Requested-With": "kiosk"}
PW = "geheim-wachtwoord"


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
def test_vlc_command_allowed(cmd):
    validate_vlc_command(cmd)


@pytest.mark.parametrize("cmd", ["bash -c 'rm -rf ~'", "/tmp/cvlc", "python3", "cvlc /etc/passwd",
                                 "cvlc --lua-intf=x", "cvlc --sout=file/ts:/home/x"])
def test_vlc_command_blocked(cmd):
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


def test_settings_endpoint_rejects_bad_vlc_command(app):
    c = app.test_client()
    login(c)
    r = c.put("/api/settings", headers=H, json={"vlc_command": "bash"})
    assert r.status_code == 400 and "vlc of cvlc" in r.get_json()["error"]
