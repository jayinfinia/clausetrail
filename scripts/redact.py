"""Redact a folder of agreements locally, score it against existing redactions, optionally import.

  python scripts/redact.py IN_DIR OUT_DIR [--policy standard|strict] [--llm auto|off|MODEL]
                           [--reference REF_DIR] [--import-to http://localhost:8000 --user alex]

- Writes OUT_DIR/<same folder layout>/<file> redacted, plus redaction_report.json and
  redaction_report.html (a scorecard; it contains counts and scores, never removed values).
- Files whose name contains "Redacted" are treated as existing reference redactions: they are
  matched to an original with the same name (scored), or leak-checked when no original exists.
- The Llama step uses a local Ollama model only. --llm off runs rules + OCR alone.
"""
import argparse
import threading
import os
from concurrent.futures import ThreadPoolExecutor
import html
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.redaction import detect, engines, evaluate, llm as llm_mod  # noqa: E402


def load_llm(choice):
    if choice == 'off':
        return None, 'off'
    try:
        fn = llm_mod.detector(None if choice == 'auto' else choice)
        return fn, fn.model
    except llm_mod.Unavailable as exc:
        if choice != 'auto':
            sys.exit(f'Local model unavailable: {exc}')
        print(f'! Local Llama step off: {exc}. Continuing with rules + OCR.')
        return None, f'off ({exc})'


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('input'); ap.add_argument('output')
    ap.add_argument('--policy', default='standard', choices=sorted(detect.POLICIES))
    ap.add_argument('--llm', default='auto', help='auto (default), off, or an installed Ollama model name')
    ap.add_argument('--reference', help='folder of existing redacted copies (default: files named *Redacted* inside input)')
    ap.add_argument('--import-to', help='Clausetrail URL to import the redacted copies into')
    ap.add_argument('--user', default='alex'); ap.add_argument('--scope', default='research')
    ap.add_argument('--limit', type=int, default=0)
    ap.add_argument('--workers', type=int, default=max(1, (os.cpu_count() or 2)), help='files processed in parallel')
    ap.add_argument('--no-verify', action='store_true', help='skip re-reading each output to confirm nothing is still visible')
    a = ap.parse_args()
    src, out = Path(a.input).resolve(), Path(a.output).resolve()
    if out == src:
        sys.exit('Output folder must differ from the input folder')
    out.mkdir(parents=True, exist_ok=True)
    detector, model = load_llm(a.llm)

    files = [p for p in sorted(src.rglob('*')) if p.is_file() and p.suffix.lower() in engines.HANDLERS and out not in p.parents]
    refs = {}
    ref_root = Path(a.reference).resolve() if a.reference else None
    if ref_root:
        refs = {evaluate.base_name(p.name): p for p in ref_root.rglob('*') if p.is_file()}
    else:
        refs = {evaluate.base_name(p.name): p for p in files if evaluate.is_reference(p.name)}
    originals = [p for p in files if not evaluate.is_reference(p.name)] if not ref_root else files
    if a.limit:
        originals = originals[:a.limit]

    rows, started = [], time.time()
    # Resumable: each finished file is appended to a progress log; a rerun skips those files.
    progress = out / '.redaction_progress.jsonl'; done_rows = {}
    if progress.exists():
        for line in progress.read_text().splitlines():
            try:
                r = json.loads(line)
                if r.get('output') and (out / r['output']).exists(): done_rows[r['file']] = r
            except ValueError:
                pass
    lock = threading.Lock()

    def one(path):
        rel = path.relative_to(src).as_posix(); t0 = time.time()
        if rel in done_rows:
            return {**done_rows[rel], 'resumed': True}
        row = {'file': rel}
        try:
            data = path.read_bytes()
            red, report, texts = engines.redact_file(data, path.name, a.policy, detector)
            out_rel = engines.redact_path_segments(rel, texts, a.policy)
            target = out / out_rel; target.parent.mkdir(parents=True, exist_ok=True); target.write_bytes(red)
            row.update(report, output=out_rel)
            if not a.no_verify:
                # Re-read the redacted output with rules + OCR: anything still found is a miss.
                row['residual'] = evaluate.leak_check(red, path.name, a.policy)['still_visible']
            ref = refs.get(evaluate.base_name(path.name))
            if ref is not None and ref != path:
                rdata = ref.read_bytes()
                if path.suffix.lower() == '.pdf' and report['engine'] == 'pdf-ocr':
                    row['score'] = evaluate.image_pair(data, rdata, red)
                else:
                    row['score'] = evaluate.text_pair(data, rdata, texts, path.name)
                row['reference'] = ref.relative_to(ref_root or src).as_posix()
        except Exception as exc:
            row['error'] = str(exc)
        row['seconds'] = round(time.time() - t0, 1)
        with lock, progress.open('a') as fh:
            fh.write(json.dumps(row) + '\n')
        return row

    # Tesseract runs as its own process, so threads give real parallelism here.
    with ThreadPoolExecutor(max_workers=a.workers) as pool:
        for i, row in enumerate(pool.map(one, originals), 1):
            rows.append(row)
            print(f"[{i}/{len(originals)}] {row.get('redactions', '-'):>3} redactions, {row.get('residual', '-')} left  {row.get('engine', 'error'):9} {row['seconds']:>5}s  {row['file']}" + (f"  ERROR {row['error']}" if 'error' in row else ''), flush=True)

    matched = {r.get('reference') for r in rows}
    for key, ref in refs.items():
        rel = ref.relative_to(ref_root or src).as_posix()
        if rel in matched:
            continue
        try:
            rows.append({'file': rel, 'reference_only': True, 'score': evaluate.leak_check(ref.read_bytes(), ref.name, a.policy, detector)})
        except Exception as exc:
            rows.append({'file': rel, 'reference_only': True, 'error': str(exc)})
        print(f"[ref] leak check {rel}: {rows[-1].get('score', {}).get('still_visible', 'error')} still visible", flush=True)

    summary = summarize(rows, a.policy, model, time.time() - started)
    (out / 'redaction_report.json').write_text(json.dumps({'summary': summary, 'files': rows}, indent=2))
    (out / 'redaction_report.html').write_text(render(summary, rows))
    print(json.dumps(summary, indent=2))

    if a.import_to:
        import_to(a.import_to, a.user, a.scope, out, [r for r in rows if r.get('output')], a.policy)


