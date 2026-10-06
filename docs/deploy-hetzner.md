# Deploying CourtWatch to Hetzner

The app runs as one Docker Compose container (`app`: FastAPI plus the 5-minute poller) listening only
on `127.0.0.1:8000`. A reverse proxy in front provides HTTPS:

- **Host nginx** (this server already runs nginx on ports 80/443), either:
  - **4a. as a subpath** of a site nginx already serves, e.g. `https://your-host/tennis/` next to
    `/stocks`. This reuses that site's certificate, so it's the simplest option. Or:
  - **4b. as its own hostname** `94-130-138-168.sslip.io`, with a new certbot certificate.

  Either way your other nginx sites are untouched.
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

Pick the Linux user that will own and run the app. GitHub Actions will log in as this user to deploy.

- **Your own login user** (simplest). It needs to run Docker without `sudo`: check that `docker ps`
  works. If you get "permission denied", run `sudo usermod -aG docker $USER`, then log out and back in.
- **Or a dedicated `deploy` user**, which keeps the app separate from your account:
  ```bash
  sudo adduser --disabled-password --gecos "" deploy
  sudo usermod -aG docker deploy
  ```

Clone the code and give that user ownership. Replace `<app-user>` with your username or `deploy`:

```bash
sudo git clone https://github.com/marcoamador/london-tennis-court-booking.git /opt/courtwatch
sudo chown -R <app-user>:<app-user> /opt/courtwatch
```

Then, **as that user** (`sudo -iu deploy` if you chose the dedicated user):

```bash
cd /opt/courtwatch
cp .env.example .env
nano .env
```

Fill in at least:

| Variable | Value |
|---|---|
| `SITE_HOST` | `94-130-138-168.sslip.io` |
| `BASE_URL` | public URL incl. any subpath: `https://your-host/tennis` (4a) or `https://94-130-138-168.sslip.io` (4b) |
| `ROOT_PATH` | `/tennis` for 4a, empty for 4b |
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

As the app user:

```bash
cd /opt/courtwatch
./scripts/deploy.sh
docker compose logs -f app
```

You should see `Polled west-ham-park: … slots` lines within a minute. Check it answers locally:

```bash
curl -s http://127.0.0.1:8000/healthz
```

## 4a. nginx: serve under a subpath (e.g. `/tennis`)

In `/opt/courtwatch/.env` set (replace `your-host` with the hostname your `/stocks` app uses):

```bash
ROOT_PATH=/tennis
BASE_URL=https://your-host/tennis
```

and re-run `./scripts/deploy.sh` as the app user. Then, as root, find the site that serves `/stocks`:

```bash
sudo nginx -T 2>/dev/null | grep -nE "^# configuration file|stocks"
```

`nginx -T` prints the configuration nginx is actually running, with a `# configuration file /path:`
header before each file. The header just above the `stocks` match is the file to edit. Grepping
`/etc/nginx/sites-enabled/` directly can miss it, because that folder usually holds symlinks, which
`grep -r` skips.

**If your nginx loads per-app snippet files** (e.g. the match is in `/etc/nginx/apps/stocks.conf`
and a server block has `include /etc/nginx/apps/*.conf;`), the repo file can be copied as one of
them, with no edits to existing files:

```bash
sudo cp /opt/courtwatch/deploy/nginx/courtwatch-subpath.conf /etc/nginx/apps/courtwatch.conf
```

**Otherwise**, open that file and paste the two `location` blocks from
`/opt/courtwatch/deploy/nginx/courtwatch-subpath.conf` into its `server { ... }` block, the one with
`listen 443 ssl`, next to the `/stocks` location. Then:

```bash
nginx -t && systemctl reload nginx
```

Open `https://your-host/tennis/`. No new certificate is needed.

## 4b. nginx: serve on its own hostname

As root (or with `sudo`):

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

`.github/workflows/deploy.yml` runs on every push to `main`, or manually via *Actions → Deploy →
Run workflow*. It:

1. runs the tests,
2. logs in to the server over SSH as the app user and runs `scripts/deploy.sh <commit>`, which
   fetches, checks out exactly the tested commit and runs `docker compose up -d --build`,
3. waits for `$APP_URL/healthz` to answer.

For step 2, GitHub needs an SSH key it can use to log in. You'll make a **new key just for GitHub**
rather than reusing your personal one:

- A key stored in GitHub is only as safe as GitHub's secret storage. With a dedicated key you can
  lock it so it can **only run the deploy script**, never open a shell.
- You can revoke it any time by deleting one line on the server, and your own login is unaffected.
- Your personal key stays only on your PC.

An SSH key is a **pair** of files:

| File | What it is | Where it goes |
|---|---|---|
| `courtwatch_deploy` | **private** key, the secret half | GitHub secret `DEPLOY_SSH_KEY` (then delete it from your PC) |
| `courtwatch_deploy.pub` | **public** key, safe to share | the server, in the app user's `~/.ssh/authorized_keys` |

### 6.1 Create the key on your PC

Open **PowerShell** on Windows (Terminal on macOS/Linux works the same). `ssh-keygen` is built into
Windows 10/11:

```powershell
ssh-keygen -t ed25519 -C "github-actions-courtwatch" -f "$HOME\.ssh\courtwatch_deploy"
```

When it asks *Enter passphrase*, press **Enter twice** to leave it empty. GitHub Actions can't type a
passphrase. The key is protected by GitHub's secret storage and by the server-side lock in 6.3.

Check that both files exist:

