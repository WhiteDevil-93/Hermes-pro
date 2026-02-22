# Deployment Profiles

This document defines secure defaults and expected runtime posture per environment.

## dev profile

Purpose: local development and debugging.

Defaults:
- `HERMES_LOG_LEVEL=DEBUG`
- `HERMES_ALLOWED_ORIGINS=http://localhost:3000,http://localhost:8080`
- `HERMES_CORS_ALLOW_CREDENTIALS=false`
- `HERMES_DATA_DIR=./data`
- `HERMES_MAX_CONCURRENT_RUNS=1`
- `headless=true` unless interactive debugging is needed.

Security defaults:
- Never use wildcard CORS when credentials are enabled.
- Use non-production credentials and constrained Vertex project.
- Keep dev data local and disposable.

## staging profile

Purpose: pre-production validation with production-like topology.

Defaults:
- `HERMES_LOG_LEVEL=INFO`
- `HERMES_ALLOWED_ORIGINS=https://staging-ui.example.com`
- `HERMES_CORS_ALLOW_CREDENTIALS=true`
- `HERMES_MAX_CONCURRENT_RUNS=2`
- Dedicated staging service account via `GOOGLE_APPLICATION_CREDENTIALS`.

Security defaults:
- Enforce least-privilege IAM for staging service accounts.
- Restrict network ingress to staging frontend and CI runners.
- Retain signals and records with short TTL (e.g., 7 days).

## prod profile

Purpose: customer-facing workload.

Defaults:
- `HERMES_LOG_LEVEL=INFO` (or `WARN` in high-volume environments)
- `HERMES_ALLOWED_ORIGINS=https://app.example.com`
- `HERMES_CORS_ALLOW_CREDENTIALS=true`
- `HERMES_MAX_CONCURRENT_RUNS` set by capacity test (start at 2-4)
- `HERMES_DATA_DIR` on persistent encrypted volume

Security defaults:
- No wildcard CORS.
- Secrets managed by platform secret manager; no plaintext key files baked into images.
- TLS required on all ingress; internal mTLS where available.
- Structured error telemetry forwarded to centralized SIEM with `error_code` indexing.
- Configure retention and access controls for run records and signals.

## Operational Checklist

- Verify `/health` readiness in each environment.
- Validate run lifecycle endpoints and websocket connectivity.
- Validate alert routing for SLO alerts before promoting changes.
