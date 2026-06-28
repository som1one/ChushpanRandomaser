"""Handler for /admin command — admin panel with admin management, mailing stub, and cache clear."""

from aiogram import Router, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from app.services.rig_service import RigService
from app.services.notification_service import NotificationService
from app.states import MailingStates
from app.utils.cache import SimpleCache

admin_router = Router()


class AdminManageStates(StatesGroup):
    """Inline states for admin add/remove flow."""
    waiting_for_admin_id = State()


async def _is_admin(user_id: int, rig_service: RigService) -> bool:
    """Check if user is a super-admin (config) or DB-stored admin."""
    if user_id in rig_service.admin_ids:
        return True
    # Check DB admins table
    async with rig_service.db.acquire() as conn:
        row = await conn.fetchval(
            "SELECT 1 FROM admins WHERE user_id=$1", user_id
        )
        return row is not None


def _admin_panel_keyboard() -> types.InlineKeyboardMarkup:
    """Build admin panel main menu keyboard."""
    return types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="⚙️ Управление событиями", callback_data="menu:manage")],
        [types.InlineKeyboardButton(text="👥 Список админов", callback_data="admin:list")],
        [
            types.InlineKeyboardButton(text="➕ Добавить админа", callback_data="admin:add"),
            types.InlineKeyboardButton(text="➖ Удалить админа", callback_data="admin:remove"),
        ],
        [types.InlineKeyboardButton(text="📢 Рассылка", callback_data="admin:mailing")],
        [types.InlineKeyboardButton(text="🗑 Очистить кеш", callback_data="admin:clear_cache")],
    ])


@admin_router.message(Command("admin"))
async def cmd_admin(
    message: types.Message,
    rig_service: RigService,
    **kwargs,
):
    """Show admin panel (only for admins)."""
    user_id = message.from_user.id
    if not await _is_admin(user_id, rig_service):
        await message.answer("🚫 У вас нет доступа к панели администратора.")
        return

    await message.answer(
        "🛠 <b>Админ-панель</b>\n\nВыберите действие:",
        reply_markup=_admin_panel_keyboard(),
    )


@admin_router.callback_query(F.data == "admin:list")
async def on_admin_list(
    callback: types.CallbackQuery,
    rig_service: RigService,
    **kwargs,
):
    """Show list of all admins (config + DB)."""
    user_id = callback.from_user.id
    if not await _is_admin(user_id, rig_service):
        await callback.answer("Нет доступа", show_alert=True)
        return

    # Gather admin list from config
    lines = ["<b>👥 Список администраторов:</b>\n"]
    lines.append("<i>Суперадмины (config):</i>")
    for admin_id in rig_service.admin_ids:
        lines.append(f"  • <code>{admin_id}</code>")

    # Gather admin list from DB
    async with rig_service.db.acquire() as conn:
        db_admins = await conn.fetch(
            "SELECT user_id, username, added_by FROM admins ORDER BY created_at ASC"
        )

    if db_admins:
        lines.append("\n<i>Админы из БД:</i>")
        for row in db_admins:
            username = row["username"] or "—"
            lines.append(f"  • <code>{row['user_id']}</code> (@{username})")
    else:
        lines.append("\n<i>Админов в БД нет.</i>")

    back_btn = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="◀️ Назад", callback_data="admin:back")]
    ])
    await callback.message.edit_text("\n".join(lines), reply_markup=back_btn)
    await callback.answer()


@admin_router.callback_query(F.data == "admin:add")
async def on_admin_add(
    callback: types.CallbackQuery,
    state: FSMContext,
    rig_service: RigService,
    **kwargs,
):
    """Prompt for user ID to add as admin."""
    user_id = callback.from_user.id
    if not await _is_admin(user_id, rig_service):
        await callback.answer("Нет доступа", show_alert=True)
        return

    # Only super-admins (from config) can add/remove other admins
    if user_id not in rig_service.admin_ids:
        await callback.answer("Только суперадмины могут управлять списком.", show_alert=True)
        return

    await state.set_state(AdminManageStates.waiting_for_admin_id)
    await state.update_data(admin_action="add")
    await callback.message.edit_text(
        "Введите ID пользователя, которого хотите добавить как админа:\n"
        "(Отправьте /cancel для отмены)",
        reply_markup=None,
    )
    await callback.answer()


