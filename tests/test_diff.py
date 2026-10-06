from datetime import date, datetime, time, timedelta

from app.config import LONDON
from app.diff import PrevState, compute
from app.providers.base import Slot

NOW = datetime(2026, 10, 7, 12, 0, tzinfo=LONDON)
LEAD = timedelta(minutes=30)


def slot(hour: int, spaces: int, d: date = date(2026, 10, 8), court: str = "Court 1") -> Slot:
    return Slot("v", court, d, time(hour), time(hour + 1), spaces)


def test_baseline_records_state_without_alerting():
    states, newly = compute({}, [slot(10, 1)], NOW, baseline=True, min_lead=LEAD)
    assert newly == []
    assert states[slot(10, 1).key].free_since == NOW.isoformat()


def test_booked_to_free_is_newly_available():
    s = slot(10, 1)
    prev = {s.key: PrevState(spaces=0, free_since=None)}
    states, newly = compute(prev, [s], NOW, baseline=False, min_lead=LEAD)
    assert newly == [s]
    assert states[s.key].free_since == NOW.isoformat()


def test_still_free_keeps_original_free_since_and_does_not_alert():
    s = slot(10, 2)
    earlier = (NOW - timedelta(hours=1)).isoformat()
    prev = {s.key: PrevState(spaces=1, free_since=earlier)}
    states, newly = compute(prev, [s], NOW, baseline=False, min_lead=LEAD)
    assert newly == []
    assert states[s.key].free_since == earlier


def test_free_to_booked_clears_free_since():
    s = slot(10, 0)
    prev = {s.key: PrevState(spaces=1, free_since=NOW.isoformat())}
    states, newly = compute(prev, [s], NOW, baseline=False, min_lead=LEAD)
    assert newly == []
    assert states[s.key].free_since is None


def test_newly_released_slot_is_newly_available():
    s = slot(10, 1, d=date(2026, 10, 20))
    _, newly = compute({}, [s], NOW, baseline=False, min_lead=LEAD)
    assert newly == [s]


def test_slots_starting_too_soon_do_not_alert():
    soon = Slot("v", "Court 1", NOW.date(), time(12, 15), time(13, 15), 1)
    past = Slot("v", "Court 1", NOW.date(), time(9), time(10), 1)
    prev = {soon.key: PrevState(0, None), past.key: PrevState(0, None)}
    _, newly = compute(prev, [soon, past], NOW, baseline=False, min_lead=LEAD)
    assert newly == []
