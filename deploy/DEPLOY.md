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

`SUPERAPP_GOOGLE_CLIENT_ID/SECRET`, `SUPERAPP_VAULT_KEY`, and `SUPERAPP_DB_PASSWORD` come from `/opt/super-app/.env`.
Persistence uses the stack's Postgres (`SUPERAPP_DB_HOST=db` by default): the daemon creates one database per user,
`muse_<user>`, and applies `db/schema.sql` on first use. Set `DATABASE_URL` instead to point elsewhere.
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

## Cells: one machine per user (Fly Machines)

`deploy/cell/` is the runtime cell image, Muse's per-user VM. Each user gets one Fly Machine
(a Firecracker VM) running this image with a volume at `/data`:

- Postgres 16 + pgvector inside the machine on `/data/pg`, the cell's own database on the Muse schema
- the daemon in cell mode (`SUPERAPP_CELL_USER`, `SUPERAPP_CELL_TOKEN`), serving exactly one user, running as the
  unprivileged `hatch` user; tool subprocesses and the browser run as that user too
- Chromium and the retrieval models baked into the image, so a fresh cell never downloads at boot
- sleep and wake: with `SUPERAPP_IDLE_EXIT_SECS` (default 600) the daemon exits 0 once nothing is running, no
  client is connected, no hook is polling, and no job is due soon; the machine stops. `/health` reports
  `cell.next_due_utc` so the gateway can start the machine again before the next job, and any request wakes it.
- egress hook: set `SUPERAPP_EGRESS_PROXY` (and `SUPERAPP_EGRESS_CA`) to route every HTTP client in the cell through a
  policy proxy, the role Sentinel plays in Muse

Build and test locally:

```bash
docker build -f deploy/cell/Dockerfile -t muse-cell .
docker run -d --name cell --env-file .env -e SUPERAPP_CELL_USER=alice -e SUPERAPP_CELL_TOKEN=$(openssl rand -hex 16) \
  -e DATABASE_URL=postgresql://superapp@127.0.0.1:5432/superapp -p 18793:18792 -v cell-data:/data muse-cell
curl -s http://127.0.0.1:18793/health
```

Push the image to Fly (machines are created per user by the gateway, not by `fly deploy`):

```bash
fly apps create muse-cells
fly deploy --config deploy/cell/fly.toml --dockerfile deploy/cell/Dockerfile --build-only --push --image-label $(git rev-parse --short HEAD)
```

Next: the gateway (`superapp/cells/`) that signs users in, creates a volume and machine per user through the
Machines API, proxies REST and WebSocket traffic to `<machine>.vm.muse-cells.internal:18792`, and wakes cells for due jobs.
