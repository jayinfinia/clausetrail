# Ask AI with source citations

The question screen supports a full local AI path: authorized retrieval → structured synthesis → exact-quote validation → independent support-check prompt → final authorization/version check → cited answer. It can abstain rather than invent an answer. This design reduces unsupported answers; it does not guarantee correctness.

## Start AI on your computer

Install Ollama from its official distribution. In one terminal run `OLLAMA_NO_CLOUD=1 ollama serve` if the app is not already running. Choose a model that fits your hardware and test it; `qwen2.5:7b` is one example, not an accuracy guarantee.

```sh
ollama pull qwen2.5:7b
# In the repository with the Python environment activated:
QA_MODEL=qwen2.5:7b python scripts/start.py
```

Model download can be several GB. Windows PowerShell: `$env:QA_MODEL='qwen2.5:7b'; python scripts/start.py`. QA_MODEL enables question synthesis without turning on model extraction for every uploaded document. OLLAMA_MODEL remains the separate extraction setting and a fallback QA model name.

Open Ask agreements. The status panel checks the actual local model list. Select **AI answer** to require AI; missing/unavailable inference returns an error. **Auto** uses the model when configured, otherwise explicitly labels evidence-only results. **Evidence only** never runs inference. Narrow the source scope to one agreement when useful.

## Docker option

Set POSTGRES_PASSWORD and QA_MODEL in `.env`, then:

```sh
docker compose -f compose.yaml -f compose.ai.yaml up --build -d
docker compose -f compose.yaml -f compose.ai.yaml exec ollama ollama pull qwen2.5:7b
```

The installed model name must match QA_MODEL. The model service has no host port. The optional overlay uses the official Ollama image; pin an evaluated version or digest before any real deployment. No GPU is assumed; CPU inference may be slow. This complete model/container path has not been run in the authoring environment.

## What the answer shows

- Claim-level source buttons, such as C1, open an evidence inspector.
- File name, page/paragraph/cell location, version, review revision and the exact quoted text.
- Original context with the supporting span highlighted and an authenticated source download.
- Reviewed-record citations for exact counts and date reports; these are clearly distinguished from document quotations.
- Review state, retrieval coverage, conflicting evidence and partial-answer warnings.
- Explicit insufficient-evidence responses when claims cannot pass the checks.

If the source is deleted, revised or no longer accessible, citation inspection fails closed and asks the user to query again. Sources are rechecked after inference as well. Existing answers cannot erase what a user has already seen.

## Accuracy safeguards and limits

Quotes must occur in the provided passage; invented IDs, fabricated quotes, unsupported numeric literals and malformed schemas are rejected. Matching tolerates typography only (`backend/services/quotes.py`): whitespace, curly versus straight quotes, dash glyphs, soft hyphens, zero-width characters and a word hyphenated across a line break. A quote with "..." elisions is accepted only when every part occurs in order in one passage; the citation then shows the full original span, omitted words included, and the support check judges that full span. A quote that runs from one passage into the next one of the same document is cited in both. Any change of words, letters, digits or other punctuation is rejected. A second model call judges both support and relevance. Only claims with an explicit affirmative verdict are shown. This uses the same configured model with a different task; its errors may be correlated. A valid quotation is not proof that an interpretation is correct.

The synthesis schema asks for evidence-first claims before any judgement, restricts source IDs to the supplied passages, and never takes an answer status from the model. Each claim is support-checked separately. The check also receives the cited documents' identity (counterparty, our organization, party roles defined in the document's opening such as `Northwind Labs, LLC ("Recipient")`) and the other claims of the same answer as context, so a defined term or a condition stated in a sibling claim is not held against a claim. A date or number in a claim must appear in its cited passages or the cited document's name; the same date in another unambiguous format ("March 2, 2026" and 2026-03-02) and a number written as a word ("sixty days") count as stated. A date that is a stated period after a stated date ("two (2) years from June 1, 2026" and 2028-06-01) is accepted, marked as `computed_dates` on the claim and named in a warning; any other derived value is rejected. A literal found in exactly one passage of the same or an amendment-related document is cited from there before checking.

