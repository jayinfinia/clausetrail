"""Evaluate Clausetrail's pipeline stages on CUAD, a public set of expert-annotated contracts.

CUAD (Contract Understanding Atticus Dataset, Hendrycks et al., NeurIPS 2021, CC BY 4.0)
contains 510 real commercial contracts from SEC filings, each annotated by lawyers for 41
clause categories. This script uses the official 102-contract test split.

Get the data (about 18 MB):

    git clone --depth 1 https://github.com/TheAtticusProject/cuad.git .local/cuad
    unzip -o .local/cuad/data.zip -d .local/cuad/data

Model-free stages (deterministic, reproducible):

    python -m eval.cuad_eval retrieval  --cuad .local/cuad/data
    python -m eval.cuad_eval quotes     --cuad .local/cuad/data
    python -m eval.cuad_eval redaction  --cuad .local/cuad/data
    python -m eval.cuad_eval extraction --cuad .local/cuad/data
    python -m eval.cuad_eval all        --cuad .local/cuad/data
    python -m eval.cuad_eval retrieval  --cuad .local/cuad/data --split dev   # tuning split

Live end-to-end question answering (needs a local Ollama model, see docs/AI_QA.md):

    QA_MODEL=qwen2.5:7b python -m eval.cuad_eval live --cuad .local/cuad/data --limit 200

Results are written to eval/results/<stage>.json. Contract text never leaves the machine.
"""
import argparse
import json
import random
import re
import statistics
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / 'results'
SEED = 20261113


# ---------------------------------------------------------------- data loading

def load(data_dir, split='test'):
    """Return contracts for a split: {title, text, qas:[{category, details, answers:[(start,end,text)], impossible}]}.

    test: the official 102-contract CUAD test split; every number in docs/EVALUATION.md comes from it.
    dev:  the other 408 contracts (CUADv1.json minus test). Retrieval settings were chosen on dev only."""
    data_dir = Path(data_dir)
    test = json.loads((data_dir / 'test.json').read_text(encoding='utf-8'))['data']
    if split == 'test':
        data = test
    else:
        held_out = {item['title'] for item in test}
        data = [item for item in json.loads((data_dir / 'CUADv1.json').read_text(encoding='utf-8'))['data'] if item['title'] not in held_out]
    out = []
    for item in data:
        para = item['paragraphs'][0]
        qas = []
        for qa in para['qas']:
            category = re.search(r'related to "([^"]+)"', qa['question']).group(1)
            details = qa['question'].split('Details:', 1)[-1].strip()
            answers = sorted({(a['answer_start'], a['answer_start'] + len(a['text']), a['text']) for a in qa['answers']})
            qas.append({'id': qa['id'], 'category': category, 'details': details, 'answers': answers, 'impossible': qa['is_impossible']})
        out.append({'title': item['title'], 'text': para['context'], 'qas': qas})
    return out


def question_for(qa):
    """A plain-language question built from CUAD's category name and its 'Details' description."""
    return f"What does the contract say about {qa['category'].lower()}? {qa['details']}"


def blocks_like_txt_parser(text):
    """Split like backend.services.parsers for .txt files (one block per non-empty line, stripped),
    but also keep each block's offset in the original text so gold spans can be matched."""
    blocks = []
    for m in re.finditer(r'[^\r\n]+', text):
        raw = m.group()
        stripped = raw.strip()
        if not stripped:
            continue
        offset = m.start() + (len(raw) - len(raw.lstrip()))
        blocks.append({'id': str(len(blocks) + 1), 'locator': f'Line {len(blocks) + 1}', 'text': stripped, 'offset': offset})
    return blocks


def record_for(contract, rid='c1'):
    blocks = blocks_like_txt_parser(contract['text'])
    return SimpleNamespace(id=rid, filename=contract['title'][:120] + '.txt', blocks=blocks, source_version='v1',
                           digest='cuad-' + rid, revision=1, executed=False, parent_id=None, approved={}, proposals={})


def overlaps(a0, a1, b0, b1):
    return a0 < b1 and b0 < a1


def pct(x):
    return round(100 * x, 1)


