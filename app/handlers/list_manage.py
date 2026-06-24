"""Handler for /list command — event management panel."""

from aiogram import Router, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.exceptions import TelegramBadRequest

from app.states import ListManageStates
from app.services.event_service import EventService

list_manage_router = Router()


async def _fetch_user_events(event_service: EventService, user_id: int, status: str) -> list[dict]:
    """Fetch user events by status category."""
    async with event_service.db.acquire() as conn:
        if status == "active":
            rows = await conn.fetch(
                "SELECT event_id, event_type, title FROM events "
                "WHERE creator_id=$1 AND is_active=true ORDER BY event_id DESC",
                user_id,
            )
        elif status == "finished":
            rows = await conn.fetch(
                "SELECT event_id, event_type, title FROM events "
                "WHERE creator_id=$1 AND is_active=false AND post_chat_id IS NOT NULL "
                "ORDER BY event_id DESC",
                user_id,
            )
        elif status == "unpublished":
            rows = await conn.fetch(
                "SELECT event_id, event_type, title FROM events "
                "WHERE creator_id=$1 AND is_active=false AND post_chat_id IS NULL "
                "ORDER BY event_id DESC",
                user_id,
            )
        else:
            return []
    return [dict(r) for r in rows]


async def _get_manage_menu_content(
    event_id: int, event_service: EventService
) -> tuple[str, types.InlineKeyboardMarkup | None]:
    """Build the main management menu for an event."""
    event = await event_service.get_event(event_id)
    if not event:
        return "Событие не найдено.", None

    text = f"Главная страница управления событием №{event_id}\nВыберите действие:"
    counter_status = "🟢" if event["show_participants_counter"] else "🔴"
    counter_btn_text = f"Счётчик: {counter_status}"

    kb = []

    is_unpublished = not event["is_active"] and event.get("post_chat_id") is None
    if is_unpublished:
        kb.append(
            [types.InlineKeyboardButton(text="🚀 Опубликовать", callback_data="evt_publish_now")]
        )

    kb.extend([
        [
            types.InlineKeyboardButton(text="🏁 Завершить", callback_data="evt_finish"),
            types.InlineKeyboardButton(text="👑 Изм. победителей", callback_data="evt_edit_winners"),
        ],
        [
            types.InlineKeyboardButton(text="🚸 Лимит участников", callback_data="evt_edit_participants"),
            types.InlineKeyboardButton(text="🔘 Текст кнопки", callback_data="evt_edit_button"),
        ],
        [
            types.InlineKeyboardButton(text=counter_btn_text, callback_data="evt_toggle_counter"),
            types.InlineKeyboardButton(text="🔧 Доп. функции", callback_data="evt_additional"),
        ],
        [types.InlineKeyboardButton(text="◀ Назад", callback_data="evt_back_list")],
    ])
    markup = types.InlineKeyboardMarkup(inline_keyboard=kb)
    return text, markup


async def _show_additional_menu(
    msg: types.Message, event_id: int, event_service: EventService
) -> None:
    """Display the additional functions sub-menu."""
    event = await event_service.get_event(event_id)
    if not event:
        return

    notify_status = "🔔" if event["notify_winners"] else "🔕"
    hide_btn_status = "👁" if event["hide_button_after_finish"] else "🔘"

    kb = [
        [
            types.InlineKeyboardButton(text="🔥 Авто-байты", callback_data="addf_autobytes"),
            types.InlineKeyboardButton(
                text=f"Уведомления: {notify_status}", callback_data="addf_notify"
            ),
        ],
        [
            types.InlineKeyboardButton(
                text=f"Скрыть кнопку: {hide_btn_status}", callback_data="addf_hidebtn"
            ),
            types.InlineKeyboardButton(text="🤝 Спонсоры", callback_data="addf_sponsor"),
        ],
        [
            types.InlineKeyboardButton(text="📤 Поделиться", callback_data="addf_share"),
            types.InlineKeyboardButton(text="🔄 Восстановить", callback_data="addf_restore"),
        ],
        [types.InlineKeyboardButton(text="🧾 Участники", callback_data="addf_participants")],
        [types.InlineKeyboardButton(text="◀ Назад", callback_data="addf_back")],
    ]
    markup = types.InlineKeyboardMarkup(inline_keyboard=kb)
    text = f"Дополнительные функции для события #{event_id}:\n\nВыберите нужное:"
    try:
        await msg.edit_text(text, reply_markup=markup)
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e):
            await msg.answer(text, reply_markup=markup)


