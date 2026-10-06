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

Create a non-root `deploy` user that owns the app and can run Docker (GitHub Actions will log in
as this user):

```bash
adduser --disabled-password --gecos "" deploy
usermod -aG docker deploy
git clone https://github.com/marcoamador/london-tennis-court-booking.git /opt/courtwatch
chown -R deploy:deploy /opt/courtwatch
su - deploy
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

As the `deploy` user:

```bash
cd /opt/courtwatch
./scripts/deploy.sh
docker compose logs -f app
```

You should see `Polled west-ham-park: … slots` lines within a minute. Then open
https://94-130-138-168.sslip.io, sign in with `ADMIN_EMAIL`, go to **Admin**, and click
**Send me a test email** to check Gmail delivery.

## 4. Invite friends

Admin → *Invite a friend* → they sign in at `/login` with that email.

## 5. Automatic deploys with GitHub Actions

`.github/workflows/deploy.yml` runs on every push to `main` (or manually via *Actions → Deploy →
Run workflow*). It runs the tests, SSHes to the server, runs `scripts/deploy.sh <commit>` (fetch,
check out exactly that commit, `docker compose up -d --build`), then waits for
`https://94-130-138-168.sslip.io/healthz` to respond.

### a. Create a deploy key (on your own machine)

```bash
ssh-keygen -t ed25519 -N "" -C "github-actions-courtwatch" -f courtwatch_deploy
```

This gives you `courtwatch_deploy` (private, goes into GitHub) and `courtwatch_deploy.pub` (public,
goes onto the server).

### b. Authorise it on the server, locked to the deploy script

As root on the server, paste the **public** key into this line in place of `ssh-ed25519 AAAA...`:

```bash
mkdir -p /home/deploy/.ssh
echo 'command="/opt/courtwatch/scripts/deploy.sh",no-port-forwarding,no-X11-forwarding,no-agent-forwarding,no-pty ssh-ed25519 AAAA... github-actions-courtwatch' >> /home/deploy/.ssh/authorized_keys
chown -R deploy:deploy /home/deploy/.ssh && chmod 700 /home/deploy/.ssh && chmod 600 /home/deploy/.ssh/authorized_keys
```

The `command=` prefix means this key can **only** run the deploy script, which accepts nothing but
a commit SHA that is already on `origin/main`. A leaked key can redeploy your own code, nothing
else.

### c. Add the secrets in GitHub

Repo → *Settings → Environments → New environment* `production`. Then add:

| Kind | Name | Value |
|---|---|---|
| Secret | `DEPLOY_SSH_KEY` | full contents of the **private** key file `courtwatch_deploy` |
| Secret | `DEPLOY_HOST` | `94.130.138.168` |
| Secret | `DEPLOY_USER` | `deploy` |
| Secret | `DEPLOY_KNOWN_HOSTS` | output of `ssh-keyscan -t ed25519 94.130.138.168` (pins the server's identity) |
| Variable | `SITE_HOST` | `94-130-138-168.sslip.io` |

Optionally add yourself as a *required reviewer* on the environment, so each deploy waits for your
click. Then delete the local private key file.

### d. Try it

*Actions → Deploy → Run workflow*. The log ends with `Deployed <sha>` and `Healthy`.

## Updating by hand

```bash
su - deploy -c "/opt/courtwatch/scripts/deploy.sh"
```

This deploys the latest `origin/main`. Don't use `git pull` here, since deploys leave the checkout on a
specific commit.

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
