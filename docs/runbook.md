# PMP runbook

Day-to-day operation of a PMP installation for the site administrator. Installing,
backups, restore and upgrades are in [deploy/README.md](../deploy/README.md); the gateway
interface is in [gateway-icd.md](gateway-icd.md).

All commands run on the PMP host, in the folder holding the PMP release, with
`DC="docker compose -f deploy/compose.yaml"` set first.

## 1. Daily check (5 minutes)

1. Sign in as an administrator and open **Administration**. The **Operational alerts**
   panel at the top appears only when something needs attention (section 3).
2. **Administration → Ingestion health:** every source "Receiving", no clock skew, the
   rejected count not growing.
3. **Fleet overview:** no "No new scores" banner (a model not scored for three cycles), and
   no unexpected models in "Unknown".
4. **Administration → Notification log:** no `failed` e-mails.

## 2. Start, stop, status

| Task | Command |
| ---- | ------- |
| Status of every service | `$DC ps` (all `running`; web `healthy`) |
| Start everything | `$DC up -d --wait` |
| Stop everything | `$DC down` (data stays in the volumes) |
| Restart one service | `$DC restart worker` (or `web`, `proxy`, `backup`) |
| Follow the logs | `$DC logs -f --tail 100 web worker` |
| Health from outside | `curl https://<host>/healthz` answers `ok`; `/readyz` also checks the database |
| Scoring status | `$DC exec web pmp score status` (each model's status and last cycle) |

The worker runs scoring, jobs (training, imports, re-scores, retention) and e-mails. Only
one worker leads scoring at a time, so a second worker is safe but does not score more.
Logs are JSON, one line per event, with the request ID, user and model.

## 3. Operational alerts and what to do

| Alert | Likely cause | Action |
| ----- | ------------ | ------ |
| Source X has sent nothing for N min | Gateway stopped, network or firewall change, key revoked | Check the gateway and the path to PMP. `$DC logs web` shows refused keys (401). Affected models show "Insufficient data" until data returns; nothing is lost if the gateway buffers (it resends up to 7 days). |
| No scoring cycle for N min | Worker stopped or stuck | `$DC ps worker`; `$DC logs --tail 200 worker`; `$DC restart worker`. Missed cycles are not back-filled; re-score the gap if needed (section 6). |
| Scoring took N s, over half the cycle | Host overloaded, many models, slow disk | Check `docker stats` and disk I/O. If it persists, raise the host's CPU or lengthen cycles of less critical models. |
| N jobs waiting over 10 min | Worker stopped, or a long job (big import, 30-day re-score) ahead of them | `$DC ps worker`; the jobs' progress is in the screen that started them. Restart the worker if it is down; jobs resume. |
| Backup failed / no successful backup for N h | Disk full, database unreachable, backup service stopped | `$DC logs --tail 50 backup`; `df -h`; then run one now: `$DC run --rm --no-deps backup backup`. |

Clock skew on a source (Ingestion health): the gateway's clock differs from PMP's by over
60 s. Fix the gateway's NTP; scores use sample times, so a skewed clock shifts them.

## 4. Users and access

| Task | Where |
| ---- | ----- |
| Add a user, give roles (optionally limited to part of the hierarchy) | Administration → Users and roles, or `$DC exec -it web pmp user create <name> --name "Full Name" --email <e-mail> --role analyst` |
| Leaver | Deactivate (Users and roles, or `pmp user deactivate <name>`): sign-in stops and sessions end; the account stays for the audit trail. |
| Forgotten password or locked account (5 failures lock for 15 minutes) | Reset the password (Users and roles, or `pmp user reset-password <name>`): unlocks and ends their sessions. |
| Who changed what | Administration → Audit log (filter, export CSV), or `pmp audit --from -7d`. |

Roles (ARC §9.2): Viewer reads; Reliability Analyst handles alerts, forecasts and cases;
Maintenance works on cases assigned to them; Model Engineer builds models and data-quality
rules; Administrator manages users, keys, retention and settings, and does not work cases.

## 5. API keys

Issue one key per gateway and per reading system (Administration → API keys). To change a
key without a gap: **Rotate** gives a replacement; give it to the gateway, check Ingestion
health shows data still arriving, then **Revoke** the old one. Revoke at once if a key may
have leaked. Key use is logged in the security log.

## 6. Data tasks

| Task | How |
| ---- | --- |
| Import history | Administration → Registry and import → History import (preview first; see the ICD) |
| Re-score a period (after a fix to data or limits) | Model version page → Re-score…, or `pmp score rescore <asset> <model> --days 30`. Replaces scores only: no alerts, no e-mails. |
| Change retention | Administration → Retention (default 24 months raw, 60 months hourly) |
| Pause a model during an outage of its equipment | Model management → Pause (open alerts go out of service; resume afterwards) |
| Exclude a faulty sensor | Asset analysis → sensor table → Exclude… (with a reason and an end) |

## 7. Disk and capacity

Data grows by about 0.35 GB a day per 5,000 tags at 60 s, compressed after 7 days
(ARC §6). Watch the `pgdata` and `backups` volumes: `docker system df -v`. Retention
deletes raw data older than the policy once a day. Backups keep 14 daily and 8 weekly
copies; copy them off the host as the site's policy requires.

## 8. Monitoring from outside

Prometheus can scrape `http://web:8000/metrics` from the stack's network (not through the
proxy). The metric names and their meaning are in
[deploy/README.md](../deploy/README.md#monitoring-arc-103). Alert on
`pmp_ingest_source_stale == 1`, `time() - pmp_scoring_last_cycle_timestamp_seconds > 600`,
`pmp_job_queue_oldest_seconds > 600` and `pmp_backup_last_failed == 1`.

## 9. Escalation

Collect before calling the PMP developer: the time of the problem, `$DC ps`, the last
200 log lines of `web` and `worker`, the Operational alerts shown, and the release
(`pmp:<version>`; the version is also at the top of `/api/v1/docs`).
