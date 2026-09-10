# Deploying the daemon next to the existing super-app stack

Target: the same Ubuntu box that runs `/opt/super-app` (Caddy + Postgres + API).
The daemon is one more container on that stack's network, reachable at
`https://<domain>/muse/`.

## 1. Sync the code

```bash
rsync -az --delete -e "ssh -i ~/.ssh/superapp.pem" \
  --exclude .venv --exclude .git --exclude .env --exclude apps/mobile/node_modules \
  --exclude reference --exclude '__pycache__' \
  ./ ubuntu@<host>:/opt/super-app-v2/
```

## 2. `/opt/super-app-v2/.env` (never committed)

```bash
META_API_KEY=...                       # Meta Model API, Standard tier
MODEL=muse-spark-1.3
SUPERAPP_API_TOKEN=<openssl rand -hex 24>      # what the phone app signs in with
SUPERAPP_INTERNAL_TOKEN=<openssl rand -hex 24> # daemon <-> connector CLIs
SUPERAPP_PUBLIC_URL=https://<domain>/muse
SUPERAPP_GOOGLE_REDIRECT_URI=https://<domain>/muse/v1/gmail/callback
SUPERAPP_GOOGLE_SIGNIN_REDIRECT_URI=https://<domain>/muse/v1/auth/google/callback
SUPERAPP_GMAIL_SCOPE_TIER=modify
SUPERAPP_TZ=America/Chicago
```

`SUPERAPP_GOOGLE_CLIENT_ID/SECRET` and `SUPERAPP_VAULT_KEY` come from `/opt/super-app/.env`.
Add both redirect URIs above to the OAuth client in Google Cloud (Gmail connect and app sign-in).

## 3. Caddy route

In `/opt/super-app/deploy/Caddyfile`, inside the site block, before the catch-all `handle`:

```
	handle_path /muse/* {
		reverse_proxy muse-daemon:18792
	}
```

then `docker exec deploy-caddy-1 caddy reload --config /etc/caddy/Caddyfile`.

## 4. Build and run

```bash
cd /opt/super-app-v2 && docker compose -f deploy/docker-compose.muse.yml up -d --build
curl https://<domain>/muse/health
```

## 5. Phone

Sign in with server `https://<domain>/muse` and the `SUPERAPP_API_TOKEN`.
