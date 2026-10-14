# PMP Implementation Plan (phase by phase)

Rev B · 14 Oct 2026 · Saiprasad Murali

Rev B changes: checked against the full spec pack (PRD, UCS, PDS, ARC, GAP, design sources). Added missing Release 1 and Release 2 items, moved audit and API keys earlier, added the missing screens, corrected several "Done when" lines, recorded answered questions and new spec conflicts, and added a requirement-to-phase table (Appendix A).

## How we work

The build runs in 10 phases (0 to 9), each split into sub-phases, and nothing moves on until the current sub-phase is built and its tests pass. Phases 0 to 6 build the backend and front end around a placeholder detector. Phase 7 builds the real prediction model. Phase 8 delivers Release 2 (Diagnose and act), and Phase 9 hardens the system and proves acceptance.

**Rules for every sub-phase**

- Build it from the spec pack, citing the use case (UC), functional spec section (UCS §), architecture section (ARC §) or screen (SCR) it implements.
- Test it: unit tests for logic, contract tests for interfaces, integration tests against a real PostgreSQL/TimescaleDB container, and the reference-data checks where the spec gives formulas.
- Done means the "Done when" line is true and the checks run green with one command.
- If the spec is unclear, conflicts with another document, or needs a client decision, stop and ask before building on a guess. Open questions are collected at the end.
- At the end of each phase, send a short update with a demo of what now works.
- Commits and pushes are done by Sai.

**Assumptions**

- Release 1 and Release 2 are both in scope, delivered by the end of November 2026. The week split below is a proposal, not a commitment.
- Backend and front end come first, and the prediction model comes after (instruction from Usama). Until then a placeholder detector, which predicts each sensor as its training median, sits behind the detector plug-in contract (ARC §8.1). The whole pipeline and every screen can be built and demoed on it, and the AAKR model replaces it in Phase 7 without changes elsewhere. Scores before Phase 7 are for demonstration only and do not indicate real anomalies.
- The scoring formulas (residual, q, z, Deviation Index, Health Score) are plain maths and are built early. The placeholder still needs a real training step, because q needs each sensor's training range (P99 − P1) and z needs the residual σ from a validation period.
- Release 3 items are stretch goals, built only if Release 1 and 2 are done (see "Stretch").
- Development environment: macOS on Apple Silicon, Docker Desktop running `timescale/timescaledb:latest-pg16` (PostgreSQL 16), Python 3.12 managed by uv, Node 26. Integration tests run against the database container locally and in CI.
- Until pilot data arrives, everything is built and demonstrated on synthetic demo data (Phase 1.4).

| Phase | Goal | Release | Proposed week |
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

Phase 0 gives a runnable, tested skeleton with the module boundaries enforced, so later phases only add code inside the right module.

**0.1 Repo and tooling** (ARC §4, §12, NFR-MAIN-01)

- Build: repo layout per ARC §12 (backend, frontend, deploy, docs), Python 3.12 project managed by uv, Ruff, mypy, pytest with Hypothesis and coverage, and import-linter contracts for the 13 modules (core, ingestion, registry, dataquality, modelling, scoring, alerting, diagnostics, prognostics, advisory, cases, notifications, reporting), with the `api` package allowed to call module public interfaces only.
- Test: lint, type check and import contracts pass on the empty modules, and a deliberate cross-module import fails the contract.
- Done when: one command runs every check.

**0.2 Core services** (ARC §4, §5.1, §6, §10.2, §10.4)

- Build: configuration from `PMP_*` environment variables, database sessions, Alembic migrations (run on web start behind an advisory lock), in-process event bus, job queue (claimed with SKIP LOCKED, retries, lock expiry), structured JSON logging with request IDs, the append-only audit writer (who, what, when, before and after values) so every later module can audit from day one, and the `pmp web | worker | migrate` commands.
- Test: unit tests for config, event bus and audit writer, and integration tests for job claim, retry, lock expiry and job survival across a process restart (NFR-REL-01).
- Done when: the web role starts and `/healthz` returns OK.

**0.3 Containers and CI** (ARC §10, §12.2, NFR-PORT-01, NFR-SEC-03)

- Build: Dockerfile (one image, both roles), a development compose file with PostgreSQL 16 and TimescaleDB (image pinned), and a CI pipeline running lint, types, import contracts, unit and property tests, integration tests against a TimescaleDB service container, an 80% line-coverage gate on the analytics modules, and pip-audit. Front-end build and npm audit join in 6.1; image scan and SBOM in 9.1.
- Test: the image builds from a clean checkout and a smoke test hits `/healthz`.
- Done when: the pipeline is green on a clean checkout.

