@echo off
rem Double-click to start Clausetrail on Windows.
cd /d "%~dp0"
set PY=
for %%v in (3.14 3.13 3.12) do if not defined PY (py -%%v -c "import sys" >nul 2>&1 && set PY=py -%%v)
if not defined PY (python -c "import sys; sys.exit(sys.version_info < (3, 12))" >nul 2>&1 && set PY=python)
if not defined PY (
  echo Clausetrail needs Python 3.12 or newer. Install it from https://www.python.org/downloads/ and double-click again.
  pause & exit /b 1
)
if not exist .venv\Scripts\python.exe (
  echo First run: setting up Clausetrail, about a minute...
  %PY% -m venv .venv || (pause & exit /b 1)
)
if not exist .venv\.installed (
  .venv\Scripts\python -m pip install -q --disable-pip-version-check -r backend\requirements.txt || (pause & exit /b 1)
  type nul > .venv\.installed
)
.venv\Scripts\python scripts\start.py --open %*
pause
