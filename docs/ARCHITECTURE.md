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
 │ 2. Bounded parsing   │   subprocess with time and size limits, durable job queue;
 └──────────┬───────────┘   paragraph/clause blocks with page-and-paragraph locators
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
| `backend/services/parsers.py`, `worker.py` | Bounded parsing into citation blocks and the leased job queue with retries and cleanup (see Import below) |
| `backend/services/extraction.py` | Conservative exact-label extraction; abstains otherwise |
| `backend/tagging.py` | Optional Claude tagging: tool schema, fixed destination, redacted text only, quote grounding, instruction-like values dropped |
| `backend/services/quotes.py` | Typography-tolerant quote matching and the number/date literal check |
| `backend/services/retrieval.py` | Lexical retrieval with synonym expansion, per-document caps and reserved opening passages |
| `backend/services/grounded_qa.py` | Structured synthesis, exact-quote and numeric-literal checks, per-claim support check, conflict warnings |
| `backend/services/queries.py` | Deterministic count and date reports over reviewed facts (no model) |
| `backend/domain/framework.py` | Labeling taxonomy loaded from `config/taxonomy.json`, file-name and folder conventions, end-date rules |
| `backend/connectors/sharepoint.py` | Read-only Microsoft Graph adapter (mock-tested, not wired to the demo) |
| `frontend/` | React and TypeScript UI served from the same origin |
| `eval/cuad_eval.py` | Evaluation on the CUAD contract benchmark (see docs/EVALUATION.md) |

## Design rules

- **Nothing automatic is a fact.** Extraction, tagging and folder hints produce proposals. Facts become approved only when a reviewer accepts them with a supporting passage, and deadlines count only reviewer-confirmed executed agreements.
- **Every claim is quoted.** A model claim survives only if each quote occurs verbatim (whitespace and quote/dash glyphs aside; see docs/AI_QA.md) in the cited passage, every number or date in the claim appears in the cited text (or is a stated period after a stated date, flagged as computed), and a separate support-check call agrees the evidence supports the claim and answers the question. Status (answered, partial, conflicting, insufficient evidence) is computed by the server, never taken from the model.
- **Access is checked before retrieval and again after inference.** Sources deleted, revised or made inaccessible during inference are dropped, and citation inspection revalidates them again.
- **No data egress by default.** Question answering talks to a local Ollama host, rejects cloud model names and ignores proxy settings. Two opt-in exceptions, both with destinations fixed in code: Claude can write answers in the fictional demo (refused in private mode, daily call cap), and Claude tagging receives only locally redacted text.
- **Counts and dates are not left to the model.** Questions such as "what expires next quarter" are answered from the reviewed register.

## Import

Blocks are the unit of citation, so each format is split into passages a reviewer can check at a glance:

| Format | Block | Locator |
|---|---|---|
| Text PDF | paragraph or clause, from pypdf text positions | `Page 2, paragraph 3`, or `(continues on page 3)` when a paragraph crosses a page break |
| Scanned PDF | paragraph or clause, from Tesseract word boxes (Poppler render at 300 DPI, `--psm 3`) | same as text PDF |
| Word | paragraph (with its automatic list number), table row with column headers, page header and footer | `Paragraph 7 (under "Term")`, `Table 1, row 2`, `Page header` |
| TXT, CSV | line; lines over 2,000 characters are split at sentence boundaries | `Line 4`, `Line 1, part 2` |
| XLSX | row | `Sheet, row 3` |

Paragraph breaks come from layout cues: extra vertical space, a clause start (`4.`, `4.1`, `(a)`, `Section 5`) or `Label:` line after a finished line, headings, font changes, indentation changes and column jumps. Wrapped lines are joined with a space and words hyphenated at a line break are re-joined, so a quote that crosses a line in the original still passes the exact-quote check. Lines in the top or bottom margin that repeat on most pages (running headers, footers) and bare page numbers are dropped.

Problems that do not stop reading are stored as content-free warnings in `labels.import` and shown on the agreement: low OCR confidence (mean word confidence under 80%), a tilted scan (the word layout is rotated back before paragraphs are measured), tracked changes in Word (text is read with all changes accepted), and text that is not UTF-8 (read as Windows-1252). Problems that do stop reading fail the job with a short code such as `pdf_is_password_protected_remove_the_password_and_import_again` or `no_readable_text_found`. Trackers, legacy and unsupported formats, password-protected Office files and empty files are rejected at upload without creating a record.

## Storage

SQLAlchemy models persist agreements, jobs, proposal batches, labels and audit events in PostgreSQL (Docker Compose) or SQLite (standalone quickstart). Original files are kept for evidence; temporary job copies are removed after each job and swept after an hour. Question and answer bodies are not stored.

## Operational boundaries

One embedded worker is the default; `RUN_WORKER=false` allows a separate `python -m backend.services.worker` process. PostgreSQL claims jobs with row locks; SQLite uses a conditional claim. Jobs that exceed their lease return to the queue with capped attempts. The schema is created idempotently; future changes need explicit migrations. See docs/PRODUCTION.md for what a real deployment would require.
