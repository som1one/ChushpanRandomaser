"""Contest wizard handler — multi-step FSM flow for creating contest events."""

import datetime
import logging
from zoneinfo import ZoneInfo

from aiogram import Router, types, F
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext

from app.states import LotMenuStates
from app.utils.helpers import (
    get_future_time_examples,
    is_bot_admin_in_channel,
    parse_channel_username_from_message,
)

lot_contest_router = Router()


async def _update_event_property(event_service, event_id: int, prop_name: str, prop_value):
    """Helper to update a single event property in the database."""
    async with event_service.db.acquire() as conn:
        query = f"UPDATE events SET {prop_name}=$1 WHERE event_id=$2"
        await conn.execute(query, prop_value, event_id)


async def _lot_cancel(callback: types.CallbackQuery, state: FSMContext):
    """Cancel current input and return to event type selection."""
    await state.clear()
    kb = types.InlineKeyboardMarkup(inline_keyboard=[
        [
            types.InlineKeyboardButton(text="🎉 Конкурс", callback_data="lot_type:contest"),
            types.InlineKeyboardButton(text="🍀 Лотерея", callback_data="lot_type:lottery"),
            types.InlineKeyboardButton(text="🔗 Реферальный", callback_data="lot_type:referral"),
        ]
    ])
    await callback.message.edit_text("Выберите тип события:", reply_markup=kb)
    await state.set_state(LotMenuStates.choosing_type)
    await callback.answer()


# ─── Step 1: Text/Media ──────────────────────────────────────────────────────


@lot_contest_router.message(
    LotMenuStates.waiting_for_contest_text,
    F.content_type.in_({"text", "photo", "animation", "video"}),
)
async def contest_media_entered(message: types.Message, state: FSMContext):
    """Capture contest text and optional media attachment."""
    media_id = None
    media_type = None
    if message.photo:
        media_id = message.photo[-1].file_id
        media_type = "photo"
    elif message.animation:
        media_id = message.animation.file_id
        media_type = "animation"
    elif message.video:
        media_id = message.video.file_id
        media_type = "video"

    text_contest = message.caption or message.text or "(без текста)"
    await state.update_data(
        contest_media_id=media_id,
        contest_media_type=media_type,
        contest_text=text_contest,
    )

    kb = types.InlineKeyboardMarkup(inline_keyboard=[
        [
            types.InlineKeyboardButton(text="Ввести число участников", callback_data="contest_by_users"),
            types.InlineKeyboardButton(text="Завершить по времени", callback_data="contest_by_time"),
        ],
        [types.InlineKeyboardButton(text="Отменить ввод", callback_data="lot_cancel")],
    ])
    await message.answer("✅ Сохранено, выберите, как завершить конкурс:", reply_markup=kb)
    await state.set_state(LotMenuStates.waiting_for_contest_participants)


# ─── Step 2: Finish Mode ─────────────────────────────────────────────────────


@lot_contest_router.callback_query(
    StateFilter(LotMenuStates.waiting_for_contest_participants),
    F.data.in_({"contest_by_users", "contest_by_time", "lot_cancel"}),
)
async def contest_participants_or_time(callback: types.CallbackQuery, state: FSMContext):
    """Choose finish mode: by participant count or by time."""
    if callback.data == "lot_cancel":
        await _lot_cancel(callback, state)
        return

    kb_cancel = types.InlineKeyboardMarkup(
        inline_keyboard=[[types.InlineKeyboardButton(text="Отменить ввод", callback_data="lot_cancel")]]
    )

    if callback.data == "contest_by_users":
        await callback.message.edit_text(
            "❗️ Если нужно завершить вручную, введите большое число.\n"
            "Отправьте максимальное число участников:",
            reply_markup=kb_cancel,
        )
        await state.update_data(contest_finish_mode="by_users")
    else:
        text = "💠 Отправьте дату окончания конкурса в формате `ДД.ММ.ГГГГ ЧЧ:ММ:СС`"
        text += get_future_time_examples()
        await callback.message.edit_text(text, reply_markup=kb_cancel, parse_mode="Markdown")
        await state.update_data(contest_finish_mode="by_time")

    await state.set_state(LotMenuStates.contest_waiting_for_finish_value)
    await callback.answer()


