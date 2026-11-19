# Implementation Status

Last updated: 2026-11-19

## Current phase

Phase 4 model validation remains incomplete: v1/v2/v3 are weak research baselines, and available subject/session data rights and independent validation are insufficient. Phase 5 consent-based capture and human review implementation is delivered with automated API coverage. The configured Compose multi-container stack and private model inference path have been runtime-verified; browser camera permissions and full browser end-to-end flows remain unchecked. Phase 6 real-data course analytics and CSV reporting are implemented; accessibility and retention review remain in progress. Phase 7 deployment baseline is running locally, while public production operations remain unfinished. A local administrator account is provisioned for the active instance. The camera path is optional and does not have validated cheating detection.

## Phase 3 work completed

- Added isolated, locked `ml/tabular` Python package using scikit-learn preprocessing pipelines, deterministic majority/logistic-regression/random-forest baselines, group-aware holdout when a verified group column exists, and a clearly labeled stratified row split fallback.
- Added provenance and SHA-256 gated dataset loading; EDA summary for class counts, missingness, duplicates, candidate target leakage columns, and group identifiers; held-out metrics; `evaluation.json`, `MODEL_CARD.md`, and a research-only model artifact.
- Added strict one-row inference validation that checks exact feature names, types, finite numeric values, and research-only output semantics. Model artifacts are not connected to the product API.
- Added generated-fixture tests for provenance gating, group split/training/artifacts/inference, and invalid split handling. Fixture metrics are test mechanics only and are not project performance results.
- Added a candidate source manifest and documented its unresolved provenance issues. No dataset or model weights were downloaded.
- Reviewed four owner-supplied CSVs from the Anita Goel online-assessment research dataset; raw data stays in ignored local storage. Built a reproducible transformation to 111 student-level feature rows, then ran two reciprocal assessment-level holdouts against the source `Cheater` proxy after explicit owner authorization. Results quantify proxy-label agreement only. The repository exposes no explicit dataset license and the paper says cheating ground truth was unavailable. See `ml/tabular/datasets/goel-internet-cheating-v1/SOURCE_REVIEW.md`.

## Phase 3 completed scope and limits

