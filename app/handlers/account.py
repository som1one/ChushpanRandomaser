"""Handler for /account command — stats, FastConnect, language selection."""

import datetime
from aiogram import Router, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from app.states import FastConnectStates, FastConnectLoginStates

account_router = Router()


async def _render_profile_message(user_id: int, username: str | None, user_service) -> tuple[str, InlineKeyboardMarkup]:
    """Build account profile text and keyboard."""
    user_data = await user_service.get_user(user_id)
    if not user_data:
        await user_service.ensure_user_exists(user_id)
        user_data = await user_service.get_user(user_id)

    subscription = user_data["subscription"]
    fc_email = user_data.get("fastconnect_email") or None
    raw_first_visit = user_data.get("first_visit")

    reg_date = "N/A"
    if isinstance(raw_first_visit, datetime.datetime):
        reg_date = raw_first_visit.strftime("%d.%m.%Y")

    fc_part, fc_wins = await user_service.get_user_participation_stats(user_id, "fastclick")
    co_part, co_wins = await user_service.get_user_participation_stats(user_id, "contest")
    lo_part, lo_wins = await user_service.get_user_participation_stats(user_id, "lottery")

    def calc_percent(wins: int, total: int) -> int:
        return round(wins / total * 100) if total > 0 else 0

    fc_pct = calc_percent(fc_wins, fc_part)
    co_pct = calc_percent(co_wins, co_part)
    lo_pct = calc_percent(lo_wins, lo_part)

    display_name = username or f"User{user_id}"

    text = (
        f"📊 Аккаунт {display_name}\n\n"
        f"📅 Регистрация: {reg_date}\n"
        f"👑 Подписка: {'да' if subscription else 'нет'}\n"
        f"🆔 Fast Connect: {'да' if fc_email else 'нет'}\n\n"
        f"⭐️ ФастКлики: {fc_part} | {fc_pct}%\n"
        f"🎉 Конкурсы: {co_part} | {co_pct}%\n"
        f"🎟 Лотереи: {lo_part} | {lo_pct}%"
    )

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🆔 FastConnect", callback_data="account:fastconnect")],
        [InlineKeyboardButton(text="🌐 Язык / Language", callback_data="account:language")],
    ])
    return text, keyboard


async def _render_fastconnect_menu(user_id: int, user_service) -> tuple[str, InlineKeyboardMarkup]:
    """Build FastConnect settings text and keyboard."""
    user_data = await user_service.get_user(user_id)
    fc_email = user_data.get("fastconnect_email") or None
    fc_pass = user_data.get("fastconnect_password") or None

    text = "🆔 <b>Fast Connect</b> — защита и перенос аккаунта\n\n"
    if not fc_email and not fc_pass:
        text += "⚠️ Аккаунт не защищён! Привяжите почту и пароль."
    else:
        text += "Ваш аккаунт частично или полностью настроен.\n"
    if fc_email:
        text += f"\nТекущая почта: {fc_email}"
    if fc_pass:
        text += "\nПароль установлен."

    text += "\n\nЧто хотите сделать?"

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📧 Email", callback_data="fc:set_email"),
            InlineKeyboardButton(text="🔑 Пароль", callback_data="fc:set_password"),
        ],
        [
            InlineKeyboardButton(text="🗑 Удалить email", callback_data="fc:remove_email"),
            InlineKeyboardButton(text="🗑 Удалить пароль", callback_data="fc:remove_password"),
        ],
        [InlineKeyboardButton(text="🔓 Войти в аккаунт", callback_data="fc:login")],
        [InlineKeyboardButton(text="◀ Назад в профиль", callback_data="fc:back_profile")],
    ])
    return text, keyboard


