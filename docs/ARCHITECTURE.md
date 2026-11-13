# Architecture

```
 files / folders
      │
      ▼
 ┌──────────────────────┐   rules + OCR + optional local Llama (Ollama, loopback only)
 │ 1. Local redaction   │   only the redacted copy is stored
 └──────────┬───────────┘
            ▼
 ┌──────────────────────┐   PDF (text or scanned via Tesseract), DOCX, XLSX, CSV, TXT
 │ 2. Bounded parsing   │   subprocess with time and size limits, durable job queue
 └──────────┬───────────┘
            ▼
 ┌──────────────────────┐   exact "Label: value" extraction, optional Claude tagging on
 │ 3. Proposals         │   redacted text; every value needs a quote found in its passage
 └──────────┬───────────┘
            ▼
 ┌──────────────────────┐   reviewer approves facts with evidence and confirms execution;
 │ 4. Human review      │   every change goes to the edit log (who, when, old, new)
 └──────────┬───────────┘
            ▼
 ┌──────────────────────┐   deadlines, alerts, CSV export from approved facts only
 │ 5. Register          │
 └──────────┬───────────┘
            ▼
 ┌──────────────────────┐   access check → retrieval → model claims with quotes →
 │ 6. Cited Q&A         │   exact-quote check → support check → access recheck → answer
 └──────────────────────┘
```

## Components

| Path | Role |
|---|---|
| `backend/api/main.py` | FastAPI app: sessions, CSRF and origin checks, scope-aware endpoints |
| `backend/redaction/` | Detection rules, local-model detector, file engines (scanned PDF pixels are burned, text PDFs truly redacted), scoring |
| `backend/services/parsers.py`, `worker.py` | Bounded parsing and the leased job queue with retries and cleanup |
| `backend/services/extraction.py` | Conservative exact-label extraction; abstains otherwise |
| `backend/tagging.py` | Optional Claude tagging: forced tool schema, fixed destination, redacted text only, quote grounding |
| `backend/services/retrieval.py` | Lexical retrieval with synonym expansion, per-document caps and reserved opening passages |
| `backend/services/grounded_qa.py` | Structured synthesis, exact-quote and numeric-literal checks, per-claim support check, conflict warnings |
| `backend/services/queries.py` | Deterministic count and date reports over reviewed facts (no model) |
| `backend/domain/framework.py` | Labeling taxonomy loaded from `config/taxonomy.json`, file-name and folder conventions, end-date rules |
| `backend/connectors/sharepoint.py` | Read-only Microsoft Graph adapter (mock-tested, not wired to the demo) |
| `frontend/` | React and TypeScript UI served from the same origin |
| `eval/cuad_eval.py` | Evaluation on the CUAD contract benchmark (see docs/EVALUATION.md) |

## Design rules

- **Nothing automatic is a fact.** Extraction, tagging and folder hints produce proposals. Facts become approved only when a reviewer accepts them with a supporting passage, and deadlines count only reviewer-confirmed executed agreements.
- **Every claim is quoted.** A model claim survives only if each quote occurs verbatim (whitespace aside) in the cited passage, every number or date in the claim appears in the cited text, and a separate support-check call agrees the evidence supports the claim and answers the question. Status (answered, partial, conflicting, insufficient evidence) is computed by the server, never taken from the model.
- **Access is checked before retrieval and again after inference.** Sources deleted, revised or made inaccessible during inference are dropped, and citation inspection revalidates them again.
- **No data egress by default.** Question answering only talks to a local Ollama host, rejects cloud model names and ignores proxy settings. Claude tagging is opt-in, receives only locally redacted text, and its destination is fixed in code.
- **Counts and dates are not left to the model.** Questions such as "what expires next quarter" are answered from the reviewed register.

## Storage

SQLAlchemy models persist agreements, jobs, proposal batches, labels and audit events in PostgreSQL (Docker Compose) or SQLite (standalone quickstart). Original files are kept for evidence; temporary job copies are removed after each job and swept after an hour. Question and answer bodies are not stored.

## Operational boundaries

One embedded worker is the default; `RUN_WORKER=false` allows a separate `python -m backend.services.worker` process. PostgreSQL claims jobs with row locks; SQLite uses a conditional claim. Jobs that exceed their lease return to the queue with capped attempts. The schema is created idempotently; future changes need explicit migrations. See docs/PRODUCTION.md for what a real deployment would require.
