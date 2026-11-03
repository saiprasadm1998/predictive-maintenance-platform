# Gateway interface control document (OI-01, ARC §7)

The interface between the client's OT gateway and PMP, from PMP's side, as built in
release 0.1.0. Items marked **To confirm** are open until the gateway owner agrees them
(PRD OI-01). The live API description is at `https://<pmp-host>/api/v1/docs`.

## 1. Connection

| Item | Value |
| ---- | ----- |
| Direction | The gateway connects to PMP. PMP never connects into OT networks (NFR-SEC-02). |
| Address | `https://<pmp-host>` on 443, through PMP's reverse proxy. |
| TLS | TLS 1.2 or 1.3; the certificate is issued by the client's corporate CA. Mutual TLS at the proxy is possible. **To confirm** whether it is required. |
| Authentication | `Authorization: ApiKey <key>` on every request. Keys are issued by a PMP administrator (Administration → API keys, or `pmp apikey create --name "Site A gateway" --scope ingest`), shown once, and can be revoked or rotated: a rotated key gets a replacement, and the old one is revoked once the gateway has switched. |
| Key scopes | `ingest`: send samples and history. `results-read`: read current health. A key has one scope; using it for anything else gets 403. |
| Firewall | Allow the gateway's address to the PMP host on 443 only. |

## 2. Live samples: REST batch (primary)

`POST /api/v1/ingest/samples`, `Content-Type: application/json`, gzip accepted
(`Content-Encoding: gzip`).

```json
{
  "source": "gw-site-a-01",
  "samples": [
    { "tag": "K101.TI1012.PV", "ts": "2026-10-08T14:20:00Z", "v": 78.42, "q": 0 },
    { "tag": "K101.ZI1015.PV", "ts": "2026-10-08T14:20:00Z", "v": 412.0, "q": "Good" },
    { "tag": "K101.TI1018.PV", "ts": "2026-10-08T14:20:00Z", "v": null, "q": "Bad" }
  ]
}
```

| Field | Rule |
| ----- | ---- |
| `source` | The gateway's name, 1 to 100 characters. Tags are registered per source, so the same tag name under two sources is two tags. |
| `tag` | The tag's source name as registered in PMP, 1 to 200 characters. |
| `ts` | ISO 8601 with a time-zone offset (`Z` or `+04:00`); stored in UTC. A time without an offset is refused. The gateway's clock is the sample's clock: keep it synchronised (NTP). |
| `v` | A number. `null` (no value, as OPC UA sends with Bad quality) refuses that sample only. |
| `q` | An OPC UA StatusCode (unsigned 32-bit: bits 30–31 give 00 Good, 01 Uncertain, 10 or 11 Bad) or the strings `Good`, `Uncertain`, `Bad`. Omitted means Good. |
| Unknown fields | Refused (the whole batch, 400). |

**Limits:** at most 10,000 samples and 5 MB per request (the proxy also refuses bodies
over 5 MB). Rate limit: 50 requests per second per key by default
(`PMP_INGEST_RATE_LIMIT`). Recommended: one batch every 5 to 10 seconds.

**Responses**

| Status | Meaning | Gateway action |
| ------ | ------- | -------------- |
| 202 | Stored (committed before the answer). Body: `{"accepted": n, "rejected": [{"index": i, "reason": "…"}]}` | Nothing; log the rejections. |
| 400 | Not valid JSON or not the schema; nothing stored; `errors` lists what is wrong | Fix the payload; do not resend unchanged. |
| 401 / 403 | Key missing, unknown or revoked / key without the `ingest` scope | Check the key. |
| 413 | Over 10,000 samples or 5 MB | Split the batch. |
| 429 | Rate limit; `Retry-After` gives the seconds to wait | Wait, then resend. |
| 503 | Database unavailable | Buffer and resend later (D-3). |

**Rejection reasons** (one sample refused, the rest stored):

