"""De regisseur: bepaalt elke paar seconden wat er moet spelen en houdt VLC in de lucht."""
from __future__ import annotations

import logging
import os
import struct
import threading
import time
import zlib
from collections import deque
from datetime import datetime

from .media import kind_of
from .player import Player, PlaySpec
from .schedule import Slot, resolve, upcoming_changes
from .store import new_id

log = logging.getLogger("kiosk.controller")

SOURCE_LABEL = {
    "schedule": "volgens planning",
    "default": "standaardwachtrij",
    "manual": "handmatig gestart",
    "idle": "zwart scherm",
}


def write_black_png(path: str, w: int = 16, h: int = 9) -> None:
    def chunk(tag, data):
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    raw = b"".join(b"\x00" + b"\x00\x00\x00" * w for _ in range(h))
    png = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
           + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))
    with open(path, "wb") as f:
        f.write(png)


class Controller:
    TICK = 5  # seconden

    def __init__(self, store, media, player: Player, data_dir: str):
        self.store = store
        self.media = media
        self.player = player
        self.events: deque = deque(maxlen=200)
        self.wake = threading.Event()
        self.failures = 0
        self.retry_at = 0.0
        self.failed_sig = None
        self.last_error: str | None = None
        self._warned: set = set()
        self.black_png = os.path.join(data_dir, "zwart.png")
        if not os.path.exists(self.black_png):
            write_black_png(self.black_png)

    # --- logboek ------------------------------------------------------------
    def event(self, level: str, message: str) -> None:
        self.events.appendleft({"ts": datetime.now().isoformat(timespec="seconds"),
                                "level": level, "message": message})
        getattr(log, "error" if level == "error" else "info")(message)

    def warn_once(self, key: str, message: str) -> None:
        if key not in self._warned:
            self._warned.add(key)
            self.event("warning", message)

    # --- lus ----------------------------------------------------------------
    def start(self) -> None:
        threading.Thread(target=self._loop, name="scheduler", daemon=True).start()

    def poke(self) -> None:
        self.wake.set()

    def _loop(self) -> None:
        while True:
            try:
                self.tick()
            except Exception:  # de lus mag nooit stoppen
                log.exception("Fout in planner")
            self.wake.wait(self.TICK)
            self.wake.clear()

    # --- beslissen ------------------------------------------------------------
    def current_slot(self, now: datetime) -> Slot:
        s = self.store.settings
        if not s.get("scheduler_enabled", True):
            return Slot(key="manual", queue_id=None)
        return resolve(self.store.rules, s.get("default_queue"), now, self.store.queue_ids())

    def desired(self, now: datetime):
        """(sleutel, bron, wachtrij-id, tijdvak) van wat er nu hoort te spelen."""
        store, rt = self.store, self.store.runtime
        slot = self.current_slot(now)
        ov = rt.get("override")
        if ov:
            gone = ov.get("queue_id") and not store.queue(ov["queue_id"])
            if ov.get("sched_key") != slot.key or ov.get("finished") or gone:
                rt["override"] = None
                store.save()
                if ov.get("sched_key") != slot.key:
                    self.event("info", "Handmatige keuze vervallen: de planning neemt het weer over")
            else:
                return f"override:{ov['id']}", "manual", ov.get("queue_id"), slot

        key, source, qid = slot.key, slot.source, slot.queue_id
        fk = rt.get("finished_key")
        if fk and not fk.startswith(slot.key):
            rt["finished_key"] = fk = None
            store.save()
        if fk and fk == key:
            dq = store.settings.get("default_queue")
            if slot.rule_id and dq and store.queue(dq):
                key, source, qid = f"{key}|default", "default", dq
            else:
                qid = None
        if fk and fk == key:
            qid = None
        return key, source, qid, slot

    def build_spec(self, key: str, source: str, queue_id) -> PlaySpec | None:
        s = dict(self.store.settings)
        q = self.store.queue(queue_id) if queue_id else None
        if q:
            items = []
            for it in q.get("items", []):
                path = self.media.path_for(it.get("file", ""))
                if not path:
                    self.warn_once(f"missing:{q['id']}:{it.get('file')}",
                                   f"Bestand '{it.get('file')}' in wachtrij '{q['name']}' ontbreekt en wordt overgeslagen")
                    continue
                kind = kind_of(path)
                items.append((path, kind, it.get("duration") if kind == "image" else None))
            if items:
                return PlaySpec(key=key, source=source, queue_id=q["id"], queue_name=q["name"],
                                items=items, loop=q.get("loop", True),
                                shuffle=q.get("shuffle", False), mute=q.get("mute", False),
                                settings=s)
            self.warn_once(f"empty:{q['id']}", f"Wachtrij '{q['name']}' is leeg en kan niet starten")
        if s.get("idle_black"):
            return PlaySpec(key="idle", source="idle", queue_id=None, queue_name="Zwart scherm",
                            items=[(self.black_png, "image", -1)], loop=True, mute=True, settings=s)
        return None

    def tick(self) -> None:
        with self.store.lock:
            self._handle_exit()
            now = datetime.now()
            key, source, qid, _slot = self.desired(now)
            spec = self.build_spec(key, source, qid)
            p = self.player

            if spec is None:
                if p.running:
                    name = p.spec.queue_name if p.spec else "VLC"
                    p.stop()
                    self.event("info", f"Gestopt: {name}")
                self.failures, self.failed_sig, self.last_error = 0, None, None
                return

            sig = spec.signature()
            if p.running and p.sig == sig:
                p.spec = spec  # zelfde inhoud, alleen bron/tijdvak bijwerken
                if p.started_at and time.time() - p.started_at > 60:
                    self.failures, self.last_error = 0, None
                return

            if not p.running and sig == self.failed_sig and time.time() < self.retry_at:
                return  # wachten voor de volgende poging
            if sig != self.failed_sig:
                self.failures = 0

            try:
                p.start(spec)
            except Exception as exc:
                self._fail(sig, f"Kon VLC niet starten: {exc}")
                return
            self.failed_sig = sig
            self.event("info", "▶ Zwart scherm" if spec.source == "idle" else
                   f"▶ {spec.queue_name} ({SOURCE_LABEL.get(spec.source, spec.source)})")

    def _handle_exit(self) -> None:
        p = self.player
        result = p.poll_exit()
        if not result:
            return
        rc, ran = result
        spec, sig = p.spec, p.sig
        if spec and not spec.loop and rc == 0:
            self.event("info", f"Afgelopen: {spec.queue_name}")
            rt = self.store.runtime
            if spec.source == "manual" and rt.get("override"):
                rt["override"]["finished"] = True
            else:
                rt["finished_key"] = spec.key
            self.store.save()
            self.failures, self.failed_sig, self.last_error = 0, None, None
        else:
            tail = p.log_tail(6)
            self._fail(sig, f"VLC stopte onverwacht (code {rc})" + (f"\n{tail}" if tail else ""),
                       reset=ran > 120)
        p.stop()

    def _fail(self, sig, message: str, reset: bool = False) -> None:
        self.failures = 1 if reset else self.failures + 1
        delay = min(60, 5 * 2 ** (self.failures - 1))
        self.retry_at = time.time() + delay
        self.failed_sig = sig
        self.last_error = message.splitlines()[0] + f" — nieuwe poging over {delay} s"
        self.event("error", f"{message}\nNieuwe poging over {delay} seconden.")

    # --- handmatige acties -------------------------------------------------
    def _reset_retry(self) -> None:
        self.failures, self.retry_at, self.failed_sig, self.last_error = 0, 0.0, None, None

    def manual(self, queue_id) -> None:
        with self.store.lock:
            slot = self.current_slot(datetime.now())
            self.store.runtime["override"] = {
                "id": new_id(), "queue_id": queue_id, "sched_key": slot.key,
                "set_at": datetime.now().isoformat(timespec="seconds"), "finished": False}
            self.store.save()
            q = self.store.queue(queue_id) if queue_id else None
            self.event("info", f"Handmatig: {q['name'] if q else 'stoppen'}")
            self._reset_retry()
        self.tick()

    def resume_schedule(self) -> None:
        with self.store.lock:
            self.store.runtime["override"] = None
            self.store.runtime["finished_key"] = None
            self.store.save()
            self.event("info", "Terug naar planning")
            self._reset_retry()
        self.tick()

    def restart(self) -> None:
        with self.store.lock:
            self.player.stop()
            self._reset_retry()
            self.store.runtime["finished_key"] = None
            self.store.save()
            self.event("info", "VLC herstart")
        self.tick()

    def scheduler_toggled(self, enabled: bool) -> None:
        """Planner uit: huidige weergave vasthouden als handmatige keuze."""
        with self.store.lock:
            rt = self.store.runtime
            if not enabled:
                current = self.player.spec.queue_id if self.player.running and self.player.spec else None
                rt["override"] = {"id": new_id(), "queue_id": current, "sched_key": "manual",
                                  "set_at": datetime.now().isoformat(timespec="seconds"),
                                  "finished": False}
            else:
                rt["override"] = None
            rt["finished_key"] = None
            self.store.save()
            self.event("info", "Planning " + ("aangezet" if enabled else "uitgezet"))
        self.tick()

    # --- status -------------------------------------------------------------
    def status(self) -> dict:
        now = datetime.now()
        with self.store.lock:
            key, source, qid, slot = self.desired(now)
            p, store = self.player, self.store
            spec = p.spec if p.running else None
            rule = store.rule(slot.rule_id) if slot.rule_id else None
            ids = store.queue_ids()
            s = store.settings
            changes = []
            if s.get("scheduler_enabled", True):
                changes = upcoming_changes(store.rules, s.get("default_queue"), now, ids)
            wanted = self.build_spec(key, source, qid) is not None
            out = {
                "now": now.astimezone().isoformat(timespec="seconds"),
                "tz": now.astimezone().tzname(),
                "running": p.running,
                "pid": p.proc.pid if p.running else None,
                "started_at": datetime.fromtimestamp(p.started_at).isoformat(timespec="seconds")
                if p.running and p.started_at else None,
                "queue_id": spec.queue_id if spec else None,
                "queue_name": spec.queue_name if spec else None,
                "source": spec.source if spec else None,
                "loop": spec.loop if spec else None,
                "command": p.display_command() if p.running else "",
                "desired": {"queue_id": qid, "source": source},
                "slot": {"rule_id": slot.rule_id, "rule_name": rule["name"] if rule else None,
                         "start": slot.start.isoformat() if slot.start else None,
                         "end": slot.end.isoformat() if slot.end else None},
                "override": store.runtime.get("override"),
                "scheduler_enabled": s.get("scheduler_enabled", True),
                "error": self.last_error,
                "retry_in": max(0, round(self.retry_at - time.time()))
                if (wanted and not p.running and self.last_error) else None,
                "next_changes": [{"at": c["start"].isoformat(), "queue_id": c["queue_id"],
                                  "rule_id": c["rule_id"]} for c in changes],
            }
        out["vlc"] = p.status() if p.running else None
        return out
