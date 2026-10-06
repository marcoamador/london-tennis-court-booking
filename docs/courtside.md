# Victoria Park (Courtside)

Victoria Park courts are booked through Courtside's own site, tennistowerhamlets.com. Unlike
ClubSpark and Better, it doesn't expose availability publicly:

- Anonymous requests are redirected to a Cloudflare Turnstile "verify you're human" page.
- `robots.txt` asks crawlers for a 300-second crawl delay.

CourtWatch never tries to solve or get around that check. For now the Victoria Park card links straight to
the booking page instead of showing a grid.

## Option 1: check whether a logged-in session is challenged

Courtside creates your account when you first book. Once you have one, run this on your own
machine:

```bash
COURTSIDE_EMAIL=you@example.com COURTSIDE_PASSWORD=... uv run python -m scripts.courtside_probe
```

It prints a single verdict line. Only **NOT CHALLENGED** makes a tracker possible. That would be
implemented in `app/providers/courtside.py`, enabled with `COURTSIDE_ENABLED=true`, and limited to
one request every 5 minutes.

## Option 2: ask Courtside for a feed (draft email)

> **To:** hello@courtside.uk
> **Subject:** Read-only availability feed for Victoria Park courts?
>
> Hi Courtside team,
>
> I play regularly at Victoria Park and run a small, non-commercial tool for myself and a few
> friends. It shows free court slots across a handful of East London venues and emails us when
> one frees up, which tends to fill cancellations quickly. ClubSpark and Better venues expose
> availability we can read politely, about once every 5 minutes.
>
> Would you be open to giving read-only access to Victoria Park's availability, either via an
> API/OpenActive feed or an approved polling arrangement? I'm happy to stay well within any rate
> you set and to link every slot straight to your booking page, so all bookings still go through
> you.
>
> Thanks,
> Marco
