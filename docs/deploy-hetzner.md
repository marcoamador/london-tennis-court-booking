# Deploying CourtWatch to Hetzner

The server runs two containers via Docker Compose: `app` (FastAPI + the 5-minute poller) and
`caddy` (HTTPS reverse proxy with automatic Let's Encrypt certificates). Data lives in a SQLite
file on a Docker volume.

Server: **94.130.138.168** → `https://94-130-138-168.sslip.io` (sslip.io resolves that name to the IP,
so no domain is needed).

## 1. Server prerequisites (once)

A Hetzner CX22 (or similar) with Ubuntu 24.04. SSH in as root:

```bash
ssh root@94.130.138.168
```

Install Docker and open the firewall:

```bash
curl -fsSL https://get.docker.com | sh
ufw allow OpenSSH && ufw allow 80 && ufw allow 443 && ufw --force enable
```

If you use a Hetzner Cloud Firewall, allow inbound TCP 22, 80, 443 (and UDP 443) there too.

## 2. Get the code and configure

```bash
git clone https://github.com/marcoamador/london-tennis-court-booking.git /opt/courtwatch
cd /opt/courtwatch
cp .env.example .env
nano .env
```

Fill in at least:

| Variable | Value |
|---|---|
| `SITE_HOST` | `94-130-138-168.sslip.io` |
| `BASE_URL` | `https://94-130-138-168.sslip.io` |
| `SECRET_KEY` | output of `python3 -c "import secrets; print(secrets.token_urlsafe(48))"` |
| `ADMIN_EMAIL` | your email |
| `SMTP_USERNAME` / `MAIL_FROM` | your Gmail address |
| `SMTP_PASSWORD` | a **new** Gmail app password (https://myaccount.google.com/apppasswords) |
| `CONTACT_EMAIL` | your email (sent in the User-Agent so venues can reach you) |

```bash
chmod 600 .env
```

## 3. Start

```bash
docker compose up -d --build
docker compose logs -f app
```

You should see `Polled west-ham-park: … slots` lines within a minute. Then open
https://94-130-138-168.sslip.io, sign in with `ADMIN_EMAIL`, go to **Admin**, and click
**Send me a test email** to check Gmail delivery.

## 4. Invite friends

Admin → *Invite a friend* → they sign in at `/login` with that email.

## Updating

```bash
cd /opt/courtwatch && git pull && docker compose up -d --build
```

## Backups

```bash
chmod +x scripts/backup.sh
(crontab -l 2>/dev/null; echo "30 3 * * * cd /opt/courtwatch && ./scripts/backup.sh >> backups/backup.log 2>&1") | crontab -
```

Hetzner's server backups (+20% of the server price) are a good second layer.

## Troubleshooting

- **Certificate errors**: ports 80/443 must be reachable from the internet; check `docker compose logs caddy`.
- **No emails**: Admin page shows "console mode" if `SMTP_PASSWORD` is empty. Gmail needs 2-step verification enabled to create app passwords.
- **A venue shows "provider issue"**: Admin → Providers shows the last error. The previous snapshot is kept, so a temporary outage won't trigger false alerts.
