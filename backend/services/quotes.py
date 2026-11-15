"""Quote and literal matching that tolerates typography, never wording.

A model copying a passage often changes how it looks but not what it says: curly quotes become straight,
an en dash becomes a hyphen, a word hyphenated across a PDF line break is joined, invisible characters
vanish, or words in the middle are elided with "...". These are accepted. Any change of letters, digits,
word order or punctuation other than quote and dash glyphs is not.

A match always reports the ORIGINAL source span, so the citation shows the source text itself. For an
elided quote that span includes the omitted words, and the support check judges the full span.
"""
import re
from datetime import date
from functools import lru_cache

# Glyph families that are interchangeable in a quotation. Mapping is one character to one character so
# offsets stay aligned with the source.
GLYPHS = str.maketrans({c: "'" for c in '‘’‚‛′ʼ'} | {c: '"' for c in '“”„‟″'}
                       | {c: '-' for c in '‐‑‒–—―−﹘﹣－'})
# Invisible characters dropped from both sides (zero-width spaces/joiners, word joiner, byte-order mark).
INVISIBLE = set('​‌‍⁠﻿')
SOFT_HYPHEN = '­'
# A word broken across a line: a hyphen followed by a line break or other whitespace, or a soft hyphen.
BREAK = r'(?:-\s+|­\s*)?'
# "...", ". . .", "…" and the bracketed forms; only used when the quote does not match as written.
ELISION = re.compile(r'\s*(?:\[\s*(?:…|\.(?:\s?\.){2,})\s*\]|…|\.(?:\s?\.){2,})\s*')
MAX_GAP = 600      # characters an elision may stand for
MAX_SPAN = 1800    # same bound as a quote
MIN_MATCH = 6


class QuoteMatch:
    """The part of re.Match that callers use: group(), start() and end() in original source offsets."""
    def __init__(self, text, start, end):
        self.string, self._start, self._end = text, start, end

    def group(self):
        return self.string[self._start:self._end]

    def start(self):
        return self._start

    def end(self):
        return self._end


@lru_cache(maxsize=64)
def _normalized(text):
    """(normalized text, index map back to the original). Soft hyphens are kept; the pattern handles them."""
    if not INVISIBLE.intersection(text):
        return text.translate(GLYPHS), None  # one-to-one: offsets are unchanged
    index = [i for i, ch in enumerate(text) if ch not in INVISIBLE]
    return ''.join(text[i] for i in index).translate(GLYPHS), index


def _token(token):
    """Regex for one whitespace-free token of the quote. Between two letters (the second lower case), the source
    may break the word with a hyphen and a line break or a soft hyphen; the quote's own hyphen may be followed
    by a line break in the source."""
    out = []
    for i, ch in enumerate(token):
        out.append(re.escape(ch))
        nxt = token[i + 1] if i + 1 < len(token) else ''
        if ch == '-' and nxt:
            out.append(r'\s*')
        elif i >= 1 and i + 2 < len(token) and ch.isalpha() and nxt.isalpha() and nxt.islower():
            out.append(BREAK)  # hyphenation leaves at least two letters on each line
    return ''.join(out)


def _segment(text):
    clean = ''.join(ch for ch in text if ch not in INVISIBLE and ch != SOFT_HYPHEN).translate(GLYPHS)
    return r'\s+'.join(_token(t) for t in clean.split())


def _search(pattern, text):
    norm, index = _normalized(text)
    match = re.search(pattern, norm)
    if not match or match.end() == match.start():
        return None
    start, end = (match.start(), match.end()) if index is None else (index[match.start()], index[match.end() - 1] + 1)
    found = QuoteMatch(text, start, end)
    return found if len(found.group().strip()) >= MIN_MATCH else None


def exact_quote(quote, text, ignore_case=False):
    """Find the quote in text, allowing only typography differences (see module docstring)."""
    if not isinstance(quote, str) or not isinstance(text, str) or not quote.strip():
        return None
    flags = '(?i)' if ignore_case else ''
    candidates = [quote.strip()]
    stripped = quote.strip().strip('"\'“”‘’').strip()
    if stripped != candidates[0]:
        candidates.append(stripped)  # the model wrapped the quote in quotation marks
    for q in candidates:
        if not q:
            continue
        # Fast path: the quote as written, whitespace aside (the common case).
        plain = re.search(flags + r'\s+'.join(re.escape(p) for p in q.split()), text)
        if plain and len(plain.group().strip()) >= MIN_MATCH:
            return QuoteMatch(text, plain.start(), plain.end())
        found = _search(flags + _segment(q), text)
        if found:
            return found
    for q in candidates:
        parts = [p for p in ELISION.split(q) if p.strip()]
        if len(parts) < 2 or any(len(re.sub(r'\W', '', p)) < 3 for p in parts):
            continue
        gap = r'[\s\S]{0,%d}?' % MAX_GAP
        found = _search(flags + gap.join('(?:%s)' % _segment(p) for p in parts), text)
        if found and found.end() - found.start() <= MAX_SPAN:
            return found
    return None


# ---------------------------------------------------------------- numbers and dates in a claim

MONTHS = {m: i for i, m in enumerate(['january', 'february', 'march', 'april', 'may', 'june', 'july', 'august',
                                      'september', 'october', 'november', 'december'], 1)}
