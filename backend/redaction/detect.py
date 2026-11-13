"""Find confidential spans in text: deterministic rules plus an optional local Llama model.

Policies
- standard: SSNs and tax IDs, other government IDs, bank and card numbers and dates of
  birth. Names, addresses and business terms stay readable for review.
- strict:   standard plus personal names, email addresses, phone numbers and street
  addresses, for copies shared outside the organization.

Every span is (start, end, category, source). Model output is only accepted when the
exact text occurs in the document, so the model cannot invent or move a redaction.
"""
import re

STANDARD = ('GOV_ID', 'FIN_ACCOUNT', 'DOB')
STRICT = STANDARD + ('PERSON', 'EMAIL', 'PHONE', 'ADDRESS', 'IP')
POLICIES = {'standard': STANDARD, 'strict': STRICT}
CATEGORY_NAMES = {'GOV_ID': 'SSN / tax ID', 'FIN_ACCOUNT': 'Bank or card number', 'DOB': 'Date of birth',
                  'PERSON': 'Person name', 'EMAIL': 'Email', 'PHONE': 'Phone', 'ADDRESS': 'Street address', 'IP': 'IP address'}

_ID_CONTEXT = r'(?:social\s+security|ssn|s\.s\.n\.|tax\s*(?:payer)?\s*(?:id|identification)|\btin\b|\bein\b|fed(?:eral)?\.?\s+tax|itin|employer\s+identification)'
_STREET = (r'(?:street|st|avenue|ave|road|rd|drive|dr|lane|ln|way|boulevard|blvd|court|ct|trail|trl|place|pl|'
           r'parkway|pkwy|circle|cir|highway|hwy|terrace|ter|square|sq|suite|ste)\.?')
_STATES = (r'(?:AL|AK|AZ|AR|CA|CO|CT|DE|DC|FL|GA|HI|ID|IL|IN|IA|KS|KY|LA|ME|MD|MA|MI|MN|MS|MO|MT|NE|NV|NH|NJ|NM|NY|'
           r'NC|ND|OH|OK|OR|PA|RI|SC|SD|TN|TX|UT|VT|VA|WA|WV|WI|WY)')
_ESIGN_NAME = r"[A-Z][A-Za-z.'\-]*\.?(?:[ \t]+[A-Z][A-Za-z.'\-]*\.?){0,3}(?:,[ \t]*(?:Jr|Sr|II|III|IV)\.?)?"
_NAME = r"[A-Z][a-zA-Z'\-]+(?:[ \t]+[A-Z]\.?)?(?:[ \t]+[A-Z][a-zA-Z'\-]+){1,2}"

RULES = [
    ('GOV_ID', re.compile(r'(?<![\d-])(?!000|666|9\d\d)\d{3}[- ]\d{2}[- ]\d{4}(?![\d-])')),            # SSN
    ('GOV_ID', re.compile(r'(?<![\d-])\d{2}-\d{7}(?![\d-])')),                                         # EIN
    ('GOV_ID', re.compile(_ID_CONTEXT + r'[^\d\n]{0,40}?(\d{9})(?!\d)', re.I), 1),                      # bare 9 digits near label
    ('GOV_ID', re.compile(r'(\d{9}|\d{3}[- ]\d{2}[- ]\d{4})[^\d\n]{0,6}\n?[^\n]{0,12}' + _ID_CONTEXT, re.I), 1),  # value above its caption
    ('FIN_ACCOUNT', re.compile(r'(?:account|acct|routing|aba|iban|swift|a/c)\s*(?:no\.?|number|#)?\s*[:#]?\s*([A-Z]{0,4}\d[\d -]{5,24}\d)', re.I), 1),
    ('DOB', re.compile(r'(?:date\s+of\s+birth|birth\s*date|d\.?o\.?b\.?|\bborn(?:\s+on)?)\s*[:\-]?\s*(\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4}|[A-Z][a-z]+\.? \d{1,2},? \d{4})', re.I), 1),
    ('EMAIL', re.compile(r'[\w.+-]+@[\w-]+(?:\.[\w-]+)+')),
    ('IP', re.compile(r'(?<![\d.])(?:(?:25[0-5]|2[0-4]\d|1?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|1?\d?\d)(?![\d.])')),
    ('PHONE', re.compile(r'(?<!\d)(?:\+?1[ .-]?)?\(?\d{3}\)?[ .-]\d{3}[ .-]\d{4}(?!\d)')),
    ('ADDRESS', re.compile(r'\b\d{1,6}\s+(?:[A-Z][\w.\-]*\s+){1,4}' + _STREET + r'(?:,?\s*(?:Ste|Suite|Apt|Unit|#)\.?\s*\w+)?', re.I)),
    ('ADDRESS', re.compile(r'\b[A-Z][a-zA-Z.]+(?:\s[A-Z][a-zA-Z.]+){0,2},\s*' + _STATES + r'\.?\s+\d{5}(?:-\d{4})?\b')),
    ('PERSON', re.compile(r'(?:^|\n)[ \t]*(?:[A-Za-z]+[ \t]+){0,2}(?:name|print(?:ed)?(?:\s+name)?|signatory|recipient)\s*:[ \t]*(' + _NAME + r')', re.I), 1),
    # E-signature audit trails (Adobe Sign, DocuSign): "approved by Jane Q. Doe", "entered name at signing as ..."
    ('PERSON', re.compile(r'(?:created|filled in|viewed|verified|approved|signed|sent|emailed|delegated|completed)\s+by\s+(' + _ESIGN_NAME + r')', re.I), 1),
    ('PERSON', re.compile(r'name at signing as\s+(' + _ESIGN_NAME + r')', re.I), 1),
    # Signature stamps: "J.Q. Doe, Jr. (May 3, 2023 18:01 EDT)"
    ('PERSON', re.compile(r'(' + _ESIGN_NAME + r')\s*\((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.? \d{1,2}, \d{4}'), 1),
    ('PERSON', re.compile(r'(?:^|\n)[ \t]*(?:by|signed)\s*:[ \t]*(' + _NAME + r')(?=[ \t]*(?:[,\n]|$))', re.I), 1),
]