def save(stage, payload):
    RESULTS.mkdir(parents=True, exist_ok=True)
    path = RESULTS / f'{stage}.json'
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    print(f'wrote {path.relative_to(ROOT.parent)}')


# ---------------------------------------------------------------- 1. retrieval

def passages_to_spans(selected, record):
    offsets = {b['id']: b['offset'] for b in record.blocks}
    return [(offsets[p['block_id']] + p['start'], offsets[p['block_id']] + p['end']) for p in selected]


def all_chunks(record):
    """Every passage window the retriever could choose from, in document order."""
    out = []
    for b in record.blocks:
        for start in range(0, len(b['text']), 1400):
            piece = b['text'][start:start + 1800]
            if piece.strip():
                out.append({'block_id': b['id'], 'start': start, 'end': start + len(piece), 'text': piece})
    return out


def fill_budget(chunks, budget, limit):
    picked, used = [], 0
    for c in chunks:
        if len(picked) >= limit or used + len(c['text']) > budget:
            continue
        picked.append(c); used += len(c['text'])
    return picked


RETRIEVAL_CONFIGS = {  # name -> keyword arguments for backend.services.retrieval.retrieve
    'clausetrail': {},
    'clausetrail_v1': {'per_doc_limit': 3, 'lead_chars': 0},
    'no_opening': {'lead_chars': 0},
    'opening_3000_chars': {'lead_chars': 3000},
}


def eval_retrieval(contracts, split='test'):
    from backend.services.retrieval import retrieve
    rng = random.Random(SEED)
    systems = (*RETRIEVAL_CONFIGS, 'first_passages', 'random_passages')
    q_hit = {s: [] for s in systems}; q_all = {s: [] for s in systems}; span_hit = {s: [0, 0] for s in systems}
    by_cat = defaultdict(lambda: {s: [] for s in systems})
    sent = {name: [] for name in RETRIEVAL_CONFIGS}; full_context = 0
    for ci, contract in enumerate(contracts):
        record = record_for(contract)
        chunks = all_chunks(record)
        for qa in contract['qas']:
            if qa['impossible'] or not qa['answers']:
                continue
            picks = {}
            for name, kwargs in RETRIEVAL_CONFIGS.items():
                selected, coverage = retrieve(question_for(qa), [record], **kwargs)
                sent[name].append((sum(len(p['text']) for p in selected), len(selected)))
                picks[name] = passages_to_spans(selected, record)
                if name == 'clausetrail':
                    full_context += not coverage.get('truncated', False)
            budget = max(sent['clausetrail'][-1][0], 1)  # baselines get the same characters Clausetrail used
            shuffled = chunks[:]; rng.shuffle(shuffled)
            picks['first_passages'] = passages_to_spans(fill_budget(chunks, budget, 40), record)
            picks['random_passages'] = passages_to_spans(fill_budget(shuffled, budget, 40), record)
            for s, spans in picks.items():
                found = [any(overlaps(a0, a1, b0, b1) for b0, b1 in spans) for a0, a1, _ in qa['answers']]
                q_hit[s].append(any(found)); q_all[s].append(all(found))
                span_hit[s][0] += sum(found); span_hit[s][1] += len(found)
                by_cat[qa['category']][s].append(any(found))
        print(f'\rretrieval: {ci + 1}/{len(contracts)} contracts', end='', file=sys.stderr)
    print(file=sys.stderr)
    n = len(q_hit['clausetrail'])
    summary = {s: {'question_hit_rate': pct(sum(q_hit[s]) / len(q_hit[s])),
                   'question_all_spans_rate': pct(sum(q_all[s]) / len(q_all[s])),
                   'span_recall': pct(span_hit[s][0] / span_hit[s][1]),
                   **({'median_chars_sent': statistics.median(c for c, _ in sent[s]),
                       'median_passages_sent': statistics.median(p for _, p in sent[s])} if s in sent else {})} for s in systems}
    categories = sorted(({'category': c, 'questions': len(v['clausetrail']),
                          **{s: pct(sum(v[s]) / len(v[s])) for s in ('clausetrail', 'clausetrail_v1', 'first_passages', 'random_passages')}}
                         for c, v in by_cat.items()),
                        key=lambda r: r['clausetrail'])
    return {
        'stage': 'retrieval' if split == 'test' else 'retrieval_dev', 'dataset': f'CUAD v1 {split} split', 'contracts': len(contracts),
        'answerable_questions': n, 'configs': RETRIEVAL_CONFIGS,
        'definition': ('A question is a hit when at least one passage sent to the model overlaps a lawyer-annotated '
                       'answer span. "all spans" requires every annotated span to be covered. Baselines get the same '
                       'character budget Clausetrail used for that question.'),
        'question_wording': 'What does the contract say about <category>? <CUAD details text>',
        'whole_document_sent_rate': pct(full_context / n),
        'summary': summary, 'by_category': categories,
    }


