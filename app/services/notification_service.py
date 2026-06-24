"""Notification service: winner notifications and broadcasts."""

import asyncio
import logging
from typing import Optional

from aiogram import Bot
from aiogram.exceptions import TelegramForbiddenError, TelegramBadRequest
from app.database import Database


class NotificationService:
    def __init__(self, bot: Bot, db: Database):
        self.bot = bot
        self.db = db

    async def notify_winners(self, event_id: int, winner_ids: list[int], event_title: str) -> None:
        """Send winner notification to each winner via PM."""
        for uid in winner_ids:
            try:
                await self.bot.send_message(
                    chat_id=uid,
                    text=f"🏆 Поздравляем! Вы выиграли в конкурсе <b>{event_title}</b> (ID {event_id})!"
                )
            except TelegramForbiddenError:
                logging.info(f"Cannot notify winner {uid} - bot is blocked")
            except Exception as e:
                logging.warning(f"Failed to notify winner {uid}: {e}")

    async def broadcast(
        self,
        text: str,
        photo_id: Optional[str] = None,
        button_text: Optional[str] = None,
        button_url: Optional[str] = None,
        batch_size: int = 50,
        delay: float = 3.0,
        exclude_subscribed: bool = False,
    ) -> tuple[int, int]:
        """Broadcast message to all users. Returns (sent_count, total_count)."""
        from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

        # Get user list
        query = "SELECT user_id FROM users"
        if exclude_subscribed:
            query += " WHERE subscription = FALSE OR subscription IS NULL"

        async with self.db.acquire() as conn:
            rows = await conn.fetch(query)

        total = len(rows)
        sent = 0

        # Build markup if button provided
        markup = None
        if button_text and button_url:
            markup = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text=button_text, url=button_url)]
            ])

        # Send in batches
        for i in range(0, total, batch_size):
            batch = rows[i:i + batch_size]
            for row in batch:
                user_id = row["user_id"]
                try:
                    if photo_id:
                        await self.bot.send_photo(
                            chat_id=user_id, photo=photo_id,
                            caption=text, reply_markup=markup
                        )
                    else:
                        await self.bot.send_message(
                            chat_id=user_id, text=text, reply_markup=markup
                        )
                    sent += 1
                except TelegramForbiddenError:
                    pass  # User blocked bot
                except TelegramBadRequest:
                    pass  # Chat not found etc
                except Exception as e:
                    logging.warning(f"Broadcast failed for {user_id}: {e}")

            # Delay between batches to avoid rate limits
            if i + batch_size < total:
                await asyncio.sleep(delay)

        return sent, total
