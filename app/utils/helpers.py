import html
import logging
from datetime import datetime, timedelta
from typing import Optional
from aiogram import Bot


def quote_html(text: str) -> str:
    """Escape HTML special characters."""
    return html.escape(str(text))


def hlink(text: str, url: str) -> str:
    """Create HTML hyperlink."""
    return f'<a href="{url}">{quote_html(text)}</a>'


def get_future_time_examples() -> str:
    """Generate example future timestamps for user guidance."""
    now = datetime.now()
    examples = []
    for delta in (timedelta(hours=1), timedelta(hours=6), timedelta(days=1), timedelta(days=3)):
        future = now + delta
        examples.append(future.strftime("%d.%m.%Y %H:%M:%S"))
    return "\n\nПримеры:\n" + "\n".join(f"• `{e}`" for e in examples)


def parse_channel_username(text: str) -> Optional[str]:
    """Extract channel username from various formats (@username, t.me/username, https://t.me/username)."""
    text = text.strip()
    if text.startswith("@"):
        return text[1:]
    if "t.me/" in text:
        parts = text.split("t.me/")
        if len(parts) > 1:
            username = parts[1].split("/")[0].split("?")[0].strip()
            if username:
                return username
    return text if text and not text.startswith("http") else None


def parse_channel_username_from_message(message) -> Optional[str]:
    """Extract channel username from message (text, forward, or link)."""
    if message.forward_from_chat:
        return message.forward_from_chat.username
    text = message.text or message.caption or ""
    return parse_channel_username(text)


async def is_bot_admin_in_channel(channel_identifier: str, bot: Bot) -> tuple[bool, str]:
    """Check if bot is admin in a channel. Returns (is_admin, error_message)."""
    try:
        chat_id = channel_identifier if channel_identifier.startswith("-") else f"@{channel_identifier}"
        bot_info = await bot.get_me()
        member = await bot.get_chat_member(chat_id, bot_info.id)
        if member.status in ("administrator", "creator"):
            return True, ""
        return False, "Бот не является администратором."
    except Exception as e:
        logging.warning(f"Cannot verify admin status for {channel_identifier}: {e}")
        return False, f"Не удалось проверить канал: {e}"