async def _show_autobytes_menu(
    msg: types.Message, event_id: int, event_service: EventService
) -> None:
    """Display the auto-bytes settings menu."""
    evt = await event_service.get_event(event_id)
    if not evt:
        await msg.answer("Ошибка: событие не найдено!")
        return

    status = "🟢 Включены" if evt["auto_bytes"] else "🔴 Отключены"
    notify_str = "🔔 Со звуком" if evt["auto_bytes_notify"] else "🔕 Без звука"
    text = (
        f"🔥 Автоматические байты:\n\n"
        f"Статус: {status}\n"
        f"Интервал: {evt['byte_interval']} мин.\n"
        f"Уведомления: {notify_str}\n\n"
        "Выберите действие:"
    )
    kb = [
        [
            types.InlineKeyboardButton(text="🔀 Вкл/Выкл", callback_data="ab_toggle"),
            types.InlineKeyboardButton(text="🔇 Уведомления", callback_data="ab_notify"),
        ],
        [types.InlineKeyboardButton(text="⏱ Интервал", callback_data="ab_interval")],
        [types.InlineKeyboardButton(text="◀ Назад", callback_data="ab_back")],
    ]
    markup = types.InlineKeyboardMarkup(inline_keyboard=kb)
    try:
        await msg.edit_text(text, reply_markup=markup)
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e):
            await msg.answer(text, reply_markup=markup)


async def _show_sponsor_menu(
    msg: types.Message, event_id: int, event_service: EventService
) -> None:
    """Display the sponsors management menu."""
    sponsors = await event_service.get_sponsors(event_id)
    text = f"🤝 <b>Спонсоры события #{event_id}</b>\n\n"
    if not sponsors:
        text += "Пока нет спонсоров.\n"
    else:
        text += "Текущий список:\n"
        for s in sponsors:
            text += f" • ID {s['sponsor_id']}, @{s['username']}\n"
    text += "\nВыберите действие:"
    kb = [
        [
            types.InlineKeyboardButton(text="➕ Добавить", callback_data="sponsor_add"),
            types.InlineKeyboardButton(text="➖ Удалить", callback_data="sponsor_del"),
        ],
        [types.InlineKeyboardButton(text="◀ Назад", callback_data="sponsor_back")],
    ]
    markup = types.InlineKeyboardMarkup(inline_keyboard=kb)
    try:
        await msg.edit_text(text, reply_markup=markup)
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e):
            await msg.answer(text, reply_markup=markup)


# ─── /list command ───────────────────────────────────────────────────────────


@list_manage_router.message(Command("list", ignore_mention=True))
async def cmd_list_menu(message: types.Message, state: FSMContext, **kwargs):
    """Show event management category selection."""
    kb = [
        [
            types.InlineKeyboardButton(text="🟢 Активные", callback_data="list_show_active"),
            types.InlineKeyboardButton(text="🔴 Завершённые", callback_data="list_show_finished"),
            types.InlineKeyboardButton(text="📝 Неопубликованные", callback_data="list_show_unpub"),
        ],
        [types.InlineKeyboardButton(text="◀ Назад", callback_data="list_go_back")],
    ]
    markup = types.InlineKeyboardMarkup(inline_keyboard=kb)
    text = "<b>Управление вашими конкурсами/лотереями</b>\n\nВыберите категорию событий:"
    await message.answer(text, reply_markup=markup)
    await state.set_state(ListManageStates.list_main)


# ─── Category selection callbacks ────────────────────────────────────────────


