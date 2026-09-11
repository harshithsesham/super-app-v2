# The runtime cell image: one machine per user (Fly Machines / Firecracker).
#
# What runs inside, mirroring Muse's runtime cell:
#   - Postgres 16 + pgvector on the machine's own volume (/data/pg), the
#     cell's private database on the Muse schema
#   - the daemon in cell mode, serving exactly one user, as the unprivileged
#     `hatch` user; tool subprocesses run as that user too
#   - Chromium for the browser worker, embedding + reranker models baked in
#   - a supervisor (entrypoint.sh) that boots Postgres, then the daemon, and
#     exits when the daemon exits so the machine stops (sleep) until woken
#
#   docker build -f deploy/cell/Dockerfile -t muse-cell .
FROM python:3.12-slim-bookworm

RUN apt-get update && apt-get install -y --no-install-recommends \
        git curl ca-certificates gnupg gosu btrfs-progs procps \
    && install -d /usr/share/postgresql-common/pgdg \
    && curl -fsSL https://www.postgresql.org/media/keys/ACCC4CF8.asc -o /usr/share/postgresql-common/pgdg/apt.postgresql.org.asc \
    && echo "deb [signed-by=/usr/share/postgresql-common/pgdg/apt.postgresql.org.asc] https://apt.postgresql.org/pub/repos/apt bookworm-pgdg main" \
        > /etc/apt/sources.list.d/pgdg.list \
    && apt-get update && apt-get install -y --no-install-recommends postgresql-16 postgresql-16-pgvector \
    && rm -rf /var/lib/apt/lists/*

# The cell user. Everything the agent touches (home, workspace, browser
# profile, vault) is owned by it; Postgres runs as `postgres`; only the
# supervisor is root. Files are copied already owned by it, and the venv is
# chowned inside the layer that creates it, so no layer duplicates another.
RUN useradd --create-home --uid 1000 --shell /bin/bash hatch

WORKDIR /opt/superapp
COPY --chown=hatch:hatch pyproject.toml README.md ./
COPY --chown=hatch:hatch superapp ./superapp
COPY --chown=hatch:hatch skills ./skills
COPY --chown=hatch:hatch config ./config
COPY --chown=hatch:hatch bin ./bin
COPY --chown=hatch:hatch db ./db
COPY --chown=hatch:hatch scripts ./scripts
COPY --chown=hatch:hatch --chmod=755 deploy/cell/entrypoint.sh /opt/superapp/entrypoint.sh

ENV PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers \
    FASTEMBED_CACHE_PATH=/opt/models \
    PATH=/usr/lib/postgresql/16/bin:$PATH

# Only the headless shell of Chromium: the worker never runs headed. Models are
# baked so a fresh cell never downloads on first boot.
RUN python -m venv .venv && ./.venv/bin/pip install --no-cache-dir -e ".[memory,server]" \
    && ./.venv/bin/pip install --no-cache-dir httpx cryptography websockets playwright croniter "psycopg[binary]" psycopg_pool h2 \
    && ./.venv/bin/playwright install --with-deps --only-shell chromium \
    && ./.venv/bin/python -c "\
from fastembed import TextEmbedding, SparseTextEmbedding; \
from fastembed.rerank.cross_encoder import TextCrossEncoder; \
TextEmbedding('sentence-transformers/all-MiniLM-L6-v2'); SparseTextEmbedding('Qdrant/bm25'); \
TextCrossEncoder('jinaai/jina-reranker-v1-turbo-en')" \
    && chmod +x bin/hatch_gws_cli \
    && chmod -R a+rX /opt/models /opt/pw-browsers && chown -R hatch:hatch /opt/superapp/.venv \
    && rm -rf /var/lib/apt/lists/* /root/.cache /tmp/*

ENV SUPERAPP_HOME_ROOT=/data/users \
    SUPERAPP_PORT=18792 \
    SUPERAPP_IDLE_EXIT_SECS=600 \
    PGDATA=/data/pg \
    PYTHONUNBUFFERED=1
EXPOSE 18792
VOLUME ["/data"]
ENTRYPOINT ["/opt/superapp/entrypoint.sh"]
