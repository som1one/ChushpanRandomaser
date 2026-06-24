"""Channel service: channel registration and management."""

import logging
import datetime
from typing import Optional

from aiogram import Bot
from app.database import Database


class ChannelService:
    def __init__(self, db: Database, bot: Bot):
        self.db = db
        self.bot = bot

    async def add_channel(self, channel_username: str, owner_id: int) -> Optional[int]:
        """Register a channel. Returns channel_id or None on failure."""
        channel_username = channel_username.lstrip("@")
        try:
            chat = await self.bot.get_chat(f"@{channel_username}")
            channel_id = chat.id
        except Exception as e:
            logging.warning(f"Cannot get chat for @{channel_username}: {e}")
            return None

        now = datetime.datetime.now(datetime.timezone.utc)
        async with self.db.acquire() as conn:
            await conn.execute(
                """INSERT INTO channels(channel_id, username, owner_id, is_active, added_at)
                   VALUES ($1, $2, $3, TRUE, $4)
                   ON CONFLICT (channel_id) DO UPDATE
                   SET username=$2, owner_id=$3, is_active=TRUE""",
                channel_id, channel_username, owner_id, now
            )
        return channel_id

    async def get_active_channel(self, owner_id: int) -> Optional[dict]:
        """Get the user's active channel for publishing."""
        async with self.db.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT channel_id, username FROM channels WHERE owner_id=$1 AND is_active=TRUE LIMIT 1",
                owner_id
            )
            return dict(row) if row else None

    async def get_user_channels(self, owner_id: int) -> list[dict]:
        """Get all channels owned by user."""
        async with self.db.acquire() as conn:
            rows = await conn.fetch(
                "SELECT channel_id, username, is_active FROM channels WHERE owner_id=$1 ORDER BY added_at DESC",
                owner_id
            )
            return [dict(r) for r in rows]

    async def set_active_channel(self, owner_id: int, channel_id: int) -> None:
        """Set a specific channel as active (deactivate others)."""
        async with self.db.acquire() as conn:
            await conn.execute(
                "UPDATE channels SET is_active=FALSE WHERE owner_id=$1",
                owner_id
            )
            await conn.execute(
                "UPDATE channels SET is_active=TRUE WHERE owner_id=$1 AND channel_id=$2",
                owner_id, channel_id
            )

    async def verify_bot_is_admin(self, channel_identifier: str) -> tuple[bool, str]:
        """Verify the bot is admin in a channel. Returns (is_admin, error_msg)."""
        try:
            chat_id = channel_identifier if channel_identifier.startswith("-") else f"@{channel_identifier}"
            bot_info = await self.bot.get_me()
            member = await self.bot.get_chat_member(chat_id, bot_info.id)
            if member.status in ("administrator", "creator"):
                return True, ""
            return False, "Бот не является администратором."
        except Exception as e:
            return False, f"Не удалось проверить канал: {e}"

    async def get_channels_with_active_events(self) -> list[dict]:
        """Get channels that have active events (for /top discovery)."""
        query = """
            SELECT DISTINCT e.channel_id, c.username
            FROM events e
            JOIN channels c ON e.channel_id = c.channel_id
            WHERE e.is_active=TRUE AND e.channel_id IS NOT NULL AND e.channel_id != 0
            ORDER BY c.username
        """
        async with self.db.acquire() as conn:
            rows = await conn.fetch(query)
            return [dict(r) for r in rows]

    async def remove_channel(self, owner_id: int, channel_id: int) -> bool:
        """Remove a channel from user's list."""
        async with self.db.acquire() as conn:
            result = await conn.execute(
                "DELETE FROM channels WHERE owner_id=$1 AND channel_id=$2",
                owner_id, channel_id
            )
            return "DELETE 1" in result