@list_manage_router.callback_query(
    ListManageStates.list_main,
    F.data.in_({"list_show_active", "list_show_finished", "list_show_unpub", "list_go_back"}),
)
async def on_list_main_buttons(
    callback: types.CallbackQuery, state: FSMContext, event_service: EventService, **kwargs
):
    """Handle category selection from the /list menu."""
    user_id = callback.from_user.id

    if callback.data == "list_go_back":
        await callback.message.edit_text("Возврат в главное меню...")
        await state.clear()
        await callback.answer()
        return

    status_map = {
        "list_show_active": "active",
        "list_show_finished": "finished",
        "list_show_unpub": "unpublished",
    }
    chosen_status = status_map.get(callback.data, "")
    events = await _fetch_user_events(event_service, user_id, chosen_status)

    if not events:
        await callback.message.edit_text("В этой категории нет событий.")
        await callback.answer()
        return

    text_header = {
        "active": "📜 Список активных лотерей/конкурсов:",
        "finished": "📜 Список завершённых событий:",
        "unpublished": "📜 Список неопубликованных событий:",
    }.get(chosen_status, "Список событий:")
    text = f"{text_header}\n\n❓Выберите нужную, чтобы управлять ею"

    ikb_rows = []
    for evt in events:
        e_id = evt["event_id"]
        e_type = evt["event_type"]
        title = evt.get("title") or f"Событие #{e_id}"
        title = (title[:25] + "..") if len(title) > 25 else title
        icon = "🎟️" if e_type == "lottery" else "🎉"
        btn_text = f"{icon} №{e_id}: {title}"
        ikb_rows.append(
            [types.InlineKeyboardButton(text=btn_text, callback_data=f"choose_evt:{e_id}")]
        )
    ikb_rows.append(
        [types.InlineKeyboardButton(text="◀ Назад", callback_data="list_return_main")]
    )
    markup = types.InlineKeyboardMarkup(inline_keyboard=ikb_rows)

    await callback.message.edit_text(text, reply_markup=markup)
    await state.set_state(ListManageStates.choosing_event)
    await callback.answer()


# ─── Event selection callback ────────────────────────────────────────────────


@list_manage_router.callback_query(ListManageStates.choosing_event)
async def on_choose_event(
    callback: types.CallbackQuery, state: FSMContext, event_service: EventService, **kwargs
):
    """Handle event selection from the list."""
    if callback.data == "list_return_main":
        await callback.message.delete()
        await cmd_list_menu(callback.message, state)
        await callback.answer()
        return

    if not callback.data.startswith("choose_evt:"):
        await callback.answer("Неизвестный формат", show_alert=True)
        return

    event_id = int(callback.data.split(":")[1])
    await state.update_data(chosen_event_id=event_id)

    text, markup = await _get_manage_menu_content(event_id, event_service)
    await callback.message.edit_text(text, reply_markup=markup)
    await state.set_state(ListManageStates.managing_event)
    await callback.answer()


# ─── Event management menu callbacks ─────────────────────────────────────────


@list_manage_router.callback_query(ListManageStates.managing_event)
async def on_event_manage_menu(
    callback: types.CallbackQuery, state: FSMContext, event_service: EventService, **kwargs
):
    """Handle actions from the event management menu."""
    data_ = await state.get_data()
    event_id = data_.get("chosen_event_id")
    action = callback.data

    if action == "evt_back_list":
        await callback.message.delete()
        await cmd_list_menu(callback.message, state)
        await callback.answer()
        return

    if action == "evt_publish_now":
        event = await event_service.get_event(event_id)
        if not event:
            await callback.answer("Событие не найдено.", show_alert=True)
            return
        ok = await event_service.publish_event_now(event_id)
        if ok:
            await callback.message.edit_text(f"✅ Событие #{event_id} успешно опубликовано!")
            await state.clear()
        else:
            await callback.answer(
                "Ошибка при публикации. Проверьте канал (/channel) и права бота.",
                show_alert=True,
            )
        await callback.answer()
        return

    if action == "evt_finish":
        result = await event_service.finish_event(event_id)
        if result is None:
            await callback.answer("Событие не найдено или уже завершено.", show_alert=True)
        else:
            winners, edit_success = result
            if not winners:
                await callback.message.answer("Событие завершено. Участников не было.")
            else:
                winners_str = "\n".join(
                    f"• <a href='tg://user?id={wid}'>{wid}</a>" for wid in winners
                )
                resp = f"Событие #{event_id} завершено!\nПобедители:\n{winners_str}"
                if not edit_success:
                    resp += "\n\n⚠️ Не удалось отредактировать пост в канале."
                await callback.message.answer(resp)
            await state.clear()
        await callback.answer()
        return

    if action == "evt_edit_winners":
        await callback.message.edit_text("Введите новое количество победителей (число) или /cancel:")
        await state.set_state(ListManageStates.editing_winners)
        await callback.answer()
        return

    if action == "evt_edit_participants":
        await callback.message.edit_text("Введите новый лимит участников (число) или /cancel:")
        await state.set_state(ListManageStates.editing_participants)
        await callback.answer()
        return

    if action == "evt_edit_button":
        await callback.message.edit_text("Введите новый текст кнопки участия (или /cancel):")
        await state.set_state(ListManageStates.editing_button_text)
        await callback.answer()
        return

    if action == "evt_toggle_counter":
        async with event_service.db.acquire() as conn:
            await conn.execute(
                "UPDATE events SET show_participants_counter = NOT show_participants_counter WHERE event_id=$1",
                event_id,
            )
        text, markup = await _get_manage_menu_content(event_id, event_service)
        await callback.message.edit_text(text, reply_markup=markup)
        await callback.answer()
        return

    if action == "evt_additional":
        await _show_additional_menu(callback.message, event_id, event_service)
        await state.set_state(ListManageStates.additional_menu)
        await callback.answer()
        return

    await callback.answer()


