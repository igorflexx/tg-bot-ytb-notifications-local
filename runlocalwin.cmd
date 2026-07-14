@echo off
setlocal EnableExtensions
cd /d "%~dp0"

if not exist "bot_token.txt" (
  echo [ERROR] bot_token.txt not found.
  exit /b 1
)

set "TOKEN_CONTENT="
for /f "usebackq delims=" %%I in (`powershell -NoProfile -Command "(Get-Content 'bot_token.txt' -Raw).Trim()"`) do set "TOKEN_CONTENT=%%I"

if not defined TOKEN_CONTENT (
  echo [ERROR] Open bot_token.txt and paste your Telegram bot token.
  exit /b 1
)

if /i "%TOKEN_CONTENT%"=="PASTE_YOUR_BOT_TOKEN_HERE" (
  echo [ERROR] Open bot_token.txt and paste your Telegram bot token.
  exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
  echo Creating virtual environment...
  where py >nul 2>nul
  if not errorlevel 1 (
    py -3 -m venv .venv || exit /b 1
  ) else (
    python -m venv .venv || exit /b 1
  )
)

echo Upgrading pip...
".venv\Scripts\python.exe" -m pip install --upgrade pip >nul || exit /b 1

echo Installing dependencies...
".venv\Scripts\python.exe" -m pip install -r requirements.txt || exit /b 1

echo.
echo Starting Telegram bot...
echo.
".venv\Scripts\python.exe" bot_notifications.py
exit /b %errorlevel%
