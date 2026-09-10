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

## Run

```bash
python3 -m venv .venv && ./.venv/bin/pip install -e ".[memory,db]"
cp .env.example .env   # add META_API_KEY
docker compose up -d   # postgres + qdrant
./.venv/bin/python -m superapp.cli --show-prompt   # inspect the assembled prompt
./.venv/bin/python -m superapp.cli --events
```

## Status

- [x] Prompt blocks, skills, config, DB schema ported
- [x] Core loop: streaming, tools, handoffs, compaction, subagents, background shell
- [ ] Memory retrieval: Qdrant + MiniLM + Jina reranker (`superapp/memory/retrieval.py`)
- [ ] Browser worker (Playwright, accessibility tree, credential grants)
- [ ] Scheduler (cron tiers) and hooks
- [ ] Approval gates (Sentinel-style auditor prompt is in `superapp/prompts/blocks/sentinel/`)
- [ ] Per-user sandbox provisioning
- [ ] Web client
