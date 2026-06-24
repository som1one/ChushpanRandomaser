"""Handler for referral contest creation wizard (FSM flow)."""

import datetime
from zoneinfo import ZoneInfo

from aiogram import Router, types, F
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext

from app.states import LotMenuStates
from app.utils.helpers import get_future_time_examples, is_bot_admin_in_channel, parse_channel_username_from_message

lot_referral_router = Router()


@lot_referral_router.message(
    LotMenuStates.waiting_for_ref_text,
    F.content_type.in_({"text", "photo", "animation", "video"}),
)
async def ref_text_entered(message: types.Message, state: FSMContext):
    """Receive referral contest text/media and ask for finish mode."""
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

    text_ref = message.caption or message.text or "(без текста)"
    await state.update_data(
        ref_media_id=media_id,
        ref_media_type=media_type,
        ref_text=text_ref,
    )

    kb = types.InlineKeyboardMarkup(inline_keyboard=[
        [
            types.InlineKeyboardButton(text="Ввести число участников", callback_data="ref_by_users"),
            types.InlineKeyboardButton(text="Завершить по времени", callback_data="ref_by_time"),
        ],
        [types.InlineKeyboardButton(text="Отменить ввод", callback_data="ref_cancel")],
    ])
    await message.answer("✅ Сохранено. Выберите, как завершить реферальный конкурс:", reply_markup=kb)
    await state.set_state(LotMenuStates.waiting_for_ref_participants)


@lot_referral_router.callback_query(
    StateFilter(LotMenuStates.waiting_for_ref_participants),
    F.data.in_({"ref_by_users", "ref_by_time", "ref_cancel"}),
)
async def ref_finish_mode_chosen(callback: types.CallbackQuery, state: FSMContext):
    """Handle finish mode selection: by participants or by time."""
    if callback.data == "ref_cancel":
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
        return

    kb_cancel = types.InlineKeyboardMarkup(
        inline_keyboard=[[types.InlineKeyboardButton(text="Отменить ввод", callback_data="ref_cancel")]]
    )

    if callback.data == "ref_by_users":
        await callback.message.edit_text(
            "❗️ Если нужно завершить вручную, введите большое число.\n"
            "Отправьте максимальное число участников:",
            reply_markup=kb_cancel,
        )
        await state.update_data(ref_finish_mode="by_users")
    else:
        text = "💠 Отправьте дату окончания в формате `ДД.ММ.ГГГГ ЧЧ:ММ:СС`"
        text += get_future_time_examples()
        await callback.message.edit_text(text, reply_markup=kb_cancel, parse_mode="Markdown")
        await state.update_data(ref_finish_mode="by_time")

    await state.set_state(LotMenuStates.ref_waiting_for_finish_value)
    await callback.answer()


@lot_referral_router.message(StateFilter(LotMenuStates.ref_waiting_for_finish_value))
async def ref_finish_value_entered(message: types.Message, state: FSMContext):
    """Parse finish value (participant count or datetime)."""
    data = await state.get_data()
    mode = data.get("ref_finish_mode")

    if mode == "by_users":
        if not message.text or not message.text.strip().isdigit():
            await message.answer("Введите число или /cancel.")
            return
        await state.update_data(ref_max_users=int(message.text.strip()))
    else:
        try:
            dt_naive = datetime.datetime.strptime(message.text.strip(), "%d.%m.%Y %H:%M:%S")
            dt_aware = dt_naive.replace(tzinfo=ZoneInfo("Europe/Kyiv"))
            await state.update_data(ref_finish_time=dt_aware.isoformat())
        except ValueError:
            await message.answer("Неверный формат даты! Пример: `08.06.2025 14:30:00`", parse_mode="Markdown")
            return

    kb_cancel = types.InlineKeyboardMarkup(
        inline_keyboard=[[types.InlineKeyboardButton(text="Отменить ввод", callback_data="ref_cancel")]]
    )
    await message.answer("🎗 Введите количество победителей (1-50):", reply_markup=kb_cancel)
    await state.set_state(LotMenuStates.waiting_for_ref_winners)


