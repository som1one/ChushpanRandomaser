"""Event service: event lifecycle management."""

import asyncpg
import datetime
import logging
from typing import Optional

from aiogram import Bot
from app.database import Database
from app.services.rig_service import RigService


class EventService:
    def __init__(self, db: Database, bot: Bot, rig_service: RigService):
        self.db = db
        self.bot = bot
        self.rig_service = rig_service

    async def create_event(
        self,
        creator_id: int,
        channel_id: int,
        event_type: str,
        title: str,
        description: str,
        media_id: Optional[str] = None,
        media_type: Optional[str] = None,
        max_winners: int = 1,
        max_tickets: Optional[int] = None,
        winning_ticket_number: Optional[int] = None,
        finish_at: Optional[datetime.datetime] = None,
        auto_bytes: bool = False,
        byte_interval: int = 60,
        auto_bytes_notify: bool = False,
        hide_button_after_finish: bool = False,
        show_participants_counter: bool = False,
        participation_button_text: str = "Участвовать!",
        premium_only: bool = False,
        no_repeat_winner: bool = False,
        intrigue: int = 0,
        vote_channel_required: bool = False,
        button_style: str = "single",
        scheduled_publish_at: Optional[datetime.datetime] = None,
    ) -> int:
        """Create a new event and return its ID."""
        now = datetime.datetime.now(datetime.timezone.utc)
        query = """
            INSERT INTO events(
                creator_id, channel_id, event_type, title, description, media_id, media_type,
                max_winners, max_tickets, winning_ticket_number, created_at, updated_at, finish_at,
                auto_bytes, byte_interval, last_byte_time, auto_bytes_notify,
                hide_button_after_finish, show_participants_counter, participation_button_text,
                premium_only, no_repeat_winner, intrigue,
                vote_channel_required, button_style, scheduled_publish_at
            )
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18,$19,$20,$21,$22,$23,$24,$25,$26)
            RETURNING event_id
        """
        async with self.db.acquire() as conn:
            row = await conn.fetchrow(
                query,
                creator_id, channel_id, event_type, title, description, media_id, media_type,
                max_winners, max_tickets, winning_ticket_number, now, now, finish_at,
                auto_bytes, byte_interval, now, auto_bytes_notify,
                hide_button_after_finish, show_participants_counter, participation_button_text,
                premium_only, no_repeat_winner, intrigue,
                vote_channel_required, button_style, scheduled_publish_at
            )
            return row["event_id"]

    async def get_event(self, event_id: int) -> Optional[dict]:
        """Get event by ID."""
        async with self.db.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM events WHERE event_id=$1", event_id)
            return dict(row) if row else None

    async def get_participants(self, event_id: int) -> list[dict]:
        """Get all participants for an event ordered by join time."""
        async with self.db.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM event_participants WHERE event_id=$1 ORDER BY id ASC",
                event_id
            )
            return [dict(r) for r in rows]

    async def get_participant_count(self, event_id: int) -> int:
        """Get number of participants for an event."""
        async with self.db.acquire() as conn:
            count = await conn.fetchval(
                "SELECT COUNT(*) FROM event_participants WHERE event_id=$1", event_id
            )
            return count or 0

    async def get_recent_events_for_top(self, days: int = 3) -> list[dict]:
        """Get recent active events for the /top command."""
        since = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=days)
        async with self.db.acquire() as conn:
            rows = await conn.fetch(
                """SELECT event_id, title, event_type, created_at
                   FROM events WHERE created_at >= $1 AND is_active=TRUE
                   ORDER BY created_at DESC""",
                since
            )
            return [dict(r) for r in rows]

    async def get_user_events(self, creator_id: int) -> list[dict]:
        """Get all events owned by a user."""
        async with self.db.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM events WHERE creator_id=$1 ORDER BY event_id DESC",
                creator_id
            )
            return [dict(r) for r in rows]

    async def get_all_events(self) -> list[dict]:
        """Get all events (for admin panel)."""
        async with self.db.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM events ORDER BY event_id DESC"
            )
            return [dict(r) for r in rows]

    async def _set_inactive(self, event_id: int) -> None:
        """Deactivate an event."""
        now = datetime.datetime.now(datetime.timezone.utc)
        async with self.db.acquire() as conn:
            await conn.execute(
                "UPDATE events SET is_active=FALSE, updated_at=$1 WHERE event_id=$2",
                now, event_id
            )

    async def _store_post_info(self, event_id: int, chat_id: int, message_id: int) -> None:
        """Store channel post information for an event."""
        async with self.db.acquire() as conn:
            await conn.execute(
                "UPDATE events SET post_chat_id=$1, post_message_id=$2, is_active=TRUE WHERE event_id=$3",
                chat_id, message_id, event_id
            )

    async def publish_event_now(self, event_id: int) -> bool:
        """Publish event to channel. Builds markup based on event_type and button_style."""
        from aiogram import types

        event = await self.get_event(event_id)
        if not event or event["is_active"]:
            return False

        # Get creator's active channel
        async with self.db.acquire() as conn:
            row_ch = await conn.fetchrow(
                "SELECT channel_id, username FROM channels WHERE owner_id=$1 AND is_active=TRUE LIMIT 1",
                event["creator_id"]
            )
        if not row_ch:
            return False

        channel_id = row_ch["channel_id"]
        channel_username = row_ch["username"]

        # Build markup
        event_type = event["event_type"]
        button_text = event.get("participation_button_text", "Участвовать!")
        button_style = event.get("button_style", "single")
        reply_markup = None

        if event_type == "lottery":
            # Grid of numbered tickets
            max_tickets = event.get("max_tickets", 25)
            kb_rows = []
            row_buf = []
            for i in range(1, max_tickets + 1):
                row_buf.append(types.InlineKeyboardButton(
                    text=str(i), callback_data=f"join_event:{event_id}:{i}"
                ))
                if len(row_buf) == 5:
                    kb_rows.append(row_buf)
                    row_buf = []
            if row_buf:
                kb_rows.append(row_buf)
            reply_markup = types.InlineKeyboardMarkup(inline_keyboard=kb_rows)

        elif event_type == "fastclick":
            callback_data = f"fast_join:{event_id}"
            reply_markup = types.InlineKeyboardMarkup(inline_keyboard=[
                [types.InlineKeyboardButton(text=button_text, callback_data=callback_data)]
            ])

        elif event_type in ("contest", "referral"):
            callback_data = f"join_event:{event_id}"
            if button_style == "grid":
                grid_buttons = [
                    [types.InlineKeyboardButton(text="🎟️", callback_data=callback_data) for _ in range(5)]
                    for _ in range(5)
                ]
                reply_markup = types.InlineKeyboardMarkup(inline_keyboard=grid_buttons)
            else:
                reply_markup = types.InlineKeyboardMarkup(inline_keyboard=[
                    [types.InlineKeyboardButton(text=button_text, callback_data=callback_data)]
                ])

        # Send to channel
        post_text = event.get("description", "")
        media_id = event.get("media_id")
        media_type = event.get("media_type")

        try:
            if media_id and media_type:
                sender_map = {
                    "photo": self.bot.send_photo,
                    "video": self.bot.send_video,
                    "animation": self.bot.send_animation,
                }
                sender = sender_map.get(media_type)
                if sender:
                    msg_sent = await sender(
                        chat_id=f"@{channel_username}",
                        **{media_type: media_id},
                        caption=post_text,
                        reply_markup=reply_markup
                    )
                else:
                    msg_sent = await self.bot.send_message(
                        chat_id=f"@{channel_username}",
                        text=post_text, reply_markup=reply_markup
                    )
            else:
                msg_sent = await self.bot.send_message(
                    chat_id=f"@{channel_username}",
                    text=post_text, reply_markup=reply_markup
                )
        except Exception as e:
            logging.error(f"Failed to publish event {event_id}: {e}")
            return False

        # Store post info and activate
        await self._store_post_info(event_id, msg_sent.chat.id, msg_sent.message_id)

        # Update channel_id if it was 0
        if event["channel_id"] == 0:
            async with self.db.acquire() as conn:
                await conn.execute(
                    "UPDATE events SET channel_id=$1 WHERE event_id=$2",
                    channel_id, event_id
                )

        return True

    async def restore_event(self, event_id: int) -> bool:
        """Restore a finished event: delete old post, reset, republish."""
        event = await self.get_event(event_id)
        if not event:
            return False

        # Delete old post
        if event.get("post_chat_id") and event.get("post_message_id"):
            try:
                await self.bot.delete_message(
                    chat_id=event["post_chat_id"], message_id=event["post_message_id"]
                )
            except Exception:
                pass

        # Reset post info
        async with self.db.acquire() as conn:
            await conn.execute(
                "UPDATE events SET is_active=FALSE, post_chat_id=NULL, post_message_id=NULL WHERE event_id=$1",
                event_id
            )

        # Republish
        return await self.publish_event_now(event_id)

    async def check_sponsors(self, event_id: int, user_id: int, bot: "Bot") -> list[str]:
        """Check if user is subscribed to all sponsor channels. Returns list of unsubscribed channels."""
        sponsors = await self.get_sponsors(event_id)
        not_subscribed = []

        for sponsor in sponsors:
            try:
                chat_id = sponsor["username"] if sponsor["username"].startswith("-") else f"@{sponsor['username']}"
                member = await bot.get_chat_member(chat_id, user_id)
                if member.status not in ("member", "administrator", "creator"):
                    not_subscribed.append(sponsor["username"])
            except Exception:
                not_subscribed.append(sponsor["username"])

        return not_subscribed

    async def get_sponsors(self, event_id: int) -> list[dict]:
        """Get all sponsors for an event."""
        async with self.db.acquire() as conn:
            rows = await conn.fetch(
                "SELECT sponsor_id, username FROM sponsors WHERE event_id=$1",
                event_id
            )
            return [dict(r) for r in rows]

    async def add_sponsor(self, event_id: int, sponsor_username: str) -> None:
        """Add a sponsor channel to an event."""
        async with self.db.acquire() as conn:
            await conn.execute(
                "INSERT INTO sponsors(event_id, username) VALUES ($1, $2)",
                event_id, sponsor_username
            )

    async def remove_sponsor(self, sponsor_id: int) -> None:
        """Remove a sponsor by ID."""
        async with self.db.acquire() as conn:
            await conn.execute("DELETE FROM sponsors WHERE sponsor_id=$1", sponsor_id)

    async def add_condition(self, event_id: int, required_event_id: int) -> bool:
        """Set a prerequisite event for participation."""
        try:
            async with self.db.acquire() as conn:
                await conn.execute(
                    "UPDATE events SET required_event_id=$1 WHERE event_id=$2",
                    required_event_id, event_id
                )
            return True
        except Exception as e:
            logging.error(f"Error adding condition: {e}")
            return False

    async def finish_event(
        self, event_id: int, instant_winner_id: Optional[int] = None
    ) -> Optional[tuple[list[int], bool]]:
        """Finish an event: deactivate, delete bytes, select winners, notify, edit post.

        Returns (winner_ids, edit_success) or None if event already inactive.
        """
        from app.utils.helpers import hlink

        event = await self.get_event(event_id)
        if not event or not event["is_active"]:
            return None

        # Delete auto-byte messages
        async with self.db.acquire() as conn:
            byte_messages = await conn.fetch(
                "SELECT chat_id, message_id FROM event_bytes WHERE event_id=$1", event_id
            )
            for msg in byte_messages:
                try:
                    await self.bot.delete_message(chat_id=msg["chat_id"], message_id=msg["message_id"])
                except Exception:
                    pass
            await conn.execute("DELETE FROM event_bytes WHERE event_id=$1", event_id)

        # Deactivate
        await self._set_inactive(event_id)

        # Select winners
        winner_ids = []
        if instant_winner_id:
            winner_ids = [instant_winner_id]
            async with self.db.acquire() as conn:
                await conn.execute(
                    "UPDATE event_participants SET winner=TRUE WHERE event_id=$1 AND user_id=$2",
                    event_id, instant_winner_id
                )
        else:
            winner_ids = await self.rig_service.select_winners(event_id)
            if winner_ids:
                async with self.db.acquire() as conn:
                    await conn.execute(
                        "UPDATE event_participants SET winner=TRUE WHERE event_id=$1 AND user_id = ANY($2::bigint[])",
                        event_id, winner_ids
                    )

        # Update winner stats
        for uid in winner_ids:
            async with self.db.acquire() as conn:
                await conn.execute(
                    "UPDATE users SET participated_wins = participated_wins + 1 WHERE user_id=$1",
                    uid
                )

        # Notify winners
        if event.get("notify_winners", True) and winner_ids:
            for uid in winner_ids:
                try:
                    await self.bot.send_message(
                        chat_id=uid,
                        text=f"🏆 Поздравляем! Вы выиграли в конкурсе <b>{event['title']}</b> (ID {event_id})!"
                    )
                except Exception:
                    pass

        # Edit channel post with winners
        edit_success = False
        if event.get("post_chat_id") and event.get("post_message_id"):
            try:
                if winner_ids:
                    winners_text_parts = []
                    for uid in winner_ids:
                        try:
                            user_info = await self.bot.get_chat(uid)
                            winners_text_parts.append(hlink(user_info.full_name, f"tg://user?id={uid}"))
                        except Exception:
                            winners_text_parts.append(f"<a href='tg://user?id={uid}'>Пользователь {uid}</a>")

                    winners_text = "\n".join(winners_text_parts)
                    final_text = f"<b>{event['title']}</b>\n\n{event['description']}\n\n<b>🎉 Победители:</b>\n{winners_text}"
                else:
                    final_text = f"<b>{event['title']}</b>\n\n{event['description']}\n\n<b>Конкурс завершён. Победители не определены.</b>"

                if event.get("media_id"):
                    await self.bot.edit_message_caption(
                        chat_id=event["post_chat_id"],
                        message_id=event["post_message_id"],
                        caption=final_text, reply_markup=None
                    )
                else:
                    await self.bot.edit_message_text(
                        final_text,
                        chat_id=event["post_chat_id"],
                        message_id=event["post_message_id"],
                        reply_markup=None
                    )
                edit_success = True
            except Exception as e:
                logging.warning(f"Could not edit finish message for event {event_id}: {e}")

        return winner_ids, edit_success

    async def add_participant(
        self,
        event_id: int,
        user_id: int,
        ticket_number: Optional[int] = None,
        inviter_id: Optional[int] = None,
    ) -> bool:
        """Add a participant to an event. Returns True on success, False if already participating or ticket taken."""
        async with self.db.acquire() as conn:
            # Check if already participating (for non-lottery events)
            existing = await conn.fetchval(
                "SELECT 1 FROM event_participants WHERE event_id=$1 AND user_id=$2",
                event_id, user_id
            )
            if existing:
                return False

            now = datetime.datetime.now(datetime.timezone.utc)
            try:
                await conn.execute(
                    """INSERT INTO event_participants(event_id, user_id, ticket_number, joined_at, inviter_id)
                       VALUES ($1, $2, $3, $4, $5)""",
                    event_id, user_id, ticket_number, now, inviter_id
                )
            except asyncpg.UniqueViolationError:
                return False

        # Increment inviter's referral count
        if inviter_id:
            async with self.db.acquire() as conn:
                await conn.execute(
                    "UPDATE event_participants SET referral_count = referral_count + 1 WHERE event_id=$1 AND user_id=$2",
                    event_id, inviter_id
                )

        # Increment user participation stats
        async with self.db.acquire() as conn:
            await conn.execute(
                "UPDATE users SET participated_count = participated_count + 1 WHERE user_id=$1",
                user_id
            )

        # Check lottery instant win
        event = await self.get_event(event_id)
        if event and event["event_type"] == "lottery" and ticket_number is not None:
            if ticket_number == event.get("winning_ticket_number"):
                async with self.db.acquire() as conn:
                    await conn.execute(
                        "UPDATE users SET participated_wins = participated_wins + 1 WHERE user_id=$1",
                        user_id
                    )
                await self.finish_event(event_id, instant_winner_id=user_id)

        return True

    async def publish_byte_if_needed(self, event_id: int) -> None:
        """Publish auto-byte engagement message if interval has passed."""
        import random

        event = await self.get_event(event_id)
        if not event or not event["auto_bytes"] or not event["is_active"]:
            return

        channel_id = event["channel_id"]
        if not channel_id or channel_id == 0:
            return

        interval = event.get("byte_interval", 60)
        last_byte_time = event.get("last_byte_time")
        now = datetime.datetime.now(datetime.timezone.utc)

        # Check if enough time has passed
        if last_byte_time:
            if last_byte_time.tzinfo is None:
                last_byte_time = last_byte_time.replace(tzinfo=datetime.timezone.utc)
            if (now - last_byte_time).total_seconds() < interval * 60:
                return

        phrases = [
            "🎁 Следующему участнику в этом конкурсе повышу шансы!",
            "🌞 Следующему участнику точно повезёт!",
            "🎉 Завершаю конкурс?",
            "👀 Все участвуют в конкурсе??",
            "👻 Следующим трём участникам повышу шансы!",
            "💬 Успеем завершить конкурс сегодня?",
            "👊 Жми кнопку!",
            "👾 Ласт клики и завершаю!",
            "❤️ Все ждут твоего участия!",
            "❗ До итогов осталось совсем немного!",
            "🔥 До итогов конкурса осталось совсем немного...",
            "🤯 Так мало человек хотят выиграть???"
        ]

        msg_text = random.choice(phrases)
        auto_bytes_notify = event.get("auto_bytes_notify", False)
        prefix = "🔔" if auto_bytes_notify else "⚠️"

        try:
            sent_msg = await self.bot.send_message(
                channel_id,
                f"{prefix} {msg_text}",
                disable_notification=not auto_bytes_notify
            )
            # Store byte message for cleanup on finish
            async with self.db.acquire() as conn:
                await conn.execute(
                    "INSERT INTO event_bytes(event_id, chat_id, message_id) VALUES ($1, $2, $3)",
                    event_id, sent_msg.chat.id, sent_msg.message_id
                )
        except Exception as e:
            logging.error(f"Failed to send auto-byte for event {event_id}: {e}")

        # Update last_byte_time
        async with self.db.acquire() as conn:
            await conn.execute(
                "UPDATE events SET last_byte_time=$1 WHERE event_id=$2",
                now, event_id
            )

    async def get_autobyte_events(self) -> list[dict]:
        """Get all active events with auto_bytes enabled."""
        async with self.db.acquire() as conn:
            rows = await conn.fetch(
                """SELECT event_id, channel_id, byte_interval, last_byte_time, auto_bytes_notify
                   FROM events WHERE is_active=TRUE AND auto_bytes=TRUE"""
            )
            return [dict(r) for r in rows]

    async def get_events_to_finish_by_time(self) -> list[dict]:
        """Get events that should be finished based on finish_at time."""
        async with self.db.acquire() as conn:
            rows = await conn.fetch(
                "SELECT event_id FROM events WHERE is_active=TRUE AND finish_at IS NOT NULL AND finish_at <= NOW()"
            )
            return [dict(r) for r in rows]

    async def get_active_events_for_counter_update(self) -> list[dict]:
        """Get active events that need participant counter updates."""
        async with self.db.acquire() as conn:
            rows = await conn.fetch(
                """SELECT event_id, post_chat_id, post_message_id, participation_button_text, button_style, event_type
                   FROM events
                   WHERE is_active=TRUE
                     AND event_type IN ('contest', 'referral', 'fastclick')
                     AND button_style = 'single'
                     AND post_chat_id IS NOT NULL
                     AND post_message_id IS NOT NULL"""
            )
            return [dict(r) for r in rows]

    async def get_events_to_publish_by_schedule(self) -> list[dict]:
        """Get events that should be published based on scheduled_publish_at."""
        async with self.db.acquire() as conn:
            rows = await conn.fetch(
                """SELECT event_id FROM events
                   WHERE scheduled_publish_at IS NOT NULL
                     AND scheduled_publish_at <= NOW()
                     AND is_active = FALSE
                     AND post_chat_id IS NULL"""
            )
            return [dict(r) for r in rows]
