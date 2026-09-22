@echo off
chcp 65001 >nul
set "LOG_FILE=%~dp0..\logs\autostart-backend.log"
cd /d "%~dp0..\ekodez-core\backend"
if errorlevel 1 exit /b 1
".venv\Scripts\python.exe" -m scripts.run_backend --instance-root "%CD%" >> "%LOG_FILE%" 2>&1
exit /b %ERRORLEVEL%