## Phase 1: Registry and ingestion

Phase 1 lets plant data flow in: an asset and tag registry, the gateway ingestion endpoint, history import, and a synthetic demo dataset to build and demo against.

**1.1 Registry** (UC-03, FR-REG-01 to -04, ARC §6.2)

- Build: asset hierarchy of variable depth (up to Enterprise › Site › Area › Unit › Equipment) with an ltree path, criticality class A, B or C, create, edit and move; tags with source, source name, description, unit, instrument range, sampling interval and owning asset; asset types with roles and tag-to-role mapping (FR-REG-04 is R2 but needed by templates and diagnostics, so built now); CSV and Excel import with a line-level validation report and atomic commit. Every change is audited.
- Test: hierarchy and move queries, import validation (bad file rejected with line numbers, valid file commits atomically), the unique (source, source name) rule, and a 500-asset import.
- Done when: the demo hierarchy from the wireframes (Site A › Ammonia unit › K-101 with its 18 tags, plus P-104A/B, K-201, P-202) imports from a file.

**1.2 REST ingestion and API keys** (UC-01, FR-ING-01, -04, -05, -06, FR-SEC-02, ARC §7.1.1)

- Build: API keys (stored as hashes, shown once, scope `ingest` or `results-read`, revoke and rotate in the service layer; admin screens come in 6.6); `POST /api/v1/ingest/samples` behind an ingestion adapter interface (ADR-07); limits of 10,000 samples or 5 MB per request, gzip accepted; quality mapping from OPC UA StatusCode severity bits or the strings Good, Uncertain, Bad (omitted means Good); idempotent upsert on (source, tag, ts) into the `sample` hypertable; 7-day late window and 5-minute future tolerance; per-item rejections; responses 202, 400, 401, 403, 413, 429 (with Retry-After) and 503; failed authentication logged; the unmapped-tags list with first-seen time and count, and promotion of an unmapped tag to a registered tag (FR-ING-06); per-source ingestion statistics (last received time, accepted and rejected counts).
- Test: contract tests for the spec payloads, idempotency on resend, each rejection reason, an ingestion key refused on every non-ingestion endpoint, and a 10,000-sample batch.
- Done when: the example batch in ARC §7.1.1 returns the counts shown there, and a 10,000-sample batch returns 202 and is queryable within 5 s.

**1.3 History import** (UC-02, FR-ING-03, ARC §7.1.3)

- Build: `POST /api/v1/ingest/backfill` accepting CSV or Parquet in long format (ts, tag, value, quality) or wide format (ts plus one column per tag); validation and preview (row counts, time range, unmapped columns, line-level errors); skip or overwrite for overlapping samples; loading as a background job with progress; loaded, rejected and duplicate counts. Backfill is not subject to the 7-day late window (see questions).
- Test: both formats, a file with errors, overlap with skip and with overwrite, and count reconciliation.
- Done when: a 12-month, 1-minute file for 50 tags loads without manual intervention and its row counts reconcile.

**1.4 Demo data seeder** (supports UC-02 and all later demos)

- Build: a seeded generator for the wireframe assets (K-101 syngas compressor, BFW pumps P-104A and P-104B, CO2 compressor K-201, carbamate pump P-202) with correlated sensors, operating modes and injected scenarios: healthy, slow drift toward thrust-bearing degradation, flatline, spike, stale data and out-of-range. History loads through 1.3; live data replays through 1.2.
- Test: the same seed gives identical data, and each injected scenario shows up in the raw signals.
- Done when: months of 1-minute history load for every demo asset and a live replay feeds the ingestion endpoint.

## Phase 2: Data quality and scoring pipeline

Phase 2 builds the pipeline that turns sensor readings into a Deviation Index and Health Score. The formulas need no client data, and their tests are the evidence for acceptance criterion AC-03.

**2.1 Data-quality rules** (UC-04, FR-DQ-01 to -03, UCS §6.1)

- Build: the eight rules in the specified order (bad quality, stale, manual exclusion, out of range, flatline, spike, uncertain, good) with their effects (spike excludes the sample for that cycle; flatline configurable to "used"; uncertain used and flagged); default thresholds overridable per tag or tag group, with rules enabled or disabled; rule sets versioned and audited; a preview of the effect on the last 30 days with a warning above 20% excluded; NE 107 status per sensor with the rule that set it, and the SensorStatusChanged event; the model coverage rule (at least 70% usable and every required sensor usable). Manual exclusions are read here; creating them is 8.1.
- Test: unit tests per rule, property-based tests with generated signals, a test that the first matching rule wins, rule clearing when the condition ends, and the preview warning.
- Done when: every row of the UCS §6.1 table has a passing test.

