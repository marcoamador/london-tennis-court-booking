"""Match newly freed slots against users' alert rules and send one batched email per user."""

import logging
from collections import defaultdict
from dataclasses import dataclass
from datetime import time
from html import escape

from app.auth import pause_token, utcnow
from app.config import Settings
from app.db import Database
from app.mailer import Mailer
from app.providers.base import Slot
from app.venues import get_venue

log = logging.getLogger(__name__)

WEEKDAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


@dataclass(frozen=True)
class Rule:
    id: int
    user_id: int
    venue_ids: frozenset[str]
    weekdays: frozenset[int]
    time_from: time
    time_to: time

    @classmethod
    def from_row(cls, row) -> "Rule":
        return cls(
            id=row["id"],
            user_id=row["user_id"],
            venue_ids=frozenset(v for v in row["venue_ids"].split(",") if v),
            weekdays=frozenset(int(d) for d in row["weekdays"].split(",") if d != ""),
            time_from=time.fromisoformat(row["time_from"]),
            time_to=time.fromisoformat(row["time_to"]),
        )

    def matches(self, slot: Slot) -> bool:
        return (
            slot.venue_id in self.venue_ids
            and slot.date.weekday() in self.weekdays
            and self.time_from <= slot.start < self.time_to
        )


@dataclass(frozen=True)
class FreedSlot:
    slot: Slot
    free_since: str


def _group(freed: list[FreedSlot]) -> dict[tuple, list[FreedSlot]]:
    """Group per venue/date/start so 3 free courts at 18:00 become one line."""
    groups: dict[tuple, list[FreedSlot]] = defaultdict(list)
    for f in sorted(freed, key=lambda f: (f.slot.date, f.slot.start, f.slot.venue_id)):
        groups[(f.slot.venue_id, f.slot.date, f.slot.start, f.slot.end)].append(f)
    return groups


def render_email(settings: Settings, user_id: int, freed: list[FreedSlot]) -> tuple[str, str, str]:
    groups = _group(freed)
    lines, rows = [], []
    for (venue_id, d, start, end), items in groups.items():
        venue = get_venue(venue_id)
        name = venue.name if venue else venue_id
        url = venue.booking_url(d) if venue else settings.base_url
        courts = sum(i.slot.spaces for i in items)
        price = items[0].slot.price or ""
        when = f"{d:%a %d %b} {start:%H:%M}–{end:%H:%M}"
        label = f"{courts} court{'s' if courts != 1 else ''}"
        lines.append(f"• {name} — {when} — {label} {price}\n  Book: {url}")
        rows.append(
            f"<tr><td><b>{escape(name)}</b></td><td>{escape(when)}</td>"
            f"<td>{escape(label)} {escape(price)}</td>"
            f'<td><a href="{escape(url)}">Book →</a></td></tr>'
        )
    first_venue = get_venue(next(iter(groups))[0])
    subject = f"🎾 {len(groups)} slot{'s' if len(groups) != 1 else ''} just opened up"
    if first_venue:
        subject += f" — {first_venue.name}" + (" and more" if len(groups) > 1 else "")
    pause_url = f"{settings.base_url}/alerts/pause?token={pause_token(settings, user_id)}"
    manage_url = f"{settings.base_url}/alerts"
    text = (
        "These slots just became available:\n\n"
        + "\n".join(lines)
        + f"\n\nManage alerts: {manage_url}\nPause all alerts: {pause_url}\n"
    )
    html = (
        "<p>These slots just became available:</p>"
        '<table cellpadding="6" style="border-collapse:collapse">' + "".join(rows) + "</table>"
        f'<p style="color:#666;font-size:13px"><a href="{escape(manage_url)}">Manage alerts</a>'
        f' · <a href="{escape(pause_url)}">Pause all alerts</a></p>'
    )
    return subject, text, html


async def dispatch(db: Database, mailer: Mailer, settings: Settings, freed: list[FreedSlot]) -> int:
    """Email every user whose active rules match newly freed slots. Returns emails sent."""
    if not freed:
        return 0
    with db.connect() as conn:
        users = {
            r["id"]: r["email"]
            for r in conn.execute("SELECT id, email FROM users WHERE alerts_paused = 0")
        }
        rules = [
            Rule.from_row(r)
            for r in conn.execute("SELECT * FROM alert_rules WHERE active = 1")
            if r["user_id"] in users
        ]
    rules_by_user: dict[int, list[Rule]] = defaultdict(list)
    for rule in rules:
        rules_by_user[rule.user_id].append(rule)

    sent = 0
    for user_id, user_rules in rules_by_user.items():
        matched = [f for f in freed if any(r.matches(f.slot) for r in user_rules)]
        if not matched:
            continue
        with db.connect() as conn:
            fresh = [
                f
                for f in matched
                if not conn.execute(
                    "SELECT 1 FROM alerts_sent WHERE user_id = ? AND slot_key = ? AND free_since = ?",
                    (user_id, f.slot.key, f.free_since),
                ).fetchone()
            ]
        if not fresh:
            continue
        subject, text, html = render_email(settings, user_id, fresh)
        try:
            await mailer.send(users[user_id], subject, text, html)
        except Exception:
            log.exception("Failed to send alert email to user %s", user_id)
            continue
        with db.connect() as conn:
            conn.executemany(
                "INSERT OR IGNORE INTO alerts_sent (user_id, slot_key, free_since, sent_at) "
                "VALUES (?, ?, ?, ?)",
                [(user_id, f.slot.key, f.free_since, utcnow()) for f in fresh],
            )
        sent += 1
    return sent
