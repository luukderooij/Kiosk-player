"""Opslag van wachtrijen, schema, instellingen en configuratie in JSON-bestanden."""
from __future__ import annotations

import copy
import json
import os
import secrets
import tempfile
import threading
import time
import uuid

DEFAULT_SETTINGS = {
    "default_queue": None,        # wachtrij als er niets gepland staat
    "scheduler_enabled": True,    # planner aan/uit
    "idle_black": False,          # zwart scherm i.p.v. bureaublad als er niets speelt
    "kill_other_vlc": True,       # andere VLC-vensters van deze gebruiker sluiten
    "vlc_command": "cvlc",
    "display": ":0",
    "default_image_duration": 10,
    "extra_args": "",
    "vlc_http_port": 18080,
}

DEFAULT_CONFIG = {
    "port": 8080,
    "host": "0.0.0.0",
    "max_upload_gb": 20,
    "password_hash": None,
    "secret_key": None,
    "update_repo": "luukderooij/Kiosk-player",  # GitHub-repository voor updates via de website
    "github_token": None,                         # alleen nodig als de repository privé is
}


def atomic_write_json(path: str, data) -> None:
    folder = os.path.dirname(path)
    fd, tmp = tempfile.mkstemp(prefix=".tmp-", dir=folder)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False, default=str)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def new_id() -> str:
    return uuid.uuid4().hex[:10]


class Config:
    """config.json: poort, wachtwoord-hash, sessiesleutel."""

    def __init__(self, data_dir: str):
        self.path = os.path.join(data_dir, "config.json")
        self.data = dict(DEFAULT_CONFIG)
        if os.path.exists(self.path):
            with open(self.path, encoding="utf-8") as f:
                self.data.update(json.load(f))
        changed = False
        if not self.data.get("secret_key"):
            self.data["secret_key"] = secrets.token_hex(32)
            changed = True
        if changed or not os.path.exists(self.path):
            self.save()

    def save(self) -> None:
        atomic_write_json(self.path, self.data)
        try:
            os.chmod(self.path, 0o600)
        except OSError:
            pass

    def __getitem__(self, key):
        return self.data[key]

    def __setitem__(self, key, value):
        self.data[key] = value


class Store:
    """data.json: wachtrijen, regels, instellingen en runtime-status."""

    def __init__(self, data_dir: str):
        self.path = os.path.join(data_dir, "data.json")
        self.lock = threading.RLock()
        self.data = {
            "queues": [],
            "rules": [],
            "settings": dict(DEFAULT_SETTINGS),
            "runtime": {"override": None, "finished_key": None},
        }
        if os.path.exists(self.path):
            with open(self.path, encoding="utf-8") as f:
                loaded = json.load(f)
            for key in ("queues", "rules"):
                self.data[key] = loaded.get(key, [])
            self.data["settings"].update(loaded.get("settings", {}))
            self.data["runtime"].update(loaded.get("runtime", {}))
        self.save()

    def save(self) -> None:
        with self.lock:
            atomic_write_json(self.path, self.data)

    # --- hulpfuncties -------------------------------------------------
    @property
    def settings(self) -> dict:
        return self.data["settings"]

    @property
    def runtime(self) -> dict:
        return self.data["runtime"]

    @property
    def queues(self) -> list:
        return self.data["queues"]

    @property
    def rules(self) -> list:
        return self.data["rules"]

    def queue(self, queue_id):
        return next((q for q in self.queues if q["id"] == queue_id), None)

    def rule(self, rule_id):
        return next((r for r in self.rules if r["id"] == rule_id), None)

    def queue_ids(self) -> set:
        return {q["id"] for q in self.queues}

    def snapshot(self) -> dict:
        with self.lock:
            return copy.deepcopy(self.data)

    @staticmethod
    def now_ts() -> float:
        return time.time()
