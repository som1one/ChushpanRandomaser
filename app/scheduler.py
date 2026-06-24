"""Background task scheduler for automated operations."""

import asyncio
import logging

from aiogram import Bot, types
from aiogram.exceptions import TelegramBadRequest

from app.services.event_service import EventService


class Scheduler:
    def __init__(self, event_service: EventService, bot: Bot):
        self.event_service = event_service
        self.bot = bot
        self._tasks: list[asyncio.Task] = []

    async def start(self) -> None:
        """Start all scheduler loops."""
        self._tasks = [
            asyncio.create_task(self._autobytes_loop()),
            asyncio.create_task(self._time_finish_loop()),
            asyncio.create_task(self._scheduled_publish_loop()),
            asyncio.create_task(self._participant_counter_loop()),
        ]
        logging.info("Scheduler started with %d tasks", len(self._tasks))

    async def stop(self) -> None:
        """Cancel all running tasks."""
        for task in self._tasks:
            task.cancel()
        self._tasks.clear()
        logging.info("Scheduler stopped.")

    async def _autobytes_loop(self) -> None:
        """Every 60s: publish auto-byte messages for eligible events."""
        while True:
            try:
                events = await self.event_service.get_autobyte_events()
                for event in events:
                    await self.event_service.publish_byte_if_needed(event["event_id"])
            except Exception as e:
                logging.error(f"Error in autobytes loop: {e}")
            await asyncio.sleep(60)

    async def _time_finish_loop(self) -> None:
        """Every 60s: finish events whose finish_at time has passed."""
        while True:
            await asyncio.sleep(60)
            try:
                events = await self.event_service.get_events_to_finish_by_time()
                for event in events:
                    logging.info(f"Auto-finishing event {event['event_id']} by time.")
                    await self.event_service.finish_event(event["event_id"])
            except Exception as e:
                logging.error(f"Error in time-finish loop: {e}")

    async def _scheduled_publish_loop(self) -> None:
        """Every 30s: publish events whose scheduled_publish_at has passed."""
        while True:
            await asyncio.sleep(30)
            try:
                events = await self.event_service.get_events_to_publish_by_schedule()
                for event in events:
                    logging.info(f"Publishing scheduled event {event['event_id']}.")
                    await self.event_service.publish_event_now(event["event_id"])
            except Exception as e:
                logging.error(f"Error in scheduled-publish loop: {e}")

    async def _participant_counter_loop(self) -> None:
        """Every 600s: update button text with participant count."""
        while True:
            await asyncio.sleep(600)
            try:
                events = await self.event_service.get_active_events_for_counter_update()
                for event in events:
                    try:
                        event_id = event["event_id"]
                        count = await self.event_service.get_participant_count(event_id)
                        button_text = event["participation_button_text"]
                        new_text = f"{button_text} ({count})"

                        cb_data = f"join_event:{event_id}"
                        if event["event_type"] == "fastclick":
                            cb_data = f"fast_join:{event_id}"

                        markup = types.InlineKeyboardMarkup(inline_keyboard=[
                            [types.InlineKeyboardButton(text=new_text, callback_data=cb_data)]
                        ])
                        await self.bot.edit_message_reply_markup(
                            chat_id=event["post_chat_id"],
                            message_id=event["post_message_id"],
                            reply_markup=markup,
                        )
                    except TelegramBadRequest as e:
                        if "message is not modified" not in str(e):
                            logging.warning(f"Counter update failed for event {event['event_id']}: {e}")
                    except Exception as e:
                        logging.error(f"Counter update error for event {event['event_id']}: {e}")
            except Exception as e:
                logging.error(f"Error in counter-update loop: {e}")
