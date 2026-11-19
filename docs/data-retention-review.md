# Data retention and privacy review

## Current implementation

- The API does not persist uploaded camera frames. A frame is read into memory, sent to the private inference service, and discarded after processing. The vision service returns boxes and labels; it does not archive the frame.
- The database does persist account details, course membership, exam answers and scores, camera consent decisions, model observation metadata, reviewer decisions, and security audit entries.
- A manual retention command now previews and can delete finalized-attempt data (answers, scores, consent, sessions, observations, and review decisions) as one audited batch. It never selects in-progress attempts. It does not delete accounts, course rosters, exam definitions/assignments, audit history, CSV exports, or backups.
- The command is preview-only unless an operator supplies both an approved policy reference and `--confirm`. It is not scheduled; a runbook/cron schedule must be deliberately configured after policy approval. The current Compose setup persists PostgreSQL in a Docker volume, and backup expiry is not configured here. Do not assume database records disappear when an exam closes or containers stop.
- Retention duration and deletion controls are not configured because the institution, jurisdiction, student age range, appeal/grade-record rules, and approved camera accommodation policy are not known. No legal compliance claim is made.

## Required decision before real student data

The institution operating the service must approve a retention schedule for each category below and a matching deletion process for database backups and exported CSV files.

| Data category | Stored now | Decision needed |
| --- | --- | --- |
| Camera frame bytes | No persistent storage by the API or model service | Confirm that reverse-proxy/container logs and crash dumps never capture bodies |
| Model observations and review notes | Yes | Expiry period, appeal hold, deletion/export behavior |
| Consent decisions | Yes | Keep period for demonstrating consent/revocation, then deletion/anonymization |
| Exam answers, scores, attempts | Yes | Academic-record schedule, appeal holds, student access/correction |
| Account and course membership | Yes | Deactivation and deletion schedule after enrollment ends |
| Audit/security events | Yes | Separate security retention, access controls, redaction, backup expiry |
| CSV exports and database backups | Outside the API's database model | Owner, storage, expiry, access log, and deletion verification |

Before choosing durations, document who approves exceptions and legal/academic holds, who runs deletion, how failures are reported, and how restore procedures prevent already-expired records from reappearing. Test the deletion plan against a disposable copy before applying it to production. Never run destructive cleanup against the current local demo database as a substitute for this review.

## Retention command

Preview finalized attempts older than a proposed duration (this does not delete anything):

```sh
docker compose exec api python -m app.retention --older-than-days 365
```

Only after approval, on a reviewed backup/restore test, pass the institution's policy reference and explicit confirmation:

```sh
docker compose exec api python -m app.retention \
  --older-than-days 365 \
  --apply \
  --approved-policy POLICY-REFERENCE \
  --confirm
```

The duration above is an example command argument, not a recommended or configured retention period. A successful deletion writes an aggregate audit record with the cutoff, policy reference, and deleted row counts.

## Current local demo

The local Compose database contains synthetic administrator/student accounts, a demo course, two submitted practice attempts, and one unattempted practice exam. It contains no genuine student information or stored camera frames. These records are intentionally left available for review.
