# 🎾 CourtWatch

Tennis court availability for East London public courts, with email alerts when a slot frees up
(cancellations or newly released days). Inspired by [londontenniscourts.com](https://www.londontenniscourts.com/).

| Venue | Booking system | Tracked |
|---|---|---|
| West Ham Park (12 courts) | ClubSpark `WestHamPark` | ✅ |
| Stratford Park, Newham (6 courts) | ClubSpark `stratford_newhamparkstennis_org_uk` | ✅ |
| Lee Valley Hockey & Tennis Centre (indoor + outdoor) | Better | ✅ |
| Victoria Park | Courtside (tennistowerhamlets.com) | ❌ link only, see [docs/courtside.md](docs/courtside.md) |

## How it works

- A poller fetches every tracked venue every 5 minutes (about 18 polite requests in total) and stores a
  snapshot in SQLite.
- Each snapshot is diffed against the previous one. A slot that goes from booked to free, or a newly
  released day, is matched against users' alert rules, and each user gets one batched email.
- The first poll after a deploy only records a baseline. Provider outages keep the last good
  snapshot, so recoveries don't send floods of false alerts.
- The web UI shows all venues as collapsible cards or one per tab. Click a green cell to book, or a red
  one to be emailed when it frees up.
- Sign-in is invite-only, by magic link. The admin invites friends from `/admin`.

## Run locally

```bash
uv sync
cp .env.example .env    # set BASE_URL=http://localhost:8000, ADMIN_EMAIL, MAIL_CONSOLE=true
uv run uvicorn app.main:app --reload
```

With `MAIL_CONSOLE=true` (or no `SMTP_PASSWORD`), emails, including sign-in links, are printed
to the log.

```bash
uv run pytest                    # tests
uv run python -m scripts.smoke   # fetch live availability once and print it
```

## Deploy

See [docs/deploy-hetzner.md](docs/deploy-hetzner.md): Docker Compose, behind the server's existing
nginx (or an optional Caddy container), with HTTPS on `94-130-138-168.sslip.io`. After a one-time setup, every push to `main` is tested and deployed by
GitHub Actions (`.github/workflows/deploy.yml`). PRs and other branches run CI only.
