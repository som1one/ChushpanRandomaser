"""Quiz handlers: /quiz creation flow and voting."""

import datetime
import logging

from aiogram import Router, types, F
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.exceptions import TelegramBadRequest

from app.states import QuizCreationStates
from app.utils.helpers import quote_html

quiz_router = Router()


@quiz_router.message(Command("quiz", ignore_mention=True))
async def cmd_quiz_start(message: types.Message, state: FSMContext):
    """Start quiz creation: choose number of columns."""
    kb = [
        [
            types.InlineKeyboardButton(text="1", callback_data="columns_1"),
            types.InlineKeyboardButton(text="2", callback_data="columns_2"),
            types.InlineKeyboardButton(text="3", callback_data="columns_3"),
        ],
        [types.InlineKeyboardButton(text="Отменить ввод", callback_data="quiz_cancel")],
    ]
    markup = types.InlineKeyboardMarkup(inline_keyboard=kb)
    text = (
        "💠 <b>Выберите количество столбцов</b> (1..3)\n\n"
        "Чем больше столбцов, тем меньше текста влезает в кнопку."
    )
    await message.answer(text, reply_markup=markup)
    await state.set_state(QuizCreationStates.choosing_columns)


@quiz_router.callback_query(StateFilter(QuizCreationStates.choosing_columns), F.data.startswith("columns_"))
async def quiz_choose_columns(callback: types.CallbackQuery, state: FSMContext):
    """Store columns count and ask for photo+text."""
    columns_count = int(callback.data.split("_")[1])
    await state.update_data(columns_count=columns_count)
    kb = types.InlineKeyboardMarkup(
        inline_keyboard=[
            [types.InlineKeyboardButton(text="Отменить ввод", callback_data="quiz_cancel")]
        ]
    )
    await callback.message.answer(
        "📊 Введите текст опроса (можно фото + подпись).", reply_markup=kb
    )
    await state.set_state(QuizCreationStates.waiting_for_photo_and_text)
    await callback.answer()


@quiz_router.callback_query(StateFilter(QuizCreationStates), F.data == "quiz_cancel")
async def quiz_cancel_any_step(callback: types.CallbackQuery, state: FSMContext):
    """Cancel quiz creation at any step."""
    await callback.message.answer("Ввод опроса отменён.")
    await state.clear()
    await callback.answer()


@quiz_router.message(
    StateFilter(QuizCreationStates.waiting_for_photo_and_text),
    F.content_type.in_({"text", "photo"}),
)
async def quiz_get_text_or_photo(message: types.Message, state: FSMContext):
    """Receive quiz question text (with optional photo) and start collecting options."""
    quiz_text = message.caption or message.text or ""
    quiz_photo_id = message.photo[-1].file_id if message.photo else None

    await state.update_data(
        quiz_text=quiz_text.strip(),
        quiz_photo_id=quiz_photo_id,
        quiz_options=[],
    )
    kb = types.InlineKeyboardMarkup(
        inline_keyboard=[
            [types.InlineKeyboardButton(text="Отменить ввод", callback_data="quiz_cancel")]
        ]
    )
    await message.answer("❓ Введите текст <b>первого</b> варианта:", reply_markup=kb)
    await state.set_state(QuizCreationStates.collecting_options)


@quiz_router.message(StateFilter(QuizCreationStates.collecting_options), F.text)
async def quiz_collect_options(message: types.Message, state: FSMContext):
    """Collect quiz option text. Allow up to 9 options."""
    data = await state.get_data()
    options = data.get("quiz_options", [])
    max_allowed = 9

    if len(options) >= max_allowed:
        await message.answer(
            "Вы достигли лимита (9 вариантов). Нажмите 'Достаточно вариантов'."
        )
        return

    options.append(message.text.strip())
    await state.update_data(quiz_options=options)

    n = len(options) + 1
    kb_rows = []
    if len(options) >= 2:
        kb_rows.append(
            [
                types.InlineKeyboardButton(
                    text="Достаточно вариантов", callback_data="quiz_enough_options"
                )
            ]
        )
    kb_rows.append(
        [types.InlineKeyboardButton(text="Отменить ввод", callback_data="quiz_cancel")]
    )
    markup = types.InlineKeyboardMarkup(inline_keyboard=kb_rows)

    if len(options) < max_allowed:
        prompt = f"❓ Введите текст <b>{n}-го</b> варианта:"
    else:
        prompt = "Лимит (9) достигнут. Нажмите 'Достаточно вариантов'."
    await message.answer(prompt, reply_markup=markup)


