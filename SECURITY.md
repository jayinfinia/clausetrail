# Security and data handling

Use fictional files only. The selectable demo identities are role-testing aids, not production authentication. Run on localhost; production mode refuses startup. Do not commit real agreements, secrets or content-bearing logs.

## Implemented controls

- API scope checks before register, jobs, source, evidence, export, question retrieval, edits and deletion.
- Signed, same-site sessions; per-session mutation token; origin checks; restrictive response headers; no document rendering as HTML.
- File extension/signature checks, 25 MB individual limit, 50-file import limit, document/page/archive/text bounds, parser subprocess timeout and resource controls.
- Office macros rejected for extraction; spreadsheet formulas never evaluated; CSV export formula-leading values escaped.
- Review required before operational deadlines; revision conflict checks; cross-scope amendment linking rejected.
- Original demo copies retained for evidence; temporary job copies removed after success/failure and stale copies swept after an hour.
- Cloud AI disabled. Local model metadata is verified before sending evidence; cloud/remote model aliases are rejected. No proxy or redirect following.
- AI answers require exact quotations and a second support-check prompt; sources and permissions are rechecked after inference and when opening citations. These checks reduce risk but do not guarantee semantic correctness.
- Deletion blocks active retrieval and removes source/derived content; protected amendment evidence cannot be removed while referenced.

## Limits

The demo is not certified for zero retention or real contract processing. Signed sessions are not encrypted; only user IDs and CSRF tokens are stored in them. SQLite, local files and backups depend on host encryption/access controls. Subprocess timeouts are not a hardened sandbox. No malware scanner, Entra integration, current SharePoint permission resolver, external notifications or managed backup service is activated.

Database evidence, proposed/reviewed facts, import batches and original uploads are intentionally retained. Question history is not stored. Operational errors expose fixed codes, not parser/provider response contents. Audit records contain action/ID metadata; reviewed values live only in the protected record. Deleting an active copy does not erase prior backups or certify physical SSD erasure.

Label edits and alert-setting changes are logged with old and new label values (relationship type, owner, dates such as relationship end). The edit log is filtered by the same access scopes as the register. `scripts/start.py --private` runs a clearly labeled private local copy in `.local-private/` for an authorized person's own files; it is not a deployment mode and does not relax any control above.

See docs/PRODUCTION.md and docs/runbooks/OPERATIONS.md before any real deployment. Report vulnerabilities through GitHub's private vulnerability reporting for this repository; do not post sensitive payloads in public issues.
