import telebot
import models
import config
from app import bot
from middleware import (
    rig_player, unrig_player, get_rigged_players,
    RigResult, end_draw_timer, select_winners,
    is_admin, is_super_admin
)
from app import middleware_base
from tool import language_check

# Запуск таймера завершения розыгрышей
end_draw_timer()

# Словарь для хранения состояний ожидания ввода
_waiting_for = {}


# ============================================ #
#                 /start                       #
# ============================================ #

@bot.message_handler(commands=['start'])
def handle_start(message):
    if message.chat.type != 'private':
        return

    user_id = str(message.chat.id)
    user_name = message.from_user.username or message.from_user.first_name

    # Регистрация пользователя если его нет
    if not middleware_base.get_one(models.User, user_id=user_id):
        middleware_base.new(models.User, user_id, user_name, "RU")

    admin_label = ""
    if is_super_admin(user_id):
        admin_label = " 👑 Главный админ"
    elif is_admin(user_id):
        admin_label = " 🛡 Админ"

    bot.send_message(
        message.chat.id,
        f"👋 Привет, {user_name}!{admin_label}\n\n"
        "🎲 Я — бот для розыгрышей с подкруткой.\n\n"
        "📋 <b>Команды:</b>\n"
        "/rig — Панель подкрутки\n"
        "/admin — Управление админами\n\n"
        "Создавайте розыгрыши, добавляйте участников — "
        "а потом подкручивайте победителей через /rig 😏",
        parse_mode='HTML'
    )


# ============================================ #
#          АДМИН-ПАНЕЛЬ ПОДКРУТКИ              #
# ============================================ #

@bot.message_handler(commands=['rig'])
def handle_rig_panel(message):
    """Открывает панель управления подкруткой (для админов)."""
    if message.chat.type != 'private':
        return

    admin_id = str(message.chat.id)

    # Проверка прав
    if not is_admin(admin_id):
        # Обычные пользователи видят только свои розыгрыши
        draws = middleware_base.select_all(models.Draw, user_id=admin_id)
    else:
        # Админы видят ВСЕ розыгрыши
        draws = middleware_base.select_all(models.Draw)

    if not draws:
        bot.send_message(message.chat.id, "📭 Нет активных розыгрышей.")
        return

    _send_draws_list(message.chat.id, draws, is_admin(admin_id))


# ============================================ #
#     ПАНЕЛЬ УПРАВЛЕНИЯ АДМИНАМИ               #
# ============================================ #

@bot.message_handler(commands=['admin'])
def handle_admin_panel(message):
    """Панель управления админами (только для главного админа)."""
    if message.chat.type != 'private':
        return

    user_id = str(message.chat.id)

    if not is_super_admin(user_id):
        bot.send_message(message.chat.id, "❌ Доступ запрещён. Только главный администратор может управлять админами.")
        return

    _send_admin_panel(message.chat.id)


def _send_admin_panel(chat_id, message_id=None):
    """Отправить/обновить панель управления админами."""
    admins = middleware_base.select_all(models.Admin)

    text = "👑 <b>Управление администраторами</b>\n\n"

    if config.ADMIN_ID:
        text += f"🔑 Главный админ: <code>{config.ADMIN_ID}</code>\n\n"

    if admins:
        text += "📋 <b>Список админов:</b>\n"
        for i, admin in enumerate(admins, 1):
            name = admin.user_name or "—"
            text += f"  {i}. {name} (<code>{admin.user_id}</code>)\n"
    else:
        text += "📋 Список админов пуст\n"

    text += "\nАдмины имеют доступ к подкрутке всех розыгрышей."

    markup = telebot.types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        telebot.types.InlineKeyboardButton("➕ Добавить админа", callback_data="adm_add"),
    )

    # Кнопки удаления для каждого админа
    for admin in admins:
        name = admin.user_name or admin.user_id
        markup.add(telebot.types.InlineKeyboardButton(
            f"🗑 Удалить {name}",
            callback_data=f"adm_del_{admin.user_id}"
        ))

    if message_id:
        try:
            bot.edit_message_text(
                text, chat_id=chat_id, message_id=message_id,
                reply_markup=markup, parse_mode='HTML'
            )
        except:
            pass
    else:
        bot.send_message(chat_id, text, reply_markup=markup, parse_mode='HTML')


# Callback: Добавить админа — ожидание ввода ID
@bot.callback_query_handler(func=lambda call: call.data == 'adm_add')
def handle_admin_add_start(call):
    if not is_super_admin(str(call.from_user.id)):
        bot.answer_callback_query(call.id, "❌ Нет доступа", show_alert=True)
        return

    _waiting_for[call.from_user.id] = {'action': 'add_admin', 'message_id': call.message.message_id}
    bot.answer_callback_query(call.id)
    bot.send_message(
        call.message.chat.id,
        "👤 Перешлите сообщение от пользователя или введите его Telegram ID:",
        reply_markup=telebot.types.ForceReply(selective=True)
    )