# ─── Text input handlers (edit winners, participants, button) ────────────────


@list_manage_router.message(ListManageStates.editing_winners, F.text)
async def on_edit_winners_input(
    message: types.Message, state: FSMContext, event_service: EventService, **kwargs
):
    """Handle new max_winners value input."""
    data_ = await state.get_data()
    event_id = data_["chosen_event_id"]

    if message.text == "/cancel":
        text, markup = await _get_manage_menu_content(event_id, event_service)
        await message.answer(text, reply_markup=markup)
        await state.set_state(ListManageStates.managing_event)
        return

    if not message.text.isdigit():
        await message.answer("Введите число или /cancel:")
        return

    new_val = int(message.text.strip())
    async with event_service.db.acquire() as conn:
        await conn.execute(
            "UPDATE events SET max_winners=$1 WHERE event_id=$2", new_val, event_id
        )
    await message.answer(f"Теперь кол-во победителей: {new_val}.")
    text, markup = await _get_manage_menu_content(event_id, event_service)
    await message.answer(text, reply_markup=markup)
    await state.set_state(ListManageStates.managing_event)


@list_manage_router.message(ListManageStates.editing_participants, F.text)
async def on_edit_participants_input(
    message: types.Message, state: FSMContext, event_service: EventService, **kwargs
):
    """Handle new max_tickets (participant limit) input."""
    data_ = await state.get_data()
    event_id = data_["chosen_event_id"]

    if message.text == "/cancel":
        text, markup = await _get_manage_menu_content(event_id, event_service)
        await message.answer(text, reply_markup=markup)
        await state.set_state(ListManageStates.managing_event)
        return

    if not message.text.isdigit():
        await message.answer("Введите число или /cancel:")
        return

    new_val = int(message.text.strip())
    async with event_service.db.acquire() as conn:
        await conn.execute(
            "UPDATE events SET max_tickets=$1 WHERE event_id=$2", new_val, event_id
        )
    await message.answer(f"Лимит участников теперь: {new_val}")
    text, markup = await _get_manage_menu_content(event_id, event_service)
    await message.answer(text, reply_markup=markup)
    await state.set_state(ListManageStates.managing_event)


@list_manage_router.message(ListManageStates.editing_button_text, F.text)
async def on_edit_button_text_input(
    message: types.Message, state: FSMContext, event_service: EventService, **kwargs
):
    """Handle new button text input."""
    data_ = await state.get_data()
    event_id = data_["chosen_event_id"]

    if message.text == "/cancel":
        text, markup = await _get_manage_menu_content(event_id, event_service)
        await message.answer(text, reply_markup=markup)
        await state.set_state(ListManageStates.managing_event)
        return

    new_text = message.text.strip()
    async with event_service.db.acquire() as conn:
        await conn.execute(
            "UPDATE events SET participation_button_text=$1 WHERE event_id=$2",
            new_text, event_id,
        )
    await message.answer("Текст кнопки обновлён!")
    text, markup = await _get_manage_menu_content(event_id, event_service)
    await message.answer(text, reply_markup=markup)
    await state.set_state(ListManageStates.managing_event)


# ─── Additional menu callbacks ───────────────────────────────────────────────


