# Traceability: requirements and specifications against the build (plan 9.3)

Every requirement and specification item in the six Rev A documents, checked against the
built product on 3 November 2026. It complements the 6.7 audit (phases 0–6) with a
final pass over all phases. Status values:

| Status | Meaning |
| ------ | ------- |
| Met | Built and tested; the evidence is the plan sub-phase (its row in the implementation plan names the code, tests and screens). |
| Met, deviation | Built differently from the letter of the spec, for a logged reason (implementation plan, decisions). |
| Gap, fixed | Found missing in this audit and fixed in sub-phase 9.4. |
| Not built (Should) | An optional Release 1–2 item, not built, with the reason. |
| Out of scope (R3/R4) | Release 3 (stretch list) or Release 4. |
| Client | The client's or gateway owner's responsibility. |

## Summary

- **PRD:** 85 requirements. Release 1–2 "Must": all met (two were incomplete, FR-ALM-03
  and FR-ADV-01, and were fixed in 9.4). Release 1–2 "Should": 4 met, 2 not built (MQTT, PCA). Release 3–4: not in
  scope. Non-functional: all met, one is the client's (NFR-REL-02).
- **UCS:** 19 use cases. All main scenarios and in-scope alternate flows met (two steps,
  UC-09 step 6 and UC-18 step 3, were fixed in 9.4). Library
  proposals (UC-13 step 3, UC-16 1a) and SSO (UC-17 1a) are Release 3. Section 6 formulas
  met (reference tests), except §6.3.2 PCA (not built).
- **PDS:** 14 screens in scope, all built (SCR-02 filters and SCR-11 wording fixed in 9.4).
- **ARC:** followed; every deviation is a logged decision.
- **GAP:** Release 1–2 capabilities closed except C-04's PCA half.
- **Wireframes:** followed (audited in 6.7).

## Gaps found (all fixed in sub-phase 9.4)

| # | Item | What was missing | Fix (9.4) |
| - | ---- | --------------- | ------------ |
| G1 | FR-ALM-03 (Must R1), PDS SCR-02 | The alert list shows persistence, linked case and forecast urgency but cannot filter or sort by them; the PDS lists "has case" and "urgency" filters. | Filters "Urgency" and "Case" and sorts by forecast urgency, persistence and linked case, in the API (`urgency`, `has_case`, `sort`) and the alert list. |
| G2 | FR-ADV-01 (Must R2), UCS UC-09 step 6 | Recommended tasks are shown on diagnostics but cannot be "copied into a case on request". | `POST /cases/{id}/tasks`; on the case, "Add tasks of <mode>" for the snapshot's likely modes adds their tasks as actions, once each. |
| G3 | UCS UC-18 step 3, FR-API-02 | A results-read key cannot call `GET /alerts?state=active`; the use case says the consumer may. | Results-read keys may read `GET /alerts`, with `state=active` for both active states. |
| G4 | PDS SCR-11 | The version page still says proposed limits "arrive with the prediction model (Phase 7)"; they are shown in the validation report above it. | Replaced. |

## Not built and out of scope

- FR-ING-02 MQTT (Should R1): waits on the gateway owner's choice (gateway ICD, open item 1).
- FR-MOD-05 and UCS §6.3.2 PCA (Should R2): AAKR is the default and the UCS's main
  algorithm; PCA would be a second detector behind the existing contract.
- Release 3: FR-MOD-09, -11, ALM-05, DIA-04, -05, PRG-03, ADV-02, CAS-04, NOT-02, -03,
  VIS-04, -05, SEC-03, and the screen parts that depend on them (SCR-04 similar cases and
  scheduled re-forecast, SCR-05 and SCR-12 library proposals, SCR-15 reports, UC-13 step 3
  proposal, UC-16 1a, UC-17 1a SSO). Release 4: FR-MOD-10, FR-CAS-05, C-15, C-26.

## Deviations (built differently, for a logged reason)

