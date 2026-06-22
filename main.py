import telebot
import models
import config
from app import bot
from middleware import (
    rig_player, unrig_player, get_rigged_players,
    RigResult, end_draw_timer, select_winners,
    is_admin, is_super_admin, check_subscription, start_draw_timer
)
from app import middleware_base
from tool import language_check

# Запуск таймеров
start_draw_timer()
end_draw_timer()

# Словарь для хранения состояний ожидания ввода
_waiting_for = {}

# Тексты кнопок главного меню
BTN_NEW = "🎲 Создать розыгрыш"
BTN_MY = "📋 Мои розыгрыши"
BTN_MANAGE = "⚙️ Управление"
BTN_ADMINS = "👑 Админы"
BTN_BACK = "◀️ Назад"


def _main_menu_keyboard(user_id):
    """Создаёт Reply-клавиатуру главного меню."""
    markup = telebot.types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.row(BTN_NEW)
    markup.row(BTN_MY, BTN_MANAGE)
    if is_super_admin(str(user_id)):
        markup.row(BTN_ADMINS)
    return markup


# ============================================ #
#                 /start                       #
# ============================================ #

@bot.message_handler(commands=['start'])
def handle_start(message):
    if message.chat.type != 'private':
        return

    user_id = str(message.chat.id)
    user_name = message.from_user.username or message.from_user.first_name

    if not middleware_base.get_one(models.User, user_id=user_id):
        middleware_base.new(models.User, user_id, user_name, "RU")

    bot.send_message(
        message.chat.id,
        f"👋 Привет, {user_name}!\n\n"
        "🎲 Я — бот для проведения розыгрышей.\n"
        "Выбери действие из меню ниже:",
        reply_markup=_main_menu_keyboard(message.chat.id),
        parse_mode='HTML'
    )


# ============================================ #
#       ОБРАБОТКА КНОПОК ГЛАВНОГО МЕНЮ         #
# ============================================ #

@bot.message_handler(func=lambda msg: msg.text == BTN_NEW)
def handle_btn_new(message):
    handle_new_draw(message)

@bot.message_handler(func=lambda msg: msg.text == BTN_MY)
def handle_btn_my(message):
    handle_my_draws(message)

@bot.message_handler(func=lambda msg: msg.text == BTN_MANAGE)
def handle_btn_manage(message):
    handle_rig_panel(message)

@bot.message_handler(func=lambda msg: msg.text == BTN_ADMINS)
def handle_btn_admins(message):
    handle_admin_panel(message)


# ============================================ #
#          СОЗДАНИЕ РОЗЫГРЫША                  #
# ============================================ #

@bot.message_handler(commands=['new'])
def handle_new_draw(message):
    if message.chat.type != 'private':
        return
    user_id = str(message.chat.id)
    if not middleware_base.get_one(models.User, user_id=user_id):
        middleware_base.new(models.User, user_id, message.from_user.username or "user", "RU")

    _waiting_for[message.chat.id] = {'action': 'draw_channel'}
    markup = telebot.types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.row(BTN_BACK)
    bot.send_message(
        message.chat.id,
        "🎲 <b>Создание розыгрыша</b>\n\n"
        "Шаг 1/4: Введите ID канала или группы\n"
        "(Бот должен быть админом канала)\n\n"
        "Пример: <code>-1001234567890</code>",
        reply_markup=markup,
        parse_mode='HTML'
    )


@bot.message_handler(func=lambda msg: msg.text == BTN_BACK)
def handle_back_to_menu(message):
    _waiting_for.pop(message.chat.id, None)
    bot.send_message(
        message.chat.id, "Главное меню:",
        reply_markup=_main_menu_keyboard(message.chat.id)
    )