**2.2 Detector contract and placeholder** (UCS §6.3.3, ARC §8.1, ADR-09)

- Build: the Detector contract (fit, predict, save, load, name, version), the plug-in registry through the `pmp.algorithms` entry point, the contract test suite, and the placeholder detector that predicts each sensor as its training median.
- Test: the contract suite (output shape, NaN handling, save and load round trip, determinism with a fixed seed).
- Done when: the pipeline can use any detector that passes the suite, and the placeholder predicts all sensors, including excluded ones.

**2.3 Outputs and health** (UCS §6.2, §6.5, §6.7.1, FR-RUN-02, FR-DIA-01, AC-03)

- Build: residual, relative deviation q (range R = P99 − P1 of cleansed training data), standardised residual z (σ = 1.4826 × MAD of validation residuals), Deviation Index over usable sensors, contributions (sum to 100%, with sign and z), Health Score with DIref = 2 × DI alert limit, band (Healthy, Watch, Alert, Unknown, including sensor-rule states) and coverage.
- Test: a reference dataset in `tests/reference_data` with supplied predictions and expected outputs checked to 1e-6, including the worked example (alert limit 25%: DI 29.5% gives Health 41; DI 15% gives Health 70). The test is independent of the detector.
- Done when: the AC-03 scoring reference test passes.

## Phase 3: Model management

Phase 3 builds model definitions, a baseline training job and the version lifecycle, so an engineer can set up, train, deploy and manage models. Full cleansing and validation metrics arrive in Phase 7.

**3.1 Model definitions and alert rules** (UC-05, FR-MOD-03, ARC §4)

- Build: model records with their sensors and required flags; one or more training periods and a hold-out validation period that may not overlap; operating-mode filter expressions (for example `II-1001 > 120`) parsed by a safe expression evaluator, used later at runtime (4.1) and in training (7.2); alert rules (one DI rule per model, optional sensor |z| rules) with warning and alert limits, persistence, on-delay and deadband.
- Test: definition validation (sensors belong to the asset, required sensors set, periods do not overlap, limits consistent) and the expression evaluator, including rejection of unsafe input.
- Done when: a model for K-101 with its 18 sensors, an operating-mode filter and alert rules can be defined.

**3.2 Baseline training job** (UC-05 steps 3, 7, 8, ARC §5.2)

- Build: a `train` job that assembles data for the training periods, applies the data-quality and operating-mode filters, fits the detector (placeholder for now), computes scaling statistics (medians and robust ranges), plays back the validation period to compute residual σ, writes the artefact and `validation.json`, and sets the version to Validated or Failed with error detail. Seeds are stored in the version parameters (ARC §8.3).
- Test: a successful run on demo data, a failing run that ends in Failed, and reproducibility with the same seed.
- Done when: a K-101 version trains on demo history and reaches Validated with the statistics q and z need.

**3.3 Artefacts and version lifecycle** (UC-06, FR-MOD-07, ARC §5.3, §8.2)

- Build: the artefact folder (algorithm files, `scaling.json`, `manifest.json`, `validation.json`) with SHA-256 verified on every load; the full state model of ARC Figure 7 (Draft, Training, Failed, Validated, Deployed, Paused, Superseded, Retired, and Validated back to Draft when rejected); exactly one Deployed version per model, with deploy superseding the previous one; immutability after Validated except status; the ModelDeployed event and per-worker model caching; every transition audited.
- Test: a tampered artefact refuses to load, every allowed transition works, every invalid one is refused, and transitions write audit entries.
- Done when: a version can be deployed, paused, resumed, superseded and retired through the service layer.

## Phase 4: Runtime and alerting

Phase 4 makes the system live: every deployed model is scored each cycle, alerts are raised and cleared by the ISA-18.2 rules, and health rolls up the asset hierarchy.

**4.1 Scoring runtime** (FR-RUN-01 to -04, FR-MOD-03, ARC §5.1, UCS §6.2)