def _luhn(digits):
    total, alt = 0, False
    for d in reversed(digits):
        n = int(d)
        if alt:
            n = n * 2 - 9 if n > 4 else n * 2
        total, alt = total + n, not alt
    return total % 10 == 0


def rule_spans(text, categories):
    spans = []
    for rule in RULES:
        cat, rx, group = rule[0], rule[1], (rule[2] if len(rule) > 2 else 0)
        if cat not in categories:
            continue
        for m in rx.finditer(text):
            s, e = m.span(group)
            if e > s:
                spans.append((s, e, cat, 'rule'))
    if 'FIN_ACCOUNT' in categories:
        for m in re.finditer(r'(?<!\d)(?:\d[ -]?){13,19}(?!\d)', text):
            digits = re.sub(r'\D', '', m.group())
            if 13 <= len(digits) <= 19 and _luhn(digits):
                spans.append((m.start(), m.start() + len(m.group().rstrip(' -')), 'FIN_ACCOUNT', 'rule'))
    return spans


def locate(text, needle):
    """All occurrences of model-reported text, exact first, then whitespace/case tolerant."""
    needle = (needle or '').strip()
    if len(needle) < 3:
        return []
    hits = [(m.start(), m.end()) for m in re.finditer(re.escape(needle), text)]
    if hits:
        return hits
    loose = r'\s+'.join(re.escape(part) for part in needle.split())
    return [(m.start(), m.end()) for m in re.finditer(loose, text, re.I)]


def propagate(text, spans, categories):
    """Redact every other occurrence of a value already found once (a name repeated on page 7)."""
    out = list(spans)
    seen = {(text[s:e].strip(), c) for s, e, c, _ in spans if e - s >= 4}
    for value, cat in seen:
        if cat in categories:
            for s, e in locate(text, value):
                out.append((s, e, cat, 'repeat'))
    return out


def merge(spans):
    """Sort and merge overlapping spans; the first category wins, sources are combined."""
    merged = []
    for s, e, c, src in sorted(spans, key=lambda x: (x[0], -x[1])):
        if merged and s <= merged[-1][1]:
            ps, pe, pc, psrc = merged[-1]
            merged[-1] = (ps, max(pe, e), pc, psrc if src in psrc.split('+') else psrc + '+' + src)
        else:
            merged.append((s, e, c, src))
    return merged


def find(text, policy='standard', llm=None):
    """Return (spans, warnings). llm is an optional callable(text, categories) -> [(value, category)]."""
    categories = POLICIES[policy]
    spans, warnings = rule_spans(text, categories), []
    if llm is not None and text.strip():
        try:
            for value, cat in llm(text, categories):
                if cat in categories:
                    spans += [(s, e, cat, 'llm') for s, e in locate(text, value)]
        except Exception as exc:  # the model is optional; rules always run
            warnings.append(f'Local model step skipped: {exc}')
    return merge(propagate(text, spans, categories)), warnings
