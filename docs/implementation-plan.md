# PMP Implementation Plan (phase by phase)

13 Oct 2026 · Sai Prasad

## How we work

The build runs in 10 phases (0 to 9), each split into sub-phases, and nothing moves on until the current sub-phase is built and its tests pass. Phases 0 to 6 build the backend and front end around a placeholder detector. Phase 7 builds the real prediction model. Phase 8 delivers Release 2 (Diagnose and act), and phase 9 hardens the system and proves acceptance.

**Rules for every sub-phase**

- Build it from the spec pack, citing the use case (UC), functional spec section (UCS §) or architecture section (ARC §) it implements.
- Test it: unit tests for logic, contract tests for interfaces, and the reference-data checks where the spec gives formulas.
- Done means the "Done when" line is true and the checks run green with one command.
- If the spec is unclear, conflicts with another document, or needs a client decision, stop and ask before building on a guess. The open questions are collected at the end.
- At the end of each phase, send a short update with a demo of what now works.

**Assumptions**

- Delivery by the end of next month. The week split below is a proposal, not a commitment.
- Backend and front end come first, and the prediction model comes after. Until then a simple placeholder detector, which predicts each sensor as its training median, sits behind the detector plug-in contract (ARC §8.1). The whole pipeline and every screen can be built and demoed on it, and the real AAKR model replaces it in Phase 7 without changes elsewhere. Scores before Phase 7 are for demonstration only and do not indicate real anomalies.
- The scoring formulas (residual, relative deviation, standardised residual, Deviation Index, Health Score) are plain maths and are built early, not deferred with the model.
- The sandbox has no PostgreSQL or Docker, so logic is built and tested against portable code first, and TimescaleDB-specific parts (hypertables, compression) are kept in migrations and verified in the Docker/CI environment.

| Phase | Goal | Release | Proposed week |
| --- | --- | --- | --- |
| 0 Foundations | Runnable skeleton, module boundaries enforced, CI | R1 | 1 |
| 1 Registry and ingestion | Assets, tags, REST ingestion, demo data | R1 | 1 |
| 2 Data quality and scoring pipeline | Rules, detector contract with placeholder, DI and Health verified to 1e-6 | R1 | 1 to 2 |
| 3 Model management | Model definitions, versions, artefacts, manual limits | R1 | 2 |
| 4 Runtime and alerting | 60 s scoring cycle, alert engine, roll-up | R1 | 2 |
| 5 API, events, security | REST, live stream, access control, audit | R1 | 3 |
| 6 Front end | Fleet, asset analysis, model builder, alerts | R1 | 3 |
| 7 Prediction model | AAKR, training and cleansing, validation, proposed limits | R1 | 3 to 4 |
| 8 Diagnose and act | Diagnostics, forecasts, cases, notifications | R2 | 4 (at risk) |
| 9 Hardening and acceptance | Deployment, replay, acceptance criteria, handover | R1 and R2 | 4 |

## Phase 0: Foundations

Phase 0 gives a runnable, tested skeleton with the module boundaries enforced, so later phases only add code inside the right module.

**0.1 Repo and tooling** (ARC §4, §12)

- Build: repo layout (backend, frontend, deploy, docs), Python 3.12 project, Ruff, mypy, pytest, and import-linter contracts for the 13 modules.
- Test: lint, type check and import contracts pass on the empty modules, and a deliberate cross-module import fails the contract.
- Done when: one command runs every check.

**0.2 Core services** (ARC §4, §6)

- Build: configuration, database sessions, Alembic migrations, in-process event bus, job queue (claimed with SKIP LOCKED), logging, and the `pmp web | worker | migrate` commands.
- Test: unit tests for config and the event bus, and an integration test for job claim, retry and lock expiry.
- Done when: the web role starts and `/healthz` returns OK.

**0.3 Containers and CI** (ARC §10, §12.2)

