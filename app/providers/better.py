"""Better (GLL) — the API behind bookings.better.org.uk; availability is visible without login."""

import logging
from datetime import date, time

import httpx

from app.providers.base import Slot
from app.venues import Venue

log = logging.getLogger(__name__)

BASE = "https://better-admin.org.uk/api/activities/venue/{venue}"
HEADERS = {
    "Origin": "https://bookings.better.org.uk",
    "Referer": "https://bookings.better.org.uk/",
    "Accept": "application/json",
}
BOOKABLE = {"BOOK"}
KNOWN_UNAVAILABLE = {"FULL"}


def parse(venue_id: str, payload: dict) -> list[Slot]:
    slots = []
    for item in payload.get("data", []):
        status = (item.get("action_to_show") or {}).get("status")
        if status not in BOOKABLE | KNOWN_UNAVAILABLE:
            log.info("Better slot with unrecognised status %r treated as unavailable", status)
        spaces = int(item.get("spaces") or 0) if status in BOOKABLE else 0
        slots.append(
            Slot(
                venue_id=venue_id,
                court="Courts",
                date=date.fromisoformat(item["date"]),
                start=time.fromisoformat(item["starts_at"]["format_24_hour"]),
                end=time.fromisoformat(item["ends_at"]["format_24_hour"]),
                spaces=spaces,
                price=(item.get("price") or {}).get("formatted_amount"),
            )
        )
    return slots


async def fetch(client: httpx.AsyncClient, venue: Venue, dates: list[date]) -> list[Slot]:
    base = BASE.format(venue=venue.params["venue"])
    activity = venue.params["activity"]
    resp = await client.get(f"{base}/activity-category/{activity}/dates", headers=HEADERS)
    resp.raise_for_status()
    offered = {d["raw"] for d in resp.json().get("data", [])}

    slots: list[Slot] = []
    for d in dates:
        if d.isoformat() not in offered:
            continue
        resp = await client.get(
            f"{base}/activity/{activity}/v2/times",
            params={"date": d.isoformat()},
            headers=HEADERS,
        )
        resp.raise_for_status()
        slots.extend(parse(venue.id, resp.json()))
    return slots