@list_manage_router.callback_query(ListManageStates.additional_menu)
async def on_additional_menu(
    callback: types.CallbackQuery, state: FSMContext, event_service: EventService, **kwargs
):
    """Handle additional functions sub-menu actions."""
    data_ = await state.get_data()
    event_id = data_.get("chosen_event_id")
    action = callback.data

    if action == "addf_back":
        text, markup = await _get_manage_menu_content(event_id, event_service)
        await callback.message.edit_text(text, reply_markup=markup)
        await state.set_state(ListManageStates.managing_event)

    elif action == "addf_autobytes":
        await _show_autobytes_menu(callback.message, event_id, event_service)
        await state.set_state(ListManageStates.autobytes_menu)

    elif action == "addf_notify":
        async with event_service.db.acquire() as conn:
            await conn.execute(
                "UPDATE events SET notify_winners = NOT notify_winners WHERE event_id=$1",
                event_id,
            )
        await _show_additional_menu(callback.message, event_id, event_service)

    elif action == "addf_hidebtn":
        async with event_service.db.acquire() as conn:
            await conn.execute(
                "UPDATE events SET hide_button_after_finish = NOT hide_button_after_finish WHERE event_id=$1",
                event_id,
            )
        await _show_additional_menu(callback.message, event_id, event_service)

    elif action == "addf_sponsor":
        await _show_sponsor_menu(callback.message, event_id, event_service)
        await state.set_state(ListManageStates.sponsor_menu)

    elif action == "addf_share":
        await callback.message.edit_text(
            "Введите @username (или ID) канала, куда расшарить, или /cancel:"
        )
        await state.set_state(ListManageStates.share_menu)

    elif action == "addf_restore":
        ok = await event_service.restore_event(event_id)
        if ok:
            await callback.message.answer(
                f"✅ Конкурс #{event_id} успешно восстановлен и заново опубликован!"
            )
        else:
            await callback.message.answer(f"❌ Не удалось восстановить конкурс #{event_id}.")
        await _show_additional_menu(callback.message, event_id, event_service)

    elif action == "addf_participants":
        participants = await event_service.get_participants(event_id)
        if not participants:
            await callback.message.answer("Участников пока нет.")
        else:
            event = await event_service.get_event(event_id)
            e_type = event["event_type"] if event else "contest"
            txt = "🧾 <b>Список участников</b>:\n"
            for p in participants:
                uid = p["user_id"]
                if e_type == "lottery":
                    txt += f" - <a href='tg://user?id={uid}'>{uid}</a>, билет №{p.get('ticket_number', 0)}\n"
                elif e_type == "referral":
                    txt += f" - <a href='tg://user?id={uid}'>{uid}</a>, рефералов: {p.get('referral_count', 0)}\n"
                else:
                    txt += f" - <a href='tg://user?id={uid}'>{uid}</a>\n"
            await callback.message.answer(txt)

    await callback.answer()


# ─── Autobytes menu callbacks ────────────────────────────────────────────────


@list_manage_router.callback_query(ListManageStates.autobytes_menu)
async def on_autobytes_callback(
    callback: types.CallbackQuery, state: FSMContext, event_service: EventService, **kwargs
):
    """Handle auto-bytes setting toggles and interval editing."""
    data_ = await state.get_data()
    event_id = data_.get("chosen_event_id")
    action = callback.data

    if action == "ab_toggle":
        async with event_service.db.acquire() as conn:
            await conn.execute(
                "UPDATE events SET auto_bytes = NOT auto_bytes WHERE event_id=$1", event_id
            )

    elif action == "ab_notify":
        async with event_service.db.acquire() as conn:
            await conn.execute(
                "UPDATE events SET auto_bytes_notify = NOT auto_bytes_notify WHERE event_id=$1",
                event_id,
            )

    elif action == "ab_interval":
        await callback.message.answer("Укажите новый интервал (минуты) или /cancel:")
        await state.set_state(ListManageStates.editing_autobytes_interval)
        await callback.answer()
        return

    elif action == "ab_back":
        await _show_additional_menu(callback.message, event_id, event_service)
        await state.set_state(ListManageStates.additional_menu)
        await callback.answer()
        return

    await _show_autobytes_menu(callback.message, event_id, event_service)
    await callback.answer()


@list_manage_router.message(ListManageStates.editing_autobytes_interval, F.text)
async def on_autobytes_interval_input(
    message: types.Message, state: FSMContext, event_service: EventService, **kwargs
):
    """Handle auto-bytes interval value input."""
    data_ = await state.get_data()
    event_id = data_["chosen_event_id"]

    if message.text == "/cancel":
        await _show_autobytes_menu(message, event_id, event_service)
        await state.set_state(ListManageStates.autobytes_menu)
        return

    if not message.text.isdigit():
        await message.answer("Введите число минут (целое) или /cancel:")
        return

    interval = int(message.text)
    async with event_service.db.acquire() as conn:
        await conn.execute(
            "UPDATE events SET byte_interval=$1 WHERE event_id=$2", interval, event_id
        )
    await message.answer(f"Интервал авто-байтов установлен: {interval} мин.")
    await _show_autobytes_menu(message, event_id, event_service)
    await state.set_state(ListManageStates.autobytes_menu)