- Build: Dockerfile, compose file with PostgreSQL and TimescaleDB, and a CI pipeline that runs lint, types, import contracts and tests.
- Test: the image builds from a clean checkout and a smoke test hits `/healthz`.
- Done when: the pipeline is green on a clean checkout.

## Phase 1: Registry and ingestion

Phase 1 lets plant data flow in: an asset and tag registry, the gateway ingestion endpoint, and a synthetic demo dataset to build and demo against.

**1.1 Registry** (UC-03, ARC §6.2)

- Build: asset hierarchy with a path column, asset types and roles, tags with unit, range and sampling interval, and CSV import.
- Test: hierarchy queries, import validation, and the unique (source, source name) rule on tags.
- Done when: Site A › Ammonia unit › K-101 can be modelled with its 18 tags.

**1.2 REST ingestion** (UC-01, ARC §7.1.1)

- Build: `POST /api/v1/ingest/samples` with API-key auth, quality mapping (OPC UA StatusCode or Good, Uncertain, Bad), idempotent writes on (source, tag, ts), 7-day late window, 5-minute future tolerance, per-item rejections, and the 202, 400, 401, 413 and 429 responses.
- Test: contract tests for the sample payloads in the spec, idempotency on resend, and each rejection reason such as an unregistered tag.
- Done when: the example batch in ARC §7.1.1 returns the accepted and rejected counts shown there.

**1.3 Demo data seeder** (UC-02)

- Build: a seeded generator for industrial assets modelled on the wireframes (K-101 syngas compressor, BFW pumps P-104A and P-104B, CO2 compressor K-201, carbamate pump P-202) with correlated sensors, operating modes and injected scenarios: healthy, slow drift toward thrust-bearing degradation, flatline, spike and stale data. It loads through the historical backfill path and can replay live.
- Test: the same seed gives identical data, and each injected scenario shows up in the raw signals.
- Done when: months of 1-minute history for a pilot asset load through the backfill path.

## Phase 2: Data quality and scoring pipeline

Phase 2 builds the pipeline that turns sensor readings into a Deviation Index and Health Score, running on a placeholder detector. The formulas need no client data, and their tests are the evidence for acceptance criterion AC-03.

**2.1 Data-quality rules** (UC-04, UCS §6.1)

- Build: the eight rules in the specified order (bad quality, stale, manual exclusion, out of range, flatline, spike, uncertain, good), NE 107 status per sensor, and the model coverage rule (at least 70% of sensors usable and every required sensor usable).
- Test: unit tests per rule, property-based tests with generated signals, and a test that the first matching rule wins.
- Done when: every row of the UCS §6.1 table has a passing test.

**2.2 Detector contract and placeholder** (UCS §6.3.3, ARC §8.1)

- Build: the Detector contract (fit, predict, save, load), the plug-in registry, and a placeholder baseline detector that predicts each sensor as its training median.
- Test: the plug-in contract suite (output shape, NaN handling, save and load round trip, determinism).
- Done when: the pipeline can use any detector that passes the suite, and the placeholder predicts all sensors, including excluded ones.

**2.3 Outputs and health** (UCS §6.2, §6.5, AC-03)

- Build: residual, relative deviation q (using the P99 minus P1 range), standardised residual z (1.4826 times MAD), Deviation Index, contributions, Health Score, band and coverage.
- Test: a reference dataset with supplied predictions and expected outputs checked to 1e-6, including the worked example in the spec (DI 29.5% with a 25% alert limit gives Health 41). The test is independent of which detector produced the predictions.
- Done when: the AC-03 reference test passes.

## Phase 3: Model management

Phase 3 builds model definitions and version handling, so an engineer can set up, deploy and manage models. Training and validation arrive in Phase 7. Until then versions use the placeholder detector and manually entered limits.

**3.1 Model definitions** (UC-05, ARC §4)

