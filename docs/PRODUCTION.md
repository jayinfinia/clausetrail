# What a real deployment would need

This repository is a local demonstration that runs on fictional data. Setting `DEMO_MODE=false` stops startup on purpose, so the selectable demo identities can never sit in front of real documents.

Before using it with real agreements, an operator would need to:

1. **Identity.** Replace demo sessions with real token validation (for example Microsoft Entra ID or another OIDC provider), map users and groups to access scopes, use secure cookies and define revocation. Administrator rights must not bypass source access.
2. **Hosting.** Deploy into infrastructure the organization controls, with managed identities, restricted network paths, secret storage and monitoring. Validate PostgreSQL migrations and restores on the actual service.
3. **Document sources.** Connect the Microsoft Graph adapter (`backend/connectors/sharepoint.py`) to an approved drive with read-only permissions, then add persistent checkpoints, scheduled sync and permission and deletion reconciliation. Copying one group scope onto a whole drive is not enough when documents have mixed permissions.
4. **Model providers.** Review every model, OCR and embedding endpoint and confirm retention terms. Cloud processing for question answering stays disabled in this build. Claude tagging only receives locally redacted text and is off unless explicitly enabled.
5. **Parser isolation.** Run untrusted parsers in an isolated container or sandbox and add malware scanning, request-size enforcement and rate limiting. The demo's subprocess timeout is not a full sandbox.
6. **Retention.** Decide retention for evidence, source copies, metadata, audit records, legal holds and backups. Restores must replay deletion tombstones before serving data. Deleting an active copy is not certified physical erasure.
7. **Accuracy.** Measure extraction and question-answering quality on a representative sample of the organization's own documents, with agreed error thresholds for critical dates. See docs/EVALUATION.md for the public-benchmark method.
8. **Ownership.** Name reviewers and support owners, and connect reminder delivery and escalation. In-app deadline views are not legal notice.
