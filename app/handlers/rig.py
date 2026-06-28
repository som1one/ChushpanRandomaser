"""Handler for /rig command — rigging panel with paginated participant toggles."""

from aiogram import Router, types, F
from aiogram.filters import Command

from app.services.rig_service import RigService
from app.services.event_service import EventService

rig_router = Router()

PAGE_SIZE = 8


async def _get_manageable_events(
    event_service: EventService, rig_service: RigService, user_id: int
) -> list[dict]:
    """Get all events for rigging panel (admin-only access).

    Only admins (config or DB) can use the rigging panel — they see all events.
    """
    is_admin = user_id in rig_service.admin_ids
    if not is_admin:
        async with rig_service.db.acquire() as conn:
            row = await conn.fetchval("SELECT 1 FROM admins WHERE user_id=$1", str(user_id))
            is_admin = row is not None

    if not is_admin:
        return []

    return await event_service.get_all_events()


def _build_event_list_markup(events: list[dict]) -> types.InlineKeyboardMarkup:
    """Build inline keyboard with event list for rigging panel."""
    rows = []
    for event in events:
        title = event.get("title") or f"Событие #{event['event_id']}"
        status = "🟢" if event.get("is_active") else "🔴"
        rows.append([
            types.InlineKeyboardButton(
                text=f"{status} #{event['event_id']} — {title}",
                callback_data=f"rig_draw:{event['event_id']}"
            )
        ])
    return types.InlineKeyboardMarkup(inline_keyboard=rows)


async def _build_participant_panel(
    rig_service: RigService, event: dict, page: int = 0
) -> tuple[str, types.InlineKeyboardMarkup]:
    """Build the participant panel text and keyboard for a given event and page."""
    event_id = event["event_id"]
    participants, total_pages = await rig_service.get_participants_page(
        event_id, page=page, page_size=PAGE_SIZE
    )

    # Get rigged count for the header
    guaranteed = await rig_service.get_guaranteed_players(event_id)
    rigged_count = len(guaranteed)
    max_winners = event.get("max_winners", 1)

    title = event.get("title") or f"Событие #{event_id}"
    header = (
        f"⚙️ <b>Подкрутка: {title}</b>\n"
        f"ID: #{event_id} | ⭐ {rigged_count}/{max_winners}\n"
        f"Страница {page + 1}/{total_pages}\n"
        f"{'─' * 20}"
    )

    # Build participant toggle buttons
    rows = []
    for p in participants:
        username = p.get("username") or f"ID:{p['user_id']}"
        icon = "⭐" if p["guaranteed_winner"] else "⬜"
        rows.append([
            types.InlineKeyboardButton(
                text=f"{icon} {username}",
                callback_data=f"rig_toggle:{event_id}:{p['user_id']}"
            )
        ])

    # Navigation buttons
    nav_row = []
    if page > 0:
        nav_row.append(
            types.InlineKeyboardButton(
                text="◀️", callback_data=f"rig_page:{event_id}:{page - 1}"
            )
        )
    if page < total_pages - 1:
        nav_row.append(
            types.InlineKeyboardButton(
                text="▶️", callback_data=f"rig_page:{event_id}:{page + 1}"
            )
        )
    if nav_row:
        rows.append(nav_row)

    # Back button
    rows.append([
        types.InlineKeyboardButton(text="◀️ Назад к списку", callback_data="rig_back")
    ])

    markup = types.InlineKeyboardMarkup(inline_keyboard=rows)
    return header, markup


@rig_router.message(Command("rig"))
async def cmd_rig(
    message: types.Message,
    rig_service: RigService,
    event_service: EventService,
):
    """Show list of events for rigging (admin only)."""
    user_id = message.from_user.id
    events = await _get_manageable_events(event_service, rig_service, user_id)

    if not events:
        await message.answer("🚫 Нет доступа или нет событий для управления.")
        return

    markup = _build_event_list_markup(events)
    await message.answer(
        "⚙️ <b>Панель подкрутки</b>\n\nВыберите событие:",
        reply_markup=markup,
    )