- Build: model records with their sensors and required flags, the training period and operating-mode filter stored with each version, and manually entered alert limits.
- Test: validation of definitions (sensors belong to the asset, required sensors are set, limits are consistent).
- Done when: a model for K-101 with its 18 sensors can be defined and saved as a version.

**3.2 Artefacts and versions** (UC-06, ARC §8.2)

- Build: model artefact folder (algorithm files, scaling, manifest, validation), SHA-256 checksum verified on every load, version states (deploy, pause, resume, retire), and immutability after validation.
- Test: a tampered artefact refuses to load, and each state transition is tested, including the invalid ones.
- Done when: a model version can be deployed, paused, resumed and retired through the service layer.

## Phase 4: Runtime and alerting

Phase 4 makes the system live: every deployed model is scored each cycle, alerts are raised and cleared by the ISA-18.2 rules, and health rolls up the asset hierarchy.

**4.1 Scoring runtime** (ARC §5.1, UCS §6.2)

- Build: a scheduler that scores each deployed model every 60 s, sample-and-hold up to the stale limit, writing scores and per-sensor outputs, and the runtime status (insufficient data, paused, error).
- Test: end-to-end run on the seeded live replay, plus a timing check against the cycle-time requirement (NFR-PERF-01).
- Done when: scores appear for every demo model and insufficient-data cases show Unknown instead of a number.

**4.2 Alert engine** (UC-10, UCS §6.6)

- Build: DI rules and optional sensor rules, persistence (default 3 of the last 5 cycles), deadband clearing (default 10% for 5 cycles), one alert per rule, escalation from Warning to Alert on the same alert, the ISA-18.2 state model, shelving (reason required, 7-day maximum), and the priority matrix by asset criticality.
- Test: state machine unit tests, plus property-based tests for persistence and deadband.
- Done when: an injected drift raises an alert at the right priority and clears after recovery.

**4.3 Health roll-up** (UC-08, UCS §6.5)

- Build: an asset takes the worst band and lowest Health of its models, and units, areas and sites take the worst band of their children, with counts per band.
- Test: roll-up unit tests on a mixed hierarchy, including Unknown and out-of-service models.
- Done when: the hierarchy endpoint returns the roll-up shown in the fleet overview wireframe.

## Phase 5: API, events and security

Phase 5 exposes everything built so far through a documented API and a live event stream, and puts access control and audit in front of it.

**5.1 REST API** (UC-18, ARC §7.3)

- Build: endpoints for assets, tags, models and versions, lifecycle actions, scores, sensor outputs, alerts and sensor health, with RFC 9457 error responses, cursor pagination and a generated OpenAPI 3.1 document.
- Test: contract tests against the OpenAPI schema, plus the downsampling of trend queries.
- Done when: `/api/v1/openapi.json` is published and every Release 1 endpoint in ARC §7.3 is covered.

**5.2 Live event stream** (ARC §7.4)

- Build: the `/api/v1/events` SSE stream with score, alert and job events, filtered by the user's scope, with LISTEN/NOTIFY carrying events from the worker role to the web role.
- Test: a client receives a score event within one cycle of it being computed, and sees only events in its scope.
- Done when: a browser can subscribe and see live updates for the demo models.

**5.3 Access control and audit** (UC-17, UC-19, ARC §9)

- Build: local users with Argon2 password hashing, roles per the RBAC matrix in ARC §9.2, scoped API keys, and an append-only audit log of configuration and workflow changes.
- Test: a matrix test of every role against every endpoint, and a check that changes write audit entries.
- Done when: each role can do exactly what the matrix allows and nothing more.

## Phase 6: Front end for Release 1

Phase 6 builds the screens an engineer actually uses, following the design spec (PMP-PDS-001) and the HTML wireframes.

**6.1 App shell and design tokens** (PDS)

