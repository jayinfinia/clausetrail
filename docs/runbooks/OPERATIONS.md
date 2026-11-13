# Local demo operations

## Processing failure

Inspect the fixed error code in Import files. Confirm the file is supported and readable. If local AI is enabled, check the model service locally without copying document contents into logs. Retry creates a new bounded job. Unreadable, password-protected and ambiguous documents require user correction, not endless retries.

## Worker recovery

Jobs running longer than five minutes return to the queue with a capped attempt count. Temporary directories older than one hour are swept. Monitor queue state and cleanup failures in any real deployment. The production monitoring/alerting integration is not active.

## Deletion

The UI deletion action removes active source copies, facts, passages and proposals and cancels jobs. A referenced amendment is protected until parent facts are revised. Store deletion tombstones with backups and replay them before serving a restored database. Demo backup restore is a manual operator task; no claim is made that live deletion erases backup media.

## Backups for local development

Stop the application and worker before copying `.local` (SQLite and originals together). For PostgreSQL use pg_dump plus a consistent copy of the original-file volume; restore into an isolated environment first. Preserve the session key privately or deliberately rotate it to invalidate sessions. Never commit backup archives. Establish tested RPO/RTO and records-hold requirements before production use.

## Reset

For disposable fictional data, stop the app and remove its `.local` folder to reset standalone state. Docker named volumes retain data across restarts; delete them only when intentionally discarding the entire fictional demo. Production data must never use this reset procedure.

## Dependency and release checks

Install requirements-dev.txt, run the unittest suite against an isolated test database, and build the frontend with npm ci. CI includes SQLite and PostgreSQL jobs. Rebuild frontend assets after edits. Review changes before upgrading pinned dependencies. No automated production deployment is configured.