@quiz_router.callback_query(
    StateFilter(QuizCreationStates.collecting_options), F.data == "quiz_enough_options"
)
async def quiz_enough_options(callback: types.CallbackQuery, state: FSMContext):
    """Options collected, ask for max votes configuration."""
    kb = [
        [
            types.InlineKeyboardButton(
                text="Неограниченное кол-во голосов",
                callback_data="quiz_unlimited_votes",
            )
        ],
        [types.InlineKeyboardButton(text="Отменить ввод", callback_data="quiz_cancel")],
    ]
    markup = types.InlineKeyboardMarkup(inline_keyboard=kb)
    await callback.message.answer(
        "⚠️ На какое количество голосов подвести итоги?\n"
        "Отправьте число или нажмите кнопку:",
        reply_markup=markup,
    )
    await state.set_state(QuizCreationStates.waiting_for_max_votes)
    await callback.answer()


@quiz_router.callback_query(
    StateFilter(QuizCreationStates.waiting_for_max_votes),
    F.data == "quiz_unlimited_votes",
)
async def quiz_unlimited_votes(callback: types.CallbackQuery, state: FSMContext):
    """Set unlimited votes and proceed to allow_change question."""
    await state.update_data(quiz_max_votes=None)
    await _ask_allow_change(callback.message, state)
    await callback.answer()


@quiz_router.message(StateFilter(QuizCreationStates.waiting_for_max_votes), F.text)
async def quiz_max_votes_entered(message: types.Message, state: FSMContext):
    """Parse max votes number from user input."""
    if not message.text.strip().isdigit():
        await message.answer("Введите число > 0 или 'Неограниченное' кнопкой.")
        return

    mv = int(message.text.strip())
    if mv <= 0:
        await message.answer("Введите число > 0!")
        return

    await state.update_data(quiz_max_votes=mv)
    await _ask_allow_change(message, state)


async def _ask_allow_change(msg: types.Message, state: FSMContext):
    """Ask user whether vote changes are allowed."""
    kb = [
        [
            types.InlineKeyboardButton(text="Разрешить!", callback_data="quiz_allow_yes"),
            types.InlineKeyboardButton(text="Запретить!", callback_data="quiz_allow_no"),
        ],
        [types.InlineKeyboardButton(text="Отменить ввод", callback_data="quiz_cancel")],
    ]
    markup = types.InlineKeyboardMarkup(inline_keyboard=kb)
    await msg.answer("♻️ Разрешить пользователям изменять свой голос?", reply_markup=markup)
    await state.set_state(QuizCreationStates.waiting_for_allow_change)


@quiz_router.callback_query(
    StateFilter(QuizCreationStates.waiting_for_allow_change),
    F.data.in_({"quiz_allow_yes", "quiz_allow_no"}),
)
async def quiz_allow_change_decided(
    callback: types.CallbackQuery, state: FSMContext, event_service
):
    """Final step: save quiz to DB and inform user."""
    allow = callback.data == "quiz_allow_yes"
    await state.update_data(quiz_allow_change=allow)
    data = await state.get_data()

    db = event_service.db
    now = datetime.datetime.now(datetime.timezone.utc)

    async with db.acquire() as conn:
        async with conn.transaction():
            quiz_id = await conn.fetchval(
                """
                INSERT INTO quizzes(
                    creator_id, question, allow_vote_change, max_votes,
                    created_at, is_active, columns_count, photo_id
                )
                VALUES ($1, $2, $3, $4, $5, FALSE, $6, $7)
                RETURNING quiz_id
                """,
                callback.from_user.id,
                data.get("quiz_text"),
                data.get("quiz_allow_change"),
                data.get("quiz_max_votes"),
                now,
                data.get("columns_count"),
                data.get("quiz_photo_id"),
            )
            for option_text in data.get("quiz_options", []):
                await conn.execute(
                    "INSERT INTO quiz_options(quiz_id, option_text) VALUES ($1, $2)",
                    quiz_id,
                    option_text,
                )

    final_text = (
        f"🎊 <b>Опрос создан (ID {quiz_id})</b>!\n\n"
        f"Пока не опубликован. <code>/start_quiz {quiz_id}</code> — для публикации.\n"
        "Или смена канала: /channel"
    )
    await callback.message.answer(final_text)
    await state.clear()
    await callback.answer()


