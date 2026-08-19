# Club Shift Manager

Simple Python app for a 24/7 computer club to track staff shifts, calculate payroll, and provide manager/employee access through the web and Telegram.

## Features

- Manager dashboard with current staff on shift
- Employee shift check-in/check-out
- Per-employee payroll reports and payouts
- Telegram bot scaffold and Telegram login support
- Username/password authentication for staff and manager
- SQLite for local development and easy setup

## Local startup

1. Create a virtual environment
   ```bash
   python -m venv .venv
   . .venv/bin/activate
   ```
2. Install dependencies
   ```bash
   pip install -r requirements.txt
   ```
3. Configure environment
   ```bash
   cp .env.example .env
   ```
   Update the values in `.env` before starting the app.
4. Run the app
   ```bash
   uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
   ```
5. Open the browser at `http://localhost:8000`.

## Default login

Default local demo accounts are created automatically from `.env`: manager and staff accounts. The app seeds a manager and sample employees if the database is empty.

## Install script

For a fresh Linux machine, run:

```bash
bash install.sh
```

The installer creates a `.env` file, resets the local database, creates a manager account from prompts, and starts the app as a background service.

## Environment variables

- `APP_SECRET_KEY` — app session secret
- `DATABASE_URL` — SQLite or PostgreSQL URL
- `HOST` and `PORT` — web server bind
- `MANAGER_USERNAME` and `MANAGER_PASSWORD` — manager login
- `MANAGER_TELEGRAM_ID` — optional Telegram ID for the manager
- `TELEGRAM_BOT_TOKEN` — Telegram bot token
- `TELEGRAM_BOT_USERNAME` — Telegram bot username without the leading `@`

## Security notes

- Never commit real secrets into the repo.
- Keep `.env` local or on the server only.
- For public Telegram login, a real domain and valid HTTPS are required.