- Build: a single scheduler leader held by `pg_advisory_lock`; per-model cycles (default 60 s, minimum 10 s) aligned to wall-clock multiples, starting after a grace period (default 20 s); scoring partitioned across a process pool; latest samples at or before the cycle time with sample-and-hold up to the stale limit; data quality, coverage and operating-mode checks before prediction; the runtime statuses Running, Not in operating mode, Insufficient data, Paused, Out of service and Error; the `score` and `sensor_output` hypertables with the envelope flag column (filled by AAKR in Phase 7); score, sensor outputs and alert changes committed in one transaction followed by NOTIFY; missed cycles not back-filled; late data not changing past scores; the ScoreComputed event.
- Test: end-to-end run on the live replay, the timing target (100 models and 5,000 tags scored within 30 s of cycle start, NFR-PERF-01), and a kill-and-restart test showing no duplicate scoring (NFR-REL-01).
- Done when: scores appear every cycle for every demo model, status changes are visible within one cycle, and insufficient-data cases show Unknown instead of a number.

**4.2 Alert engine** (UC-10, FR-ALM-01, -02, -04, NFR-ACC-01, UCS §6.6)

- Build: DI and sensor rules (sensor rules skipped for excluded sensors); persistence (default 3 of the last 5 cycles); on-delay (default 0); deadband clearing (default 10% for 5 cycles); one alert per rule; escalation from Warning to Alert on the same alert; the ISA-18.2 state model of UCS Figure 6, including RTN-unacknowledged, Out of service set automatically on pause or retire and cleared on redeploy; shelving with reason and duration (7-day maximum), unshelve, and re-evaluation at expiry by a scheduled job; alert rules not evaluated while a model has insufficient data (active alerts keep their state); the priority matrix by criticality and severity (FR-ALM-04, R2, built now), configurable, with changes re-prioritising active alerts and audited; the alert event log; a traceability record stored with each raised alert (model version, rule, input sample times, contributions and data-quality states); the AlertChanged event.
- Test: state-machine unit tests for every transition, property-based tests for persistence and deadband, and an AC-03 alert reference test with expected states for given DI sequences.
- Done when: a 3-of-5 rule ignores two isolated exceedances and raises on the third, and an injected drift raises an alert at the right priority and clears after recovery.

**4.3 Health roll-up** (UC-08, FR-HLT-01, UCS §6.5)

- Build: an asset takes the worst band and lowest Health of its models; units, areas and sites take the worst band of their children (Health bar shows the minimum of children per PDS), with counts per band; optional weighted roll-up by criticality.
- Test: roll-up unit tests on the demo hierarchy, including Unknown and out-of-service models. Tested against the spec rule, not the wireframe numbers, which are internally inconsistent (see questions).
- Done when: the hierarchy endpoint returns a correct roll-up and updates within one cycle of a model change.

## Phase 5: Security, API and events

Phase 5 puts access control in front of everything built so far, then exposes it through a documented API and a live event stream.

**5.1 Users, access control and audit review** (UC-17, UC-19, FR-SEC-01, -02, FR-AUD-01, ARC §9)

- Build: local users with Argon2id hashing; session cookies (secure, with CSRF protection) for the web and bearer tokens for the API; lockout after 5 failed attempts for 15 minutes; 30-minute idle timeout; the five roles with optional hierarchy scope; authorisation checked in application services; API key administration (issue, show once, revoke, rotate); audit query by period, user, entity type and entity, with CSV export; security events (logins, key use, denials) in the logs.
- Test: a matrix test of every role against every endpoint, generated from ARC §9.2, scoped-role tests, lockout and timeout tests, and a check that changes write audit entries.
- Done when: each role can do exactly what the matrix allows and nothing more (AC-07).

**5.2 REST API** (FR-API-01, FR-ALM-03, NFR-PERF-03, ARC §7.3)

- Build: Release 1 endpoints from ARC §7.3 (assets with roll-up, tags and import, asset types and roles, models and versions, lifecycle actions, scores and outputs, alerts with filter, sort, bulk acknowledge and shelve, data-quality rules and preview, unmapped tags, backfill, jobs, users and keys, audit) plus fleet KPIs; RFC 9457 errors with stable codes; cursor pagination; ISO 8601 UTC times; server-side min/max downsampling per pixel bucket with raw values below 2 days; the generated OpenAPI 3.1 document. Every UI read goes through this public API.
- Test: contract tests against the OpenAPI schema, downsampling correctness, filtering 1,000 alerts in under 1 s, and a 30-day trend of 20 sensors within budget.
- Done when: `/api/v1/openapi.json` validates and every Release 1 endpoint is covered.

**5.3 Live event stream** (FR-VIS-03, NFR-PERF-02, ARC §7.4)

