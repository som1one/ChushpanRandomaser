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