@rig_router.callback_query(F.data.startswith("rig_draw:"))
async def on_rig_draw(
    callback: types.CallbackQuery,
    rig_service: RigService,
    event_service: EventService,
):
    """Show paginated participant panel for a specific event (admin only)."""
    event_id = int(callback.data.split(":")[1])
    user_id = callback.from_user.id

    # Admin check
    is_admin = user_id in rig_service.admin_ids
    if not is_admin:
        async with rig_service.db.acquire() as conn:
            row = await conn.fetchval("SELECT 1 FROM admins WHERE user_id=$1", str(user_id))
            is_admin = row is not None

    if not is_admin:
        await callback.answer("🚫 Нет доступа", show_alert=True)
        return

    event = await event_service.get_event(event_id)
    if not event:
        await callback.answer("Событие не найдено.", show_alert=True)
        return

    header, markup = await _build_participant_panel(rig_service, event, page=0)
    await callback.message.edit_text(header, reply_markup=markup)
    await callback.answer()


@rig_router.callback_query(F.data.startswith("rig_toggle:"))
async def on_rig_toggle(
    callback: types.CallbackQuery,
    rig_service: RigService,
    event_service: EventService,
):
    """Toggle guaranteed_winner status for a participant (admin only)."""
    parts = callback.data.split(":")
    event_id = int(parts[1])
    target_user_id = int(parts[2])
    admin_id = callback.from_user.id

    # Admin check
    is_admin = admin_id in rig_service.admin_ids
    if not is_admin:
        async with rig_service.db.acquire() as conn:
            row = await conn.fetchval("SELECT 1 FROM admins WHERE user_id=$1", str(admin_id))
            is_admin = row is not None

    if not is_admin:
        await callback.answer("🚫 Нет доступа", show_alert=True)
        return

    result = await rig_service.toggle_guaranteed(event_id, target_user_id, admin_id)

    if not result.success:
        await callback.answer(result.message, show_alert=True)
        return

    # Refresh the panel on current page
    event = await event_service.get_event(event_id)
    if not event:
        await callback.answer("Событие не найдено.", show_alert=True)
        return

    page = _extract_page_from_text(callback.message.text or "")

    header, markup = await _build_participant_panel(rig_service, event, page=page)
    await callback.message.edit_text(header, reply_markup=markup)
    await callback.answer(result.message)


@rig_router.callback_query(F.data.startswith("rig_page:"))
async def on_rig_page(
    callback: types.CallbackQuery,
    rig_service: RigService,
    event_service: EventService,
):
    """Navigate between pages in the participant panel (admin only)."""
    parts = callback.data.split(":")
    event_id = int(parts[1])
    page = int(parts[2])
    user_id = callback.from_user.id

    # Admin check
    is_admin = user_id in rig_service.admin_ids
    if not is_admin:
        async with rig_service.db.acquire() as conn:
            row = await conn.fetchval("SELECT 1 FROM admins WHERE user_id=$1", str(user_id))
            is_admin = row is not None

    if not is_admin:
        await callback.answer("🚫 Нет доступа", show_alert=True)
        return

    event = await event_service.get_event(event_id)
    if not event:
        await callback.answer("Событие не найдено.", show_alert=True)
        return

    header, markup = await _build_participant_panel(rig_service, event, page=page)
    await callback.message.edit_text(header, reply_markup=markup)
    await callback.answer()


@rig_router.callback_query(F.data == "rig_back")
async def on_rig_back(
    callback: types.CallbackQuery,
    rig_service: RigService,
    event_service: EventService,
):
    """Return to event list from participant panel (admin only)."""
    user_id = callback.from_user.id
    events = await _get_manageable_events(event_service, rig_service, user_id)

    if not events:
        await callback.message.edit_text("🚫 Нет доступа или нет событий.")
        await callback.answer()
        return

    markup = _build_event_list_markup(events)
    await callback.message.edit_text(
        "⚙️ <b>Панель подкрутки</b>\n\nВыберите событие:",
        reply_markup=markup,
    )
    await callback.answer()


def _extract_page_from_text(text: str) -> int:
    """Extract current page number from panel header text.

    Header format: '... Страница X/Y ...'
    Returns 0-indexed page number, defaults to 0 if not found.
    """
    import re

    match = re.search(r"Страница (\d+)/\d+", text)
    if match:
        return int(match.group(1)) - 1
    return 0