def _render_language_keyboard() -> InlineKeyboardMarkup:
    """Build language selection keyboard."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🇷🇺 Русский", callback_data="lang:RU"),
            InlineKeyboardButton(text="🇬🇧 English", callback_data="lang:EN"),
        ],
        [InlineKeyboardButton(text="◀ Назад в профиль", callback_data="fc:back_profile")],
    ])


# --- Command handler ---

@account_router.message(Command("account", ignore_mention=True))
async def cmd_account(message: types.Message, state: FSMContext, **kwargs):
    """Show user participation stats and settings buttons."""
    user_service = kwargs.get("user_service")
    user_id = message.from_user.id
    username = message.from_user.username
    text, keyboard = await _render_profile_message(user_id, username, user_service)
    await message.answer(text, reply_markup=keyboard)


# --- FastConnect menu ---

@account_router.callback_query(F.data == "account:fastconnect")
async def on_fastconnect_menu(callback: types.CallbackQuery, **kwargs):
    """Open FastConnect settings menu."""
    user_service = kwargs.get("user_service")
    user_id = callback.from_user.id
    text, keyboard = await _render_fastconnect_menu(user_id, user_service)
    await callback.message.edit_text(text, reply_markup=keyboard)
    await callback.answer()


# --- FastConnect: set email ---

@account_router.callback_query(F.data == "fc:set_email")
async def on_fc_set_email(callback: types.CallbackQuery, state: FSMContext, **kwargs):
    """Prompt user to enter email for FastConnect."""
    await state.set_state(FastConnectStates.waiting_for_email)
    await callback.message.answer("Введите ваш email для FastConnect (или /cancel для отмены).")
    await callback.answer()


@account_router.message(FastConnectStates.waiting_for_email)
async def process_fc_email(message: types.Message, state: FSMContext, **kwargs):
    """Process FastConnect email input."""
    user_service = kwargs.get("user_service")

    if message.text and message.text.strip() == "/cancel":
        await state.clear()
        await message.answer("Отмена операции.")
        user_id = message.from_user.id
        text, keyboard = await _render_fastconnect_menu(user_id, user_service)
        await message.answer(text, reply_markup=keyboard)
        return

    email = (message.text or "").strip()
    if "@" not in email or "." not in email:
        await message.answer("Это не похоже на email. Повторите или /cancel.")
        return

    user_id = message.from_user.id
    await user_service.set_fastconnect_email(user_id, email)
    await message.answer("✅ Почта для FastConnect успешно сохранена!")
    await state.clear()
    text, keyboard = await _render_fastconnect_menu(user_id, user_service)
    await message.answer(text, reply_markup=keyboard)


# --- FastConnect: set password ---

@account_router.callback_query(F.data == "fc:set_password")
async def on_fc_set_password(callback: types.CallbackQuery, state: FSMContext, **kwargs):
    """Prompt user to enter a new password."""
    await state.set_state(FastConnectStates.waiting_for_password)
    await callback.message.answer("Введите новый пароль (или /cancel для отмены).")
    await callback.answer()


@account_router.message(FastConnectStates.waiting_for_password)
async def process_fc_password(message: types.Message, state: FSMContext, **kwargs):
    """Process FastConnect password input."""
    user_service = kwargs.get("user_service")

    if message.text and message.text.strip() == "/cancel":
        await state.clear()
        await message.answer("Отмена операции.")
        user_id = message.from_user.id
        text, keyboard = await _render_fastconnect_menu(user_id, user_service)
        await message.answer(text, reply_markup=keyboard)
        return

    password = (message.text or "").strip()
    user_id = message.from_user.id
    await user_service.set_fastconnect_password(user_id, password)
    await message.answer("✅ Пароль сохранён. Не забудьте его!")
    await state.clear()
    text, keyboard = await _render_fastconnect_menu(user_id, user_service)
    await message.answer(text, reply_markup=keyboard)


# --- FastConnect: remove email/password ---

@account_router.callback_query(F.data == "fc:remove_email")
async def on_fc_remove_email(callback: types.CallbackQuery, **kwargs):
    """Remove FastConnect email."""
    user_service = kwargs.get("user_service")
    user_id = callback.from_user.id
    await user_service.set_fastconnect_email(user_id, "")
    await callback.answer("Email удалён.")
    text, keyboard = await _render_fastconnect_menu(user_id, user_service)
    await callback.message.edit_text(text, reply_markup=keyboard)


@account_router.callback_query(F.data == "fc:remove_password")
async def on_fc_remove_password(callback: types.CallbackQuery, **kwargs):
    """Remove FastConnect password."""
    user_service = kwargs.get("user_service")
    user_id = callback.from_user.id
    await user_service.remove_fastconnect_password(user_id)
    await callback.answer("Пароль удалён.")
    text, keyboard = await _render_fastconnect_menu(user_id, user_service)
    await callback.message.edit_text(text, reply_markup=keyboard)


# --- FastConnect: login to existing account ---

@account_router.callback_query(F.data == "fc:login")
async def on_fc_login(callback: types.CallbackQuery, state: FSMContext, **kwargs):
    """Start FastConnect login flow (migrate from another account)."""
    await state.set_state(FastConnectLoginStates.waiting_for_email)
    await callback.message.answer("Введите email существующего аккаунта (или /cancel).")
    await callback.answer()


@account_router.message(FastConnectLoginStates.waiting_for_email)
async def fc_login_email(message: types.Message, state: FSMContext, **kwargs):
    """Process email for FastConnect login."""
    user_service = kwargs.get("user_service")

    if message.text and message.text.strip() == "/cancel":
        await state.clear()
        await message.answer("Отмена входа.")
        user_id = message.from_user.id
        text, keyboard = await _render_fastconnect_menu(user_id, user_service)
        await message.answer(text, reply_markup=keyboard)
        return

    email = (message.text or "").strip()
    if "@" not in email or "." not in email:
        await message.answer("Это не похоже на email. Повторите или /cancel.")
        return

    await state.update_data(fc_login_email=email)
    await state.set_state(FastConnectLoginStates.waiting_for_password)
    await message.answer("Введите пароль (или /cancel).")


@account_router.message(FastConnectLoginStates.waiting_for_password)
async def fc_login_password(message: types.Message, state: FSMContext, **kwargs):
    """Process password for FastConnect login and attempt migration."""
    user_service = kwargs.get("user_service")

    if message.text and message.text.strip() == "/cancel":
        await state.clear()
        await message.answer("Отмена входа.")
        user_id = message.from_user.id
        text, keyboard = await _render_fastconnect_menu(user_id, user_service)
        await message.answer(text, reply_markup=keyboard)
        return

    password = (message.text or "").strip()
    data = await state.get_data()
    email = data.get("fc_login_email", "")
    user_id = message.from_user.id

    ok = await user_service.attempt_fastconnect_login(user_id, email, password)
    if ok:
        await message.answer("✅ Вы успешно вошли! Данные аккаунта мигрированы.")
    else:
        await message.answer("❌ Не удалось найти аккаунт с таким email и паролем.")

    await state.clear()
    text, keyboard = await _render_fastconnect_menu(user_id, user_service)
    await message.answer(text, reply_markup=keyboard)


# --- Language selection ---

@account_router.callback_query(F.data == "account:language")
async def on_language_menu(callback: types.CallbackQuery, **kwargs):
    """Show language selection keyboard."""
    await callback.message.edit_text(
        "🌐 Выберите язык / Choose language:",
        reply_markup=_render_language_keyboard(),
    )
    await callback.answer()


@account_router.callback_query(F.data.startswith("lang:"))
async def on_language_select(callback: types.CallbackQuery, **kwargs):
    """Set user language preference."""
    user_service = kwargs.get("user_service")
    lang = callback.data.split(":")[1]  # "RU" or "EN"
    user_id = callback.from_user.id

    await user_service.set_user_language(user_id, lang)

    if lang == "RU":
        await callback.answer("Язык установлен: Русский")
    else:
        await callback.answer("Language set: English")

    # Return to profile
    username = callback.from_user.username
    text, keyboard = await _render_profile_message(user_id, username, user_service)
    await callback.message.edit_text(text, reply_markup=keyboard)


# --- Back to profile ---

@account_router.callback_query(F.data == "fc:back_profile")
async def on_back_to_profile(callback: types.CallbackQuery, **kwargs):
    """Return to profile view from FastConnect or language menu."""
    user_service = kwargs.get("user_service")
    user_id = callback.from_user.id
    username = callback.from_user.username
    text, keyboard = await _render_profile_message(user_id, username, user_service)
    await callback.message.edit_text(text, reply_markup=keyboard)
    await callback.answer()
