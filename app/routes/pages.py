from datetime import datetime, timedelta
from urllib.parse import urlencode

from fastapi import APIRouter, Request

from app import grid
from app.auth import current_user
from app.config import LONDON
from app.main import templates
from app.poller import tracked_venues
from app.venues import VENUES, get_venue

router = APIRouter()

ALL = "all"
DAY_CHOICES = (7, 14)
PERIOD_LABELS = {
    "all": "All day",
    "morning": "Morning",
    "afternoon": "Afternoon",
    "evening": "Evening",
}


def _parse_days(raw: str | None) -> int:
    try:
        return max(1, min(14, int(raw))) if raw else 7
    except ValueError:
        return 7


def filter_url(venue: str, days: int, period: str, weekend: bool, prefix: str = "") -> str:
    """Home URL for a filter combination; defaults are left out so links never carry empty params."""
    params: list[tuple[str, str]] = []
    if venue != ALL:
        params.append(("venue", venue))
    if days != 7:
        params.append(("days", str(days)))
    if period != "all":
        params.append(("period", period))
    if weekend:
        params.append(("weekend", "1"))
    return f"{prefix}/?" + urlencode(params) if params else f"{prefix}/"


def hour_label(hour: int) -> str:
    suffix = "AM" if hour < 12 else "PM"
    return f"{(hour % 12) or 12} {suffix}"


def _free_counts(db, dates, now) -> dict[str, int]:
    """Free court-hours per venue over the shown dates, for the venue tabs."""
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT venue_id, date, start, spaces FROM slots"
            " WHERE spaces > 0 AND date BETWEEN ? AND ?",
            (dates[0].isoformat(), dates[-1].isoformat()),
        ).fetchall()
    shown = {d.isoformat() for d in dates}
    today, hour = now.date().isoformat(), now.hour
    counts: dict[str, int] = {}
    for r in rows:
        if r["date"] not in shown or (r["date"] == today and int(r["start"][:2]) <= hour):
            continue
        counts[r["venue_id"]] = counts.get(r["venue_id"], 0) + r["spaces"]
    return counts


@router.get("/")
def index(
    request: Request,
    venue: str | None = None,
    days: str | None = None,
    period: str | None = None,
    weekend: str | None = None,
):
    settings = request.app.state.settings
    db = request.app.state.db
    user = current_user(request)
    current = get_venue(venue or "")  # None = all venues
    days_n = _parse_days(days)
    period = period if period in grid.PERIODS else "all"
    weekend_on = weekend not in (None, "", "0", "false")

    now = datetime.now(LONDON)
    dates = [now.date() + timedelta(days=i) for i in range(days_n)]
    if weekend_on:
        dates = [d for d in dates if d.weekday() >= 5] or dates
    tracked = {v.id for v in tracked_venues(settings)}
    shown = [current] if current else VENUES
    grids = grid.build(db, [(v, v.id in tracked) for v in shown], dates, now, period)

    watched = set()
    if user:
        with db.connect() as conn:
            for r in conn.execute(
                "SELECT venue_ids, weekdays, time_from FROM alert_rules"
                " WHERE user_id = ? AND active = 1",
                (user["id"],),
            ):
                for vid in r["venue_ids"].split(","):
                    for wd in r["weekdays"].split(","):
                        watched.add((vid, int(wd), int(r["time_from"][:2])))

    def link(**overrides) -> str:
        state = {
            "venue": current.id if current else ALL,
            "days": days_n,
            "period": period,
            "weekend": weekend_on,
        }
        state.update(overrides)
        return filter_url(**state, prefix=settings.prefix)

    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "user": user,
            "grids": grids,
            "venue": current,
            "all_id": ALL,
            "venues": VENUES,
            "tracked": tracked,
            "free_counts": _free_counts(db, dates, now),
            "days": days_n,
            "day_choices": DAY_CHOICES,
            "period": period,
            "period_labels": PERIOD_LABELS,
            "weekend": weekend_on,
            "watched": watched,
            "link": link,
            "hour_label": hour_label,
        },
    )