@bot.message_handler(func=lambda msg: msg.chat.id in _waiting_for and _waiting_for[msg.chat.id].get('action') == 'draw_channel')
def handle_draw_channel(message):
    if message.text == BTN_BACK:
        return
    channel_id = message.text.strip()
    try:
        bot_member = bot.get_chat_member(channel_id, bot.get_me().id)
        if bot_member.status not in ['administrator', 'creator']:
            bot.send_message(message.chat.id, "❌ Бот не является администратором канала.")
            return
        chat_info = bot.get_chat(channel_id)
        channel_name = chat_info.title
    except Exception:
        bot.send_message(message.chat.id, "❌ Не удалось найти канал. Проверьте ID.")
        return

    _waiting_for[message.chat.id] = {
        'action': 'draw_text', 'channel_id': channel_id, 'channel_name': channel_name
    }
    bot.send_message(message.chat.id, f"✅ Канал: <b>{channel_name}</b>\n\nШаг 2/4: Введите текст розыгрыша:", parse_mode='HTML')


@bot.message_handler(func=lambda msg: msg.chat.id in _waiting_for and _waiting_for[msg.chat.id].get('action') == 'draw_text')
def handle_draw_text(message):
    if message.text == BTN_BACK:
        return
    state = _waiting_for[message.chat.id]
    state['action'] = 'draw_winners'
    state['text'] = message.text.strip()
    bot.send_message(message.chat.id, "Шаг 3/4: Сколько победителей? (число)")


@bot.message_handler(func=lambda msg: msg.chat.id in _waiting_for and _waiting_for[msg.chat.id].get('action') == 'draw_winners')
def handle_draw_winners(message):
    if message.text == BTN_BACK:
        return
    try:
        count = int(message.text.strip())
        if count < 1:
            raise ValueError
    except ValueError:
        bot.send_message(message.chat.id, "❌ Введите положительное число.")
        return
    state = _waiting_for[message.chat.id]
    state['action'] = 'draw_duration'
    state['winners_count'] = count
    bot.send_message(message.chat.id, "Шаг 4/4: Через сколько минут завершить?\n(5 = 5 мин, 60 = 1 час, 1440 = 1 день)")


@bot.message_handler(func=lambda msg: msg.chat.id in _waiting_for and _waiting_for[msg.chat.id].get('action') == 'draw_duration')
def handle_draw_duration(message):
    if message.text == BTN_BACK:
        return
    try:
        minutes = int(message.text.strip())
        if minutes < 1:
            raise ValueError
    except ValueError:
        bot.send_message(message.chat.id, "❌ Введите положительное число минут.")
        return

    from datetime import datetime, timedelta
    now = datetime.now()
    post_time = now.strftime('%Y-%m-%d %H:%M')
    end_time = (now + timedelta(minutes=minutes)).strftime('%Y-%m-%d %H:%M')

    state = _waiting_for[message.chat.id]
    state['action'] = 'draw_confirm'
    state['post_time'] = post_time
    state['end_time'] = end_time

    markup = telebot.types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        telebot.types.InlineKeyboardButton("✅ Опубликовать", callback_data="draw_confirm"),
        telebot.types.InlineKeyboardButton("❌ Отмена", callback_data="draw_cancel"),
    )
    bot.send_message(
        message.chat.id,
        f"📋 <b>Превью:</b>\n\n"
        f"📢 {state['channel_name']}\n"
        f"📝 {state['text']}\n"
        f"🏆 Победителей: {state['winners_count']}\n"
        f"⏰ Завершение: {end_time}\n\nВсё верно?",
        reply_markup=markup, parse_mode='HTML'
    )


