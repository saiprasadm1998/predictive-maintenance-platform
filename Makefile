# One command for every check: `make check` (needs the dev database: `make db-up`).
# Backend commands run inside backend/ through uv (Python 3.12); front-end commands inside
# frontend/ through npm (Node 22 or later).

UV := cd backend && uv run
NPM := cd frontend && npm
COMPOSE := docker compose -f deploy/compose.dev.yaml
STACK := docker compose -f deploy/compose.yaml
VERSION := $(shell sed -n 's/^version = "\(.*\)"/\1/p' backend/pyproject.toml)
# Trivy for the image scan and SBOM (plan 9.1); pinned by version, pin by digest after a pull.
TRIVY := docker run --rm -v /var/run/docker.sock:/var/run/docker.sock \
	-v pmp-trivy-cache:/root/.cache -v "$(CURDIR)/reports:/reports" aquasec/trivy:0.58.1

.PHONY: check check-unit lint format-check format types contracts test test-unit audit \
        sync db-up db-down db-reset migrate web worker image sbom scan up down logs perf-backfill perf-scoring perf-api perf-ingest perf-latency \
        fe-install fe-dev fe-check fe-lint fe-format fe-test fe-build fe-audit fe-e2e

check: lint format-check types contracts test fe-check

check-unit: lint format-check types contracts test-unit fe-check

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

# ---- front end (frontend/) ----

fe-install:
	$(NPM) ci

# Development server on http://localhost:5173; /api goes to the web role (`make web`).
fe-dev:
	$(NPM) run dev

fe-check: fe-lint fe-test fe-build

fe-lint:
	$(NPM) run lint
	$(NPM) run format:check

fe-format:
	$(NPM) run format

fe-test:
	$(NPM) test

fe-build:
	$(NPM) run build

fe-audit:
	$(NPM) audit --audit-level=moderate

# Browser journeys against the production build, with the API mocked (no database needed).
# Once per machine first: cd frontend && npx playwright install chromium
fe-e2e:
	$(NPM) run e2e

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
	docker build -f deploy/Dockerfile -t pmp:local -t pmp:$(VERSION) .

# The image's software bill of materials (CycloneDX) and vulnerability report, in reports/.
# `make scan` fails on a critical vulnerability that has a fix (ARC §9, NFR-SEC-03).
sbom:
	mkdir -p reports
	$(TRIVY) image --format cyclonedx --output /reports/pmp-sbom.cdx.json pmp:local

scan:
	mkdir -p reports
	$(TRIVY) image --scanners vuln --severity HIGH,CRITICAL --ignore-unfixed \
		--format table --output /reports/pmp-vulnerabilities.txt pmp:local
	$(TRIVY) image --scanners vuln --severity CRITICAL --ignore-unfixed --exit-code 1 pmp:local

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

perf-scoring:
	$(UV) python tools/perf_scoring.py

perf-api:
	$(UV) python tools/perf_api.py

# NFR-PERF-04: 10,000 samples/s through the REST batch endpoint (about 1 minute).
perf-ingest:
	$(UV) python tools/perf_ingest.py

# NFR-PERF-02, AC-05: sample to browser within one cycle plus 5 s, on the wall clock
# (about 5 minutes).
perf-latency:
	$(UV) python tools/perf_latency.py
