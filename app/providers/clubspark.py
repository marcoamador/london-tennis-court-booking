"""ClubSpark (LTA) — public JSON used by the venue booking pages; no login needed."""

from datetime import date

import httpx

from app.providers.base import ProviderError, Slot, minutes_to_time
from app.venues import Venue

URL = "https://clubspark.lta.org.uk/v0/VenueBooking/{slug}/GetVenueSessions"

FREE = 0
CLOSED = 8000  # every other session category (bookings, coaching, club sessions) means taken


def _price(session: dict) -> str | None:
    # "Cost" is what the booking page charges: court hire plus floodlights when they're needed.
    cost = session.get("Cost") or (session.get("CourtCost") or 0) + (
        session.get("LightingCost") or 0
    )
    return f"£{cost:.2f}" if cost else None


def parse(venue_id: str, payload: dict, resource_category: int | None = None) -> list[Slot]:
    step = payload.get("MinimumInterval") or 60
    slots: list[Slot] = []
    for resource in payload.get("Resources", []):
        if resource_category is not None and resource.get("Category") != resource_category:
            continue
        court = resource.get("Name") or f"Court {resource.get('Number')}"
        for day in resource.get("Days", []):
            d = date.fromisoformat(day["Date"][:10])
            for session in day.get("Sessions", []):
                category = session.get("Category")
                if category == CLOSED:
                    continue
                free = category == FREE and (session.get("Capacity") or 0) > 0
                price = _price(session) if free else None
                start = session["StartTime"]
                while start + step <= session["EndTime"]:
                    slots.append(
                        Slot(
                            venue_id=venue_id,
                            court=court,
                            date=d,
                            start=minutes_to_time(start),
                            end=minutes_to_time(start + step),
                            spaces=1 if free else 0,
                            price=price,
                        )
                    )
                    start += step
    return slots


async def fetch(client: httpx.AsyncClient, venue: Venue, dates: list[date]) -> list[Slot]:
    if not dates:
        return []
    resp = await client.get(
        URL.format(slug=venue.params["slug"]),
        params={
            "resourceID": "",
            "startDate": min(dates).isoformat(),
            "endDate": max(dates).isoformat(),
            "roleId": "",
        },
    )
    resp.raise_for_status()
    payload = resp.json()
    if not payload.get("Resources"):
        raise ProviderError(f"ClubSpark returned no courts for {venue.params['slug']}")
    wanted = set(dates)
    return [
        s
        for s in parse(venue.id, payload, venue.params.get("resource_category"))
        if s.date in wanted
    ]
