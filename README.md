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
| **Private** | Sensitive values are redacted locally (rules, OCR and an optional local Llama model) before a document is stored. With real documents, question answering only talks to a local model. Claude can write answers for the fictional demo and tag redacted text, always to a destination fixed in code. |

## Measured on real contracts

Evaluated on the official test split of [CUAD](https://www.atticusprojectai.org/cuad), 102 real commercial contracts annotated by lawyers (settings tuned on the separate 408-contract dev split). Full method, ablations and per-category results: **[docs/EVALUATION.md](docs/EVALUATION.md)**.

| Stage | Result |
|---|---|
| Retrieval: the annotated clause reaches the model | **89.5%** of 1,244 questions (55.2% before tuning; 55.5% for "first pages" and 50.6% for random passages at the same budget) |
| Quote check: altered or borrowed quotes accepted | **0 of 6,461** (genuine quotes rejected: 0 of 4,862) |
| Redaction: injected SSNs, tax IDs, card and account numbers, birth dates caught | **1,326 of 1,326**, with 9 flags on 4.8M characters of clean text, all real account or tax numbers |
| Default extractor on real contracts | Abstains on 99.7% of fields instead of guessing |
| End to end with a local 7B model (qwen2.5:7b, 40 questions) | Correctly declined **85%** of questions whose clause is absent; answered **60%** of answerable questions with a citation on the annotated clause |

The end-to-end sample is small (95% intervals of roughly ±20 points); the main gap is recall after retrieval, discussed in the evaluation doc.

## Features

- **Import** PDF (text and scanned, via OCR), DOCX, XLSX, CSV and TXT by drag and drop or whole folders, with bounded parsers, a durable job queue, retries and cleanup.
- **Review queue** with evidence selection, reviewer notes, revisions and explicit execution confirmation.
- **Deadlines**: expiration, notice, confidentiality-end and return dates; reviewed amendments update their parent agreement.
- **Ask agreements**: cited answers with claim-level source buttons and an evidence inspector, or evidence-only search without a model. Count and date questions ("what expires next quarter?") use the reviewed register.
- **Expiration alerts**: weekly summary, urgent and past-due previews to configurable roles and owners (previews only; nothing is sent).
- **Spreadsheet reconciliation**: map tracker columns, preview conflicts, import matched rows as proposals and roll back safely.
- **Labeling taxonomy** (relationship types, owners, components, ID prefix) in [`config/taxonomy.json`](config/taxonomy.json), so it can be adapted to any organization. Folder paths such as `Suppliers/<counterparty>/file.pdf` produce suggested labels.
- **Access scopes** enforced at the API, evidence, search, jobs, download and export boundaries. Demo identities show how access works.

## Try it

You need [Python 3.12 or newer](https://www.python.org/downloads/). Nothing else.

1. **Download** this repository (green **Code** button → **Download ZIP**, then unzip) or `git clone` it.
2. **Double-click** `Clausetrail.command` (macOS) or `Clausetrail.bat` (Windows). The first start takes about a minute to set up; later starts take a few seconds. Your browser opens to Clausetrail.
3. **Sign in** as Alex Morgan and choose **Add agreements → Load fictional examples**.

Then try:

- **Review queue**: open an agreement, check each proposed value against its highlighted source passage, and approve.
- **Ask agreements**: "Can the recipient share the Lark materials with another lab?" or "Which CDAs expire in the next 90 days?" Click the C1, C2 buttons to see the exact quoted evidence.
- **Expiration alerts** and the **Edit log**: every change shows who made it, when, and the old and new value.
- **Switch identity** (bottom left) to Sam Rivera, a viewer, or Jordan Lee, who only sees the restricted legal collection.

On macOS, if a downloaded ZIP says the file "cannot be opened", right-click `Clausetrail.command` → **Open** once. The demo identities show roles, not real sign-in; the app only listens on this computer.

### Turn on written answers

Without a model, **Ask agreements** shows the matching cited passages. For written, cited answers on the fictional demo, copy `.env.example` to `.env` and set:

```sh
QA_PROVIDER=claude
ANTHROPIC_API_KEY=sk-ant-...
```

Restart the launcher. Answers are capped at `QA_DAILY_LIMIT` model calls per day (default 200; a question uses about 2 to 4). Claude answers are refused in the private mode for real documents, which uses a local model instead (below).

### From a terminal

```sh
python -m venv .venv && source .venv/bin/activate
pip install -r backend/requirements.txt
python scripts/start.py --open
```

For scanned PDFs install Tesseract and Poppler (`brew install tesseract poppler`, or `apt install tesseract-ocr poppler-utils`). Node 22+ is only needed to change the interface; a built copy is committed.

### Docker and PostgreSQL

```sh
cp .env.example .env       # set POSTGRES_PASSWORD to a random value
docker compose up --build
```

### Local AI answers (private, works with real documents)

```sh
ollama pull qwen2.5:7b
QA_MODEL=qwen2.5:7b python scripts/start.py --open
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
python -m unittest discover -s tests -v       # 155 tests
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
