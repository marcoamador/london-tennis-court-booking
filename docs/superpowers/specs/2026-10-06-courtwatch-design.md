# CourtWatch — London tennis court availability tracker + cancellation alerts

## Context
Marco wants a small, self-hosted app (deployable to Hetzner) that shows live tennis court
availability for four East London venues and emails him and a few friends when a slot frees up
(new release or cancellation) at venues and times they care about. Inspiration:
londontenniscourts.com (grid of slots, "click a full slot to get notified") and LayUp's
aggregation approach. The repo is empty (only LICENSE, 1 commit), so this is a greenfield build.

### Research findings (verified live on 2026-10-06)
| Venue | Booking system | Public data? | How we read it |
|---|---|---|---|
| **West Ham Park** (12 courts, no lights) | ClubSpark `WestHamPark` | ✅ no login | `GET https://clubspark.lta.org.uk/v0/VenueBooking/WestHamPark/GetVenueSessions?resourceID=&startDate=YYYY-MM-DD&endDate=YYYY-MM-DD&roleId=` → `Resources[].Days[].Sessions[]`; times are minutes from midnight; `Category 0` + `Capacity>0` = free window (split by `Interval`, 60 min), `1000` = booked, `8000` = closed |
| **Stratford Park (Newham)** | ClubSpark white-label `stratford.newhamparkstennis.org.uk`, slug `stratford_newhamparkstennis_org_uk` (⚠️ `StratfordParkTennisCourts` is Stroud's Stratford Park; `StratfordParkTennis` is a coaching provider) | ✅ no login | same endpoint; price = `Cost` (court + floodlights) |
| **Lee Valley Hockey & Tennis Centre** | Better (GLL) | ✅ no login (headers `Origin/Referer: https://bookings.better.org.uk`) | dates: `GET https://better-admin.org.uk/api/activities/venue/lee-valley-hockey-and-tennis-centre/activity-category/{slug}/dates`; slots: `.../activity/{slug}/v2/times?date=YYYY-MM-DD` → `data[]` with `starts_at.format_24_hour`, `spaces`, `price.formatted_amount`, `action_to_show.status`. Slugs: `tennis-court-outdoor`, `tennis-court-indoor` |
| **Victoria Park** | Courtside in-house (`tennistowerhamlets.com/book/courts/victoria-park`) | ❌ anonymous requests redirect to Cloudflare Turnstile `/verify-human`; robots.txt `Crawl-delay: 300` | Experimental adapter **only if** a logged-in session is served without the challenge (we never solve or evade the challenge). Otherwise: deep-link tile. Also email hello@courtside.uk asking for a feed |

### Decisions (from Marco)
- Victoria Park: try with Marco's Courtside login and fall back to a deep link.
- Notifications: **email** via **Gmail SMTP** (app password).
- Users: **Marco + a few friends**, invite-only, magic-link sign-in.
- Stack: **Python**: FastAPI + APScheduler + SQLite + Jinja2/HTMX.
- No domain yet: **sslip.io** hostname + Caddy auto-HTTPS.
- Poll every **5 min** (Courtside throttled to ≥300 s between requests).

## Architecture
One `app` container (FastAPI + in-process APScheduler poller) and one `caddy` container (TLS
reverse proxy), via `docker compose`. SQLite file on a named volume. Everything runs in Europe/London time (`zoneinfo`).

```
app/
  main.py          FastAPI app factory, lifespan starts scheduler, mounts routes
  config.py        pydantic-settings (env): SMTP_*, ADMIN_EMAIL, SECRET_KEY, BASE_URL, POLL_SECONDS, COURTSIDE_* …
  db.py            sqlite3/SQLModel engine + schema init (WAL mode)
  models.py        User, Invite, AlertRule, SlotState, AlertSent, ProviderStatus, LoginToken
  venues.py        static registry: id, name, area, provider, provider params, days_ahead, booking_url(date)
  providers/
    base.py        Slot dataclass + Provider protocol: async fetch(venue, dates) -> list[Slot]
    clubspark.py   one request per venue for the whole date range; expands free windows into hourly slots
    better.py      /dates then /v2/times per date per activity (outdoor + indoor shown as separate "sub-venues")
    courtside.py   experimental; disabled unless COURTSIDE_ENABLED=true; login with httpx, abort on /verify-human redirect
  poller.py        job: for each venue → fetch → diff vs SlotState → persist → hand newly-free slots to alerts
  diff.py          pure: (previous states, new slots) -> newly_available[]; baseline/recovery rules below
  alerts.py        match newly-free slots to rules, dedupe via AlertSent, batch into one email per user per poll
  mailer.py        aiosmtplib (smtp.gmail.com:587 STARTTLS), plain-text + simple HTML templates
  auth.py          magic links (itsdangerous, 15-min tokens, single-use), signed session cookie (30 days), invite allowlist
  routes/          pages.py (grid, venue), rules.py (CRUD + quick "notify me"), auth.py, admin.py (invites, provider health)
  templates/       Jinja2 + HTMX + Pico.css (no JS build step)
tests/             pytest + respx; fixtures/ holds recorded JSON from each provider
scripts/
  smoke.py         hits the real ClubSpark/Better endpoints once and prints parsed slots
  courtside_probe.py  Marco runs this locally with his own creds in env; reports whether logged-in pages bypass the challenge
Dockerfile, docker-compose.yml, Caddyfile, .env.example, docs/deploy-hetzner.md
```

### Core data model
- **Slot** (normalized): `venue_id, court` (court name, or `"any"` for Better pooled courts), `date, start, end, price, spaces, booking_url`. Key = `(venue_id, court, date, start)`.
- **SlotState**: last known `spaces` per key + `first_seen_free_at`.
- **AlertRule**: `user_id, venue_ids[], weekdays[], time_from, time_to, days_ahead_max (default 14), active`. A quick rule comes from clicking a booked cell (one venue, that weekday, that hour).
- **AlertSent**: `(user_id, slot_key, free_since)`, so each user gets one email per "became free" event.
- **ProviderStatus**: `venue_id, last_ok_at, last_error, consecutive_failures`.

### Availability diff rules (`diff.py`)
- A slot is **newly available** when spaces go from 0 (or unknown and booked) to >0 *and* it is in the future.
- **Baseline:** the first successful poll for a venue (fresh deploy, or a newly added venue) records state and fires no alerts.
- **Provider failures:** keep the last-good state, so a failed fetch followed by recovery doesn't look like everything just freed up.
- Ignore slots starting less than 30 min from now. Ignore `Closed` (ClubSpark 8000) and Better slots whose `action_to_show.status` isn't bookable.

### UI (inspired by londontenniscourts.com)
- **Home grid:** one card per venue, days (next 7–14) as columns and hours as rows. A cell shows free-court count (green), booked (grey) or closed (blank). Clicking a free cell opens the provider booking page for that date. Clicking a booked cell gives a "🔔 Notify me" quick rule. Filters: venue, morning/afternoon/evening, weekend only.
- Per-venue "updated X min ago" plus a stale banner if the last success is >20 min old.
- **Rules page:** list, edit and pause your alert rules.
- **Admin page** (ADMIN_EMAIL only): invite emails, view provider health, "send test email".
- Victoria Park: a live card if Courtside works, otherwise a "Check on Courtside →" deep-link card.

### Poll loop & politeness
- APScheduler `interval` job every `POLL_SECONDS=300`, `max_instances=1`, with jitter. Venues are fetched concurrently with an httpx timeout of 20 s and 2 retries with backoff.
- Request volume per poll: ClubSpark 2 requests (one per venue for the whole 14-day range) plus Better ~16 (8 days × 2 activities). That's about 18 requests every 5 minutes.
- Descriptive User-Agent (`CourtWatch/1.0 (+contact email)`).
- Courtside (if enabled) runs a separate job that fetches **one** day-page per 300 s, rotating through the 7 days with the soonest days weighted. It disables itself (and notifies admin) the moment a response redirects to `/verify-human`.

### Security / privacy
- Secrets (Gmail app password, SECRET_KEY, Courtside creds) live only in `.env` on the server, never committed. `.env.example` has placeholders.
- Invite-only sign-up, signed HttpOnly+Secure cookies, CSRF token on POST forms, rate-limited magic-link requests.
- Courtside credentials: Marco puts them in `.env` himself. I won't type or handle the password.

## Implementation steps
1. **Spec + scaffold:** write `docs/superpowers/specs/2026-10-06-courtwatch-design.md` (this design) and commit. Set up `pyproject.toml` (fastapi, uvicorn, httpx, apscheduler, jinja2, sqlmodel, pydantic-settings, itsdangerous, aiosmtplib; dev: pytest, pytest-asyncio, respx, ruff), the `app/` skeleton, and `.gitignore`.
2. **Providers (TDD with recorded fixtures):** record real JSON from the endpoints above into `tests/fixtures/`, then implement `clubspark.py` and `better.py` parsers to the `Slot` model. `scripts/smoke.py` checks them against live data.
3. **State + diff:** schema, `diff.py` with unit tests for the baseline, recovery, past-slot and spaces-change cases.
4. **Poller:** scheduler wiring, ProviderStatus tracking, concurrency, retries.
5. **Auth + mailer:** magic link, sessions, invites, Gmail SMTP. Bootstrap ADMIN_EMAIL on first start.
6. **Alerts:** rule matching, dedupe, batched email (venue, date, time, courts free, direct Book link), plus an unsubscribe/pause link.
7. **UI:** grid, venue cards, quick "notify me", rules CRUD, admin page.
8. **Victoria Park:** `scripts/courtside_probe.py`. Marco runs it with his creds. If logged-in pages are served without the challenge, implement `courtside.py` behind `COURTSIDE_ENABLED`; otherwise ship the deep-link card. Draft an email to hello@courtside.uk asking for a data feed.
9. **Deploy:** Dockerfile (python:3.12-slim, non-root), `docker-compose.yml` (app + caddy, volumes `data`, `caddy_data`), Caddyfile using `{$SITE_HOST}` (e.g. `5-75-1-2.sslip.io`). `docs/deploy-hetzner.md` covers: create a CX22 running Ubuntu 24.04 → install Docker → `git clone` → `cp .env.example .env` and fill it in → `docker compose up -d`. Also covers updates (`git pull && docker compose up -d --build`) and SQLite backup (nightly `sqlite3 .backup` cron or Hetzner backups).

## Verification
- `pytest`: parsers against fixtures, diff/alert unit tests, auth flow tests with an SMTP stub (aiosmtpd/in-memory mailer).
- `python scripts/smoke.py`: real slots for West Ham Park, Stratford Park and Lee Valley, cross-checked by eye against the providers' booking pages in the browser pane.
- Local `docker compose up` (with `SITE_HOST=localhost`): open the grid in the browser pane, sign in via the magic link (mail shown in the console in dev mode), create a rule, then inject a fake "freed" slot via a dev-only fixture provider and confirm one email arrives with no duplicate on the next poll.
- After deploying to Hetzner: HTTPS works on the sslip.io host, the provider health page shows all green after 10 min, and the admin "send test email" reaches Marco's Gmail.

## Server
- Hetzner IP **94.130.138.168** → `SITE_HOST=94-130-138-168.sslip.io`, `BASE_URL=https://94-130-138-168.sslip.io`.

## What Marco does himself
- **Gmail app password:** the one pasted in chat must be revoked. Marco creates a new one and puts it in the server `.env` as `SMTP_PASSWORD`. `.env.example` only ever holds placeholders.
- **Courtside account:** Courtside only creates an account on a first booking. So **v1 ships Victoria Park as a deep-link card** ("Check on Courtside →", linking to the right date). Step 8 is reduced to: write `scripts/courtside_probe.py` + a disabled `courtside.py` stub, and draft the email to hello@courtside.uk. When Marco next books Victoria Park (which creates his account), he runs the probe with `COURTSIDE_EMAIL/COURTSIDE_PASSWORD` in his local env and shares only the result (challenged / not challenged). If not challenged, enable the adapter.

## Changes during implementation (2026-10-06)
- Stratford Park corrected to Newham's ClubSpark venue (see table above).
- The dev-only fake provider was removed. Alert flow is covered by tests with stub fetchers instead.
- UI: venue tabs (All venues + one per venue, with free counts). "All venues" shows collapsible cards,
  and the collapsed state is remembered per browser. Styling follows londontenniscourts.com: green
  cells with court counts, red "–" for fully booked (click to watch).
- Victoria Park ships as a deep-link card. `scripts/courtside_probe.py` and `docs/courtside.md` cover next steps.