- A second candidate, the [Anita Goel online-assessment dataset](https://github.com/anitagoel/Dataset), was supplied locally as two student-level aggregate CSVs and two question-level raw CSVs. The files are not stored in Git. The associated paper describes 1,665 question records from 111 students and unsupervised cluster analysis, but explicitly notes the lack of ground truth. The CSV `Cheater` field remains an unverified proxy, and the GitHub page did not provide explicit data reuse terms. The project owner authorized local exploratory training. Two reciprocal assessment-level held-outs were run and documented; metrics quantify only agreement with the proxy label. This completes Phase 3's re-scoped research benchmark, not validation of cheating detection. Do not publish or deploy these artifacts. See `ml/tabular/datasets/goel-internet-cheating-v1/SOURCE_REVIEW.md`.

- The Mendeley record [DOI 10.17632/39xs8th543.1](https://data.mendeley.com/datasets/39xs8th543/1) lists CC BY 4.0 and describes 5,500 simulated frame-level rows from 30+ volunteers, with labels based on observation logs/session context. The live record lists one CSV and two feature-table documents. It reports 38 attributes in the overview but 37 features per row in the reproduction notes. The actual file schema, participant/session identifiers, annotation protocol, and local CSV checksum remain unverified.
- Attempts to fetch the listed files from the canonical Mendeley file URLs returned a 25-byte `{"err":"Unhandled error"}` response. The canonical Download All endpoint returned HTTP 500; the documented public metadata API returned HTTP 401. These error bodies were not treated as data. No download from another repository or mirror was attempted.
- The manifest at `ml/tabular/datasets/mendeley-proctoring-v1/manifest.json` records the canonical source, record-stated license, reported archive digest, and unresolved content/schema fields. It intentionally remains `provenance_reviewed: false` and has a placeholder CSV checksum. The CLI blocks inspection/training until a real CSV and supporting documents are available and reviewed.
- No validated real-world cheating-detection performance is available. Proxy-label metrics are local exploratory results only and must not be described as actual cheating-detection accuracy or platform performance. Generated test-fixture scores are not project metrics.

## Phase 4 work in progress

- Reviewed the canonical [Zenodo record 14606173](https://zenodo.org/records/14606173). The owner supplied the original archive. Its MD5 matches `78fde2372a5a58efba55ed4d47039429`; SHA-256 is `ca94adccd9745f819d912435c68197adfe59bca3a0f644b5c36a92f522dffe52`; ZIP integrity passes. The archive remains ignored under `ml/vision/data/`.
- Audited 5,575 640x640 JPEGs: 5,494 labeled train/valid images and 81 unlabeled test images. The class map is confirmed from `classes.txt`. One zero-width annotation was excluded. The `data.yaml` paths are placeholders; all 38 filename-derived source groups appear in both supplied train and valid sets; the unlabeled test folder contains five exact duplicates across existing splits and is excluded from evaluation.
- Added an archive-confirmed annotation spec, source manifest/review, ZIP auditor with image decoding, original HOG + LinearSVC detector, deterministic grouped holdout, model cards, and private `POST /api/v1/detect`. The seed-42 split has 4,448 training and 1,046 holdout images from eight filename-derived groups; it is not participant-independent.
- V1 held-out macro mAP@0.5 **0.0675**, mAP@[0.5:0.95] **0.0177**. V2 adds horizontal-flip crop augmentation and five-scale scanning; on the same previously inspected holdout it reaches **0.0712** and **0.0248** respectively. V2 is an exploratory comparison, not independent validation, and remains unsuitable for real exams. V2 CPU latency excluding decode over 1,046 images: mean 378.2 ms, p50 321.6 ms, p95 664.2 ms. Artifacts and per-class results are under ignored `artifacts/vision/zenodo-students-online-exam-v1/hog-svm-grouped-seed42-v2/`.
- V3 adds hard-negative mining from training groups only (maximum 12 selected frames per source group, up to 3 mined windows per frame, capped at 20 mined windows per group). It reaches macro mAP@0.5 **0.0572** and mAP@[0.5:0.95] **0.0201** on the same previously inspected holdout. Macro precision at uncalibrated margin 0 / IoU 0.5 is **0.0409**, with macro recall **0.3786**. This is a precision/recall tradeoff and a lower mAP than v2, not an overall improvement or independent validation. CPU latency excluding decode over 1,046 images: mean 505.1 ms, p50 495.5 ms, p95 683.6 ms. Artifacts and per-class results are under ignored `artifacts/vision/zenodo-students-online-exam-v1/hog-svm-grouped-seed42-v3/`.
- Surveyed an additional non-Mendeley Roboflow object dataset. Its page lists CC BY 4.0 and six object classes, but reports inconsistent image counts and does not document participant/session IDs or human-subject consent. The export timed out here; no archive has been downloaded or trained. It is recorded as supplemental object data only in `ml/vision/datasets/roboflow-online-proctoring-v1/`.
- Added bounded, internal-key-protected inference with a five-second request timeout and 4 MiB/8 MP caps. In-process ASGI checks with v3 returned: readiness 200 with v3 ID, patterned image 200 with 16 detections, no-visual-signal 200 with zero detections, and missing key 401. Earlier artifact checks also covered unsupported media 415, corrupt image 400, oversized image 413, and forced timeout 504. It is now called only through the opt-in Phase 5 path; outputs cannot affect an exam attempt.
- Four standard-library unit tests pass; Ruff format/lint pass. Sandbox policy blocked a TCP bind, so a live localhost server test was not possible. PyPI DNS blocked `uv.lock` generation; exact direct pins are in `ml/vision/requirements.txt`, but transitive dependencies are not locked.
- Provenance remains partial: the record states CC BY 4.0, but the paper does not clearly document consent/ethics approval for the images, and the archive has no participant/session IDs. Keep data and artifacts local; do not deploy or redistribute images/model pending review.

## Phase 5 implementation delivered; browser verification pending

- Added a versioned optional camera policy and explicit accept/decline choice. Declining consent leaves the exam available. Consent records are bound to the attempt and policy hash; students can revoke or stop a session.
- Added five-second minimum sampled frame submission with a 4 MiB cap. Frames are forwarded transiently to the private vision API and are not persisted by the assessment API. If inference is unconfigured or unavailable, the attempt continues.
- Added observation events, append-only reviewer decisions (`reviewed`, `dismissed`, `needs_follow_up`) scoped to course owners/administrators, and audit rows for consent and review activity. These outputs remain neutral visible-behavior observations and do not trigger exam or discipline decisions.
- Added a student consent/camera control and instructor review queue UI, an optional vision Docker profile, and migration `0003_phase5_proctoring.py`.
- Exam submission closes any active camera session on the server. A result returned by inference is discarded if consent was revoked or the attempt ended while inference was running.
- Leaving an active student attempt within the app shows a warning and stops local camera tracks; returning to the attempt prompts for camera consent again. The browser warns on reload/close and shows an in-page warning when the exam tab becomes hidden. These browser signals are not persisted as audit events, and browser UI controls may vary. The frame endpoint rejects submissions after the exam deadline.
- Instructors/administrators can record `suspected_cheating` as a human review outcome with a required note. It is displayed as an instructor assessment, not an AI verdict, and does not automatically alter grades or trigger discipline.
- The consent policy is now `proctoring-v2`: three separate model-positive frames in one camera session escalate the student warning and surface the observations for instructor review. API coverage verifies counts 1, 2, 3. The threshold never cancels the attempt; it continues while a human reviews the signals.
- Automated checks: API test suite **7 passed**, including decline/accept, unavailable inference, three-frame warning escalation, review outcomes (with required notes for suspected cheating), revoke, server-side session shutdown, and rejection of sampled frames after the attempt deadline; frontend production build passed; Ruff, migration SQL generation (5 Phase 5 tables), Compose config, and `git diff --check` passed. The live multi-container consent-to-model path was exercised with a synthetic blank frame; real browser camera permissions/device handling remain unverified.
- Raw frames are not stored. A manual, preview-first deletion command now purges finalized attempt data only after an approved policy reference and explicit confirmation; it preserves in-progress attempts and writes an aggregate audit record. Account/roster data, audit history, exports, and backups are outside this command. No schedule or retention duration is configured. See `docs/data-retention-review.md`.

## Phase 6 in progress

- Added course-scoped analytics for instructors and administrators: assignments, starts, finalized attempts, completion rates, objective score aggregates, and daily completions for the last 14 days. Student identities and answer content are not included.
- Score averages are suppressed until at least five scored attempts exist; descriptive responses are excluded. This reduces exposure of individual results in small cohorts.
- Added authorized CSV export with audit logging and spreadsheet formula-injection escaping for exported text. Added paginated, admin-only audit-log API and workspace view; security-relevant course, enrollment, exam, attempt, consent, review, analytics-read, and export actions are recorded.
- Added a responsive analytics view with course selection, summary cards, 14-day chart, exam breakdown table, and CSV download. Charts and tables are based on actual API responses.
- Added accessible workspace navigation landmarks/current-page state, a skip link, page-heading focus management, visible focus rings, improved small-text contrast, and labels for previously unlabeled form controls. Active-exam navigation warnings and camera-consent re-prompt on return remain. These are source-level improvements; no browser or screen-reader audit is recorded.
- API integration coverage checks the analytics summary, score suppression, CSV export without student email, denial of student access, admin-only audit log access, and camera CORS preflight. Added a tested retention preview/purge function and tested provisioning/enrollment by email. Latest checks: Ruff passed, API tests **7 passed**, frontend production build passed, Compose config passed, and `git diff --check` passed.
- Remaining Phase 6 work: review keyboard/screen-reader behavior in a browser and obtain institution-approved retention periods, backup expiry, and deletion scheduling. Live course analytics were exercised on the local PostgreSQL demo data.

## Phase 7 in progress

- Added a production Compose file with private database/API network exposure, health checks, restart policies, required production secrets/origins, and a static unprivileged Nginx web container that proxies API requests.
- API container now runs as a non-root user. Production configuration rejects the known development JWT secrets, insecure refresh cookies, and wildcard CORS; interactive API docs are disabled in production.
- Pinned and regenerated the API lock from the local cache; `uv sync --locked`, Ruff, format check, and API tests **7 passed**. The API Dockerfile now installs from `uv.lock` using the pinned uv version.
- Added a CORS preflight regression test for the camera frame's `X-Event-Key` header; before the fix, the dev browser flow could fail at the browser boundary.
- Student enrollment now accepts a student email as well as the legacy ID field, making the flow usable from the workspace without copying an internal ID. API coverage verifies account provisioning, email enrollment, and roster visibility.
- Production Compose and local Compose both pass `docker compose config -q` with required deployment values supplied; frontend production build and `git diff --check` pass.
- Built and started the local Compose stack with the optional vision profile after Docker Desktop became available. Existing host services occupied 5432, 8000, and 5173, so this stack uses localhost ports 5433 (PostgreSQL), 8001 (API), and 5688 (web); existing processes were left untouched.
- All four containers started; PostgreSQL, API, and vision report healthy. Applied Alembic revisions 0001–0003 to the live Compose PostgreSQL database. From inside the API container, vision readiness returned `northstar-hog-linear-svm-detector-v3`; a synthetic blank PNG passed through authenticated private inference and returned `no_visual_signal` with zero detections. The internal key was not written to the repository.
- Provisioned the one-time local administrator through the supported bootstrap endpoint, removed the bootstrap password from the local environment, and verified a successful admin login. Current local ports: web 5688, API 8001, PostgreSQL 5433. `.env` is ignored by Git.
- Seeded a local demonstration course, one student, two submitted demo exams, and one published unattempted practice exam. Ran publish → student login → start attempt → versioned answer save → submit → score/analytics. Also exercised consent acceptance → synthetic frame upload through the API to the private v3 service → no-signal response → camera stop → submit. The blank synthetic frame produced zero observations; this checks connectivity and consent handling, not detection quality. The student practice exam remains open for seven days from 2026-11-19 local time.
- Host-side browser access was unavailable in the current computer-use session, so no visual browser walkthrough was performed. Public deployment still requires HTTPS, a secret manager, backup/restore, monitoring, rate limiting, and institution-specific retention policy.
- Added [`docs/data-retention-review.md`](docs/data-retention-review.md) and [`docs/production-deployment.md`](docs/production-deployment.md). They document the stored data, missing expiry automation, required institutional approvals, and concrete first-deploy steps. No production host/domain/secrets were available, so no public deployment was made.

## Phase 2 delivered

- Argon2 password hashing; short-lived signed bearer access tokens; opaque, rotating refresh sessions in HttpOnly, SameSite Strict cookies; hashed CSRF tokens; Origin checks on login, refresh, and logout; role checks; and a one-time environment-configured administrator bootstrap.
- User roles: student, instructor, administrator, and ML maintainer. Administrators can provision student, instructor, and ML maintainer accounts.
- Course creation, instructor-owned course visibility, student memberships, and rosters.
- Student enrollment by email from course management; the API also preserves ID-based enrollment for compatibility.
- Draft exams, MCQ and descriptive questions, publish-time assignment to enrolled students, server-owned exam windows and timers, attempt limits, idempotent resume, versioned answer saves, submission, and objective scoring.
- Student exam serialization omits correct answer IDs. Descriptive answers remain ungraded; scores do not claim an overall grade.
- Admins and course staff can enroll students using the account email rather than needing an undisplayed internal ID.
- Authenticated React workspace with login/session restore, role-specific navigation, account provisioning, courses/rosters, exam creation/question authoring/publishing, student attempt screens, debounced autosave, and server-side submission.
- The workspace uses live API data. AI monitoring, camera capture, and related signals remain out of scope for Phase 2.

## Verification performed

- `npm run build` — passed (TypeScript and Vite production build).
- `uv sync --offline --cache-dir /private/tmp/assessment-uv-cache --locked --extra dev` — passed; API lock refreshed from local cache.
- `uv run --offline --cache-dir /private/tmp/assessment-uv-cache --locked ruff format --check .` and `ruff check .` — passed.
- `uv run --offline --cache-dir /private/tmp/assessment-uv-cache --locked pytest` — **7 passed**, including SQLite API flows for answer-key secrecy, answer versioning, objective scoring, analytics privacy, admin audit access, CORS preflight, expired-frame rejection, and retention deletion behavior.
- `uv run --offline --cache-dir /private/tmp/assessment-uv-cache --locked alembic upgrade head --sql` — passed; generated SQL contains the domain tables, role seed, and bootstrap state.
- `docker compose config -q` — passed.
- Docker Compose stack started successfully; PostgreSQL migration revisions 0001–0003 applied, and API/vision health checks passed. A live model inference request through the private service returned the expected no-signal result on a synthetic blank frame. Browser-based end-to-end testing was not performed.
- `cd ml/tabular && uv sync --locked --extra dev` — passed with isolated environment.
- `cd ml/tabular && uv run --locked ruff format .` and `uv run --locked ruff check .` — passed.
- `cd ml/tabular && uv run --locked pytest` — **3 passed** on generated fixtures.
- `uv run --locked northstar-tabular inspect datasets/mendeley-proctoring-v1/manifest.json` — correctly blocked because target column/schema and an actual CSV checksum are not available.
- `uv run --offline --cache-dir /private/tmp/tabular-uv-cache --locked python scripts/prepare_goel_proxy.py --source-dir data/goel-v1/source --output data/goel-v1/features.csv` — produced 111 grouped student-level records from the supplied raw logs; raw files and output remain gitignored.
- Explicitly opted in to two local research-only runs with `--allow-unreviewed-research-data`, holding out Assessment 2 (seed 42) and Assessment 1 (seed 1) in turn. Metrics are stored in ignored `artifacts/tabular/goel-v1/` and `artifacts/tabular/goel-v1-reverse/`.
- `git diff --check` — passed.
- `cd ml/vision && PYTHONPATH=src python3 -m unittest discover -s tests -v` — **4 passed**.
- `ml/tabular/.venv/bin/ruff format --check ml/vision/src ml/vision/tests` and `ruff check` — passed.
- Audit of the supplied archive — published MD5 and ZIP integrity passed; all images decoded as 640x640 JPEGs; 81 unlabeled test images and one zero-width box were identified.
- `PYTHONPATH=src python3 -u -m northstar_vision.cli train ... --seed 42` — completed on 4,448 training and 1,046 grouped holdout images; measured metrics are above.
- Private API route was smoke-checked in-process with v3: readiness returned the v3 ID, a blank image returned `no_visual_signal` with zero detections, a patterned image returned 200 with 16 detections, and a missing key returned 401. Earlier error-path checks included unsupported media, corrupt/oversized images, and forced timeout. A TCP server bind to localhost was blocked by sandbox policy; no external API was exposed.
- `docker compose -f docker-compose.production.yml config -q` — passed with required production environment values supplied. Local development Compose images built and the app stack started with the vision profile; production Compose has not been deployed.
- Current local API login returned 200 for the provisioned admin; the API CORS preflight from `http://localhost:5688` returned 200 and included `X-Event-Key` in allowed headers. API and vision health checks are healthy; the private detector returned a successful no-signal inference for a synthetic blank PNG.
- Live PostgreSQL demonstration run: one normal exam attempt submitted with 1/1 objective marks; one optional-proctoring attempt accepted consent, uploaded a synthetic blank PNG, received `no_visual_signal` with zero observations, stopped the camera session, and submitted with 1/1. A separate student practice exam is published and unattempted for hands-on review.
- Retention command preview against the live local database (365-day example cutoff) selected zero rows and made no changes. Unit coverage verifies preview is non-destructive, deletion removes related finalized attempt data, an audit record is written, and in-progress attempts are preserved.
- Final combined checks: frontend production build passed; API tests **7 passed**; tabular tests **3 passed**; vision tests **4 passed**; local and production Compose configuration checks passed; `git diff --check` passed. Production config validation used throwaway local values and did not start or deploy production services.
- A second grouped vision training run with seed 2026 did not reach model/evaluation artifact creation in this environment. Its incomplete split file was removed; no additional metrics are claimed. The seed-42 figures remain the only reported model evaluation.

## Important setup

After starting the database and API, run `alembic upgrade head`. Set both `BOOTSTRAP_ADMIN_EMAIL` and `BOOTSTRAP_ADMIN_PASSWORD` before starting the API, call `POST /api/v1/auth/bootstrap-admin` once, then remove those environment values. No administrator password is hard-coded or seeded.

## Known limitations

- Account recovery, password reset, email verification, refresh-session management/revocation UI, and account deactivation workflows are not implemented.
- The web interface supports authoring MCQ questions; the API also supports descriptive questions. Question bank reuse, rich media, bulk rosters, and exam editing are not included yet.
- Autosave is debounced in the browser and guarded by server answer versions; a real browser/network interruption scenario has not been end-to-end tested.
- Deployment-level HTTPS, secret management, rate limiting, and production database operation remain to be configured and verified.
- Phase 1 previously recorded 4 high-severity findings in the development-only npm dependency tree; production dependency audit found zero. This Phase 2 turn did not rerun npm audit.

## Phase 2 core files

- API schema, security, and routes: `services/api/app/models.py`, `services/api/app/security.py`, `services/api/app/api/routes/platform.py`.
- Domain migration: `services/api/migrations/versions/0002_phase2_domain.py`.
- Web workspace: `apps/web/src/PhaseTwo.tsx`, `apps/web/src/App.tsx`, `apps/web/src/styles.css`.
- Integration coverage: `services/api/tests/test_phase2_api.py`.
- Dependency, configuration, and setup: `services/api/pyproject.toml`, `services/api/uv.lock`, `.env.example`, `docker-compose.yml`, `README.md`.

## Phase 3 files

- Pipeline/package: `ml/tabular/pyproject.toml`, `ml/tabular/uv.lock`, `ml/tabular/src/northstar_tabular/`.
- Candidate provenance and review: `ml/tabular/datasets/mendeley-proctoring-v1/manifest.json`, `ml/tabular/datasets/goel-internet-cheating-v1/SOURCE_REVIEW.md`, `ml/tabular/README.md`.
- Reproducible feature transformation: `ml/tabular/scripts/prepare_goel_proxy.py`; local source files, manifest, features, and run outputs are gitignored.
- Generated-fixture tests and CI job: `ml/tabular/tests/test_pipeline.py`, `.github/workflows/ci.yml`.

## Phase 4 files

- Auditor, trainer, inference, and API: `ml/vision/src/northstar_vision/audit.py`, `ml/vision/src/northstar_vision/training.py`, `ml/vision/src/northstar_vision/inference.py`, `ml/vision/src/northstar_vision/api.py`, `ml/vision/src/northstar_vision/cli.py`.
- Supplemental dataset candidate review: `ml/vision/datasets/roboflow-online-proctoring-v1/`.
- Optional model service image: `ml/vision/Dockerfile`.
- Data provenance/spec: `ml/vision/datasets/zenodo-students-online-exam-v1/manifest.json`, `ml/vision/datasets/zenodo-students-online-exam-v1/SOURCE_REVIEW.md`, `ml/vision/datasets/zenodo-students-online-exam-v1/ANNOTATION_SPEC.md`.
- Requirements, tests, and CI: `ml/vision/requirements.txt`, `ml/vision/tests/test_vision_pipeline.py`, `.github/workflows/ci.yml`.
- Ignored local artifacts: `artifacts/vision/zenodo-students-online-exam-v1/hog-svm-grouped-seed42/` (v1), `.../hog-svm-grouped-seed42-v2/` (v2), and `.../hog-svm-grouped-seed42-v3/` (latest exploratory iteration).

## Remaining gates

Phase 4 still needs stronger performance and rights/participant provenance; the supplied five-label archive has been trained in v1-v3, but the results are weak and only seed-42 metrics are available. Phase 5 service-to-model runtime verification is complete with synthetic input; actual browser camera permissions/device checks remain. Phase 6 source-level accessibility fixes and tested manual retention tooling are in; screen-reader review and institution-approved retention durations/scheduling remain. Phase 7 local runtime validation and deployment documentation are complete; a public launch still needs an operator-provided host, domain, TLS, secrets, backups, and monitoring. Phase 3 proxy labels do not validate cheating detection.
