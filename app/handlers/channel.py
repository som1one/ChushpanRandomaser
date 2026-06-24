"""Handler for /channel — add, select active, verify admin."""

from aiogram import Router, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext

from app.states import ChannelStates
from app.services.channel_service import ChannelService
from app.utils.helpers import parse_channel_username

channel_router = Router()


async def _display_channels(
    user_id: int,
    channel_service: ChannelService,
    *,
    message: types.Message | None = None,
    callback: types.CallbackQuery | None = None,
) -> None:
    """Show user's channels with inline buttons to add or select active one."""
    channels = await channel_service.get_user_channels(user_id)
    active = await channel_service.get_active_channel(user_id)

    active_text = f"@{active['username']}" if active else "Не выбран"

    text = (
        f"🌐 <b>Активный канал:</b> {active_text}\n\n"
        "Выберите канал из списка, чтобы сделать его активным для публикаций.\n"
        "Если вашего канала нет — добавьте его кнопкой ниже."
    )

    keyboard_rows = []
    for ch in channels:
        btn_text = f"@{ch['username']}"
        if ch["is_active"]:
            btn_text += " ✅"
        keyboard_rows.append([
            types.InlineKeyboardButton(
                text=btn_text,
                callback_data=f"channel_select:{ch['channel_id']}",
            )
        ])

    keyboard_rows.append([
        types.InlineKeyboardButton(
            text="➕ Добавить канал",
            callback_data="channel_add",
        )
    ])

    markup = types.InlineKeyboardMarkup(inline_keyboard=keyboard_rows)

    if message:
        await message.answer(text, reply_markup=markup)
    elif callback:
        await callback.message.edit_text(text, reply_markup=markup)


@channel_router.message(Command("channel"))
async def cmd_channel(
    message: types.Message,
    state: FSMContext,
    channel_service: ChannelService,
    **kwargs,
):
    """Handle /channel — display user channels list."""
    await state.clear()
    await _display_channels(message.from_user.id, channel_service, message=message)


@channel_router.callback_query(F.data == "channel_add")
async def on_channel_add(
    callback: types.CallbackQuery,
    state: FSMContext,
    **kwargs,
):
    """Prompt user to send channel username for adding."""
    bot_user = await callback.bot.get_me()
    text = (
        "💠 <b>Добавление канала</b>\n\n"
        "1. Добавьте бота в ваш канал как администратора.\n"
        "2. Отправьте мне @username канала или ссылку t.me/...\n\n"
        "Для закрытых каналов перешлите любой пост из канала."
    )
    kb = types.InlineKeyboardMarkup(inline_keyboard=[
        [
            types.InlineKeyboardButton(
                text="👤 Добавить бота в админы",
                url=f"https://t.me/{bot_user.username}?startchannel=true",
            )
        ],
        [
            types.InlineKeyboardButton(
                text="◀ Назад", callback_data="channel_back"
            )
        ],
    ])

    await callback.message.edit_text(text, reply_markup=kb)
    await state.set_state(ChannelStates.waiting_for_channel_username)
    await callback.answer()


@channel_router.callback_query(F.data == "channel_back")
async def on_channel_back(
    callback: types.CallbackQuery,
    state: FSMContext,
    channel_service: ChannelService,
    **kwargs,
):
    """Return to channels list."""
    await state.clear()
    await _display_channels(callback.from_user.id, channel_service, callback=callback)
    await callback.answer()


@channel_router.message(ChannelStates.waiting_for_channel_username)
async def process_channel_input(
    message: types.Message,
    state: FSMContext,
    channel_service: ChannelService,
    **kwargs,
):
    """Process channel username/link/forward and add channel."""
    user_id = message.from_user.id
    raw_identifier: str | None = None

    # Handle forwarded messages from channels
    if message.forward_from_chat and message.forward_from_chat.type == "channel":
        raw_identifier = str(message.forward_from_chat.id)
    elif message.text:
        raw_identifier = message.text.strip()

    if not raw_identifier:
        await message.answer(
            "Не удалось распознать канал. Отправьте @username, ссылку или перешлите пост из канала."
        )
        return

    # Try to parse as numeric channel ID (for forwarded / private channels)
    try:
        numeric_id = int(raw_identifier)
        # It's a numeric channel ID — use it directly
        chat = await message.bot.get_chat(numeric_id)
    except (ValueError, TypeError):
        # Parse username from text
        username = parse_channel_username(raw_identifier)
        if not username:
            await message.answer(
                "Не удалось распознать канал. Попробуйте @username или ссылку."
            )
            return
        try:
            chat = await message.bot.get_chat(f"@{username}")
        except Exception as e:
            await message.answer(
                f"Не удалось найти канал. Убедитесь, что бот добавлен в канал.\nОшибка: {e}"
            )
            return
    except Exception as e:
        await message.answer(f"Не удалось найти канал.\nОшибка: {e}")
        return

    if chat.type not in ("channel", "supergroup"):
        await message.answer("Это не канал и не супергруппа.")
        return

    # Verify bot is admin
    is_admin, err_msg = await channel_service.verify_bot_is_admin(str(chat.id))
    if not is_admin:
        await message.answer(
            f"Бот не является администратором в этом канале.\n{err_msg}"
        )
        return

    # Register channel via service
    channel_username = chat.username or f"id{chat.id}"
    channel_id = chat.id

    # Use service's add_channel logic but with resolved data
    async with channel_service.db.acquire() as conn:
        await conn.execute(
            """INSERT INTO channels(channel_id, username, owner_id, is_active)
               VALUES ($1, $2, $3, FALSE)
               ON CONFLICT (channel_id) DO UPDATE
               SET username = EXCLUDED.username, owner_id = EXCLUDED.owner_id""",
            channel_id, channel_username, user_id,
        )

    await state.clear()
    await message.answer(f"✅ Канал «{chat.title or channel_username}» добавлен!")
    await _display_channels(user_id, channel_service, message=message)


@channel_router.callback_query(F.data.startswith("channel_select:"))
async def on_channel_select(
    callback: types.CallbackQuery,
    state: FSMContext,
    channel_service: ChannelService,
    **kwargs,
):
    """Select a channel as active for publishing."""
    user_id = callback.from_user.id
    try:
        channel_id = int(callback.data.split(":")[1])
    except (ValueError, IndexError):
        await callback.answer("Некорректные данные!", show_alert=True)
        return

    await channel_service.set_active_channel(user_id, channel_id)
    await callback.answer("Канал выбран как активный!")
    await _display_channels(user_id, channel_service, callback=callback)


@channel_router.my_chat_member()
async def on_bot_added_to_channel(
    update: types.ChatMemberUpdated,
    channel_service: ChannelService,
    **kwargs,
):
    """Auto-register channel when bot is added as admin, remove when kicked."""
    if update.chat.type != "channel":
        return

    new_status = update.new_chat_member.status
    chat_id = update.chat.id
    username = update.chat.username or f"id{chat_id}"
    owner_id = update.from_user.id

    async with channel_service.db.acquire() as conn:
        if new_status in ("administrator", "creator"):
            await conn.execute(
                """INSERT INTO channels (channel_id, username, owner_id, is_active)
                   VALUES ($1, $2, $3, FALSE)
                   ON CONFLICT (channel_id) DO UPDATE SET
                       username = EXCLUDED.username,
                       owner_id = EXCLUDED.owner_id""",
                chat_id, username, owner_id,
            )
        elif new_status in ("left", "kicked"):
            await conn.execute(
                "DELETE FROM channels WHERE channel_id = $1", chat_id
            )
