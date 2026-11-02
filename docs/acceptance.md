# Acceptance results (PMP-PRD-001 §7, plan 9.2)

Each acceptance criterion with its evidence and result, as of 2 November 2026. Results come
from the demo plant (synthetic data from `pmp demo`, with seeded faults in
`data/demo/events.csv`) until the client's gateway feed and data packages arrive; a
criterion that needs them says so. Rerun the commands to reproduce a result.

| Result | Meaning |
| ------ | ------- |
| Passed | Met on the evidence shown. |
| Rehearsed | The procedure works end to end on demo data; the formal run needs client data or a client environment. |
| Waiting | Cannot be run without the client input named. |
| Not met | Run, and the target was missed: the gap and the next step are given. |

## Acceptance criteria

| AC | Criterion (short) | Result | Evidence |
| -- | ----------------- | ------ | -------- |
| AC-01 | 7 days of live gateway data, no unexplained loss | Waiting: the gateway feed (OI-01) | Ingestion health (Administration → Ingestion health) shows accepted and rejected counts per source and tag, and every rejection has a reason; a stopped feed is warned and e-mailed within 3 scan intervals (8.7). For the run: compare the gateway's sent counts with `pmp_ingest_samples_accepted_total` over the 7 days. Throughput headroom: 37,600 samples/s against 10,000 (NFR-PERF-04). |
| AC-02 | Pilot models built, validated and deployed entirely in the web UI | Rehearsed; waiting: the pilot asset list | Playwright journey "define, train, validate and deploy a model entirely in the UI" (`frontend/e2e/builder.spec.ts`); the 8 demo models were built with the same steps (`pmp demo models` does them from files). |
| AC-03 | Scores, health and alerts reproduce UCS §6 on a reference set | Passed | Reference set of 10 cases with exact expected values, to 1e-6 (`backend/tests/unit/test_scoring_reference.py`); alert state machine reference sequences (`backend/tests/reference_data/alert_reference.json`, run by `test_alert_engine.py`); repeated end to end with AAKR (7.4). Runs in CI on every push. |
| AC-04 | Retrospective evaluation on the DP-04 event history | Not met on demo data; waiting: DP-04 | `pmp evaluate EVENTS.csv` (7.4). Demo, 30-day replay, 8 AAKR models with proposed limits: 5 of 5 detectable events alerted (target 70 %), median lead time 2.9 days, but 11.5 false alerts per model-week against the proposed 0.5. Most false raises come from the per-sensor \|z\| rules. Targets are agreed with the client after the data review (PRD): rerun on DP-04, then tune the sensor rules with the review (decision 7.4). |
| AC-05 | Live dashboard shows a new score within one cycle plus 5 s | Passed | `make perf-latency` on the wall clock: scores reached the browser 3.2 to 4.0 s after their cycle; worst 64.0 s from a sample (budget 65 s). The default scoring grace was lowered from 5 s to 3 s to meet it (9.2). |
| AC-06 | Detect › Diagnose › Act › Close on a replayed historical event | Rehearsed; waiting: a client historical event | On a replayed demo fault: Playwright journey "detect, diagnose, act and close" (`frontend/e2e/case.spec.ts`), the same flow on the database in `backend/tests/integration/test_diagnostics.py`, and by hand from the README's rehearsal section (8.4c). |
| AC-07 | RBAC and audit trail per FR-SEC-01 and FR-AUD-01 | Passed | `backend/tests/integration/test_api_contract.py` calls every API operation and replays each change as every role the ARC §9.2 matrix refuses: all get 403. Audit entries for every change are checked in the module tests; the audit log screen and CSV export (UC-19). See also [the ASVS checklist](security-asvs-l1.md). |
| AC-08 | Clean host installs from the image by the documented procedure | Rehearsed; waiting: a clean client host | CI starts the stack from a fresh image on a fresh runner on every push and checks it through the proxy (`/healthz`, a deep link, the 5 MB limit, one backup). On a developer machine (30 October) one undocumented step surfaced, a database volume left from an earlier stack keeping its old password, and is now in `deploy/README.md`. The formal run follows `deploy/README.md` on the client's host (D-5). |

## Non-functional targets measured

| Target | Measured | Where |
| ------ | -------- | ----- |
| NFR-PERF-01: 100 models, 5,000 tags scored within 50 % of a 60 s cycle | 13.2 s with AAKR (budget 30 s) | `make perf-scoring`, sandbox |
| NFR-PERF-02: sample to browser within one cycle plus 5 s | worst 64.0 s (budget 65 s) | `make perf-latency`, sandbox |
| NFR-PERF-03: 30-day trend of 20 sensors under 3 s | API 1.43 s (budget 1.5 s); browser render 1.9 s from fixtures | `make perf-api` on the TimescaleDB dev database (MacBook Air); Playwright |
| NFR-PERF-03 (plan 5.2): 1,000 alerts filtered under 1 s | 0.07 s | `make perf-api`, MacBook Air |
| Plan 6.2: fleet overview of 500 assets under 2 s | API reads 0.50 s; screen ready in the browser under 2 s | `make perf-api`, MacBook Air; Playwright |
| NFR-PERF-04: 10,000 samples/s through REST | 37,600 samples/s | `make perf-ingest`, sandbox |
| NFR-REL-03: nightly backup, tested restore | Backup restores into an empty database with the same rows and artefacts | `backend/tests/integration/test_backup_restore.py`; CI runs a backup from the stack |
| NFR-SEC: OWASP ASVS level 1 | Met except one item, with a reason | [security-asvs-l1.md](security-asvs-l1.md) |
| NFR-USE: WCAG 2.1 AA | No axe violations on 12 screens, light and dark | [accessibility.md](accessibility.md) |

The sandbox is a 2-vCPU cloud workspace with PostgreSQL but without TimescaleDB, so it is
slower than the reference host (8 vCPU, 32 GB, NFR-PERF-01). All figures are to be
re-confirmed on the client's host with plant data volumes.

## Client inputs needed to close

- OI-01, the gateway interface and a live feed: AC-01, and AC-08 on the client host (D-5).
- The pilot asset list: AC-02.
- DP-04, the event history with detectability: AC-04, and a real event for AC-06.
