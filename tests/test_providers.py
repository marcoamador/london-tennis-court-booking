import json
from datetime import date, time
from pathlib import Path

import httpx
import respx

from app.providers import better, clubspark
from app.venues import get_venue

FIXTURES = Path(__file__).parent / "fixtures"


def load(name: str):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def by_key(slots):
    return {(s.court, s.date, s.start): s for s in slots}


class TestClubSpark:
    def test_splits_free_windows_into_hourly_slots(self):
        slots = by_key(clubspark.parse("west-ham-park", load("clubspark_westhampark.json"), 1))
        d = date(2026, 10, 7)
        # Court 1: 08:00 booked, 09:00-11:00 free window, 11:00 booked, 12:00-18:00 free, 18:00+ closed
        assert slots[("Court 1", d, time(8))].spaces == 0
        assert slots[("Court 1", d, time(9))].spaces == 1
        assert slots[("Court 1", d, time(10))].spaces == 1
        assert slots[("Court 1", d, time(10))].end == time(11)
        assert slots[("Court 1", d, time(11))].spaces == 0
        assert slots[("Court 1", d, time(17))].spaces == 1
        assert ("Court 1", d, time(18)) not in slots  # closed sessions are dropped

    def test_filters_to_tennis_resources(self):
        slots = clubspark.parse("west-ham-park", load("clubspark_westhampark.json"), 1)
        assert not any("Cricket" in s.court for s in slots)
        assert {s.court for s in slots} == {f"Court {i}" for i in range(1, 13)}

    def test_price_formatted(self):
        slots = clubspark.parse("west-ham-park", load("clubspark_westhampark.json"), 1)
        free = next(s for s in slots if s.spaces)
        assert free.price == "£7.90"

    @respx.mock
    async def test_fetch_requests_whole_range_once(self):
        route = respx.get(
            "https://clubspark.lta.org.uk/v0/VenueBooking/WestHamPark/GetVenueSessions"
        ).mock(return_value=httpx.Response(200, json=load("clubspark_westhampark.json")))
        async with httpx.AsyncClient() as client:
            slots = await clubspark.fetch(
                client, get_venue("west-ham-park"), [date(2026, 10, 7), date(2026, 10, 8)]
            )
        assert route.call_count == 1
        params = route.calls[0].request.url.params
        assert params["startDate"] == "2026-10-07" and params["endDate"] == "2026-10-08"
        assert slots

    @respx.mock
    async def test_stratford_park_uses_newham_venue(self):
        # Regression: "StratfordParkTennisCourts" is Stroud's Stratford Park, not Newham's.
        route = respx.get(
            "https://clubspark.lta.org.uk/v0/VenueBooking/stratford_newhamparkstennis_org_uk/GetVenueSessions"
        ).mock(return_value=httpx.Response(200, json=load("clubspark_stratford.json")))
        venue = get_venue("stratford-park")
        async with httpx.AsyncClient() as client:
            slots = await clubspark.fetch(client, venue, [date(2026, 10, 7), date(2026, 10, 8)])
        assert route.called
        assert {s.court for s in slots} == {f"Court {i}" for i in range(1, 7)}
        assert venue.booking_url(date(2026, 10, 7)).startswith(
            "https://stratford.newhamparkstennis.org.uk/Booking/BookByDate#?date=2026-10-07"
        )


class TestBetter:
    def test_parse_times(self):
        slots = better.parse("lee-valley-outdoor", load("better_times.json"))
        assert len(slots) == 8
        first = slots[0]
        assert (first.date, first.start, first.end) == (date(2026, 10, 7), time(10), time(11))
        assert first.spaces == 6
        assert first.price == "£14.00"
        assert first.court == "Courts"

    def test_full_slots_have_zero_spaces(self):
        slots = {s.start: s for s in better.parse("lee-valley-outdoor", load("better_times.json"))}
        assert slots[time(18)].spaces == 0

    def test_non_bookable_status_counts_as_unavailable(self):
        payload = load("better_times.json")
        payload["data"][0]["action_to_show"] = {"status": "NOT_YET_BOOKABLE", "reason": None}
        slots = better.parse("lee-valley-outdoor", payload)
        assert slots[0].spaces == 0

    @respx.mock
    async def test_fetch_only_requests_offered_dates(self):
        base = (
            "https://better-admin.org.uk/api/activities/venue/lee-valley-hockey-and-tennis-centre"
        )
        respx.get(f"{base}/activity-category/tennis-court-outdoor/dates").mock(
            return_value=httpx.Response(200, json=load("better_dates.json"))
        )
        times = respx.get(f"{base}/activity/tennis-court-outdoor/v2/times").mock(
            return_value=httpx.Response(200, json=load("better_times.json"))
        )
        offered = [d["raw"] for d in load("better_dates.json")["data"]]
        wanted = [date.fromisoformat(offered[0]), date(2030, 1, 1)]
        async with httpx.AsyncClient() as client:
            await better.fetch(client, get_venue("lee-valley-outdoor"), wanted)
        assert times.call_count == 1
        assert times.calls[0].request.headers["origin"] == "https://bookings.better.org.uk"
