"""Утилиты: проверка языка, создание inline-клавиатур."""
import json
import telebot
import models
from app import tool_base

# Загрузка файлов локализации
with open("RU.json", encoding="utf-8") as f:
    ru_bot_text = json.load(f)

with open("ENG.json", encoding="utf-8") as f:
    eng_bot_text = json.load(f)


def language_check(user_id):
    """Определяет язык пользователя и возвращает словарь текстов."""
    language = tool_base.get_one(models.User, user_id=str(user_id))
    if language is None:
        return (False, ru_bot_text)
    else:
        if language.language == "RU":
            return (True, ru_bot_text)
        else:
            return (True, eng_bot_text)


def create_inlineKeyboard(key, row=0):
    """Создаёт inline-клавиатуру из словаря {текст: callback_data}."""
    keyboard = telebot.types.InlineKeyboardMarkup()
    key_list = []
    count = 0
    for i in key:
        key_list.append(telebot.types.InlineKeyboardButton(
            text=i, callback_data=key.get(i)))
        count += 1
        if count >= row and row > 0:
            keyboard.add(*[btn for btn in key_list])
            key_list = []
            count = 0
    if key_list:
        keyboard.add(*[btn for btn in key_list])
    return keyboard