- Build: `/api/v1/events` SSE stream with `score.updated`, `alert.changed` and `job.progress` events (`case.changed` added in 8.4), filtered by the user's scope, with LISTEN/NOTIFY carrying events from the worker role to the web role.
- Test: a client receives a score event within one cycle plus 5 s of the sample being accepted, and sees only events in its scope.
- Done when: a browser can subscribe and see live updates for the demo models.

**5.4 Time-series storage and retention** (FR-RUN-03, NFR-DATA-01, ARC §6.3)

- Build: chunk intervals and compression after 7 days for `sample`, `score` and `sensor_output`; continuous aggregates `sample_1h` and `score_1h` for trends over 30 days; a scheduled retention job (default 24 months raw, 5 years aggregates), configurable by an administrator.
- Test: compression and aggregate policies applied, trend queries switching to aggregates, and the retention job removing only expired data.
- Done when: outputs for any past period within retention are retrievable, and the retention job test passes.

## Phase 6: Front end for Release 1

Phase 6 builds every Release 1 screen, following PMP-PDS-001 and the HTML wireframes. Every read uses the public API.

**6.1 App shell, design system and accessibility** (PDS §2.2, §3, §5, §6, §8, NFR-USE-02)

- Build: React, TypeScript and Vite app; React Router with routes mirroring screen IDs; TanStack Query with an SSE hook that invalidates affected queries; sign-in; left navigation rail; top bar with breadcrumb, global time range with time zone, asset search ("/" to focus) and live indicator; every screen state in the URL (deep links); design tokens as CSS custom properties, with dark-theme tokens; StatusChip, HealthScore, HealthBar, TrendChart (ECharts wrapper enforcing PDS §3.4), TimeRangePicker and ConfirmDialog; keyboard access, focus ring and ARIA live regions. ESLint, front-end unit tests, build and npm audit added to CI.
- Test: component tests, a check that no status is shown by colour alone, and keyboard navigation tests.
- Done when: navigation, deep links and status chips match the design spec.

**6.2 Fleet overview and area/unit view** (UC-08, SCR-01, SCR-08, FR-VIS-01, FR-HLT-01)

- Build: KPI strip (models running, assets in Alert, Watch and Unknown, open cases, sensors in Failure) with click-through to filtered lists; hierarchy tree with bands, Health bars, active alerts and open cases; highest-deviation list; recent alerts; Unknown reason on hover; empty state and stale-data banner; live row highlight; the area/unit view with asset cards and 7-day DI sparklines.
- Test: Playwright journey from fleet to asset; fleet view loads in under 2 s for 500 assets; a sensor trend is reachable in three interactions or fewer (NFR-USE-01).
- Done when: both screens match the wireframes on the demo data and update live.

**6.3 Asset analysis** (UC-09, SCR-03, FR-VIS-02, FR-DIA-01, FR-DQ-02)

- Build: summary card (Health, band, DI, model version, coverage, last scored, alert); DI and Health trends with limits, alert bars and excluded-period shading; top contributors with direction and z; actual versus predicted small multiples with expected band; sensor table with NE 107 status; synchronised time range and cursor; model version selector; paused, retired and insufficient-data states with reasons; "View data" tables for charts; acknowledge from the page. Exclude sensor and Diagnose are added in Phase 8.
- Test: Playwright journey from an alert to its asset with the alert window selected, and a visual comparison against wireframe 03.
- Done when: the screen matches the wireframe on the demo data and updates live.

**6.4 Alert list** (UC-10, SCR-02, FR-ALM-02, -03)

- Build: virtualised table with the PDS columns; filters by scope, state, priority, severity, has case and urgency; saved filters per user; default sort unacknowledged first, then priority, then age; bulk acknowledge; shelve with mandatory reason and duration; row click to asset analysis.
- Test: Playwright journey that acknowledges and shelves alerts, and a sorting test.
- Done when: the list matches wireframe 02 and every alert action works and is audited.

**6.5 Models: management, builder and version detail** (UC-05, UC-06, SCR-06, SCR-10, SCR-11, FR-MOD-01, -06, -07)

- Build: model management list (deployed version, status, last trained, alert rate, actions); the six-step wizard (asset and sensors, training and validation periods, cleanse data, train and validate, alert limits, deploy) with per-step validation, automatic drafts and a resumable training job with progress; until Phase 7 the cleanse step shows the data-quality and operating-mode filters and training runs the baseline job; version detail with configuration, training definition, metrics, playback trends, proposed and active limits, and audit history; lifecycle actions with confirmation.
- Test: Playwright journey that builds, trains, validates and deploys a model entirely in the UI (AC-02 rehearsal).
- Done when: an engineer can define, train and deploy a model entirely from the UI.

