#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

if [ ! -f "bot_token.txt" ]; then
  echo "❌ Файл bot_token.txt не найден."
  exit 1
fi

TOKEN_CONTENT="$(tr -d '\r' < bot_token.txt | xargs)"
if [ -z "$TOKEN_CONTENT" ] || [ "$TOKEN_CONTENT" = "PASTE_YOUR_BOT_TOKEN_HERE" ]; then
  echo "❌ Открой bot_token.txt и вставь туда свой токен Telegram-бота."
  exit 1
fi

if [ ! -d ".venv" ]; then
  echo "→ Создаю виртуальное окружение"
  python3 -m venv .venv
fi

echo "→ Обновляю pip"
.venv/bin/python -m pip install --upgrade pip >/dev/null

echo "→ Устанавливаю зависимости"
.venv/bin/pip install -r requirements.txt

echo
echo "▶ Запускаю Telegram-бота"
echo

trap 'echo; echo "→ Бот остановлен."; exit 0' INT TERM

.venv/bin/python bot_notifications.py
