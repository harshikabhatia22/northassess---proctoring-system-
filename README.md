# AI-Powered Assessment Proctoring Platform

An original greenfield online assessment platform with optional, consent-based AI decision support. AI observations are reviewable signals, never proof of misconduct or a basis for automatic punishment.

## Project status

The project includes secure assessment workflows, exploratory Phase 3 tabular work, Phase 4 vision prototypes, Phase 5 optional consent-based camera review, and Phase 6 API-backed course analytics, audited CSV export, and an administrator audit trail. The vision models are weak research baselines and remain disabled unless a private model service is configured; AI observations never determine grades or misconduct.

## Local development

Requirements: Docker Desktop or Docker Engine with Compose. For running the web app outside Docker, use Node.js 20.19 or newer (or 22.12 or newer). For backend checks outside Docker, install `uv`.

1. Copy `.env.example` to `.env` and adjust local values if needed.
2. Start the services:

   ```sh
   docker compose up --build
   ```

3. Apply database migrations in another terminal:

   ```sh
   docker compose exec api alembic upgrade head
   ```
4. To create the first administrator, set `BOOTSTRAP_ADMIN_EMAIL` and a long random `BOOTSTRAP_ADMIN_PASSWORD` in `.env`, restart the API, then call `POST /api/v1/auth/bootstrap-admin` once. Remove both values after it succeeds. An existing installation with no bootstrap environment configured returns 404.
5. Open the authenticated workspace at <http://localhost:5173> and API docs at <http://localhost:8000/docs>.

For the currently running workspace, the ignored local `.env` maps the web app to <http://localhost:5688>, API to port `8001`, and PostgreSQL to port `5433` because the default ports were already occupied. Its administrator is `admin@localhost.test`; the generated password was shared in the Codex conversation and is intentionally not stored in the repository. A demo student account and course are seeded for review; the student password was also shared in the conversation. The demo course contains completed sample attempts and an unattempted practice exam. The one-time bootstrap environment values have been removed after account creation.

The database is exposed only on loopback and persists in the `postgres_data` volume. The `.env.example` password is for local development only; use a secret manager and production-grade credentials outside local development. Camera review is optional per attempt. To enable the private, optional vision container after training a local detector and configuring a shared internal key in `.env`, set `VISION_MODEL_FILE` and `VISION_INTERNAL_API_KEY`, then start with `docker compose --profile vision up --build`.

## Deployment baseline

`docker-compose.production.yml` builds the web app as static files served by an unprivileged Nginx container and proxies `/api/` to the private API service. It does not publish the database or API ports. Production startup rejects the development JWT secret, insecure refresh cookies, and wildcard CORS. The production Compose file requires `POSTGRES_PASSWORD`, `DATABASE_URL`, `JWT_SECRET_KEY`, and `CORS_ORIGINS`; provide them through the deployment secret manager or an untracked environment file. The API database URL password must be URL-encoded.

Apply migrations before the first web request:

```sh
docker compose -f docker-compose.production.yml run --rm api alembic upgrade head
docker compose -f docker-compose.production.yml up --build -d
```

The web container listens on `WEB_HTTP_PORT` (8080 by default). Put it behind an HTTPS reverse proxy before exposing it publicly; camera access and secure refresh cookies require HTTPS. Set `CORS_ORIGINS` to the exact HTTPS origin, for example `'["https://exam.example.edu"]'`. Configure backups, secret rotation, TLS, monitoring, and an institution-approved data retention policy before real student use. The vision service remains disabled in this deployment baseline because the current model is not validated for exam decisions.

Review [`docs/data-retention-review.md`](docs/data-retention-review.md) before handling real student data. Its manual retention command defaults to a non-destructive preview; applying a purge requires an approved policy reference and explicit confirmation. It is not scheduled automatically.

## Checks

Frontend build:

```sh
cd apps/web
npm ci
npm run build
```

Backend checks:

```sh
cd services/api
uv sync --locked --extra dev
uv run --locked pytest
uv run --locked ruff check .
```

Tabular ML pipeline mechanics:

```sh
cd ml/tabular
uv sync --extra dev
uv run pytest
```

The Phase 3 research pipeline uses owner-supplied local CSVs and an explicitly gated manifest. It does not depend on Mendeley. No dataset download is automated.

Compose configuration:

```sh
docker compose config
```

## Architecture

The approved Phase 0 proposal is in [docs/phase-0-architecture-and-roadmap.md](docs/phase-0-architecture-and-roadmap.md). Phase 3 proxy metrics and Phase 4 vision results are exploratory. The optional camera path requires consent and a configured private detector; review decisions remain human-authored.