@bot.callback_query_handler(func=lambda call: call.data == 'draw_confirm')
def handle_draw_confirm(call):
    state = _waiting_for.pop(call.from_user.id, None)
    if not state or state.get('action') != 'draw_confirm':
        bot.answer_callback_query(call.id, "⚠️ Сессия истекла", show_alert=True)
        return
    user_id = str(call.from_user.id)
    text = state['text']

    markup = telebot.types.InlineKeyboardMarkup()
    markup.add(telebot.types.InlineKeyboardButton("🎉 Участвовать", callback_data="join_placeholder"))
    try:
        msg = bot.send_message(
            state['channel_id'],
            f"🎲 <b>РОЗЫГРЫШ</b>\n\n{text}\n\n"
            f"🏆 Победителей: {state['winners_count']}\n⏰ До: {state['end_time']}\n\n👥 Участников: 0",
            reply_markup=markup, parse_mode='HTML'
        )
    except Exception as e:
        bot.edit_message_text(f"❌ Ошибка: {e}", chat_id=call.message.chat.id, message_id=call.message.message_id)
        bot.answer_callback_query(call.id)
        return

    all_draws = middleware_base.select_all(models.Draw)
    next_id = max([d.id for d in all_draws], default=0) + 1
    middleware_base.new(models.Draw, next_id, user_id, str(msg.message_id),
                       state['channel_id'], state['channel_name'], text, 'text', '',
                       state['winners_count'], state['post_time'], state['end_time'])

    join_markup = telebot.types.InlineKeyboardMarkup()
    join_markup.add(telebot.types.InlineKeyboardButton(f"🎉 Участвовать (0)", callback_data=f"join_{next_id}"))
    bot.edit_message_reply_markup(chat_id=state['channel_id'], message_id=msg.message_id, reply_markup=join_markup)

    bot.edit_message_text(
        f"✅ <b>Розыгрыш #{next_id} опубликован!</b>\n📢 {state['channel_name']}\n⏰ {state['end_time']}",
        chat_id=call.message.chat.id, message_id=call.message.message_id, parse_mode='HTML'
    )
    bot.send_message(call.message.chat.id, "Главное меню:", reply_markup=_main_menu_keyboard(call.from_user.id))
    bot.answer_callback_query(call.id, "✅ Опубликовано!")


@bot.callback_query_handler(func=lambda call: call.data == 'draw_cancel')
def handle_draw_cancel(call):
    _waiting_for.pop(call.from_user.id, None)
    bot.edit_message_text("❌ Отменено.", chat_id=call.message.chat.id, message_id=call.message.message_id)
    bot.send_message(call.message.chat.id, "Главное меню:", reply_markup=_main_menu_keyboard(call.from_user.id))
    bot.answer_callback_query(call.id)


# ============================================ #
#          УЧАСТИЕ В РОЗЫГРЫШЕ                 #
# ============================================ #

@bot.callback_query_handler(func=lambda call: call.data.startswith('join_'))
def handle_join_draw(call):
    raw = call.data.split('_')[1]
    if raw == 'placeholder':
        bot.answer_callback_query(call.id, "⏳ Загрузка...", show_alert=False)
        return
    draw_id = int(raw)
    user_id = str(call.from_user.id)
    user_name = call.from_user.username or call.from_user.first_name or str(call.from_user.id)

    draw = middleware_base.get_one(models.Draw, id=draw_id)
    if draw is None:
        bot.answer_callback_query(call.id, "❌ Розыгрыш завершён", show_alert=True)
        return
    if not check_subscription(draw_id, user_id):
        bot.answer_callback_query(call.id, "❌ Подпишитесь на каналы-спонсоры!", show_alert=True)
        return
    existing = middleware_base.get_one(models.DrawPlayer, draw_id=str(draw_id), user_id=user_id)
    if existing:
        bot.answer_callback_query(call.id, "✋ Вы уже участвуете!", show_alert=True)
        return

    middleware_base.new(models.DrawPlayer, draw_id, user_id, user_name)
    players_count = len(middleware_base.select_all(models.DrawPlayer, draw_id=str(draw_id)))
    join_markup = telebot.types.InlineKeyboardMarkup()
    join_markup.add(telebot.types.InlineKeyboardButton(f"🎉 Участвовать ({players_count})", callback_data=f"join_{draw_id}"))
    try:
        bot.edit_message_reply_markup(chat_id=call.message.chat.id, message_id=call.message.message_id, reply_markup=join_markup)
    except:
        pass
    bot.answer_callback_query(call.id, "🎉 Вы участвуете!")


