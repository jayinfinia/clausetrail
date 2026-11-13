# Clausetrail

**Source-cited, auditable agreement review that runs on your own machine.**

Clausetrail turns a folder of contracts (NDAs, material transfer agreements, services and collaboration agreements) into a reviewed register with deadlines, alerts and question answering. Every automated value is a proposal tied to a quoted passage, every answer is checked against its sources before it is shown, and every change is logged.

> Every organization, person and agreement in this repository is fictional. The demo organization is "Northwind Labs".

## Why

When an AI system reads contracts for a team, the hard part is not producing an answer. It is being able to show where the answer came from, prove that nothing was invented, and keep sensitive values from leaving the building. Clausetrail is built around those three requirements:

| Requirement | How it is enforced |
|---|---|
| **Traceable** | Each claim cites passages; the quote must occur verbatim in the source, numbers in the claim must appear in the cited text, and a separate support-check call must agree. Otherwise the claim is dropped and the answer is marked partial or abstains. |
| **Auditable** | Nothing extracted becomes a fact until a reviewer approves it with evidence. Imports, reviews, label edits and settings changes are logged with who, when, old and new value. Deadlines and counts come from reviewed facts, not from a model. |
| **Private** | Sensitive values are redacted locally (rules, OCR and an optional local Llama model) before a document is stored. Question answering only talks to a local model. Optional Claude tagging receives redacted text only, to a destination fixed in code. |

## Measured on real contracts

Evaluated on the official test split of [CUAD](https://www.atticusprojectai.org/cuad), 102 real commercial contracts annotated by lawyers (settings tuned on the separate 408-contract dev split). Full method, ablations and per-category results: **[docs/EVALUATION.md](docs/EVALUATION.md)**.

| Stage | Result |
|---|---|
| Retrieval: the annotated clause reaches the model | **89.5%** of 1,244 questions (55.2% before tuning; 55.5% for "first pages" and 50.6% for random passages at the same budget) |
| Quote check: altered or borrowed quotes accepted | **0 of 6,461** (genuine quotes rejected: 0 of 4,862) |
| Redaction: injected SSNs, tax IDs, card and account numbers, birth dates caught | **1,326 of 1,326**, with 9 flags on 4.8M characters of clean text, all real account or tax numbers |
| Default extractor on real contracts | Abstains on 99.7% of fields instead of guessing |

End-to-end answer accuracy needs a local model; the harness is included (`python -m eval.cuad_eval live`) and results are pending.

## Features

- **Import** PDF (text and scanned, via OCR), DOCX, XLSX, CSV and TXT by drag and drop or whole folders, with bounded parsers, a durable job queue, retries and cleanup.
- **Review queue** with evidence selection, reviewer notes, revisions and explicit execution confirmation.
- **Deadlines**: expiration, notice, confidentiality-end and return dates; reviewed amendments update their parent agreement.
- **Ask agreements**: cited answers with claim-level source buttons and an evidence inspector, or evidence-only search without a model. Count and date questions ("what expires next quarter?") use the reviewed register.
- **Expiration alerts**: weekly summary, urgent and past-due previews to configurable roles and owners (previews only; nothing is sent).
- **Spreadsheet reconciliation**: map tracker columns, preview conflicts, import matched rows as proposals and roll back safely.
- **Labeling taxonomy** (relationship types, owners, components, ID prefix) in [`config/taxonomy.json`](config/taxonomy.json), so it can be adapted to any organization. Folder paths such as `Suppliers/<counterparty>/file.pdf` produce suggested labels.
- **Access scopes** enforced at the API, evidence, search, jobs, download and export boundaries. Demo identities show how access works.

## Run locally

Requires Python 3.12+ and Node 22+. For scanned PDFs install Tesseract and Poppler (`brew install tesseract poppler` on macOS, `apt install tesseract-ocr poppler-utils` on Debian or Ubuntu).

```sh
python -m venv .venv && source .venv/bin/activate
pip install -r backend/requirements.txt
python scripts/start.py
```

Open http://localhost:8000, sign in as **Alex Morgan** and choose **Add agreements → Load fictional examples**. Open the **Review queue**, inspect the evidence and approve. Switch to **Sam Rivera** (viewer) or **Jordan Lee** (restricted legal collection) to see access scoping.

The demo identities are for showing roles, not real authentication. Keep the app on localhost.

### Docker and PostgreSQL

```sh
cp .env.example .env       # set POSTGRES_PASSWORD to a random value
docker compose up --build
```

### Local AI answers

```sh
ollama pull qwen2.5:7b
QA_MODEL=qwen2.5:7b python scripts/start.py
```

See [docs/AI_QA.md](docs/AI_QA.md) for how answers are checked and what the screen shows.

### Redaction

| Policy | Removes | Keeps |
|---|---|---|
| `standard` (default) | SSNs and tax IDs (including EIN/TIN), bank and card numbers, dates of birth | Names, addresses, emails, agreement dates, amounts |
| `strict` | Standard, plus people's names (as consistent `[PERSON 1]` tokens, also in file and folder names), emails, phone numbers and street addresses | Company names, dates, amounts |

Scanned PDFs are OCR'd and the boxes are burned into the page pixels, so nothing survives under a black box. Text PDFs are truly redacted. Word, Excel, CSV and text files get `[REDACTED ...]` tokens, and author metadata is cleared. Every output is re-read and anything still detectable is reported.

```sh
python scripts/redact.py IN_DIR OUT_DIR --policy standard        # folder runner with an HTML scorecard
python scripts/make_redaction_samples.py .local/redaction-samples  # fictional forms with reference redactions
```

### Optional Claude tagging

Claude can fill review fields and labels from the **redacted** text. It is off unless both variables are set; values are proposals that keep their passage only if Claude's quote is found in it, and labels a reviewer already confirmed are never overwritten.

```sh
export ANTHROPIC_API_KEY=...   # never commit it
export CLAUDE_TAGGING=on
python scripts/start.py
```

## Checks

```sh
pip install -r requirements-dev.txt
python -m unittest discover -s tests -v       # 150 tests
npm ci --prefix frontend && npm run build --prefix frontend
python -m scripts.smoke http://localhost:8000  # live HTTP flow against a running demo
```

CI runs the suite against SQLite and PostgreSQL and builds the frontend.

## Documentation

- [docs/EVALUATION.md](docs/EVALUATION.md): benchmark method and results
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md): pipeline, components and design rules
- [docs/AI_QA.md](docs/AI_QA.md): cited question answering
- [docs/PRODUCTION.md](docs/PRODUCTION.md): what a real deployment would need
- [SECURITY.md](SECURITY.md): controls and limits

## Data

The CUAD contracts used for evaluation are © The Atticus Project, licensed CC BY 4.0, and are downloaded at evaluation time rather than stored here. All fixtures in `demo/` are fictional.

## License

MIT, see [LICENSE](LICENSE).
