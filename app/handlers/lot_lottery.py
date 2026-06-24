"""Lottery wizard handler — create lottery events via FSM."""

import random
from aiogram import Router, types, F
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext

from app.states import LotMenuStates
from app.services.event_service import EventService
from app.utils.helpers import parse_channel_username_from_message, is_bot_admin_in_channel

lot_lottery_router = Router()


# --- Step 1: Receive lottery text/media ---

@lot_lottery_router.message(
    StateFilter(LotMenuStates.waiting_for_lottery_text),
    F.content_type.in_({"text", "photo", "animation", "video"}),
)
async def lottery_text_entered(message: types.Message, state: FSMContext):
    """Capture lottery description text and optional media."""
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

    text_lot = message.caption or message.text or "(без текста)"
    await state.update_data(
        lottery_media_id=media_id,
        lottery_media_type=media_type,
        lottery_text=text_lot,
    )

    # Build ticket count keyboard: 5, 10, 15, 20, 25 + custom
    kb = types.InlineKeyboardMarkup(inline_keyboard=[
        [
            types.InlineKeyboardButton(text="5", callback_data="lottery_ticket_5"),
            types.InlineKeyboardButton(text="10", callback_data="lottery_ticket_10"),
            types.InlineKeyboardButton(text="15", callback_data="lottery_ticket_15"),
            types.InlineKeyboardButton(text="20", callback_data="lottery_ticket_20"),
            types.InlineKeyboardButton(text="25", callback_data="lottery_ticket_25"),
        ],
        [types.InlineKeyboardButton(text="Ввести другое число", callback_data="lottery_ticket_custom")],
        [types.InlineKeyboardButton(text="Отменить ввод", callback_data="lot_cancel")],
    ])
    await message.answer(
        "✅ Сохранено! Выберите количество билетов в лотерее:", reply_markup=kb
    )
    await state.set_state(LotMenuStates.waiting_for_lottery_tickets)


# --- Step 2: Ticket count selection ---

@lot_lottery_router.callback_query(
    StateFilter(LotMenuStates.waiting_for_lottery_tickets),
    F.data.startswith("lottery_ticket_"),
)
async def lottery_tickets_cb(callback: types.CallbackQuery, state: FSMContext, event_service: EventService):
    """Handle ticket count button press or custom entry."""
    if callback.data == "lottery_ticket_custom":
        kb_cancel = types.InlineKeyboardMarkup(
            inline_keyboard=[
                [types.InlineKeyboardButton(text="Отменить ввод", callback_data="lot_cancel")]
            ]
        )
        await callback.message.edit_text(
            "Укажите количество билетов (от 2 до 100):", reply_markup=kb_cancel
        )
        await state.set_state(LotMenuStates.lottery_enter_custom_tickets)
    else:
        ticket_count = int(callback.data.split("_")[-1])
        await state.update_data(lottery_tickets=ticket_count)
        await _create_lottery_event(callback.message, state, event_service, callback.from_user.id)
    await callback.answer()


@lot_lottery_router.callback_query(
    StateFilter(LotMenuStates.waiting_for_lottery_tickets),
    F.data == "lot_cancel",
)
async def lottery_cancel_from_tickets(callback: types.CallbackQuery, state: FSMContext):
    """Cancel lottery creation and return to type selection."""
    await _lot_cancel(callback, state)


@lot_lottery_router.message(
    StateFilter(LotMenuStates.lottery_enter_custom_tickets), F.text
)
async def lottery_custom_tickets_entered(message: types.Message, state: FSMContext, event_service: EventService):
    """Handle custom ticket count text input."""
    if not message.text.isdigit():
        await message.answer("Введите число от 2 до 100!")
        return
    ticket_count = int(message.text)
    if not (2 <= ticket_count <= 100):
        await message.answer("Допустимый диапазон: 2-100!")
        return
    await state.update_data(lottery_tickets=ticket_count)
    await _create_lottery_event(message, state, event_service, message.from_user.id)


# --- Step 3: Sponsors ---

@lot_lottery_router.message(
    StateFilter(LotMenuStates.waiting_for_lottery_sponsors),
    F.content_type.in_({"text", "photo", "video"}),
)
async def lottery_sponsor_entered(message: types.Message, state: FSMContext, event_service: EventService):
    """Add a sponsor channel to the lottery event."""
    sponsor_username = parse_channel_username_from_message(message)
    if not sponsor_username:
        await message.answer(
            "Неверный формат канала! Отправьте @username, ссылку t.me/ или перешлите пост из канала."
        )
        return

    data = await state.get_data()
    event_id = data.get("lottery_event_id")
    if not event_id:
        await message.answer("Ошибка: не найден ID события. Начните заново.")
        await state.clear()
        return

    is_admin, err_msg = await is_bot_admin_in_channel(sponsor_username, message.bot)
    if not is_admin:
        await message.answer(
            f"Бот не является администратором в {sponsor_username}.\n{err_msg}"
        )
        return

    await event_service.add_sponsor(event_id, sponsor_username.lstrip("@"))
    kb = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="Достаточно спонсоров", callback_data="lottery_sponsors_done")]
    ])
    await message.answer(
        f"✅ Спонсор {sponsor_username} добавлен.\nДобавьте ещё или нажмите 'Достаточно'.",
        reply_markup=kb,
    )