Recorded with their reasons under "Decisions" in the implementation plan; the main ones:
scoring grace 3 s instead of the ARC table's 20 s (to meet NFR-PERF-02); a source is stale
after 2 scan intervals (to warn within 3, FR-ING-07); case snapshots stored as data and
redrawn rather than as images (UCS §6.9); some REST paths named differently from ARC §7.3's
selected list (for example `/library` for `/library/modes`, and case changes through
`/cases/{id}/transition` and its siblings), all in the OpenAPI document;
UC-09 2a "close the alert as a sensor issue" is done through the case outcome "Sensor
issue", since ISA-18.2 alerts return to normal by themselves; the false-alert target
(AC-04) is agreed with the client after the data review.

## PMP-PRD-001: functional and non-functional requirements

| ID | Priority | Requirement (short) | Status | Evidence and notes |
| -- | -------- | ------------------- | ------ | ------------------ |
| FR-ING-01 | Must R1 | Accept time-series samples from the OT gateway through an authenticated REST batch endpoint. Each sample carri… | Met | plan 1.2 |
| FR-ING-02 | Should R1 | Optionally subscribe to an MQTT broker topic namespace carrying the same sample schema (JSON). Sparkplug B dec… | Not built (Should) | Transport to be agreed with the gateway owner (OI-01); REST is built. |
| FR-ING-03 | Must R1 | Load historical data in bulk for training, through file upload (CSV, Parquet) in the UI and a backfill API. | Met | plan 1.3, 6.6 |
| FR-ING-04 | Must R1 | Writes are idempotent on (tag, timestamp). Late and out-of-order samples are accepted within a configurable wi… | Met | plan 1.2, 1.3 |
| FR-ING-05 | Must R1 | Preserve the source quality code and map it to Good, Uncertain or Bad using OPC UA status-code semantics. | Met | plan 1.2 |
| FR-ING-06 | Must R1 | Reject samples for unregistered tags with a per-item reason. Record them in an "unmapped tags" list that can b… | Met | plan 1.2, 6.6 |
| FR-ING-07 | Should R2 | Show ingestion health: last received time per source and tag, throughput, rejection counts, and stale-source w… | Met | plan 8.7 |
| FR-REG-01 | Must R1 | Maintain an asset hierarchy Enterprise › Site › Area › Unit › Equipment, aligned to ISA-95 / IEC 62264, with a… | Met | plan 1.1, 6.6 |
| FR-REG-02 | Must R1 | Maintain a tag registry: source name, description, engineering unit, instrument range, expected sampling inter… | Met | plan 1.1, 6.6 |
| FR-REG-03 | Must R1 | Import the hierarchy and tag list from CSV or Excel with a validation report before commit. | Met | plan 1.1, 6.6 |
| FR-REG-04 | Must R2 | Define asset types with standard roles (for example "drive-end bearing temperature") and map each asset's tags… | Met | plan 1.1, 6.6 |
| FR-DQ-01 | Must R1 | Evaluate configurable sensor rules on every scoring cycle: stale, flatline, out of instrument range, rate-of-c… | Met | plan 2.1, 6.6 |
| FR-DQ-02 | Must R1 | Express sensor status in NAMUR NE 107 categories: Good, Failure, Function check, Out of specification, Mainten… | Met | plan 2.1, 6.3 |
| FR-DQ-03 | Must R1 | Exclude sensors in Failure, Out of specification or Function check from scoring automatically. A model continu… | Met | plan 2.1, 4.1 |
| FR-DQ-04 | Must R2 | Allow manual exclusion of a sensor with reason, user and expiry (NE 107 "Function check"). | Met | plan 8.1 |
| FR-DQ-05 | Should R2 | Provide a sensor-health list across all models showing category, rule, duration and impacted models, with over… | Met | plan 8.1 |
| FR-MOD-01 | Must R1 | Provide a web-based model-building wizard: asset, sensors, training periods, cleansing, training, validation,… | Met | plan 6.5, 7.4 |
| FR-MOD-02 | Must R1 | Cleanse training data: automatic robust outlier removal, data-quality filtering, and manual exclusion of perio… | Met | plan 7.2 |
| FR-MOD-03 | Must R1 | Define operating-mode filters as condition expressions (for example "II-1001 \> 120") applied to training and… | Met | plan 3.1, 4.1, 7.2 |
| FR-MOD-04 | Must R1 | Train a normal-behaviour model with the default algorithm (auto-associative kernel regression with a cluster-b… | Met | plan 7.1 |
| FR-MOD-05 | Should R2 | Provide an alternative built-in algorithm (principal component reconstruction). | Not built (Should) | AAKR is built and the default; PCA would be a second detector behind the same contract. |
| FR-MOD-06 | Must R1 | Validate by playback over a hold-out period. Report per-sensor fit, Deviation Index distribution and alert cou… | Met | plan 3.2, 7.3, 6.5 |
| FR-MOD-07 | Must R1 | Version every trained model; support deploy, pause, resume, supersede and retire. Only one version per model i… | Met | plan 3.3, 6.5 |
| FR-MOD-08 | Must R2 | Create models for all assets of a type in one action, from an asset-type model template. | Met | plan 8.6 |
| FR-MOD-09 | Should R3 | Provide a plug-in interface for custom Python algorithms (fit/predict contract). Plug-in models use all downst… | Out of scope (R3/R4) | On the stretch list |
| FR-MOD-10 | Could R4 | Compare two model versions on the same period (champion / challenger). | Out of scope (R3/R4) | Release 4 |
| FR-MOD-11 | Should R3 | Define calculated tags (soft sensors) with an expression engine for use as model inputs. | Out of scope (R3/R4) | On the stretch list |
| FR-RUN-01 | Must R1 | Score each deployed model at its configured cycle (default 60 s, minimum 10 s) using the latest valid samples. | Met | plan 4.1 |
| FR-RUN-02 | Must R1 | For every sensor compute actual, predicted, residual, relative deviation q and standardised residual z. For th… | Met | plan 2.3, 4.1 |
| FR-RUN-03 | Must R1 | Persist all outputs as time series for trends, reports and the API. | Met | plan 4.1, 5.4 |
| FR-RUN-04 | Must R1 | Maintain a runtime status per model: Running, Not in operating mode, Insufficient data, Paused, Out of service… | Met | plan 4.1 |
| FR-RUN-05 | Should R2 | Re-score a historical period on demand (for example after late data or a new version), without raising live no… | Met | plan 8.7 |
| FR-HLT-01 | Must R1 | Show a Health Score (0–100) and band (Healthy, Watch, Alert, Unknown) per model, rolled up to asset, unit, are… | Met | plan 2.3, 4.3, 6.2 |
| FR-ALM-01 | Must R1 | Configure alert rules on DI and on per-sensor z with warning and alert limits, persistence (n of m cycles), on… | Met | plan 3.1, 4.2 |
| FR-ALM-02 | Must R1 | Manage the alert lifecycle per ANSI/ISA-18.2: Active-Unacknowledged, Active-Acknowledged, Returned-to-normal-U… | Met | plan 4.2, 6.4 |
| FR-ALM-03 | Must R1 | Provide an alert list with filtering and sorting by hierarchy, state, priority, severity, age, persistence, li… | Gap, fixed | plan 5.2, 6.4; Fixed in 9.4: filters for linked case and forecast urgency; sorts by urgency, persistence and case (G1). |
| FR-ALM-04 | Must R2 | Derive alert priority (P1–P4) from asset criticality and severity through a configurable matrix. | Met | plan 4.2 |
| FR-ALM-05 | Should R3 | Report alert performance KPIs per ISA-18.2 monitoring: alerts per model per week, standing alerts, shelved cou… | Out of scope (R3/R4) | On the stretch list |
| FR-DIA-01 | Must R1 | Rank signal contributions to the current DI (share of Σq²) with direction and z. | Met | plan 2.3, 6.3 |
| FR-DIA-02 | Must R2 | Maintain a failure-mode library per asset type with symptom signatures (role, expected direction, weight), cod… | Met | plan 8.2 |
| FR-DIA-03 | Must R2 | Compute a signature match score per failure mode for the current state and as a trend. | Met | plan 8.2 |
| FR-DIA-04 | Should R3 | Show a fault-tree view (asset type › failure modes › symptoms) with current match status. | Out of scope (R3/R4) | On the stretch list |
| FR-DIA-05 | Should R3 | Retrieve similar past cases by signature similarity. | Out of scope (R3/R4) | On the stretch list |
| FR-PRG-01 | Must R2 | Forecast time to threshold for a selected sensor or DI by trend regression (linear and exponential) with an 80… | Met | plan 8.3 |
| FR-PRG-02 | Must R2 | Classify urgency from time to threshold using configurable bands (Immediate, High, Medium, Low, None). | Met | plan 8.3 |
| FR-PRG-03 | Should R3 | Re-run forecasts on a schedule for models in Alert. | Out of scope (R3/R4) | On the stretch list |
| FR-ADV-01 | Must R2 | Display recommended inspections and tasks for each matched failure mode. | Gap, fixed | plan 8.2; Fixed in 9.4: "Add tasks of …" on the case copies a mode's tasks as actions (G2). |
| FR-ADV-02 | Should R3 | Allow authorised users to edit the library with version history; closed-case lessons can be proposed as librar… | Out of scope (R3/R4) | On the stretch list |
| FR-CAS-01 | Must R2 | Create a case from one or more alerts and attach a snapshot of trends, contributions, diagnostics and forecast… | Met | plan 8.4 |
| FR-CAS-02 | Must R2 | Run the case workflow Open › Investigating › Action required › Monitoring › Closed (or Cancelled), with assign… | Met | plan 8.4 |
| FR-CAS-03 | Must R2 | Keep an activity log (comments, attachments, actions; who and when). Require closure with an outcome (true fin… | Met | plan 8.4 |
| FR-CAS-04 | Should R3 | Search the case library by asset, mode, outcome and text. | Out of scope (R3/R4) | On the stretch list |
| FR-CAS-05 | Could R4 | Export a case as a CMMS work-request payload (JSON or CSV). | Out of scope (R3/R4) | Release 4 |
| FR-NOT-01 | Must R2 | Send e-mail notifications on alert raise, escalation and case assignment, filtered by subscription (scope, pri… | Met | plan 8.5 |
| FR-NOT-02 | Should R3 | Send webhook notifications (signed JSON) for integration with collaboration tools. | Out of scope (R3/R4) | On the stretch list |
| FR-NOT-03 | Should R3 | Send a daily digest of the fleet state per subscriber. | Out of scope (R3/R4) | On the stretch list |
| FR-VIS-01 | Must R1 | Provide a fleet overview: hierarchy with health bands, KPI strip (models running, assets in Alert/Watch/Unknow… | Met | plan 6.2 |
| FR-VIS-02 | Must R1 | Provide asset analysis: DI and Health trends with limits; actual vs predicted with expected band per sensor; c… | Met | plan 6.3 |
| FR-VIS-03 | Must R1 | Update the live health dashboard automatically at least once per scoring cycle without page reload. | Met | plan 5.3, 6.1 |
| FR-VIS-04 | Should R3 | Compare assets of the same type side by side (health, DI and residuals of a common role). | Out of scope (R3/R4) | On the stretch list |
| FR-VIS-05 | Should R3 | Produce reports: model performance, alert KPIs, case outcomes; export to PDF and CSV. | Out of scope (R3/R4) | On the stretch list |
| FR-API-01 | Must R1 | Expose a documented REST API (OpenAPI 3.1) for hierarchy, models, health, outputs, alerts and cases. | Met | plan 5.2 |
| FR-API-02 | Should R2 | Provide a read-only results interface for the gateway or plant systems to retrieve health, status and active a… | Met | plan 8.7; One call returns all models; since 9.4 the same key reads `GET /alerts?state=active` (G3). |
| FR-SEC-01 | Must R1 | Local user accounts with Argon2id password hashing, session cookies (web) and bearer tokens (API); roles Viewe… | Met | plan 9.1 |
| FR-SEC-02 | Must R1 | Machine credentials (API keys) for the gateway, scoped to ingestion or results-read only, with rotation and re… | Met | plan by design, 9.2 review |
| FR-SEC-03 | Should R3 | Single sign-on through OpenID Connect. | Out of scope (R3/R4) | plan 0.3, 6.1, 9.1, 9.2; On the stretch list |
| FR-AUD-01 | Must R1 | Record an audit trail of configuration changes, model lifecycle, alert and case actions, and user administrati… | Met | plan 0.2, 5.1, 6.6 |
| NFR-PERF-01 |   | Design target on the reference host (8 vCPU, 32 GB RAM, SSD): 100 deployed models and 5,000 tags at a 60 s cyc… | Met | plan 4.1, 9.2 |
| NFR-PERF-02 |   | Latency from sample acceptance to updated health in the browser is no more than one cycle plus 5 s. | Met | plan 5.3, 9.2 |
| NFR-PERF-03 |   | A 30-day trend of 20 sensors renders in under 3 s using server-side downsampling (min/max per pixel bucket). | Met | plan 5.2, 9.2 |
| NFR-PERF-04 |   | Ingestion sustains 10,000 samples/s through the REST batch endpoint. | Met | plan 1.2, 9.2 |
| NFR-REL-01 |   | Accepted samples are durable once 202 is returned. Jobs survive process restart. The scheduler resumes without… | Met | plan 0.2, 4.1 |
| NFR-REL-02 |   | The gateway buffers data during application unavailability and back-fills on reconnection (gateway responsibil… | Client | plan client; Gateway buffering is the gateway owner's; PMP accepts 7 days of late data. |
| NFR-REL-03 |   | Nightly backup of database and artefacts; documented restore achieves RPO 24 h and RTO 4 h for the PoC. | Met | plan 9.1 |
| NFR-SEC-01 |   | TLS 1.2 or higher on all external interfaces. Controls oriented to IEC 62443-3-3 security level 1 (identificat… | Met | plan 9.1 |
| NFR-SEC-02 |   | No write path to control systems. OT integration is inbound-only for data; results are pulled by, or published… | Met | plan by design, 9.2 review |
| NFR-SEC-03 |   | Web application meets OWASP ASVS level 1. Dependencies are scanned on every build; no known critical vulnerabi… | Met | plan 0.3, 6.1, 9.1, 9.2 |
| NFR-MAIN-01 |   | Modular monolith with module boundaries enforced by import contracts in CI. Analytics modules have at least 80… | Met | plan 0.1, 0.3 |
| NFR-MAIN-02 |   | Schema changes only through versioned migrations. All configuration through environment variables or the datab… | Met | plan 0.2 |
| NFR-USE-01 |   | Displays follow ANSI/ISA-101.01 principles: neutral background, colour reserved for abnormal states. A sensor … | Met | plan 6.1, 6.2, 9.2 |
| NFR-USE-02 |   | WCAG 2.1 AA contrast. Status is never conveyed by colour alone (shape and text are always present). | Met | plan 6.1, 9.2 |
| NFR-PORT-01 |   | One container image runs both roles on Linux x86-64 and is deployed with docker compose. No external services … | Met | plan 0.3, 9.1 |
| NFR-COMP-01 |   | Timestamps stored in UTC (ISO 8601 at interfaces). Units are carried per tag. The API is described in OpenAPI … | Met | plan 1.2, 5.2 |
| NFR-ACC-01 |   | Every alert is traceable to its model version, rule, input samples, contributions and data-quality state at th… | Met | plan 4.2 |
| NFR-DATA-01 |   | Raw samples and outputs retained for a configurable period (default 24 months). Compression applies to chunks … | Met | plan 5.4 |


## PMP-UCS-001: use cases

| UC | Main scenario | Alternate flows | Notes |
| -- | ------------- | --------------- | ----- |
| UC-01 Ingest live data | Met (1.2) | 2a, 2b, 3a, 5a, 5b met; MQTT alternative not built | |
| UC-02 Load historical data | Met (1.3, 6.6) | 2a, 3a met | |
| UC-03 Configure hierarchy and tags | Met (1.1, 6.6) | 1a, 2a met | |
| UC-04 Configure data-quality rules | Met (2.1, 6.6) | 3a met | |
| UC-05 Build, train and validate | Met (3.x, 6.5, 7.x) | 6a, 7a, 8a met; no overlapping periods enforced | |
| UC-06 Manage model lifecycle | Met (3.3, 6.5); step 4 re-score (8.7) | 1a, 1b met | |
| UC-07 Templates | Met (8.6) | 2a met | |
| UC-08 Monitor fleet health | Met (4.3, 6.2) | 2a met | |
| UC-09 Investigate an alert | Met (6.3, 8.2, 9.4) | 2a via case outcome; 3a, 4a met | Step 6 tasks fixed in 9.4 |
| UC-10 Acknowledge or shelve | Met (4.2, 6.4) | 1a, 1b met; 7-day maximum | |
| UC-11 Forecast | Met (8.3) | 2a met | |
| UC-12 Cases | Met (8.4) | 1a, 3a met; automatic states | |
| UC-13 Close a case | Met (8.4) | 2a met | Step 3 library proposal is R3 |
| UC-14 Sensor exclusions | Met (8.1) | 1a met | |
| UC-15 Notifications | Met (8.5) | 3a met | |
| UC-16 Failure-mode library | Met (8.2) | 1a is R3 | |
| UC-17 Users and credentials | Met (5.1, 6.6) | 1a is R3 (SSO) | |
| UC-18 Results via API | Met (8.7, 9.4) | 1a met | |
| UC-19 Audit trail | Met (5.1, 6.6) | — | |

Section 6: §6.1 data-quality rules (2.1), §6.2 outputs and §6.5 bands (2.3, AC-03 reference
set to 1e-6), §6.3.1 AAKR (7.1), §6.3.2 PCA not built, §6.3.3 plug-in contract (2.2; the
reference plug-in is R3), §6.4 cleansing and limits (7.2, 7.3), §6.6 alert logic (4.2,
reference sequences), §6.7.1–2 contributions and matching (2.3, 8.2), §6.7.3 R3,
§6.8 prognostics (8.3), §6.9 cases (8.4), §6.10 notifications (8.5).

## PMP-PDS-001: screens

| Screen | Status | Notes |
| ------ | ------ | ----- |
| SCR-01 Fleet overview | Met (6.2) | KPI strip, hierarchy sort by band or health, live highlight, stale banner |
| SCR-02 Alert list | Met (6.4, 9.4) | Columns, filters (incl. has case and urgency since 9.4), bulk actions, saved filter, default sort |
| SCR-03 Asset analysis | Met (6.3) | |
| SCR-04 Diagnostics and forecast | Met (8.2, 8.3) | Similar cases and scheduled re-forecast are R3 |
| SCR-05 Case detail | Met (8.4) | Library proposal is R3 |
| SCR-06 Model builder | Met (6.5, 7.x) | |
| SCR-07 Sensor health | Met (8.1) | |
| SCR-08 Area / unit view | Met (6.2) | |
| SCR-09 Case list | Met (8.4) | Text search is R3 (FR-CAS-04) |
| SCR-10 Model management | Met (6.5) | |
| SCR-11 Model version detail | Met (6.5, 7.3, 9.4) | |
| SCR-12 Failure-mode library | Met (8.2) | Proposals are R3 |
| SCR-13 Registry and import | Met (6.6) | |
| SCR-14 Administration | Met (6.6, 8.5, 8.7, 9.1) | |
| SCR-15 Reports | Out of scope (R3) | |

Global (§2–3): navigation rail, top bar, deep links, colour tokens with a dark theme,
status shapes, chart conventions (expected band, limits, excluded periods, bad-data
ticks, alert bar, forecast cone, synchronised cursor, server-side downsampling): met
(6.1–6.4, 8.3).

## PMP-ARC-001: architecture

Modular monolith with import contracts (0.1, CI), one image with web, worker and backup
roles (0.3, 9.1), PostgreSQL with TimescaleDB, hypertables, aggregates and retention
(0.2, 5.4), scoring leader with advisory locks (4.1), events through LISTEN/NOTIFY and SSE
(5.3), interfaces §7.1–7.2 (1.2, 1.3, 8.7; MQTT not built), REST API §7.3 (5.2), security
§9 with the role matrix (5.1, contract test), deployment, configuration, observability and
upgrade §10 (9.1). Met, with the deviations listed above.

## PMP-GAP-001: parity matrix

Release 1–2 capabilities C-01 to C-08, C-11 to C-14, C-16 to C-25 (their R1–R2 parts),
C-27 to C-31 and C-33: closed by the requirements above. C-04: AAKR built, PCA not.
C-09, C-10 and the R3 parts of C-18, C-21 to C-25, C-27: Release 3. C-15, C-26: Release 4.
C-32 and C-34: not in a release.
