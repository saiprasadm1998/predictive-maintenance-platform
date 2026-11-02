# TLS certificates

For the plant, put the certificate issued by the corporate CA and its key here as
`pmp.crt` and `pmp.key`, and set `PMP_TLS=/certs/pmp.crt /certs/pmp.key` in deploy/.env.
Never commit them: `*.crt` and `*.key` are ignored. With `PMP_TLS=internal` (the default,
for trials) this folder stays empty and Caddy issues its own certificate.