@lot_lottery_router.callback_query(
    StateFilter(LotMenuStates.waiting_for_lottery_sponsors),
    F.data == "lottery_sponsors_done",
)
async def lottery_sponsors_done(callback: types.CallbackQuery, state: FSMContext):
    """Sponsors step complete — proceed to publication."""
    await _show_lottery_publication(callback.message, state, callback.from_user.id)
    await callback.answer()


# --- Step 4: Publication ---

@lot_lottery_router.callback_query(
    StateFilter(LotMenuStates.waiting_for_lottery_publication),
    F.data == "lottery_publish",
)
async def lottery_publish_cb(callback: types.CallbackQuery, state: FSMContext, event_service: EventService):
    """Publish the lottery event to the channel."""
    data = await state.get_data()
    event_id = data.get("lottery_event_id")
    if not event_id:
        await callback.message.answer("Ошибка: нет event_id!")
        await state.clear()
        await callback.answer()
        return

    ok = await event_service.publish_event_now(event_id)
    await callback.message.answer(
        "🍀 Лотерея опубликована!" if ok else "Ошибка при публикации (нет канала?)."
    )
    await state.clear()
    await callback.answer()


# --- Helpers ---

async def _create_lottery_event(
    message: types.Message, state: FSMContext, event_service: EventService, user_id: int
):
    """Create the lottery event in the database with a random winning ticket."""
    data = await state.get_data()
    lot_text = data.get("lottery_text", "Без описания")
    tickets = data.get("lottery_tickets", 5)
    media_id = data.get("lottery_media_id")
    media_type = data.get("lottery_media_type")
    title = (lot_text[:50] + "...") if len(lot_text) > 50 else lot_text

    # Select a random winning ticket number
    winning_ticket = random.randint(1, tickets)

    event_id = await event_service.create_event(
        creator_id=user_id,
        channel_id=0,
        event_type="lottery",
        title=title,
        description=lot_text,
        media_id=media_id,
        media_type=media_type,
        max_tickets=tickets,
        max_winners=1,
        participation_button_text="Участвовать!",
        button_style="grid",
        winning_ticket_number=winning_ticket,
    )
    await state.update_data(lottery_event_id=event_id)

    bot_info = await message.bot.get_me()
    kb = types.InlineKeyboardMarkup(inline_keyboard=[
        [
            types.InlineKeyboardButton(
                text="Добавить бота на канал",
                url=f"http://t.me/{bot_info.username}?startchannel=true",
            )
        ],
        [types.InlineKeyboardButton(text="Без спонсоров", callback_data="lottery_sponsors_done")],
    ])
    await message.answer(
        f"🍀 Лотерея (ID {event_id}) создана!\n\n"
        f"Отправьте каналы-спонсоры или нажмите 'Без спонсоров'.",
        reply_markup=kb,
    )
    await state.set_state(LotMenuStates.waiting_for_lottery_sponsors)


async def _show_lottery_publication(message: types.Message, state: FSMContext, user_id: int):
    """Show publication preview with publish button."""
    data = await state.get_data()
    event_id = data.get("lottery_event_id")

    text = (
        f"🎊 Лотерея (ID {event_id}) готова к публикации!\n\n"
        "Нажмите кнопку ниже, чтобы опубликовать."
    )
    kb = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="Опубликовать лотерею", callback_data="lottery_publish")]
    ])
    await message.answer(text, reply_markup=kb)
    await state.set_state(LotMenuStates.waiting_for_lottery_publication)


async def _lot_cancel(callback: types.CallbackQuery, state: FSMContext):
    """Cancel and return to event type selection."""
    await state.clear()
    kb = types.InlineKeyboardMarkup(inline_keyboard=[
        [
            types.InlineKeyboardButton(text="🎉 Конкурс", callback_data="lot_type:contest"),
            types.InlineKeyboardButton(text="🍀 Лотерея", callback_data="lot_type:lottery"),
            types.InlineKeyboardButton(text="🔗 Реферальный", callback_data="lot_type:referral"),
        ]
    ])
    await callback.message.edit_text("🎟️ Выберите тип события:", reply_markup=kb)
    await state.set_state(LotMenuStates.choosing_type)
    await callback.answer()
