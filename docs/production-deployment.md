# Production deployment runbook

The repository contains a production Compose baseline, not a deployed public service. No hosting account, domain, TLS endpoint, or production secret manager is configured in this workspace. Keep production startup on hold until an operator has those resources and the institution has approved privacy and retention settings.

## Before deployment

1. Provision a host with Docker Compose and a persistent encrypted volume for PostgreSQL. Restrict database ingress to the Compose network.
2. Point a domain at a TLS reverse proxy. The public web container should be reachable only through HTTPS; browser camera APIs and the refresh cookie require a secure context.
3. Create unique random values for `POSTGRES_PASSWORD`, `JWT_SECRET_KEY` (at least 32 characters), and the one-time `BOOTSTRAP_ADMIN_PASSWORD`. Store them in the provider's secret manager or an untracked production env file. Never reuse the local `.env` values.
4. Set `DATABASE_URL` with the production database password URL-encoded and `CORS_ORIGINS` to the exact HTTPS origin. Keep `COOKIE_SECURE=true`.
5. Review [`data-retention-review.md`](data-retention-review.md), approve the retention schedule, backup expiry, deletion process, camera notice, and accommodation path. Do not enable the vision service for real decisions with the current weak baseline.

## First startup

With the production secrets loaded into the shell or secret manager, apply migrations and start the production stack:

```sh
docker compose -f docker-compose.production.yml run --rm api alembic upgrade head
docker compose -f docker-compose.production.yml up --build -d
```

For the Render Docker Web Service, set the **Docker Command** to `/app/start-render.sh`.
That script applies Alembic migrations and then starts the API, avoiding shell-quoting
issues in the dashboard. It is intended for this single-instance deployment; use a
separate one-off migration step before scaling the API to multiple instances.

Set `BOOTSTRAP_ADMIN_EMAIL` and `BOOTSTRAP_ADMIN_PASSWORD` only for first-admin creation, call `POST /api/v1/auth/bootstrap-admin` once through the protected HTTPS origin, then remove both values and recreate the API container. Verify admin login and the role-protected audit endpoint.

## Operations to complete before inviting students

- Verify TLS renewal, restore from an encrypted database backup, monitoring/alert delivery, container restart behavior, database disk capacity, and application/API health checks.
- Add rate limiting at the trusted reverse proxy and restrict administrative access.
- Approve institution-specific retention and accommodation policies; test expiry/deletion against a disposable restored backup.
- Run browser checks on supported desktop/mobile browsers, keyboard-only navigation, screen readers, student camera permission grant/deny/revoke, and session recovery.
- Confirm account provisioning, password reset/recovery, incident response, support contacts, and administrator offboarding.

The production Compose file intentionally leaves the vision service disabled. Do not turn it on for exam decisions until a new, rights-cleared, participant-independent evaluation demonstrates adequate performance for the intended setting and a human review policy is approved.
