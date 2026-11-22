"""Tests voor de regisseur, met een nep-VLC. Uitvoeren met: python3 -m pytest tests/"""
import os
import sys
import threading
import time
from datetime import datetime, timedelta

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.controller import Controller  # noqa: E402
from app.store import Store  # noqa: E402

ALL_DAYS = list(range(7))


class FakeProc:
    pid = 4242

    def __init__(self, player):
        self.player = player

    def poll(self):
        return self.player.exit_code


class FakePlayer:
    """Gedraagt zich als app.player.Player, maar start geen VLC."""

    def __init__(self):
        self.proc = None
        self.spec = None
        self.sig = None
        self.started_at = None
        self.exit_code = None
        self.started = []          # queue_id per start
        self.start_gate = None     # threading.Event om start() te laten wachten
        self.fail_start = False

    @property
    def running(self):
        return self.proc is not None and self.exit_code is None

    def start(self, spec):
        self.stop()
        if self.start_gate:
            self.start_gate.wait(5)
        if self.fail_start:
            raise OSError("cvlc niet gevonden")
        self.exit_code = None
        self.proc = FakeProc(self)
        self.spec, self.sig, self.started_at = spec, spec.signature(), time.time()
        self.started.append(spec.queue_id)
        self._reported = False

    def stop(self):
        self.proc = self.spec = self.sig = self.started_at = None
        self.exit_code = None
        self._reported = True

    def finish(self, rc=0):
        self.exit_code = rc

    def poll_exit(self):
        if self.proc is None or self._reported or self.exit_code is None:
            return None
        self._reported = True
        return self.exit_code, 1.0

    def log_tail(self, lines=15):
        return ""

    def display_command(self):
        return "cvlc ..." if self.proc else ""

    def status(self):
        return None


class FakeMedia:
    def path_for(self, name):
        return f"/media/{name}"


def make(tmp_path, queues, rules=(), default=None):
    store = Store(str(tmp_path))
    store.data["queues"] = [
        {"id": qid, "name": qid, "items": [{"file": f"{qid}.mp4"}], "loop": loop}
        for qid, loop in queues.items()]
    store.data["rules"] = [dict(r) for r in rules]
    store.settings["default_queue"] = default
    player = FakePlayer()
    return Controller(store, FakeMedia(), player, str(tmp_path)), store, player


def whole_day(rule_id, queue_id):
    return {"id": rule_id, "queue_id": queue_id, "days": ALL_DAYS,
            "start": "00:00", "end": "00:00", "enabled": True}


def test_one_shot_rule_then_one_shot_default_stops_instead_of_alternating(tmp_path):
    c, _store, p = make(tmp_path, {"A": False, "D": False}, [whole_day("r", "A")], default="D")
    c.tick()
    assert p.started == ["A"]
    p.finish()
    c.tick()
    assert p.started == ["A", "D"]
    p.finish()
    for _ in range(3):
        c.tick()
    assert p.started == ["A", "D"] and not p.running


def test_one_shot_rule_falls_back_to_looping_default(tmp_path):
    c, _store, p = make(tmp_path, {"A": False, "D": True}, [whole_day("r", "A")], default="D")
    c.tick()
    p.finish()
    c.tick()
    c.tick()
    assert p.started == ["A", "D"] and p.running and p.spec.queue_id == "D"


def test_finished_rule_plays_again_on_next_occurrence(tmp_path):
    c, store, _p = make(tmp_path, {"A": False, "D": False}, [whole_day("r", "A")], default="D")
    today = datetime(2026, 11, 23, 10)
    key, _src, qid, _slot = c.desired(today)
    store.runtime["finished_key"] = f"{key}|default"
    assert c.desired(today)[2] is None
    assert c.desired(today + timedelta(days=1))[2] == "A"
    assert store.runtime["finished_key"] is None


def test_one_shot_default_without_rule_stops(tmp_path):
    c, _store, p = make(tmp_path, {"D": False}, default="D")
    c.tick()
    p.finish()
    c.tick()
    c.tick()
    assert p.started == ["D"] and not p.running


def test_manual_override_wins_and_resume_returns_to_schedule(tmp_path):
    c, _store, p = make(tmp_path, {"A": True, "M": True}, [whole_day("r", "A")])
    c.tick()
    c.manual("M")
    assert p.spec.queue_id == "M" and p.spec.source == "manual"
    c.resume_schedule()
    assert p.spec.queue_id == "A"


def test_manual_override_expires_when_schedule_changes(tmp_path):
    c, store, _p = make(tmp_path, {"A": True, "M": True}, [whole_day("r", "A")])
    c.manual("M")
    store.runtime["override"]["sched_key"] = "rule:r:gisteren"
    assert c.desired(datetime.now())[2] == "A"
    assert store.runtime["override"] is None


def test_scheduler_off_keeps_current_queue(tmp_path):
    c, store, p = make(tmp_path, {"A": True}, [whole_day("r", "A")])
    c.tick()
    store.settings["scheduler_enabled"] = False
    c.scheduler_toggled(False)
    c.tick()
    assert p.running and p.spec.queue_id == "A" and p.spec.source == "manual"


def test_crash_waits_with_backoff_before_retry(tmp_path):
    c, _store, p = make(tmp_path, {"A": True}, default="A")
    c.tick()
    p.finish(rc=1)
    c.tick()                      # crash opgemerkt, wacht 5 s
    assert p.started == ["A"] and c.last_error and c.retry_at > time.time()
    c.retry_at = time.time() - 1
    c.tick()
    assert p.started == ["A", "A"]


def test_start_failure_is_reported(tmp_path):
    c, _store, p = make(tmp_path, {"A": True}, default="A")
    p.fail_start = True
    c.tick()
    assert not p.running and "Kon VLC niet starten" in c.last_error


def test_status_does_not_wait_for_slow_vlc_start(tmp_path):
    c, _store, p = make(tmp_path, {"A": True}, default="A")
    p.start_gate = threading.Event()
    t = threading.Thread(target=c.tick)
    t.start()
    try:
        time.sleep(0.1)           # tick hangt nu in player.start()
        result = {}
        s = threading.Thread(target=lambda: result.update(c.status()))
        s.start()
        s.join(1)
        assert not s.is_alive(), "status() wacht op het starten van VLC"
        assert result["desired"]["queue_id"] == "A"
    finally:
        p.start_gate.set()
        t.join(5)
    assert p.running


@pytest.mark.parametrize("queue_loop", [True, False])
def test_deleted_queue_override_is_dropped(tmp_path, queue_loop):
    c, store, _p = make(tmp_path, {"A": queue_loop, "M": True}, default="A")
    c.manual("M")
    store.data["queues"] = [q for q in store.queues if q["id"] != "M"]
    assert c.desired(datetime.now())[2] == "A"
