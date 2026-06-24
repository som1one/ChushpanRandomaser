"""Middleware to auto-register users on first interaction."""

from typing import Any, Awaitable, Callable, Dict

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Message, CallbackQuery

from app.services.user_service import UserService


class UserRegistrationMiddleware(BaseMiddleware):
    """Ensures user exists in DB for every incoming message/callback."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        user_service: UserService = data.get("user_service")
        if user_service:
            user = None
            if isinstance(event, Message) and event.from_user:
                user = event.from_user
            elif isinstance(event, CallbackQuery) and event.from_user:
                user = event.from_user

            if user:
                await user_service.ensure_user_exists(user.id)

        return await handler(event, data)