```powershell
Get-ChildItem "$HOME\.ssh\courtwatch_deploy*"
```

You should see `courtwatch_deploy` and `courtwatch_deploy.pub`.

### 6.2 Copy the public key

```powershell
Get-Content "$HOME\.ssh\courtwatch_deploy.pub"
```

It prints one line like `ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAA... github-actions-courtwatch`. Copy the
whole line.

### 6.3 Install it on the server, locked to the deploy script

SSH in as the app user and open the list of keys allowed to log in. For the dedicated `deploy` user,
see the note further down.

```bash
mkdir -p ~/.ssh && chmod 700 ~/.ssh
nano ~/.ssh/authorized_keys
```

Add a **new line** at the end: this prefix, a space, then the public key line you copied:

```
command="/opt/courtwatch/scripts/deploy.sh",no-port-forwarding,no-X11-forwarding,no-agent-forwarding,no-pty ssh-ed25519 AAAAC3Nza... github-actions-courtwatch
```

Save (Ctrl+O, Enter, Ctrl+X), then fix the permissions. SSH ignores the file if others can write to it.

```bash
chmod 600 ~/.ssh/authorized_keys
```

> ⚠️ **Don't touch the other lines.** If you log in with a key, your own key is already in this file.
> Leave it exactly as it is, and never put `command=...` in front of it, or your own login would
> only run the deploy script. Keep your current SSH session open until you've confirmed, from a
> second terminal, that you can still log in.

What the prefix does: whenever someone logs in with **this** key, the server ignores whatever they
asked to run and runs `deploy.sh` instead. The script only reads a commit SHA, and only deploys a
commit that is already on `origin/main`. So even if this key leaked, it could only redeploy your own
code. `no-pty` and the other options block interactive shells and tunnels.

**Using the dedicated `deploy` user?** It has no password, so add the line as root instead:

```bash
sudo mkdir -p /home/deploy/.ssh
sudo nano /home/deploy/.ssh/authorized_keys
sudo chown -R deploy:deploy /home/deploy/.ssh
sudo chmod 700 /home/deploy/.ssh && sudo chmod 600 /home/deploy/.ssh/authorized_keys
```

**App not in `/opt/courtwatch`?** Use your path in `command="..."`, and set the GitHub variable
`DEPLOY_PATH` (6.5) to the same folder.

### 6.4 Test the key from your PC

Replace `<app-user>` with the user from step 2:

```powershell
ssh -i "$HOME\.ssh\courtwatch_deploy" <app-user>@94.130.138.168
```

If SSH asks you to confirm the server's fingerprint, type `yes`. Instead of a shell you should see
the deploy run and end with `==> Deployed <sha>`, possibly after a `PTY allocation request failed`
line, which is expected. That proves the key works **and** can't get a shell. Running it again is
harmless: it just redeploys the latest `main`.

### 6.5 Add the secrets to GitHub

GitHub also needs the server's public fingerprint, so it can check it's really talking to your
server. In PowerShell:

```powershell
ssh-keyscan -t ed25519 94.130.138.168
```

It prints one line starting with `94.130.138.168 ssh-ed25519 AAAA...`. Optionally confirm it's genuine:
these two commands should print the same `SHA256:...` fingerprint. The first runs on your PC, the
second on the server:

```powershell
ssh-keyscan -t ed25519 94.130.138.168 | ssh-keygen -lf -
```

```bash
ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub
```

Now in GitHub, open the repo → **Settings** → **Environments** → **New environment**, name it
`production`, and click **Configure environment**.

Under **Environment secrets → Add environment secret**, add:

| Name | Value |
|---|---|
| `DEPLOY_SSH_KEY` | the **private** key. Copy it with `Get-Content "$HOME\.ssh\courtwatch_deploy" -Raw \| Set-Clipboard` and paste. It must include the `-----BEGIN OPENSSH PRIVATE KEY-----` and `-----END OPENSSH PRIVATE KEY-----` lines. |
| `DEPLOY_HOST` | `94.130.138.168` |
| `DEPLOY_USER` | the app user from step 2 (your username, or `deploy`) |
| `DEPLOY_KNOWN_HOSTS` | the full line printed by `ssh-keyscan -t ed25519 94.130.138.168` |

Under **Environment variables → Add environment variable**, add:

| Name | Value |
|---|---|
| `APP_URL` | the app's public URL, no trailing slash: `https://your-host/tennis` (4a) or `https://94-130-138-168.sslip.io` (4b) |
| `DEPLOY_PATH` | *(optional)* only if the app isn't in `/opt/courtwatch` |

Optional: under **Deployment protection rules**, tick **Required reviewers** and add yourself. Each
deploy then waits for your approval in the Actions tab.

### 6.6 Run it, then remove the private key from your PC

Go to **Actions → Deploy → Run workflow**. The log ends with `==> Deployed <sha>` and `Healthy`. From
now on every push to `main` deploys automatically.

Once that works, delete the private key from your PC. GitHub has its copy, and you can always make a
new key:

```powershell
Remove-Item "$HOME\.ssh\courtwatch_deploy"
```

### Revoking or replacing the key

- **Revoke:** delete the `github-actions-courtwatch` line from the app user's
  `~/.ssh/authorized_keys`. GitHub can no longer log in, and nothing else changes.
- **Replace:** repeat 6.1 to 6.5 with a new key, and update the `DEPLOY_SSH_KEY` secret.

## Updating by hand

As the app user:

```bash
/opt/courtwatch/scripts/deploy.sh
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