# Callback: Удалить админа
@bot.callback_query_handler(func=lambda call: call.data.startswith('adm_del_'))
def handle_admin_delete(call):
    if not is_super_admin(str(call.from_user.id)):
        bot.answer_callback_query(call.id, "❌ Нет доступа", show_alert=True)
        return

    target_id = call.data.split('_')[2]
    admin = middleware_base.get_one(models.Admin, user_id=target_id)

    if admin:
        middleware_base.delete(models.Admin, user_id=target_id)
        bot.answer_callback_query(call.id, f"✅ Админ {admin.user_name or target_id} удалён")
    else:
        bot.answer_callback_query(call.id, "❌ Админ не найден", show_alert=True)
        return

    _send_admin_panel(call.message.chat.id, call.message.message_id)


# Обработка ввода ID нового админа (текст или пересланное сообщение)
@bot.message_handler(func=lambda msg: msg.chat.id in _waiting_for and _waiting_for[msg.chat.id].get('action') == 'add_admin')
def handle_admin_add_input(message):
    state = _waiting_for.pop(message.chat.id, None)
    if not state:
        return

    # Определяем user_id
    if message.forward_from:
        # Пересланное сообщение
        new_admin_id = str(message.forward_from.id)
        new_admin_name = message.forward_from.username or message.forward_from.first_name or None
    else:
        # Текстовый ввод
        text = message.text.strip()
        if not text.isdigit():
            bot.send_message(message.chat.id, "❌ Некорректный ID. Введите числовой Telegram ID или перешлите сообщение.")
            return
        new_admin_id = text
        new_admin_name = None

    # Проверка: уже админ?
    existing = middleware_base.get_one(models.Admin, user_id=new_admin_id)
    if existing:
        bot.send_message(message.chat.id, f"⚠️ Пользователь {new_admin_id} уже является админом.")
        return

    # Проверка: это не главный админ?
    if str(new_admin_id) == str(config.ADMIN_ID):
        bot.send_message(message.chat.id, "⚠️ Это уже главный администратор.")
        return

    # Добавляем
    middleware_base.new(models.Admin, new_admin_id, new_admin_name, str(message.chat.id))

    bot.send_message(
        message.chat.id,
        f"✅ Админ добавлен: <code>{new_admin_id}</code>" + (f" (@{new_admin_name})" if new_admin_name else ""),
        parse_mode='HTML'
    )

    # Обновляем панель
    _send_admin_panel(message.chat.id)


# ============================================ #
#          ПАНЕЛЬ ПОДКРУТКИ (CALLBACKS)         #
# ============================================ #

@bot.callback_query_handler(func=lambda call: call.data.startswith('rig_draw_'))
def handle_rig_draw_selected(call):
    draw_id = int(call.data.split('_')[2])
    admin_id = str(call.from_user.id)

    draw = middleware_base.get_one(models.Draw, id=draw_id)
    if draw is None:
        bot.answer_callback_query(call.id, "❌ Розыгрыш не найден", show_alert=True)
        return

    # Доступ: владелец ИЛИ админ
    if str(draw.user_id) != admin_id and not is_admin(admin_id):
        bot.answer_callback_query(call.id, "❌ Нет доступа", show_alert=True)
        return

    _show_players_panel(call.message.chat.id, call.message.message_id, draw)
    bot.answer_callback_query(call.id)


@bot.callback_query_handler(func=lambda call: call.data.startswith('rig_toggle_'))
def handle_rig_toggle(call):
    parts = call.data.split('_')
    draw_id = int(parts[2])
    player_user_id = parts[3]
    admin_id = str(call.from_user.id)

    draw = middleware_base.get_one(models.Draw, id=draw_id)
    if draw is None:
        bot.answer_callback_query(call.id, "❌ Розыгрыш не найден", show_alert=True)
        return

    if str(draw.user_id) != admin_id and not is_admin(admin_id):
        bot.answer_callback_query(call.id, "❌ Нет доступа", show_alert=True)
        return

    player = middleware_base.get_one(models.DrawPlayer, draw_id=str(draw_id), user_id=player_user_id)
    if player is None:
        bot.answer_callback_query(call.id, "❌ Игрок не найден", show_alert=True)
        return

    # Toggle
    if player.is_rigged:
        result = unrig_player(draw_id, player_user_id, admin_id)
        if result.success:
            bot.answer_callback_query(call.id, f"❌ Подкрутка снята: {player.user_name}")
        else:
            bot.answer_callback_query(call.id, f"⚠️ {result.message}", show_alert=True)
            return
    else:
        result = rig_player(draw_id, player_user_id, admin_id)
        if result.success:
            bot.answer_callback_query(call.id, f"✅ Подкручен: {player.user_name}")
        else:
            bot.answer_callback_query(call.id, f"⚠️ {result.message}", show_alert=True)
            return

    _show_players_panel(call.message.chat.id, call.message.message_id, draw)


@bot.callback_query_handler(func=lambda call: call.data.startswith('rig_page_'))
def handle_rig_page(call):
    parts = call.data.split('_')
    draw_id = int(parts[2])
    page = int(parts[3])
    admin_id = str(call.from_user.id)

    draw = middleware_base.get_one(models.Draw, id=draw_id)
    if draw is None or (str(draw.user_id) != admin_id and not is_admin(admin_id)):
        bot.answer_callback_query(call.id, "❌ Нет доступа", show_alert=True)
        return

    _show_players_panel(call.message.chat.id, call.message.message_id, draw, page=page)
    bot.answer_callback_query(call.id)


