"""Redact PDF (text or scanned), Word, Excel, CSV and text files.

Scanned PDF pages are OCR'd with Tesseract, redacted on the pixels, and rebuilt as
image-only pages, so nothing hidden survives under a black box. Text PDFs use true
redaction (the text is removed, not covered). Reports never contain the removed values.
"""
import csv
import io
import os
import re
import shutil
import subprocess
import tempfile
from collections import Counter
from pathlib import Path

from . import detect

OCR_DPI = int(os.getenv('REDACT_OCR_DPI', '200'))


class Tokens:
    """'[REDACTED SSN / tax ID]' or, for people in strict mode, a stable '[PERSON 1]' per document."""
    def __init__(self):
        self.people = {}

    def __call__(self, value, cat):
        if cat == 'PERSON':
            key = re.sub(r'\W+', ' ', value).strip().lower()
            self.people.setdefault(key, len(self.people) + 1)
            return f'[PERSON {self.people[key]}]'
        return f'[REDACTED {detect.CATEGORY_NAMES[cat]}]'


def _report(engine, policy, llm, spans_by_unit, warnings, extra=None):
    counts = Counter(c for spans in spans_by_unit for _, _, c, _ in spans)
    sources = Counter(src for spans in spans_by_unit for *_, src in spans)
    return {'engine': engine, 'policy': policy, 'model': getattr(llm, 'model', None), 'redactions': sum(counts.values()),
            'by_category': dict(counts), 'by_source': dict(sources), 'warnings': sorted(set(warnings)), **(extra or {})}


# ---------- PDF ----------

def _words_to_text(words):
    """words: [(x0,y0,x1,y1,text,line_key)] -> text and per-word char offsets."""
    parts, offsets, pos, last = [], [], 0, None
    for w in words:
        sep = '' if last is None else (' ' if w[5] == last else '\n')
        pos += len(sep); parts.append(sep + w[4])
        offsets.append((pos, pos + len(w[4]))); pos += len(w[4]); last = w[5]
    return ''.join(parts), offsets


def _span_rects(words, offsets, spans, pad=2):
    rects = []
    for s, e, cat, src in spans:
        hit = [w for w, (a, b) in zip(words, offsets) if a < e and b > s]
        by_line = {}
        for w in hit:
            by_line.setdefault(w[5], []).append(w)
        for ws in by_line.values():
            rects.append((min(w[0] for w in ws) - pad, min(w[1] for w in ws) - pad,
                          max(w[2] for w in ws) + pad, max(w[3] for w in ws) + pad, cat))
    return rects


def ocr_words(png_path):
    if not shutil.which('tesseract'):
        raise RuntimeError('Tesseract is not installed; scanned PDFs cannot be read (brew install tesseract)')
    env = {**os.environ, 'OMP_THREAD_LIMIT': '1'}  # one core per page; files run in parallel
    out = subprocess.run(['tesseract', png_path, 'stdout', '--psm', '3', 'tsv'], capture_output=True, text=True, timeout=180, env=env)
    words = []
    for row in csv.DictReader(io.StringIO(out.stdout), delimiter='\t', quoting=csv.QUOTE_NONE):
        t = (row.get('text') or '').strip()
        if t and float(row.get('conf') or -1) >= 0:
            x, y, w, h = (int(row[k]) for k in ('left', 'top', 'width', 'height'))
            words.append((x, y, x + w, y + h, t, (row['block_num'], row['par_num'], row['line_num'])))
    return words


