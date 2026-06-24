"""Handler for /post command — post builder with text, media, and URL buttons."""

from aiogram import Router, types, F
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext

from app.states import PostBuilderStates
from app.services.channel_service import ChannelService

post_router = Router()


@post_router.message(Command("post"))
async def cmd_post(message: types.Message, state: FSMContext, **kwargs):
    """Start the post builder — ask for text/media content."""
    await state.clear()
    kb = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="❌ Отмена", callback_data="post_cancel")]
    ])
    await message.answer(
        "📰 <b>Создание поста</b>\n\n"
        "Отправьте текст поста. Можно прикрепить фото, видео или GIF.",
        reply_markup=kb,
    )
    await state.set_state(PostBuilderStates.waiting_for_content)


@post_router.callback_query(StateFilter(PostBuilderStates), F.data == "post_cancel")
async def post_cancel(callback: types.CallbackQuery, state: FSMContext):
    """Cancel post creation at any step."""
    await state.clear()
    await callback.message.answer("Создание поста отменено.")
    await callback.answer()


@post_router.message(
    PostBuilderStates.waiting_for_content,
    F.content_type.in_({"text", "photo", "video", "animation"}),
)
async def got_post_content(message: types.Message, state: FSMContext):
    """Receive post text/media and move to button collection step."""
    media_type = None
    file_id = None
    text_part = message.text or message.caption or ""

    if message.photo:
        file_id = message.photo[-1].file_id
        media_type = "photo"
    elif message.video:
        file_id = message.video.file_id
        media_type = "video"
    elif message.animation:
        file_id = message.animation.file_id
        media_type = "animation"

    await state.update_data(
        post_text=text_part.strip(),
        post_media_id=file_id,
        post_media_type=media_type,
        buttons=[],
    )

    kb = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(
            text="✅ Опубликовать без кнопок", callback_data="post_publish_no_buttons"
        )],
        [types.InlineKeyboardButton(text="❌ Отмена", callback_data="post_cancel")],
    ])
    await message.answer(
        "🔗 Теперь отправьте текст для URL-кнопки или опубликуйте без кнопок.",
        reply_markup=kb,
    )
    await state.set_state(PostBuilderStates.adding_buttons)


@post_router.message(PostBuilderStates.adding_buttons, F.text)
async def process_button_text(message: types.Message, state: FSMContext):
    """Receive button text and ask for URL."""
    btn_text = message.text.strip()
    if not btn_text:
        await message.answer("Текст кнопки не может быть пустым.")
        return

    await state.update_data(current_button_text=btn_text)
    data = await state.get_data()
    btn_number = len(data.get("buttons", [])) + 1
    await message.answer(f"🔗 Отправьте ссылку для кнопки №{btn_number}:")
    await state.set_state(PostBuilderStates.waiting_for_button_url)


@post_router.message(PostBuilderStates.waiting_for_button_url, F.text)
async def process_button_url(
    message: types.Message, state: FSMContext, channel_service: ChannelService, **kwargs
):
    """Receive button URL, validate, and ask for next action."""
    url = message.text.strip()
    if not (url.startswith("http://") or url.startswith("https://") or url.startswith("tg://")):
        await message.answer("Ссылка должна начинаться с http://, https:// или tg://")
        return

    data = await state.get_data()
    buttons = data.get("buttons", [])
    buttons.append({"text": data["current_button_text"], "url": url})
    await state.update_data(buttons=buttons, current_button_text=None)

    if len(buttons) >= 10:
        # Max buttons reached — publish directly
        await _publish_post(message, state, channel_service)
        return

    kb = types.InlineKeyboardMarkup(inline_keyboard=[
        [
            types.InlineKeyboardButton(text="➕ Добавить кнопку", callback_data="post_add_button"),
            types.InlineKeyboardButton(text="✅ Опубликовать", callback_data="post_publish_now"),
        ],
        [types.InlineKeyboardButton(text="❌ Отмена", callback_data="post_cancel")],
    ])
    await message.answer(
        f"✨ Добавлено кнопок: {len(buttons)}. Добавить ещё или опубликовать?",
        reply_markup=kb,
    )
    await state.set_state(PostBuilderStates.adding_buttons)


@post_router.callback_query(PostBuilderStates.adding_buttons, F.data == "post_add_button")
async def add_another_button(callback: types.CallbackQuery, state: FSMContext):
    """User wants to add another URL button."""
    data = await state.get_data()
    next_num = len(data.get("buttons", [])) + 1
    await callback.message.answer(f"Введите текст кнопки №{next_num}:")
    await callback.answer()


@post_router.callback_query(PostBuilderStates.adding_buttons, F.data == "post_publish_no_buttons")
async def publish_no_buttons(
    callback: types.CallbackQuery, state: FSMContext, channel_service: ChannelService, **kwargs
):
    """Publish post without any URL buttons."""
    await callback.answer()
    await _publish_post(callback.message, state, channel_service)


@post_router.callback_query(PostBuilderStates.adding_buttons, F.data == "post_publish_now")
async def publish_with_buttons(
    callback: types.CallbackQuery, state: FSMContext, channel_service: ChannelService, **kwargs
):
    """Publish post with collected URL buttons."""
    await callback.answer()
    await _publish_post(callback.message, state, channel_service)


async def _publish_post(
    message: types.Message, state: FSMContext, channel_service: ChannelService
) -> None:
    """Build and publish the post to user's active channel via channel_service."""
    data = await state.get_data()
    post_text = data.get("post_text", "")
    media_id = data.get("post_media_id")
    media_type = data.get("post_media_type")
    buttons = data.get("buttons", [])

    # Determine chat_id for publish
    user_id = message.chat.id
    channel = await channel_service.get_active_channel(user_id)

    if not channel:
        await message.answer(
            "❗ У вас нет активного канала. Добавьте канал через /channel."
        )
        await state.clear()
        return

    channel_id = channel["channel_id"]
    channel_username = channel.get("username", "")

    # Build inline keyboard from collected buttons
    markup = _build_button_markup(buttons)

    try:
        if media_id and media_type:
            send_method = getattr(message.bot, f"send_{media_type}", None)
            if send_method:
                await send_method(
                    chat_id=channel_id,
                    **{media_type: media_id},
                    caption=post_text or None,
                    reply_markup=markup,
                )
            else:
                await message.bot.send_message(
                    chat_id=channel_id, text=post_text, reply_markup=markup
                )
        else:
            await message.bot.send_message(
                chat_id=channel_id, text=post_text or "​", reply_markup=markup
            )

        display_name = f"@{channel_username}" if channel_username else str(channel_id)
        await message.answer(f"✅ Пост опубликован в {display_name}!")
    except Exception as e:
        await message.answer(f"❌ Ошибка при публикации: {e}")

    await state.clear()


def _build_button_markup(
    buttons: list[dict],
) -> types.InlineKeyboardMarkup | None:
    """Build InlineKeyboardMarkup from button list with single-column layout."""
    if not buttons:
        return None

    kb_rows = []
    for btn in buttons:
        kb_rows.append([
            types.InlineKeyboardButton(text=btn["text"], url=btn["url"])
        ])

    return types.InlineKeyboardMarkup(inline_keyboard=kb_rows)
