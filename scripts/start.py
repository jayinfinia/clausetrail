"""Start Clausetrail; run from the repository root (the launchers do this for you).

  python scripts/start.py            fictional-data demo (data in .local/)
  python scripts/start.py --open     same, and open the browser when the server is ready
  python scripts/start.py --private  private local copy for real documents on this computer only
                                     (separate data folder .local-private/, never committed, never deploy)

Settings are read from the environment and from a .env file in the repository root (see .env.example).
"""
import os
import shutil
import socket
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
    if not stale or os.getenv('SKIP_FRONTEND_BUILD') == 'true' or (built.exists() and not Path('frontend/node_modules').exists()):
        # Without node_modules this is not a development checkout: use the committed build (file times from a
        # clone or unzip are not a reliable staleness signal). Developers with node_modules get automatic rebuilds.
        return
    lock = Path('frontend/package-lock.json')
    if not Path('frontend/node_modules').exists() or not built.exists() or lock.stat().st_mtime > built.stat().st_mtime:
        subprocess.run(['npm', 'ci', '--prefix', 'frontend'], check=True)
    subprocess.run(['npm', 'run', 'build', '--prefix', 'frontend'], check=True)


def free_port(start=8000, tries=20):
    """The first port from start that nothing is listening on, so a second copy never fails to start."""
    for port in range(start, start + tries):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(('127.0.0.1', port)); return port
            except OSError:
                continue
    sys.exit(f'Ports {start} to {start + tries - 1} are all in use. Close other copies of Clausetrail and try again.')


def open_when_ready(url):
    for _ in range(120):
        try:
            urllib.request.urlopen(url + '/api/auth', timeout=1)
            webbrowser.open(url); return
        except Exception:
            time.sleep(0.5)


def main():
    load_env()
    build_frontend()
    if not Path('Sample files').exists():
        try:
            sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
            from scripts.make_sample_files import make
            make('Sample files')
            print('Created the "Sample files" folder: fictional Word, PDF, scanned PDF and Excel files to drag into the app.')
        except Exception as exc:  # samples are a convenience; never block startup
            print(f'Could not create sample files ({type(exc).__name__}).')
    os.environ.setdefault('DEMO_MODE', 'true')
    if '--private' in sys.argv:
        os.environ['PRIVATE_LOCAL'] = 'true'
        os.environ.setdefault('DATA_DIR', '.local-private')
        print('PRIVATE LOCAL COPY: real documents stay in .local-private/ on this computer. Do not share or deploy.')
    port = int(os.getenv('PORT') or free_port())
    os.environ.setdefault('APP_ORIGIN', f'http://localhost:{port}')
    url = os.environ['APP_ORIGIN']
    answers = 'Claude (fictional demo)' if os.getenv('QA_PROVIDER', '').lower() == 'claude' and os.getenv('ANTHROPIC_API_KEY') and '--private' not in sys.argv \
        else ('local model ' + (os.getenv('QA_MODEL') or os.getenv('OLLAMA_MODEL'))) if (os.getenv('QA_MODEL') or os.getenv('OLLAMA_MODEL')) else 'evidence search only (no AI model configured)'
    print(f'\n  Clausetrail is running at {url}\n  Answers: {answers}\n  Close this window or press Ctrl+C to stop.\n')
    if '--open' in sys.argv:
        threading.Thread(target=open_when_ready, args=(url,), daemon=True).start()
    subprocess.run([sys.executable, '-m', 'uvicorn', 'backend.api.main:app', '--host', '127.0.0.1', '--port', str(port), '--log-level', 'warning'], check=True)


if __name__ == '__main__':
    main()