MONTHS.update({m[:3]: i for m, i in list(MONTHS.items())}); MONTHS['sept'] = 9
_MONTH = r'(%s)\.?' % '|'.join(sorted(MONTHS, key=len, reverse=True))
DATE_FORMS = [
    (re.compile(r'\b(\d{4})-(\d{1,2})-(\d{1,2})\b'), ('y', 'm', 'd')),
    (re.compile(r'\b' + _MONTH + r'\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})\b', re.I), ('mon', 'd', 'y')),
    (re.compile(r'\b(\d{1,2})(?:st|nd|rd|th)?(?:\s+day)?(?:\s+of)?\s+' + _MONTH + r',?\s+(\d{4})\b', re.I), ('d', 'mon', 'y')),
]
UNITS = 'zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen'.split()
TENS = {'twenty': 20, 'thirty': 30, 'forty': 40, 'fifty': 50, 'sixty': 60, 'seventy': 70, 'eighty': 80, 'ninety': 90}
WORD_NUMBER = re.compile(r'\b(%s)(?:[\s-]+(%s))?\b|\b(%s)\b' % ('|'.join(TENS), '|'.join(UNITS[1:10]), '|'.join(UNITS)), re.I)


def numbers(text):
    return set(re.findall(r'\b\d+(?:[./-]\d+)*\b', text))


def dates(text):
    """[(literal, ISO date)] for unambiguous written dates. Numeric day/month forms such as 03/04/27 are left
    as plain numbers because their order is ambiguous."""
    found = []
    for pattern, order in DATE_FORMS:
        for m in pattern.finditer(text):
            parts = dict(zip(order, m.groups()))
            month = MONTHS[parts['mon'].lower()] if 'mon' in parts else int(parts['m'])
            try:
                found.append((m.group(), date(int(parts['y']), month, int(parts['d'])).isoformat(), m.span()))
            except ValueError:
                continue
    return found


def _word_numbers(text):
    out = set()
    for m in WORD_NUMBER.finditer(text):
        if m.group(3):
            out.add(str(UNITS.index(m.group(3).lower())))
        else:
            out.add(str(TENS[m.group(1).lower()] + (UNITS.index(m.group(2).lower()) if m.group(2) else 0)))
    return out


DURATION = re.compile(r'\b(?:(\d{1,3})|(%s)(?:[\s-]+(%s))?)(?:\s*\((\d{1,3})\))?\s+(?:calendar\s+)?(day|month|year)s?\b'
                      % ('|'.join([*TENS, *UNITS]), '|'.join(UNITS[1:10])), re.I)


def _add(start, n, unit):
    if unit == 'day':
        return date.fromordinal(start.toordinal() + n)
    months = start.month - 1 + n * (12 if unit == 'year' else 1)
    year, month = start.year + months // 12, months % 12 + 1
    for day in (start.day, 30, 29, 28):  # clamp the 31st to the end of a shorter month
        try:
            return date(year, month, day)
        except ValueError:
            continue


def durations(text):
    """{(n, unit)} for periods such as "thirty (30) days", "18 months", "two years". Business days are excluded:
    they need a holiday calendar."""
    found = set()
    for m in DURATION.finditer(text):
        if re.search(r'business\s+$', text[max(0, m.start() - 10):m.start()], re.I):
            continue
        if m.group(4):
            n = int(m.group(4))
        elif m.group(1):
            n = int(m.group(1))
        else:
            word = m.group(2).lower()
            n = TENS[word] + (UNITS.index(m.group(3).lower()) if m.group(3) else 0) if word in TENS else UNITS.index(word)
        if n:
            found.add((n, m.group(5).lower()))
    return found


def computed_dates(evidence):
    """ISO dates that are a stated period after a stated date, both written in the evidence. Only addition: a
    claim must not move a date backwards from what the text says."""
    starts = {date.fromisoformat(iso) for _, iso, _ in dates(evidence)}
    return {_add(d, n, unit).isoformat() for d in starts for n, unit in durations(evidence)}


def check_literals(claim, evidence):
    """(missing, computed): numbers and dates written in the claim that the evidence does not state, and the
    claim's dates that are only a simple computation from a period and a start date in the evidence.

    A date matches the same calendar date written in another unambiguous form ("March 2, 2026" and 2026-03-02),
    or, as before, when all of its digit groups appear in the evidence. A number matches the same digits or the
    same number written as a word ("eighteen months")."""
    evidence_numbers = numbers(evidence) | _word_numbers(evidence)
    evidence_dates = {iso for _, iso, _ in dates(evidence)}
    missing, computed, spans, derivable = [], [], [], None
    for literal, iso, span in dates(claim):
        if any(a < span[1] and span[0] < b for a, b in spans):
            continue
        spans.append(span)
        if iso in evidence_dates or numbers(literal) <= evidence_numbers:
            continue
        derivable = computed_dates(evidence) if derivable is None else derivable
        (computed if iso in derivable else missing).append(literal)
    masked = ''.join(' ' if any(a <= i < b for a, b in spans) else ch for i, ch in enumerate(claim))
    missing += sorted(n for n in numbers(masked) if n not in evidence_numbers)
    return missing, computed


def unsupported_literals(claim, evidence):
    """Numbers and dates in the claim that the evidence neither states nor determines by a simple computation."""
    return check_literals(claim, evidence)[0]