@lot_contest_router.message(StateFilter(LotMenuStates.contest_waiting_for_finish_value))
async def contest_finish_value_entered(message: types.Message, state: FSMContext):
    """Process the finish condition value (participant count or datetime)."""
    data = await state.get_data()
    mode = data.get("contest_finish_mode")

    if mode == "by_users":
        if not message.text or not message.text.isdigit():
            await message.answer("Введите число или /cancel.")
            return
        await state.update_data(contest_max_users=int(message.text))
    else:
        try:
            dt_naive = datetime.datetime.strptime(message.text.strip(), "%d.%m.%Y %H:%M:%S")
            dt_aware = dt_naive.replace(tzinfo=ZoneInfo("Europe/Kyiv"))
            await state.update_data(contest_finish_time=dt_aware.isoformat())
        except (ValueError, AttributeError):
            await message.answer(
                "Неверный формат даты! Пример: `08.06.2025 14:30:00`", parse_mode="Markdown"
            )
            return

    kb_cancel = types.InlineKeyboardMarkup(
        inline_keyboard=[[types.InlineKeyboardButton(text="Отменить ввод", callback_data="lot_cancel")]]
    )
    await message.answer("🎗 Введите количество победителей (1-50):", reply_markup=kb_cancel)
    await state.set_state(LotMenuStates.waiting_for_contest_winners)


# ─── Step 3: Winners Count ───────────────────────────────────────────────────


@lot_contest_router.message(StateFilter(LotMenuStates.waiting_for_contest_winners))
async def contest_winners_entered(
    message: types.Message,
    state: FSMContext,
    event_service,
    **kwargs,
):
    """Receive winner count, create the event in DB, proceed to sponsors."""
    if not message.text or not message.text.isdigit():
        await message.answer("Введите число или /cancel.")
        return

    w = int(message.text)
    if not (1 <= w <= 50):
        await message.answer("От 1 до 50!")
        return

    await state.update_data(contest_winners=w)
    data = await state.get_data()

    finish_time = None
    if data.get("contest_finish_time"):
        finish_time = datetime.datetime.fromisoformat(data["contest_finish_time"])

    evt_id = await event_service.create_event(
        creator_id=message.from_user.id,
        channel_id=0,
        event_type="contest",
        title=(data.get("contest_text", "Без описания"))[:50],
        description=data.get("contest_text", "Без описания"),
        max_winners=w,
        media_id=data.get("contest_media_id"),
        media_type=data.get("contest_media_type"),
        max_tickets=data.get("contest_max_users"),
        finish_at=finish_time,
    )
    await state.update_data(contest_event_id=evt_id)

    bot_info = await message.bot.get_me()
    kb = types.InlineKeyboardMarkup(inline_keyboard=[
        [
            types.InlineKeyboardButton(
                text="Добавить бота на канал",
                url=f"http://t.me/{bot_info.username}?startchannel=true",
            )
        ],
        [types.InlineKeyboardButton(text="Без спонсоров", callback_data="contest_sponsors_done")],
    ])
    await message.answer(
        f"✅ Конкурс #{evt_id} создан!\n\n"
        "Отправьте каналы-спонсоры или нажмите 'Без спонсоров'.",
        reply_markup=kb,
    )
    await state.set_state(LotMenuStates.waiting_for_contest_sponsors)


# ─── Step 4: Sponsors ────────────────────────────────────────────────────────


@lot_contest_router.message(
    StateFilter(LotMenuStates.waiting_for_contest_sponsors),
    F.content_type.in_({"text", "photo", "video"}),
)
async def contest_sponsor_entered(
    message: types.Message,
    state: FSMContext,
    event_service,
    **kwargs,
):
    """Add a sponsor channel to the event."""
    sponsor_raw = parse_channel_username_from_message(message)
    if not sponsor_raw:
        await message.answer(
            "Неверный формат канала! Отправьте @username, ссылку t.me/ или перешлите пост из канала."
        )
        return

    data = await state.get_data()
    event_id = data.get("contest_event_id")
    if not event_id:
        await message.answer("Ошибка: не найден ID события. Начните заново.")
        await state.clear()
        return

    is_admin, err_msg = await is_bot_admin_in_channel(sponsor_raw, message.bot)
    if not is_admin:
        await message.answer(f"Бот не является администратором в {sponsor_raw}.\n{err_msg}")
        return

    await event_service.add_sponsor(event_id, sponsor_raw.lstrip("@"))
    kb = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="Достаточно спонсоров", callback_data="contest_sponsors_done")]
    ])
    await message.answer(
        f"✅ Спонсор {sponsor_raw} добавлен.\nДобавьте ещё или нажмите 'Достаточно'.",
        reply_markup=kb,
    )


@lot_contest_router.callback_query(
    StateFilter(LotMenuStates.waiting_for_contest_sponsors),
    F.data == "contest_sponsors_done",
)
async def contest_sponsors_done(callback: types.CallbackQuery, state: FSMContext):
    """All sponsors added — proceed to vote channel required step."""
    await _proceed_to_vote_required(callback.message, state)
    await callback.answer()


# ─── Step 5: Vote Channel Required ──────────────────────────────────────────


