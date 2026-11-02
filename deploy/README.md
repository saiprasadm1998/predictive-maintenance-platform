# Deployment

The production stack (ARC §10, plan 9.1): `compose.yaml` runs the Caddy reverse proxy, the
web and worker roles and the nightly backup from one image (`Dockerfile`), with TimescaleDB.
`compose.dev.yaml` is the development database and mail catcher only (`make db-up`).

| Service  | What it does                                                                   |
| -------- | ------------------------------------------------------------------------------ |
| `proxy`  | TLS on 443 (HTTP on 80 redirects), HTTP/2, 5 MB limit on gateway batches, live events unbuffered (`Caddyfile`) |
| `web`    | `pmp web`: API, live events and the front end; runs migrations on start-up     |
| `worker` | `pmp worker`: scoring scheduler, jobs (training, imports, re-scores), e-mails   |
| `db`     | TimescaleDB (PostgreSQL 16), volume `pgdata`                                   |
| `backup` | `pmp backup --at 02:30`: nightly database dump and artefact archive, volume `backups` |

## Install

Needs Docker with the compose plugin, ports 80 and 443 free, and 4 vCPU / 16 GB for the
PoC fleet (ARC §6).

1. Copy the settings and set the secrets:
   ```
   cp deploy/.env.example deploy/.env
   openssl rand -hex 32   # once for POSTGRES_PASSWORD, once for PMP_SECRET_KEY
   ```
2. Address and certificate. `PMP_HOSTNAME` is the name users and the gateway use, and
   `PMP_PUBLIC_URL` is `https://` and that name (links in e-mails). For a trial, leave
   `PMP_TLS=internal`: Caddy issues its own certificate and browsers warn. For the plant,
   put the corporate-CA certificate and key in `deploy/certs/` as `pmp.crt` and `pmp.key`
   and set `PMP_TLS=/certs/pmp.crt /certs/pmp.key`.
3. Sizing: `PMP_WEB_WORKERS` is 2 per vCPU, at most 8; `PMP_DB_SHARED_BUFFERS` a quarter
   of the memory.
4. Notifications: set the `PMP_SMTP_*` lines for the plant's relay (587 with STARTTLS).
5. Start, then create the first administrator:
   ```
   make up
   docker compose -f deploy/compose.yaml exec -it web pmp user create admin --name "Plant admin" --role administrator
   ```
6. Check: `https://<hostname>/healthz` answers `ok`; sign in; issue the gateway's `ingest`
   API key under Administration → API keys.

## Backups (NFR-REL-03: RPO 24 h, RTO 4 h)

Every day at `PMP_BACKUP_AT` (UTC) the `backup` service writes into the `backups` volume a
database dump (`pmp-<time>.dump`, pg_dump custom format) and the model artefacts
(`pmp-<time>-artefacts.tar.gz`), then keeps the newest copy of each of the last 14 days and
of each of the last 8 weeks. Every run is recorded (`backup_run`); a failed one is retried
the next night. Copy the volume off the host as the plant's backup policy requires:

```
docker compose -f deploy/compose.yaml run --rm --no-deps backup backup     # one now
docker run --rm -v pmp_backups:/b -v "$PWD":/out alpine cp -r /b /out/pmp-backups
```

## Restore into an empty database

`pmp restore` refuses a database that has tables, so a running system is never overwritten.

```
docker compose -f deploy/compose.yaml stop web worker backup
docker compose -f deploy/compose.yaml exec db dropdb -U pmp pmp
docker compose -f deploy/compose.yaml exec db createdb -U pmp pmp
docker compose -f deploy/compose.yaml run --rm --no-deps backup \
    restore /data/backups/pmp-20261030T023000Z.dump
docker compose -f deploy/compose.yaml up -d --wait
```

The artefact archive next to the dump is unpacked too. The web role then applies any
migrations newer than the backup.
