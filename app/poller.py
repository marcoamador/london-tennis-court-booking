"""Periodic job: fetch every tracked venue, diff against stored state, send alerts."""

import asyncio
import logging
from datetime import UTC, date, datetime, timedelta

import httpx

from app import alerts
from app.config import LONDON, Settings
from app.db import Database
from app.diff import PrevState, compute
from app.mailer import Mailer
from app.providers import FETCHERS, Fetcher
from app.providers.base import Slot
from app.venues import Venue, all_venues

log = logging.getLogger(__name__)

RETRY_DELAYS = (2, 5)


def tracked_venues(settings: Settings) -> list[Venue]:
    return [v for v in all_venues() if v.provider != "courtside" or settings.courtside_enabled]


async def _fetch_with_retries(
    fetcher: Fetcher, client: httpx.AsyncClient, venue: Venue, dates: list[date]
) -> list[Slot]:
    for attempt, delay in enumerate((*RETRY_DELAYS, None)):
        try:
            return await fetcher(client, venue, dates)
        except Exception:
            if delay is None:
                raise
            log.info("Fetch %s failed (attempt %d), retrying in %ss", venue.id, attempt + 1, delay)
            await asyncio.sleep(delay)
    raise AssertionError("unreachable")


def _record_failure(db: Database, venue_id: str, error: str) -> None:
    now = datetime.now(UTC).isoformat()
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO provider_status (venue_id, last_error, last_error_at, consecutive_failures)"
            " VALUES (?, ?, ?, 1) ON CONFLICT(venue_id) DO UPDATE SET last_error = excluded.last_error,"
            " last_error_at = excluded.last_error_at,"
            " consecutive_failures = consecutive_failures + 1",
            (venue_id, error[:500], now),
        )


def _store(
    db: Database, settings: Settings, venue: Venue, slots: list[Slot], now: datetime
) -> list[alerts.FreedSlot]:
    with db.connect() as conn:
        status = conn.execute(
            "SELECT baseline_done FROM provider_status WHERE venue_id = ?", (venue.id,)
        ).fetchone()
        baseline = not (status and status["baseline_done"])
        prev = {
            r["key"]: PrevState(r["spaces"], r["free_since"])
            for r in conn.execute(
                "SELECT key, spaces, free_since FROM slots WHERE venue_id = ?", (venue.id,)
            )
        }
        states, newly = compute(
            prev,
            slots,
            now,
            baseline=baseline,
            min_lead=timedelta(minutes=settings.min_lead_minutes),
        )
        # Replace the venue's snapshot wholesale: slots that vanished (past, removed) go away.
        conn.execute("DELETE FROM slots WHERE venue_id = ?", (venue.id,))
        stamp = now.isoformat()
        conn.executemany(
            'INSERT OR REPLACE INTO slots (key, venue_id, court, date, start, "end", spaces, price,'
            " free_since, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    s.key,
                    s.venue_id,
                    s.court,
                    s.date.isoformat(),
                    f"{s.start:%H:%M}",
                    f"{s.end:%H:%M}",
                    s.spaces,
                    s.price,
                    states[s.key].free_since,
                    stamp,
                )
                for s in slots
            ],
        )
        conn.execute(
            "INSERT INTO provider_status (venue_id, last_ok_at, consecutive_failures, baseline_done)"
            " VALUES (?, ?, 0, 1) ON CONFLICT(venue_id) DO UPDATE SET"
            " last_ok_at = excluded.last_ok_at, consecutive_failures = 0, baseline_done = 1",
            (venue.id, datetime.now(UTC).isoformat()),
        )
    return [alerts.FreedSlot(s, states[s.key].free_since) for s in newly]


async def poll_venue(
    db: Database, settings: Settings, client: httpx.AsyncClient, venue: Venue, now: datetime
) -> list[alerts.FreedSlot]:
    today = now.astimezone(LONDON).date()
    dates = [today + timedelta(days=i) for i in range(settings.days_ahead)]
    try:
        slots = await _fetch_with_retries(FETCHERS[venue.provider], client, venue, dates)
    except Exception as exc:
        # Keep the last good snapshot so a recovery doesn't look like a wave of cancellations.
        log.warning("Polling %s failed: %r", venue.id, exc)
        _record_failure(db, venue.id, repr(exc))
        return []
    freed = _store(db, settings, venue, slots, now)
    log.info("Polled %s: %d slots, %d newly free", venue.id, len(slots), len(freed))
    return freed


async def poll_once(
    db: Database,
    settings: Settings,
    mailer: Mailer,
    client: httpx.AsyncClient,
    now: datetime | None = None,
) -> int:
    now = now or datetime.now(LONDON)
    results = await asyncio.gather(
        *(poll_venue(db, settings, client, v, now) for v in tracked_venues(settings))
    )
    freed = [f for venue_freed in results for f in venue_freed]
    return await alerts.dispatch(db, mailer, settings, freed)


def make_client(settings: Settings) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        timeout=20, headers={"User-Agent": settings.user_agent}, follow_redirects=False
    )
