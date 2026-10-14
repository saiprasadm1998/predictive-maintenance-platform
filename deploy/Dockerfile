# One image, two roles: `pmp web` and `pmp worker` (ARC-001 §2.2, ADR-01, NFR-PORT-01).
# Build from the repository root:  docker build -f deploy/Dockerfile -t pmp .

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

RUN useradd --system --uid 10001 --home-dir /app --shell /usr/sbin/nologin pmp \
    && mkdir -p /data/artefacts \
    && chown pmp /data/artefacts

COPY --from=build /opt/venv /opt/venv
COPY --from=build /app /app

ENV PATH=/opt/venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PMP_WEB_HOST=0.0.0.0 \
    PMP_ARTEFACT_DIR=/data/artefacts

USER pmp
WORKDIR /app
EXPOSE 8000

ENTRYPOINT ["pmp"]
CMD ["web"]
