"""Bounded local parsing. Invoked in a subprocess by the worker.

Every format becomes a list of blocks, the unit of citation: ``{'id', 'locator', 'text'}``. Blocks are sized for
precise citations: one per paragraph or clause in PDFs (text and OCR) and Word files, one per table row, one per
text line. ``parse_document`` also returns content-free warnings (for example low OCR confidence or tracked changes)
that the worker stores on the record. Errors are raised as ``ParseError`` with a short, content-free code that is
shown to the reviewer.
"""
import csv
import io
import json
import re
import shutil
import statistics
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

MAX_TEXT = 1_000_000
MAX_BLOCK = 2000          # longer paragraphs or lines are split at sentence boundaries into parts
MAX_PAGES = 200
OCR_DPI = 300             # Tesseract is trained on ~300 DPI text; lower resolutions lose small print
OCR_MAX_PIXELS = 4200     # cap on the long side of a rendered page (oversized pages are rendered at lower DPI)
OCR_LOW_CONFIDENCE = 80   # mean word confidence (0 to 100) under which a page gets a warning

UNSUPPORTED = {
    '.doc': 'Legacy Word (.doc) files are not supported. Open the file and save it as .docx or PDF, then import that copy.',
    '.rtf': 'Rich Text (.rtf) files are not supported. Save the file as .docx or PDF, then import that copy.',
    '.pages': 'Apple Pages files are not supported. Export the file to Word (.docx) or PDF, then import that copy.',
    '.odt': 'OpenDocument (.odt) files are not supported. Save the file as .docx or PDF, then import that copy.',
    '.xls': 'Legacy Excel (.xls) files are not supported. Save the workbook as .xlsx, then import that copy.',
    '.numbers': 'Apple Numbers files are not supported. Export the sheet to Excel (.xlsx) or CSV, then import that copy.',
    '.docm': 'Macro-enabled Word files are not supported. Save the file as .docx or PDF, then import that copy.',
    '.xlsm': 'Macro-enabled Excel files are not supported. Save the workbook as .xlsx, then import that copy.',
}
SUPPORTED = ('.pdf', '.docx', '.xlsx', '.csv', '.txt')

class ParseError(ValueError):
    """A content-free reason a file could not be read; the code is shown to the reviewer."""

def unsupported_message(suffix):
    return UNSUPPORTED.get(suffix, f'Unsupported file type{" " + suffix if suffix else ""}. Import PDF, DOCX, XLSX, CSV or TXT.')

def zip_guard(path):
    with zipfile.ZipFile(path) as archive:
        infos = archive.infolist()
        if len(infos) > 10000 or sum(i.file_size for i in infos) > 100_000_000:
            raise ParseError('archive_limits')
        if any('vbaProject' in i.filename for i in infos):
            raise ParseError('macros_rejected')

class Blocks:
    """Collects blocks with sequential ids and enforces the total text limit."""
    def __init__(self):
        self.items, self.total = [], 0
    def add(self, locator, text):
        text = (text or '').strip()
        if not text:
            return
        parts = split_long(text)
        for i, part in enumerate(parts, 1):
            self.items.append({'id': str(len(self.items) + 1), 'locator': locator if len(parts) == 1 else f'{locator}, part {i}', 'text': part})
            self.total += len(part)
        if self.total > MAX_TEXT:
            raise ParseError('text_limit')

_SENTENCE_END = re.compile(r'(?<=[.;:!?])\s+(?=\S)')

