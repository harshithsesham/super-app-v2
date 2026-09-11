# The daemon image: Python runtime + the repo (prompts, skills, connectors,
# bin/hatch_gws_cli). Per-user homes live on a mounted volume at /data/users.
FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends git curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/superapp
COPY pyproject.toml README.md ./
COPY superapp ./superapp
COPY skills ./skills
COPY config ./config
COPY bin ./bin
COPY db ./db
COPY scripts ./scripts

# Browsers live outside /root/.cache, which the compose file mounts as a volume.
ENV PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers

# The CLI shim expects the repo's own venv at .venv/bin/python.
RUN python -m venv .venv && ./.venv/bin/pip install --no-cache-dir -e ".[memory,server]" \
    && ./.venv/bin/pip install --no-cache-dir httpx cryptography websockets playwright croniter "psycopg[binary]" psycopg_pool h2 \
    && ./.venv/bin/playwright install --with-deps chromium \
    && chmod +x bin/hatch_gws_cli

ENV SUPERAPP_HOME_ROOT=/data/users \
    SUPERAPP_PORT=18792 \
    PYTHONUNBUFFERED=1
EXPOSE 18792
VOLUME ["/data"]
CMD ["./.venv/bin/uvicorn", "superapp.server:app", "--host", "0.0.0.0", "--port", "18792", "--log-level", "info"]