def redact_pdf(data, policy, llm=None):
    import pymupdf
    src = pymupdf.open(stream=data, filetype='pdf')
    if src.needs_pass:
        raise ValueError('Password-protected PDF')
    out = pymupdf.open()
    spans_all, warnings, scanned_pages, texts = [], [], 0, []
    for page in src:
        words = [(w[0], w[1], w[2], w[3], w[4], (w[5], w[6])) for w in page.get_text('words')]
        if sum(len(w[4]) for w in words) >= 40:
            text, offs = _words_to_text(words)
            spans, warn = detect.find(text, policy, llm)
            # Tight boxes: a padded box would also remove a letter of the neighbouring word.
            for x0, y0, x1, y1, cat in _span_rects(words, offs, spans, pad=0):
                page.add_redact_annot(pymupdf.Rect(x0 + 0.3, y0, x1 - 0.3, y1), fill=(0, 0, 0))
            page.apply_redactions(images=pymupdf.PDF_REDACT_IMAGE_PIXELS)
            out.insert_pdf(src, from_page=page.number, to_page=page.number)
        else:
            scanned_pages += 1
            zoom = OCR_DPI / 72
            pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), colorspace=pymupdf.csRGB, alpha=False)
            with tempfile.TemporaryDirectory() as tmp:
                png = os.path.join(tmp, 'p.png'); pix.save(png)
                words = ocr_words(png)
            text, offs = _words_to_text(words)
            spans, warn = detect.find(text, policy, llm)
            for x0, y0, x1, y1, cat in _span_rects(words, offs, spans, pad=6):
                pix.set_rect(pymupdf.IRect(int(x0), int(y0), int(x1), int(y1)) & pix.irect, (0, 0, 0))
            new = out.new_page(width=page.rect.width, height=page.rect.height)
            new.insert_image(new.rect, stream=pix.tobytes('jpeg', jpg_quality=85))
        spans_all.append(spans); warnings += warn; texts.append((text, spans))
    out.set_metadata({'producer': 'Clausetrail redaction', 'title': '', 'author': '', 'subject': '', 'keywords': '', 'creator': ''})
    buf = out.tobytes(garbage=4, deflate=True)
    report = _report('pdf-ocr' if scanned_pages == len(src) else 'pdf-text' if not scanned_pages else 'pdf-mixed',
                     policy, llm, spans_all, warnings, {'pages': len(src), 'scanned_pages': scanned_pages})
    return buf, report, texts


# ---------- Word ----------

def _redact_runs(runs, policy, llm, tokens, context=''):
    text = ''.join(r.text for r in runs)
    if not text.strip():
        return [], []
    prefix = f'{context}: ' if context else ''
    spans, warn = detect.find(prefix + text, policy, llm)
    spans = [(max(s, len(prefix)) - len(prefix), e - len(prefix), c, src) for s, e, c, src in spans if e > len(prefix)]
    if not spans:
        return [], warn
    bounds, pos = [], 0
    for r in runs:
        bounds.append((pos, pos + len(r.text))); pos += len(r.text)
    new_texts = [list(r.text) for r in runs]
    for s, e, cat, _ in reversed(spans):
        token = tokens(text[s:e], cat); placed = False
        for i, (a, b) in enumerate(bounds):
            lo, hi = max(s, a), min(e, b)
            if lo >= hi:
                continue
            new_texts[i][lo - a:hi - a] = list(token) if not placed else []
            placed = True
    for r, chars in zip(runs, new_texts):
        r.text = ''.join(chars)
    return spans, warn


def _docx_paragraphs(doc, with_context=False):
    """Every paragraph in body, tables (nested) and headers/footers. With context, a table cell's
    paragraphs come with the row's first cell text, since forms put the label beside the value."""
    def walk(container, context=''):
        for p in container.paragraphs:
            yield (p, context) if with_context else p
        for t in getattr(container, 'tables', []):
            for row in t.rows:
                cells = row.cells; label = cells[0].text.strip()[:60] if len(cells) > 1 else ''
                for i, cell in enumerate(cells):
                    yield from walk(cell, label if i else '')
    yield from walk(doc)
    for section in doc.sections:
        for part in (section.header, section.footer, section.first_page_header, section.first_page_footer):
            yield from walk(part)


def redact_docx(data, policy, llm=None):
    import docx
    d = docx.Document(io.BytesIO(data)); tokens = Tokens(); spans_all, warnings, texts, seen = [], [], [], set()
    for p, context in _docx_paragraphs(d, with_context=True):
        if p._p in seen:  # merged table cells repeat the same paragraph (keep elements, not id())
            continue
        seen.add(p._p); before = p.text
        spans, warn = _redact_runs(p.runs, policy, llm, tokens, context)
        spans_all.append(spans); warnings += warn
        if spans: texts.append((before, spans))
    cp = d.core_properties
    cp.author = cp.last_modified_by = cp.comments = ''
    buf = io.BytesIO(); d.save(buf)
    return buf.getvalue(), _report('docx', policy, llm, spans_all, warnings), texts


# ---------- Excel / CSV / text ----------

def _cell_text(header, value):
    prefix = f'{header}: ' if header else ''
    return prefix, prefix + str(value)