def summarize(rows, policy, model, seconds):
    done = [r for r in rows if r.get('output')]
    pairs = [r['score'] for r in rows if r.get('score', {}).get('mode', '').endswith('pair')]
    leaks = [r['score'] for r in rows if r.get('score', {}).get('mode') == 'reference leak check']
    cats = {}
    for r in done:
        for k, v in r.get('by_category', {}).items():
            cats[k] = cats.get(k, 0) + v
    def avg(key, items):
        vals = [s[key] for s in items if key in s]
        return round(sum(vals) / len(vals), 3) if vals else None
    text_pairs = [s for s in pairs if s['mode'] == 'text pair']; img_pairs = [s for s in pairs if s['mode'] == 'scanned pair']
    return {'policy': policy, 'model': model, 'files_redacted': len(done), 'errors': sum('error' in r for r in rows),
            'redactions': sum(r.get('redactions', 0) for r in done), 'by_category': cats,
            'scanned_pages': sum(r.get('scanned_pages', 0) for r in done), 'seconds': round(seconds, 1),
            'text_pairs': len(text_pairs), 'text_recall': avg('recall', text_pairs), 'text_precision': avg('precision', text_pairs), 'text_f1': avg('f1', text_pairs),
            'scanned_pairs': len(img_pairs), 'pixel_recall': avg('pixel_recall', img_pairs), 'pixel_precision': avg('pixel_precision', img_pairs), 'iou': avg('iou', img_pairs),
            'reference_boxes': sum(s.get('reference_boxes', 0) for s in img_pairs), 'reference_boxes_covered': sum(s.get('reference_boxes_covered', 0) for s in img_pairs),
            'residual_after_redaction': sum(r.get('residual', 0) for r in done),
            'references_leak_checked': len(leaks), 'references_with_visible_items': sum(1 for s in leaks if s['still_visible'])}


