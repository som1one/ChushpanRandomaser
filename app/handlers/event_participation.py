"""Handler for event participation (join_event callback)."""

import logging

from aiogram import Bot, Router, types, F
from aiogram.fsm.context import FSMContext

from app.services.event_service import EventService
from app.services.user_service import UserService

event_participation_router = Router()


@event_participation_router.callback_query(F.data.startswith("join_event:"))
async def on_join_event(
    callback: types.CallbackQuery,
    bot: Bot,
    state: FSMContext,
    event_service: EventService,
    user_service: UserService,
    **kwargs,
):
    """Handle join_event:{event_id} and join_event:{event_id}:{ticket} callbacks.

    Flow:
    1. Parse callback data
    2. Check event is active
    3. Check if user already participates (non-lottery)
    4. Check sponsor subscriptions
    5. Check vote_channel_required (main channel subscription)
    6. Check prerequisite event participation
    7. Add participant
    8. Handle lottery ticket UI update
    9. Handle referral link generation
    10. Handle max participants (auto-finish)
    """
    # Parse callback data
    parts = callback.data.split(":")
    try:
        event_id = int(parts[1])
        ticket_number = int(parts[2]) if len(parts) > 2 else None
    except (ValueError, IndexError):
        await callback.answer("Ошибка в данных события.", show_alert=True)
        return

    user = callback.from_user

    # 1. Check event exists and is active
    event = await event_service.get_event(event_id)
    if not event or not event["is_active"]:
        await callback.answer("Событие больше неактивно.", show_alert=True)
        return

    # 2. Check if already participating (skip for lottery — ticket uniqueness handled by DB)
    if event["event_type"] != "lottery":
        is_participant = await user_service.check_user_is_participant(user.id, event_id)
        if is_participant:
            await callback.answer("Вы уже участвуете!", show_alert=True)
            return

    # 3. Check premium_only restriction
    if event.get("premium_only") and not getattr(user, "is_premium", False):
        await callback.answer(
            "Этот конкурс только для Premium-пользователей.", show_alert=True
        )
        return

    # 4. Check prerequisite event
    required_event_id = event.get("required_event_id")
    if required_event_id:
        is_required_participant = await user_service.check_user_is_participant(
            user.id, required_event_id
        )
        if not is_required_participant:
            await callback.answer(
                f"Для участия необходимо сначала принять участие в конкурсе #{required_event_id}",
                show_alert=True,
            )
            return

    # 5. Check vote_channel_required (main channel subscription)
    not_subscribed_to: list[str] = []

    if event.get("vote_channel_required") and event.get("channel_id"):
        try:
            main_channel_member = await bot.get_chat_member(
                event["channel_id"], user.id
            )
            if main_channel_member.status not in (
                "member",
                "administrator",
                "creator",
            ):
                chat_info = await bot.get_chat(event["channel_id"])
                not_subscribed_to.append(
                    chat_info.username or str(event["channel_id"])
                )
        except Exception:
            try:
                chat_info = await bot.get_chat(event["channel_id"])
                not_subscribed_to.append(
                    chat_info.username or str(event["channel_id"])
                )
            except Exception:
                logging.warning(
                    f"Could not check main channel {event['channel_id']} for user {user.id}"
                )

    # 6. Check sponsor subscriptions
    sponsors = await event_service.get_sponsors(event_id)
    if sponsors:
        for sponsor in sponsors:
            try:
                chat_id = (
                    sponsor["username"]
                    if str(sponsor["username"]).startswith("-")
                    else f"@{sponsor['username']}"
                )
                member = await bot.get_chat_member(chat_id, user.id)
                if member.status not in ("member", "administrator", "creator"):
                    not_subscribed_to.append(sponsor["username"])
            except Exception:
                not_subscribed_to.append(sponsor["username"])

    # If not subscribed to required channels — notify user
    if not_subscribed_to:
        unique_channels = sorted(set(not_subscribed_to))
        channels_list = "\n".join(
            [f"➡️ @{ch.lstrip('@')}" for ch in unique_channels]
        )
        text = f"Для участия необходимо подписаться на каналы:\n{channels_list}"
        kb = types.InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    types.InlineKeyboardButton(
                        text="✅ Я подписался, проверить",
                        callback_data=callback.data,
                    )
                ]
            ]
        )
        try:
            await bot.send_message(user.id, text, reply_markup=kb)
            await callback.answer()
        except Exception:
            bot_info = await bot.get_me()
            await callback.answer(
                f"Подпишитесь на каналы и запустите бота @{bot_info.username}",
                show_alert=True,
            )
        return

    # 7. Determine inviter_id for referral events
    inviter_id = None
    if event["event_type"] == "referral":
        user_data = await state.get_data()
        if user_data.get("referred_event_id") == event_id:
            inviter_id = user_data.get("inviter_id")

    # 8. Add participant
    added_successfully = await event_service.add_participant(
        event_id=event_id,
        user_id=user.id,
        ticket_number=ticket_number,
        inviter_id=inviter_id,
    )

    if not added_successfully:
        await callback.answer(
            "Вы уже участвуете или этот билет занят!", show_alert=True
        )
        return

    # 9. Check if max participants reached → auto-finish
    participant_limit = event.get("max_tickets")
    if participant_limit:
        current_participants = await event_service.get_participant_count(event_id)
        if current_participants >= participant_limit:
            await callback.answer(
                "Вы стали последним участником! Завершаем конкурс...",
                show_alert=True,
            )
            await event_service.finish_event(event_id)
            return

    # 10. Handle lottery ticket selection UI
    if event["event_type"] == "lottery":
        taken_ticket_text = f"✅ {user.first_name[:10]}"
        current_markup = callback.message.reply_markup
        if current_markup:
            for row in current_markup.inline_keyboard:
                for button in row:
                    if button.callback_data == callback.data:
                        button.text = taken_ticket_text
                        button.callback_data = "ticket_taken"
            try:
                await callback.message.edit_reply_markup(
                    reply_markup=current_markup
                )
            except Exception:
                pass

        # Check if this was the winning ticket (event finished by add_participant)
        updated_event = await event_service.get_event(event_id)
        if updated_event and updated_event["is_active"]:
            await callback.answer(
                f"Вы выбрали билет №{ticket_number}. Удачи!", show_alert=True
            )
        else:
            await callback.answer(
                "Это был выигрышный билет! Поздравляем!", show_alert=True
            )

    # 11. Handle referral link generation
    elif event["event_type"] == "referral":
        bot_info = await bot.get_me()
        ref_link = f"https://t.me/{bot_info.username}?start=ref_{event_id}_{user.id}"
        try:
            await bot.send_message(
                user.id,
                f"Вы успешно стали участником реферального конкурса!\n\n"
                f"Ваша ссылка для приглашения друзей:\n<code>{ref_link}</code>",
            )
            await callback.answer(
                "Вы стали участником! Ссылка отправлена в личные сообщения.",
                show_alert=True,
            )
        except Exception:
            await callback.answer(
                f"Вы стали участником! Запустите бота @{bot_info.username} для получения реф. ссылки.",
                show_alert=True,
            )

    # 12. Default — contest participation
    else:
        await callback.answer(
            "Вы успешно приняли участие в событии!", show_alert=True
        )


@event_participation_router.callback_query(F.data == "ticket_taken")
async def on_ticket_taken(callback: types.CallbackQuery, **kwargs):
    """Handle click on already-taken lottery ticket."""
    await callback.answer("Этот билет уже занят!", show_alert=True)