# ---------------------------------------------------------------- 2. quote guard

def _alter_number(q):
    m = re.search(r'\d', q)
    return q[:m.start()] + str((int(m.group()) + 1) % 10) + q[m.end():] if m else None


def _negate(q):
    m = re.search(r'\b(shall|will|may|must)\b(?! not)', q)
    return q[:m.end()] + ' not' + q[m.end():] if m else None


def _drop_word(q):
    words = q.split(' ')
    if len(words) < 6:
        return None
    i = len(words) // 2
    return ' '.join(words[:i] + words[i + 1:])


def _reflow(q):
    return re.sub(r'\s+', '\n  ', q, count=3)


def eval_quotes(contracts):
    from backend.services.grounded_qa import exact_quote
    rng = random.Random(SEED)
    pool_by_cat = defaultdict(list)
    for ci, c in enumerate(contracts):
        for qa in c['qas']:
            for _, _, t in qa['answers']:
                if len(t.strip()) >= 12:
                    pool_by_cat[qa['category']].append((ci, t))
    variants = {
        'verbatim': (lambda q, ci, cat: q, True),
        'whitespace_reflowed': (lambda q, ci, cat: _reflow(q), True),
        'number_changed': (lambda q, ci, cat: _alter_number(q), False),
        'negation_inserted': (lambda q, ci, cat: _negate(q), False),
        'word_dropped': (lambda q, ci, cat: _drop_word(q), False),
        'from_other_contract': (None, False),
    }
    counts = {k: [0, 0] for k in variants}  # accepted, total
    same_text_elsewhere = 0
    for ci, c in enumerate(contracts):
        text = c['text']
        for qa in c['qas']:
            for _, _, quote in qa['answers']:
                if len(quote.strip()) < 12:
                    continue
                for name, (fn, _) in variants.items():
                    if name == 'from_other_contract':
                        others = [t for j, t in pool_by_cat[qa['category']] if j != ci]
                        if not others:
                            continue
                        candidate = rng.choice(others)
                        if re.sub(r'\s+', ' ', candidate.strip()) in re.sub(r'\s+', ' ', text):
                            same_text_elsewhere += 1  # boilerplate that really is in this contract; skip
                            continue
                    else:
                        candidate = fn(quote, ci, qa['category'])
                        if not candidate or candidate == quote and name != 'verbatim':
                            continue
                        if name != 'verbatim' and name != 'whitespace_reflowed' and re.sub(r'\s+', ' ', candidate) in re.sub(r'\s+', ' ', text):
                            continue  # the altered wording genuinely appears elsewhere in the contract
                    counts[name][1] += 1
                    counts[name][0] += bool(exact_quote(candidate, text))
    rows = {k: {'should_accept': variants[k][1], 'cases': n, 'accepted': a, 'accept_rate': pct(a / n) if n else None,
                'correct_rate': pct((a if variants[k][1] else n - a) / n) if n else None} for k, (a, n) in counts.items()}
    return {'stage': 'quote_guard', 'dataset': 'CUAD v1 test split', 'contracts': len(contracts),
            'definition': ('Each lawyer-annotated answer span (12+ characters) is offered to the exact-quote check as if a '
                           'model had cited it, then altered in ways a model might hallucinate. Verbatim and re-wrapped '
                           'quotes should pass; altered or borrowed quotes should be rejected.'),
            'variants': rows, 'skipped_true_boilerplate_matches': same_text_elsewhere,
            'limit': ('This checks that a quote exists in the source. It cannot tell whether a claim interprets a real '
                      'quote correctly; that is the job of the separate support-check model call, measured by the live stage.')}


