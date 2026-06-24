"""FastClick handlers: create, publish, settings, and atomic participation."""

import datetime
import logging

from aiogram import Router, types, F
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.exceptions import TelegramBadRequest

from app.states.fastclick_states import FastClickStates
from app.utils.helpers import quote_html, hlink

fastclick_router = Router()


@fastclick_router.message(Command("fast", ignore_mention=True))
async def cmd_fast(message: types.Message, state: FSMContext):
    """Prompt user for FastClick text and set FSM state."""
    await message.answer("🔥 Введите текст фастклика:")
    await state.set_state(FastClickStates.waiting_for_text)


@fastclick_router.message(F.text, FastClickStates.waiting_for_text)
async def step_fast_text(
    message: types.Message,
    state: FSMContext,
    event_service,
    user_service,
):
    """Create FastClick event with user's personal FC settings."""
    user_id = message.from_user.id
    fc_text = message.text.strip()

    # Get user's personal FastClick settings
    settings = await user_service.get_fastclick_settings(user_id)

    event_id = await event_service.create_event(
        creator_id=user_id,
        channel_id=0,
        event_type="fastclick",
        title=fc_text[:60],
        description=fc_text,
        max_winners=1,
        premium_only=settings["fc_premium_only"],
        no_repeat_winner=settings["fc_no_repeat_winner"],
        intrigue=settings["fc_intrigue"],
        participation_button_text="Участвовать!",
    )

    await state.clear()
    msg = (
        "🎊 <b>Фастклик создан!</b> Перед публикацией не забудьте проверить канал\n\n"
        f"✅ Для публикации: <code>/fast_publish {event_id}</code>\n"
        "✅ Смена канала: <b>/channel</b>\n"
        "✅ Настройка ФК: <b>/settings</b>"
    )
    await message.answer(msg)


@fastclick_router.message(Command("fast_publish", ignore_mention=True))
async def cmd_fast_publish(
    message: types.Message,
    event_service,
    channel_service,
):
    """Publish a FastClick event to the user's active channel."""
    parts = message.text.strip().split()
    if len(parts) < 2:
        await message.answer(
            f"Использование: /fast_publish {quote_html('<event_id>')}"
        )
        return

    try:
        event_id = int(parts[1])
    except (ValueError, IndexError):
        await message.answer("Неверный event_id!")
        return

    evt = await event_service.get_event(event_id)
    if not evt or evt["event_type"] != "fastclick":
        await message.answer("Фастклик не найден.")
        return
    if evt["creator_id"] != message.from_user.id:
        await message.answer("Это не ваш фастклик!")
        return
    if evt["is_active"]:
        await message.answer("Этот фастклик уже опубликован!")
        return

    # Get user's active channel
    channel = await channel_service.get_active_channel(message.from_user.id)
    if not channel:
        await message.answer("У вас нет активного канала! /channel для подключения.")
        return

    channel_id = channel["channel_id"]
    channel_username = channel["username"]

    title = evt["title"]
    descr = evt["description"]
    button_text = evt.get("participation_button_text") or "Участвовать!"

    text_post = (
        f"⚡️ Фастклик <b>{quote_html(title)}</b>\n\n"
        f"{quote_html(descr)}\n\n"
        "Первый, кто нажмёт кнопку, станет победителем!"
    )
    join_kb = types.InlineKeyboardMarkup(
        inline_keyboard=[
            [
                types.InlineKeyboardButton(
                    text=button_text,
                    callback_data=f"fast_join:{event_id}",
                )
            ]
        ]
    )

    try:
        msg_sent = await message.bot.send_message(
            chat_id=f"@{channel_username}",
            text=text_post,
            reply_markup=join_kb,
        )
    except Exception as e:
        await message.answer(f"Ошибка публикации: {e}")
        return

    # Activate event and store post info
    now = datetime.datetime.now(datetime.timezone.utc)
    db = event_service.db
    async with db.acquire() as conn:
        await conn.execute(
            "UPDATE events SET channel_id=$1, is_active=TRUE, updated_at=$2, "
            "post_chat_id=$3, post_message_id=$4 WHERE event_id=$5",
            channel_id, now, msg_sent.chat.id, msg_sent.message_id, event_id,
        )

    await message.answer("⚡️ Фастклик опубликован!")


