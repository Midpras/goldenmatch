# syntax=docker/dockerfile:1

# Node is needed only to compile the browser assets.
FROM node:22-bookworm-slim AS frontend
WORKDIR /src
RUN corepack enable && corepack prepare pnpm@9.15.0 --activate
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml .npmrc ./
COPY packages/python/goldenmatch/web/frontend/package.json packages/python/goldenmatch/web/frontend/package.json
RUN pnpm --filter frontend install --frozen-lockfile --ignore-scripts
COPY packages/python/goldenmatch/web/frontend/ packages/python/goldenmatch/web/frontend/
RUN pnpm --filter frontend build

# Build the fork's Python package, including the compiled frontend. No Rust,
# Node, compiler, or source checkout is carried into the runtime image.
FROM python:3.12-slim-bookworm AS python-build
WORKDIR /src
COPY packages/python/goldenmatch/pyproject.toml packages/python/goldenmatch/README.md packages/python/goldenmatch/LICENSE ./
COPY packages/python/goldenmatch/goldenmatch/ goldenmatch/
COPY --from=frontend /src/packages/python/goldenmatch/web/frontend/dist/ goldenmatch/web/static/
RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install --no-cache-dir --only-binary=:all: '.[web,polars,web-data]'

FROM python:3.12-slim-bookworm AS runtime
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    HOME=/data \
    ARROW_DEFAULT_MEMORY_POOL=system
COPY --from=python-build /opt/venv /opt/venv
RUN apt-get update \
    && apt-get install -y --no-install-recommends gosu \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 goldenmatch \
    && useradd --uid 10001 --gid 10001 --home-dir /data --no-create-home goldenmatch \
    && mkdir /data && chown 10001:10001 /data
USER root
WORKDIR /data
EXPOSE 5050
# Project readiness reports 503 until legacy data or an imported snapshot exists.
# Probe the public shell so a new, empty workspace can open its first import.
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:5050/', timeout=3)"
# Coolify bind mounts may be root-owned. Fix only the mount root, then run the
# server as an unprivileged user without recursively chowning customer data.
CMD ["sh", "-c", "chown 10001:10001 /data && exec gosu goldenmatch goldenmatch serve-ui /data --host 0.0.0.0 --port 5050 --no-open"]