@quiz_router.message(Command("start_quiz", ignore_mention=True))
async def cmd_start_quiz(
    message: types.Message, event_service, channel_service
):
    """Publish a quiz to the user's active channel."""
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.answer(
            f"Использование: /start_quiz {quote_html('<quiz_id>')}"
        )
        return

    try:
        quiz_id = int(args[1])
    except ValueError:
        await message.answer("Неверный quiz_id!")
        return

    db = event_service.db

    async with db.acquire() as conn:
        quiz_data = await conn.fetchrow(
            "SELECT * FROM quizzes WHERE quiz_id=$1", quiz_id
        )
        if not quiz_data:
            await message.answer("Опрос не найден!")
            return
        if quiz_data["is_active"]:
            await message.answer("Этот опрос уже опубликован.")
            return

    # Get user's active channel
    channel = await channel_service.get_active_channel(message.from_user.id)
    if not channel:
        await message.answer(
            "У вас нет активного канала для публикации. Выберите его через /channel."
        )
        return

    channel_username = channel["username"]
    target_chat = f"@{channel_username}"

    async with db.acquire() as conn:
        opts = await conn.fetch(
            "SELECT option_id, option_text FROM quiz_options WHERE quiz_id=$1 ORDER BY option_id",
            quiz_id,
        )
    if not opts:
        await message.answer("В этом опросе нет вариантов ответа!")
        return

    quiz_text = f"<b>{quiz_data['question']}</b>"
    columns_count = quiz_data.get("columns_count", 1) or 1

    # Build voting keyboard
    kb_rows = []
    row_buf = []
    for opt in opts:
        btn_text = opt["option_text"]
        callback_data = f"quiz_vote:{quiz_id}:{opt['option_id']}"
        row_buf.append(
            types.InlineKeyboardButton(text=btn_text, callback_data=callback_data)
        )
        if len(row_buf) == columns_count:
            kb_rows.append(row_buf)
            row_buf = []
    if row_buf:
        kb_rows.append(row_buf)

    reply_markup = types.InlineKeyboardMarkup(inline_keyboard=kb_rows)

    try:
        if quiz_data["photo_id"]:
            msg_sent = await message.bot.send_photo(
                chat_id=target_chat,
                photo=quiz_data["photo_id"],
                caption=quiz_text,
                reply_markup=reply_markup,
            )
        else:
            msg_sent = await message.bot.send_message(
                chat_id=target_chat, text=quiz_text, reply_markup=reply_markup
            )
    except Exception as e:
        await message.answer(f"Ошибка публикации в канал @{channel_username}: {e}")
        return

    async with db.acquire() as conn:
        await conn.execute(
            "UPDATE quizzes SET is_active=TRUE, post_chat_id=$1, post_message_id=$2, channel_id=$3 WHERE quiz_id=$4",
            msg_sent.chat.id,
            msg_sent.message_id,
            channel["channel_id"],
            quiz_id,
        )

    await message.answer(
        f"✅ Опрос #{quiz_id} успешно опубликован в канале @{channel_username}!"
    )