**6.6 Registry, data import and administration** (UC-02, UC-03, UC-04, UC-17, UC-19, SCR-13, SCR-14)

- Build: hierarchy editor, tag table, asset types with roles and tag mapping, import with validation report, unmapped tags with promote, history import with preview and progress; administration for users and roles, API keys, data-quality defaults and the rule editor with preview, retention setting and the audit log viewer with CSV export.
- Test: Playwright journeys for a registry import, a history import and issuing an API key.
- Done when: an empty system can be set up through the UI from a hierarchy file, a tag file and a history file.

## Phase 7: Prediction model

Phase 7 replaces the placeholder with the real model. It is the riskiest piece, so it has its own scheduled phase. It uses the demo data until pilot data arrives.

**7.1 AAKR detector** (UCS §6.3.1, FR-MOD-04, ARC §8.1, §8.3)

- Build: robust scaling; a k-means memory matrix (k from 20 to 200 by silhouette score, plus the min and max vectors per sensor, target 200 to 1,000 vectors, capped at 1,000) with a fixed seed; kernel-weighted prediction on usable sensors; bandwidth selection on the validation period (0.1 to 2.0 × median nearest-neighbour distance); the out-of-envelope flag (99.5th percentile of validation minimum distances); all behind the Detector contract.
- Test: the contract suite, plus accuracy checks on seeded healthy and drifting data, and per-model latency.
- Done when: a model trained on seeded healthy data predicts all sensors, including excluded ones, and the seeded drift shows a rising Deviation Index.

**7.2 Training data and cleansing** (UC-05, FR-MOD-02, -03, UCS §6.4, SCR-06 step 3)

- Build: the data-quality filter, operating-mode filter, per-sensor outlier removal (|robust z| > 4), multivariate removal above the 99.9th percentile of nearest-centroid distance, manual exclusion periods drawn on the trend, retained data per operating cluster, the coverage check and the minimum-data block (2,000 vectors and 50% of the period); the wizard's cleanse step wired to all of these, with the effect of each rule shown before training.
- Test: each cleansing step on its own, and the blocked cases with the plain-language error from PDS §6.
- Done when: the wizard shows a summary like wireframe 06 (retained share, effect of each rule, clusters, coverage).

**7.3 Validation and proposed limits** (FR-MOD-06, UCS §6.4)

- Build: hold-out playback exactly as at runtime, per-sensor normalised RMSE and bias, DI percentiles (P50, P95, P99, P99.9), share of cycles outside the envelope, estimated alerts per model-week, proposed limits (DI warning 1.2 × P99, DI alert 1.5 × P99.9 with a 10% minimum, sensor |z| warning 3 and alert 5), and the warning when the estimate exceeds one false alert per model-week (UC-05 8a).
- Test: metrics on seeded data, and the limit formulas against hand-computed values.
- Done when: the validation report is stored with the version, viewable later, and all limits remain editable before deployment.

**7.4 Swap-in and evaluation** (AC-02, AC-03, AC-04)

- Build: AAKR registered as the default detector, the demo models retrained through the wizard, and a replay evaluation of alert timing on the injected faults.
- Test: the AC-03 reference tests repeated end to end with AAKR, and a replay showing the seeded faults are caught before the injected failure with few false alerts.
- Done when: the wizard trains, validates and deploys an AAKR model end to end, and the placeholder is no longer the default.

## Phase 8: Release 2, Diagnose and act

Phase 8 adds the explanation, forecast and workflow layers, each with its backend and its screens.

**8.1 Sensor exclusions and sensor health** (UC-14, FR-DQ-04, -05, SCR-07)

- Build: manual exclusion with reason and expiry (NE 107 Function check) from the next cycle; override of an automatic status to Good with reason and expiry; automatic expiry; the sensor-health screen with category counts and the non-Good list filtered by category and site, with models affected and scoring use; Exclude sensor on asset analysis. All audited.
- Test: exclusion takes effect on the next cycle and expires automatically, override and expiry, and the screen filters.
- Done when: the screen matches wireframe 07 on the demo data.

**8.2 Failure-mode library and diagnostics** (UC-09, UC-16, FR-DIA-02, -03, FR-ADV-01, UCS §6.7, SCR-04, SCR-12)

