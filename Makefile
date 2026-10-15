# One command for every check: `make check` (needs the dev database: `make db-up`).
# Backend commands run inside backend/ through uv (Python 3.12).

UV := cd backend && uv run
COMPOSE := docker compose -f deploy/compose.dev.yaml
STACK := docker compose -f deploy/compose.yaml

.PHONY: check check-unit lint format-check format types contracts test test-unit audit \
        sync db-up db-down db-reset migrate web worker image up down logs perf-backfill

check: lint format-check types contracts test

check-unit: lint format-check types contracts test-unit

sync:
	cd backend && uv sync

lint:
	$(UV) ruff check .

format-check:
	$(UV) ruff format --check .

format:
	$(UV) ruff format . && $(UV) ruff check --fix .

types:
	$(UV) mypy

contracts:
	$(UV) lint-imports --no-cache

# Tests with coverage, then the 80% gate on the analytics modules (NFR-MAIN-01).
test:
	$(UV) pytest --cov=pmp --cov-report=
	$(UV) python tools/coverage_gate.py

test-unit:
	$(UV) pytest -m "not integration"

audit:
	$(UV) pip-audit --skip-editable

db-up:
	$(COMPOSE) up -d --wait

db-down:
	$(COMPOSE) down

db-reset:
	$(COMPOSE) down -v && $(COMPOSE) up -d --wait

migrate:
	$(UV) pmp migrate

web:
	$(UV) pmp web

worker:
	$(UV) pmp worker

image:
	docker build -f deploy/Dockerfile -t pmp:local .

up:
	$(STACK) up -d --build --wait

down:
	$(STACK) down

logs:
	$(STACK) logs -f

# FR-ING-03 acceptance: 12 months of 1-minute data for 50 tags (about 26 million samples).
# Needs the dev database with the demo registry imported. Run once and record the result.
# Kept outside the repository (and outside iCloud-synced folders): about 270 MB.
PERF_FILE := $(HOME)/pmp-perf/history_12m_50tags.parquet
perf-backfill:
	$(UV) python tools/make_history_file.py $(PERF_FILE)
	cd backend && time uv run pmp ingest backfill $(PERF_FILE) --source gw-site-a-01 --mode overwrite
