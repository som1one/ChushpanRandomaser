"""Handler for /start and /cancel commands."""

from aiogram import Router, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

start_router = Router()


def get_main_menu_keyboard() -> InlineKeyboardMarkup:
    """Build the main menu inline keyboard."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🎟 Конкурс", callback_data="menu:lot"),
            InlineKeyboardButton(text="⚡ ФастКлик", callback_data="menu:fast"),
        ],
        [
            InlineKeyboardButton(text="📝 Опрос", callback_data="menu:quiz"),
            InlineKeyboardButton(text="📰 Пост", callback_data="menu:post"),
        ],
        [
            InlineKeyboardButton(text="📋 События", callback_data="menu:list"),
            InlineKeyboardButton(text="⚙️ Управление", callback_data="menu:manage"),
        ],
    ])


@start_router.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext, **kwargs):
    """Handle /start command — show welcome message and main menu."""
    await state.clear()

    user = message.from_user
    name = user.first_name or user.username or "друг"

    # Handle referral deep link (ref_{event_id}_{inviter_id})
    args = message.text.split(maxsplit=1)
    if len(args) > 1 and args[1].startswith("ref_"):
        parts = args[1].split("_")
        if len(parts) == 3:
            try:
                event_id = int(parts[1])
                inviter_id = int(parts[2])
                if inviter_id != user.id:
                    await state.update_data(
                        referred_event_id=event_id, inviter_id=inviter_id
                    )
            except (ValueError, IndexError):
                pass

    await message.answer(
        f"👋 Привет, {name}!\n\n"
        "Я — бот для проведения розыгрышей, конкурсов и лотерей.\n"
        "Выбери действие из меню ниже:",
        reply_markup=get_main_menu_keyboard(),
    )


@start_router.message(Command("cancel"))
async def cmd_cancel(message: types.Message, state: FSMContext, **kwargs):
    """Handle /cancel command — clear FSM state and notify user."""
    await state.clear()
    await message.answer("Действие отменено.")


# --- Menu button callbacks ---

@start_router.callback_query(F.data == "menu:lot")
async def menu_lot(callback: types.CallbackQuery, state: FSMContext, **kwargs):
    """Redirect to /lot flow."""
    from app.states import LotMenuStates
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


@start_router.callback_query(F.data == "menu:fast")
async def menu_fast(callback: types.CallbackQuery, state: FSMContext, **kwargs):
    """Redirect to /fast flow."""
    await state.clear()
    await callback.message.edit_text("🔥 Введите текст фастклика:")
    from app.states import FastClickStates
    await state.set_state(FastClickStates.waiting_for_text)
    await callback.answer()


@start_router.callback_query(F.data == "menu:quiz")
async def menu_quiz(callback: types.CallbackQuery, state: FSMContext, **kwargs):
    """Redirect to /quiz flow."""
    from app.states import QuizCreationStates
    await state.clear()
    kb = types.InlineKeyboardMarkup(inline_keyboard=[
        [
            types.InlineKeyboardButton(text="1", callback_data="columns_1"),
            types.InlineKeyboardButton(text="2", callback_data="columns_2"),
            types.InlineKeyboardButton(text="3", callback_data="columns_3"),
        ],
        [types.InlineKeyboardButton(text="Отменить ввод", callback_data="quiz_cancel")],
    ])
    await callback.message.edit_text(
        "💠 <b>Выберите количество столбцов</b> (1..3)\n\n"
        "Чем больше столбцов, тем меньше текста влезает в кнопку.",
        reply_markup=kb,
    )
    await state.set_state(QuizCreationStates.choosing_columns)
    await callback.answer()


@start_router.callback_query(F.data == "menu:post")
async def menu_post(callback: types.CallbackQuery, state: FSMContext, **kwargs):
    """Redirect to /post flow."""
    from app.states import PostBuilderStates
    await state.clear()
    kb = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="❌ Отмена", callback_data="post_cancel")]
    ])
    await callback.message.edit_text(
        "📰 <b>Создание поста</b>\n\n"
        "Отправьте текст поста. Можно прикрепить фото, видео или GIF.",
        reply_markup=kb,
    )
    await state.set_state(PostBuilderStates.waiting_for_content)
    await callback.answer()


@start_router.callback_query(F.data == "menu:list")
async def menu_list(callback: types.CallbackQuery, state: FSMContext, **kwargs):
    """Redirect to /list flow."""
    from app.states import ListManageStates
    await state.clear()
    kb = types.InlineKeyboardMarkup(inline_keyboard=[
        [
            types.InlineKeyboardButton(text="🟢 Активные", callback_data="list_show_active"),
            types.InlineKeyboardButton(text="🔴 Завершённые", callback_data="list_show_finished"),
            types.InlineKeyboardButton(text="📝 Неопубликованные", callback_data="list_show_unpub"),
        ],
    ])
    await callback.message.edit_text(
        "<b>Управление вашими конкурсами/лотереями</b>\n\nВыберите категорию событий:",
        reply_markup=kb,
    )
    await state.set_state(ListManageStates.list_main)
    await callback.answer()


@start_router.callback_query(F.data == "menu:manage")
async def menu_manage(callback: types.CallbackQuery, **kwargs):
    """Redirect to /rig flow."""
    rig_service = kwargs.get("rig_service")
    event_service = kwargs.get("event_service")
    user_id = callback.from_user.id

    if not rig_service or not event_service:
        await callback.answer("Сервис недоступен", show_alert=True)
        return

    # Get manageable events
    user_events = await event_service.get_user_events(user_id)
    manageable = []
    for event in user_events:
        if await rig_service.can_manage_event(event["event_id"], user_id):
            manageable.append(event)

    if not manageable:
        await callback.answer("Нет событий для управления", show_alert=True)
        return

    rows = []
    for event in manageable:
        title = event.get("title") or f"Событие #{event['event_id']}"
        status = "🟢" if event.get("is_active") else "🔴"
        rows.append([
            types.InlineKeyboardButton(
                text=f"{status} #{event['event_id']} — {title[:25]}",
                callback_data=f"rig_draw:{event['event_id']}"
            )
        ])

    markup = types.InlineKeyboardMarkup(inline_keyboard=rows)
    await callback.message.edit_text(
        "⚙️ <b>Панель подкрутки</b>\n\nВыберите событие:",
        reply_markup=markup,
    )
    await callback.answer()
