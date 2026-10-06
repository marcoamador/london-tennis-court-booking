from dataclasses import dataclass
from datetime import date, datetime, time

from app.config import LONDON


class ProviderError(Exception):
    """A provider could not return trustworthy availability for a venue."""


@dataclass(frozen=True)
class Slot:
    venue_id: str
    court: str
    date: date
    start: time
    end: time
    spaces: int
    price: str | None = None

    @property
    def key(self) -> str:
        return f"{self.venue_id}|{self.court}|{self.date.isoformat()}|{self.start:%H:%M}"

    @property
    def starts_at(self) -> datetime:
        return datetime.combine(self.date, self.start, tzinfo=LONDON)


def minutes_to_time(minutes: int) -> time:
    minutes = min(minutes, 24 * 60 - 1)
    return time(minutes // 60, minutes % 60)
