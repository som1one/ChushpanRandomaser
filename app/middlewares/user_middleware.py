"""Middleware to auto-register users on first interaction."""

from typing import Any, Awaitable, Callable, Dict

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Update

from app.services.user_service import UserService


class UserRegistrationMiddleware(BaseMiddleware):
    """Ensures user exists in DB for every incoming update."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        user_service: UserService = data.get("user_service")
        if user_service and isinstance(event, Update):
            user = None
            if event.message and event.message.from_user:
                user = event.message.from_user
            elif event.callback_query and event.callback_query.from_user:
                user = event.callback_query.from_user

            if user:
                await user_service.ensure_user_exists(user.id)

        return await handler(event, data)
