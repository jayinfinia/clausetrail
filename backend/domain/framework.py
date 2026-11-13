"""Agreement labeling framework.

Pure functions only: relationship types and labels, standard file names and
folders, the "later of 5 years or end of relationship" end rule, agreement IDs,
and classification hints read from a folder path or an original file name.

The vocabulary (organization name, relationship types, owners, components, ID
prefix) comes from config/taxonomy.json, or the file named by TAXONOMY_FILE, so
the same engine can be pointed at any organization's labeling scheme.

Hints from folder paths and file names are *suggestions* for a reviewer. They
never become approved contractual facts on their own.
"""
import json
import os
import re
from datetime import date
from pathlib import Path

_DEFAULT_TAXONOMY = Path(__file__).resolve().parents[2] / 'config' / 'taxonomy.json'


def load_taxonomy(path=None):
    path = Path(path or os.getenv('TAXONOMY_FILE') or _DEFAULT_TAXONOMY)
    data = json.loads(path.read_text(encoding='utf-8'))
    types = tuple(data['relationship_types'])
    if UNCLASSIFIED not in types:
        types = (*types, UNCLASSIFIED)
    aliases = {k.casefold(): v for k, v in (data.get('folder_aliases') or {}).items()}
    for alias, target in aliases.items():
        if target not in types:
            raise ValueError(f'Folder alias {alias!r} points at unknown relationship type {target!r}')
    return {
        'organization': str(data.get('organization') or 'Your organization').strip(),
        'id_prefix': re.sub(r'[^A-Z0-9]', '', str(data.get('id_prefix') or 'AGR').upper()) or 'AGR',
        'relationship_types': types,
        'folder_aliases': aliases,
        'owners': tuple(data.get('owners') or ()),
        'components': tuple(data.get('components') or ()),
        'alert_roles': tuple(data.get('alert_roles') or ()),
    }


UNCLASSIFIED = 'Unclassified'
TAXONOMY = load_taxonomy()
ORGANIZATION = TAXONOMY['organization']
ID_PREFIX = TAXONOMY['id_prefix']
RELATIONSHIP_TYPES = TAXONOMY['relationship_types']
OWNERS = TAXONOMY['owners']
COMPONENTS = TAXONOMY['components']
ALERT_ROLES = TAXONOMY['alert_roles']
DIRECTIONS = ('Inbound', 'Outbound', 'Mutual')
STATUSES = ('Requested', 'Drafting', 'In review', 'Out for signature', 'Executed', 'Expired', 'Terminated')
IN_PROGRESS = ('Requested', 'Drafting', 'In review', 'Out for signature')
END_RULES = ('fixed', 'later5')

# Agreement kind -> (ID code, default primary type, default components)
KINDS = {
    'CDA': ('CDA', 'Confidential Disclosure Agreement', ['Confidentiality']),
    'MTA': ('MTA', 'Material Transfer Agreement', ['Material transfer']),
    'DUA': ('DUA', 'Data Use Agreement', ['Data use']),
    'SERVICES': ('SVC', 'Services Agreement', ['Services']),
    'COLLABORATION': ('COL', 'Collaboration Agreement', ['Research']),
    'CONSULTING': ('CON', 'Consulting Agreement', ['Consulting']),
    'GRANT': ('GRT', 'Grant Agreement', ['Grant']),
    'INVESTMENT': ('INV', 'Investment Agreement', ['Investment']),
    'AMENDMENT': ('AMD', 'Amendment', []),
    'OTHER': ('OTH', 'Agreement', []),
}

RESERVED = {'con', 'prn', 'aux', 'nul', 'desktop.ini', '.lock',
            *{f'com{i}' for i in range(1, 10)}, *{f'lpt{i}' for i in range(1, 10)}}


def relationship_from_label(text):
    """Accept a relationship type in its taxonomy form, a folder alias, or a simple plural."""
    if not text:
        return None
    t = str(text).strip()
    for rel in RELATIONSHIP_TYPES:
        if t.casefold() == rel.casefold():
            return rel
    key = re.sub(r'\s+', ' ', t).casefold()
    if key in TAXONOMY['folder_aliases']:
        return TAXONOMY['folder_aliases'][key]
    for rel in RELATIONSHIP_TYPES:
        if key == rel.casefold() + 's':
            return rel
    return None