- Build: the failure-mode library per asset type with ISO 14224 codes, symptoms (role, direction, weight) and linked tasks, versioned and audited; signature matching with the UCS §6.7.2 formula, "not evaluated" symptoms and "insufficient evidence" below half the weight, current and as a trend; recommended tasks; the diagnostics half of SCR-04 with the "relative match, not probability" statement; the library screen; Diagnose from asset analysis.
- Test: the match formula against reference cases, including an excluded symptom and insufficient evidence.
- Done when: the seeded bearing-degradation drift ranks thrust-bearing degradation first.

**8.3 Prognostics** (UC-11, FR-PRG-01, -02, UCS §6.8, SCR-04)

- Build: forecast on a sensor actual, residual or DI with a threshold and fit window (default 7 days); 15-minute means of valid samples; linear and exponential fits (exponential only if adjusted R² improves by at least 0.05); median crossing from 500 residual-bootstrap refits with a fixed seed; 80% interval; validity (R² ≥ 0.5, slope towards the threshold); urgency classes; the result stored with the alert and shown in the alert list and asset view; the forecast chart on SCR-04.
- Test: synthetic ramps with known crossings, a flat trend and a trend moving away from the threshold.
- Done when: a forecast on a synthetic ramp returns the analytical crossing time within 5%.

**8.4 Cases** (UC-12, UC-13, FR-CAS-01 to -03, UCS §6.9, SCR-05, SCR-09)

- Build: cases created from one or more alerts (C-nnnn numbers; an alert linked to only one open case; add an alert to an existing case); priority from the highest linked alert, editable; immutable snapshot (JSON plus images) of DI trend, contributions, matches, forecast and data-quality state; activities (comment, attachment up to 20 MB, action with owner, due date and status, state change, assignment); the state model of UCS Figure 7 with cancel reason; closure with mandatory outcome and a confirmed failure mode for true findings; a prompt to the model engineer on false alerts; the `case.changed` event; the case list and case detail screens; open cases feeding the fleet KPIs.
- Test: every transition allowed and refused, snapshot immutability after new data, and closure refused without an outcome.
- Done when: the full Detect › Diagnose › Act › Close workflow runs on a replayed event in the UI (AC-06 rehearsal).

**8.5 Notifications** (UC-15, FR-NOT-01, UCS §6.10)

- Build: subscriptions per user (scope, minimum priority, events); e-mail for alert raised, escalated, case assigned, case overdue and ingestion source stale (administrators); deep links; throttling (one per alert per 30 minutes, 20 per user per hour then a summary); suppression for shelved alerts, out-of-service models and re-scored history; retry with exponential back-off for up to 1 hour; delivery log visible to administrators. A local mail catcher in the development compose file stands in for the SMTP relay.
- Test: throttling and suppression logic, and SMTP failure with retry.
- Done when: a P1 alert e-mails a subscriber within 2 minutes, once.

**8.6 Asset-type templates** (UC-07, FR-MOD-08)

- Build: model templates per asset type; applying a template to selected assets resolves roles, reports gaps, skips assets missing required roles, creates one draft model per asset and queues training.
- Test: template application across 10 assets with deliberate mapping gaps.
- Done when: applying a template to 10 assets creates 10 draft models and a gap report.

**8.7 Remaining Release 2 items** (FR-RUN-05, FR-ING-07, FR-API-02, ARC §7.2)

- Build: re-scoring of a past period as a background job, without notifications, replacing outputs for the selected version; the ingestion-health view (last received per source and tag, throughput, rejections, stale-source warning within 3 scan intervals, clock-skew warning above 60 s); the read-only results API `GET /api/v1/results/health` for `results-read` keys.
- Test: a 30-day re-score, a stopped feed raising the stale warning, and a results-read key refused elsewhere.
- Done when: all three work on the demo data.

## Phase 9: Hardening and acceptance

Phase 9 proves the system works under realistic conditions and hands it over in a state someone else can run.

**9.1 Packaging and operations** (ARC §9, §10, NFR-PORT-01, NFR-REL-03, NFR-SEC-01, -03)

- Build: Caddy reverse proxy with TLS, SSE buffering off and a 5 MB ingest limit; production compose configuration and `.env.example`; `pmp backup` (nightly, 14 daily and 8 weekly copies) and restore; `/readyz` and `/metrics` (Prometheus); the built-in operational alerts (source stale, cycle overrun, job queue older than 10 minutes, backup failure); image vulnerability scan and SBOM in CI; documented upgrade sequence.
- Test: a fresh install from the image, and a restore from backup into an empty database.
- Done when: a clean machine runs the full stack from the documented steps (AC-08 rehearsal).

