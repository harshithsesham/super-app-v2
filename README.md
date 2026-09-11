# super-app-v2

A from-scratch implementation of the Muse personal-agent architecture: a
persistent agent with a home directory, curated and retrieved memory, skills
as playbooks, subagents, browser workers, scheduled work, and approval gates.
Model: Muse Spark 1.3 via the Meta Model API.

## Layout

| Path | What |
|---|---|
| `superapp/prompts/blocks/` | 300+ system-prompt blocks recovered from the Muse runtime, ported verbatim (`scripts/port_blocks.py`) |
| `superapp/prompts/roles.yaml` | assembly order per agent role (chat, subagent, compaction) |
| `superapp/prompts/assembler.py` | fills placeholders and joins blocks into a system prompt |
| `superapp/tools/schemas/` | 68 captured tool schemas + reconstructed core namespaces (muse, process, subagent, browser, todo) |
| `superapp/tools/local.py` | shell, files, background processes, todo |
| `superapp/memory/files.py` | home-directory memory layout (MEMORY.md, daily logs, bank, people/groups) |
| `superapp/agent/loop.py` | streaming turn loop, tool dispatch, handoff delivery, compaction |
| `superapp/agent/subagents.py` | spawn/list/send/resume/close with depth limit and concurrency cap |
| `skills/` | 59 skill playbooks (SKILL.md + manifests + evals) |
| `config/home.yaml` | model, memory retrieval tuning, resource caps, compaction thresholds |
| `db/schema.sql` | Postgres DDL for the 194-table runtime schema, generated from `skills/muse_db/references/schema.md` |
| `reference/runtime-cell/` | container boot and supervision scripts from the original runtime |

| `superapp/server.py` | the daemon: bearer auth, one warm agent per user, REST + WebSocket streaming, feed/ideas/goals |
| `apps/mobile/` | Expo app: Muse structure in the space theme. Hub, chat thread with avatar status, Ideas, Goals, Library, Connectors, Memory, activity log, voice orb |

## Run

```bash
python3 -m venv .venv && ./.venv/bin/pip install -e ".[memory,db,server]"
cp .env.example .env   # add META_API_KEY
./.venv/bin/python -m superapp.cli --events          # terminal chat
SUPERAPP_API_TOKEN=dev-token ./.venv/bin/uvicorn superapp.server:app --host 0.0.0.0 --port 18792
```

Mobile (simulator or Expo Go on a phone on the same network):

```bash
cd apps/mobile && npm install
SUPERAPP_API_URL=http://localhost:18792 SUPERAPP_API_TOKEN=dev-token npx expo start --ios
```

Without those env vars the app shows a sign-in screen asking for the server URL and token.

## Status

- [x] Prompt blocks, skills, config, DB schema ported
- [x] Core loop: streaming, tools, handoffs, compaction, subagents, background shell
- [x] Memory retrieval: Qdrant + MiniLM + Jina reranker (`superapp/memory/retrieval.py`)
- [x] Daemon with WebSocket streaming; Expo app in the Muse layout
- [x] Gmail connector: encrypted vault, OAuth connect flow, `bin/hatch_gws_cli` driving the ported skill, sends gated by approval cards (`superapp/connectors/`, `superapp/approvals.py`)
- [x] Browser worker: Playwright driver with referenced-element snapshots, `browser_task` role, live Browser card, approval on checkout-like steps (`superapp/browser/`)
- [x] Hub page and voice orb from the earlier app, fed by this runtime (`superapp/hub.py`, `superapp/voice.py`, `apps/mobile/src/screens/HubScreen.tsx`, `apps/mobile/src/ui/Orb.tsx`)
- [ ] Browser credential grants and takeover
- [x] Persistence on the Muse schema: one Postgres database per user, transcript/tool/compaction/subagent/browser rows, restart checkpoints and recovery (`superapp/db.py`)
- [x] Scheduler: cron jobs and event hooks with the captured tool contracts, worker roles, system jobs (hourly memory upkeep, daily brief) (`superapp/scheduler/`)
- [ ] Gmail watch hook, proactive push notifications
- [ ] Sentinel-style tool-call auditor (prompt is in `superapp/prompts/blocks/sentinel/`)
- [x] Deployed next to the existing API on the AWS box (`deploy/DEPLOY.md`)
- [x] Google sign-in (`superapp/auth.py`)
- [x] Runtime cell image: one Firecracker machine per user with its own Postgres, unprivileged tool user, idle exit and wake state (`deploy/cell/`)
- [ ] Cell gateway: per-user machine provisioning on Fly, routing, wake for due jobs (`superapp/cells/`)

## Gmail setup

Set on the daemon: `SUPERAPP_GOOGLE_CLIENT_ID`, `SUPERAPP_GOOGLE_CLIENT_SECRET`,
`SUPERAPP_GOOGLE_REDIRECT_URI=<public daemon url>/v1/gmail/callback`, `SUPERAPP_PUBLIC_URL`,
and a `SUPERAPP_VAULT_KEY` (Fernet). Add the redirect URI to the OAuth client in Google Cloud.
Then Connectors → Gmail → Connect in the app, or ask the agent, which posts a connect link.
`scripts/test_gmail_flow.py` and `scripts/fake_gmail.py` exercise the whole path without Google.