def hints_from_path(relative_path):
    """Read classification hints from a folder path such as
    'Sample Set/Suppliers/Example Reagents Co/file.pdf'.

    Returns {'relationship', 'counterparty', 'folder'} with None where unknown.
    The counterparty is the first folder below the category folder.
    """
    parts = [p for p in str(relative_path or '').replace('\\', '/').split('/') if p and p not in ('.', '..')]
    folders = parts[:-1]
    rel, counterparty, index = None, None, None
    for i, name in enumerate(folders):
        found = relationship_from_label(name)
        if found:
            rel, index = found, i
    if index is not None:
        below = folders[index + 1:]
        counterparty = below[0] if below else None
    return {'relationship': rel, 'counterparty': counterparty, 'folder': '/'.join(folders) or None}


_KIND_PATTERNS = (
    ('AMENDMENT', r'\bamend(?:ment|ed)?\b'),
    ('MTA', r'\bmta\b|material transfer'),
    ('DUA', r'\bdua\b|data use'),
    ('GRANT', r'\bgrant\b|\baward\b'),
    ('INVESTMENT', r'operating agreement|subscription|\bsafe\b|convertible|investment'),
    ('CONSULTING', r'consult|advis'),
    ('SERVICES', r'\bmsa\b|\bsow\b|\blsa\b|services?\b|statement of work|quote|invoice'),
    ('COLLABORATION', r'collaborat|\bsra\b|research agreement'),
    ('CDA', r'\bcda\b|\bnda\b|confidential|non-?disclosure'),
)


def kind_from_name(filename):
    name = re.sub(r'[_\-]+', ' ', str(filename or '')).lower()
    for kind, pattern in _KIND_PATTERNS:
        if re.search(pattern, name):
            return kind
    return None


def _valid(y, m, d):
    try:
        return date(y, m, d)
    except ValueError:
        return None


