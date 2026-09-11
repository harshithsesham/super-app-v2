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
fly deploy --config fly.cells.toml --build-only --push --image-label $(git rev-parse --short HEAD)
```

Next: the gateway (`superapp/cells/`) that signs users in, creates a volume and machine per user through the
Machines API, proxies REST and WebSocket traffic to `<machine>.vm.muse-cells.internal:18792`, and wakes cells for due jobs.

## Gateway: the control plane in front of cells

With `SUPERAPP_CELLS=fly` the daemon runs as the gateway (`superapp/cells/gateway.py`): no agent in-process. It keeps
Google sign-in and the session store, holds the registry `<HOME_ROOT>/.cells.json` (user -> machine, volume, cell token,
vault key), creates a volume and a machine on a user's first request or sign-in, proxies every `/v1/*` call and the
WebSocket to `http://[<private_ip>]:18792` on the cell, starts a stopped machine on demand (first response takes a few
seconds), and starts machines `SUPERAPP_CELL_WAKE_LEAD_SECS` (default 120) before their next due job. Cells post their
next-due time to `/internal/cells/state` when they idle out. Gmail connect/callback links are routed by the user encoded
in their signed state. `GET /internal/cells` (header `X-Internal-Token`) lists the fleet.

Gateway env:

```bash
SUPERAPP_CELLS=fly
FLY_API_TOKEN=<fly tokens create deploy -a muse-cells>
FLY_CELLS_APP=muse-cells
FLY_CELLS_IMAGE=registry.fly.io/muse-cells:v3
FLY_CELLS_REGION=ord
FLY_CELLS_MEMORY_MB=2048            # shared-cpu-1x
FLY_CELLS_VOLUME_GB=10
SUPERAPP_GATEWAY_URL=http://<gateway private host>:18792   # how cells reach the gateway to report state
SUPERAPP_CELL_IDLE_EXIT_SECS=600
# plus everything a cell needs, passed through at machine creation: META_API_KEY, MODEL, SUPERAPP_GOOGLE_CLIENT_ID/SECRET,
# SUPERAPP_GOOGLE_REDIRECT_URI, SUPERAPP_PUBLIC_URL, SUPERAPP_TZ, SUPERAPP_ELEVENLABS_API_KEY, SUPERAPP_VOICE_ID
```

The gateway must sit on the Fly private network to reach cells. Simplest: run it as one more Fly machine in the same
org (public service on 443, `fly.toml` for it to follow), and point Caddy's `handle_path /muse/*` at it, or point the app
straight at it. Rotating a cell's secrets or image means recreating its machine (the volume and data stay).

Local test without a Fly account: `scripts/fake_fly.py` serves the Machines API over Docker containers on a `cells`
network. Run it, then the gateway image on that network with `FLY_API_BASE=http://host.docker.internal:18795`,
`FLY_CELLS_IMAGE=muse-cell`, `FLY_CELL_ADDR_TEMPLATE=http://{private_ip}:18792`, and `SUPERAPP_GATEWAY_URL=http://<gateway container>:18792`.
Verified locally: first message provisions a cell in ~8s, WebSocket bridge, idle exit with state report, wake ahead of a
scheduled reminder, delivery, and sleep again.

## Going live on Fly and migrating a user

1. Push the cell image (repeat with a new label whenever `superapp/` changes; then update `FLY_CELLS_IMAGE` in
   `fly.gateway.toml` and redeploy the gateway. Existing machines keep their old image until recreated):
   `fly deploy --config fly.cells.toml --build-only --push --image-label v2`
2. Gateway app: `fly apps create muse-gateway`, set its secrets (see the header of `fly.gateway.toml`; `FLY_API_TOKEN` is
   a deploy token for `muse-cells`), then `fly deploy --config fly.gateway.toml`. Check `https://muse-gateway.fly.dev/health`
   shows `"gateway": true`.
3. Migrate a user from the AWS box (exports home + `muse_<user>` dump + sign-in sessions + old vault key, imports into
   the cell, which restarts itself): `scripts/migrate_cell.py --user <uid> --ssh ubuntu@<box> --gateway https://muse-gateway.fly.dev --internal-token <gateway SUPERAPP_INTERNAL_TOKEN>`.
   Verified locally end to end: 12 home entries, database restored, history and memory visible through the gateway.
4. Cut over: in `/opt/super-app/deploy/Caddyfile` change the `/muse/*` upstream from `muse-daemon:18792` to
   `https://muse-gateway.fly.dev` (with `header_up Host muse-gateway.fly.dev`), reload Caddy, then stop `muse-daemon`.
   The app keeps using `https://app.nutrishiksha.com/muse`, so Google redirect URIs stay valid.

## Push notifications

No third-party relay: the app registers its raw APNs device token with the gateway (`POST /v1/push/register`, stored in
`<HOME_ROOT>/.push.json`), and the gateway talks to Apple directly over HTTP/2 with an ES256 provider token
(`superapp/cells/apns.py`). A cell asks the gateway to notify its user (`POST /internal/cells/notify`, cell token) when the
agent speaks on its own with no app attached: a scheduled job result, a hook, a finished background task, or an approval
card. Dead tokens are dropped on Apple's `BadDeviceToken`/`Unregistered`.

Gateway secrets (an APNs auth key from the Apple developer portal, Keys → Apple Push Notifications service):

```bash
fly secrets set -a muse-gateway APNS_KEY_ID=<key id> APNS_TEAM_ID=JAUSPN67UY APNS_BUNDLE_ID=com.harshith.superapp \
  APNS_KEY_P8="$(cat ~/Downloads/AuthKey_<key id>.p8)"
```

Without the secrets the gateway logs a dry run for every notification it would have sent (`push: dry run ...`).
TestFlight builds use Apple's production APNs host; a local Xcode build registers with `env: sandbox`.
