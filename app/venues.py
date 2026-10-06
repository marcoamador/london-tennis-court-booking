from dataclasses import dataclass, field
from datetime import date


@dataclass(frozen=True)
class Venue:
    id: str
    name: str
    area: str
    provider: str  # clubspark | better | courtside
    booking_url_template: str
    params: dict = field(default_factory=dict)
    note: str = ""

    def booking_url(self, d: date | None = None) -> str:
        return self.booking_url_template.format(date=(d or date.today()).isoformat())


VENUES: list[Venue] = [
    Venue(
        id="west-ham-park",
        name="West Ham Park",
        area="Forest Gate, E7",
        provider="clubspark",
        params={"slug": "WestHamPark", "resource_category": 1},
        booking_url_template="https://clubspark.lta.org.uk/WestHamPark/Booking/BookByDate#?date={date}&role=guest",
        note="12 hard courts, no floodlights",
    ),
    Venue(
        id="stratford-park",
        name="Stratford Park",
        area="Stratford, E15",
        provider="clubspark",
        # Newham Parks Tennis white-label ClubSpark site. Not "StratfordParkTennisCourts" (that's Stroud).
        params={"slug": "stratford_newhamparkstennis_org_uk", "resource_category": 1},
        booking_url_template="https://stratford.newhamparkstennis.org.uk/Booking/BookByDate#?date={date}&role=guest",
        note="Newham Parks Tennis · 6 courts, floodlit",
    ),
    Venue(
        id="lee-valley-outdoor",
        name="Lee Valley — outdoor",
        area="Olympic Park, E20",
        provider="better",
        params={"venue": "lee-valley-hockey-and-tennis-centre", "activity": "tennis-court-outdoor"},
        booking_url_template="https://bookings.better.org.uk/location/lee-valley-hockey-and-tennis-centre/tennis-court-outdoor/{date}/by-time",
        note="Better — courts are pooled, numbers show courts left",
    ),
    Venue(
        id="lee-valley-indoor",
        name="Lee Valley — indoor",
        area="Olympic Park, E20",
        provider="better",
        params={"venue": "lee-valley-hockey-and-tennis-centre", "activity": "tennis-court-indoor"},
        booking_url_template="https://bookings.better.org.uk/location/lee-valley-hockey-and-tennis-centre/tennis-court-indoor/{date}/by-time",
        note="Better — courts are pooled, numbers show courts left",
    ),
    Venue(
        id="victoria-park",
        name="Victoria Park",
        area="Hackney, E9",
        provider="courtside",
        params={"slug": "victoria-park"},
        booking_url_template="https://tennistowerhamlets.com/book/courts/victoria-park",
        note="Courtside (Tennis Tower Hamlets) — availability not shared publicly, check on their site",
    ),
]


def all_venues() -> list[Venue]:
    return list(VENUES)


def get_venue(venue_id: str) -> Venue | None:
    return next((v for v in VENUES if v.id == venue_id), None)