@lot_referral_router.message(StateFilter(LotMenuStates.waiting_for_ref_winners))
async def ref_winners_entered(message: types.Message, state: FSMContext, event_service):
    """Create the referral event and proceed to sponsors step."""
    if not message.text or not message.text.strip().isdigit():
        await message.answer("Введите число или /cancel.")
        return

    w = int(message.text.strip())
    if not (1 <= w <= 50):
        await message.answer("От 1 до 50!")
        return

    await state.update_data(ref_winners=w)
    data = await state.get_data()

    finish_at = None
    if data.get("ref_finish_time"):
        finish_at = datetime.datetime.fromisoformat(data["ref_finish_time"])

    evt_id = await event_service.create_event(
        creator_id=message.from_user.id,
        channel_id=0,
        event_type="referral",
        title=data.get("ref_text", "Без описания")[:50],
        description=data.get("ref_text", "Без описания"),
        max_winners=w,
        media_id=data.get("ref_media_id"),
        media_type=data.get("ref_media_type"),
        max_tickets=data.get("ref_max_users"),
        finish_at=finish_at,
    )
    await state.update_data(ref_event_id=evt_id)

    bot_info = await message.bot.get_me()
    kb = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(
            text="Добавить бота на канал",
            url=f"http://t.me/{bot_info.username}?startchannel=true",
        )],
        [types.InlineKeyboardButton(text="Без спонсоров", callback_data="ref_sponsors_done")],
    ])
    await message.answer(
        f"✅ Реферальный конкурс #{evt_id} создан!\n\n"
        "Отправьте каналы-спонсоры или нажмите 'Без спонсоров'.",
        reply_markup=kb,
    )
    await state.set_state(LotMenuStates.waiting_for_ref_sponsors)


@lot_referral_router.message(
    StateFilter(LotMenuStates.waiting_for_ref_sponsors),
    F.content_type.in_({"text", "photo", "video"}),
)
async def ref_sponsor_entered(message: types.Message, state: FSMContext, event_service):
    """Add a sponsor channel to the referral event."""
    sponsor_raw = parse_channel_username_from_message(message)
    if not sponsor_raw:
        await message.answer(
            "Неверный формат канала! Отправьте @username, ссылку t.me/ или перешлите пост из канала."
        )
        return

    data = await state.get_data()
    event_id = data.get("ref_event_id")
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
        [types.InlineKeyboardButton(text="Достаточно спонсоров", callback_data="ref_sponsors_done")]
    ])
    await message.answer(
        f"✅ Спонсор {sponsor_raw} добавлен.\nДобавьте ещё или нажмите 'Достаточно'.",
        reply_markup=kb,
    )


@lot_referral_router.callback_query(
    StateFilter(LotMenuStates.waiting_for_ref_sponsors),
    F.data == "ref_sponsors_done",
)
async def ref_sponsors_done(callback: types.CallbackQuery, state: FSMContext):
    """Sponsors step complete — proceed to vote channel requirement."""
    kb = types.InlineKeyboardMarkup(inline_keyboard=[
        [
            types.InlineKeyboardButton(text="Да", callback_data="ref_vote_yes"),
            types.InlineKeyboardButton(text="Нет", callback_data="ref_vote_no"),
        ]
    ])
    await callback.message.answer(
        "⭐️ Требовать «голос за канал» (подписку на основной канал) для участия?",
        reply_markup=kb,
    )
    await state.set_state(LotMenuStates.waiting_for_ref_vote_required)
    await callback.answer()


@lot_referral_router.callback_query(
    StateFilter(LotMenuStates.waiting_for_ref_vote_required),
    F.data.in_({"ref_vote_yes", "ref_vote_no"}),
)
async def ref_vote_required_cb(callback: types.CallbackQuery, state: FSMContext, event_service):
    """Save vote_channel_required and proceed to button text step."""
    data = await state.get_data()
    event_id = data.get("ref_event_id")
    vote_required = callback.data == "ref_vote_yes"

    if event_id:
        async with event_service.db.acquire() as conn:
            await conn.execute(
                "UPDATE events SET vote_channel_required=$1 WHERE event_id=$2",
                vote_required, event_id,
            )

    kb = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="Слово «Участвую»", callback_data="ref_btn_word")],
        [types.InlineKeyboardButton(text="Массив билетов", callback_data="ref_btn_tickets")],
    ])
    await callback.message.answer(
        "✳️ Отправьте текст для кнопки или используйте стандартный вариант.",
        reply_markup=kb,
    )
    await state.set_state(LotMenuStates.waiting_for_ref_button_text)
    await callback.answer()


