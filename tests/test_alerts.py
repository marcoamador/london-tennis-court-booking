from datetime import date, time

from app.alerts import FreedSlot, Rule, dispatch
from app.providers.base import Slot
from tests.conftest import add_rule

SAT = date(2026, 10, 10)


def freed(hour=18, venue="west-ham-park", d=SAT, court="Court 1"):
    return FreedSlot(
        Slot(venue, court, d, time(hour), time(hour + 1), 1, "£7.90"), "2026-10-07T12:00"
    )


def test_rule_matching():
    rule = Rule(1, 1, frozenset({"west-ham-park"}), frozenset({5, 6}), time(17), time(20))
    assert rule.matches(freed(18).slot)
    assert not rule.matches(freed(20).slot)  # end is exclusive
    assert not rule.matches(freed(16).slot)
    assert not rule.matches(freed(18, venue="stratford-park").slot)
    assert not rule.matches(freed(18, d=date(2026, 10, 12)).slot)  # Monday


async def test_dispatch_batches_and_dedupes(db, mailer, settings, user_id):
    add_rule(db, user_id, weekdays="5,6", frm="17:00", to="21:00")
    batch = [freed(18), freed(18, court="Court 2"), freed(19), freed(9)]
    assert await dispatch(db, mailer, settings, batch) == 1
    assert len(mailer.outbox) == 1
    mail = mailer.outbox[0]
    assert mail.to == "friend@example.com"
    assert "2 courts" in mail.text and "18:00" in mail.text and "19:00" in mail.text
    assert "09:00" not in mail.text
    assert "BookByDate#?date=2026-10-10" in mail.text

    # Same free events again (e.g. a duplicate poll) — no second email.
    assert await dispatch(db, mailer, settings, batch) == 0
    assert len(mailer.outbox) == 1


async def test_paused_users_get_nothing(db, mailer, settings, user_id):
    add_rule(db, user_id)
    with db.connect() as conn:
        conn.execute("UPDATE users SET alerts_paused = 1")
    assert await dispatch(db, mailer, settings, [freed()]) == 0