# ============================================ #
#          МОИ РОЗЫГРЫШИ                       #
# ============================================ #

@bot.message_handler(commands=['my'])
def handle_my_draws(message):
    if message.chat.type != 'private':
        return
    user_id = str(message.chat.id)
    active = middleware_base.select_all(models.Draw, user_id=user_id)
    pending = middleware_base.select_all(models.DrawNot, user_id=user_id)

    if not active and not pending:
        bot.send_message(message.chat.id, "📭 У вас нет розыгрышей.", reply_markup=_main_menu_keyboard(message.chat.id))
        return

    text = "📋 <b>Ваши розыгрыши:</b>\n\n"
    if pending:
        text += "⏳ <b>Ожидают:</b>\n"
        for d in pending:
            text += f"  • #{d.id} {d.text[:30]}.. | 🕐 {d.post_time}\n"
        text += "\n"
    if active:
        text += "🟢 <b>Активные:</b>\n"
        for d in active:
            pc = len(middleware_base.select_all(models.DrawPlayer, draw_id=str(d.id)))
            text += f"  • #{d.id} {d.text[:30]}.. | 👥{pc} | ⏰{d.end_time}\n"

    bot.send_message(message.chat.id, text, parse_mode='HTML', reply_markup=_main_menu_keyboard(message.chat.id))


# ============================================ #
#          УПРАВЛЕНИЕ (бывш. /rig)             #
# ============================================ #

@bot.message_handler(commands=['rig'])
def handle_rig_panel(message):
    if message.chat.type != 'private':
        return
    admin_id = str(message.chat.id)
    if is_admin(admin_id):
        draws = middleware_base.select_all(models.Draw)
    else:
        draws = middleware_base.select_all(models.Draw, user_id=admin_id)

    if not draws:
        bot.send_message(message.chat.id, "📭 Нет активных розыгрышей.", reply_markup=_main_menu_keyboard(message.chat.id))
        return
    _send_draws_list(message.chat.id, draws, is_admin(admin_id))


# ============================================ #
#     ПАНЕЛЬ АДМИНОВ                           #
# ============================================ #

@bot.message_handler(commands=['admin'])
def handle_admin_panel(message):
    if message.chat.type != 'private':
        return
    if not is_super_admin(str(message.chat.id)):
        bot.send_message(message.chat.id, "❌ Нет доступа.")
        return
    _send_admin_panel(message.chat.id)


def _send_admin_panel(chat_id, message_id=None):
    admins = middleware_base.select_all(models.Admin)
    text = "👑 <b>Администраторы</b>\n\n"
    if admins:
        for i, admin in enumerate(admins, 1):
            name = admin.user_name or "—"
            text += f"  {i}. {name} (<code>{admin.user_id}</code>)\n"
    else:
        text += "Список пуст\n"
    text += "\nАдмины видят все розыгрыши в разделе «Управление»."

    markup = telebot.types.InlineKeyboardMarkup(row_width=1)
    markup.add(telebot.types.InlineKeyboardButton("➕ Добавить", callback_data="adm_add"))
    for admin in admins:
        markup.add(telebot.types.InlineKeyboardButton(f"🗑 {admin.user_name or admin.user_id}", callback_data=f"adm_del_{admin.user_id}"))

    if message_id:
        try:
            bot.edit_message_text(text, chat_id=chat_id, message_id=message_id, reply_markup=markup, parse_mode='HTML')
        except:
            pass
    else:
        bot.send_message(chat_id, text, reply_markup=markup, parse_mode='HTML')