# ---------------------------------------------------------------- 3. redaction

def _luhn_complete(prefix):
    digits = [int(d) for d in prefix]
    for check in range(10):
        total = 0
        for i, d in enumerate(reversed(digits + [check])):
            if i % 2:
                d *= 2
                d -= 9 if d > 9 else 0
            total += d
        if total % 10 == 0:
            return prefix + str(check)


def synthetic_values(rng):
    """Fictional sensitive values in common real-world layouts. (label, value, category, label_kind)."""
    ssn = f'{rng.randint(100, 665)}-{rng.randint(10, 99)}-{rng.randint(1000, 9999)}'
    ein = f'{rng.randint(10, 99)}-{rng.randint(1000000, 9999999)}'
    card = _luhn_complete('4' + ''.join(str(rng.randint(0, 9)) for _ in range(14)))
    acct = ''.join(str(rng.randint(0, 9)) for _ in range(rng.randint(9, 14)))
    dob = f'{rng.randint(1, 12):02d}/{rng.randint(1, 28):02d}/{rng.randint(1950, 2001)}'
    months = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December']
    dob_long = f'{rng.choice(months)} {rng.randint(1, 28)}, {rng.randint(1950, 2001)}'
    return [
        ('Social Security Number: ', ssn, 'GOV_ID', 'labeled'),
        ('SSN ', ssn.replace('-', ''), 'GOV_ID', 'labeled, no dashes'),
        ('Taxpayer Identification Number: ', ein, 'GOV_ID', 'labeled'),
        ('Federal Employer Identification No. ', ein, 'GOV_ID', 'labeled'),
        ('Tax ID\n', ssn, 'GOV_ID', 'label on previous line'),
        ('', ssn, 'GOV_ID', 'unlabeled SSN shape'),
        ('Card number ', ' '.join(card[i:i + 4] for i in range(0, 16, 4)), 'FIN_ACCOUNT', 'labeled, spaced'),
        ('', card, 'FIN_ACCOUNT', 'unlabeled card (Luhn-valid)'),
        ('Account Number: ', acct, 'FIN_ACCOUNT', 'labeled'),
        ('ABA routing / account no. ', acct, 'FIN_ACCOUNT', 'labeled'),
        ('Date of Birth: ', dob, 'DOB', 'labeled'),
        ('DOB ', dob_long, 'DOB', 'labeled, long form'),
        ('born on ', dob_long, 'DOB', 'phrase'),
    ]


