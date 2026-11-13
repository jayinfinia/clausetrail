import os
from pathlib import Path

DATA = Path(os.getenv('DATA_DIR', '.local')).resolve()
DATABASE_URL = os.getenv('DATABASE_URL', f'sqlite:///{DATA}/clausetrail.db')
DEMO_MODE = os.getenv('DEMO_MODE', 'true').lower() == 'true'
SECRET = os.getenv('SESSION_SECRET', '')
ORIGIN = os.getenv('APP_ORIGIN', 'http://localhost:8000')
MAX_BYTES = 25 * 1024 * 1024
FIELDS = ('agreement_type', 'counterparty', 'owner', 'effective_date', 'expiration_date', 'notice_days', 'confidentiality_end', 'return_date', 'permitted_use', 'renewal', 'parent_reference')
DATE_FIELDS = {'effective_date', 'expiration_date', 'confidentiality_end', 'return_date'}

def initialize():
    global SECRET
    DATA.mkdir(parents=True, exist_ok=True)
    for folder in ('originals', 'tmp'):
        (DATA / folder).mkdir(exist_ok=True)
    if not DEMO_MODE:
        raise RuntimeError('Production mode is intentionally blocked: this build uses demo sign-in. See docs/PRODUCTION.md for what a deployment needs.')
    if not SECRET:
        path = DATA / 'session.key'
        if not path.exists():
            import secrets
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            with os.fdopen(fd, 'w') as out:
                out.write(secrets.token_hex(32))
        SECRET = path.read_text().strip()