@lot_referral_router.callback_query(
    StateFilter(LotMenuStates.waiting_for_ref_button_text),
    F.data.in_({"ref_btn_word", "ref_btn_tickets"}),
)
async def ref_button_choice(callback: types.CallbackQuery, state: FSMContext, event_service):
    """Handle preset button choice and proceed to schedule."""
    data = await state.get_data()
    event_id = data.get("ref_event_id")

    if callback.data == "ref_btn_word":
        if event_id:
            async with event_service.db.acquire() as conn:
                await conn.execute(
                    "UPDATE events SET participation_button_text=$1, button_style=$2 WHERE event_id=$3",
                    "Участвую", "single", event_id,
                )
    elif callback.data == "ref_btn_tickets":
        if event_id:
            async with event_service.db.acquire() as conn:
                await conn.execute(
                    "UPDATE events SET participation_button_text=$1, button_style=$2 WHERE event_id=$3",
                    "🗒 Билеты", "grid", event_id,
                )

    await _ask_schedule_time(callback.message, state)
    await callback.answer()


@lot_referral_router.message(StateFilter(LotMenuStates.waiting_for_ref_button_text), F.text)
async def ref_button_text_entered(message: types.Message, state: FSMContext, event_service):
    """Handle custom button text and proceed to schedule."""
    custom_btn = message.text.strip()
    if not custom_btn:
        await message.answer("Текст кнопки не может быть пустым.")
        return

    data = await state.get_data()
    event_id = data.get("ref_event_id")
    if event_id:
        async with event_service.db.acquire() as conn:
            await conn.execute(
                "UPDATE events SET participation_button_text=$1, button_style=$2 WHERE event_id=$3",
                custom_btn, "single", event_id,
            )

    await _ask_schedule_time(message, state)


async def _ask_schedule_time(msg: types.Message, state: FSMContext) -> None:
    """Ask user when to publish the referral contest."""
    kb = types.InlineKeyboardMarkup(inline_keyboard=[
        [
            types.InlineKeyboardButton(text="Запланировать", callback_data="ref_schedule_plan"),
            types.InlineKeyboardButton(text="Опубликовать вручную", callback_data="ref_schedule_manual"),
        ]
    ])
    await msg.answer("🕑 Когда публикуем реферальный конкурс?", reply_markup=kb)
    await state.set_state(LotMenuStates.waiting_for_ref_schedule)


@lot_referral_router.callback_query(
    StateFilter(LotMenuStates.waiting_for_ref_schedule),
    F.data.in_({"ref_schedule_plan", "ref_schedule_manual"}),
)
async def ref_schedule_cb(callback: types.CallbackQuery, state: FSMContext, event_service):
    """Handle schedule choice: plan for later or publish manually now."""
    if callback.data == "ref_schedule_plan":
        text = "💠 Отправьте дату публикации в формате `ДД.ММ.ГГГГ ЧЧ:ММ:СС`"
        text += get_future_time_examples()
        await callback.message.edit_text(text, parse_mode="Markdown")
        await state.set_state(LotMenuStates.ref_waiting_for_plan_time)
    else:
        await _show_ref_publication_preview(callback.message, state, event_service, callback.from_user.id)
    await callback.answer()


@lot_referral_router.message(StateFilter(LotMenuStates.ref_waiting_for_plan_time), F.text)
async def ref_plan_time_entered(message: types.Message, state: FSMContext, event_service):
    """Parse planned publication time and show preview."""
    try:
        dt_naive = datetime.datetime.strptime(message.text.strip(), "%d.%m.%Y %H:%M:%S")
        dt_aware = dt_naive.replace(tzinfo=ZoneInfo("Europe/Kyiv"))
        await state.update_data(ref_plan_time=dt_aware.isoformat())
    except ValueError:
        await message.answer("Неверный формат даты! Пример: `08.06.2025 14:30:00`", parse_mode="Markdown")
        return

    await _show_ref_publication_preview(message, state, event_service, message.from_user.id)


