# PMP Implementation Plan

Rev C · 15 Oct 2026 · Saiprasad Murali

This is my plan for building the Predictive Maintenance Platform (PMP) from the spec pack (PMP-PRD-001, UCS-001, PDS-001, ARC-001, GAP-001 and the design sources). I've checked it against every document in the pack, and Appendix A maps each requirement, use case, screen and acceptance criterion to the sub-phase where I build it, so nothing in the spec gets missed.

What changed in Rev C: I added a progress section, recorded the decisions I made while building Phase 1, and updated the environment notes to match the repo.

## Where I am

| Sub-phase | Status | Notes |
| --- | --- | --- |
| 0.1 Repo and tooling | Done | `make check` runs every check |
| 0.2 Core services | Done | Web role starts, migrates and `/healthz` returns OK |
| 0.3 Containers and CI | Done | Pipeline green on GitHub |
| 1.1 Registry | Done | Demo hierarchy (16 assets, 60 tags, K-101 with 18) imports from CSV or Excel |
| 1.2 REST ingestion and API keys | Done | Example batch and 10,000-sample batch pass |
| 1.3 History import | Done | FR-ING-03 test on my Mac: 12 months × 1 minute × 50 tags = 26,280,000 samples loaded in 6 min 43 s, counts reconcile |
| 1.4 Demo data seeder | Done | 180 days of history for every demo tag; live replay feeds the ingestion endpoint |
| 2.1 Data-quality rules | Done | All eight UCS §6.1 rules, coverage rule, versioned overrides, 30-day preview, `pmp dq` |
| 2.2 Detector contract and placeholder | Done | Contract suite runs before any detector is enabled; median placeholder passes; `pmp algorithms list` |
| 2.3 Outputs and health | Done | Residual, q, z, DI, contributions, Health, band and coverage; AC-03 reference set (10 cases, exact decimal expected values) passes to 1e-6 |
| 3.1 Model definitions and alert rules | Done | Models with Draft versions, sensors, periods, safe operating-mode filters, alert rules; K-101 defined from `data/demo/models/k101.json` |
| 3.2 Baseline training job | Done | K-101 trained on 157,398 of 158,400 cycles of demo history and validated on 42,584; artefact with SHA-256 |
| 3.3 Artefacts and version lifecycle | Done | Deploy, pause, resume, retire, reject; deploy supersedes; one version in service (database-enforced); SHA-256 checked on every load; per-worker cache |
| 4.1 Scoring runtime | Done | Scheduler leader in the worker, cycles on the clock with a 20 s grace; DQ, coverage and operating mode before prediction; score, sensor_output and runtime_status written in one transaction with NOTIFY; no duplicates, no back-fill; NFR-PERF-01 check (`make perf-scoring`): 100 models and 5,000 tags in 5.5 s against a 30 s budget; final check on my Mac in progress |
| 4.2 Alert engine | Done | ISA-18.2 lifecycle (UCS Figure 6) with persistence, on-delay, deadband clearing and escalation; evaluated in the scoring transaction; acknowledge, shelve (reason, 7-day maximum), unshelve and expiry; Out of service follows the model; priority matrix with re-prioritising; event log, audit, traceability record and NOTIFY; `pmp alert` commands; AC-03 alert reference sequences; |
| 4.3 Health roll-up | Done | Worst band and lowest Health from models up through equipment, units, sites and the enterprise; counts of assets per band; not-monitored assets; computed on read from the latest cycle; `pmp health tree`; the REST endpoint comes with the other asset endpoints in 5.2 |
| 4.4 Spec alignment | Done | Full audit of Phases 0–4 against PRD, UCS, ARC, PDS, GAP and the design sources; fixes in data quality, roll-up, alert lifecycle, scoring cycle, job queue and the ingest API (see decisions marked 4.4) |
| 5.1 Users, access control and audit review | Done | Users with Argon2id passwords, role assignments with optional hierarchy scope, sessions (cookie with CSRF, or bearer token), lockout and idle timeout; the ARC §9.2 matrix checked in the services and unit-tested cell by cell; API key administration and the audit search with CSV export over the API; `pmp user` and `pmp audit` |
| 5.2 REST API | Done | 56 operations under `/api/v1`: reads for the screens (assets with roll-up, tags, types, sensor health, models, trends downsampled to min/max per pixel bucket), alerts (list with database keyset paging, one with trace and history, acknowledge/shelve/unshelve one or many), priority matrix, fleet KPIs, jobs; writes for the registry (assets, tags, types and roles, import, unmapped tags), models (create, alert rules, train, lifecycle), data-quality rules (preview, save with confirmation) and users; cursor paging, problem+json for every error, scope filtering, Swagger Authorize. Contract test: the OpenAPI 3.1 document validates and every documented operation is called with its response checked against the schema. `make perf-api`: 30-day trend of 20 sensors 1.3 s, 1,000 alerts 0.04 s |
| 5.3 Live event stream | Done | `GET /api/v1/events` (server-sent events): score.updated, alert.changed and job.progress, from the worker's NOTIFY through one LISTEN connection per web process; filtered by the user's scope; keep-alives; the stream ends when the session does. Tested over a real HTTP server: a score reaches a subscribed client within seconds of the cycle's commit, and a client scoped elsewhere never sees it; passes on my Mac |
| 5.4 Time-series storage and retention | Done | Chunks and compression after 7 days as ARC §6.3 (score now 7-day chunks); hourly continuous aggregates `sample_1h`, `score_1h` and `sensor_output_1h` (min, max, mean, count) with a 30-minute refresh and real-time aggregation; trends longer than 30 days read them; a history import refreshes the hours it touched; retention (24 months raw, 60 months aggregates) set by an administrator (`/api/v1/retention`, `pmp retention`) and applied daily by the scheduler leader. The compression and aggregate checks run on real TimescaleDB (my Mac and CI) and pass |
| 6.0 Demo story for the screens | Done | Eight demo models (`pmp demo models`) and back-scoring of the last 24 h (`pmp demo score`), so the screens open on a running plant: K-101 and K-201 in Alert, P-104A and F-3 in Watch, P-205 with an alert returned to normal unacknowledged, P-202 Unknown (no data), E-110, P-104B and P-205 Healthy; K-201 and F-3 now class B. Checked on the full 180-day demo history; passes on my Mac |
| 6.1 App shell, design system and accessibility | Done | React 18, TypeScript and Vite app in `frontend/`. Sign-in with the session cookie and CSRF token, returning to the deep link it came from; one route per SCR-nn screen (placeholders until each screen's sub-phase); navigation rail, top bar with title, TimeRangePicker (presets and custom range, in the URL, with the time zone), asset search ("/" to focus) and the live indicator ("Live · scored 14:05"); user menu with sign-out and the dark control-room theme. Shared components: StatusChip and AlertStateChip (shape + text + colour for every band, severity, NE 107 and alert state), HealthScore, HealthBar, TrendChart (ECharts, enforcing PDS §3.4: band, limits, exclusions, bad-data gaps and ticks, alert bar, shared cursor and zoom, arrow-key cursor and a View data table) and ConfirmDialog; all on `/design` in development. The live event stream refreshes the affected reads (once per burst), re-reads everything after a reconnect, announces new alerts to screen readers and signs out when the session ends. The web role serves the built app (one origin), and the image builds it. 89 front-end tests: components, chart conventions, live events, axe checks, keyboard navigation, and token contrast in both themes. Passes on my Mac |
| 6.2 Fleet overview and area/unit view | Built | SCR-01: fleet figures with shapes (models running, assets in Alert, Watch and Unknown, sensor faults) that open the filtered view; the hierarchy with type, band, Health bar and open alerts, abnormal branches open and healthy ones closed, the Unknown reason on hover; highest deviation now (held still under the pointer) and recent alerts; stale-data banner, empty state, live row highlight. SCR-08: one card per monitored asset (band, Health, 7-day DI sparkline, open alerts) and the unit's open-alert count over the chosen period. The asset tree now carries asset type and open-alert counts. N+1 queries removed from the roll-up, the runtime statuses and the model list: the fleet overview's four reads for 500 assets take 0.76 s in my sandbox (were 5 s). Playwright journeys on the production build with a mocked API: 500-asset fleet ready in about 1 s (budget 2 s), fleet to unit to asset, search; 108 component tests. Final check on my Mac in progress |
| 6.3 Asset analysis | Built | SCR-03 on the demo data: summary card (Health with shape, band and DI, model and version, coverage, last scored and cycle, status since, the most urgent open alert); DI trend with the warning and alert limits always in view, alert bars that end when the condition cleared, and shading (with the reason) wherever the model was not scoring normally, or since a pause; Health trend; top contributors with share, direction and z, which add or remove their charts; actual vs predicted small multiples with the expected band (± warning × σ); the sensor table with NE 107 status and rule; version selector for historical comparison; insufficient-data reasons with the unusable sensors; acknowledge from the page with an optional comment; an alert link opens on the alert's window. New API reads: the latest cycle per sensor (`/models/{id}/latest`, with σ from the artefact), `/models/{id}/status-periods`, `version` on scores and outputs, and `cleared_at` on alerts. 124 component tests, 6 browser journeys. Final check on my Mac in progress |
| 6.4 Alert list | Built | SCR-02 as wireframe 02: priority with shape, state, asset path, model and version with the rule, severity, DI, Health, persistence (n of m), age; forecast urgency and case shown as Release 2. Server order (unacknowledged first, then priority, then age) kept; virtualised rows; filters by scope, state, priority, severity and rule (plus closed alerts), all in the URL, and saved filters per user; bulk acknowledge (optional comment), shelve (reason and duration required), unshelve, all or nothing; the asset opens on the alert's window; a detail panel with what the alert was based on (cycle, value against limits, inputs with data quality) and its history (who, what, comment); the priority matrix. Live updates refresh values in place and show "N new alerts · show" instead of re-sorting. New API fields: asset path, version, the model's DI and Health, persistence, and usernames in history. 138 component tests, 8 browser journeys. Final check on my Mac in progress |
| 6.5 Models: management, builder and version detail | Built | SCR-10 model list (version in service, runtime status, band, DI, when trained or deployed, alert rate from the last 30 days, the newer version if any, runtime-status filter, New model) and SCR-11 version detail (configuration, training definition, sensors, training and validation figures, active alert limits, playback of what the version scored with its limits and shading, audit history for administrators, links between versions, New version); deploy, pause, resume, retire and reject from both, each confirmed with its consequence. SCR-06 builder in six steps with checks before Next: asset and sensors (asset-type template, required sensors, no clash with an existing model name), training and validation periods and the scoring cycle, cleansing (operating-mode filters with the effect of each rule, retained share, flagged sensors, the minimum-data block, and each sensor's training data with excluded periods shaded, from the new `POST /models/training-data` preview), training as a background job with live progress that can be left and resumed, alert limits (DI with persistence, sensor |z| rules), and deploy with a summary and confirmation. A Playwright journey builds, trains, validates and deploys a model in the UI (AC-02 rehearsal). |
| 6.6 Registry, data import and administration | Built | SCR-13 registry and import in six tabs: the hierarchy (indented, with edit, move under any higher level, and add below), tags (filter by asset or text, edit, register, role from the asset's type), asset types and their roles, registry import (validate first with a report by sheet, line and column; import only after a clean validation, all or nothing), history import (CSV or Parquet, long or wide, preview as a job with rows, time range, tags, rejects by reason and samples already stored; then the same upload imported, with the counts reconciled), and unmapped tags with register; history upload now accepts a signed-in user as well as an ingest key. SCR-14 administration: users and roles (roles limited to part of the hierarchy, deactivate, password reset, each confirmed), API keys (issued and rotated keys shown once with copy, revoke), data-quality rules everywhere, per asset-type role or per tag (inherit or override each parameter, preview on 7 to 90 days with the tags most affected, confirmation above 20 %, a comment kept with the version), retention (confirmed, saying what will be deleted), and the audit log (filters, before and after of each change, older pages, CSV export). SCR-07 sensor health list: NE 107 counts that filter, non-Good sensors worst first with rule, scoring use and since. Playwright journeys for a registry import, a history import and issuing an API key. |
| 6.7 Audit of Phases 0–6 | Built | Audit against all six documents (PRD, UCS, PDS, ARC, GAP and the design sources). 6.7a built: alerts of a removed or switched-off rule close with the reason; a scoped engineer can no longer move another site's tag (register, change or promote); a sample without a value is refused alone; every sensor gets a current NE 107 status (other sensors checked once a minute); preview and live judge flatlines alike; rule and job reads follow the user's scope and rule changes are authorised before any preview; security headers; Rejected versions kept; the audit CSV holds every match; user and model IDs on log lines; 5 s default grace with per-source grace; the role matrix tested at every endpoint (each call made again as every refused role). 6.7b built: retention runs as a worker job and each module names its own tables; an import contract keeps the modules layered (scoring, alerting, modelling, data quality, ingestion, registry); contributions at a chosen time (`at=`); unused periods with each sensor trend; alert list sort (newest, oldest, priority, severity) and raised-between filters; sensor health and unmapped tags paged; a model's versions and a type's roles readable on their own; the shelve maximum exposed. 6.7c-1 built: preset ranges slide with the clock each minute; zooming a chart fetches finer data for that window; tooltips give the full ISO time and data tables round to six significant digits; Health on a fixed 0 to 100 axis; a click on a chart (or an alert link) shows the contributors at that time, with a way back to the latest cycle; sensor charts shade the cycles a sensor was left out of scoring, with its status and rule; alert list sort in the URL; only active alerts can be shelved, for up to the configured maximum; unshelve from the panel is confirmed; the history names alerts closed by a removed rule. 6.7c-2 built: the fleet hierarchy sorts by band or Health (worst first among siblings, in the URL); every panel shows its own load error; the deploy confirmation says open alerts carry on under the new version (they belong to the model); equipment needs a criticality class in the form, as on the server; leaving a changed form (hierarchy, tag, user, rules) asks first; arrow keys move between rows of the fleet, alert, model, tag and sensor tables; status colours meet 4.5:1 on the selected-row tint in both themes and menu items show a focus outline; SCR-07 names the models scoring each sensor and lists statuses in the figures' order; the asset summary always describes the latest cycle and warns when scores stopped. Phase 6 audit complete. |
| 7.1 AAKR detector | Built | `pmp/modelling/algorithms/aakr.py`, a built-in detector behind the contract (not yet the default; 7.4). Memory matrix: k-means centroids (k from 20 to 200 by silhouette score on a seeded sample), plus each sensor's minimum and maximum rows, 200 to 1,000 vectors, seeded. Prediction: Gaussian kernel on the root-mean-square distance over the sensors usable in the cycle, so an excluded sensor is predicted from the others. Calibrated on the validation period: the bandwidth with the lowest validation error among 0.1 to 2.0 x the median nearest-neighbour distance, and the out-of-envelope limit at the 99.5th percentile of validation minimum distances. What it learnt is kept with the version's metrics. Tests: the contract suite; healthy data predicted within noise, an excluded sensor too; a seeded drift raises the Deviation Index quarter by quarter and is carried by the drifting sensor; the envelope flag; save and load; under 50 ms per model per cycle; K-101 trained end to end with AAKR beats the placeholder on the hold-out. |
| 7.2 Training data and cleansing | Built | 7.2a built (back end): `pmp/modelling/cleansing.py` runs the rules in order on the training cycles, each counting only what it removed: operating mode, data quality and coverage, periods excluded on the trend, per-sensor outliers (|robust z| > 4 drops the whole cycle), and multivariate outliers (beyond the 99.9th percentile of distance to the nearest of 2 to 8 operating clusters, chosen by silhouette score). Training fits on what is kept and checks the minimum data after cleansing; validation is played back with the runtime rules only. Excluded periods are part of the model definition (stored with the version, in the audit snapshot and the definition file format; refused outside every training period). The training-data preview returns each rule's count and the retained cycles per operating cluster; the version's metrics keep the same. Migration 0013. 7.2b built (wizard, SCR-06 step 3 as wireframe 06): every rule's effect in order (operating mode, data quality and coverage, excluded on the trend, outliers, multivariate outliers), the retained share, the operating clusters with a warning for any holding under 5 % of the data, and the minimum-data block; drag across the training trend to exclude a period, or add one by its times (the keyboard route), each listed with editable times and a remove button, and the preview follows at once. Drafts saved in the browser before 7.2 load with no exclusions. Fixed on the way: turning a click on a chart into a time failed, so the asset page's click-to-pick (6.7c) did nothing; a browser journey now covers both. |
| 7.3 Validation and proposed limits | Built | 7.3a built (back end): `pmp/modelling/validation.py`. The hold-out is scored as runtime scores it: the Deviation Index of every cycle over the usable sensors, its P50, P95, P99 and P99.9, and the share of cycles outside the model's envelope (AAKR). Proposed limits: DI warning 1.2 x P99, DI alert 1.5 x P99.9 and at least 10 % above the warning, sensor |z| 3 and 5, rounded up to one decimal. The default alert rule (3 of 5 to raise, 10 % deadband for 5 cycles to clear) is run on the hold-out with the proposed warning: every alert is a false one, per model-week, with the UC-05 8a warning above one a week. The report is kept with the version (metrics and the artefact's validation.json); per-sensor normalised RMSE and bias were already there. On the demo K-101 with AAKR: DI P99 22.8, proposed warning 27.4 and alert 38.0, no false alert in the hold-out. 7.3b built: the wizard's train step shows the validation report (cycles scored, DI percentiles, share outside the envelope, proposed limits, estimated false alerts a week, the UC-05 8a warning, and each sensor's normalised RMSE and bias, worst first); moving on puts the proposed DI limits into the limits step once per validated version, so later edits stay; the limits step explains where they came from and warns when the DI warning is set below the proposal; the version page (SCR-11) shows the same report later. Per-sensor RMSE and bias are now kept with the version's metrics too. Versions trained before 7.3 say so. |
| 7.4 Swap-in and evaluation | Built | 7.4a built: AAKR is the default detector (definition files without `algorithm`, the wizard, the demo); the median placeholder stays available and the pipeline-mechanics tests pin it. Corrected to the UCS §6.4 wording: the DI alert limit is 1.5 x P99.9 with a minimum of DI 10 % (7.3 had read the minimum as 10 % above the warning), and the cleansing rules run in the table's order (data quality, operating mode, outliers, multivariate, then manual exclusions). The demo models take the DI limits their validation proposes, as an engineer would in the wizard; the files' sensor rules stay. The per-sensor outlier rule runs within each operating cluster (decision below, for review). On the full demo history: healthy DI P50 1 to 4.5, proposed limits from 5 / 21.4 (F-3) to 11 / 18.2 (K-101), estimated 1.4 to 5 false alerts a week, so every demo model shows the UC-05 8a warning (measured properly in 7.4b). 7.4b built: `pmp evaluate EVENTS.csv` (`pmp/evaluation.py`) compares the alerts raised in a period with an event history (DP-04: asset, start, end, description, detectable): an event is detected when an alert on its asset was raised between its start and end, with lead time end minus first alert; not-detectable events are listed apart; every other raise is a false alert per model-week; each raise is listed for classification. Raises are counted from each alert's history, because an unacknowledged alert that returns to normal and comes back keeps its record (ISA-18.2) and nobody acknowledges in a replay. The demo's faults are in `data/demo/events.csv`. First evaluation, 30-day replay of the 8 demo models with AAKR and proposed limits: 5 of 5 detectable events alerted (100 %), median lead time 2.9 days (K-101 thrust bearing 17.8 days); false alerts 394, 11.5 per model-week against the 0.5 starting target, about 460 raises from sensor |z| rules and 130 from DI rules. Detection meets the target; false alerts do not on the demo, and are evaluated again on pilot data in 9.2 (decided, see below). |
| 8.1 Sensor exclusions and sensor health | In progress | 8.1a built (back end): exclude a sensor (NE 107 Function check, left out of every model) or override an automatic status to Good (UC-14 1a), each with a reason and an expiry of at most 90 days, from the next cycle; both end on their own at the expiry or by hand, and a new entry ends the previous one; all audited and authorised per asset (sensor-exclusion permission: analysts and model engineers). An override covers out of range, flatline, spike and uncertain quality, never bad source quality or missing data (FR-ING-05). API: `POST /sensors/{tag_id}/exclusions`, `POST /sensor-exclusions/{id}/end`, `GET /sensor-exclusions`; sensor health gains the active entry per sensor and a `scope` filter (a site and everything beneath it). Migration 0014. Next: 8.1b, the SCR-07 screen and Exclude on asset analysis. |

## How I work

I've split the build into 10 phases (0 to 9), each broken into sub-phases, and I don't move on until the current sub-phase is built and its tests pass. Phases 0 to 6 build the backend and front end around a placeholder detector. Phase 7 builds the real prediction model. Phase 8 delivers Release 2 (Diagnose and act), and Phase 9 hardens the system and proves acceptance.

**My rules for every sub-phase**

- I build it from the spec pack and cite the use case (UC), functional spec section (UCS §), architecture section (ARC §) or screen (SCR) it implements.
- I test it: unit tests for logic, contract tests for interfaces, integration tests against a real PostgreSQL/TimescaleDB container, and the reference-data checks wherever the spec gives formulas.
- It's done when the "Done when" line is true and all the checks run green with one command (`make check`).
- If the spec is unclear, conflicts with another document or needs a client decision, I stop and ask rather than build on a guess. Open questions are listed at the end.
- At the end of each phase I send a short update with a demo of what now works.

**My assumptions**

- Release 1 and Release 2 are both in scope, delivered by the end of November 2026. The week split below is my estimate, not a commitment.
- I'm building the backend and front end first and the prediction model after. Until then a placeholder detector, which predicts each sensor as its training median, sits behind the detector plug-in contract (ARC §8.1). That lets me build and demo the whole pipeline and every screen, and the AAKR model replaces it in Phase 7 without changes anywhere else. Scores before Phase 7 are for demonstration only and don't indicate real anomalies.
- The scoring formulas (residual, q, z, Deviation Index, Health Score) are plain maths, so I build them early. The placeholder still needs a real training step, because q needs each sensor's training range (P99 − P1) and z needs the residual σ from a validation period.
- Release 3 items are stretch goals. I only build them if Release 1 and 2 are done (see "Stretch").
- My development environment: macOS on Apple Silicon, Docker Desktop running TimescaleDB on PostgreSQL 16 (the image is pinned by digest), Python 3.12 managed by uv, and Node 26 for the front end. Integration tests run against the database container on my Mac and in CI.
- Until pilot data arrives, I build and demo everything on synthetic demo data (Phase 1.4).

| Phase | Goal | Release | Week |
| --- | --- | --- | --- |
| 0 Foundations | Runnable skeleton, module boundaries, audit, CI | R1 | 1 |
| 1 Registry and ingestion | Assets, tags, REST ingestion, history import, demo data | R1 | 1 to 2 |
| 2 Data quality and scoring pipeline | Configurable rules, detector contract, DI and Health verified to 1e-6 | R1 | 2 |
| 3 Model management | Definitions, baseline training, artefacts, version lifecycle | R1 | 2 to 3 |
| 4 Runtime and alerting | Scoring cycle, alert engine, roll-up | R1 | 3 |
| 5 Security, API and events | RBAC, REST, live stream, retention | R1 | 3 to 4 |
| 6 Front end for Release 1 | All R1 screens | R1 | 4 to 5 |
| 7 Prediction model | AAKR, cleansing, validation, proposed limits | R1 | 5 to 6 |
| 8 Diagnose and act | Exclusions, diagnostics, forecasts, cases, notifications, templates, with screens | R2 | 6 to 7 |
| 9 Hardening and acceptance | Packaging, operations, acceptance, handover | R1 and R2 | 7 |

## Phase 0: Foundations

In Phase 0 I set up a runnable, tested skeleton with the module boundaries enforced, so every later phase only adds code inside the right module.

**0.1 Repo and tooling** (ARC §4, §12, NFR-MAIN-01)

- Build: repo layout per ARC §12 (backend, frontend, deploy, docs), a Python 3.12 project managed by uv, Ruff, mypy, pytest with Hypothesis and coverage, and import-linter contracts for the 13 modules (core, ingestion, registry, dataquality, modelling, scoring, alerting, diagnostics, prognostics, advisory, cases, notifications, reporting), with the `api` package allowed to call module public interfaces only.
- Test: lint, type check and import contracts pass on the empty modules, and a deliberate cross-module import fails the contract.
- Done when: one command runs every check.

**0.2 Core services** (ARC §4, §5.1, §6, §10.2, §10.4)

- Build: configuration from `PMP_*` environment variables, database sessions, Alembic migrations (run on web start behind an advisory lock), an in-process event bus, a job queue (claimed with SKIP LOCKED, with retries and lock expiry), structured JSON logging with request IDs, the append-only audit writer (who, what, when, before and after values) so every later module can audit from day one, and the `pmp web | worker | migrate` commands.
- Test: unit tests for config, event bus and audit writer, and integration tests for job claim, retry, lock expiry and job survival across a process restart (NFR-REL-01).
- Done when: the web role starts and `/healthz` returns OK.

**0.3 Containers and CI** (ARC §10, §12.2, NFR-PORT-01, NFR-SEC-03)

- Build: a Dockerfile (one image, both roles), a development compose file with PostgreSQL 16 and TimescaleDB (image pinned), and a CI pipeline running lint, types, import contracts, unit and property tests, integration tests against a TimescaleDB service container, an 80% line-coverage gate on the analytics modules, and pip-audit. The front-end build and npm audit join in 6.1, and the image scan and SBOM in 9.1.
- Test: the image builds from a clean checkout and a smoke test hits `/healthz`.
- Done when: the pipeline is green on a clean checkout.

## Phase 1: Registry and ingestion

In Phase 1 I get plant data flowing in: an asset and tag registry, the gateway ingestion endpoint, history import, and a synthetic demo dataset to build and demo against.

**1.1 Registry** (UC-03, FR-REG-01 to -04, ARC §6.2)

- Build: an asset hierarchy of variable depth (up to Enterprise › Site › Area › Unit › Equipment) with an ltree path, criticality class A, B or C, and create, edit and move; tags with source, source name, description, unit, instrument range, sampling interval and owning asset; asset types with roles and tag-to-role mapping (FR-REG-04 is R2, but templates and diagnostics need it, so I build it now); CSV and Excel import with a line-level validation report and atomic commit. Every change is audited.
- Test: hierarchy and move queries, import validation (a bad file is rejected with line numbers, a valid file commits atomically), the unique (source, source name) rule, and a 500-asset import.
- Done when: the demo hierarchy from the wireframes (Site A › Ammonia unit › K-101 with its 18 tags, plus P-104A/B, K-201, P-202) imports from a file.

**1.2 REST ingestion and API keys** (UC-01, FR-ING-01, -04, -05, -06, FR-SEC-02, ARC §7.1.1)

- Build: API keys (stored as hashes, shown once, scope `ingest` or `results-read`, revoke and rotate in the service layer and the CLI; the admin screens come in 6.6); `POST /api/v1/ingest/samples` behind an ingestion adapter interface (ADR-07); limits of 10,000 samples or 5 MB per request, gzip accepted; quality mapping from OPC UA StatusCode severity bits or the strings Good, Uncertain, Bad (omitted means Good); idempotent upsert on (source, tag, ts) into the `sample` hypertable; a 7-day late window and 5-minute future tolerance; per-item rejections; responses 202, 400, 401, 403, 413, 429 (with Retry-After) and 503; failed authentication logged; the unmapped-tags list with first-seen time and count, and promotion of an unmapped tag to a registered tag (FR-ING-06); per-source ingestion statistics (last received time, accepted and rejected counts).
- Test: contract tests for the spec payloads, idempotency on resend, each rejection reason, an ingestion key refused on every non-ingestion endpoint, and a 10,000-sample batch.
- Done when: the example batch in ARC §7.1.1 returns the counts shown there, and a 10,000-sample batch returns 202 and is queryable within 5 s.

**1.3 History import** (UC-02, FR-ING-03, ARC §7.1.3)

- Build: `POST /api/v1/ingest/backfill` accepting CSV or Parquet in long format (ts, tag, value, quality) or wide format (ts plus one column per tag); validation and preview (row counts, time range, unmapped columns, line-level errors); skip or overwrite for overlapping samples; loading as a background job with progress; loaded, rejected and duplicate counts. Backfill isn't subject to the 7-day late window (see decisions).
- Test: both formats, a file with errors, overlap with skip and with overwrite, and count reconciliation.
- Done when: a 12-month, 1-minute file for 50 tags loads without manual intervention and its row counts reconcile.

**1.4 Demo data seeder** (supports UC-02 and all later demos)

- Build: a seeded generator for the wireframe assets (K-101 syngas compressor, BFW pumps P-104A and P-104B, CO2 compressor K-201, carbamate pump P-202) with correlated sensors, operating modes and injected scenarios: healthy, slow drift toward thrust-bearing degradation, flatline, spike, stale data and out-of-range. History loads through 1.3, and live data replays through 1.2.
- Test: the same seed gives identical data, and each injected scenario shows up in the raw signals.
- Done when: months of 1-minute history load for every demo asset and a live replay feeds the ingestion endpoint.

## Phase 2: Data quality and scoring pipeline

In Phase 2 I build the pipeline that turns sensor readings into a Deviation Index and Health Score. The formulas don't need client data, and their tests are my evidence for acceptance criterion AC-03.

**2.1 Data-quality rules** (UC-04, FR-DQ-01 to -03, UCS §6.1)

- Build: the eight rules in the specified order (bad quality, stale, manual exclusion, out of range, flatline, spike, uncertain, good) with their effects (spike excludes the sample for that cycle, flatline can be configured to "used", uncertain is used and flagged); default thresholds overridable per tag or tag group, with rules enabled or disabled; rule sets versioned and audited; a preview of the effect on the last 30 days with a warning above 20% excluded; NE 107 status per sensor with the rule that set it, and the SensorStatusChanged event; the model coverage rule (at least 70% usable and every required sensor usable). Manual exclusions are read here; creating them comes in 8.1.
- Test: unit tests per rule, property-based tests with generated signals, a test that the first matching rule wins, rule clearing when the condition ends, and the preview warning.
- Done when: every row of the UCS §6.1 table has a passing test.

**2.2 Detector contract and placeholder** (UCS §6.3.3, ARC §8.1, ADR-09)

- Build: the Detector contract (fit, predict, save, load, name, version), the plug-in registry through the `pmp.algorithms` entry point, the contract test suite, and the placeholder detector that predicts each sensor as its training median.
- Test: the contract suite (output shape, NaN handling, save and load round trip, determinism with a fixed seed).
- Done when: the pipeline can use any detector that passes the suite, and the placeholder predicts all sensors, including excluded ones.

**2.3 Outputs and health** (UCS §6.2, §6.5, §6.7.1, FR-RUN-02, FR-DIA-01, AC-03)

- Build: residual, relative deviation q (range R = P99 − P1 of cleansed training data), standardised residual z (σ = 1.4826 × MAD of validation residuals), Deviation Index over usable sensors, contributions (summing to 100%, with sign and z), Health Score with DIref = 2 × DI alert limit, band (Healthy, Watch, Alert, Unknown, including sensor-rule states) and coverage.
- Test: a reference dataset in `tests/reference_data` with supplied predictions and expected outputs checked to 1e-6, including the worked example (alert limit 25%: DI 29.5% gives Health 41, DI 15% gives Health 70). The test is independent of the detector.
- Done when: the AC-03 scoring reference test passes.

## Phase 3: Model management

In Phase 3 I build model definitions, a baseline training job and the version lifecycle, so an engineer can set up, train, deploy and manage models. Full cleansing and validation metrics come in Phase 7.

**3.1 Model definitions and alert rules** (UC-05, FR-MOD-03, ARC §4)

- Build: model records with their sensors and required flags; one or more training periods and a hold-out validation period that may not overlap; operating-mode filter expressions (for example `II-1001 > 120`) parsed by a safe expression evaluator, used later at runtime (4.1) and in training (7.2); alert rules (one DI rule per model, optional sensor |z| rules) with warning and alert limits, persistence, on-delay and deadband.
- Test: definition validation (sensors belong to the asset, required sensors set, periods don't overlap, limits consistent) and the expression evaluator, including rejection of unsafe input.
- Done when: a model for K-101 with its 18 sensors, an operating-mode filter and alert rules can be defined.

**3.2 Baseline training job** (UC-05 steps 3, 7, 8, ARC §5.2)

- Build: a `train` job that assembles data for the training periods, applies the data-quality and operating-mode filters, fits the detector (the placeholder for now), computes scaling statistics (medians and robust ranges), plays back the validation period to compute residual σ, writes the artefact and `validation.json`, and sets the version to Validated or Failed with error detail. Seeds are stored in the version parameters (ARC §8.3).
- Test: a successful run on demo data, a failing run that ends in Failed, and reproducibility with the same seed.
- Done when: a K-101 version trains on demo history and reaches Validated with the statistics q and z need.

**3.3 Artefacts and version lifecycle** (UC-06, FR-MOD-07, ARC §5.3, §8.2)

- Build: the artefact folder (algorithm files, `scaling.json`, `manifest.json`, `validation.json`) with SHA-256 verified on every load; the full state model of ARC Figure 7 (Draft, Training, Failed, Validated, Deployed, Paused, Superseded, Retired, and Validated back to Draft when rejected); exactly one Deployed version per model, with deploy superseding the previous one; immutability after Validated except status; the ModelDeployed event and per-worker model caching; every transition audited.
- Test: a tampered artefact refuses to load, every allowed transition works, every invalid one is refused, and transitions write audit entries.
- Done when: a version can be deployed, paused, resumed, superseded and retired through the service layer.

## Phase 4: Runtime and alerting

In Phase 4 the system goes live: every deployed model is scored each cycle, alerts are raised and cleared by the ISA-18.2 rules, and health rolls up the asset hierarchy.

**4.1 Scoring runtime** (FR-RUN-01 to -04, FR-MOD-03, ARC §5.1, UCS §6.2)

- Build: a single scheduler leader held by `pg_advisory_lock`; per-model cycles (default 60 s, minimum 10 s) aligned to wall-clock multiples, starting after a grace period (default 20 s); scoring partitioned across a process pool; latest samples at or before the cycle time with sample-and-hold up to the stale limit; data quality, coverage and operating-mode checks before prediction; the runtime statuses Running, Not in operating mode, Insufficient data, Paused, Out of service and Error; the `score` and `sensor_output` hypertables with the envelope flag column (filled by AAKR in Phase 7); score, sensor outputs and alert changes committed in one transaction followed by NOTIFY; missed cycles not back-filled; late data not changing past scores; the ScoreComputed event.
- Test: an end-to-end run on the live replay, the timing target (100 models and 5,000 tags scored within 30 s of cycle start, NFR-PERF-01), and a kill-and-restart test showing no duplicate scoring (NFR-REL-01).
- Done when: scores appear every cycle for every demo model, status changes are visible within one cycle, and insufficient-data cases show Unknown instead of a number.

**4.2 Alert engine** (UC-10, FR-ALM-01, -02, -04, NFR-ACC-01, UCS §6.6)

- Build: DI and sensor rules (sensor rules skipped for excluded sensors); persistence (default 3 of the last 5 cycles); on-delay (default 0); deadband clearing (default 10% for 5 cycles); one alert per rule; escalation from Warning to Alert on the same alert; the ISA-18.2 state model of UCS Figure 6, including RTN-unacknowledged, and Out of service set automatically on pause or retire and cleared on redeploy; shelving with reason and duration (7-day maximum), unshelve, and re-evaluation at expiry by a scheduled job; alert rules not evaluated while a model has insufficient data (active alerts keep their state); the priority matrix by criticality and severity (FR-ALM-04 is R2, but I build it now), configurable, with changes re-prioritising active alerts and audited; the alert event log; a traceability record stored with each raised alert (model version, rule, input sample times, contributions and data-quality states); the AlertChanged event.
- Test: state-machine unit tests for every transition, property-based tests for persistence and deadband, and an AC-03 alert reference test with expected states for given DI sequences.
- Done when: a 3-of-5 rule ignores two isolated exceedances and raises on the third, and an injected drift raises an alert at the right priority and clears after recovery.

**4.3 Health roll-up** (UC-08, FR-HLT-01, UCS §6.5)

- Build: an asset takes the worst band and lowest Health of its models; units, areas and sites take the worst band of their children (the Health bar shows the minimum of the children, per PDS), with counts per band; optional weighted roll-up by criticality.
- Test: roll-up unit tests on the demo hierarchy, including Unknown and out-of-service models. I test against the spec rule, not the wireframe numbers, which don't add up (see questions).
- Done when: the roll-up returns the correct result for the demo hierarchy and a model change shows on the next cycle. (Changed in 4.3: the hierarchy endpoint is built in 5.2 with the other asset endpoints, once user login exists.)

**4.4 Spec alignment** (added after a full audit against all Rev A documents)

- Build: bad source quality always excluded (FR-ING-05); paused, retired and errored models Unknown in the roll-up with their reason and last cycle (UCS §6.5, UC-08 2a); alert rules out of service with their model, Normal included, and counting afresh on return (UCS Figure 6); escalation acknowledged again; a per-version lock and a leader check every tick so a cycle is never counted twice; job lock heartbeats, ownership checks and a failure hook so a lost training job ends Failed (ARC Figure 7); ingest keys read only their own history jobs (ARC §1.2); data-quality preview and status judged with the deployed models' training statistics; the NE 107 status, rule and use of every sensor kept with each cycle's outputs, Insufficient-data cycles included; the scoring cycle checked at save (minimum 10 s); the shelving maximum as a setting; out-of-service alerts without priority and listed last.
- Test: each fix has a test that fails without it.
- Done when: every mismatch the audit found is fixed or logged below.

## Phase 5: Security, API and events

In Phase 5 I put access control in front of everything built so far, then expose it through a documented API and a live event stream.

**5.1 Users, access control and audit review** (UC-17, UC-19, FR-SEC-01, -02, FR-AUD-01, ARC §9)

- Build: local users with Argon2id hashing; session cookies (secure, with CSRF protection) for the web and bearer tokens for the API; lockout after 5 failed attempts for 15 minutes; a 30-minute idle timeout; the five roles with optional hierarchy scope; authorisation checked in the application services; API key administration (issue, show once, revoke, rotate); audit query by period, user, entity type and entity, with CSV export; security events (logins, key use, denials) in the logs.
- Test: a matrix test of every role against every endpoint, generated from ARC §9.2, scoped-role tests, lockout and timeout tests, and a check that changes write audit entries.
- Done when: each role can do exactly what the matrix allows and nothing more (AC-07).

**5.2 REST API** (FR-API-01, FR-ALM-03, NFR-PERF-03, ARC §7.3)

- Build: the Release 1 endpoints from ARC §7.3 (assets with roll-up, tags and import, asset types and roles, models and versions, lifecycle actions, scores and outputs, alerts with filter, sort, bulk acknowledge and shelve, data-quality rules and preview, unmapped tags, backfill, jobs, users and keys, audit) plus fleet KPIs; RFC 9457 errors with stable codes; cursor pagination; ISO 8601 UTC times; server-side min/max downsampling per pixel bucket, with raw values below 2 days; the generated OpenAPI 3.1 document. Every UI read goes through this public API.
- Test: contract tests against the OpenAPI schema, downsampling correctness, filtering 1,000 alerts in under 1 s, and a 30-day trend of 20 sensors within budget.
- Done when: `/api/v1/openapi.json` validates and every Release 1 endpoint is covered.

**5.3 Live event stream** (FR-VIS-03, NFR-PERF-02, ARC §7.4)

- Build: the `/api/v1/events` SSE stream with `score.updated`, `alert.changed` and `job.progress` events (`case.changed` is added in 8.4), filtered by the user's scope, with LISTEN/NOTIFY carrying events from the worker role to the web role.
- Test: a client receives a score event within one cycle plus 5 s of the sample being accepted, and only sees events in its scope.
- Done when: a browser can subscribe and see live updates for the demo models.

**5.4 Time-series storage and retention** (FR-RUN-03, NFR-DATA-01, ARC §6.3)

- Build: chunk intervals and compression after 7 days for `sample`, `score` and `sensor_output`; continuous aggregates `sample_1h` and `score_1h` for trends over 30 days; a scheduled retention job (default 24 months raw, 5 years aggregates), configurable by an administrator.
- Test: compression and aggregate policies applied, trend queries switching to aggregates, and the retention job removing only expired data.
- Done when: outputs for any past period within retention can be retrieved, and the retention job test passes.

## Phase 6: Front end for Release 1

In Phase 6 I build every Release 1 screen, following PMP-PDS-001 and the HTML wireframes. Every read uses the public API.

**6.0 Demo story for the screens** (found in the 4.4 audit)

- Build: demo models for P-104A, K-201, P-202, P-205, F-3 and E-110 so every wireframe screen has data; criticality as the wireframes imply (K-201 and F-3 class B); the missing story pieces (P-205 RTN-unacknowledged alert, F-3 Warning, VI-2010 in Function check); TI-1016 not required on K-101; the TI-1012 ramp timed for the 6.5-day forecast (Phase 8).
- Done when: the demo plant produces every state the wireframes show.

**6.1 App shell, design system and accessibility** (PDS §2.2, §3, §5, §6, §8, NFR-USE-02)

- Build: a React, TypeScript and Vite app; React Router with routes mirroring the screen IDs; TanStack Query with an SSE hook that invalidates affected queries; sign-in; the left navigation rail; a top bar with breadcrumb, global time range with time zone, asset search ("/" to focus) and live indicator; every screen state in the URL (deep links); design tokens as CSS custom properties, with dark-theme tokens; StatusChip, HealthScore, HealthBar, TrendChart (an ECharts wrapper enforcing PDS §3.4), TimeRangePicker and ConfirmDialog; keyboard access, focus ring and ARIA live regions. ESLint, front-end unit tests, the build and npm audit are added to CI.
- Test: component tests, a check that no status is shown by colour alone, and keyboard navigation tests.
- Done when: navigation, deep links and status chips match the design spec.

**6.2 Fleet overview and area/unit view** (UC-08, SCR-01, SCR-08, FR-VIS-01, FR-HLT-01)

- Build: the KPI strip (models running, assets in Alert, Watch and Unknown, open cases, sensors in Failure) with click-through to filtered lists; the hierarchy tree with bands, Health bars, active alerts and open cases; the highest-deviation list; recent alerts; the Unknown reason on hover; empty state and stale-data banner; live row highlight; the area/unit view with asset cards and 7-day DI sparklines.
- Test: a Playwright journey from fleet to asset; the fleet view loads in under 2 s for 500 assets; a sensor trend is reachable in three interactions or fewer (NFR-USE-01).
- Done when: both screens match the wireframes on the demo data and update live.

**6.3 Asset analysis** (UC-09, SCR-03, FR-VIS-02, FR-DIA-01, FR-DQ-02)

- Build: the summary card (Health, band, DI, model version, coverage, last scored, alert); DI and Health trends with limits, alert bars and excluded-period shading; top contributors with direction and z; actual versus predicted small multiples with the expected band; the sensor table with NE 107 status; synchronised time range and cursor; the model version selector; paused, retired and insufficient-data states with reasons; "View data" tables for the charts; acknowledge from the page. Exclude sensor and Diagnose come in Phase 8.
- Test: a Playwright journey from an alert to its asset with the alert window selected, and a visual comparison against wireframe 03.
- Done when: the screen matches the wireframe on the demo data and updates live.

**6.4 Alert list** (UC-10, SCR-02, FR-ALM-02, -03)

- Build: a virtualised table with the PDS columns; filters by scope, state, priority, severity, has case and urgency; saved filters per user; default sort unacknowledged first, then priority, then age; bulk acknowledge; shelve with a mandatory reason and duration; row click through to asset analysis.
- Test: a Playwright journey that acknowledges and shelves alerts, and a sorting test.
- Done when: the list matches wireframe 02 and every alert action works and is audited.

**6.5 Models: management, builder and version detail** (UC-05, UC-06, SCR-06, SCR-10, SCR-11, FR-MOD-01, -06, -07)

- Build: the model management list (deployed version, status, last trained, alert rate, actions); the six-step wizard (asset and sensors, training and validation periods, cleanse data, train and validate, alert limits, deploy) with per-step validation, automatic drafts and a resumable training job with progress (until Phase 7 the cleanse step shows the data-quality and operating-mode filters and training runs the baseline job); version detail with configuration, training definition, metrics, playback trends, proposed and active limits, and audit history; lifecycle actions with confirmation.
- Test: a Playwright journey that builds, trains, validates and deploys a model entirely in the UI (AC-02 rehearsal).
- Done when: an engineer can define, train and deploy a model entirely from the UI.

**6.6 Registry, data import and administration** (UC-02, UC-03, UC-04, UC-17, UC-19, SCR-13, SCR-14)

- Build: the hierarchy editor, tag table, asset types with roles and tag mapping, import with validation report, unmapped tags with promote, history import with preview and progress; administration for users and roles, API keys, data-quality defaults and the rule editor with preview, the retention setting, and the audit log viewer with CSV export.
- Test: Playwright journeys for a registry import, a history import and issuing an API key.
- Done when: an empty system can be set up through the UI from a hierarchy file, a tag file and a history file.

## Phase 7: Prediction model

In Phase 7 I replace the placeholder with the real model. It's the riskiest piece, so I've given it its own phase. I'll use the demo data until pilot data arrives.

**7.1 AAKR detector** (UCS §6.3.1, FR-MOD-04, ARC §8.1, §8.3)

- Build: robust scaling; a k-means memory matrix (k from 20 to 200 by silhouette score, plus the min and max vectors per sensor, target 200 to 1,000 vectors, capped at 1,000) with a fixed seed; kernel-weighted prediction on usable sensors; bandwidth selection on the validation period (0.1 to 2.0 × median nearest-neighbour distance); the out-of-envelope flag (99.5th percentile of validation minimum distances); all behind the Detector contract.
- Test: the contract suite, plus accuracy checks on seeded healthy and drifting data, and per-model latency.
- Done when: a model trained on seeded healthy data predicts all sensors, including excluded ones, and the seeded drift shows a rising Deviation Index.

**7.2 Training data and cleansing** (UC-05, FR-MOD-02, -03, UCS §6.4, SCR-06 step 3)

- Build: the data-quality filter, operating-mode filter, per-sensor outlier removal (|robust z| > 4), multivariate removal above the 99.9th percentile of nearest-centroid distance, manual exclusion periods drawn on the trend, retained data per operating cluster, the coverage check and the minimum-data block (2,000 vectors and 50% of the period); the wizard's cleanse step wired to all of these, showing the effect of each rule before training.
- Test: each cleansing step on its own, and the blocked cases with the plain-language error from PDS §6.
- Done when: the wizard shows a summary like wireframe 06 (retained share, effect of each rule, clusters, coverage).

**7.3 Validation and proposed limits** (FR-MOD-06, UCS §6.4)

- Build: hold-out playback exactly as at runtime, per-sensor normalised RMSE and bias, DI percentiles (P50, P95, P99, P99.9), share of cycles outside the envelope, estimated alerts per model-week, proposed limits (DI warning 1.2 × P99, DI alert 1.5 × P99.9 with a 10% minimum, sensor |z| warning 3 and alert 5), and the warning when the estimate exceeds one false alert per model-week (UC-05 8a).
- Test: metrics on seeded data, and the limit formulas against hand-computed values.
- Done when: the validation report is stored with the version and viewable later, and all limits stay editable before deployment.

**7.4 Swap-in and evaluation** (AC-02, AC-03, AC-04)

- Build: AAKR registered as the default detector, the demo models retrained through the wizard, and a replay evaluation of alert timing on the injected faults.
- Test: the AC-03 reference tests repeated end to end with AAKR, and a replay showing the seeded faults are caught before the injected failure with few false alerts.
- Done when: the wizard trains, validates and deploys an AAKR model end to end, and the placeholder is no longer the default.

## Phase 8: Release 2, Diagnose and act

In Phase 8 I add the explanation, forecast and workflow layers, each with its backend and its screens.

**8.1 Sensor exclusions and sensor health** (UC-14, FR-DQ-04, -05, SCR-07)

- Build: manual exclusion with reason and expiry (NE 107 Function check) from the next cycle; override of an automatic status to Good with reason and expiry; automatic expiry; the sensor-health screen with category counts and the non-Good list filtered by category and site, with models affected and scoring use; Exclude sensor on asset analysis. All audited.
- Test: an exclusion takes effect on the next cycle and expires automatically, override and expiry, and the screen filters.
- Done when: the screen matches wireframe 07 on the demo data.

**8.2 Failure-mode library and diagnostics** (UC-09, UC-16, FR-DIA-02, -03, FR-ADV-01, UCS §6.7, SCR-04, SCR-12)

- Build: the failure-mode library per asset type with ISO 14224 codes, symptoms (role, direction, weight) and linked tasks, versioned and audited; signature matching with the UCS §6.7.2 formula, "not evaluated" symptoms and "insufficient evidence" below half the weight, current and as a trend; recommended tasks; the diagnostics half of SCR-04 with the "relative match, not probability" statement; the library screen; Diagnose from asset analysis.
- Test: the match formula against reference cases, including an excluded symptom and insufficient evidence.
- Done when: the seeded bearing-degradation drift ranks thrust-bearing degradation first.

**8.3 Prognostics** (UC-11, FR-PRG-01, -02, UCS §6.8, SCR-04)

- Build: a forecast on a sensor actual, residual or DI with a threshold and fit window (default 7 days); 15-minute means of valid samples; linear and exponential fits (exponential only if adjusted R² improves by at least 0.05); the median crossing from 500 residual-bootstrap refits with a fixed seed; an 80% interval; validity (R² ≥ 0.5, slope towards the threshold); urgency classes; the result stored with the alert and shown in the alert list and asset view; the forecast chart on SCR-04.
- Test: synthetic ramps with known crossings, a flat trend and a trend moving away from the threshold.
- Done when: a forecast on a synthetic ramp returns the analytical crossing time within 5%.

**8.4 Cases** (UC-12, UC-13, FR-CAS-01 to -03, UCS §6.9, SCR-05, SCR-09)

- Build: cases created from one or more alerts (C-nnnn numbers, an alert linked to only one open case, adding an alert to an existing case); priority from the highest linked alert, editable; an immutable snapshot (JSON plus images) of the DI trend, contributions, matches, forecast and data-quality state; activities (comment, attachment up to 20 MB, action with owner, due date and status, state change, assignment); the state model of UCS Figure 7 with a cancel reason; closure with a mandatory outcome and a confirmed failure mode for true findings; a prompt to the model engineer on false alerts; the `case.changed` event; the case list and case detail screens; open cases feeding the fleet KPIs.
- Test: every transition allowed and refused, snapshot immutability after new data, and closure refused without an outcome.
- Done when: the full Detect › Diagnose › Act › Close workflow runs on a replayed event in the UI (AC-06 rehearsal).

**8.5 Notifications** (UC-15, FR-NOT-01, UCS §6.10)

- Build: subscriptions per user (scope, minimum priority, events); e-mail for alert raised, escalated, case assigned, case overdue and ingestion source stale (administrators); deep links; throttling (one per alert per 30 minutes, 20 per user per hour, then a summary); suppression for shelved alerts, out-of-service models and re-scored history; retry with exponential back-off for up to 1 hour; a delivery log visible to administrators. A local mail catcher in the development compose file stands in for the SMTP relay.
- Test: throttling and suppression logic, and SMTP failure with retry.
- Done when: a P1 alert e-mails a subscriber within 2 minutes, once.

**8.6 Asset-type templates** (UC-07, FR-MOD-08)

- Build: model templates per asset type; applying a template to selected assets resolves roles, reports gaps, skips assets missing required roles, creates one draft model per asset and queues training.
- Test: applying a template across 10 assets with deliberate mapping gaps.
- Done when: applying a template to 10 assets creates 10 draft models and a gap report.

**8.7 Remaining Release 2 items** (FR-RUN-05, FR-ING-07, FR-API-02, ARC §7.2)

- Build: re-scoring of a past period as a background job, without notifications, replacing outputs for the selected version; the ingestion-health view (last received per source and tag, throughput, rejections, a stale-source warning within 3 scan intervals, a clock-skew warning above 60 s); the read-only results API `GET /api/v1/results/health` for `results-read` keys.
- Test: a 30-day re-score, a stopped feed raising the stale warning, and a results-read key refused elsewhere.
- Done when: all three work on the demo data.

## Phase 9: Hardening and acceptance

In Phase 9 I prove the system works under realistic conditions and hand it over in a state someone else can run.

**9.1 Packaging and operations** (ARC §9, §10, NFR-PORT-01, NFR-REL-03, NFR-SEC-01, -03)

- Build: a Caddy reverse proxy with TLS, SSE buffering off and a 5 MB ingest limit; the production compose configuration and `.env.example`; `pmp backup` (nightly, 14 daily and 8 weekly copies) and restore; `/readyz` and `/metrics` (Prometheus); the built-in operational alerts (source stale, cycle overrun, job queue older than 10 minutes, backup failure); an image vulnerability scan and SBOM in CI; a documented upgrade sequence.
- Test: a fresh install from the image, and a restore from backup into an empty database.
- Done when: a clean machine runs the full stack from the documented steps (AC-08 rehearsal).

**9.2 Acceptance and replay** (PRD AC-01 to AC-08, ARC §12.1)

- Build: historical replay through scoring with notifications off, the event-based evaluation report, load tests against NFR-PERF-01 to -04, the OWASP ASVS level 1 checklist and a WCAG 2.1 AA check.
- Test: each acceptance criterion run and its result recorded; criteria that depend on client data or the gateway are marked as such.
- Done when: every acceptance criterion has a recorded result, or a recorded reason it's waiting on client data.

**9.3 Handover**

- Build: the gateway interface control document (OI-01), a runbook, a short user guide and release notes.
- Test: someone who hasn't worked on the project follows the runbook and guide without help.
- Done when: the documents are reviewed.

## Stretch (only if Release 1 and 2 are done)

If I finish Release 1 and 2 early, I'll pick up the Release 3 "Should" items and a few optional ones, roughly in this order: MQTT ingestion (FR-ING-02, Should, R1, depends on OI-01), PCA algorithm (FR-MOD-05, Should, R2), scheduled re-forecasts (FR-PRG-03), webhooks and daily digest (FR-NOT-02, -03), library proposals from closed cases (FR-ADV-02), case search (FR-CAS-04), similar cases and fault tree (FR-DIA-04, -05), alert KPIs and reports (FR-ALM-05, FR-VIS-05, SCR-15), asset comparison (FR-VIS-04), calculated tags (FR-MOD-11), a reference third-party plug-in (FR-MOD-09), a health roll-up weighted by criticality (4.3) and OIDC single sign-on (FR-SEC-03). Release 4 items (FR-MOD-10, FR-CAS-05) are out of scope.

## Questions I need answered

None of these block the current work.

**Answered**

- [x] **Scope:** Release 1 and Release 2 are both in scope, delivered by the end of November 2026, as soon as possible.
- [x] **Build order:** front end and backend first on the placeholder, then the prediction model.

**Open: client or management decisions**

- [x] **Model algorithm (phase 7):** Is AAKR still the intended algorithm? Decided (7.4): yes. AAKR is built and is the default; it is the algorithm UCS §6.3.1 specifies, and the median placeholder stays available as a baseline.
- [ ] **Team (all phases):** Am I the only developer, or will someone review code or help with the front end?
- [ ] **Gateway (phase 1.2, OI-01):** Is REST batch confirmed as the transport, and can I get a sample payload or a test feed? Is MQTT needed?
- [ ] **Pilot assets and data (phases 1.4, 7, 9.2, OI-02, OI-03):** Which assets are the pilot, and when can I get 6 months of history plus trip and work-order history? Until then I'm building on synthetic demo data.
- [ ] **Database and hosting (phases 0.3, 9.1, OI-04):** Is PostgreSQL with TimescaleDB approved for production (Timescale License), or should I plan for native partitioning? Where will it be hosted, and which SMTP relay will notifications use?
- [ ] **Priority matrix (phase 4.2, OI-05):** Are criticality classes A, B, C and the P1 to P4 matrix in UCS §6.6 acceptable for the pilot?
- [x] **Stretch items:** Should I keep the Release 3 items as stretch goals, or drop them? Decided (7.4): keep them as stretch. Release 1 and 2 are the commitment for November; stretch work starts only once both pass acceptance.
- [x] **PCA and MQTT (GAP C-04, C-12):** PCA (FR-MOD-05, Should, R2) and MQTT ingestion (FR-ING-02, Should, R1) are in scope in GAP-001 but planned as stretch. OK to defer both? (asked Usama) Decided (7.4): defer both. Both are Should, not Must; REST batch covers ingestion until the gateway transport is confirmed (OI-01), and AAKR covers modelling (FR-MOD-04). The plug-in contract (ADR-09) lets PCA arrive later without changing the pipeline.
- [ ] **Spec changes (all phases):** The documents are Rev A and not yet approved. Who decides on errors and conflicts, and should they be logged as spec changes?

**Decisions I've made while building (tell me if any should change)**

- [x] **Backfill and late window (1.3):** The 7-day late window would block history import, so it applies to live ingestion only, not to backfill.
- [x] **Raw quality code (1.2):** The `quality` column stores the category (Good, Uncertain, Bad), and a separate nullable `quality_code` column keeps the raw OPC UA StatusCode when the gateway sends one, so nothing is lost.
- [x] **Missing sample value (1.2, changed in 6.7):** A sample without a value (OPC UA servers send none with Bad quality) is refused on its own with the reason `no_value`; the rest of its batch is stored. Before 6.7 the whole batch was refused with 400, which could lose up to 10,000 good samples (AC-01).
- [x] **Range for flatline and spike before a model exists (2.1):** Both thresholds are a percentage of the sensor's training range, which only exists once a model is trained. Until then the rules use the instrument range (range_hi − range_lo) and skip the flatline guard (training standard deviation above 1 % of range). From 4.1 scoring passes in the deployed model's training statistics. Effect on the demo data: constant-speed machines' speed sensors show as flatlined until a model is trained, unless set to "used" with an override.
- [x] **Tag groups (2.1):** UC-04 allows overrides "per tag or tag group", but the registry has no groups. Overrides apply at three levels: global, asset-type role (for example the flow sensor on every pump), then the tag itself, the most specific one winning.
- [x] **How a filter names a sensor (3.1):** The spec's example is `II-1001 > 120`, but the registry has no instrument-tag field. Filters name tags by their source name (`K101.II1001.PV > 120`), which is exact; any tag on the model's asset can be used. If a named tag has no usable value, the condition is false, so the cycle is "Not in operating mode". The wizard (6.5) will offer a picker.
- [x] **Where a model's definition lives (3.1):** On a Draft model version (ARC ERD: model_sensor, training_period and mode_filter belong to model_version). Saving again updates the Draft; once a version is trained, saving starts a new Draft version, so trained versions never change.
- [x] **Which training cycles count (3.2):** A cycle is used for training when it is in the operating mode and passes the coverage rule (at least 70 % of sensors usable and every required sensor usable), the same test scoring applies, so the model learns only from cycles it would later score. Unusable values inside a retained cycle are left out, not filled in.
- [x] **Deploying needs a DI alert rule (3.3):** The Health Score is measured against the DI alert limit (DIref = 2 × alert), so a model without a DI rule cannot be deployed; the message says to set it first.
- [x] **Rejecting a Validated version (3.3, changed in 6.7):** The version keeps its artefact, metrics and validation report with the status Rejected (PRD glossary: a model version is immutable); a changed definition is saved as a new version number. Before 6.7 it went back to Draft and its artefact was deleted, so two trained models could share a number.
- [x] **Demo noise (1.4 follow-up, found in 4.1):** Once scoring used each sensor's real training range, four demo signals (K-101 lube-oil pressure, suction pressure, seal-gas dP and axial displacement) tripped the spike rule on up to 27 % of minutes, because the simulator gave them noise that was large compared with their normal swing. Their noise is now realistic, and a unit test checks that no healthy demo tag trips the spike or flatline rule on more than 0.1 % of minutes. Product logic is unchanged.
- [x] **Order of the cycle checks (4.1):** Coverage is checked before the operating mode, as in UCS Figure 5, so when data stops the status says "Insufficient data" rather than "Not in operating mode".
- [x] **Process pool (4.1):** ARC §5.1 allows scoring across a process pool. One process already scores 100 models and 5,000 tags in 5.5 s (budget 30 s), so the pool is not built yet; it is added in Phase 7 if AAKR needs it, with `make perf-scoring` as the check.
- [x] **Sensors that did not move in training (2.3):** The spec gives q = |r| / R and z = r / σ but nothing for R = 0 or σ = 0 (a sensor that was constant in training, such as a fixed-speed machine's speed). R is floored at 1 % of the instrument range and σ at 1 % of R, and the floor is recorded with the sensor's scale.
- [x] **"A sensor z warning active" (2.3, 4.2):** UCS §6.5 makes the band Watch or Alert when a sensor z warning or alert is "active". I read "active" as an active sensor alert (after persistence), the same as in the alert lifecycle. Since 4.2 the band uses the active sensor alerts of usable sensors (before that, each sensor's current |z|).
- [x] **Built-in detectors (2.2):** Built-in algorithms are listed in the code; only third-party plug-ins come through the `pmp.algorithms` entry point. Both pass the same contract suite before use, and a plug-in cannot take a built-in's name.
- [x] **Severity while active (4.2):** An alert escalates from Warning to Alert on the same alert but never drops back to Warning while its condition is active; it ends only by clearing (UCS §6.6 deadband), so operators don't see an alert flap between severities.
- [x] **Which cycles count for persistence (4.2):** Only cycles that were evaluated (status Running) count towards n of m, on-delay and clearing. Insufficient-data and not-in-operating-mode cycles are skipped and leave open alerts as they are.
- [x] **Supersede keeps alerts (4.2):** Deploying a new version of a model keeps its open alerts, since the rules belong to the model, not the version. Out of service only applies when the model has no deployed version (paused or retired); on redeploy those alerts return to Normal and the rules start counting afresh (since 4.4 also for rules that had no open alert).
- [x] **Missing criticality (4.2):** Equipment must have a class, but a model could sit on a higher-level asset without one. Such an asset counts as C, the lowest priority, rather than blocking alerts.
- [x] **Alarm returns while RTN-unacknowledged (4.2):** UCS Figure 6 doesn't say what happens when the condition comes back before anyone acknowledges. The same alert goes back to Active-Unacknowledged (ISA-18.2), rather than a second alert being raised.
- [x] **Shelved alerts keep evaluating (4.2):** While an alert is shelved its rule keeps running, so at expiry (or unshelve) it goes to Active-Unacknowledged if the condition is still active, otherwise to Normal.
- [x] **Unknown in the roll-up (4.3):** Band order, worst first: Alert, Watch, Unknown, Healthy. An asset that can't be assessed never makes its parent look Healthy, and never hides a real Watch or Alert.
- [x] **Unknown in the roll-up (4.3, changed in 4.4):** UCS §6.5 makes Paused, Out of service and Error Unknown, so a paused or errored model counts as Unknown with its reason. A retired model counts as Unknown only while its asset has no other model in service (deployed or paused), so a decommissioned model never greys out an asset another model watches. Models never deployed count for nothing: an asset with none of the above shows "No model" (no band, no Health). (4.3 first showed paused and retired models as "Not monitored"; the audit found that against §6.5.)
- [x] **What the counts count (4.3):** Each node's counts are the monitored assets at or beneath it, by their own band (an asset with two models counts once), so a site reads "Alert 1 · Watch 2 · Healthy 9".
- [x] **Weighted roll-up by criticality (4.3):** Not built. The UCS §6.5 rule is worst-of, the plan marks weighting optional, and it would make the figures harder to explain. Moved to the stretch list.
- [x] **Bad quality is always excluded (4.4):** UC-04 lets users switch rules on and off, but FR-ING-05 says bad-quality samples are always excluded from scoring, so the bad-quality rule can't be switched off. The other rules still can.
- [x] **Out of service per rule (4.4):** Figure 6 moves an alert from Normal to Out of service when the model is paused. Rules have no alert while Normal, so each rule carries its own out-of-service flag (shown in `pmp model show`); open alerts move with it. Shelving details are cleared when a shelved alert goes out of service.
- [x] **Escalation is acknowledged again (4.4):** The spec is silent. An escalation from Warning to Alert returns an acknowledged alert to Active-Unacknowledged (ISA-18.2: a higher severity needs a new acknowledgement). A shelved alert stays shelved.
- [x] **Per-cycle data-quality state (4.4):** `sensor_output.dq_status` holds the NE 107 status (it held usable/excluded before), with the rule and whether the value was used beside it. Outputs are written for Insufficient-data and Not-in-operating-mode cycles too, without predictions, and the Insufficient-data reason names the unusable sensors.
- [x] **Data-quality preview and status (4.4):** Both now use the deployed models' training statistics, as scoring does. `pmp dq status` shows the statuses without storing them (the scheduler stores them), and a stored status is never replaced by one evaluated for an earlier time.
- [x] **Ingest keys and jobs (4.4):** An ingest key may still upload history (it writes samples, which ARC §1.2 allows) but reads only the history jobs it started. Rate limits for history uploads come with 5.2.
- [x] **Lost jobs (4.4):** Workers renew a running job's lock every third of the timeout, only the worker holding a job may finish it, and a job that fails for good tells its module, so a training version never stays in Training.
- [x] **DIref (4.4):** UCS §6.2 calls 2 × the alert limit the default. It stays fixed at 2 × until per-model limits are edited in 7.3, where it becomes a model setting.
- [x] **Settings added (4.4):** `PMP_ALERT_MAX_SHELVE_DAYS` (default 7, UCS §6.6 "configurable maximum").
- [x] **Passwords (5.1):** The spec only asks for Argon2id. Rules: at least 12 characters and not containing the username; no forced character classes (NIST SP 800-63B).
- [x] **Session lifetime (5.1):** Besides the 30-minute idle timeout (ARC §9.3), a session lasts at most 12 hours (`PMP_SESSION_MAX_HOURS`), so a session kept busy all day still needs a fresh sign-in.
- [x] **Role assignments (5.1):** UC-17 assigns "roles and an optional site scope", so a user holds one or more (role, scope) pairs, for example Analyst for SITE-A plus Viewer everywhere. A scope covers the asset and everything beneath it; actions not tied to an asset (users, keys, audit, global data-quality rules, the priority matrix) need an unscoped role.
- [x] **Priority matrix (5.1):** ARC §9.2 doesn't list it. It configures alerting, so it goes with "Models: alert limits": Model Engineer.
- [x] **The command line is trusted (5.1):** `pmp` commands run as the system actor, since whoever can run them can already reach the database. Every web and API action runs as the signed-in user and is checked against the matrix. The first Administrator is created with `pmp user create`.
- [x] **Users are never deleted (5.1):** They are deactivated, so audit entries always name a real account. The table is `app_user` (`user` is reserved in PostgreSQL).
- [x] **Key-use logging (5.1):** Successful API-key use is a security event (ARC §9.3 FR 6), but the gateway calls many times a minute, so each key is logged at most every 5 minutes; failures are always logged.
- [x] **Read scoping (5.1, 5.2):** Scoped users must only see their part of the hierarchy. The matrix gives everyone "view"; filtering lists and the event stream by scope comes with the endpoints in 5.2 and 5.3 (`Principal.visible_scopes`).
- [x] **API paths and trends (5.2):** Numeric IDs in paths, as ARC §7.3 writes them (`/models/{id}`); asset codes are accepted as filters. Trends return at most `px` points (default 1,000, at most 5,000), each with the minimum and maximum of every series; periods under two days come back raw. Series are columns (one list per value).
- [x] **Out of scope is not found (5.2):** A user scoped to part of the hierarchy gets 404 for an asset or model outside it, not 403, so its existence isn't revealed; lists simply leave such items out.
- [x] **Results API (5.2):** `GET /api/v1/results/health` for results-read keys (UC-18) is Release 2 and comes with Phase 8.
- [x] **Alert actions over the API (5.2):** Each action exists for one alert (`/alerts/{id}/ack`) and for many (`/alerts/ack` with `ids`); many is all or nothing (UC-10). Acting on an alert in the wrong state is 409. Shelving takes minutes, capped at the configured maximum.
- [x] **Stale data (5.2):** The fleet KPIs list deployed models with no scored cycle for three cycles plus a minute, for the stale-data banner (PDS SCR-01).
- [x] **Create and change (5.2):** `POST` creates and answers 409 if the code already exists; `PATCH` changes only the fields sent (moving an asset is a `PATCH` of its parent). A lifecycle action is `POST /versions/{id}/{action}`, with 409 when the transition isn't allowed.
- [x] **Rule changes over the API (5.2):** `PUT /dq/rules` previews first and answers 409 with the preview if a tag would be excluded more than 20 % of the time (UC-04 3a); sending `confirm: true` saves anyway, as `--yes` does on the command line.
- [x] **The API document tells the truth (5.2):** FastAPI documents schema errors as 422, but the API answers 400 with problem details (ARC §7.1.1). The document is corrected, and every operation lists problem details as its error response. A contract test calls every documented operation and checks each response against its schema, so the two can't drift apart.
- [x] **The live stream and the session (5.3):** An open stream is not user activity, so it doesn't keep the session alive; when the session ends (idle timeout, sign-out, deactivation) the stream sends `session.ended` and closes. Scope and session are checked again every minute, and at once for an event from a model the stream doesn't know yet (a new deployment).
- [x] **Missed events (5.3):** Events are not replayed: a browser that reconnects re-reads what it shows (the screens' queries are refreshed on reconnect, 6.1). A client that falls 1,000 events behind loses the oldest ones. Job events go to every signed-in user (they carry no asset data).
- [x] **A third aggregate (5.4):** ARC §6.3 names `sample_1h` and `score_1h`. The asset screen's sensor trends (actual, predicted, residual, q, z) need the same for long periods, so there is also `sensor_output_1h`.
- [x] **Retention settings (5.4):** The policy lives in the database (`retention_policy`) so an administrator can change it (ARC §9.2), through the API or `pmp retention`; `PMP_RETENTION_MONTHS` is the raw default used until someone does. Aggregates default to 60 months (ARC §6.3) and may never be kept shorter than raw data.
- [x] **How retention runs (5.4):** "a scheduled job" (ARC §6.3): the scheduler leader runs it once a day, so it never runs twice at once. With TimescaleDB whole chunks are dropped; a chunk is removed once all of it is past the cut-off.
- [x] **History and the aggregates (5.4):** The aggregates' refresh policy only looks back three days, so a history import refreshes the hours it wrote. Imports older than seven days write into compressed chunks, which TimescaleDB supports but which is slower than into uncompressed ones; `make perf-backfill` should be re-run on my Mac.
- [x] **Development sandbox without TimescaleDB (5.4):** Where the extension is missing (my cloud test sandbox only), migration 0011 creates the aggregates as plain views over the same rows and retention deletes rows, so the application code is the same; compression and chunk settings are then checked only on real TimescaleDB.
- [x] **Demo story placement (6.0):** Past history is never scored (only live cycles are), so `pmp demo score` scores the last 24 hours of data cycle by cycle, oldest first, through the same runtime as the worker; cycles already scored are skipped, so it is safe to repeat. `pmp demo models` creates, trains and deploys every file in `data/demo/models` and leaves models already in service alone. Both live in `pmp/demo_story.py`, above the feature modules like the CLI, since they drive several of them.
- [x] **Demo alert limits (6.0):** The median placeholder's Deviation Index on healthy equipment runs at about 5 to 25 % (it ignores load and season). K-101, K-201 and P-202 keep the 15/25 % limits; the others get limits just above their healthy spread (E-110 30/45, P-104B 25/40, P-104A and P-205 20/35, F-3 20/40), so healthy machines stay Healthy. P-104B has no sensor rule (its healthy seasonal drift reached |z| 2.9). Revisited with AAKR and its proposed limits (7.3).
- [x] **Story sizes (6.0):** Scenario sizes are set against the trained demo models' residual spread: P-205 TI-2054 +22 °C for 3 hours (|z| about 8, Alert, then back to normal), F-3 VI-4002 +0.45 mm/s over 20 hours then held (Warning), P-104A TI-1044 +15 °C over 3 days then held (Warning). Held rather than still growing, so the demo shows the same states on the day after.
- [x] **Flatline guard during training (6.0):** UCS §6.1 skips the flatline rule for a sensor whose training standard deviation is under 1 % of its range, but training itself has no training statistics yet, so every steady signal (K-201's rod drop: 0.4 µm noise on a 1,000 µm range) counted as flatlined and K-201 could not train. Training now uses the assessed period's own spread for the guard; once deployed the model's training statistics are used as before.
- [x] **Deferred from 6.0:** VI-2010 in Function check needs the NE 107 "Function check" source (maintenance mode), and the TI-1012 ramp timed for the 6.5-day forecast needs the prognostics model; they move to 8.1 (sensor health) and 8.3 (prognostics), where those features arrive.
- [x] **Front-end tool versions (6.1):** React 18 as PDS §9 names it (React 19 is out, but the spec fixes 18); Vite 8, React Router 7, TanStack Query 5, TypeScript 6.0 (typescript-eslint does not support 7 yet) and ESLint 9 (the accessibility plugin, eslint-plugin-jsx-a11y, does not support 10 yet). All versions are pinned exactly in `package-lock.json`. Prettier formats the code, like Ruff does for Python.
- [x] **Front-end routes (6.1):** One route per screen ID: `/fleet` (SCR-01), `/units/:id` (SCR-08), `/assets/:id` (SCR-03), `/assets/:id/diagnostics` (SCR-04), `/alerts` (SCR-02), `/cases` and `/cases/:id` (SCR-09, -05), `/models`, `/models/:id/build/:step` and `/models/:id/versions/:version` (SCR-10, -06, -11), `/sensors` (SCR-07), `/library` (SCR-12), `/admin` and `/admin/registry` (SCR-14, -13), `/reports` (SCR-15). The navigation rail has the seven items of PDS §2.2; the registry sits under Administration. The time range (`range=7d`, or `from` and `to`) follows the user from screen to screen.
- [x] **Asset search (6.1):** The API has no text search yet, so the search box loads the list of assets the user may see once (on first focus) and matches code first, then name. Equipment opens on asset analysis, anything above it on the area/unit view. Fine for the hundreds of assets in a plant; a server-side search joins if a fleet outgrows it.
- [x] **Development sign-in over HTTP (6.1):** The front-end dev server is plain HTTP, so `backend/.env.example` now sets `PMP_SESSION_COOKIE_SECURE=false` for development; production keeps the default (Secure).
- [x] **Watch colour contrast (6.1, PDS §3.1 and §8):** The spec's `--watch` (#D99A00) is 2.4:1 on white, below the 3:1 for graphics that §8 requires. I keep the colour, outline Watch shapes in `--watch-text` (#9A6C00, 4.6:1) and draw the warning limit line and HealthBar tick in `--watch-text`. A test checks every token's contrast in both themes.
- [x] **Unknown text colour (6.1):** `--unknown` (#7A7F87) is 4.0:1 on white, below 4.5:1 for text, so labels use a darker `--unknown-text` (#5F646B); shapes keep `--unknown`.
- [x] **Build files under /static (6.1):** Vite normally puts the built files under `/assets`, which clashes with the asset analysis route `/assets/:id` once the web role serves the app, so they go under `/static` (cached for a year: their names carry a content hash). Every other path that is not the API or an operations endpoint returns the app, so deep links work from the server too.
- [x] **Live indicator time (6.1):** `GET /api/v1/fleet/kpis` gains `last_cycle` (the newest scoring cycle of a model the user may see), so the indicator shows the last cycle as soon as the page opens, before the first live event.
- [x] **Which reads an event refreshes (6.1):** Screen queries are keyed by domain first (`fleet`, `assets`, `models`, `alerts`, `sensors`, `jobs` ...); `score.updated` refreshes fleet, assets, models, scores, health and sensors; `alert.changed` alerts, fleet, assets and models; `job.progress` jobs and models. Events within a second are batched into one refresh, since all models score in the same second.
- [x] **Design reference page (6.1):** `/design` shows every shared component with sample data in development builds only (not in the production bundle), so the design can be reviewed before the screens use it.
- [x] **Open cases on the fleet overview (6.2):** Wireframe 01 shows an open-cases figure and column, but cases are Release 2 (8.4). The figure is shown as "—" with "Cases arrive in Release 2", and the column joins with the cases.
- [x] **Figures open filtered views (6.2):** "Assets in Alert / Watch / Unknown" filter the hierarchy on the same screen (`/fleet?band=Watch`), showing only the branches that hold such assets; "Models running" opens the model list and "Sensor faults" the sensor health screen filtered to Failure (built in 6.5 and 6.6).
- [x] **What the hierarchy opens with (6.2):** The top level, and every branch holding an asset in Alert, Watch or Unknown, start open; healthy branches start closed, as in the wireframe, so what needs attention shows without a click.
- [x] **Recent alerts (6.2):** The open alerts, newest first, described as the wireframe does ("K-101 Deviation Index high", "P-104A TI1044 residual"); each opens the alert list on that alert (6.4).
- [x] **Fleet speed (6.2):** The roll-up, the runtime statuses, the active versions and the model list each made one query per model; with 500 models the fleet overview took 5 s to read. They now load in a fixed number of queries; the four reads take 0.76 s together in my sandbox, and `make perf-api` checks them against a 1 s budget for 500 assets. The browser half is checked by a Playwright test (500 assets ready in about 1 s, budget 2 s).
- [x] **Browser tests without a database (6.2):** The Playwright journeys run the production build against fixtures for the API, so they are fast and run in CI without the stack; the API's own speed and behaviour are covered by the backend tests and `make perf-api`.
- [x] **Expected band (6.3):** PDS §3.4 defines it as ± the warning limit converted to engineering units (|z| × σ). The new `/models/{id}/latest` read gives each sensor's σ (from the trained artefact) and its |z| warning limit (the sensor rule's, or the default 3), and the chart draws predicted ± warning × σ.
- [x] **Alert bars end when the condition clears (6.3):** An alert can stay open (returned to normal, unacknowledged) long after its condition cleared, so a bar from raise to close would overstate it. Alerts now carry `cleared_at` (the last time the condition returned to normal), and the bar runs from raise to clear, or to now while the condition is active.
- [x] **Shading on the DI trend (6.3):** "Excluded periods" are the runs of cycles that were not scored normally (outside the operating mode, insufficient data, error), each with its status and reason on hover, plus everything since the model was paused or taken out of service (PDS §4.3 states). The new `/models/{id}/status-periods` read returns them.
- [x] **Version comparison (6.3):** The selector lists the versions that were ever in service; choosing one restricts the DI, Health, sensor outputs and shading to that version's cycles (`version` on the reads). Long trends of one version are computed from raw scores, since the hourly aggregates are per model.
- [x] **Charted sensors (6.3):** The two largest contributors are charted by default; selecting a contributor or a row of the sensor table adds or removes its chart (up to six), and the choice is in the URL (`sensors=`).
- [x] **Not yet on the asset screen (6.3):** Exclude sensor and Diagnose (Phase 8) and the forecast row (8.3) are named on the page as Release 2 rather than shown as dead buttons. The comparison with wireframe 03 is a review of screenshots on the demo data, not an automated pixel comparison: fonts differ between my Mac and CI, which would make such a test flaky.
- [x] **Alert list filters (6.4):** Scope, state, priority, severity and rule (DI or sensor), plus "include closed". "Has case" and "urgency" join with cases (8.4) and forecasts (8.3); the columns show "—" until then, with a note. Creating a case from a selection also comes in 8.4.
- [x] **Saved filters (6.4):** Saved by name per user in the browser (keyed by username). A saved filter is only the filter part of the URL, so it can also be bookmarked or shared as a link. Saving them on the server (to follow a user between browsers) can join the user settings that notifications need (8.5).
- [x] **Row click (6.4):** PDS §4.2 says a row click opens asset analysis with the alert window. The asset path in each row is that link (a real link, so it works from the keyboard and opens in a new tab); "Details" opens the alert's own panel beside the list (trace and history), which is also where the fleet's recent alerts lead.
- [x] **Persistence column (6.4):** "n of m" is how many of the rule's last m evaluated cycles met the alert's severity, from the rule's stored memory; "—" while shelved or out of service.
- [x] **Live list (6.4):** Values update in place in the order on screen; alerts that arrive are counted on a "N new alerts · show" button, and the list re-sorts only when the user presses it or changes a filter (PDS §6).
- [x] **Model list figures (6.5):** "Last trained" shows when the version in service reached its status (trained, then deployed); the alert rate is the alerts raised in the last 30 days, as a weekly rate. Both come with the model list (`alerts_30d`, `status_changed_at`).
- [x] **Version audit history (6.5):** The history on SCR-11 is read from the audit trail (the model and the version), which ARC §9.2 opens to administrators only; other roles see a note instead.
- [x] **Builder drafts (6.5):** The server only accepts a complete, valid definition as a Draft, so the builder keeps its input in the browser (per user and model) as it is edited, and saves the Draft when training starts; Discard draft removes the browser copy after confirming. A Draft or Failed version saved again is updated in place, a trained one gets a new version (as in 3.1).
- [x] **Alert limits of a new version (6.5):** Alert rules belong to the model, so the version in service uses them. When a model has a version in service, the builder keeps edited limits until Deploy and saves them just before deploying; for a model with nothing in service they are saved at step 5. A saved definition without `alert_rules` now leaves the model's rules as they are (before, it removed them).
- [x] **Cleanse step until Phase 7 (6.5):** The data-quality, coverage and operating-mode rules are applied exactly as training applies them, with the effect of each (operating mode first, then data quality and coverage). A sensor usable in less than 90 % of the in-mode cycles is flagged. Outlier removal, exclusions drawn on the trend and operating clusters arrive in 7.2, proposed limits and the alert-rate estimate in 7.3. The preview reads the whole training period, so a six-month, 18-sensor model takes about 13 s in the sandbox (as long as training's own data step).
- [x] **Asset-type template (6.5):** Applying the template selects every tag of the asset that is mapped to a role of its asset type; required flags already set are kept. The registry has no "required" flag per role, so none is set by the template.
- [x] **Page heading (6.5):** Only the last breadcrumb is the page's heading; earlier crumbs without a link are plain text (the version page showed two headings).
- [x] **History import from the screen (6.6):** `POST /ingest/backfill` and `/load` accept a signed-in user with the registry permission (ARC §9.2: Model Engineer or Administrator) as well as an ingest key. The registry permission is checked without an asset, so a role scoped to part of the hierarchy cannot import history (a file can hold any tag). An import (not a preview) started by a user is audited; an ingest key still reads only the jobs it started, so it cannot read a user's.
- [x] **Moving an asset (6.6):** The registry allows any parent at a higher level (depth is variable: a unit may sit straight under a site), so the move list offers every higher-level asset outside the asset's own subtree; a new asset may take any level below its parent, or enterprise or site at the top. Criticality and asset type are offered for equipment.
- [x] **Who sees the registry (6.6):** Everyone signed in may look (the reads are open to all roles); the change and import controls are shown only to Model Engineers and Administrators, and the server checks every change again.
- [x] **Administration by role (6.6):** Administrators see users, API keys, retention and the audit log; everyone sees the data-quality rules, which only Model Engineers change (ARC §9.2: the matrix gives rule changes to Model Engineers, not Administrators). The server checks every request again.
- [x] **Data-quality rule editor (6.6):** Each scope (everywhere, an asset-type role, or one tag) lists every parameter as "inherit" or an override, next to the UCS §6.1 default. Saving needs a preview of the exact change first, and a tick to save anyway when some tag would lose more than 20 % of its data (UC-04 3a); the comment is kept with the version.
- [x] **Sensor health before 8.1 (6.6):** SCR-07 is built as a list so the fleet figure "Sensor faults" opens it: NE 107 counts that filter, and every non-Good sensor with the rule, its use in scoring and since when. The models column, overrides and manual exclusions arrive with 8.1.
- [x] **Alerts of a removed rule (6.7):** UCS Figure 6 assumes rules last. When a rule is removed or switched off, its open alerts (Out of service and Shelved included) move to Normal with the action `rule_removed` and the reason in the history, and the rule's persistence memory is cleared; otherwise they could never clear and a sensor alert would hold the band.
- [x] **Sensor status for every tag (6.7):** FR-DQ-02 wants one current category per sensor. Sensors of Deployed models are checked by their scoring cycle; all others (paused or retired models, or none) are checked by the scheduler leader once a minute, with a paused model's training statistics where it has them.
- [x] **Flatline guard without a model (6.7):** UCS §6.1 ties the guard to the training standard deviation. A sensor no deployed model scores has none, so the live check and the rule preview both apply no guard; training data assessment still uses the period's own spread (decision 6.0).
- [x] **Authorise before answering (6.7):** Changes are authorised before existence or validation checks (asset and tag creation, promotion, key rotation, data-quality rule changes), so a refused user learns nothing from the answer. The contract test classifies every operation by its ARC §9.2 permission and makes each call again as every role the matrix refuses, which must get 403 (AC-07).
- [x] **Scoped reads (6.7):** A tag's data-quality rules and the preview list only tags the user may see; a training job is read by users who may see its model's asset; a history import by users who may import.
- [x] **Security headers (6.7):** Every response carries `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: same-origin`, a Content-Security-Policy that keeps the app to its own origin (inline styles allowed for ECharts and React; not on the Swagger page, which loads its own assets), and HSTS when cookies are HTTPS-only.
- [x] **Preview warning (2.1):** The 20 % warning (UC-04 3a) is checked per tag, so one sensor that would be excluded most of the time isn't hidden by an average over many healthy ones.

**Open: spec conflicts (I follow the proposed answer until told otherwise)**

- [ ] **Flatline status (2.1, 6.3):** Wireframes 03 and 07 label a flatlined sensor "Failure", but UCS §6.1 says "Maintenance required". Proposed: follow UCS §6.1.
- [ ] **Alert limits (3.1, 7.3):** ARC §6.2 makes a version immutable once Validated, with limits stored on it, while UCS §6.4 says limits stay editable until deployment. Proposed: proposed limits stay on the immutable version, and active limits live on `alert_rule`, editable and audited.
- [ ] **Hierarchy depth (1.1):** FR-REG-01 specifies five levels (Enterprise › Site › Area › Unit › Equipment) and UC-03 four (Site, Area, Unit, Equipment), but the wireframes skip Area (Site › Unit › Equipment). Built as: variable depth up to five levels.
- [ ] **Unshelve (4.2):** UC-10 1b lets a user end shelving early, but UCS Figure 6 has no transition for it. Proposed: re-evaluate the condition as on expiry. Built this way.
- [x] **Latency vs grace (4.1, 5.3, 9.2; settled in 6.7):** The default grace is now 5 s, so a new score reaches the browser within one cycle plus 5 s of the sample (NFR-PERF-02, FR-VIS-03, AC-05). A gateway that sends late gets its own grace (below).
- [x] **Grace per source (4.1; built in 6.7):** `pmp ingest grace SOURCE SECONDS|default` sets a source's grace (0 to 600 s, an Administrator's change, audited); a model waits for the longest grace among its sensors' sources (ARC §5.1).
- [x] **Retention as a job (6.7):** The scheduler leader queues one retention job at most hourly while it is due; a worker runs it, so a long drop never delays a scoring cycle. Each module names its raw table and hourly aggregate (`RetainedTable`); core no longer knows them.
- [x] **Module layers (6.7):** import-linter checks scoring > alerting > modelling > dataquality > ingestion > registry, each importing only those below it. Scoring calls alerting directly (the decision below), so alerting sits under scoring.
- [ ] **Health limits (6.7):** The Health chart has no warning or alert lines: the band comes from the DI limits (on the DI chart above it) and Health depends on each version's DI reference, which the screens don't have. Proposed: keep as is.
- [x] **Clustering library (7.1):** scikit-learn (KMeans, MiniBatchKMeans above 20,000 rows, silhouette score) rather than our own k-means; it adds scikit-learn and SciPy to the image.
- [x] **Calibration step (7.1):** UCS §6.3.1 tunes AAKR on the validation period, but the contract's `fit()` sees only training data. Added an optional `calibrate(X_validation)` that training calls after `fit()` when a detector has it; the placeholder and plug-ins without it train as before.
- [x] **Outlier handling (7.2):** A sensor value with |robust z| > 4 removes its whole training cycle rather than only that value, so the model remembers only clean, complete states and each rule's count is simple to read.
- [x] **Outlier rule per operating cluster (7.4, decided).** UCS §6.4 says |robust z| > 4 "against the training median and MAD". Applied literally to the full demo history, it removed every turndown (about 5 % of the time at 65 % load) as outliers; AAKR never learnt turndown, normal turndowns scored DI about 150, the proposed limits rose to about 150 / 200 and the models went nearly blind. Built: a first k-means pass finds the operating clusters, and the rule uses each cluster's median and MAD (clusters of fewer than 30 cycles, usually spikes, join the nearest real cluster). Result: proposed limits about 5 to 11 / 14 to 26. Decided: keep it. Reasons: it is the same rule (|robust z| > 4 on median and MAD) applied where the median and MAD mean something; real plants run in several states, so the literal reading would fail on pilot data as it did on the demo; it is reversible in one function if the spec owner disagrees; and it is logged as a spec change for Rev B.
- [x] **Operating clusters (7.2):** UCS §6.4 asks for retained data per operating cluster and a nearest-centroid distance but does not say how the clusters are found. Built: k-means on the robust-scaled sensors, 2 to 8 clusters by silhouette score, seeded; the same clusters give the multivariate rule its distances.
- [x] **DI alert minimum (7.3, corrected in 7.4):** UCS §6.4: DI alert = 1.5 x P99.9 with a minimum of 10 %; DI is a percentage, so the alert limit is never below DI 10. (7.3 had read it as 10 % above the warning, which can never apply: P99.9 >= P99, so 1.5 x P99.9 is always at least 1.25 x the warning.)
- [x] **False-alert estimate (7.3):** Alerting sits above modelling in the import contract, so validation simulates the default alert rule (3 of 5, 10 % deadband for 5 cycles) itself; it counts DI alerts only, since sensor rules are optional and chosen after validation.
- [x] **False alerts in the demo evaluation (7.4, decided).** With AAKR, the UCS §6.4 proposed limits and the default alert rule (3 of 5, 10 % deadband for 5 cycles), the demo raises 11.5 false alerts per model-week against AC-04's starting target of 0.5, mostly from the sensor |z| rules (warning 3, alert 5) chattering: raised, cleared, raised again. Detection is fine (5 of 5, median lead 2.9 days). Options to discuss with Usama: longer persistence or on-delay for sensor rules, sensor sigma from a heavier-tailed estimate, the demo's noise model, or agreeing targets after pilot data as AC-04 allows. Decided: no tuning on the demo; keep the UCS §6.4 limits and the default alert rule, and evaluate again on the pilot history in 9.2 with `pmp evaluate`. Reasons: the false alerts come from the simulator's noise, so tuning to it would fit the demo, not the plant; AC-04 says its targets are agreed after the data review (OI-03); persistence, on-delay and deadband are already editable per rule, so the engineer can tune each model in the wizard; and detection already meets the target (5 of 5).
- [x] **Exclusion expiry (8.1):** FR-DQ-04 requires an expiry but sets no limit. Built: at most 90 days, so an exclusion or override is never forgotten for good; it can be set again when it ends.
- [x] **What an override covers (8.1):** UC-14 1a forces Good over an automatic status. Built: over out of range, flatline, spike and uncertain quality only; bad source quality stays excluded (FR-ING-05), a sensor without data stays Stale, and a manual exclusion is ended rather than overridden. The status shows the rule "override" so the screens can say it is forced.
- [ ] **Deferred from the audit (6.7):** web worker count (one process until 9.1 sizes it); renaming a tag's source (re-register for now); saved alert filters on the server (kept in the browser); persistence filter on the alert list; the `job.progress` event names the job's type `job_type` because `type` already names the event.
- [ ] **Events vs one transaction (4.2):** ARC §4 has alerting consume ScoreComputed events, but ARC §5.1 commits score and alert changes in one transaction. Built: scoring calls the alert engine through its public interface inside the cycle's transaction; the event is still published after commit.
- [ ] **Deploy while paused (3.3):** ARC Figure 7 has no Paused → Superseded edge. Built: deploying a new version supersedes the version in service whether Deployed or Paused, so there is always at most one.
- [ ] **Deadband reference (4.2):** UCS §6.6 doesn't say which limit the deadband applies to. Built: clearing is below the warning limit less the deadband, for both severities.
- [ ] **Manual exclusion order (2.1):** UCS §6.1 puts manual exclusion third (after Bad and Stale); Figure 5 and UC-14 imply it overrides the rules. Built: as §6.1.
- [ ] **Preview per sample (2.1):** UC-04 3a says "> 20 % of samples"; the preview counts per cycle (minute). They differ only for tags not sampled every minute.
- [ ] **Contributions when every residual is zero (2.3):** FR-DIA-01 says contributions add up to 100 %; with every residual exactly zero there is nothing to share, and all are 0.
- [ ] **Wireframes against the UCS (6.x):** P-202 is Unknown in wireframe 01 but its alert is Out of service in 02; TI-1016 is excluded in 04 but not in 03 or 07; the sensor KPI is "sensor faults" (01, FR-VIS-01), "sensors in Failure" (SCR-01) or "Failure" (07); 07 shows a spike as a lasting status though the rule is per sample; UC-09 2a lets a user close an alert, which Figure 6 doesn't allow. Proposed: follow the UCS and settle the screens in Phase 6.
- [x] **Administrator and the registry (5.1):** The ARC §9.2 matrix and UCS give Administrators registry and import rights; the PRD's Administrator row doesn't list them. Decided (7.4): follow ARC §9.2. Reasons: ARC §9.2 is the detailed permission matrix and UCS agrees with it; the PRD role table is a summary; an administrator setting up a site needs to load the registry before any engineer exists; and the contract test checks every endpoint against the matrix.
- [ ] **Not in operating mode (4.1):** UCS §6.5 doesn't give a band for this status. Proposed: no Health value, shown as Unknown with the reason "Not in operating mode", and alert rules not evaluated.
- [ ] **Alert list sort (6.4):** PDS §4.2 says unacknowledged first, but the wireframe caption says priority, then age. Proposed: follow PDS.
- [ ] **Fleet roll-up figures (4.3):** Wireframe 01 shows Site A at 38 while its lowest child is 41. Proposed: test against the UCS §6.5 rule, not the wireframe figures.

## Appendix A: Requirement-to-phase traceability

| Area | Requirement → sub-phase |
| --- | --- |
| Ingestion | ING-01 → 1.2 · ING-02 → stretch · ING-03 → 1.3, 6.6 · ING-04 → 1.2, 1.3 · ING-05 → 1.2 · ING-06 → 1.2, 6.6 · ING-07 → 8.7 |
| Registry | REG-01 to -03 → 1.1, 6.6 · REG-04 → 1.1, 6.6 |
| Data quality | DQ-01 → 2.1, 6.6 · DQ-02 → 2.1, 6.3 · DQ-03 → 2.1, 4.1 · DQ-04, -05 → 8.1 |
| Modelling | MOD-01 → 6.5, 7.4 · MOD-02 → 7.2 · MOD-03 → 3.1, 4.1, 7.2 · MOD-04 → 7.1 · MOD-05 → stretch · MOD-06 → 3.2, 7.3, 6.5 · MOD-07 → 3.3, 6.5 · MOD-08 → 8.6 · MOD-09 → 2.2 (contract), stretch (reference plug-in) · MOD-10 → out (R4) · MOD-11 → stretch |
| Runtime | RUN-01 → 4.1 · RUN-02 → 2.3, 4.1 · RUN-03 → 4.1, 5.4 · RUN-04 → 4.1 · RUN-05 → 8.7 |
| Health and alerts | HLT-01 → 2.3, 4.3, 6.2 · ALM-01 → 3.1, 4.2 · ALM-02 → 4.2, 6.4 · ALM-03 → 5.2, 6.4 · ALM-04 → 4.2 · ALM-05 → stretch |
| Diagnostics | DIA-01 → 2.3, 6.3 · DIA-02, -03 → 8.2 · DIA-04, -05 → stretch |
| Prognostics | PRG-01, -02 → 8.3 · PRG-03 → stretch |
| Advisory | ADV-01 → 8.2 · ADV-02 → stretch |
| Cases | CAS-01 to -03 → 8.4 · CAS-04 → stretch · CAS-05 → out (R4) |
| Notifications | NOT-01 → 8.5 · NOT-02, -03 → stretch |
| Visualisation | VIS-01 → 6.2 · VIS-02 → 6.3 · VIS-03 → 5.3, 6.1 · VIS-04, -05 → stretch |
| API | API-01 → 5.2 · API-02 → 8.7 |
| Security and audit | SEC-01 → 5.1 · SEC-02 → 1.2, 5.1, 6.6 · SEC-03 → stretch · AUD-01 → 0.2, 5.1, 6.6 |
| Non-functional | PERF-01 → 4.1, 9.2 · PERF-02 → 5.3, 9.2 · PERF-03 → 5.2, 9.2 · PERF-04 → 1.2, 9.2 · REL-01 → 0.2, 4.1 · REL-02 → client · REL-03 → 9.1 · SEC-01 → 9.1 · SEC-02 → by design, 9.2 review · SEC-03 → 0.3, 6.1, 9.1, 9.2 · MAIN-01 → 0.1, 0.3 · MAIN-02 → 0.2 · USE-01 → 6.1, 6.2, 9.2 · USE-02 → 6.1, 9.2 · PORT-01 → 0.3, 9.1 · COMP-01 → 1.2, 5.2 · ACC-01 → 4.2 · DATA-01 → 5.4 |
| Use cases | UC-01 → 1.2 · UC-02 → 1.3, 6.6 · UC-03 → 1.1, 6.6 · UC-04 → 2.1, 6.6 · UC-05 → 3.1, 3.2, 6.5, 7.2, 7.3 · UC-06 → 3.3, 6.5 · UC-07 → 8.6 · UC-08 → 4.3, 6.2 · UC-09 → 6.3, 8.2 · UC-10 → 4.2, 6.4 · UC-11 → 8.3 · UC-12, -13 → 8.4 · UC-14 → 8.1 · UC-15 → 8.5 · UC-16 → 8.2 · UC-17 → 5.1, 6.6 · UC-18 → 8.7 · UC-19 → 5.1, 6.6 |
| Screens | SCR-01, -08 → 6.2 · SCR-02 → 6.4 · SCR-03 → 6.3 · SCR-04 → 8.2, 8.3 · SCR-05, -09 → 8.4 · SCR-06, -10, -11 → 6.5 · SCR-07 → 8.1 · SCR-12 → 8.2 · SCR-13, -14 → 6.6 (ingestion health 8.7) · SCR-15 → stretch |
| Acceptance | AC-01 → 9.2 (needs gateway) · AC-02 → 6.5, 7.4, 9.2 · AC-03 → 2.3, 4.2, 7.4 · AC-04 → 7.4, 9.2 (needs client data) · AC-05 → 5.3, 9.2 · AC-06 → 8.4, 9.2 · AC-07 → 5.1 · AC-08 → 9.1 |
