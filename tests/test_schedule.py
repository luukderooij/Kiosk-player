"""Tests voor de schema-logica. Uitvoeren met: python3 -m pytest tests/"""
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.schedule import resolve, timeline, upcoming_changes  # noqa: E402

Q = {"main", "promo", "night", "special"}
WEEKDAYS = [0, 1, 2, 3, 4]


def rule(id, queue, days, start, end, created=0, **kw):
    return dict(id=id, queue_id=queue, days=days, start=start, end=end,
                created=created, enabled=True, **kw)


def test_default_when_nothing_planned():
    s = resolve([], "main", datetime(2026, 11, 2, 9), Q)
    assert s.queue_id == "main" and s.key == "default" and s.source == "default"


def test_nothing_without_default():
    s = resolve([], None, datetime(2026, 11, 2, 9), Q)
    assert s.queue_id is None and s.source == "none"


def test_rule_overrides_default_and_ends():
    rules = [rule("r1", "promo", WEEKDAYS, "09:00", "12:00")]
    assert resolve(rules, "main", datetime(2026, 11, 2, 8, 59), Q).queue_id == "main"
    assert resolve(rules, "main", datetime(2026, 11, 2, 9, 0), Q).queue_id == "promo"
    assert resolve(rules, "main", datetime(2026, 11, 2, 11, 59), Q).queue_id == "promo"
    assert resolve(rules, "main", datetime(2026, 11, 2, 12, 0), Q).queue_id == "main"
    # zaterdag niet
    assert resolve(rules, "main", datetime(2026, 11, 7, 10), Q).queue_id == "main"


def test_overnight_rule_belongs_to_start_day():
    rules = [rule("n", "night", [4], "22:00", "06:00")]  # vrijdagnacht
    assert resolve(rules, None, datetime(2026, 11, 6, 23), Q).queue_id == "night"
    assert resolve(rules, None, datetime(2026, 11, 7, 5, 59), Q).queue_id == "night"   # za-ochtend
    assert resolve(rules, None, datetime(2026, 11, 7, 6), Q).queue_id is None
    assert resolve(rules, None, datetime(2026, 11, 5, 23), Q).queue_id is None          # donderdag


def test_whole_day_and_later_start_wins():
    rules = [rule("all", "main", list(range(7)), "00:00", "00:00"),
             rule("lunch", "promo", WEEKDAYS, "12:00", "13:00")]
    assert resolve(rules, None, datetime(2026, 11, 2, 12, 30), Q).queue_id == "promo"
    assert resolve(rules, None, datetime(2026, 11, 2, 23, 59), Q).queue_id == "main"
    assert resolve(rules, None, datetime(2026, 11, 3, 0, 0), Q).queue_id == "main"


def test_date_range_and_specific_beats_general_on_tie():
    rules = [rule("all", "main", list(range(7)), "00:00", "00:00", created=1),
             rule("monday", "special", list(range(7)), "00:00", "00:00", created=0,
                  date_from="2026-11-02", date_to="2026-11-02")]
    assert resolve(rules, None, datetime(2026, 11, 1, 10), Q).queue_id == "main"
    assert resolve(rules, None, datetime(2026, 11, 2, 10), Q).queue_id == "special"
    assert resolve(rules, None, datetime(2026, 11, 3, 10), Q).queue_id == "main"


def test_from_monday_onwards():
    rules = [rule("new", "promo", list(range(7)), "00:00", "00:00", date_from="2026-11-02")]
    assert resolve(rules, "main", datetime(2026, 11, 1, 23, 59), Q).queue_id == "main"
    assert resolve(rules, "main", datetime(2026, 11, 2, 0, 0), Q).queue_id == "promo"
    assert resolve(rules, "main", datetime(2027, 3, 1, 12), Q).queue_id == "promo"


def test_disabled_rule_and_deleted_queue_are_ignored():
    rules = [rule("off", "promo", WEEKDAYS, "09:00", "17:00"),
             rule("ghost", "deleted", WEEKDAYS, "09:00", "17:00")]
    rules[0]["enabled"] = False
    assert resolve(rules, "main", datetime(2026, 11, 2, 10), Q).queue_id == "main"


def test_key_changes_per_occurrence():
    rules = [rule("r", "promo", list(range(7)), "09:00", "10:00")]
    k1 = resolve(rules, None, datetime(2026, 11, 2, 9, 30), Q).key
    k2 = resolve(rules, None, datetime(2026, 11, 3, 9, 30), Q).key
    assert k1 != k2 and k1.startswith("rule:r:")


def test_timeline_segments_are_contiguous_and_merged():
    rules = [rule("lunch", "promo", WEEKDAYS, "12:00", "13:00")]
    t0, t1 = datetime(2026, 11, 2), datetime(2026, 11, 3)
    segs = timeline(rules, "main", t0, t1, Q)
    assert [(s["start"].hour, s["queue_id"]) for s in segs] == [(0, "main"), (12, "promo"), (13, "main")]
    assert segs[0]["start"] == t0 and segs[-1]["end"] == t1
    for a, b in zip(segs, segs[1:]):
        assert a["end"] == b["start"]


def test_upcoming_changes_skips_same_queue():
    rules = [rule("a", "promo", WEEKDAYS, "09:00", "10:00"),
             rule("b", "promo", WEEKDAYS, "10:00", "11:00")]
    ch = upcoming_changes(rules, "main", datetime(2026, 11, 2, 8), Q, days=1)
    assert [(c["start"].hour, c["queue_id"]) for c in ch] == [(9, "promo"), (11, "main")]