- Build: React, TypeScript and Vite app, routing, server-state handling with TanStack Query, design tokens following the neutral-background rule (colour only for abnormal states), and a status chip that always combines shape, text and colour.
- Test: component tests, and a check that no status is shown by colour alone.
- Done when: navigation and status chips match the design spec.

**6.2 Fleet overview and asset analysis** (UC-08, UC-09, wireframes 01 and 03)

- Build: KPI cards, the health hierarchy table, recent alerts, and the asset page with DI trend and limits, excluded-period shading, top contributors, actual versus predicted charts (Apache ECharts) and the sensor table with NE 107 status, all updating live.
- Test: a Playwright journey from the fleet view to an alert on an asset, and a visual comparison against the wireframes.
- Done when: both screens match the wireframes on the demo data.

**6.3 Model builder and alert actions** (UC-05, UC-10, wireframe 06)

- Build: the six-step model wizard (asset and sensors, training period, cleanse data, train and validate, alert limits, deploy), where the cleanse and train steps are wired to the placeholder until Phase 7, plus the alert list with acknowledge and shelve.
- Test: a Playwright journey that defines and deploys a model, and one that acknowledges and shelves an alert.
- Done when: an engineer can define and deploy a model entirely from the UI.

## Phase 7: Prediction model

Phase 7 replaces the placeholder with the real model. It is the riskiest piece, so it gets its own scheduled phase instead of being left for "if there is time". It needs history to train on, so it uses the demo data until the pilot data arrives.

**7.1 AAKR detector** (UCS §6.3.1, ARC §8.1)

- Build: robust scaling, a k-means memory matrix (k from 20 to 200 by silhouette score, plus the min and max vectors per sensor), kernel-weighted prediction on usable sensors, bandwidth selection on the validation period, and the out-of-envelope flag, all behind the Detector contract.
- Test: the plug-in contract suite, plus accuracy checks on seeded healthy and drifting data.
- Done when: a model trained on seeded healthy data predicts all sensors, including excluded ones, and the seeded drift shows a rising Deviation Index.

**7.2 Training data and cleansing** (UC-05, UCS §6.4)

- Build: training data assembly for a chosen period, the data-quality filter, operating-mode expressions, per-sensor outlier removal (robust z above 4), multivariate removal at the 99.9th percentile, manual exclusion periods, and the minimum-data block (2,000 vectors and 50% of the period retained).
- Test: each cleansing step on its own, and the cases where training is blocked.
- Done when: a summary like the model builder wireframe is produced (retained share, effect of each rule).

**7.3 Validation and proposed limits** (UCS §6.4)

- Build: hold-out playback exactly as at runtime, per-sensor RMSE/R and bias, DI percentiles (P50, P95, P99, P99.9), share of cycles outside the envelope, estimated alerts per model-week, and proposed limits (DI warning 1.2 × P99, DI alert 1.5 × P99.9 with a 10% minimum, sensor z warning 3 and alert 5).
- Test: metrics on seeded data, and the limit formulas against hand-computed values.
- Done when: a validation report is produced and all limits remain editable before deployment.

**7.4 Swap-in and evaluation** (AC-03, AC-04)

- Build: AAKR registered as the default detector, the demo models retrained through the wizard, and a replay evaluation of alert timing on the injected faults.
- Test: the AC-03 reference test repeated end to end with AAKR, and a replay showing the seeded faults are caught before the injected failure with few false alerts.
- Done when: the wizard trains, validates and deploys an AAKR model end to end, and the placeholder is no longer the default.

## Phase 8: Release 2, Diagnose and act

Phase 8 starts only when the prediction model is done. It adds the explanation, forecast and workflow layers on top of alerts.

**8.1 Failure-mode library and diagnostics** (UC-09, UC-16, UCS §6.7)

- Build: the failure-mode library with symptoms and tasks, signal contribution, signature matching against current residuals, and recommended tasks.
- Test: matching on seeded fault scenarios, including a symptom whose sensor is excluded.
- Done when: the seeded bearing-degradation drift ranks the right failure mode first.