@fastclick_router.message(Command("settings", ignore_mention=True))
async def cmd_settings(message: types.Message, user_service):
    """Show FastClick settings with toggle buttons."""
    await _show_fastclick_settings(message, user_service)


async def _show_fastclick_settings(
    target: types.Message | types.CallbackQuery,
    user_service,
):
    """Render FastClick settings panel (for message or callback)."""
    user_id = target.from_user.id
    settings = await user_service.get_fastclick_settings(user_id)

    prem_status = "🟢" if settings["fc_premium_only"] else "🔴"
    banr_status = "🟢" if settings["fc_no_repeat_winner"] else "🔴"
    intr_status = "🟢" if settings["fc_intrigue"] > 0 else "🔴"

    text = (
        "⚙️ <b>Настройка ваших фасткликов</b>:\n\n"
        f"┏⭐️ Премиальность: {prem_status}\n"
        f"┣🚫 Запрет повторной победы: {banr_status}\n"
        f"┗🔮 Интрига: {intr_status}\n\n"
        "⭐️ Премиальный ФК — участвуют только пользователи с Telegram Premium\n"
        "🚫 Запрет повторной победы — один человек не сможет забрать два фастклика подряд\n"
        "🔮 Интрига — итоги ФК подводятся с анимацией\n"
    )

    kb = types.InlineKeyboardMarkup(
        inline_keyboard=[
            [
                types.InlineKeyboardButton(
                    text=f"⭐️ {'Выключить' if settings['fc_premium_only'] else 'Включить'} ⭐️",
                    callback_data="toggle_fc:premium",
                )
            ],
            [
                types.InlineKeyboardButton(
                    text=f"🚫 {'Выключить' if settings['fc_no_repeat_winner'] else 'Включить'} 🚫",
                    callback_data="toggle_fc:ban_repeat",
                )
            ],
            [
                types.InlineKeyboardButton(
                    text=f"🔮 {'Выключить' if settings['fc_intrigue'] > 0 else 'Включить'} 🔮",
                    callback_data="toggle_fc:intrigue",
                )
            ],
        ]
    )

    if isinstance(target, types.Message):
        await target.answer(text, reply_markup=kb)
    else:
        try:
            await target.message.edit_text(text, reply_markup=kb)
        except TelegramBadRequest as e:
            if "message is not modified" not in str(e):
                logging.warning(f"Message not modified on settings update: {e}")
        await target.answer()


@fastclick_router.callback_query(F.data.startswith("toggle_fc:"))
async def toggle_fc_callback(callback: types.CallbackQuery, user_service):
    """Toggle a FastClick setting via callback."""
    user_id = callback.from_user.id
    setting = callback.data.split(":")[1]

    if setting == "premium":
        await user_service.toggle_fc_premium(user_id)
    elif setting == "ban_repeat":
        await user_service.toggle_fc_no_repeat(user_id)
    elif setting == "intrigue":
        settings = await user_service.get_fastclick_settings(user_id)
        new_value = 0 if settings["fc_intrigue"] > 0 else 1
        await user_service.update_fc_intrigue(user_id, new_value)

    await _show_fastclick_settings(callback, user_service)


