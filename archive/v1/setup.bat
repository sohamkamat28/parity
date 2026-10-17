@echo off
setlocal
cd /d "%~dp0"
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup.ps1"
set "PARITY_SETUP_EXIT=%ERRORLEVEL%"
if not "%PARITY_SETUP_EXIT%"=="0" echo Setup did not complete. Review the error above and retry.
pause
exit /b %PARITY_SETUP_EXIT%
