# Evaluation

Clausetrail answers questions about contracts by retrieving passages, asking a model for claims with exact quotes, checking every quote against the source, and running a second support check before anything is shown. This page measures each stage that can be measured without a model on **real contracts**, and gives the harness for the stage that needs one.

All numbers come from `eval/cuad_eval.py` and are stored in `eval/results/`. They are deterministic: rerunning the commands below reproduces them exactly.

## Dataset

[CUAD v1](https://www.atticusprojectai.org/cuad) (Hendrycks, Burns, Chen and Ball, *CUAD: An Expert-Annotated NLP Dataset for Legal Contract Review*, NeurIPS 2021) has 510 commercial contracts from public SEC filings, annotated by lawyers for 41 clause categories such as governing law, change of control and non-compete. It is licensed CC BY 4.0. The contracts are not redistributed in this repository; the commands below download them.

| Split | Contracts | Used for |
|---|---|---|
| **test** (official CUAD test split) | 102 | Every number reported on this page |
| **dev** (the other 408) | 408 | Choosing retrieval settings. Test was run once per setting choice, after the choice was made on dev |

The median test contract is about 25,700 characters, longer than the 20,000-character context budget, so retrieval decides what the model can see.

```sh
git clone --depth 1 https://github.com/TheAtticusProject/cuad.git .local/cuad
unzip -o .local/cuad/data.zip -d .local/cuad/data
python -m eval.cuad_eval all --cuad .local/cuad/data                       # test split, about 1 minute
python -m eval.cuad_eval retrieval --cuad .local/cuad/data --split dev     # tuning split
```

## Summary (CUAD test split)

| Stage | What is measured | Result |
|---|---|---|
| Retrieval | Questions where the lawyer-annotated clause reaches the model | **90.2%** (1,244 questions), up from 55.2% at the first measurement |
| Quote check | Fabricated or altered quotes accepted | **0 of 6,461** |
| Quote check | Genuine quotes (verbatim or re-wrapped) rejected | **0 of 4,862** |
| Redaction (rules only) | Injected SSNs, tax IDs, card and account numbers, birth dates caught | **100%** (1,326 values, 13 layouts) |
| Redaction (rules only) | Flags on 4.8 million characters of clean contract text | 9 flags, all real bank, routing or tax numbers on manual review |
| Default extractor | Fields it proposes on real contracts | Abstains on 99.7% of fields, by design |
| End-to-end answers (qwen2.5:7b, 40 questions) | Answerable questions answered with a citation on the annotated clause | **60%** (12 of 20) |
| End-to-end answers (qwen2.5:7b, 40 questions) | Questions with no such clause where the system correctly declined | **85%** (17 of 20) |

## 1. Retrieval

**Question.** For each CUAD question with at least one annotated answer, the question is phrased as *"What does the contract say about governing law? Which state/country's law governs the interpretation of the contract?"* (category name plus CUAD's own description). The contract is split exactly like the app's text importer, one block per line. (Since the import hardening change the app also splits lines over 2,000 characters into sentence-aligned parts; the evaluation replica does not, and the figures here were not re-measured with that split. Retrieval already reads blocks in 1,800-character windows, so the effect is limited to window boundaries on very long lines.)

**Metric.** A question is a *hit* when at least one passage sent to the model overlaps a lawyer-annotated answer span. *All spans* requires every annotated span to be covered. Baselines get exactly the same number of characters Clausetrail used for that question.

| System | Hit rate | All spans | Span recall | Median context sent |
|---|---|---|---|---|
| **Clausetrail (current)** | **90.2%** | **79.0%** | **79.6%** | 19,638 chars, 34 passages |
| Clausetrail before tuning | 58.2% | 45.2% | 42.0% | 3,157 chars, 3 passages |
| Same budget, first passages of the document | 55.2% | 50.2% | 49.1% | same as current |
| Same budget, random passages | 50.4% | 39.0% | 39.2% | same as current |

**What changed, and why.** The first run showed two problems, and a live test with Claude later showed a third:

1. **Unused budget.** Retrieval capped every document at 3 passages so that one repetitive agreement could not crowd out the others in a large collection. With a single contract in scope that cap left 85% of the budget empty. The cap now spreads the passage limit over the documents that matched: still 3 per document for large collections, more when few documents are in scope.
2. **Front matter.** Titles, parties and dates sit at the top of a contract and rarely share words with the question. The opening 1,500 characters of each matched document are now reserved when few documents are in scope.

3. **Word forms and repeat parties.** "expires" did not match "expire", and a party with several agreements (an MTA, its amendment and a renewal) stopped counting as a name, so a question naming it was not narrowed to its documents. Retrieval now applies light, consistent suffix stripping to questions and passages, and a party name counts as distinctive when it appears in up to a quarter of the collection. Measured the same way (dev first): dev 90.0% to 90.5%, test 89.5% to 90.2%. The before-tuning baselines moved too, because stemming applies to every configuration.

Ablation on the same test questions, with settings chosen on dev first:

| Setting | Dev hit rate | Test hit rate |
|---|---|---|
| Before tuning (3 per document, no opening) | 58.9% | 58.2% |
| Spread cap, no reserved opening | 82.7% | 82.6% |
| Spread cap, 3,000-character opening | 89.0% | 85.8% |
| **Spread cap, 1,500-character opening (shipped)** | **90.5%** | **90.2%** |

Dev and test agree within a point, so the choice was not fitted to the test set.

**Where it is still weak.** Hit rate by CUAD category (test, worst first):

| Category | Questions | Current | Before | First passages | Random |
|---|---|---|---|---|---|
| No-Solicit Of Customers | 7 | 57.1 | 57.1 | 57.1 | 28.6 |
| Non-Disparagement | 7 | 57.1 | 57.1 | 14.3 | 28.6 |
| Revenue/Profit Sharing | 35 | 60.0 | 20.0 | 51.4 | 48.6 |
| Affiliate License-Licensor | 6 | 66.7 | 16.7 | 33.3 | 50.0 |
| Unlimited/All-You-Can-Eat-License | 3 | 66.7 | 33.3 | 66.7 | 66.7 |
| Competitive Restriction Exception | 16 | 68.8 | 31.2 | 50.0 | 18.8 |
| Volume Restriction | 17 | 70.6 | 17.6 | 58.8 | 47.1 |
| Joint Ip Ownership | 7 | 71.4 | 42.9 | 0.0 | 28.6 |
| Ip Ownership Assignment | 23 | 73.9 | 39.1 | 39.1 | 56.5 |
| Governing Law | 83 | 97.6 | 90.4 | 25.3 | 44.6 |
| Parties | 102 | 100.0 | 28.4 | 100.0 | 63.7 |
| Anti-Assignment | 72 | 100.0 | 90.3 | 31.9 | 54.2 |

The full table for all 41 categories is in `eval/results/retrieval.json`. The weak categories are the ones where the contract uses different words from the question ("shall not make any statement that disparages" vs "non-disparagement"; "royalty" vs "revenue sharing"). Lexical retrieval with a small synonym list cannot close that gap. The obvious next step is adding a local embedding model and fusing its ranking with the lexical one, measured on the same dev/test protocol.

## 2. Quote check

Every claim a model makes must carry a quote that occurs in the cited passage. Each lawyer-annotated answer span (12+ characters) was offered to the check as if a model had cited it, then altered in the ways models typically misquote.

| Variant | Cases | Should | Accepted |
|---|---|---|---|
| Verbatim | 2,432 | accept | 100% |
| Re-wrapped line breaks | 2,430 | accept | 100% |
| One digit changed | 967 | reject | 0% |
| "not" inserted after shall/will/may/must | 1,236 | reject | 0% |
| One word dropped | 1,833 | reject | 0% |
| A real clause of the same category from a different contract | 2,425 | reject | 0% |

Two borrowed clauses were skipped because the identical boilerplate really does appear in the target contract, where accepting it would be correct.

**Limit.** This check is exact matching, so these results show that it is implemented correctly on long, messy real text, not that answers are right. A model can quote a real sentence and still misread it. That is what the separate support-check call is for, and it can only be measured with a model (section 5).

## 3. Redaction (standard policy, rules only)

**Recall on injected values.** Fictional SSNs, EINs, card numbers (Luhn-valid), bank account numbers and dates of birth were inserted into each of the 102 real contracts at a random sentence boundary, in 13 layouts: labeled, unlabeled, label on the previous line, no dashes, spaced card digits, long-form dates and phrases such as "born on March 4, 1985". A value counts as caught only if one redaction span covers all of it.

Result: **1,326 of 1,326 caught**, with no oversized spans. The first run caught 92.3%: the "born on ..." phrasing was missed in every case. The rule was extended and a regression test added (`tests/test_redaction.py`). Because the layouts were written by the same person as the rules, treat this as a regression suite rather than proof of real-world recall; the optional local Llama detector exists for layouts the rules do not anticipate.

**Flags on clean text.** On the unmodified contracts (4.8 million characters), the standard policy raised 9 flags: 7 bank account or ABA routing numbers in payment and escrow clauses, and 2 company EINs on signature blocks. All 9 are values the policy is meant to remove. Names, dates, dollar amounts and addresses were left intact.

## 4. Default extractor

Without a model, the importer only reads explicit `Label: value` lines. On the 102 test contracts it proposed 3 values out of 1,122 field slots (99.7% abstention), all effective dates, and marked all 3 *ambiguous* rather than guessing (two of the three evidence lines matched CUAD's annotation). That is the intended behavior: on real contracts the deterministic path stays silent instead of inventing values, and model-assisted tagging with quote grounding (`backend/tagging.py`) fills the fields as proposals for a reviewer.

## 5. End-to-end answers (local model)

The harness samples answerable and unanswerable CUAD test questions in equal numbers and runs the full pipeline: retrieval, structured synthesis, quote check, support check. First run: **qwen2.5:7b** (4.7 GB, 4-bit) through Ollama on an Apple Silicon MacBook Pro, 40 questions, seed 20261113, no errors.

| Metric | Result | 95% interval (Wilson) |
|---|---|---|
| Answerable questions answered (20) | 70% (14) | 48 to 85% |
| Answerable questions answered with a citation on the lawyer-annotated clause | 60% (12) | 39 to 78% |
| Questions with no such clause where the system declined (20) | 85% (17) | 64 to 95% |
| Citations that land on the annotated clause | 60% | |
| Median time per question | 37.5 s (laptop CPU/GPU) | |

**Reading it.**

- **Declining is the strong side.** On 17 of 20 questions where CUAD says the contract has no such clause, the system said so rather than inventing one. The 3 that answered need manual review: a supported claim about a related clause (for example a general termination right when asked about termination for convenience) is counted here as a failure.
- **Recall is the weak side.** 6 of 20 answerable questions ended as "insufficient evidence". Since retrieval reaches the annotated clause about 90% of the time (section 1), most of that loss happens after retrieval: the 7B model either did not propose a claim or its claim failed the quote or support check. That trade is deliberate (an abstention is safer than an unsupported answer), but it is the main thing to improve.
- **Citation precision is a lower bound.** CUAD annotates the most relevant span; a correct citation of a related clause elsewhere counts as a miss.
- **A harness artifact in this run.** CUAD's question descriptions capitalize clause names ("Non-Compete, Exclusivity"), and the app's unknown-party check read them as a company name and declined before retrieval. That affected 2 of these 40 questions (one answerable scored as a miss, one unanswerable scored as a correct abstention). The harness now lower-cases the descriptions, and the product check was fixed separately; the next run measures without it.
- **Small sample.** 40 questions gives wide intervals (shown above). A 200-question run takes about 4 hours on the same laptop (this run averaged about 75 seconds per question including model loading) and is the next measurement.

Next experiments, each measured the same way: a larger local model, splitting the support check from claim drafting across two different models so their errors are less correlated, and embedding retrieval for the vocabulary-mismatch categories in section 1.

```sh
ollama pull qwen2.5:7b
QA_MODEL=qwen2.5:7b python -m eval.cuad_eval live --cuad .local/cuad/data --limit 200
```

To reproduce or extend it, the harness reports:

- **Answered rate** on questions with an annotated answer, and the share answered with at least one citation on the annotated span.
- **Correct abstention rate** on questions CUAD marks as having no answer in the contract.
- **Citation precision** against the annotated spans (a lower bound, since a correct citation of a related clause elsewhere counts as a miss).
- Errors and median seconds per question.

The fictional-clause evaluator (`python -m scripts.evaluate_qa --live`) complements it with hand-written cases for consent, survival, renewal, conflicting dates and support-check probes that should be rejected.

## Reproducibility notes

- Random choices use a fixed seed (`20261113`).
- `tests/test_eval_harness.py` runs every model-free stage on a tiny fictional contract in CUAD's format, so the harness is tested in CI without downloading the dataset.
- Contract text never leaves the machine. Results files contain metrics and, for redaction review, short context snippets from the public filings.
