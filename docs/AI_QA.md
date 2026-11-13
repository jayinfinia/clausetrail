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

Quotes must occur in the provided passage; invented IDs, fabricated quotes, unsupported numeric literals and malformed schemas are rejected. A second model call judges both support and relevance. Only claims with an explicit affirmative verdict are shown. This uses the same configured model with a different task; its errors may be correlated. A valid quotation is not proof that an interpretation is correct.

The synthesis schema asks for evidence-first claims before any judgement, restricts source IDs to the supplied passages, and never takes an answer status from the model. Each claim is support-checked separately. A date or number in a claim must appear in its cited passages; a literal found in exactly one passage of the same or an amendment-related document is cited from there before checking. Cross-document claims are labelled with the document they cite, and the answer discloses how many examined documents it cites. See docs/EVALUATION.md for measured results.

Only narrowly recognized count/date reports use deterministic queries. Questions such as “How many agreements require consent?” are not silently treated as counts of all agreements. They require AI evidence analysis and may abstain. Retrieval is lexical with domain synonym expansion and document diversity; selected passages can omit relevant context. Full-corpus completeness is not promised. OCR inaccuracies, unstated terms and ambiguous amendments still need human review.

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