@bot.callback_query_handler(func=lambda call: call.data == 'adm_add')
def handle_admin_add_start(call):
    if not is_super_admin(str(call.from_user.id)):
        bot.answer_callback_query(call.id, "❌ Нет доступа", show_alert=True)
        return
    _waiting_for[call.from_user.id] = {'action': 'add_admin'}
    bot.answer_callback_query(call.id)
    bot.send_message(call.message.chat.id, "👤 Перешлите сообщение или введите Telegram ID:")


@bot.callback_query_handler(func=lambda call: call.data.startswith('adm_del_'))
def handle_admin_delete(call):
    if not is_super_admin(str(call.from_user.id)):
        bot.answer_callback_query(call.id, "❌ Нет доступа", show_alert=True)
        return
    target_id = call.data.split('_')[2]
    middleware_base.delete(models.Admin, user_id=target_id)
    bot.answer_callback_query(call.id, "✅ Удалён")
    _send_admin_panel(call.message.chat.id, call.message.message_id)


@bot.message_handler(func=lambda msg: msg.chat.id in _waiting_for and _waiting_for[msg.chat.id].get('action') == 'add_admin')
def handle_admin_add_input(message):
    _waiting_for.pop(message.chat.id, None)
    if message.forward_from:
        new_id = str(message.forward_from.id)
        new_name = message.forward_from.username or message.forward_from.first_name
    else:
        if not message.text.strip().isdigit():
            bot.send_message(message.chat.id, "❌ Введите числовой ID.")
            return
        new_id = message.text.strip()
        new_name = None

    if middleware_base.get_one(models.Admin, user_id=new_id):
        bot.send_message(message.chat.id, "⚠️ Уже админ.")
        return
    middleware_base.new(models.Admin, new_id, new_name, str(message.chat.id))
    bot.send_message(message.chat.id, f"✅ Админ добавлен: <code>{new_id}</code>", parse_mode='HTML')
    _send_admin_panel(message.chat.id)


# ============================================ #
#     INLINE-ПАНЕЛЬ УПРАВЛЕНИЯ РОЗЫГРЫШАМИ     #
# ============================================ #

PLAYERS_PER_PAGE = 8


def _send_draws_list(chat_id, draws, admin_mode=False, message_id=None):
    markup = telebot.types.InlineKeyboardMarkup(row_width=1)
    for draw in draws:
        pc = len(middleware_base.select_all(models.DrawPlayer, draw_id=str(draw.id)))
        btn_text = f"🎲 #{draw.id} | {draw.text[:25]}.. | 👥{pc}/{draw.winers_count}"
        markup.add(telebot.types.InlineKeyboardButton(text=btn_text, callback_data=f"rig_draw_{draw.id}"))

    title = "⚙️ <b>Управление розыгрышами</b>\n\nВыберите розыгрыш:"
    if message_id:
        try:
            bot.edit_message_text(title, chat_id=chat_id, message_id=message_id, reply_markup=markup, parse_mode='HTML')
        except:
            pass
    else:
        bot.send_message(chat_id, title, reply_markup=markup, parse_mode='HTML')


