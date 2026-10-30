@echo off
chcp 65001 >nul
cd /d "%~dp0"
where py >nul 2>&1
if %errorlevel%==0 (set "PY=py -3") else (set "PY=python")
%PY% -m venv .venv
if errorlevel 1 (echo Python 3.11+ is required & pause & exit /b 1)
".venv\Scripts\python.exe" -m pip install --upgrade pip
".venv\Scripts\python.exe" -m pip install --upgrade -r requirements.txt
if errorlevel 1 (echo Installation failed & pause & exit /b 1)
echo Ready. Install FFmpeg separately for MP3 and HD merges.
pause
