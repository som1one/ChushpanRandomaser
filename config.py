"""Конфигурация бота. Загружает переменные из .env файла."""
import os
from dotenv import load_dotenv

load_dotenv()

# Telegram Bot API Token
TOKEN = os.getenv("BOT_TOKEN", "")

# URL подключения к БД
db_url = os.getenv("DATABASE_URL", "sqlite:///bot.db")

# ID администратора (опционально)
ADMIN_ID = os.getenv("ADMIN_ID", "")
