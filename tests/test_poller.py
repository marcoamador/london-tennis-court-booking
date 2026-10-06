from datetime import date, datetime, time

import httpx
import pytest

from app import poller
from app.config import LONDON
from app.providers.base import Slot
from tests.conftest import add_rule

NOW = datetime(2026, 10, 7, 12, 0, tzinfo=LONDON)


class FakeFetcher:
    def __init__(self):
        self.spaces = 0
        self.fail = False

    async def __call__(self, client, venue, dates):
        if self.fail:
            raise httpx.ConnectError("boom")
        return [Slot(venue.id, "Court 1", date(2026, 10, 10), time(18), time(19), self.spaces)]


@pytest.fixture
def fetcher(monkeypatch):
    fake = FakeFetcher()
    monkeypatch.setitem(poller.FETCHERS, "clubspark", fake)
    monkeypatch.setitem(poller.FETCHERS, "better", FakeFetcher())
    monkeypatch.setattr(poller, "RETRY_DELAYS", ())
    return fake


async def run(db, settings, mailer):
    async with httpx.AsyncClient() as client:
        return await poller.poll_once(db, settings, mailer, client, now=NOW)


async def test_cancellation_triggers_one_alert(db, settings, mailer, user_id, fetcher):
    add_rule(db, user_id, venues="west-ham-park")
    fetcher.spaces = 1
    assert await run(db, settings, mailer) == 0  # baseline: free already, no alert
    fetcher.spaces = 0
    assert await run(db, settings, mailer) == 0  # someone books it
    fetcher.spaces = 1
    assert await run(db, settings, mailer) == 1  # cancellation
    assert await run(db, settings, mailer) == 0  # still free, no repeat
    assert "West Ham Park" in mailer.outbox[0].subject


async def test_outage_then_recovery_does_not_alert(db, settings, mailer, user_id, fetcher):
    add_rule(db, user_id, venues="west-ham-park")
    fetcher.spaces = 0
    await run(db, settings, mailer)
    fetcher.fail = True
    await run(db, settings, mailer)
    with db.connect() as conn:
        status = conn.execute(
            "SELECT * FROM provider_status WHERE venue_id = 'west-ham-park'"
        ).fetchone()
        kept = conn.execute(
            "SELECT COUNT(*) FROM slots WHERE venue_id = 'west-ham-park'"
        ).fetchone()
    assert status["consecutive_failures"] == 1
    assert kept[0] == 1  # last good snapshot kept
    fetcher.fail = False
    assert await run(db, settings, mailer) == 0
