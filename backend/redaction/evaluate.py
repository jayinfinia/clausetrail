"""Compare pipeline redactions with redactions people already made.

pair mode (original + reference redacted copy):
  text files:    words the reference removed vs words the pipeline removed -> precision, recall, F1
  scanned PDFs:  pixels blacked out by the reference vs by the pipeline (relative to the original)
                 -> pixel recall, precision, IoU, and whether every reference box is covered
reference only (no original available):
  leak check:    read the reference and run the detector; anything still found is a value the
                 existing redaction left visible under the chosen policy.
Reports hold counts and scores only, never the values themselves.
"""
import io
import re
from collections import Counter
from pathlib import Path

from . import detect, engines

REF_MARK = re.compile(r'[\s_\-]*\(?redacted\)?|\s*\(\d{3}\)', re.I)


def base_name(filename):
    stem = Path(filename).stem
    return re.sub(r'\s+', ' ', REF_MARK.sub('', stem)).strip().lower()


def is_reference(filename):
    return 'redacted' in Path(filename).stem.lower()


def _tokens(text):
    return Counter(re.findall(r'[A-Za-z0-9@.\-]+', text.lower()))


def extract_text(data, filename):
    ext = Path(filename).suffix.lower()
    if ext == '.pdf':
        import pymupdf
        doc = pymupdf.open(stream=data, filetype='pdf'); out = []
        for page in doc:
            t = page.get_text()
            if len(t.strip()) < 40:
                import os, tempfile
                pix = page.get_pixmap(dpi=engines.OCR_DPI)
                with tempfile.TemporaryDirectory() as tmp:
                    p = os.path.join(tmp, 'p.png'); pix.save(p)
                    t, _ = engines._words_to_text(engines.ocr_words(p))
            out.append(t)
        return '\n'.join(out)
    if ext == '.docx':
        import docx
        d = docx.Document(io.BytesIO(data))
        return '\n'.join(p.text for p in engines._docx_paragraphs(d))
    if ext == '.xlsx':
        import openpyxl
        wb = openpyxl.load_workbook(io.BytesIO(data))
        return '\n'.join(str(c.value) for ws in wb.worksheets for row in ws.iter_rows() for c in row if c.value is not None)
    return data.decode('utf-8', errors='replace')


def _prf(tp, fp, fn):
    p = tp / (tp + fp) if tp + fp else 1.0
    r = tp / (tp + fn) if tp + fn else 1.0
    return {'precision': round(p, 3), 'recall': round(r, 3), 'f1': round(2 * p * r / (p + r), 3) if p + r else 0.0}


def text_pair(original, reference, ours_texts, filename):
    orig_text = extract_text(original, filename)
    ref_removed = _tokens(orig_text) - _tokens(extract_text(reference, filename))
    ours_removed = Counter()
    for text, spans in ours_texts:
        for s, e, _, _ in spans:
            ours_removed += _tokens(text[s:e])
    tp = sum((ref_removed & ours_removed).values())
    fp = sum((ours_removed - ref_removed).values())
    fn = sum((ref_removed - ours_removed).values())
    return {'mode': 'text pair', 'reference_redacted_words': sum(ref_removed.values()),
            'pipeline_redacted_words': sum(ours_removed.values()), 'matched_words': tp,
            'missed_words': fn, 'extra_words': fp, **_prf(tp, fp, fn)}


def _dark_masks(data, dpi=60):
    import pymupdf
    doc = pymupdf.open(stream=data, filetype='pdf'); masks = []
    for page in doc:
        pix = page.get_pixmap(dpi=dpi, colorspace=pymupdf.csGRAY, alpha=False)
        masks.append((pix.width, pix.height, bytes(1 if b < 40 else 0 for b in pix.samples)))
    return masks


def _boxes(mask, w, h, min_px=30):
    """Connected dark regions (4-neighbour) -> list of pixel index sets, ignoring specks."""
    seen, boxes = bytearray(len(mask)), []
    for i, v in enumerate(mask):
        if v and not seen[i]:
            stack, comp = [i], []
            seen[i] = 1
            while stack:
                j = stack.pop(); comp.append(j); x, y = j % w, j // w
                for k in ((j - 1) if x else -1, (j + 1) if x < w - 1 else -1, j - w, j + w):
                    if 0 <= k < len(mask) and mask[k] and not seen[k]:
                        seen[k] = 1; stack.append(k)
            if len(comp) >= min_px:
                boxes.append(set(comp))
    return boxes


def image_pair(original, reference, ours):
    o, r, p = _dark_masks(original), _dark_masks(reference), _dark_masks(ours)
    pages = min(len(o), len(r), len(p))
    inter = ref_px = our_px = 0; ref_boxes = covered = 0
    for i in range(pages):
        (w, h, om), (_, _, rm), (_, _, pm) = o[i], r[i], p[i]
        if not (len(om) == len(rm) == len(pm)):
            continue
        ref_new = bytes(a and not b for a, b in zip(rm, om))
        our_new = bytes(a and not b for a, b in zip(pm, om))
        inter += sum(1 for a, b in zip(ref_new, our_new) if a and b)
        ref_px += sum(ref_new); our_px += sum(our_new)
        for box in _boxes(ref_new, w, h):
            ref_boxes += 1
            # A reference redaction often draws one box over the whole field; the value is part of it. The
            # value-only box the pipeline draws overlaps it; whether the value is gone is checked by re-reading the output.
            covered += sum(1 for j in box if our_new[j]) / len(box) >= 0.05
    union = ref_px + our_px - inter
    return {'mode': 'scanned pair', 'pages_compared': pages, 'reference_boxes': ref_boxes, 'reference_boxes_covered': covered,
            'pixel_recall': round(inter / ref_px, 3) if ref_px else 1.0,
            'pixel_precision': round(inter / our_px, 3) if our_px else (1.0 if not ref_px else 0.0),
            'iou': round(inter / union, 3) if union else 1.0}


def leak_check(reference, filename, policy, llm=None):
    text = extract_text(reference, filename)
    spans, warnings = detect.find(text, policy, llm)
    return {'mode': 'reference leak check', 'still_visible': len(spans),
            'still_visible_by_category': dict(Counter(c for _, _, c, _ in spans)), 'warnings': warnings}