async def _show_ref_publication_preview(
    msg: types.Message, state: FSMContext, event_service, user_id: int
) -> None:
    """Display publication preview with action buttons."""
    data = await state.get_data()
    event_id = data.get("ref_event_id")

    async with event_service.db.acquire() as conn:
        channel_row = await conn.fetchrow(
            "SELECT username FROM channels WHERE owner_id=$1 AND is_active=true",
            user_id,
        )
    channel_text = f"@{channel_row['username']}" if channel_row else "Канал не выбран!"

    plan_time_iso = data.get("ref_plan_time")
    plan_time_str = (
        datetime.datetime.fromisoformat(plan_time_iso).strftime("%d.%m.%Y %H:%M:%S")
        if plan_time_iso
        else "(не запланировано)"
    )

    text = (
        f"🔗 Реферальный конкурс (unpublished) #{event_id}!\n\n"
        f"📤 Публикуем в: {channel_text}\n"
        f"Время публикации: {plan_time_str}\n\n"
        "Доступные действия:"
    )
    kb = types.InlineKeyboardMarkup(inline_keyboard=[
        [
            types.InlineKeyboardButton(text="Опубликовать сейчас", callback_data="ref_pub_now"),
            types.InlineKeyboardButton(text="Изменить канал", callback_data="ref_pub_channel"),
        ],
        [
            types.InlineKeyboardButton(text="Изменить время", callback_data="ref_pub_time"),
            types.InlineKeyboardButton(text="Добавить условие", callback_data="ref_pub_condition"),
        ],
    ])
    await msg.answer(text, reply_markup=kb)
    await state.set_state(LotMenuStates.waiting_for_ref_publication)


@lot_referral_router.callback_query(StateFilter(LotMenuStates.waiting_for_ref_publication))
async def ref_publication_menu(callback: types.CallbackQuery, state: FSMContext, event_service):
    """Handle publication menu actions: publish, change channel/time, add condition."""
    data = await state.get_data()
    event_id = data.get("ref_event_id")
    action = callback.data

    if action == "ref_pub_now":
        # Save scheduled time if set
        plan_time_iso = data.get("ref_plan_time")
        if plan_time_iso and event_id:
            dt = datetime.datetime.fromisoformat(plan_time_iso)
            async with event_service.db.acquire() as conn:
                await conn.execute(
                    "UPDATE events SET scheduled_publish_at=$1 WHERE event_id=$2",
                    dt, event_id,
                )

        ok = await event_service.publish_event_now(event_id)
        await callback.message.answer(
            "🔗 Реферальный конкурс опубликован!" if ok else "Ошибка публикации."
        )
        await state.clear()

    elif action == "ref_pub_channel":
        await callback.message.answer("Для смены канала используйте /channel")

    elif action == "ref_pub_time":
        text = "💠 Отправьте новую дату публикации:"
        text += get_future_time_examples()
        await callback.message.edit_text(text, parse_mode="Markdown")
        await state.set_state(LotMenuStates.ref_waiting_for_plan_time)

    elif action == "ref_pub_condition":
        await callback.message.edit_text("➕ Укажите ID другого конкурса (условие):")
        await state.set_state(LotMenuStates.waiting_for_ref_condition)

    await callback.answer()


@lot_referral_router.message(StateFilter(LotMenuStates.waiting_for_ref_condition), F.text)
async def ref_condition_id_entered(message: types.Message, state: FSMContext, event_service):
    """Set prerequisite event condition."""
    if not message.text or not message.text.strip().isdigit():
        await message.answer("Нужен числовой ID!")
        return

    cond_id = int(message.text.strip())
    data = await state.get_data()
    event_id = data.get("ref_event_id")

    if event_id == cond_id:
        await message.answer("Нельзя ссылаться на то же самое событие!")
        return

    ok = await event_service.add_condition(event_id, cond_id)
    await message.answer("Условие добавлено." if ok else "Не удалось добавить условие.")
    await _show_ref_publication_preview(message, state, event_service, message.from_user.id)