def _show_players_panel(chat_id, message_id, draw, page=0):
    draw_id = draw.id
    players = middleware_base.select_all(models.DrawPlayer, draw_id=str(draw_id))
    rigged_count = sum(1 for p in players if p.is_rigged)
    total_players = len(players)
    start = page * PLAYERS_PER_PAGE
    end = start + PLAYERS_PER_PAGE
    page_players = players[start:end]
    total_pages = max(1, (total_players + PLAYERS_PER_PAGE - 1) // PLAYERS_PER_PAGE)

    header = (
        f"⚙️ <b>Розыгрыш #{draw_id}</b>\n"
        f"📝 {draw.text[:50]}\n"
        f"👥 Участников: {total_players} | 🏆 Победителей: {draw.winers_count}\n"
        f"⭐ Выбрано: {rigged_count}/{draw.winers_count}\n\n"
    )
    if not players:
        header += "⚠️ Пока нет участников."
    else:
        header += "Нажмите на участника для выбора:"

    markup = telebot.types.InlineKeyboardMarkup(row_width=1)
    for player in page_players:
        icon = "⭐" if player.is_rigged else "⬜"
        markup.add(telebot.types.InlineKeyboardButton(
            f"{icon} {player.user_name or player.user_id}",
            callback_data=f"rig_toggle_{draw_id}_{player.user_id}"
        ))

    nav = []
    if page > 0:
        nav.append(telebot.types.InlineKeyboardButton("◀️", callback_data=f"rig_page_{draw_id}_{page-1}"))
    if total_pages > 1:
        nav.append(telebot.types.InlineKeyboardButton(f"{page+1}/{total_pages}", callback_data="noop"))
    if page < total_pages - 1:
        nav.append(telebot.types.InlineKeyboardButton("▶️", callback_data=f"rig_page_{draw_id}_{page+1}"))
    if nav:
        markup.row(*nav)
    markup.add(telebot.types.InlineKeyboardButton("◀️ Назад", callback_data="rig_back_to_draws"))

    try:
        bot.edit_message_text(header, chat_id=chat_id, message_id=message_id, reply_markup=markup, parse_mode='HTML')
    except:
        pass


@bot.callback_query_handler(func=lambda call: call.data.startswith('rig_draw_'))
def handle_rig_draw_selected(call):
    draw_id = int(call.data.split('_')[2])
    admin_id = str(call.from_user.id)
    draw = middleware_base.get_one(models.Draw, id=draw_id)
    if not draw or (str(draw.user_id) != admin_id and not is_admin(admin_id)):
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
    if not draw or (str(draw.user_id) != admin_id and not is_admin(admin_id)):
        bot.answer_callback_query(call.id, "❌ Нет доступа", show_alert=True)
        return
    player = middleware_base.get_one(models.DrawPlayer, draw_id=str(draw_id), user_id=player_user_id)
    if not player:
        bot.answer_callback_query(call.id, "❌ Не найден", show_alert=True)
        return

    if player.is_rigged:
        result = unrig_player(draw_id, player_user_id, admin_id)
        bot.answer_callback_query(call.id, f"⬜ {player.user_name}" if result.success else f"⚠️ {result.message}")
    else:
        result = rig_player(draw_id, player_user_id, admin_id)
        bot.answer_callback_query(call.id, f"⭐ {player.user_name}" if result.success else f"⚠️ {result.message}")

    if result.success:
        _show_players_panel(call.message.chat.id, call.message.message_id, draw)


@bot.callback_query_handler(func=lambda call: call.data.startswith('rig_page_'))
def handle_rig_page(call):
    parts = call.data.split('_')
    draw_id = int(parts[2])
    page = int(parts[3])
    draw = middleware_base.get_one(models.Draw, id=draw_id)
    if not draw:
        bot.answer_callback_query(call.id, "❌", show_alert=True)
        return
    _show_players_panel(call.message.chat.id, call.message.message_id, draw, page=page)
    bot.answer_callback_query(call.id)


@bot.callback_query_handler(func=lambda call: call.data == 'rig_back_to_draws')
def handle_rig_back(call):
    admin_id = str(call.from_user.id)
    draws = middleware_base.select_all(models.Draw) if is_admin(admin_id) else middleware_base.select_all(models.Draw, user_id=admin_id)
    if not draws:
        bot.edit_message_text("📭 Нет розыгрышей.", chat_id=call.message.chat.id, message_id=call.message.message_id)
    else:
        _send_draws_list(call.message.chat.id, draws, is_admin(admin_id), message_id=call.message.message_id)
    bot.answer_callback_query(call.id)


@bot.callback_query_handler(func=lambda call: call.data == 'noop')
def handle_noop(call):
    bot.answer_callback_query(call.id)


# -------------------------------------- #
if __name__ == '__main__':
    bot.polling(none_stop=True)