@bot.callback_query_handler(func=lambda call: call.data == 'rig_back_to_draws')
def handle_rig_back(call):
    admin_id = str(call.from_user.id)

    if is_admin(admin_id):
        draws = middleware_base.select_all(models.Draw)
    else:
        draws = middleware_base.select_all(models.Draw, user_id=admin_id)

    if not draws:
        bot.edit_message_text(
            "📭 Нет активных розыгрышей.",
            chat_id=call.message.chat.id,
            message_id=call.message.message_id
        )
        bot.answer_callback_query(call.id)
        return

    _send_draws_list(call.message.chat.id, draws, is_admin(admin_id), message_id=call.message.message_id)
    bot.answer_callback_query(call.id)


# ============================================ #
#          ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ             #
# ============================================ #

PLAYERS_PER_PAGE = 8


def _send_draws_list(chat_id, draws, admin_mode=False, message_id=None):
    """Показать список розыгрышей для выбора."""
    markup = telebot.types.InlineKeyboardMarkup(row_width=1)
    for draw in draws:
        players_count = len(middleware_base.select_all(models.DrawPlayer, draw_id=str(draw.id)))
        rigged_count = len(middleware_base.select_all(models.DrawPlayer, draw_id=str(draw.id), is_rigged=True))
        btn_text = f"🎲 #{draw.id} | {draw.text[:25]}.. | 👥{players_count} | 🎯{rigged_count}/{draw.winers_count}"
        markup.add(telebot.types.InlineKeyboardButton(
            text=btn_text,
            callback_data=f"rig_draw_{draw.id}"
        ))

    title = "🎯 <b>Панель подкрутки</b>"
    if admin_mode:
        title += " (👑 режим админа — все розыгрыши)"
    title += "\n\nВыберите розыгрыш:"

    if message_id:
        try:
            bot.edit_message_text(
                title, chat_id=chat_id, message_id=message_id,
                reply_markup=markup, parse_mode='HTML'
            )
        except:
            pass
    else:
        bot.send_message(chat_id, title, reply_markup=markup, parse_mode='HTML')


def _show_players_panel(chat_id, message_id, draw, page=0):
    """Показать панель участников розыгрыша с кнопками подкрутки."""
    draw_id = draw.id
    players = middleware_base.select_all(models.DrawPlayer, draw_id=str(draw_id))
    rigged_count = sum(1 for p in players if p.is_rigged)
    total_players = len(players)

    start = page * PLAYERS_PER_PAGE
    end = start + PLAYERS_PER_PAGE
    page_players = players[start:end]
    total_pages = max(1, (total_players + PLAYERS_PER_PAGE - 1) // PLAYERS_PER_PAGE)

    header = (
        f"🎯 <b>Розыгрыш #{draw_id}</b>\n"
        f"📝 {draw.text[:50]}\n"
        f"👥 Участников: {total_players} | 🏆 Победителей: {draw.winers_count}\n"
        f"🎯 Подкручено: {rigged_count}/{draw.winers_count}\n\n"
    )

    if not players:
        header += "⚠️ Пока нет участников."
    else:
        header += "Нажмите чтобы подкрутить/снять:"

    markup = telebot.types.InlineKeyboardMarkup(row_width=1)

    for player in page_players:
        icon = "✅" if player.is_rigged else "⬜"
        btn_text = f"{icon} {player.user_name or player.user_id}"
        markup.add(telebot.types.InlineKeyboardButton(
            text=btn_text,
            callback_data=f"rig_toggle_{draw_id}_{player.user_id}"
        ))

    # Навигация
    nav_buttons = []
    if page > 0:
        nav_buttons.append(telebot.types.InlineKeyboardButton(
            "◀️", callback_data=f"rig_page_{draw_id}_{page - 1}"
        ))
    if total_pages > 1:
        nav_buttons.append(telebot.types.InlineKeyboardButton(
            f"{page + 1}/{total_pages}", callback_data="noop"
        ))
    if page < total_pages - 1:
        nav_buttons.append(telebot.types.InlineKeyboardButton(
            "▶️", callback_data=f"rig_page_{draw_id}_{page + 1}"
        ))
    if nav_buttons:
        markup.row(*nav_buttons)

    markup.add(telebot.types.InlineKeyboardButton(
        "◀️ К списку розыгрышей", callback_data="rig_back_to_draws"
    ))

    try:
        bot.edit_message_text(
            header, chat_id=chat_id, message_id=message_id,
            reply_markup=markup, parse_mode='HTML'
        )
    except:
        pass


# Заглушка для кнопки "noop"
@bot.callback_query_handler(func=lambda call: call.data == 'noop')
def handle_noop(call):
    bot.answer_callback_query(call.id)


# -------------------------------------- #
# Запуск бота
# -------------------------------------- #
if __name__ == '__main__':
    bot.polling(none_stop=True)