**8.2 Prognostics** (UC-11, UCS §6.8)

- Build: trend fitting on a chosen sensor or DI, time-to-threshold with an interval, urgency, and scheduled re-forecasts.
- Test: forecasts on synthetic trends with known crossing times, and a flat trend that never crosses.
- Done when: a forecast for the seeded drift returns a crossing time that contains the true one.

**8.3 Cases** (UC-12, UC-13, UCS §6.9)

- Build: case workflow from an alert, activities, an immutable snapshot of the diagnostic state, and closure that requires an outcome.
- Test: workflow transitions, snapshot immutability, and closure refused without an outcome.
- Done when: an alert can be turned into a case and closed with an outcome.

**8.4 Notifications and templates** (UC-15, UC-07, UCS §6.10)

- Build: subscriptions, throttled e-mail and webhook delivery, digests, and asset-type templates that create models for similar assets.
- Test: throttling and digest logic, delivery failures with retry, and template creation across several assets.
- Done when: a raised alert notifies a subscriber once, not repeatedly.

## Phase 9: Hardening and acceptance

Phase 9 proves the system works under real conditions and hands it over in a state someone else can run.

**9.1 Packaging and operations** (ARC §10)

- Build: production compose configuration, environment settings, backup and restore commands, and the health, readiness and metrics endpoints.
- Test: a fresh install from the image, and a restore from backup into an empty database.
- Done when: a clean machine runs the full stack from the documented steps.

**9.2 Acceptance and replay** (PRD AC-01 to AC-08, ARC §12.1)

- Build: historical replay through scoring with notifications off, the event-based evaluation report, and load tests against the performance requirements.
- Test: each acceptance criterion is run and its result recorded; criteria that depend on client data are marked as such.
- Done when: every acceptance criterion has a recorded result, or a recorded reason it is waiting on client data.

**9.3 Handover**

- Build: the gateway interface control document (OI-01), a runbook, a short user guide, and release notes.
- Test: someone who has not worked on the project follows the runbook and the guide without help.
- Done when: the documents are reviewed.

## Questions to confirm

None of these block Phase 0, so the build can start now. The first three decide how far Release 2 can go.

- [ ] **Scope (phase 8):** Is Release 2 (diagnostics, forecasts, cases, notifications) in scope for the end-of-next-month delivery, or Release 1 only?
- [ ] **Placeholder detector (phases 2 and 7):** Is it fine to run on a simple placeholder detector until Phase 7, and to build the scoring formulas (DI, Health) early rather than with the model?
- [ ] **Model timing (phase 7):** When should the prediction model start, and is AAKR still the intended algorithm for it?
- [ ] **Team (all phases):** Is it one developer, or will someone review code or help with the front end?
- [ ] **Gateway (phase 1.2, OI-01):** Is REST batch ingestion confirmed as the transport, and can we get a sample payload or a test feed?
- [ ] **Pilot assets and data (phases 1.3, 7, 9.2, OI-02 and OI-03):** Which assets are the pilot, and when can we get 6 months of history plus trip and work-order history? Until then we build on the synthetic demo data.
- [ ] **Database and hosting (phases 0.3, 9.1, OI-04):** Is PostgreSQL with TimescaleDB approved for production, or should we plan native partitioning? Where will it be hosted, and which SMTP server do notifications use?
- [ ] **Priority matrix (phase 4.2, OI-05):** Are the default criticality classes A, B and C and the P1 to P4 matrix in UCS §6.6 acceptable for the pilot?
- [ ] **Flatline status (phase 6.2):** The wireframe labels a flatlined sensor as "Failure", but UCS §6.1 classes it as "Maintenance required". Until told otherwise, the build follows UCS §6.1.
- [ ] **Spec changes (all phases):** The documents are Rev A and not yet approved. If we find an error or conflict, who decides, and do we log it as a change to the spec?
