@echo off
REM Deriv Trading Bot - Windows start script

cd /d "%~dp0"

IF NOT EXIST ".env" (
    echo No .env file found. Copy .env.example to .env and set your DERIV_API_TOKEN.
    pause
    exit /b 1
)

IF NOT EXIST ".venv\Scripts\python.exe" (
    echo Creating virtual environment...
    python -m venv .venv
)

echo Installing dependencies...
.venv\Scripts\pip install -q -r requirements.txt

echo.
echo Starting Deriv Trading Bot...
echo Press Ctrl+C to stop.
echo.

cd ..
trading_bot\.venv\Scripts\python -m trading_bot %*
pause
