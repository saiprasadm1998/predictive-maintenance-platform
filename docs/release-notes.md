# Release notes

## PMP 0.1.0 (November 2026)

The first release of the Predictive Maintenance Platform for Lean Automation FZE: PRD
Release 1 and Release 2. Image `pmp:0.1.0`, database migrations 0001 to 0021.

### What it does

- **Data in:** live samples from the OT gateway over REST (API key, batches up to 10,000
  samples, late data up to 7 days, OPC UA quality), history imports (CSV, Parquet), an
  asset and tag registry with asset types and roles, and NE 107 data-quality rules per
  sensor with manual exclusions. Ingestion health per source and tag, with stale-source and
  clock-skew warnings.
- **Models:** normal-behaviour models (AAKR by default, a median baseline) built in a
  six-step wizard with data cleansing, validation and proposed limits; versions with a
  lifecycle (deploy, pause, retire), asset-type templates to create many at once, and
  re-scoring of past periods.
- **Scoring:** every model every 60 s: Deviation Index, Health, band, per-sensor
  contributions, operating modes and coverage, with the runtime status always visible.
- **Alerts:** ISA-18.2 lifecycle with persistence, deadband, escalation, priority from
  criticality and severity, acknowledge and shelve.
- **Diagnosis and prognosis:** failure-mode library (ISO 14224 codes) with symptom
  matching, and time-to-limit forecasts with an urgency.
- **Work:** cases from alert to closed work with an evidence snapshot, actions,
  attachments and outcomes; a false alert asks for a model review.
- **People:** five roles scoped to the hierarchy, audit trail, e-mail notifications with
  throttling and an hourly summary.
- **Plant systems:** current health of every model in one call (`/results/health`).
- **Operations:** Docker images behind a Caddy reverse proxy with TLS, nightly backups with
  restore, Prometheus metrics, built-in operational alerts, SBOM and vulnerability scan
  per build, a documented upgrade sequence.

### Measured

On the reference load (100 models, 5,000 tags, 60 s cycle): scoring 13.2 s per cycle,
ingestion 37,600 samples/s, a new score in the browser within one cycle plus 4 s, a
30-day trend of 20 sensors in 1.4 s from the API. Measured on a development machine;
to be confirmed on the client's host. Details in [acceptance.md](acceptance.md).

### Known limitations

- **False alerts on the demo data:** 11.5 per model-week against a proposed 0.5, mostly
  from per-sensor rules; detection was 5 of 5 faults with a median 2.9 days' warning. To
  be tuned on the client's event history (AC-04).
- **Passwords are not checked against breach lists** (ASVS 2.1.7): the host has no
  internet access. Length and lockout rules apply.
- **MQTT ingestion is not built**; REST is the transport until the gateway owner asks for
  MQTT (OI-01).
- **One scoring leader:** a second worker takes over if the first stops but does not share
  the scoring.
- **Missed cycles are not back-filled** automatically after an outage; re-score the period.
- Accessibility: automated WCAG 2.1 AA checks pass; a screen-reader and zoom review is
  still to do ([accessibility.md](accessibility.md)).

### Not in this release

Release 3 items: webhooks and the daily digest, single sign-on (OIDC), scheduled
re-forecasts, case search, similar cases and fault trees, library proposals from closed
cases, the PCA algorithm, alert KPIs and reports, asset comparison, calculated tags and
publishing results over MQTT. Release 4 items are out of scope.

### Before going live

- Agree the gateway interface ([gateway-icd.md](gateway-icd.md), section 6).
- Install on the client's host by [deploy/README.md](../deploy/README.md) (AC-08).
- Import the registry, build the pilot models (AC-02) and run 7 days of live data (AC-01).
- Run the evaluation on the client's event history and agree the alert targets (AC-04).