def _replace_cell(value, text, prefix, spans, tokens):
    """Blank the whole cell when the confidential value is most of it (as people do in trackers)."""
    if sum(e - s for s, e, _, _ in spans) >= 0.5 * len(value.strip()):
        return tokens(text[spans[0][0]:spans[0][1]], spans[0][2]), [(len(prefix), len(text), spans[0][2], spans[0][3])]
    for s, e, cat, _ in reversed(spans):
        value = value[:s - len(prefix)] + tokens(text[s:e], cat) + value[e - len(prefix):]
    return value, spans


def redact_xlsx(data, policy, llm=None):
    import openpyxl
    wb = openpyxl.load_workbook(io.BytesIO(data)); tokens = Tokens(); spans_all, warnings, texts = [], [], []
    for ws in wb.worksheets:
        headers = {c.column: str(c.value) for c in ws[1] if c.value is not None} if ws.max_row else {}
        for row in ws.iter_rows(min_row=1):
            for c in row:
                if c.value is None or isinstance(c.value, bool) or (isinstance(c.value, str) and c.value.startswith('=')):
                    continue
                prefix, text = _cell_text(headers.get(c.column) if c.row > 1 else '', c.value)
                spans, warn = detect.find(text, policy, llm)
                spans = [(max(s, len(prefix)), e, cat, src) for s, e, cat, src in spans if e > len(prefix)]
                warnings += warn
                if spans:
                    c.value, spans = _replace_cell(str(c.value), text, prefix, spans, tokens)
                    texts.append((text, spans)); spans_all.append(spans)
    wb.properties.creator = wb.properties.lastModifiedBy = ''
    buf = io.BytesIO(); wb.save(buf)
    return buf.getvalue(), _report('xlsx', policy, llm, spans_all, warnings), texts


def redact_text(text, policy, llm=None):
    spans, warn = detect.find(text, policy, llm); tokens = Tokens()
    for s, e, cat, _ in reversed(spans):
        text = text[:s] + tokens(text[s:e], cat) + text[e:]
    return text, spans, warn


def redact_csv(data, policy, llm=None):
    rows = list(csv.reader(io.StringIO(data.decode('utf-8-sig'))))
    headers = rows[0] if rows else []; spans_all, warnings, texts = [], [], []; tokens = Tokens()
    for r_i, row in enumerate(rows):
        for c_i, value in enumerate(row):
            prefix, text = _cell_text(headers[c_i] if r_i and c_i < len(headers) else '', value)
            spans, warn = detect.find(text, policy, llm); warnings += warn
            spans = [(max(s, len(prefix)), e, cat, src) for s, e, cat, src in spans if e > len(prefix)]
            if spans:
                row[c_i], spans = _replace_cell(value, text, prefix, spans, tokens)
                texts.append((text, spans)); spans_all.append(spans)
    buf = io.StringIO(); csv.writer(buf).writerows(rows)
    return buf.getvalue().encode(), _report('csv', policy, llm, spans_all, warnings), texts


def redact_txt(data, policy, llm=None):
    text = data.decode('utf-8', errors='replace')
    out, spans, warn = redact_text(text, policy, llm)
    return out.encode(), _report('text', policy, llm, [spans], warn), [(text, spans)]


HANDLERS = {'.pdf': redact_pdf, '.docx': redact_docx, '.xlsx': redact_xlsx, '.csv': redact_csv, '.txt': redact_txt, '.md': redact_txt}


def redact_file(data, filename, policy='standard', llm=None):
    """Return (redacted_bytes, report, texts). texts = [(original_text, spans)] stays in memory for scoring."""
    ext = Path(filename).suffix.lower()
    if ext not in HANDLERS:
        raise ValueError(f'Unsupported file type {ext}; supported: {", ".join(sorted(HANDLERS))}')
    if policy not in detect.POLICIES:
        raise ValueError('Unknown policy')
    return HANDLERS[ext](data, policy, llm)


def redact_path_segments(rel_path, texts, policy):
    """In strict mode, hide people's names in folder and file names too."""
    if policy != 'strict' or not rel_path:
        return rel_path
    names = {t[s:e].strip() for t, spans in texts for s, e, c, _ in spans if c == 'PERSON'}
    for n in sorted(names, key=len, reverse=True):
        for part in [n] + [p for p in n.split() if len(p) > 3]:
            rel_path = re.sub(re.escape(part), 'REDACTED', rel_path, flags=re.I)
    return rel_path