async def _proceed_to_vote_required(message: types.Message, state: FSMContext):
    """Ask whether subscription to the publishing channel is required."""
    kb = types.InlineKeyboardMarkup(inline_keyboard=[
        [
            types.InlineKeyboardButton(text="Да", callback_data="contest_vote_yes"),
            types.InlineKeyboardButton(text="Нет", callback_data="contest_vote_no"),
        ]
    ])
    await message.answer(
        "⭐️ Требовать «голос за канал» (подписку на основной канал) для участия?",
        reply_markup=kb,
    )
    await state.set_state(LotMenuStates.waiting_for_contest_vote_required)


@lot_contest_router.callback_query(
    StateFilter(LotMenuStates.waiting_for_contest_vote_required),
    F.data.in_({"contest_vote_yes", "contest_vote_no"}),
)
async def contest_vote_required_cb(
    callback: types.CallbackQuery,
    state: FSMContext,
    event_service,
    **kwargs,
):
    """Save vote_channel_required, proceed to button text."""
    data = await state.get_data()
    event_id = data.get("contest_event_id")
    vote_required = callback.data == "contest_vote_yes"

    if event_id:
        await _update_event_property(event_service, event_id, "vote_channel_required", vote_required)

    kb = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="Слово «Участвую»", callback_data="contest_btn_word")],
        [types.InlineKeyboardButton(text="Массив билетов", callback_data="contest_btn_tickets")],
    ])
    await callback.message.answer(
        "✳️ Отправьте текст для кнопки или используйте стандартный вариант.",
        reply_markup=kb,
    )
    await state.set_state(LotMenuStates.waiting_for_contest_button_text)
    await callback.answer()


# ─── Step 6: Button Text ─────────────────────────────────────────────────────


@lot_contest_router.callback_query(
    StateFilter(LotMenuStates.waiting_for_contest_button_text),
    F.data.in_({"contest_btn_word", "contest_btn_tickets"}),
)
async def contest_button_choice(
    callback: types.CallbackQuery,
    state: FSMContext,
    event_service,
    **kwargs,
):
    """Handle preset button text choices."""
    data = await state.get_data()
    event_id = data.get("contest_event_id")

    if callback.data == "contest_btn_word":
        if event_id:
            await _update_event_property(event_service, event_id, "participation_button_text", "Участвую")
            await _update_event_property(event_service, event_id, "button_style", "single")
    elif callback.data == "contest_btn_tickets":
        if event_id:
            await _update_event_property(event_service, event_id, "participation_button_text", "🗒 Билеты")
            await _update_event_property(event_service, event_id, "button_style", "grid")

    await _ask_schedule_time(callback.message, state)
    await callback.answer()


@lot_contest_router.message(
    StateFilter(LotMenuStates.waiting_for_contest_button_text),
    F.text,
)
async def contest_button_word_entered(
    message: types.Message,
    state: FSMContext,
    event_service,
    **kwargs,
):
    """Handle custom button text input."""
    custom_btn = message.text.strip()
    if not custom_btn:
        await message.answer("Текст кнопки не может быть пустым.")
        return

    data = await state.get_data()
    event_id = data.get("contest_event_id")
    if event_id:
        await _update_event_property(event_service, event_id, "participation_button_text", custom_btn)
        await _update_event_property(event_service, event_id, "button_style", "single")

    await _ask_schedule_time(message, state)


# ─── Step 7: Schedule ────────────────────────────────────────────────────────


async def _ask_schedule_time(message: types.Message, state: FSMContext):
    """Ask when to publish the contest."""
    kb = types.InlineKeyboardMarkup(inline_keyboard=[
        [
            types.InlineKeyboardButton(text="Запланировать", callback_data="contest_schedule_plan"),
            types.InlineKeyboardButton(text="Опубликовать вручную", callback_data="contest_schedule_manual"),
        ]
    ])
    await message.answer("🕑 Когда публикуем конкурс?", reply_markup=kb)
    await state.set_state(LotMenuStates.waiting_for_contest_schedule)


@lot_contest_router.callback_query(
    StateFilter(LotMenuStates.waiting_for_contest_schedule),
    F.data.in_({"contest_schedule_plan", "contest_schedule_manual"}),
)
async def contest_schedule_cb(
    callback: types.CallbackQuery,
    state: FSMContext,
    channel_service,
    **kwargs,
):
    """Handle schedule choice: plan for later or show publication preview now."""
    user_id = callback.from_user.id
    if callback.data == "contest_schedule_plan":
        text = "💠 Отправьте дату публикации в формате `ДД.ММ.ГГГГ ЧЧ:ММ:СС`"
        text += get_future_time_examples()
        await callback.message.edit_text(text, parse_mode="Markdown")
        await state.set_state(LotMenuStates.contest_waiting_for_plan_time)
    else:
        await _show_publication_preview(callback.message, state, channel_service, user_id)
    await callback.answer()