def eval_redaction(contracts, sample_size=40):
    from backend.redaction import detect
    rng = random.Random(SEED)
    # (a) Flags on clean, unmodified contracts: these are public SEC filings, so most flags are company
    # numbers (EINs, file numbers, account numbers in payment clauses). Each flag is listed for review.
    flags, chars = [], 0
    for c in contracts:
        text = c['text']; chars += len(text)
        spans, _ = detect.find(text, 'standard')
        for s, e, cat, src in spans:
            flags.append({'contract': c['title'][:60], 'category': cat, 'value_chars': e - s,
                          # The flagged value is masked so results never republish account numbers, even from public filings.
                          'context': re.sub(r'\s+', ' ', re.sub(r'\d', '#', text[max(0, s - 70):s]) + '[[' + re.sub(r'[0-9A-Za-z]', '#', text[s:e]) + ']]'
                                            + re.sub(r'\d', '#', text[e:e + 30]))})
    sample = rng.sample(flags, min(sample_size, len(flags)))
    # (b) Recall on injected fictional values in real contract text.
    per_kind = defaultdict(lambda: [0, 0]); collateral = []
    for c in contracts:
        text = c['text']
        for label, value, cat, kind in synthetic_values(rng):
            # insert after a random sentence end so the value sits inside real legal prose
            cuts = [m.end() for m in re.finditer(r'\.\s', text)] or [len(text)]
            at = rng.choice(cuts)
            injected = text[:at] + label + value + '. ' + text[at:]
            v0 = at + len(label); v1 = v0 + len(value)
            spans, _ = detect.find(injected, 'standard')
            covered = any(s <= v0 and e >= v1 for s, e, *_ in spans)
            per_kind[(cat, kind)][0] += covered; per_kind[(cat, kind)][1] += 1
            extra = [(s, e) for s, e, *_ in spans if overlaps(s, e, v0, v1) and (e - s) > (v1 - v0) + 40]
            if extra:
                collateral.append(kind)
    rows = [{'category': cat, 'layout': kind, 'cases': n, 'detected': d, 'recall': pct(d / n)} for (cat, kind), (d, n) in sorted(per_kind.items())]
    total_d = sum(r['detected'] for r in rows); total_n = sum(r['cases'] for r in rows)
    return {'stage': 'redaction', 'dataset': 'CUAD v1 test split', 'contracts': len(contracts), 'policy': 'standard', 'detector': 'rules only (no local model)',
            'injected': {'definition': ('Fictional SSNs, tax IDs, card and account numbers and dates of birth are inserted into each '
                                        'real contract at a random sentence boundary in 13 layouts. Detected means one redaction span covers the whole value.'),
                         'overall_recall': pct(total_d / total_n), 'cases': total_n, 'by_layout': rows,
                         'oversized_spans': len(collateral)},
            'clean_contracts': {'definition': ('Flags raised on the unmodified contracts. These are public filings, so a flag is not '
                                               'necessarily wrong: company tax IDs and payment account numbers are in scope for the policy. '
                                               'A random sample is listed for manual review.'),
                                'characters': chars, 'flags': len(flags), 'flags_per_100k_chars': round(100000 * len(flags) / chars, 2),
                                'by_category': dict(Counter(f['category'] for f in flags)), 'review_sample': sample}}


# ---------------------------------------------------------------- 4. deterministic extraction

def eval_extraction(contracts):
    from backend.services.extraction import extract
    proposed, correct, by_field = 0, 0, Counter()
    examples = []
    gold_cat = {'effective_date': 'Effective Date', 'expiration_date': 'Expiration Date', 'counterparty': 'Parties',
                'renewal': 'Renewal Term', 'notice_days': 'Notice Period To Terminate Renewal'}
    for c in contracts:
        record = record_for(c)
        result = extract(record.blocks)
        gold = {qa['category']: qa for qa in c['qas']}
        offsets = {b['id']: b['offset'] for b in record.blocks}
        lengths = {b['id']: len(b['text']) for b in record.blocks}
        for field, p in result.items():
            if p.get('state') == 'unknown' or p.get('method') == 'abstain':
                continue
            proposed += 1; by_field[field] += 1
            g = gold.get(gold_cat.get(field, ''), {'answers': []})
            ev = p.get('evidence')
            hit = ev in offsets and any(overlaps(offsets[ev], offsets[ev] + lengths[ev], a0, a1) for a0, a1, _ in g['answers'])
            correct += hit
            if len(examples) < 15:
                examples.append({'contract': c['title'][:60], 'field': field, 'raw': p.get('raw'), 'state': p.get('state'), 'evidence_matches_gold': hit})
    total = len(contracts) * 11
    return {'stage': 'extraction', 'dataset': 'CUAD v1 test split', 'contracts': len(contracts),
            'definition': ('The default extractor only reads explicit "Label: value" lines and abstains otherwise. This counts how '
                           'often it proposes anything on real contracts and whether its evidence line overlaps the matching CUAD annotation.'),
            'field_slots': total, 'proposals': proposed, 'abstention_rate': pct(1 - proposed / total),
            'proposals_by_field': dict(by_field), 'evidence_overlaps_gold': correct, 'examples': examples,
            'takeaway': ('On real contracts the deterministic extractor almost always abstains. That is the intended failure '
                         'mode (no invented values), and it is why model-assisted tagging with quote grounding exists.')}


# ---------------------------------------------------------------- 5. live end to end