def date_from_name(filename):
    """Find one date in a file name. Accepts YYYYMMDD, MM.DD.YY(YY), M-D-YYYY and MMDDYYYY.
    Returns an ISO date string or None. Ambiguous or impossible dates return None."""
    name = str(filename or '')
    found = []
    for m in re.finditer(r'(?<!\d)(20\d{2})(\d{2})(\d{2})(?!\d)', name):
        d = _valid(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        if d: found.append(d)
    if not found:
        for m in re.finditer(r'(?<!\d)(\d{1,2})[.\-/](\d{1,2})[.\-/](\d{2}|\d{4})(?!\d)', name):
            year = int(m.group(3)); year = year + 2000 if year < 100 else year
            d = _valid(year, int(m.group(1)), int(m.group(2)))
            if d: found.append(d)
    if not found:
        for m in re.finditer(r'(?<!\d)(\d{2})(\d{2})(20\d{2})(?!\d)', name):
            d = _valid(int(m.group(3)), int(m.group(1)), int(m.group(2)))
            if d: found.append(d)
    unique = sorted(set(found))
    return unique[0].isoformat() if len(unique) == 1 else None


def status_from_name(filename):
    name = str(filename or '').lower()
    if re.search(r'execut|fully signed|countersigned', name):
        return 'Executed'
    if re.search(r'\bsigned\b', name):
        return 'Out for signature'
    if re.search(r'draft|redline', name):
        return 'Drafting'
    return None


def suggest_labels(relative_path, filename=None):
    """Combine folder and file-name hints into suggested labels for a reviewer."""
    filename = filename or str(relative_path or '').replace('\\', '/').split('/')[-1]
    path = hints_from_path(relative_path)
    kind = kind_from_name(filename)
    rel = path['relationship']
    labels = {
        'rel': rel or UNCLASSIFIED,
        'kind': kind or 'OTHER',
        'primaryType': KINDS[kind or 'OTHER'][1],
        'components': list(KINDS[kind or 'OTHER'][2]),
        'status': status_from_name(filename),
        'eff': date_from_name(filename),
        'party': path['counterparty'],
        'sourceFolder': path['folder'],
        'owner': '',
        'dir': '',
        'endRule': 'fixed',
        'confirmed': False,
        'suggestedFrom': [s for s, ok in (('folder', rel), ('file name', kind or date_from_name(filename))) if ok],
    }
    labels['components'] = [c for c in labels['components'] if c in COMPONENTS]
    return labels


def clean_segment(text):
    """Make one file-name or folder segment safe for SharePoint, OneDrive and Windows."""
    s = re.sub(r'[\x00-\x1f\x7f]', ' ', str(text or ''))
    s = re.sub(r'\s*:\s*', ' - ', s)
    s = re.sub(r'[/\\|]', '-', s)
    s = s.replace('"', "'")
    s = re.sub(r'[<>*?#%]', '', s)
    s = re.sub(r'\s+', ' ', s)
    s = re.sub(r'\s*-\s*(?:-\s*)+', ' - ', s)
    s = re.sub(r'\s-\s', ' - ', s)
    s = s.strip(' .~-')
    if s.casefold() in RESERVED or s.casefold().startswith('_vti_'):
        s += '_'
    return s


def file_name(counterparty, primary_type, effective, status, extension=''):
    """'Counterparty - Organization - Primary type - YYYYMMDD - STATUS[.ext]' plus warnings."""
    warnings = []
    stamp = str(effective or '').replace('-', '')[:8]
    if not re.fullmatch(r'\d{8}', stamp):
        stamp = 'NODATE'; warnings.append('No effective date; file name uses NODATE.')
    parts = [clean_segment(counterparty) or 'UNKNOWN', clean_segment(ORGANIZATION), clean_segment(primary_type) or 'Agreement',
             stamp, clean_segment(status).upper() or 'UNKNOWN']
    name = ' - '.join(parts)
    ext = str(extension or '')
    if ext and not ext.startswith('.'):
        ext = '.' + ext
    name += ext.lower()
    if len(name) > 200:
        warnings.append('File name is over 200 characters.')
    return name, warnings


def folder_path(relationship, counterparty):
    return '/'.join(['Agreements', clean_segment(relationship or UNCLASSIFIED), clean_segment(counterparty) or 'UNKNOWN'])


def add_years(d, years):
    try:
        return d.replace(year=d.year + years)
    except ValueError:  # Feb 29 -> Feb 28
        return d.replace(year=d.year + years, day=28)


def _d(value):
    if value in (None, ''):
        return None
    return value if isinstance(value, date) else date.fromisoformat(str(value)[:10])


def effective_end(end_rule, effective=None, expiration=None, floor=None, relationship_end=None):
    """Return (end_date_or_None, floor_or_None).

    fixed:  ends on the expiration date.
    later5: open-ended (None) while the relationship is active; floor is the effective
            date plus 5 years unless given. Once the relationship ends, the end date is
            the later of the floor and the relationship end date.
    """
    if end_rule != 'later5':
        return _d(expiration), None
    floor_d = _d(floor) or (add_years(_d(effective), 5) if _d(effective) else None)
    rel_end = _d(relationship_end)
    if rel_end is None:
        return None, floor_d
    return (max(floor_d, rel_end) if floor_d else rel_end), floor_d


def reference_id(kind, year, existing_ids):
    code = KINDS.get(kind or 'OTHER', KINDS['OTHER'])[0]
    prefix = f'{ID_PREFIX}-{code}-{year}-'
    used = [int(i[len(prefix):]) for i in existing_ids if i and i.startswith(prefix) and i[len(prefix):].isdigit()]
    return f'{prefix}{(max(used) + 1 if used else 1):03d}'


LABEL_FIELDS = ('rel', 'owner', 'kind', 'primaryType', 'dir', 'status', 'components',
                'party', 'eff', 'endRule', 'floor', 'relEnd', 'waiting')


def validate_labels(current, changes):
    """Apply label changes and return the new label dict. Raises ValueError on bad input.
    An in-progress status is marked as waiting on the agreement's owner."""
    new = dict(current or {})
    for key, value in changes.items():
        if key not in LABEL_FIELDS:
            raise ValueError(f'Unknown label {key}')
        if key == 'rel':
            value = relationship_from_label(value)
            if not value: raise ValueError('Unknown relationship type')
        elif key == 'owner':
            value = (value or '').strip()
            if value and value not in OWNERS: raise ValueError('Unknown owner')
        elif key == 'kind':
            if value not in KINDS: raise ValueError('Unknown agreement kind')
        elif key == 'dir':
            if value and value not in DIRECTIONS: raise ValueError('Unknown direction')
        elif key == 'status':
            if value and value not in STATUSES: raise ValueError('Unknown status')
        elif key == 'components':
            if not isinstance(value, list) or any(c not in COMPONENTS for c in value): raise ValueError('Unknown component')
            value = [c for c in COMPONENTS if c in value]
        elif key == 'endRule':
            if value not in END_RULES: raise ValueError('Unknown end rule')
        elif key in ('eff', 'floor', 'relEnd'):
            value = _d(value).isoformat() if value else None
        elif isinstance(value, str):
            value = value.strip()[:200]
        new[key] = value
    if 'status' in changes:
        new['waiting'] = new.get('owner') or 'Agreement owner' if new.get('status') in IN_PROGRESS else None
    return new
