"""Middleware to inject services into handler kwargs."""

from typing import Any, Awaitable, Callable, Dict

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject


class ServiceMiddleware(BaseMiddleware):
    """Injects service instances into handler kwargs."""

    def __init__(
        self,
        user_service,
        event_service,
        rig_service,
        channel_service,
        notification_service,
        cache=None,
        config=None,
    ):
        self.user_service = user_service
        self.event_service = event_service
        self.rig_service = rig_service
        self.channel_service = channel_service
        self.notification_service = notification_service
        self.cache = cache
        self.config = config

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        data["user_service"] = self.user_service
        data["event_service"] = self.event_service
        data["rig_service"] = self.rig_service
        data["channel_service"] = self.channel_service
        data["notification_service"] = self.notification_service
        data["cache"] = self.cache
        data["config"] = self.config
        return await handler(event, data)