Protocol failures are handled without loosening the gate. A reply with no readable JSON object is requested once more. A verdict whose booleans are not JSON booleans fails closed. With one claim per check, a single verdict is used whatever its claim_index; missing or duplicate verdicts reject the claim. If no verdict at all can be read the request fails with an error rather than an "insufficient evidence" answer; if only some fail, those claims are removed and a warning says so. A malformed individual claim (no text, a quote too short or too long) is dropped and counted instead of failing the answer.

When every claim fails the support check as worded but the checker judged it on-topic, the answer has status `quoted_evidence`: only the verified verbatim spans are shown, the rejected sentences are not, and a warning says these are excerpts rather than an answer. Every AI answer carries a `diagnostics` object with counts only (claims drafted, malformed, quote not found, number not in evidence, support check unreadable, unsupported, off-question, truncated). Cross-document claims are labelled with the document they cite, and the answer discloses how many examined documents it cites. See docs/EVALUATION.md for measured results.

Only narrowly recognized count/date reports use deterministic queries. Questions such as “How many agreements require consent?” are not silently treated as counts of all agreements. They require AI evidence analysis and may abstain. Retrieval is lexical with domain synonym expansion and document diversity; selected passages can omit relevant context. Full-corpus completeness is not promised. OCR inaccuracies, unstated terms and ambiguous amendments still need human review.

## Claude transport (fictional demo)

With QA_PROVIDER=claude the passages are sent as XML (`<documents>`, one `<document>` per agreement with `<passage source_id=...>`), with the question last; the support check stays JSON. Tag-like text inside a passage that could close that structure is neutralized. Replies are taken from the tool call, a single tool call under another name, an answer wrapped in `{"input": ...}`, or a JSON object written in text after prose; source IDs are compared case-insensitively. Rate-limited, overloaded (429, 529) and transient server errors are retried up to three attempts, honouring `retry-after` (capped at 30 s) and otherwise backing off exponentially; these attempts are not billed and do not count against QA_DAILY_LIMIT. A reply cut off at max_tokens is never parsed: it is requested once more with a larger limit, and both calls count. Timeouts give a fixed message. No request or response body is logged or included in errors. This path is tested with mocked replies only.

## Data handling

All inference is sent to the configured local Ollama endpoint, with no cloud fallback or tool execution. The transport rejects cloud model names and requires local model metadata before transmitting evidence; also disable Ollama cloud features on the model server. The app does not persist question/answer bodies in logs, its database or browser local storage. Model-server logging and host retention remain operator responsibilities. This is not provider ZDR certification.

## Evaluation

```sh
python -m unittest discover -s tests -v
QA_MODEL=qwen2.5:7b python -m scripts.evaluate_qa --live
```

The opt-in live evaluator uses only fictional clauses, validates expected source references and reports per-case results. A failed case exits nonzero. Offline tests exercise the real pipeline with controlled model responses; they do not measure a live model's accuracy. See docs/EVALUATION.md for the public-benchmark evaluation.

## References

- https://docs.ollama.com/api/chat: chat and structured output schema
- https://docs.ollama.com/api/tags: model availability

## Deadline and count reports

Questions that name a reporting period ("How many agreements are due in 2026?", "Which CDAs expire next month?", "What is overdue?") use the reviewed register, not the model. This covers a year, a month, this/next month, quarter or year, the next N days, before or by a date, and overdue. Retrieval sees only a sample of passages, so model counts across many agreements would be unreliable. "Due" counts every reviewed deadline: expiration, notice, confidentiality end and return. "Expire" counts expirations only. If the question adds any other condition or party ("…that require consent…", "Which Aster agreements…"), it goes to evidence analysis, so no filter is silently dropped. Reports include only reviewer-confirmed executed agreements. An amendment changes a date only after it is reviewed and linked to its parent.
