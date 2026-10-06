"""Turn stored slots into a days × hours grid per venue for the home page."""

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta

from app.db import Database
from app.venues import Venue

PERIODS = {
    "all": (0, 24),
    "morning": (0, 12),
    "afternoon": (12, 17),
    "evening": (17, 24),
}
STALE_AFTER = timedelta(minutes=20)


@dataclass
class Cell:
    state: str  # free | booked | past | none
    free: int = 0
    total: int = 0
    price: str | None = None


@dataclass
class VenueGrid:
    venue: Venue
    tracked: bool
    dates: list[date] = field(default_factory=list)
    hours: list[int] = field(default_factory=list)
    cells: dict[tuple[date, int], Cell] = field(default_factory=dict)
    last_ok_at: datetime | None = None
    last_error: str | None = None
    stale: bool = False
    free_total: int = 0
    now: datetime | None = None

    def cell(self, d: date, hour: int) -> Cell:
        if (d, hour) in self.cells:
            return self.cells[(d, hour)]
        if self.now and _starts_at(d, hour, self.now) < self.now:
            return Cell("past")
        return Cell("none")

    @property
    def updated_ago(self) -> str:
        if not self.last_ok_at:
            return "not yet updated"
        minutes = int((datetime.now(UTC) - self.last_ok_at).total_seconds() // 60)
        return "just now" if minutes < 1 else f"{minutes} min ago"


def _starts_at(d: date, hour: int, now: datetime) -> datetime:
    return datetime.combine(d, time(hour), now.tzinfo)


def build(
    db: Database,
    venues: list[tuple[Venue, bool]],
    dates: list[date],
    now: datetime,
    period: str = "all",
) -> list[VenueGrid]:
    lo, hi = PERIODS.get(period, PERIODS["all"])
    grids = []
    with db.connect() as conn:
        for venue, tracked in venues:
            grid = VenueGrid(venue=venue, tracked=tracked, dates=dates, now=now)
            grids.append(grid)
            status = conn.execute(
                "SELECT * FROM provider_status WHERE venue_id = ?", (venue.id,)
            ).fetchone()
            if status:
                if status["last_ok_at"]:
                    grid.last_ok_at = datetime.fromisoformat(status["last_ok_at"])
                    grid.stale = datetime.now(UTC) - grid.last_ok_at > STALE_AFTER
                if status["consecutive_failures"]:
                    grid.last_error = status["last_error"]
            if not tracked:
                continue
            rows = conn.execute(
                "SELECT date, start, spaces, price FROM slots"
                " WHERE venue_id = ? AND date BETWEEN ? AND ?",
                (venue.id, dates[0].isoformat(), dates[-1].isoformat()),
            ).fetchall()
            agg: dict[tuple[date, int], Cell] = defaultdict(lambda: Cell("booked"))
            for r in rows:
                hour = int(r["start"][:2])
                if not lo <= hour < hi:
                    continue
                d = date.fromisoformat(r["date"])
                cell = agg[(d, hour)]
                cell.total += max(r["spaces"], 1)
                cell.free += r["spaces"]
                cell.price = cell.price or r["price"]
            for (d, hour), cell in agg.items():
                if _starts_at(d, hour, now) < now:
                    cell.state = "past"
                elif cell.free > 0:
                    cell.state = "free"
                    grid.free_total += cell.free
            grid.cells = dict(agg)
            grid.hours = sorted({h for _, h in agg})
    return grids