@admin_router.callback_query(F.data == "admin:remove")
async def on_admin_remove(
    callback: types.CallbackQuery,
    state: FSMContext,
    rig_service: RigService,
    **kwargs,
):
    """Prompt for user ID to remove from admins."""
    user_id = callback.from_user.id
    if not await _is_admin(user_id, rig_service):
        await callback.answer("Нет доступа", show_alert=True)
        return

    if user_id not in rig_service.admin_ids:
        await callback.answer("Только суперадмины могут управлять списком.", show_alert=True)
        return

    await state.set_state(AdminManageStates.waiting_for_admin_id)
    await state.update_data(admin_action="remove")
    await callback.message.edit_text(
        "Введите ID пользователя, которого хотите удалить из админов:\n"
        "(Отправьте /cancel для отмены)",
        reply_markup=None,
    )
    await callback.answer()


@admin_router.message(AdminManageStates.waiting_for_admin_id, F.text)
async def on_admin_manage_input(
    message: types.Message,
    state: FSMContext,
    rig_service: RigService,
    **kwargs,
):
    """Handle admin add/remove input (user ID)."""
    user_id = message.from_user.id
    if user_id not in rig_service.admin_ids:
        await state.clear()
        return

    data = await state.get_data()
    action = data.get("admin_action")

    if not action:
        await state.clear()
        return

    text = message.text.strip()
    if text == "/cancel":
        await state.clear()
        await message.answer("Отменено.", reply_markup=None)
        return

    if not text.isdigit():
        await message.answer("Введите числовой ID пользователя или /cancel для отмены.")
        return

    target_id = int(text)

    if action == "add":
        async with rig_service.db.acquire() as conn:
            # Check if already exists
            exists = await conn.fetchval(
                "SELECT 1 FROM admins WHERE user_id=$1", target_id
            )
            if exists:
                await message.answer(f"Пользователь <code>{target_id}</code> уже является админом.")
            else:
                # Try to get username from Telegram
                username = None
                try:
                    chat = await message.bot.get_chat(target_id)
                    username = chat.username
                except Exception:
                    pass
                await conn.execute(
                    "INSERT INTO admins (user_id, username, added_by) VALUES ($1, $2, $3)",
                    target_id, username, user_id,
                )
                await message.answer(f"✅ Пользователь <code>{target_id}</code> добавлен как админ.")
    elif action == "remove":
        async with rig_service.db.acquire() as conn:
            result = await conn.execute(
                "DELETE FROM admins WHERE user_id=$1", target_id
            )
            if "DELETE 1" in result:
                await message.answer(f"✅ Пользователь <code>{target_id}</code> удалён из админов.")
            else:
                await message.answer(f"Пользователь <code>{target_id}</code> не найден в списке админов БД.")

    await state.clear()
    # Return to admin panel
    await message.answer(
        "🛠 <b>Админ-панель</b>\n\nВыберите действие:",
        reply_markup=_admin_panel_keyboard(),
    )


@admin_router.callback_query(F.data == "admin:mailing")
async def on_admin_mailing(
    callback: types.CallbackQuery,
    rig_service: RigService,
    notification_service: NotificationService,
    **kwargs,
):
    """Mailing stub — show info that full mailing is available."""
    user_id = callback.from_user.id
    if not await _is_admin(user_id, rig_service):
        await callback.answer("Нет доступа", show_alert=True)
        return

    back_btn = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="◀️ Назад", callback_data="admin:back")]
    ])
    await callback.message.edit_text(
        "📢 <b>Рассылка</b>\n\n"
        "Функция рассылки в разработке.\n"
        "Используйте полное меню рассылки через FSM-состояния MailingStates "
        "для отправки сообщений всем пользователям.",
        reply_markup=back_btn,
    )
    await callback.answer()


@admin_router.callback_query(F.data == "admin:clear_cache")
async def on_admin_clear_cache(
    callback: types.CallbackQuery,
    rig_service: RigService,
    cache: SimpleCache = None,
    **kwargs,
):
    """Clear the TTL cache."""
    user_id = callback.from_user.id
    if not await _is_admin(user_id, rig_service):
        await callback.answer("Нет доступа", show_alert=True)
        return

    if cache:
        cache.clear()
        await callback.answer("🧹 Кеш очищен!", show_alert=True)
    else:
        await callback.answer("Кеш не используется.", show_alert=True)

    # Stay on admin panel
    await callback.message.edit_text(
        "🛠 <b>Админ-панель</b>\n\nВыберите действие:",
        reply_markup=_admin_panel_keyboard(),
    )


@admin_router.callback_query(F.data == "admin:back")
async def on_admin_back(
    callback: types.CallbackQuery,
    rig_service: RigService,
    **kwargs,
):
    """Return to admin panel main menu."""
    user_id = callback.from_user.id
    if not await _is_admin(user_id, rig_service):
        await callback.answer("Нет доступа", show_alert=True)
        return

    await callback.message.edit_text(
        "🛠 <b>Админ-панель</b>\n\nВыберите действие:",
        reply_markup=_admin_panel_keyboard(),
    )
    await callback.answer()
