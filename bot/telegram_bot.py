import os

from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

from app.database import SessionLocal
from app.models import Employee


def get_bot_token() -> str:
    return os.getenv('TELEGRAM_BOT_TOKEN', '').strip()


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text('Привет! Бот клуба запущен. Используйте /status, /who, /open, /close.')


async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text('Статус: бот запущен и готов к работе.')


async def who(update: Update, context: ContextTypes.DEFAULT_TYPE):
    db = SessionLocal()
    try:
        employees = db.query(Employee).all()
        active = [e.full_name for e in employees if e.role and e.role.lower() == 'staff']
        await update.message.reply_text('Сотрудники: ' + ', '.join(active) if active else 'Сотрудников нет.')
    finally:
        db.close()


async def open_shift(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text('Смена открыта.')


async def close_shift(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text('Смена закрыта.')


def main():
    token = get_bot_token()
    if not token:
        raise RuntimeError('TELEGRAM_BOT_TOKEN is not configured.')
    app = ApplicationBuilder().token(token).build()
    app.add_handler(CommandHandler('start', start))
    app.add_handler(CommandHandler('status', status))
    app.add_handler(CommandHandler('who', who))
    app.add_handler(CommandHandler('open', open_shift))
    app.add_handler(CommandHandler('close', close_shift))
    app.run_polling()


if __name__ == '__main__':
    main()
