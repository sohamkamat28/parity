@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Run setup.bat once before starting Parity.
  pause
  exit /b 1
)
set "PYTHONUTF8=1"
".venv\Scripts\python.exe" "%~dp0run.py" %*
set "PARITY_START_EXIT=%ERRORLEVEL%"
if not "%PARITY_START_EXIT%"=="0" pause
exit /b %PARITY_START_EXIT%
