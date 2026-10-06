"""Fetch real availability once from every trackable venue and print a summary.

uv run python -m scripts.smoke
"""

import asyncio
from collections import Counter
from datetime import date, timedelta

from app.config import get_settings
from app.poller import make_client
from app.providers import FETCHERS
from app.venues import VENUES


async def main() -> None:
    dates = [date.today() + timedelta(days=i) for i in range(7)]
    async with make_client(get_settings()) as client:
        for venue in VENUES:
            if venue.provider == "courtside":
                print(f"{venue.name}: skipped (not trackable) — {venue.booking_url()}")
                continue
            try:
                slots = await FETCHERS[venue.provider](client, venue, dates)
            except Exception as exc:
                print(f"{venue.name}: FAILED {exc!r}")
                continue
            free = Counter(s.date for s in slots if s.spaces)
            print(f"{venue.name}: {len(slots)} slots, {sum(free.values())} free")
            for d in dates:
                times = sorted({f"{s.start:%H:%M}" for s in slots if s.date == d and s.spaces})
                print(f"  {d:%a %d %b}: {', '.join(times) or '—'}")


if __name__ == "__main__":
    asyncio.run(main())
