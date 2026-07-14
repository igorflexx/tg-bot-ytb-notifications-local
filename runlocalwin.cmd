@echo off
setlocal EnableExtensions
title tg-bot-ytb-notifications-local launcher

call :main
set "EXIT_CODE=%errorlevel%"
if not "%EXIT_CODE%"=="0" (
  echo.
  echo [ERROR] Script finished with code %EXIT_CODE%.
  echo Press any key to close this window.
  pause >nul
)
exit /b %EXIT_CODE%

:main
cd /d "%~dp0"

if not exist "bot_token.txt" (
  >"bot_token.txt" echo PASTE_YOUR_BOT_TOKEN_HERE
  echo Created bot_token.txt template
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

echo Installing dependencies...
call :install_requirements || exit /b 1

echo.
echo Starting Telegram bot...
echo.
".venv\Scripts\python.exe" bot_notifications.py
exit /b %errorlevel%

:install_requirements
set "NO_PROXY=*"
set "no_proxy=*"
set "ALL_PROXY="
set "all_proxy="
set "HTTP_PROXY="
set "HTTPS_PROXY="
set "http_proxy="
set "https_proxy="
set "PIP_DISABLE_PIP_VERSION_CHECK=1"
".venv\Scripts\python.exe" -m pip install -r requirements.txt
exit /b %errorlevel%