@quiz_router.callback_query(F.data.startswith("quiz_vote:"))
async def on_quiz_vote(callback: types.CallbackQuery, event_service):
    """Handle quiz voting with atomic DB operations."""
    try:
        _, quiz_id_str, option_id_str = callback.data.split(":")
        quiz_id = int(quiz_id_str)
        option_id = int(option_id_str)
        user_id = callback.from_user.id
    except (ValueError, IndexError):
        await callback.answer("Ошибка в данных. Попробуйте снова.", show_alert=True)
        return

    db = event_service.db

    async with db.acquire() as conn:
        async with conn.transaction():
            quiz = await conn.fetchrow(
                "SELECT * FROM quizzes WHERE quiz_id=$1 FOR UPDATE", quiz_id
            )
            if not quiz or not quiz["is_active"]:
                await callback.answer(
                    "Этот опрос больше неактивен.", show_alert=True
                )
                return

            previous_vote = await conn.fetchrow(
                "SELECT id, chosen_option_id FROM quiz_answers WHERE quiz_id=$1 AND user_id=$2",
                quiz_id,
                user_id,
            )

            if previous_vote:
                if not quiz["allow_vote_change"]:
                    await callback.answer(
                        "Вы уже проголосовали, и изменять свой голос запрещено.",
                        show_alert=True,
                    )
                    return
                if previous_vote["chosen_option_id"] == option_id:
                    await callback.answer("Вы уже выбрали этот вариант.")
                    return

                # Decrement old option
                await conn.execute(
                    "UPDATE quiz_options SET votes_count = votes_count - 1 "
                    "WHERE option_id=$1 AND votes_count > 0",
                    previous_vote["chosen_option_id"],
                )
                # Update answer
                await conn.execute(
                    "UPDATE quiz_answers SET chosen_option_id=$1, answered_at=$2 WHERE id=$3",
                    option_id,
                    datetime.datetime.now(datetime.timezone.utc),
                    previous_vote["id"],
                )
            else:
                # New vote
                await conn.execute(
                    "INSERT INTO quiz_answers(quiz_id, user_id, chosen_option_id, answered_at) "
                    "VALUES($1, $2, $3, $4)",
                    quiz_id,
                    user_id,
                    option_id,
                    datetime.datetime.now(datetime.timezone.utc),
                )

            # Increment chosen option
            await conn.execute(
                "UPDATE quiz_options SET votes_count = votes_count + 1 WHERE option_id=$1",
                option_id,
            )

            # Get updated totals for keyboard rebuild
            total_votes_row = await conn.fetchrow(
                "SELECT SUM(votes_count) as total FROM quiz_options WHERE quiz_id=$1",
                quiz_id,
            )
            total_votes = total_votes_row["total"] or 0

            opts = await conn.fetch(
                "SELECT option_id, option_text, votes_count FROM quiz_options "
                "WHERE quiz_id=$1 ORDER BY option_id",
                quiz_id,
            )

            # Rebuild keyboard with vote counts
            columns_count = quiz.get("columns_count", 1) or 1
            kb_rows = []
            row_buf = []
            for opt in opts:
                vote_count = opt["votes_count"] or 0
                percentage = (
                    round((vote_count / total_votes) * 100) if total_votes > 0 else 0
                )
                btn_text = f"{opt['option_text']} ({vote_count} | {percentage}%)"
                cb_data = f"quiz_vote:{quiz_id}:{opt['option_id']}"
                row_buf.append(
                    types.InlineKeyboardButton(text=btn_text, callback_data=cb_data)
                )
                if len(row_buf) == columns_count:
                    kb_rows.append(row_buf)
                    row_buf = []
            if row_buf:
                kb_rows.append(row_buf)

            reply_markup = types.InlineKeyboardMarkup(inline_keyboard=kb_rows)

            try:
                await callback.message.edit_reply_markup(reply_markup=reply_markup)
                await callback.answer("Ваш голос принят!")
            except TelegramBadRequest:
                await callback.answer("Ваш голос принят!")

            # Check if max_votes reached — finish quiz
            if quiz["max_votes"] and total_votes >= quiz["max_votes"]:
                await conn.execute(
                    "UPDATE quizzes SET is_active=FALSE WHERE quiz_id=$1", quiz_id
                )

                winner_opt = max(opts, key=lambda x: x["votes_count"])

                # Build final results text
                if callback.message.photo:
                    original_text = callback.message.caption or ""
                else:
                    original_text = callback.message.text or ""

                final_parts = [
                    f"<b>{original_text}</b>\n\n",
                    "<b>Голосование завершено!</b>\n\n<b>Итоги:</b>\n",
                ]
                for opt in opts:
                    final_parts.append(
                        f"▫️ {opt['option_text']} — {opt['votes_count']} голосов\n"
                    )
                final_parts.append(
                    f"\n🏆 Победил вариант «{winner_opt['option_text']}»!"
                )
                final_text = "".join(final_parts)

                try:
                    if callback.message.photo:
                        await callback.message.edit_caption(
                            caption=final_text, reply_markup=None
                        )
                    else:
                        await callback.message.edit_text(
                            final_text, reply_markup=None
                        )
                except Exception as e:
                    logging.warning(f"Could not edit quiz finish message: {e}")
