"""Start Clausetrail; run from the repository root (the launchers do this for you).

  python scripts/start.py            fictional-data demo (data in .local/)
  python scripts/start.py --open     same, and open the browser when the server is ready
  python scripts/start.py --private  private local copy for real documents on this computer only
                                     (separate data folder .local-private/, never committed, never deploy)

Settings are read from the environment and from a .env file in the repository root (see .env.example).
"""
import os
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path


def load_env(path=Path('.env')):
    """KEY=value lines; existing environment variables win. Values are never printed."""
    if not path.exists():
        return
    for line in path.read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        key, value = line.split('=', 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def build_frontend():
    built = Path('frontend/dist/index.html')
    if not shutil.which('npm'):
        if built.exists():
            return  # use the committed build; Node is only needed to change the interface
        sys.exit('The interface is not built and Node.js is not installed. Install Node 22+ or download a release.')
    sources = [p for p in [Path('frontend/package-lock.json'), Path('frontend/index.html'), *Path('frontend/src').rglob('*')] if p.is_file()]
    stale = not built.exists() or max(p.stat().st_mtime for p in sources) > built.stat().st_mtime
    if not stale or os.getenv('SKIP_FRONTEND_BUILD') == 'true':
        return
    lock = Path('frontend/package-lock.json')
    if not Path('frontend/node_modules').exists() or not built.exists() or lock.stat().st_mtime > built.stat().st_mtime:
        subprocess.run(['npm', 'ci', '--prefix', 'frontend'], check=True)
    subprocess.run(['npm', 'run', 'build', '--prefix', 'frontend'], check=True)


def open_when_ready(url):
    for _ in range(120):
        try:
            urllib.request.urlopen(url + '/api/auth', timeout=1)
            webbrowser.open(url); return
        except Exception:
            time.sleep(0.5)


load_env()
build_frontend()
os.environ.setdefault('DEMO_MODE', 'true')
if '--private' in sys.argv:
    os.environ['PRIVATE_LOCAL'] = 'true'
    os.environ.setdefault('DATA_DIR', '.local-private')
    print('PRIVATE LOCAL COPY: real documents stay in .local-private/ on this computer. Do not share or deploy.')
os.environ.setdefault('APP_ORIGIN', 'http://localhost:8000')
url = os.environ['APP_ORIGIN']
answers = 'Claude (fictional demo)' if os.getenv('QA_PROVIDER', '').lower() == 'claude' and os.getenv('ANTHROPIC_API_KEY') and '--private' not in sys.argv \
    else ('local model ' + (os.getenv('QA_MODEL') or os.getenv('OLLAMA_MODEL'))) if (os.getenv('QA_MODEL') or os.getenv('OLLAMA_MODEL')) else 'evidence search only (no AI model configured)'
print(f'\n  Clausetrail is running at {url}\n  Answers: {answers}\n  Close this window or press Ctrl+C to stop.\n')
if '--open' in sys.argv:
    threading.Thread(target=open_when_ready, args=(url,), daemon=True).start()
subprocess.run([sys.executable, '-m', 'uvicorn', 'backend.api.main:app', '--host', '127.0.0.1', '--port', '8000', '--log-level', 'warning'], check=True)
