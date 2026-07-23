# Security Policy

## Supported version

`0.2.x` is a single-user/small-team, single-instance Beta. Security fixes target the latest `main`; older snapshots are not maintained.

## Reporting a vulnerability

Please do not open a public issue for suspected vulnerabilities or exposed credentials. Use GitHub's **Report a vulnerability** / private security advisory flow for this repository and include:

- affected commit and configuration;
- minimal reproduction without private documents or live keys;
- impact and whether the issue is reachable with the default offline setup;
- suggested mitigation, if known.

Do not test against systems or data you do not own. Maintainers should acknowledge a complete report within 5 business days and publish a remediation status before disclosure.

## Deployment responsibilities

- Keep `API_AUTH_TOKEN`, provider keys, database DSNs and Sentry DSNs outside Git and browser bundles.
- Terminate TLS and user authentication at a trusted gateway; the built-in Bearer token is a Beta boundary, not a complete identity system.
- Keep `RAG_ALLOW_PRIVATE_URLS=0` unless the service is isolated and the imported private hosts are explicitly trusted.
- Use per-workspace object prefixes and row-level authorization before enabling multiple teams.
- Treat uploaded content and generated answers as untrusted; scan files and apply retention/deletion policies appropriate to the deployment.
- Keep the built-in SQLite index worker single-instance; migrate to an authenticated external queue before horizontal scaling.
- Set Sentry `send_default_pii=false` and never attach document text or authorization headers to events.

## Current defenses

See [README](README.md#安全与稳定性) for upload, URL, logging, rate-limit and request-timeout controls. Remaining production gaps are tracked in [docs/known-limitations.md](docs/known-limitations.md).
