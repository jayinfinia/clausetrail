"""Start the local demo; run from repository root after installing requirements.

  python scripts/start.py            fictional-data demo (data in .local/)
  python scripts/start.py --private  private local copy for real documents on this computer only
                                     (separate data folder .local-private/, never committed, never deploy)
"""
import os
import subprocess
import sys
from pathlib import Path

built=Path('frontend/dist/index.html')
sources=[p for p in [Path('frontend/package-lock.json'),Path('frontend/index.html'),*Path('frontend/src').rglob('*')] if p.is_file()]
if not built.exists() or max(p.stat().st_mtime for p in sources)>built.stat().st_mtime:
    # First run, or the interface changed since the last build (for example after switching branches).
    lock=Path('frontend/package-lock.json')
    if not built.exists() or not Path('frontend/node_modules').exists() or lock.stat().st_mtime>built.stat().st_mtime:
        subprocess.run(['npm','ci','--prefix','frontend'],check=True)
    subprocess.run(['npm','run','build','--prefix','frontend'],check=True)
os.environ.setdefault('DEMO_MODE','true')
if '--private' in sys.argv:
    os.environ['PRIVATE_LOCAL']='true'
    os.environ.setdefault('DATA_DIR','.local-private')
    print('PRIVATE LOCAL COPY: real documents stay in .local-private/ on this computer. Do not share or deploy.')
os.environ.setdefault('APP_ORIGIN','http://localhost:8000')
print('Open '+os.environ['APP_ORIGIN']+' in your browser.')
subprocess.run([sys.executable,'-m','uvicorn','backend.api.main:app','--host','127.0.0.1','--port','8000'],check=True)