| Reason | Cause |
| ------ | ----- |
| `unregistered_tag` | The tag is not registered for this source. PMP lists it under Administration → Registry and import → Unmapped tags, where an engineer can register it. |
| `no_value` | `v` is null. |
| `too_old` | More than 7 days old (`PMP_LATE_DATA_DAYS`). Send older history as a backfill (section 4). |
| `in_future` | More than 5 minutes ahead of PMP's clock. |

**Semantics:** a sample is identified by (source, tag, timestamp). Resending stores it once;
the last value sent wins. Order does not matter, and late samples within 7 days are
accepted, so the gateway can buffer during an outage and resend on reconnection (D-3,
NFR-REL-02).

**Timing:** PMP scores each model every 60 s (per model, at least 10 s), 3 s after the
cycle boundary, with the newest sample of each sensor at or before the boundary. A source
that delivers later than that can be given a longer grace (`pmp ingest grace <source>
<seconds>`, up to 600 s), at the cost of later scores.

**Health:** PMP shows per source and tag what arrived (Administration → Ingestion health).
A source that sends nothing for 2 of its scan intervals is stale and administrators are
e-mailed. A clock difference over 60 s between receive time and sample time is flagged.

## 3. Live samples: MQTT (optional)

Not built in release 0.1.0. ARC §7.1.2 describes it (PMP subscribes to
`pmp/v1/<source>/samples` on the client's broker, QoS 1, TLS, the same JSON). **To
confirm** whether it is needed (PRD OI-01); REST is the default.

## 4. History: backfill

`POST /api/v1/ingest/backfill`, a multipart upload of a CSV or Parquet file with the form
field `source`, by an `ingest` key or an engineer in the UI (Administration → Registry and import → History import).
It is checked and imported as a background job; the answer gives a job ID, and
`GET /api/v1/jobs/{id}` its progress and report.

| Field | Default | Meaning |
| ----- | ------- | ------- |
| `file` | | `.csv` or `.parquet`, up to `PMP_BACKFILL_MAX_MB` (2 GB). |
| `layout` | detected | `long` (columns ts, tag, value, quality) or `wide` (ts and one column per tag). |
| `mode` | `skip` | Where samples exist already: `skip` keeps them, `overwrite` replaces them. |
| `preview` | false | Check and report only; import later with `POST /api/v1/ingest/backfill/{upload_id}/load`. |
| `naive_as_utc` | false | Treat times without an offset as UTC (otherwise they are refused). |
| `ts_column`, `tag_column`, `value_column`, `quality_column` | ts, tag, value, quality | Column names in a long file. |

## 5. Results for plant systems

`GET /api/v1/results/health?scope=<asset code>` with a `results-read` key returns every
model in service, under the asset if given (404 if the code is unknown):

```json
{ "ts": "2026-10-08T14:20:00Z",
  "models": [ { "asset": "K-101", "model": "main v3", "modelId": 4, "health": 41, "di": 29.5,
                "band": "Alert", "status": "Running", "lastCycle": "2026-10-08T14:20:00Z",
                "activeAlerts": 1, "urgency": "High" } ] }
```

`band` is Healthy, Watch, Alert or Unknown; `status` the runtime status (null while a
deployed model has not been scored yet); `health` and `di` are null when the band is
Unknown; `urgency` is the most urgent forecast of the model's open alerts, or null.
Recommended: one call a minute, after the cycle (for example 10 s past the minute).

The same key may also read the alerts: `GET /api/v1/alerts?state=active` returns the
active alerts (paged, `next_cursor` for more) with asset, model, priority, severity, DI,
raised time and forecast urgency.

## 6. Open items with the gateway owner

1. Transport: REST only, or MQTT too.
2. Source names and tag naming: the tag list per source for the registry import.
3. Quality: OPC UA StatusCodes or the strings.
4. Mutual TLS at the proxy: needed or not.
5. Batching interval and expected delivery delay (sets the scoring grace).
6. Buffering during PMP outages: how long, and the resend rate.
7. Results: whether the DCS reads `/results/health`, and how often.
