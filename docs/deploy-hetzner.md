# Deploying CourtWatch to Hetzner

The app runs as one Docker Compose container (`app`: FastAPI plus the 5-minute poller) listening only
on `127.0.0.1:8000`. A reverse proxy in front provides HTTPS:

- **Host nginx** (this server already runs nginx on ports 80/443): nginx forwards
  `94-130-138-168.sslip.io` to the app and certbot handles the certificate. Your other nginx sites
  are untouched. This is the path below.
- **Optional Caddy container**, for a server with nothing on 80/443: set `COMPOSE_PROFILES=caddy`
  in `.env` and skip the nginx step.

Data lives in a SQLite file on a Docker volume.

Server: **94.130.138.168** → `https://94-130-138-168.sslip.io` (sslip.io resolves that name to the IP,
so no domain is needed).

## 1. Server prerequisites (once)

Ubuntu 22.04/24.04 with Docker and the Compose plugin (`docker compose version`). SSH in as root:

```bash
ssh root@94.130.138.168
```

Firewall: ports 22, 80 and 443 must be reachable. ufw is inactive on this server, so only check
the Hetzner Cloud Console → *Firewalls*: if one is attached, allow inbound TCP 22, 80 and 443.
Nothing new needs opening for the app itself, because it only listens on localhost.

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

Port 8000 on localhost must be free (`ss -tlnp | grep ':8000'` prints nothing). If it isn't, set
`APP_PORT=8001` (or similar) in `.env` and use that port in the nginx config.

## 3. Start the app

As the `deploy` user:

```bash
cd /opt/courtwatch
./scripts/deploy.sh
docker compose logs -f app
```

You should see `Polled west-ham-park: … slots` lines within a minute. Check it answers locally:

```bash
curl -s http://127.0.0.1:8000/healthz
```

## 4. Put it behind nginx with HTTPS

As root (`exit` back from the deploy user):

```bash
cp /opt/courtwatch/deploy/nginx/courtwatch.conf /etc/nginx/sites-available/courtwatch
ln -s /etc/nginx/sites-available/courtwatch /etc/nginx/sites-enabled/courtwatch
nginx -t && systemctl reload nginx
```

Then get the certificate. certbot edits the nginx file to add HTTPS and an HTTP→HTTPS redirect, and
renews automatically:

```bash
certbot --version || apt install -y certbot python3-certbot-nginx
certbot --nginx -d 94-130-138-168.sslip.io
```

Open https://94-130-138-168.sslip.io, sign in with `ADMIN_EMAIL`, go to **Admin**, and click
**Send me a test email** to check Gmail delivery.

## 5. Invite friends

Admin → *Invite a friend* → they sign in at `/login` with that email.

## 6. Automatic deploys with GitHub Actions

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

- **502 Bad Gateway** from nginx: the app isn't up. Check `docker compose ps` and `docker compose logs app` in `/opt/courtwatch`, and `curl http://127.0.0.1:8000/healthz`.
- **certbot fails**: port 80 must be reachable from the internet (Hetzner firewall), and `nginx -t` must pass.
- **No emails**: Admin page shows "console mode" if `SMTP_PASSWORD` is empty. Gmail needs 2-step verification enabled to create app passwords.
- **A venue shows "provider issue"**: Admin → Providers shows the last error. The previous snapshot is kept, so a temporary outage won't trigger false alerts.
