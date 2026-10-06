from collections.abc import Awaitable, Callable
from datetime import date

import httpx

from app.providers import better, clubspark, courtside
from app.providers.base import ProviderError, Slot
from app.venues import Venue

Fetcher = Callable[[httpx.AsyncClient, Venue, list[date]], Awaitable[list[Slot]]]

FETCHERS: dict[str, Fetcher] = {
    "clubspark": clubspark.fetch,
    "better": better.fetch,
    "courtside": courtside.fetch,
}

__all__ = ["FETCHERS", "Fetcher", "ProviderError", "Slot"]
