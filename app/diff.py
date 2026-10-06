"""Pure availability diffing: which slots just became free since the last successful poll."""

from dataclasses import dataclass
from datetime import datetime, timedelta

from app.providers.base import Slot


@dataclass(frozen=True)
class PrevState:
    spaces: int
    free_since: str | None


def compute(
    prev: dict[str, PrevState],
    slots: list[Slot],
    now: datetime,
    *,
    baseline: bool,
    min_lead: timedelta,
) -> tuple[dict[str, PrevState], list[Slot]]:
    """Return the new state per slot key and the slots that became available.

    `baseline` is True on a venue's first successful poll: state is recorded but nothing alerts,
    otherwise a fresh deploy would report every free slot as a cancellation.
    """
    states: dict[str, PrevState] = {}
    newly: list[Slot] = []
    cutoff = now + min_lead
    for s in slots:
        before = prev.get(s.key)
        was_free = before is not None and before.spaces > 0
        if s.spaces > 0:
            free_since = before.free_since if was_free and before.free_since else now.isoformat()
            if not was_free and not baseline and s.starts_at >= cutoff:
                newly.append(s)
        else:
            free_since = None
        states[s.key] = PrevState(spaces=s.spaces, free_since=free_since)
    return states, newly