def eval_live(contracts, limit):
    from backend.services import qa_provider
    from backend.services.grounded_qa import ask
    status = qa_provider.readiness()
    if not status.get('ready'):
        sys.exit(f"Live evaluation needs a local model: {status.get('reason')}")
    rng = random.Random(SEED)
    pool = [(c, qa) for c in contracts for qa in c['qas']]
    answerable = [x for x in pool if not x[1]['impossible']]; unanswerable = [x for x in pool if x[1]['impossible']]
    half = limit // 2
    sample = rng.sample(answerable, min(half, len(answerable))) + rng.sample(unanswerable, min(limit - half, len(unanswerable)))
    rows = []
    for i, (c, qa) in enumerate(sample):
        record = record_for(c)
        offsets = {b['id']: b['offset'] for b in record.blocks}
        t0 = time.time()
        try:
            result = ask(question_for(qa), [record], mode='ai'); error = None
        except Exception as exc:  # report and continue; a failed call counts as no answer
            result, error = {'status': 'error', 'citations': [], 'claims': []}, type(exc).__name__
        cites = [x for x in result.get('citations', []) if x.get('kind') == 'document']
        grounded = [any(overlaps(offsets[x['block_id']] + x['start'], offsets[x['block_id']] + x['end'], a0, a1) for a0, a1, _ in qa['answers']) for x in cites]
        rows.append({'id': qa['id'], 'category': qa['category'], 'answerable': not qa['impossible'], 'status': result.get('status'),
                     'claims': len(result.get('claims', [])), 'citations': len(cites), 'citations_on_gold': sum(grounded),
                     'seconds': round(time.time() - t0, 1), 'error': error})
        print(f'\rlive: {i + 1}/{len(sample)}', end='', file=sys.stderr)
    print(file=sys.stderr)
    ans = [r for r in rows if r['answerable']]; un = [r for r in rows if not r['answerable']]
    answered = lambda r: r['status'] in ('answered', 'partial', 'conflicting_evidence')
    cited = sum(r['citations'] for r in rows if answered(r))
    return {'stage': 'live', 'model': status.get('model'), 'questions': len(rows),
            'answerable': {'n': len(ans), 'answered_rate': pct(sum(map(answered, ans)) / len(ans)) if ans else None,
                           'answered_with_a_gold_citation_rate': pct(sum(answered(r) and r['citations_on_gold'] > 0 for r in ans) / len(ans)) if ans else None},
            'unanswerable': {'n': len(un), 'correct_abstention_rate': pct(sum(not answered(r) for r in un) / len(un)) if un else None},
            'citation_precision_vs_gold': pct(sum(r['citations_on_gold'] for r in ans if answered(r)) / max(1, sum(r['citations'] for r in ans if answered(r)))),
            'citations_total': cited, 'errors': sum(bool(r['error']) for r in rows),
            'median_seconds': statistics.median(r['seconds'] for r in rows) if rows else None, 'rows': rows,
            'note': ('Citation precision against CUAD is a lower bound: lawyers annotated the most relevant span, so a correct '
                     'citation of a related clause elsewhere counts as a miss.')}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('stage', choices=['retrieval', 'quotes', 'redaction', 'extraction', 'live', 'all'])
    ap.add_argument('--cuad', required=True, help='CUAD data folder containing test.json and CUADv1.json')
    ap.add_argument('--split', choices=['test', 'dev'], default='test', help='dev is only for tuning retrieval settings')
    ap.add_argument('--limit', type=int, default=200, help='Questions for the live stage')
    args = ap.parse_args(argv)
    contracts = load(args.cuad, args.split)
    if args.split == 'dev':
        if args.stage != 'retrieval':
            sys.exit('The dev split is only used to tune retrieval.')
        save('retrieval_dev', eval_retrieval(contracts, 'dev')); return
    stages = {'retrieval': eval_retrieval, 'quotes': eval_quotes, 'redaction': eval_redaction, 'extraction': eval_extraction}
    run = list(stages) if args.stage == 'all' else [args.stage]
    for name in run:
        if name == 'live':
            save('live', eval_live(contracts, args.limit)); continue
        t0 = time.time(); result = stages[name](contracts); result['seconds'] = round(time.time() - t0, 1)
        save(result['stage'], result)


if __name__ == '__main__':
    main()
