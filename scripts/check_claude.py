"""Check the Claude setup step by step and print Anthropic's reason for any failure.

    .venv/bin/python scripts/check_claude.py

Reads ANTHROPIC_API_KEY (and optional CLAUDE_TAG_MODEL / CLAUDE_QA_MODEL) from the environment or .env.
Sends only tiny fictional text. Never prints the key.
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.chdir(Path(__file__).resolve().parents[1])
from scripts.start import load_env  # noqa: E402  (start.py only runs its server under __main__)

load_env()
import httpx  # noqa: E402

from backend import tagging  # noqa: E402
from backend.services import qa_provider  # noqa: E402
from backend.services.grounded_qa import Draft  # noqa: E402

key = os.getenv('ANTHROPIC_API_KEY', '')
print(f"Key: {'set, starts with ' + key[:10] + '...' if key else 'NOT SET'}  ({len(key)} characters)")
if key and not key.startswith('sk-ant-api'):
    print('  Note: API keys start with sk-ant-api. A different prefix (for example sk-ant-oat) is a sign-in token, not an API key.')
if key != key.strip() or '"' in key or "'" in key or ' ' in key:
    print('  Note: the key contains spaces or quotes; remove them in .env.')


def call(label, body):
    try:
        with httpx.Client(timeout=60, trust_env=False) as c:
            r = c.post('https://api.anthropic.com/v1/messages', json=body,
                       headers={'x-api-key': key.strip(), 'anthropic-version': '2023-06-01', 'content-type': 'application/json'})
    except httpx.HTTPError as exc:
        print(f'{label}: network error {type(exc).__name__}'); return False
    ok = r.status_code == 200
    print(f"{label}: {'OK' if ok else 'FAILED (' + str(r.status_code) + ')' + qa_provider.api_error_reason(r)}")
    return ok


tag_model = tagging.model()
qa_model = os.getenv('CLAUDE_QA_MODEL', 'claude-sonnet-5-5')
call(f'1. Plain message ({tag_model})', {'model': tag_model, 'max_tokens': 16, 'messages': [{'role': 'user', 'content': 'Say OK.'}]})
call('2. Tagging request', {'model': tag_model, 'max_tokens': 800, 'system': tagging.system_prompt(), 'tools': [tagging.TOOL],
                            'tool_choice': {'type': 'tool', 'name': 'record_agreement'},
                            'messages': [{'role': 'user', 'content': 'File name: x.txt\nFolder: (none)\n\nPASSAGES:\n[p1 | Line 1]\nAgreement type: CDA\n'}]})
call(f'3. Answer request ({qa_model})', {'model': qa_model, 'max_tokens': 400, 'temperature': 0, 'system': 'Return the structured response.',
                                         'tools': [{'name': 'respond', 'description': 'Return the structured response.',
                                                    'input_schema': qa_provider._inline_refs(Draft.model_json_schema())}],
                                         'tool_choice': {'type': 'tool', 'name': 'respond'},
                                         'messages': [{'role': 'user', 'content': '{"question": "test", "documents": []}'}]})