def render(s, rows):
    e = html.escape
    def pct(v): return '—' if v is None else f'{v * 100:.0f}%'
    cards = [('Files redacted', s['files_redacted']), ('Redactions', s['redactions']), ('Scanned pages OCR’d', s['scanned_pages']),
             ('Reference boxes covered', f"{s['reference_boxes_covered']} / {s['reference_boxes']}" if s['reference_boxes'] else '—'),
             ('Still visible after redaction', s['residual_after_redaction']),
             ('Text recall vs reference', pct(s['text_recall'])), ('Text precision vs reference', pct(s['text_precision']))]
    body = ''.join(f"<tr><td>{e(r['file'])}{' <small>(reference)</small>' if r.get('reference_only') else ''}</td><td>{e(r.get('engine', ''))}</td>"
                   f"<td>{r.get('redactions', '')}</td><td>{e(', '.join(f'{detect.CATEGORY_NAMES.get(k, k)} {v}' for k, v in r.get('by_category', {}).items()))}</td>"
                   f"<td>{r.get('residual', '')}</td><td>{e(score_text(r))}</td><td>{e(r.get('error', '') or '; '.join(r.get('warnings', [])))}</td></tr>" for r in rows)
    return f"""<!doctype html><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1"><title>Redaction scorecard</title>
<style>body{{font:14px system-ui,sans-serif;margin:24px;color:#1b2a30;background:#f6f8f8}}h1{{margin:0 0 4px}}.cards{{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin:16px 0}}
.card{{background:#fff;border:1px solid #d9e2e4;border-radius:8px;padding:12px}}.card b{{display:block;font-size:24px;color:#1d5c6b}}table{{border-collapse:collapse;width:100%;background:#fff}}td,th{{border-bottom:1px solid #e3e9ea;padding:6px 8px;text-align:left;vertical-align:top;font-size:13px}}small{{color:#6b7c80}}</style>
<h1>Redaction scorecard</h1><p>Policy <b>{e(s['policy'])}</b> · local model <b>{e(str(s['model']))}</b> · {s['seconds']} s · {s['errors']} errors. Counts and scores only; no redacted values are stored in this report.</p>
<div class=cards>{''.join(f'<div class=card><b>{e(str(v))}</b>{e(k)}</div>' for k, v in cards)}</div>
<p>Scanned pairs: pixel recall {pct(s['pixel_recall'])}, precision {pct(s['pixel_precision'])}, IoU {pct(s['iou'])}. References leak-checked: {s['references_leak_checked']} ({s['references_with_visible_items']} with items still visible under this policy).</p>
<table><tr><th>File</th><th>Engine</th><th>Redactions</th><th>By category</th><th>Still visible</th><th>Comparison</th><th>Notes</th></tr>{body}</table>"""


def score_text(r):
    s = r.get('score')
    if not s: return ''
    if s['mode'] == 'text pair': return f"vs reference: recall {s['recall']:.0%}, precision {s['precision']:.0%}"
    if s['mode'] == 'scanned pair': return f"vs reference: {s['reference_boxes_covered']}/{s['reference_boxes']} boxes covered, IoU {s['iou']:.0%}"
    return f"leak check: {s['still_visible']} still visible" + (f" ({', '.join(f'{k} {v}' for k, v in s['still_visible_by_category'].items())})" if s['still_visible'] else '')


def import_to(url, user, scope, out, rows, policy='standard'):
    import httpx
    with httpx.Client(base_url=url, timeout=120, trust_env=False) as c:
        r = c.post('/api/auth/demo', json={'username': user}, headers={'Origin': url}); r.raise_for_status()
        h = {'X-CSRF-Token': r.json()['csrf'], 'Origin': url}
        for i in range(0, len(rows), 50):
            batch = rows[i:i + 50]
            files = [('files', (Path(x['output']).name, (out / x['output']).read_bytes())) for x in batch]
            # The app runs the same policy again as a second pass and records the redaction report.
            data = {'scope': scope, 'paths': [x['output'] for x in batch], 'redact': policy}
            res = c.post('/api/imports', files=files, data=data, headers=h); res.raise_for_status()
            print(f"Imported {sum(1 for x in res.json()['results'] if 'id' in x and not x.get('duplicate'))} redacted files into {url}")


if __name__ == '__main__':
    main()
