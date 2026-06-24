"""Handler for /top command — shows active events from the last 3 days."""

from aiogram import Router, types
from aiogram.filters import Command

from app.services.event_service import EventService

top_router = Router()


@top_router.message(Command("top"))
async def cmd_top(message: types.Message, event_service: EventService, **kwargs):
    """Handle /top command — display recently created active events."""
    events = await event_service.get_recent_events_for_top()

    if not events:
        await message.answer("Нет активных событий")
        return

    lines = ["<b>🔥 Активные события (последние 3 дня):</b>\n"]
    for i, ev in enumerate(events, start=1):
        title = ev.get("title") or "Без названия"
        event_type = ev.get("event_type", "")
        type_emoji = {
            "contest": "🎟",
            "lottery": "🎰",
            "referral": "🔗",
            "fastclick": "⚡",
        }.get(event_type, "📌")
        lines.append(f"{i}. {type_emoji} {title} (ID: {ev['event_id']})")

    await message.answer("\n".join(lines))
