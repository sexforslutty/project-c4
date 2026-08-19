#!/usr/bin/env bash
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$APP_DIR"

if [ ! -f .env ]; then
  cp .env.example .env
fi

read -p "Введите username руководителя [manager]: " MANAGER_USERNAME
MANAGER_USERNAME="${MANAGER_USERNAME:-manager}"
read -sp "Введите пароль руководителя [manager123]: " MANAGER_PASSWORD
echo
MANAGER_PASSWORD="${MANAGER_PASSWORD:-manager123}"
read -p "Введите Telegram ID руководителя (оставьте пусто если нет): " MANAGER_TELEGRAM_ID
read -p "Введите токен Telegram бота: " TELEGRAM_BOT_TOKEN
read -p "Введите username Telegram бота без @: " TELEGRAM_BOT_USERNAME
read -p "Введите порт приложения [8000]: " APP_PORT
APP_PORT="${APP_PORT:-8000}"

export MANAGER_USERNAME MANAGER_PASSWORD MANAGER_TELEGRAM_ID TELEGRAM_BOT_TOKEN TELEGRAM_BOT_USERNAME APP_PORT

python3 - <<'PY'
import os
from pathlib import Path

app_dir = Path('.')
env_path = app_dir / '.env'
config = {}
if env_path.exists():
    for line in env_path.read_text(encoding='utf-8').splitlines():
        if not line or line.strip().startswith('#') or '=' not in line:
            continue
        key, value = line.split('=', 1)
        config[key.strip()] = value.strip()

config['APP_SECRET_KEY'] = config.get('APP_SECRET_KEY') or os.urandom(32).hex()
config['DATABASE_URL'] = config.get('DATABASE_URL') or 'sqlite:///./club.db'
config['HOST'] = config.get('HOST') or '0.0.0.0'
config['PORT'] = os.environ.get('APP_PORT', config.get('PORT', '8000'))
config['MANAGER_USERNAME'] = os.environ.get('MANAGER_USERNAME', config.get('MANAGER_USERNAME', 'manager'))
config['MANAGER_PASSWORD'] = os.environ.get('MANAGER_PASSWORD', config.get('MANAGER_PASSWORD', 'manager123'))
config['MANAGER_TELEGRAM_ID'] = os.environ.get('MANAGER_TELEGRAM_ID', config.get('MANAGER_TELEGRAM_ID', ''))
config['TELEGRAM_BOT_TOKEN'] = os.environ.get('TELEGRAM_BOT_TOKEN', config.get('TELEGRAM_BOT_TOKEN', ''))
config['TELEGRAM_BOT_USERNAME'] = os.environ.get('TELEGRAM_BOT_USERNAME', config.get('TELEGRAM_BOT_USERNAME', ''))

with env_path.open('w', encoding='utf-8') as fh:
    for key in ['APP_SECRET_KEY', 'DATABASE_URL', 'HOST', 'PORT', 'MANAGER_USERNAME', 'MANAGER_PASSWORD', 'MANAGER_TELEGRAM_ID', 'TELEGRAM_BOT_TOKEN', 'TELEGRAM_BOT_USERNAME']:
        fh.write(f'{key}={config.get(key, "")}\n')
PY

if [ -f club.db ]; then
  rm -f club.db
fi

python3 -m venv .venv
. .venv/bin/activate
pip install --upgrade pip >/dev/null
pip install -r requirements.txt >/dev/null

set -a
. ./.env
set +a

python - <<'PY'
from app.main import startup_event
startup_event()
PY

if command -v systemctl >/dev/null 2>&1; then
  cat > /etc/systemd/system/club-shift-manager.service <<EOF
[Unit]
Description=Club Shift Manager
After=network.target

[Service]
Type=simple
WorkingDirectory=$(pwd)
ExecStart=$(pwd)/.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port ${APP_PORT}
Restart=always
RestartSec=5
EnvironmentFile=$(pwd)/.env

[Install]
WantedBy=multi-user.target
EOF

  systemctl daemon-reload
  systemctl enable club-shift-manager.service
  systemctl restart club-shift-manager.service
else
  nohup ./.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port "${APP_PORT}" >/tmp/club-shift-manager.log 2>&1 &
fi

echo "Установка завершена."
echo "Логин руководителя: ${MANAGER_USERNAME}"
echo "Пароль руководителя: ${MANAGER_PASSWORD}"
echo "Сайт: http://localhost:${APP_PORT}"