**9.2 Acceptance and replay** (PRD AC-01 to AC-08, ARC §12.1)

- Build: historical replay through scoring with notifications off, the event-based evaluation report, load tests against NFR-PERF-01 to -04, the OWASP ASVS level 1 checklist and a WCAG 2.1 AA check.
- Test: each acceptance criterion run and its result recorded; criteria that depend on client data or the gateway are marked as such.
- Done when: every acceptance criterion has a recorded result, or a recorded reason it is waiting on client data.

**9.3 Handover**

- Build: the gateway interface control document (OI-01), a runbook, a short user guide and release notes.
- Test: someone who has not worked on the project follows the runbook and guide without help.
- Done when: the documents are reviewed.

## Stretch (only if Release 1 and 2 are done)

Release 3 "Should" items and a few optional ones, in rough priority order: MQTT ingestion (FR-ING-02, Should, R1, depends on OI-01), PCA algorithm (FR-MOD-05, Should, R2), scheduled re-forecasts (FR-PRG-03), webhooks and daily digest (FR-NOT-02, -03), library proposals from closed cases (FR-ADV-02), case search (FR-CAS-04), similar cases and fault tree (FR-DIA-04, -05), alert KPIs and reports (FR-ALM-05, FR-VIS-05, SCR-15), asset comparison (FR-VIS-04), calculated tags (FR-MOD-11), a reference third-party plug-in (FR-MOD-09), OIDC single sign-on (FR-SEC-03). Release 4 items (FR-MOD-10, FR-CAS-05) are out of scope.

## Questions to confirm

None of these block Phase 0.

**Answered**

- [x] **Scope:** Release 1 and Release 2 are both in scope, delivered by the end of November 2026, as soon as possible.
- [x] **Build order:** frontend and backend first on the placeholder, then the prediction model (Usama).

**Open: client or management decisions**

- [ ] **Model algorithm (phase 7):** Is AAKR still the intended algorithm?
- [ ] **Team (all phases):** One developer, or will someone review code or help with the front end?
- [ ] **Gateway (phase 1.2, OI-01):** Is REST batch confirmed as the transport, and can we get a sample payload or test feed? Is MQTT needed?
- [ ] **Pilot assets and data (phases 1.4, 7, 9.2, OI-02, OI-03):** Which assets are the pilot, and when can we get 6 months of history plus trip and work-order history? Until then we build on synthetic demo data.
- [ ] **Database and hosting (phases 0.3, 9.1, OI-04):** Is PostgreSQL with TimescaleDB approved for production (Timescale License), or should we plan native partitioning? Where will it be hosted, and which SMTP relay do notifications use?
- [ ] **Priority matrix (phase 4.2, OI-05):** Are criticality classes A, B, C and the P1 to P4 matrix in UCS §6.6 acceptable for the pilot?
- [ ] **Stretch items:** Keep Release 3 items as stretch goals, or drop them?
- [ ] **Spec changes (all phases):** The documents are Rev A and not yet approved. Who decides on errors and conflicts, and are they logged as spec changes?

**Open: spec conflicts (the build follows the proposed answer until told otherwise)**

- [ ] **Flatline status (2.1, 6.3):** Wireframes 03 and 07 label a flatlined sensor "Failure"; UCS §6.1 says "Maintenance required". Proposed: follow UCS §6.1.
- [ ] **Alert limits (3.1, 7.3):** ARC §6.2 makes a version immutable once Validated, with limits stored on it; UCS §6.4 says limits stay editable until deployment. Proposed: proposed limits stay on the immutable version; active limits live on `alert_rule`, editable and audited.
- [ ] **Hierarchy depth (1.1):** FR-REG-01 specifies five levels; UC-03 and the wireframes use Site › Unit › Equipment. Proposed: variable depth up to five levels.
- [ ] **Unshelve (4.2):** UCS Figure 6 has no transition for unshelving early. Proposed: re-evaluate the condition as on expiry.
- [ ] **Not in operating mode (4.1):** UCS §6.5 does not give a band for this status. Proposed: no Health value, shown as Unknown with the reason "Not in operating mode", alert rules not evaluated.
- [ ] **Backfill and late window (1.3):** The 7-day late window would block history import. Proposed: the window applies to live ingestion only, not to backfill.
- [ ] **Alert list sort (6.4):** PDS §4.2 says unacknowledged first; the wireframe caption says priority, then age. Proposed: follow PDS.
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