@fastclick_router.callback_query(F.data.startswith("fast_join:"))
async def on_fast_join_click(
    callback: types.CallbackQuery,
    event_service,
    user_service,
):
    """Atomic FastClick participation — first click wins using SELECT FOR UPDATE."""
    try:
        event_id = int(callback.data.split(":")[1])
    except (IndexError, ValueError):
        await callback.answer("Некорректный callback!", show_alert=True)
        return

    user = callback.from_user

    # Check sponsors before locking
    sponsors = await event_service.get_sponsors(event_id)
    if sponsors:
        not_subscribed_to = []
        for sponsor in sponsors:
            try:
                chat_id = (
                    sponsor["username"]
                    if sponsor["username"].startswith("-")
                    else f"@{sponsor['username']}"
                )
                member = await callback.bot.get_chat_member(chat_id, user.id)
                if member.status not in ("member", "administrator", "creator"):
                    not_subscribed_to.append(sponsor["username"])
            except Exception:
                not_subscribed_to.append(sponsor["username"])

        if not_subscribed_to:
            channels_list = "\n".join(f"➡️ @{ch}" for ch in not_subscribed_to)
            text = f"Для участия необходимо подписаться на каналы:\n{channels_list}"
            kb = types.InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        types.InlineKeyboardButton(
                            text="✅ Я подписался, проверить",
                            callback_data=f"fast_join:{event_id}",
                        )
                    ]
                ]
            )
            await callback.message.answer(text, reply_markup=kb)
            await callback.answer()
            return

    # Quick pre-check before locking (avoid unnecessary transactions)
    evt_precheck = await event_service.get_event(event_id)
    if not evt_precheck or not evt_precheck["is_active"]:
        await callback.answer("Этот фастклик уже завершён!", show_alert=True)
        return

    # Atomic participation with SELECT FOR UPDATE
    db = event_service.db
    async with db.acquire() as conn:
        async with conn.transaction():
            # Lock the event row to prevent race conditions
            evt = await conn.fetchrow(
                "SELECT * FROM events WHERE event_id=$1 AND event_type='fastclick' FOR UPDATE",
                event_id,
            )
            if not evt:
                await callback.answer("Фастклик не найден.", show_alert=True)
                return
            if not evt["is_active"]:
                await callback.answer(
                    "Этот фастклик уже завершён!", show_alert=True
                )
                return

            # Check premium-only restriction
            if evt["premium_only"] and not (user and user.is_premium):
                await callback.answer(
                    "У вас нет Telegram Premium, участие запрещено!",
                    show_alert=True,
                )
                return

            # Check no-repeat-winner restriction
            if evt["no_repeat_winner"]:
                is_blocked = await conn.fetchval(
                    "SELECT no_repeat_block FROM users WHERE user_id=$1",
                    user.id,
                )
                if is_blocked:
                    await callback.answer(
                        "Вы уже выигрывали, повторная победа запрещена!",
                        show_alert=True,
                    )
                    return

            # Record winner and deactivate event atomically
            now = datetime.datetime.now(datetime.timezone.utc)
            await conn.execute(
                "INSERT INTO event_participants(event_id, user_id, joined_at, winner) "
                "VALUES ($1, $2, $3, TRUE)",
                event_id, user.id, now,
            )
            await conn.execute(
                "UPDATE events SET is_active=FALSE, updated_at=$1 WHERE event_id=$2",
                now, event_id,
            )

            # Block user from future fastclicks if no_repeat_winner
            if evt["no_repeat_winner"]:
                await conn.execute(
                    "UPDATE users SET no_repeat_block=TRUE WHERE user_id=$1",
                    user.id,
                )

    await callback.answer(
        "Поздравляю, вы успели первым и стали победителем!", show_alert=True
    )

    # Edit channel post with winner info
    winner_name = user.full_name
    winner_mention = hlink(winner_name, f"tg://user?id={user.id}")

    final_text = (
        f"⚡️ Фастклик <b>{quote_html(evt_precheck['title'])}</b> завершён!\n\n"
        f"{quote_html(evt_precheck['description'])}\n\n"
        f"🏆 Победитель: {winner_mention}"
    )

    if evt_precheck.get("post_chat_id") and evt_precheck.get("post_message_id"):
        try:
            await callback.bot.edit_message_text(
                text=final_text,
                chat_id=evt_precheck["post_chat_id"],
                message_id=evt_precheck["post_message_id"],
                reply_markup=None,
            )
        except Exception as e:
            logging.error(
                f"Could not edit fastclick message {event_id}: {e}"
            )