# ─── Sponsor menu callbacks ──────────────────────────────────────────────────


@list_manage_router.callback_query(ListManageStates.sponsor_menu)
async def on_sponsor_menu_callback(
    callback: types.CallbackQuery, state: FSMContext, event_service: EventService, **kwargs
):
    """Handle sponsor menu actions."""
    data_ = await state.get_data()
    event_id = data_.get("chosen_event_id")
    action = callback.data

    if action == "sponsor_back":
        await _show_additional_menu(callback.message, event_id, event_service)
        await state.set_state(ListManageStates.additional_menu)

    elif action == "sponsor_add":
        await callback.message.answer("Введите @username спонсора или /cancel:")
        await state.set_state(ListManageStates.sponsor_adding)

    elif action == "sponsor_del":
        await callback.message.answer("Введите ID спонсора (число) или /cancel:")
        await state.set_state(ListManageStates.sponsor_deleting)

    await callback.answer()


@list_manage_router.message(ListManageStates.sponsor_adding, F.text)
async def on_sponsor_add_input(
    message: types.Message, state: FSMContext, event_service: EventService, **kwargs
):
    """Handle sponsor username input for adding."""
    data_ = await state.get_data()
    event_id = data_["chosen_event_id"]

    if message.text == "/cancel":
        await _show_sponsor_menu(message, event_id, event_service)
        await state.set_state(ListManageStates.sponsor_menu)
        return

    username = message.text.strip().lstrip("@")
    await event_service.add_sponsor(event_id, username)
    await message.answer(f"Спонсор @{username} добавлен.")
    await _show_sponsor_menu(message, event_id, event_service)
    await state.set_state(ListManageStates.sponsor_menu)


@list_manage_router.message(ListManageStates.sponsor_deleting, F.text)
async def on_sponsor_del_input(
    message: types.Message, state: FSMContext, event_service: EventService, **kwargs
):
    """Handle sponsor ID input for deletion."""
    data_ = await state.get_data()
    event_id = data_["chosen_event_id"]

    if message.text == "/cancel":
        await _show_sponsor_menu(message, event_id, event_service)
        await state.set_state(ListManageStates.sponsor_menu)
        return

    if not message.text.isdigit():
        await message.answer("Нужно число! Введите ID или /cancel:")
        return

    s_id = int(message.text)
    await event_service.remove_sponsor(s_id)
    await message.answer(f"Спонсор с ID {s_id} удалён.")
    await _show_sponsor_menu(message, event_id, event_service)
    await state.set_state(ListManageStates.sponsor_menu)


# ─── Share menu callback ─────────────────────────────────────────────────────


@list_manage_router.message(ListManageStates.share_menu, F.text)
async def on_share_input(
    message: types.Message, state: FSMContext, event_service: EventService, **kwargs
):
    """Handle channel input for sharing event."""
    data_ = await state.get_data()
    event_id = data_["chosen_event_id"]

    if message.text == "/cancel":
        await _show_additional_menu(message, event_id, event_service)
        await state.set_state(ListManageStates.additional_menu)
        return

    channel_username = message.text.strip()
    # Re-publish the event to the specified channel
    event = await event_service.get_event(event_id)
    if event:
        try:
            post_text = event.get("description", "")
            btn_text = event.get("participation_button_text", "Участвовать!")
            markup = types.InlineKeyboardMarkup(inline_keyboard=[
                [types.InlineKeyboardButton(text=btn_text, callback_data=f"join_event:{event_id}")]
            ])
            await event_service.bot.send_message(
                chat_id=channel_username, text=post_text, reply_markup=markup
            )
            await message.answer(f"Событие #{event_id} опубликовано дополнительно в {channel_username}!")
        except Exception:
            await message.answer("Ошибка при публикации. Проверьте username и права бота.")
    else:
        await message.answer("Событие не найдено.")

    await _show_additional_menu(message, event_id, event_service)
    await state.set_state(ListManageStates.additional_menu)