@lot_contest_router.message(
    StateFilter(LotMenuStates.contest_waiting_for_plan_time),
    F.text,
)
async def contest_plan_time_entered(
    message: types.Message,
    state: FSMContext,
    channel_service,
    **kwargs,
):
    """Parse scheduled publish datetime and show preview."""
    try:
        dt_naive = datetime.datetime.strptime(message.text.strip(), "%d.%m.%Y %H:%M:%S")
        dt_aware = dt_naive.replace(tzinfo=ZoneInfo("Europe/Kyiv"))
        await state.update_data(contest_plan_time=dt_aware.isoformat())
    except (ValueError, AttributeError):
        await message.answer(
            "Неверный формат даты! Пример: `08.06.2025 14:30:00`", parse_mode="Markdown"
        )
        return

    await _show_publication_preview(message, state, channel_service, message.from_user.id)


# ─── Step 8: Publish ─────────────────────────────────────────────────────────


async def _show_publication_preview(
    message: types.Message,
    state: FSMContext,
    channel_service,
    user_id: int,
):
    """Show contest publication preview with action buttons."""
    data = await state.get_data()
    event_id = data.get("contest_event_id")

    channel = await channel_service.get_active_channel(user_id)
    channel_text = f"@{channel['username']}" if channel else "Канал не выбран!"

    plan_time_iso = data.get("contest_plan_time")
    plan_time_str = (
        datetime.datetime.fromisoformat(plan_time_iso).strftime("%d.%m.%Y %H:%M:%S")
        if plan_time_iso
        else "(не запланировано)"
    )

    text = (
        f"🎊 Конкурс (unpublished) #{event_id}!\n\n"
        f"📤 Публикуем в: {channel_text}\n"
        f"Время публикации: {plan_time_str}\n\n"
        "Доступные действия:"
    )
    kb = types.InlineKeyboardMarkup(inline_keyboard=[
        [
            types.InlineKeyboardButton(text="Опубликовать сейчас", callback_data="contest_pub_now"),
            types.InlineKeyboardButton(text="Изменить канал", callback_data="contest_pub_channel"),
        ],
        [
            types.InlineKeyboardButton(text="Изменить время", callback_data="contest_pub_time"),
            types.InlineKeyboardButton(text="Добавить условие", callback_data="contest_pub_condition"),
        ],
    ])
    await message.answer(text, reply_markup=kb)
    await state.set_state(LotMenuStates.waiting_for_contest_publication)


@lot_contest_router.callback_query(StateFilter(LotMenuStates.waiting_for_contest_publication))
async def contest_publication_menu(
    callback: types.CallbackQuery,
    state: FSMContext,
    event_service,
    channel_service,
    **kwargs,
):
    """Handle publication preview actions: publish, change channel/time, add condition."""
    data = await state.get_data()
    event_id = data.get("contest_event_id")
    action = callback.data

    if action == "contest_pub_now":
        # Set scheduled publish time if planned
        plan_time_iso = data.get("contest_plan_time")
        if plan_time_iso:
            dt = datetime.datetime.fromisoformat(plan_time_iso)
            await _update_event_property(event_service, event_id, "scheduled_publish_at", dt)

        # Set channel from active channel
        user_id = callback.from_user.id
        channel = await channel_service.get_active_channel(user_id)
        if channel:
            await _update_event_property(event_service, event_id, "channel_id", channel["channel_id"])

        ok = await event_service.publish_event_now(event_id)
        await callback.message.answer("Конкурс опубликован!" if ok else "Ошибка публикации.")
        await state.clear()

    elif action == "contest_pub_channel":
        await callback.message.answer("Для смены канала используйте /channel")

    elif action == "contest_pub_time":
        text = "💠 Отправьте новую дату публикации:"
        text += get_future_time_examples()
        await callback.message.edit_text(text, parse_mode="Markdown")
        await state.set_state(LotMenuStates.contest_waiting_for_plan_time)

    elif action == "contest_pub_condition":
        await callback.message.edit_text("➕ Укажите ID другого конкурса (условие):")
        await state.set_state(LotMenuStates.contest_waiting_for_cond_id)

    await callback.answer()


# ─── Condition ID Step ────────────────────────────────────────────────────────


@lot_contest_router.message(StateFilter(LotMenuStates.contest_waiting_for_cond_id), F.text)
async def contest_condition_id_entered(
    message: types.Message,
    state: FSMContext,
    event_service,
    channel_service,
    **kwargs,
):
    """Add a prerequisite event condition."""
    if not message.text.isdigit():
        await message.answer("Нужен числовой ID!")
        return

    cond_id = int(message.text)
    data = await state.get_data()
    event_id = data.get("contest_event_id")

    if event_id == cond_id:
        await message.answer("Нельзя ссылаться на то же самое событие!")
        return

    ok = await event_service.add_condition(event_id, cond_id)
    await message.answer("Условие добавлено." if ok else "Не удалось добавить условие.")
    await _show_publication_preview(message, state, channel_service, message.from_user.id)
