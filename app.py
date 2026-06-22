"""Инициализация бота и базы данных."""
import telebot
import config
from base import DataBase

bot = telebot.TeleBot(config.TOKEN)

# Экземпляры DataBase для разных модулей
middleware_base = DataBase()
post_base = DataBase()
end_base = DataBase()
tool_base = DataBase()
