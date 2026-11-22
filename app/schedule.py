"""Schema-logica: welke wachtrij hoort op een bepaald moment te spelen.

Een regel (rule) heeft dagen (0 = maandag ... 6 = zondag), een start- en
eindtijd en optioneel een datumbereik. Ligt de eindtijd op of voor de
starttijd, dan loopt de regel door tot de volgende dag (00:00-00:00 = hele dag).

Zijn meerdere regels tegelijk actief, dan wint:
  1. de regel die het laatst begonnen is,
  2. daarna de kortste,
  3. daarna die met het kleinste datumbereik,
  4. daarna de nieuwste.
Is er geen regel actief, dan speelt de standaard-wachtrij (of niets).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time as dtime, timedelta
from typing import Iterable, Optional

UNBOUNDED_SPAN = 10**6


@dataclass
class Slot:
    key: str                      # stabiele sleutel voor dit tijdvak
    queue_id: Optional[str]
    rule_id: Optional[str] = None
    start: Optional[datetime] = None
    end: Optional[datetime] = None

    @property
    def source(self) -> str:
        if self.rule_id:
            return "schedule"
        if self.queue_id:
            return "default"
        return "none"


def parse_hm(value: str) -> int:
    """'08:30' -> 510 minuten. '24:00' is toegestaan als einde van de dag."""
    h, m = value.strip().split(":")[:2]
    h, m = int(h), int(m)
    if h == 24 and m == 0:
        return 1440
    if not (0 <= h < 24 and 0 <= m < 60):
        raise ValueError(f"ongeldige tijd: {value}")
    return h * 60 + m


def _date(value) -> Optional[date]:
    if not value:
        return None
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


def occurrence(rule: dict, day: date):
    """(start, eind) van de regel als die op `day` begint, anders None."""
    if not rule.get("enabled", True):
        return None
    if day.weekday() not in rule.get("days", []):
        return None
    d_from, d_to = _date(rule.get("date_from")), _date(rule.get("date_to"))
    if d_from and day < d_from:
        return None
    if d_to and day > d_to:
        return None
    s = parse_hm(rule["start"])
    e = parse_hm(rule["end"])
    if e <= s:
        e += 1440
    midnight = datetime.combine(day, dtime())
    return midnight + timedelta(minutes=s), midnight + timedelta(minutes=e)


def _span(rule: dict) -> int:
    d_from, d_to = _date(rule.get("date_from")), _date(rule.get("date_to"))
    if d_from and d_to:
        return (d_to - d_from).days
    return UNBOUNDED_SPAN


def resolve(rules: Iterable[dict], default_queue: Optional[str], t: datetime,
            valid_queue_ids: set) -> Slot:
    candidates = []
    for rule in rules:
        if rule.get("queue_id") not in valid_queue_ids:
            continue
        for day in (t.date(), t.date() - timedelta(days=1)):
            occ = occurrence(rule, day)
            if occ and occ[0] <= t < occ[1]:
                candidates.append((rule, occ))
    if candidates:
        def rank(item):
            rule, (start, end) = item
            return (start, -(end - start).total_seconds(), -_span(rule),
                    rule.get("created", 0))
        rule, (start, end) = max(candidates, key=rank)
        return Slot(key=f"rule:{rule['id']}:{start.isoformat(timespec='minutes')}",
                    queue_id=rule["queue_id"], rule_id=rule["id"],
                    start=start, end=end)
    if default_queue and default_queue in valid_queue_ids:
        return Slot(key="default", queue_id=default_queue)
    return Slot(key="none", queue_id=None)


def timeline(rules: list, default_queue: Optional[str], t0: datetime, t1: datetime,
             valid_queue_ids: set) -> list:
    """Effectief programma tussen t0 en t1 als lijst aaneengesloten segmenten."""
    bounds = {t0, t1}
    day = t0.date() - timedelta(days=1)
    while day <= t1.date():
        for rule in rules:
            if rule.get("queue_id") not in valid_queue_ids:
                continue
            occ = occurrence(rule, day)
            if occ:
                for b in occ:
                    if t0 < b < t1:
                        bounds.add(b)
        day += timedelta(days=1)
    points = sorted(bounds)
    segments = []
    for a, b in zip(points, points[1:]):
        slot = resolve(rules, default_queue, a, valid_queue_ids)
        if segments and segments[-1]["key"] == slot.key:
            segments[-1]["end"] = b
            continue
        segments.append({"start": a, "end": b, "key": slot.key,
                         "queue_id": slot.queue_id, "rule_id": slot.rule_id})
    return segments


def upcoming_changes(rules: list, default_queue: Optional[str], now: datetime,
                     valid_queue_ids: set, days: int = 8, limit: int = 6) -> list:
    """De eerstvolgende momenten waarop er iets anders op het scherm komt."""
    segs = timeline(rules, default_queue, now, now + timedelta(days=days), valid_queue_ids)
    changes = []
    prev_queue = segs[0]["queue_id"] if segs else None
    for seg in segs[1:]:
        if seg["queue_id"] != prev_queue:
            changes.append(seg)
            prev_queue = seg["queue_id"]
        if len(changes) >= limit:
            break
    return changes
