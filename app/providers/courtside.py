"""Courtside (tennistowerhamlets.com) — placeholder.

Anonymous requests are redirected to a Cloudflare Turnstile check, and we never try to solve or
evade it. If `scripts/courtside_probe.py` shows that a logged-in session is served booking pages
without the challenge, a real implementation can go here (behind COURTSIDE_ENABLED, at most one
request per 300 s, per their robots.txt). Until then the UI shows a deep link instead.
"""

from datetime import date

import httpx

from app.providers.base import ProviderError, Slot
from app.venues import Venue


async def fetch(client: httpx.AsyncClient, venue: Venue, dates: list[date]) -> list[Slot]:
    raise ProviderError("Courtside availability tracking is not implemented yet")
