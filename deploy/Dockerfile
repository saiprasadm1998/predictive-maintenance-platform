# One image, three commands: `pmp web`, `pmp worker` and `pmp backup` (ARC-001 §2.2, §10.1,
# ADR-01, NFR-PORT-01).
# Build from the repository root:  docker build -f deploy/Dockerfile -t pmp .

# ---------------------------------------------------------------- front-end build stage
FROM node:22-bookworm-slim AS frontend

WORKDIR /frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# ---------------------------------------------------------------- build stage
FROM python:3.12-slim-bookworm AS build

COPY --from=ghcr.io/astral-sh/uv:0.13.0 /uv /usr/local/bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/opt/venv

WORKDIR /app

# Dependencies first, so code changes do not invalidate this layer.
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY backend/pmp ./pmp
COPY backend/migrations ./migrations
# Make the code world-readable whatever the permissions on the build machine,
# because the runtime user (pmp) does not own these files.
RUN chmod -R a+rX /app \
    && uv sync --frozen --no-dev

# ---------------------------------------------------------------- runtime stage
FROM python:3.12-slim-bookworm

# PostgreSQL 16 client tools for `pmp backup` and `pmp restore` (Debian's own are version 15,
# which cannot dump a version 16 server), from the PostgreSQL project's signed repository.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl \
    && install -d /usr/share/postgresql-common/pgdg \
    && curl -fsSL -o /usr/share/postgresql-common/pgdg/apt.postgresql.org.asc \
        https://www.postgresql.org/media/keys/ACCC4CF8.asc \
    && echo "deb [signed-by=/usr/share/postgresql-common/pgdg/apt.postgresql.org.asc] https://apt.postgresql.org/pub/repos/apt bookworm-pgdg main" \
        > /etc/apt/sources.list.d/pgdg.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends postgresql-client-16 \
    && apt-get purge -y curl \
    && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/*

RUN useradd --system --uid 10001 --home-dir /app --shell /usr/sbin/nologin pmp \
    && mkdir -p /data/artefacts /data/backups \
    && chown pmp /data/artefacts /data/backups

COPY --from=build /opt/venv /opt/venv
COPY --from=build /app /app
COPY --from=frontend /frontend/dist /app/frontend

ENV PATH=/opt/venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PMP_WEB_HOST=0.0.0.0 \
    PMP_ARTEFACT_DIR=/data/artefacts \
    PMP_BACKUP_DIR=/data/backups \
    PMP_FRONTEND_DIR=/app/frontend

USER pmp
WORKDIR /app
EXPOSE 8000

ENTRYPOINT ["pmp"]
CMD ["web"]
