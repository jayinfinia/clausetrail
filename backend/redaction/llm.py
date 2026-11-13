"""Local Llama (Ollama) detector for confidential values. Loopback only, no cloud fallback.

Model choice: REDACT_MODEL, else OLLAMA_MODEL / QA_MODEL, else the first installed model
whose name contains "llama". Text never leaves this computer and is never logged.
"""
import json
import os
import urllib.request
from urllib.parse import urlparse

PROMPT = """You find confidential values in business documents so they can be redacted.
Return JSON: {"items":[{"text":"<exact text copied from the document>","category":"<CATEGORY>"}]}
Only use these categories: %s
GOV_ID = social security, taxpayer, EIN/TIN or passport/driver licence numbers.
FIN_ACCOUNT = bank account, routing, IBAN or card numbers.
DOB = a person's date of birth.
PERSON = names of individual people (not companies, universities or job titles).
EMAIL, PHONE, ADDRESS = a person's or company's email, phone or street address.
Copy each value exactly as written. Do not include labels like "Name:". Do not include
company names, agreement dates, dollar amounts or unit counts. If nothing qualifies return {"items":[]}."""

SCHEMA = {'type': 'object', 'properties': {'items': {'type': 'array', 'items': {'type': 'object', 'properties': {
    'text': {'type': 'string'}, 'category': {'type': 'string'}}, 'required': ['text', 'category']}}}, 'required': ['items']}


class Unavailable(Exception):
    pass


def base_url():
    url = os.getenv('OLLAMA_URL', 'http://127.0.0.1:11434')
    p = urlparse(url)
    if p.scheme != 'http' or p.hostname not in ('127.0.0.1', 'localhost', '::1', 'ollama') or p.username or p.query or p.path not in ('', '/'):
        raise Unavailable('Only a local Ollama endpoint is allowed')
    return url.rstrip('/')


def _call(path, body=None, timeout=5):
    req = urllib.request.Request(base_url() + path, data=json.dumps(body).encode() if body is not None else None,
                                 headers={'Content-Type': 'application/json'}, method='POST' if body is not None else 'GET')
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))  # never route through a proxy
    with opener.open(req, timeout=timeout) as r:
        return json.loads(r.read(2_000_000))


def pick_model():
    wanted = os.getenv('REDACT_MODEL') or os.getenv('OLLAMA_MODEL') or os.getenv('QA_MODEL')
    try:
        names = [m.get('name', '') for m in _call('/api/tags').get('models', [])]
    except Exception:
        raise Unavailable('Ollama is not running on this computer')
    if wanted:
        if wanted in names or wanted + ':latest' in names:
            return wanted
        raise Unavailable(f'Model {wanted} is not installed; run: ollama pull {wanted}')
    llamas = [n for n in names if 'llama' in n.lower() and 'cloud' not in n.lower()]
    if not llamas:
        raise Unavailable('No local Llama model installed; run: ollama pull llama3.1:8b')
    return sorted(llamas, key=lambda n: ('3.1' not in n, '8b' not in n, n))[0]


def status():
    try:
        return {'ready': True, 'model': pick_model(), 'reason': None}
    except Unavailable as exc:
        return {'ready': False, 'model': None, 'reason': str(exc)}


def chunks(text, size=3000, overlap=200):
    i = 0
    while i < len(text):
        yield text[i:i + size]
        i += size - overlap


def detector(model=None):
    """Return a callable(text, categories) -> [(value, category)] bound to one local model."""
    model = model or pick_model()
    if 'cloud' in model.lower():
        raise Unavailable('Cloud models are not allowed')

    def run(text, categories):
        found = []
        for part in chunks(text):
            body = {'model': model, 'stream': False, 'format': SCHEMA, 'keep_alive': '10m',
                    'options': {'temperature': 0, 'num_ctx': 8192, 'num_predict': 1200},
                    'messages': [{'role': 'system', 'content': PROMPT % ', '.join(categories)},
                                 {'role': 'user', 'content': part}]}
            try:
                reply = _call('/api/chat', body, timeout=180)
                items = json.loads(reply['message']['content']).get('items', [])
            except Exception:
                raise Unavailable('the local model did not return a usable answer')
            found += [(str(i.get('text', '')), str(i.get('category', '')).upper()) for i in items if isinstance(i, dict)]
        return found
    run.model = model
    return run