def split_long(text, limit=MAX_BLOCK):
    """Split an oversized paragraph or line at sentence (or else word) boundaries; short text is returned unchanged."""
    if len(text) <= limit:
        return [text]
    parts, rest = [], text
    while len(rest) > limit:
        window = rest[:limit]
        cut = max((m.end() for m in _SENTENCE_END.finditer(window) if m.end() >= limit // 2), default=0)
        if not cut:
            space = window.rfind(' ')
            cut = space + 1 if space >= limit // 2 else limit
        parts.append(rest[:cut].strip()); rest = rest[cut:].lstrip()
    if rest.strip():
        parts.append(rest.strip())
    return [p for p in parts if p]

# ---------------------------------------------------------------- paragraph segmentation from positioned lines

CLAUSE_START = re.compile(
    r'^(?:(?i:section|article|clause|schedule|exhibit|annex|appendix)\s+[0-9IVXLC]+[.:)]?(?:\d+[.)]?)*(?:\s|$)'
    r'|\d{1,3}(?:\.\d{1,3})*\.\s+\S'           # 4. Term / 4.1. Term
    r'|\d{1,3}(?:\.\d{1,3})+\s+[A-Z(]'          # 4.1 Term
    r'|\((?:[a-z]{1,2}|[ivxlc]{1,5})\)\s'       # (a) / (iv)
    r'|\(\d{1,2}\)\s+[A-Z]'                     # (1) The
    r'|[a-z]\)\s|[A-Z]\.\s+[A-Z]|[IVX]{1,5}\.\s+[A-Z]'
    r'|[•●▪–\-*]\s)')
LABEL_LINE = re.compile(r"^[A-Z][A-Za-z /&()'-]{1,40}:(?:\s|$)")
TERMINAL = re.compile(r'[.:;!?)\]"”]\s*$')
PAGE_NUMBER = re.compile(r'^(?:page\s*)?[#ivxlc]+(?:\s*(?:of|/)\s*[#ivxlc]+)?$|^[-–—]\s*#\s*[-–—]$', re.I)
KEEP_HYPHEN = {'non', 'self', 'co', 'pre', 'post', 're', 'anti', 'multi', 'third', 'cross', 'sub', 'inter', 'semi', 'well', 'long', 'short', 'sole', 'end', 'cost', 'time', 'arm', 'year', 'month', 'day', 'one', 'two', 'three', 'four', 'five', 'six', 'seven', 'eight', 'nine', 'ten', 'twenty', 'thirty', 'forty', 'fifty', 'sixty', 'seventy', 'eighty', 'ninety'}

def is_heading(text):
    letters = [c for c in text if c.isalpha()]
    return 3 <= len(letters) and len(text) <= 90 and sum(c.isupper() for c in letters) / len(letters) > 0.9 and not text.endswith(',')

def join_lines(lines):
    """Join wrapped lines of one paragraph, re-joining words hyphenated at a line break."""
    out = ''
    for line in lines:
        line = line.replace('­', '').strip()
        if not line:
            continue
        if not out:
            out = line
            continue
        m = re.search(r'([A-Za-z]+)-$', out)
        if m and line[:1].islower() and m.group(1).lower() not in KEEP_HYPHEN and not re.search(r'-[A-Za-z]+-$', out):
            out = out[:-1] + line           # "agree-\nment" -> "agreement"
        elif out.endswith(('-', '/')) and not out.endswith(' -'):
            out += line                     # "non-\ncommercial" keeps its hyphen
        else:
            out += ' ' + line
    return re.sub(r'[ \t]+', ' ', out)

def segment(lines):
    """Group positioned lines into paragraphs using layout cues.

    Each line is a dict with text, x0, x1, top, bottom and optionally size, bold and group (a source block id).
    A new paragraph starts at extra vertical space, a clause number or ``Label:`` line after a finished line, a
    heading, a change of font size or weight, an indentation change after a finished line, or a jump back up the page
    (a new column)."""
    lines = [l for l in lines if l['text'].strip()]
    if not lines:
        return []
    heights = sorted(max(1.0, l['bottom'] - l['top']) for l in lines)
    h = statistics.median(heights)
    lefts = sorted(l['x0'] for l in lines); rights = sorted(l['x1'] for l in lines)
    left = lefts[len(lefts) // 10]; right = rights[(len(rights) * 9) // 10]
    gaps = sorted(b['top'] - a['bottom'] for a, b in zip(lines, lines[1:]) if -h / 2 <= b['top'] - a['bottom'] <= 3 * h)
    base = gaps[len(gaps) // 4] if gaps else 0
    short_by = max(4 * h, 0.1 * (right - left))
    paragraphs, current = [], [lines[0]]
    for prev, line in zip(lines, lines[1:]):
        text, ptext = line['text'].strip(), prev['text'].strip()
        finished = bool(TERMINAL.search(ptext)) or is_heading(ptext) or prev['x1'] < left + 0.6 * (right - left)
        gap = line['top'] - prev['bottom']
        brk = (
            gap > base + max(0.5 * h, 2)
            or line['top'] < prev['top'] - h                      # jumped back up: new column or out-of-order text
            or LABEL_LINE.match(text)
            or (LABEL_LINE.match(ptext) and text[:1].isupper())        # a "Label: value" line ends at the next capitalised line
            or (CLAUSE_START.match(text) and finished)
            or is_heading(text) or is_heading(ptext)
            or abs(line.get('size', 0) - prev.get('size', 0)) > 1
            or line.get('bold', False) != prev.get('bold', False)
            or (abs(line['x0'] - prev['x0']) > 0.8 * h and finished)
            or (prev['x1'] < right - short_by and TERMINAL.search(ptext))
            or line.get('group') is not None and prev.get('group') is not None and line['group'] != prev['group'] and finished
        )
        if brk:
            paragraphs.append(current); current = [line]
        else:
            current.append(line)
    paragraphs.append(current)
    return [t for t in (join_lines([l['text'] for l in p]) for p in paragraphs) if t.strip()]

def margin_noise(pages):
    """Return per-page sets of line indexes that are running headers, footers or page numbers.

    pages: list of (height, lines). A line counts when it sits in the top or bottom 9% of the page and its text (with
    digits normalized) repeats on at least half of the pages (minimum two), or when it is just a page number."""
    def key(text):
        return re.sub(r'\d+', '#', re.sub(r'\s+', ' ', text.strip().lower()))
    counts = {}
    candidates = []
    for height, lines in pages:
        found = {}
        for i, l in enumerate(lines):
            if l['bottom'] <= 0.09 * height or l['top'] >= 0.91 * height:
                found[i] = key(l['text'])
        candidates.append(found)
        for k in set(found.values()):
            counts[k] = counts.get(k, 0) + 1
    need = max(2, (len(pages) + 1) // 2)
    return [{i for i, k in found.items() if counts[k] >= need or PAGE_NUMBER.match(k)} for found in candidates]

# ---------------------------------------------------------------- PDF (pypdf for text, Poppler + Tesseract for scans)

def _mult(m, n):
    return [m[0]*n[0] + m[1]*n[2], m[0]*n[1] + m[1]*n[3], m[2]*n[0] + m[3]*n[2], m[2]*n[1] + m[3]*n[3],
            m[4]*n[0] + m[5]*n[2] + n[4], m[4]*n[1] + m[5]*n[3] + n[5]]

def _width(text, font, size):
    """Approximate rendered width from the font's /Widths table, or half the font size per character."""
    try:
        widths, first = font['/Widths'], int(font['/FirstChar'])
        total = 0.0
        for ch in text:
            code = ord(ch) - first
            total += float(widths[code]) if 0 <= code < len(widths) and float(widths[code]) > 0 else 500.0
        return total / 1000 * size
    except Exception:
        return 0.5 * size * len(text)

def pdf_lines(page):
    """Positioned text lines of a text PDF page from pypdf's text visitor (PDF y is converted to top-down)."""
    box = page.mediabox
    top_edge = float(box.top)
    pieces = []
    def visit(text, cm, tm, font, size):
        if not text or not text.strip('\n'):
            return
        m = _mult(tm, cm)
        scale = (m[0] ** 2 + m[1] ** 2) ** 0.5 or 1.0
        eff = max(1.0, (size or 12) * scale)
        name = str((font or {}).get('/BaseFont', '')).lower()
        x, y = m[4], m[5]
        for k, part in enumerate(text.split('\n')):
            if part.strip():
                pieces.append({'x': x, 'y': y - k * eff * 1.2, 'text': part, 'size': eff, 'w': _width(part, font or {}, size or 12) * scale,
                               'bold': 'bold' in name or 'black' in name or 'heavy' in name})
    page.extract_text(visitor_text=visit)
    lines = []
    for p in pieces:
        last = lines[-1] if lines else None
        if last and abs(p['y'] - last['y']) < 0.3 * p['size'] and -p['size'] < p['x'] - last['x1'] < 6 * p['size']:
            sep = '' if p['x'] - last['x1'] < 0.15 * p['size'] or last['text'].endswith(' ') or p['text'].startswith(' ') else ' '
            last.update(text=last['text'] + sep + p['text'], x1=max(last['x1'], p['x'] + p['w']))
            continue
        lines.append({'text': p['text'], 'x0': p['x'], 'x1': p['x'] + p['w'], 'y': p['y'], 'top': top_edge - p['y'] - 0.8 * p['size'],
                      'bottom': top_edge - p['y'] + 0.2 * p['size'], 'size': round(p['size']), 'bold': p['bold']})
    for l in lines:
        l.pop('y')
    return lines

def ocr_page(path, index, width_pt, height_pt, tmp, warnings):
    """Render one page with Poppler at OCR_DPI, read it with Tesseract and return (lines, page height in pixels)."""
    if not shutil.which('tesseract') or not shutil.which('pdftoppm'):
        raise ParseError('scanned_pdf_needs_ocr_install_tesseract_and_poppler')
    longest = max(width_pt, height_pt) / 72
    dpi = max(72, min(OCR_DPI, int(OCR_MAX_PIXELS / longest))) if longest else OCR_DPI
    prefix = str(Path(tmp) / f'page-{index}')
    subprocess.run(['pdftoppm', '-f', str(index + 1), '-l', str(index + 1), '-r', str(dpi), '-gray', '-png', '-singlefile', str(path), prefix],
                   check=True, timeout=60, capture_output=True)
    # psm 3: automatic page segmentation (columns, headings); --dpi tells Tesseract the true resolution.
    result = subprocess.run(['tesseract', prefix + '.png', 'stdout', '--psm', '3', '--dpi', str(dpi), 'tsv'],
                            capture_output=True, text=True, check=True, timeout=90)
    Path(prefix + '.png').unlink(missing_ok=True)
    lines, conf, skew = tesseract_lines(result.stdout)
    if skew:
        warnings.append(f'Page {index + 1}: the scan is tilted about {abs(skew):.1f} degrees; the layout was straightened before reading paragraphs.')
    if conf is not None and conf < OCR_LOW_CONFIDENCE:
        warnings.append(f'Page {index + 1}: low OCR confidence ({conf:.0f}%). Check the text against the scan before approving.')
    return lines, height_pt * dpi / 72

def tesseract_lines(tsv):
    """Lines, mean word confidence and corrected skew (degrees, 0 when straight) from Tesseract TSV output.

    Tesseract reads slightly tilted text well but its line boxes are axis-aligned, so a tilt makes neighbouring lines
    overlap. When the median word baseline slope exceeds 0.4 degrees, word positions are rotated back before lines are
    measured, which keeps paragraph detection working without re-rendering the page."""
    import math
    rows = list(csv.DictReader(io.StringIO(tsv), delimiter='\t', quoting=csv.QUOTE_NONE))
    lines, order, confs = {}, [], []
    for r in rows:
        if r.get('level') != '5' or not (r.get('text') or '').strip():
            continue
        key = (r['block_num'], r['par_num'], r['line_num'])
        left, top, width, height = (int(r[k]) for k in ('left', 'top', 'width', 'height'))
        if key not in lines:
            lines[key] = {'words': [], 'group': r['block_num']}; order.append(key)
        lines[key]['words'].append([left, top, left + width, top + height, r['text']])
        try:
            c = float(r['conf'])
            if c >= 0:
                confs.append(c)
        except ValueError:
            pass
    slopes = []
    for key in order:
        words = lines[key]['words']
        if len(words) >= 4:
            xs = [(w[0] + w[2]) / 2 for w in words]; ys = [w[3] for w in words]
            mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
            den = sum((x - mx) ** 2 for x in xs)
            if den:
                slopes.append(sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / den)
    skew = math.degrees(math.atan(statistics.median(slopes))) if len(slopes) >= 3 else 0.0
    skew = skew if 0.4 <= abs(skew) <= 10 else 0.0
    if skew:
        a = math.radians(-skew); ca, sa = math.cos(a), math.sin(a)
        for key in order:
            for w in lines[key]['words']:
                cx, cy = (w[0] + w[2]) / 2, (w[1] + w[3]) / 2
                nx, ny = cx * ca - cy * sa, cx * sa + cy * ca
                hw, hh = (w[2] - w[0]) / 2, (w[3] - w[1]) / 2
                w[0], w[1], w[2], w[3] = nx - hw, ny - hh, nx + hw, ny + hh
    out = []
    for key in order:
        words = lines[key]['words']
        tops = sorted(w[1] for w in words); bottoms = sorted(w[3] for w in words)
        out.append({'text': ' '.join(w[4] for w in words), 'x0': min(w[0] for w in words), 'x1': max(w[2] for w in words),
                    'top': tops[len(tops) // 2], 'bottom': bottoms[len(bottoms) // 2], 'group': lines[key]['group']})
    return out, (sum(confs) / len(confs) if confs else None), round(skew, 1)

def parse_pdf(path, blocks, warnings):
    from pypdf import PdfReader
    from pypdf.errors import DependencyError
    try:
        reader = PdfReader(path)
        if reader.is_encrypted and not reader.decrypt(''):
            raise ParseError('pdf_is_password_protected_remove_the_password_and_import_again')
        pages_in = list(reader.pages)
    except ParseError:
        raise
    except DependencyError:
        raise ParseError('pdf_encryption_needs_the_cryptography_package')
    except Exception:
        raise ParseError('pdf_is_damaged_or_unreadable')
    if len(pages_in) > MAX_PAGES:
        raise ParseError('page_limit')
    pages, scanned = [], []
    with tempfile.TemporaryDirectory(prefix='ocr-', dir=Path(path).parent) as tmp:
        for index, page in enumerate(pages_in):
            try:
                lines = pdf_lines(page)
            except Exception:
                lines = []
            height = float(page.mediabox.height)
            if len(''.join(l['text'] for l in lines).strip()) < 20:
                lines, height = ocr_page(path, index, float(page.mediabox.width), height, tmp, warnings); scanned.append(index + 1)
            pages.append((height, lines))
    if len(pages) > 1:
        noise = margin_noise(pages)
    else:
        noise = [{i for i, l in enumerate(lines) if (l['bottom'] <= 0.09 * height or l['top'] >= 0.91 * height)
                  and PAGE_NUMBER.match(re.sub(r'\d+', '#', l['text'].strip().lower()))} for height, lines in pages]
    per_page = [segment([l for i, l in enumerate(lines) if i not in drop]) for (_, lines), drop in zip(pages, noise)]
    for index, paragraphs in enumerate(per_page):
        first = 1
        if index and per_page[index - 1] and paragraphs and paragraphs[0][:1].islower() and not TERMINAL.search(per_page[index - 1][-1]):
            first = 2                   # the opening fragment was joined to the previous page's last paragraph
        for n, text in enumerate(paragraphs[first - 1:], first):
            locator = f'Page {index + 1}, paragraph {n}'
            following = per_page[index + 1] if index + 1 < len(per_page) else []
            if n == len(paragraphs) and following and following[0][:1].islower() and not TERMINAL.search(text):
                text, locator = join_lines([text, following[0]]), f'{locator} (continues on page {index + 2})'
            blocks.add(locator, text)
    return {'engine': 'pdf-ocr' if len(scanned) == len(pages) else 'pdf-mixed' if scanned else 'pdf-text', 'ocr_pages': scanned}

# ---------------------------------------------------------------- Word

W = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
SKIP = {W + 'del', W + 'moveFrom', W + 'txbxContent', W + 'pPr', W + 'rPr', W + 'instrText', W + 'delInstrText',
        '{http://schemas.openxmlformats.org/markup-compatibility/2006}Fallback', W + 'footnoteReference', W + 'commentReference'}

def run_text(element):
    """Visible text of a paragraph with tracked changes accepted (insertions kept, deletions dropped)."""
    out = []
    def walk(el):
        for child in el:
            tag = child.tag
            if tag in SKIP:
                continue
            if tag == W + 't':
                out.append(child.text or '')
            elif tag == W + 'tab':
                out.append('\t')
            elif tag in (W + 'br', W + 'cr'):
                out.append('\n')
            elif tag == W + 'noBreakHyphen':
                out.append('-')
            else:
                walk(child)
    walk(element)
    return ''.join(out)

def _roman(n):
    vals = [(1000, 'm'), (900, 'cm'), (500, 'd'), (400, 'cd'), (100, 'c'), (90, 'xc'), (50, 'l'), (40, 'xl'), (10, 'x'), (9, 'ix'), (5, 'v'), (4, 'iv'), (1, 'i')]
    out = ''
    for v, s in vals:
        while n >= v:
            out += s; n -= v
    return out

def _fmt(n, kind):
    if kind in ('lowerLetter', 'upperLetter'):
        s = ''
        while n > 0:
            n, r = divmod(n - 1, 26); s = chr(97 + r) + s
        return s.upper() if kind == 'upperLetter' else s
    if kind == 'lowerRoman':
        return _roman(n)
    if kind == 'upperRoman':
        return _roman(n).upper()
    if kind == 'none':
        return ''
    return str(n)

class Numbering:
    """Renders Word automatic list numbers ("4.", "4.1", "(a)") that are not part of the paragraph text."""
    def __init__(self, doc):
        self.nums, self.abstract, self.counters = {}, {}, {}
        try:
            root = doc.part.numbering_part.element
        except (NotImplementedError, KeyError, AttributeError):
            return
        for a in root.findall(W + 'abstractNum'):
            levels = {}
            for lvl in a.findall(W + 'lvl'):
                get = lambda name: (lvl.find(W + name).get(W + 'val') if lvl.find(W + name) is not None else None)
                levels[int(lvl.get(W + 'ilvl', '0'))] = (int(get('start') or 1), get('numFmt') or 'decimal', get('lvlText') or '')
            self.abstract[a.get(W + 'abstractNumId')] = levels
        for n in root.findall(W + 'num'):
            ref = n.find(W + 'abstractNumId')
            restart = n.find(f'{W}lvlOverride/{W}startOverride') is not None
            self.nums[n.get(W + 'numId')] = (ref.get(W + 'val') if ref is not None else None, n.get(W + 'numId') if restart else None)

    def label(self, paragraph):
        num_pr = paragraph._p.find(f'{W}pPr/{W}numPr')
        if num_pr is None:
            try:
                num_pr = paragraph.style.element.find(f'{W}pPr/{W}numPr')
            except AttributeError:
                num_pr = None
        if num_pr is None:
            return ''
        nid = num_pr.find(W + 'numId'); ilvl = num_pr.find(W + 'ilvl')
        nid = nid.get(W + 'val') if nid is not None else None
        level = int(ilvl.get(W + 'val')) if ilvl is not None else 0
        if not nid or nid == '0' or nid not in self.nums:
            return ''
        abstract_id, own = self.nums[nid]
        levels = self.abstract.get(abstract_id, {})
        if level not in levels:
            return ''
        key = own or abstract_id
        counts = self.counters.setdefault(key, {})
        start, kind, text = levels[level]
        counts[level] = counts.get(level, start - 1) + 1
        for deeper in [k for k in counts if k > level]:
            del counts[deeper]
        if kind == 'bullet':
            return '•'
        def sub(m):
            k = int(m.group(1)) - 1
            s, f, _ = levels.get(k, (1, 'decimal', ''))
            return _fmt(counts.get(k, s), f)
        return re.sub(r'%(\d)', sub, text).strip()

def table_rows(table):
    """Rows of a Word table as lists of cell texts, with horizontally merged cells counted once."""
    rows = []
    for row in table.rows:
        cells, seen = [], set()
        for cell in row.cells:
            if id(cell._tc) in seen:
                continue
            seen.add(id(cell._tc))
            cells.append(' '.join(run_text(p).strip() for p in cell._tc.iter(W + 'p') if run_text(p).strip()))
        rows.append((row, cells))
    return rows

def has_header(table, rows):
    if len(rows) < 2:
        return False
    first_row, first = rows[0]
    if not all(c.strip() for c in first) or len(set(first)) != len(first) or any(len(c) > 60 for c in first):
        return False
    tr_pr = first_row._tr.find(W + 'trPr')
    repeat = tr_pr is not None and tr_pr.find(W + 'tblHeader') is not None
    bold = any(r.get(W + 'val', 'true') not in ('0', 'false') for r in first_row._tr.iter(W + 'b'))
    return repeat or bold or len(first) >= 3

def parse_docx(path, blocks, warnings):
    zip_guard(path)
    from docx import Document
    from docx.table import Table
    from docx.text.paragraph import Paragraph
    try:
        doc = Document(path)
    except Exception:
        raise ParseError('word_file_is_damaged_or_unreadable')
    body = doc.element.body
    if any(True for _ in body.iter(W + 'ins', W + 'del', W + 'moveFrom', W + 'moveTo')):
        warnings.append('This Word file has tracked changes. Its text was read with all changes accepted; check it against the final signed version.')
    numbering = Numbering(doc)
    paragraph_no = table_no = 0
    heading, seen_body = '', False
    def items(parent):
        for child in parent:
            if child.tag == W + 'p':
                yield Paragraph(child, doc._body)
            elif child.tag == W + 'tbl':
                yield Table(child, doc._body)
            elif child.tag == W + 'sdt':
                content = child.find(W + 'sdtContent')
                if content is not None:
                    yield from items(content)
    for item in items(body):
        if isinstance(item, Paragraph):
            text = run_text(item._p).strip()
            if not text:
                continue
            label = numbering.label(item)
            if label and not text.startswith(label):
                text = f'{label} {text}'
            paragraph_no += 1
            style = (item.style.name if item.style is not None else '') or ''
            if style.startswith(('Heading', 'Title')) or (is_heading(text) and not TERMINAL.search(text)):
                # The first heading before any body text is the document title, not a section.
                heading = text if seen_body and not style.startswith('Title') else heading
                blocks.add(f'Paragraph {paragraph_no}', text)
            else:
                seen_body = True
                blocks.add(f'Paragraph {paragraph_no}' + (f' (under "{heading[:60]}")' if heading else ''), text)
        else:
            table_no += 1
            rows = table_rows(item)
            header = rows[0][1] if has_header(item, rows) else None
            for j, (_, cells) in enumerate(rows, 1):
                if header and j == 1:
                    continue
                if header:
                    text = ' | '.join(f'{h}: {c}' for h, c in zip(header, cells) if c.strip())
                else:
                    text = ' | '.join(c for c in cells if c.strip())
                blocks.add(f'Table {table_no}, row {j}', text)
    seen = set()
    for kind, attrs in (('header', ('header', 'first_page_header', 'even_page_header')), ('footer', ('footer', 'first_page_footer', 'even_page_footer'))):
        n = 0
        for section in doc.sections:
            for attr in attrs:
                part = getattr(section, attr)
                if part.is_linked_to_previous:
                    continue
                text = ' '.join(t for t in (run_text(p).strip() for p in part._element.iter(W + 'p')) if t)
                text = re.sub(r'\s+', ' ', text).strip()
                if text and not PAGE_NUMBER.match(re.sub(r'\d+', '#', text.lower())) and text not in seen:
                    seen.add(text); n += 1
                    blocks.add(f'Page {kind}' + (f' {n}' if n > 1 else ''), text)
    return {'engine': 'docx'}

# ---------------------------------------------------------------- text, CSV and Excel

def decode_text(data, warnings):
    """Decode text files: UTF-8 (with or without BOM), UTF-16 with BOM, then Windows-1252 with a warning."""
    if data.startswith((b'\xff\xfe', b'\xfe\xff')):
        return data.decode('utf-16')
    if b'\x00' in data[:4096]:
        raise ParseError('file_looks_binary_not_text')
    try:
        return data.decode('utf-8-sig')
    except UnicodeDecodeError:
        warnings.append('This file is not UTF-8; it was read as Windows-1252 (Western European). Check accented characters.')
        return data.decode('cp1252', errors='replace')

def parse_text(path, blocks, warnings):
    data = Path(path).read_bytes()
    if len(data) > 25_000_000:
        raise ParseError('text_limit')
    for i, line in enumerate(decode_text(data, warnings).splitlines()):
        blocks.add(f'Line {i + 1}', line)
    return {'engine': 'text'}

def parse_xlsx(path, blocks, warnings):
    zip_guard(path)
    from openpyxl import load_workbook
    wb = load_workbook(path, read_only=True, data_only=False)
    try:
        for ws in wb:
            if ws.max_row and ws.max_row > 10000 or ws.max_column and ws.max_column > 100:
                raise ParseError('sheet_limit')
            for row in ws.iter_rows():
                text = ' | '.join(f'{cell.coordinate}: {cell.value}' for cell in row if getattr(cell, 'value', None) is not None and cell.data_type != 'f')
                if row:
                    blocks.add(f'{ws.title}, row {row[0].row}', text)
    finally:
        wb.close()
    return {'engine': 'xlsx'}

def parse_document(path, suffix):
    """Parse a file into blocks. Returns {'blocks', 'warnings', 'engine', ...}; raises ParseError with a code."""
    path = Path(path)
    if suffix not in SUPPORTED:
        raise ParseError('unsupported_type')
    if path.stat().st_size == 0:
        raise ParseError('file_is_empty')
    blocks, warnings = Blocks(), []
    if suffix == '.pdf':
        info = parse_pdf(path, blocks, warnings)
    elif suffix == '.docx':
        info = parse_docx(path, blocks, warnings)
    elif suffix in ('.txt', '.csv'):
        info = parse_text(path, blocks, warnings)
    else:
        info = parse_xlsx(path, blocks, warnings)
    if not blocks.items:
        raise ParseError('no_readable_text_found')
    return {'blocks': blocks.items, 'warnings': warnings, **info}

def parse(path, suffix):
    return parse_document(path, suffix)['blocks']

# ---------------------------------------------------------------- spreadsheet reconciliation

TRACKER_PARTY = ('counterparty', 'counter party', 'other party', 'vendor', 'supplier', 'customer', 'partner', 'company', 'institution', 'party')
TRACKER_DATE = ('expiration', 'expiry', 'expires', 'end date', 'termination date', 'renewal date', 'effective')
TRACKER_META = ('owner', 'status', 'agreement id', 'contract id', 'agreement type', 'contract type', 'type', 'notice', 'agreement', 'contract', 'reference')

def _rows(data, suffix, limit=None):
    if suffix == '.csv':
        text = decode_text(data, [])
        reader = csv.reader(io.StringIO(text))
        rows = []
        for row in reader:
            rows.append(row)
            if limit and len(rows) >= limit:
                break
        return rows, 'CSV'
    from openpyxl import load_workbook
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        if sum(i.file_size for i in z.infolist()) > 100_000_000:
            raise ValueError('archive_limits')
    wb = load_workbook(io.BytesIO(data), read_only=True, data_only=False)
    try:
        ws = wb.worksheets[0]
        if ws.max_row and ws.max_row > 10000 or ws.max_column and ws.max_column > 100:
            raise ValueError('sheet_limit')
        rows = []
        for row in ws.iter_rows():
            rows.append([None if getattr(c, 'data_type', None) == 'f' else getattr(c, 'value', None) for c in row])
            if limit and len(rows) >= limit:
                break
        return rows, ws.title
    finally:
        wb.close()

def tracker_columns(data, suffix):
    """If a CSV or XLSX file looks like an agreement tracker, return its recognised header names, else None.

    A tracker has a header row (within the first five rows) naming a counterparty-like column plus an expiration,
    owner, status or similar column, at least three named columns and at least one data row below."""
    if suffix not in ('.csv', '.xlsx'):
        return None
    try:
        rows, _ = _rows(data, suffix, limit=6)
    except Exception:
        return None
    for i, row in enumerate(rows[:5]):
        headers = [str(v).strip() for v in row if v is not None and str(v).strip()]
        norm = [h.lower() for h in headers]
        party = [h for h, n in zip(headers, norm) if any(k == n or n.startswith(k + ' ') or n.endswith(' ' + k) for k in TRACKER_PARTY)]
        other = [h for h, n in zip(headers, norm) if h not in party and any(k in n for k in TRACKER_DATE + TRACKER_META)]
        data_rows = [r for r in rows[i + 1:] if any(v is not None and str(v).strip() for v in r)]
        if len(headers) >= 3 and party and other and data_rows and all(len(h) <= 60 for h in headers):
            return party + other
    return None

def spreadsheet_rows(data, suffix):
    if suffix not in ('.csv', '.xlsx'):
        raise ValueError('CSV or XLSX required')
    rows, sheet = _rows(data, suffix)
    if not rows or len(rows) > 10001 or len(rows[0]) > 100:
        raise ValueError('sheet_limit')
    headers = [str(v or '').strip() for v in rows[0]]
    if len(set(headers)) != len(headers) or any(not h for h in headers):
        raise ValueError('Headers must be unique and nonempty')
    return headers, [{'row': i+2, 'sheet': sheet, 'values': {h: str(v or '') for h,v in zip(headers, row)}} for i,row in enumerate(rows[1:]) if any(row)]

if __name__ == '__main__':
    try:
        try:
            import resource
            resource.setrlimit(resource.RLIMIT_CPU, (150, 150))
            resource.setrlimit(resource.RLIMIT_AS, (2_000_000_000, 2_000_000_000))
        except (ImportError, ValueError):
            pass
        result = parse_document(Path(sys.argv[1]), sys.argv[2])
    except ParseError as exc:
        result = {'error': str(exc)}   # content-free code
    except Exception:
        result = {'error': 'parse_failed_or_unsupported_content'}
    Path(sys.argv[3]).write_text(json.dumps(result))
