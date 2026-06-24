"""Main entry point for the Unified Giveaway Bot."""

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.bot import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand

from app.config import load_config
from app.database import Database
from app.services.user_service import UserService
from app.services.rig_service import RigService
from app.services.event_service import EventService
from app.services.channel_service import ChannelService
from app.services.notification_service import NotificationService
from app.middlewares.db_middleware import ServiceMiddleware
from app.middlewares.user_middleware import UserRegistrationMiddleware
from app.utils.cache import SimpleCache

logging.basicConfig(level=logging.INFO)


async def set_bot_commands(bot: Bot) -> None:
    """Register bot commands visible in Telegram menu."""
    commands = [
        BotCommand(command="start", description="🏠 Главное меню"),
        BotCommand(command="cancel", description="❌ Отменить действие"),
        BotCommand(command="account", description="👤 Аккаунт"),
        BotCommand(command="lot", description="🎟️ Создать конкурс/лотерею"),
        BotCommand(command="fast", description="⚡ Создать ФастКлик"),
        BotCommand(command="quiz", description="📝 Создать опрос"),
        BotCommand(command="post", description="📰 Создать пост"),
        BotCommand(command="list", description="📋 Управление событиями"),
        BotCommand(command="settings", description="⚙️ Настройка ФастКлика"),
        BotCommand(command="channel", description="🔄 Смена канала"),
        BotCommand(command="rig", description="⚙️ Управление (подкрутка)"),
        BotCommand(command="top", description="🏆 Активные события"),
        BotCommand(command="admin", description="👑 Админ-панель"),
    ]
    await bot.set_my_commands(commands)


async def main() -> None:
    """Async entry point: load config, init bot, connect DB, wire services, start polling."""
    config = load_config()

    bot = Bot(
        token=config.token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    storage = MemoryStorage()
    dp = Dispatcher(storage=storage)

    # Database
    db = Database()
    await db.connect(config.db)

    # Cache
    cache = SimpleCache(ttl=config.cache_ttl) if config.use_cache else None

    # Services
    user_service = UserService(db)
    rig_service = RigService(db, config.admin_ids)
    event_service = EventService(db, bot, rig_service)
    channel_service = ChannelService(db, bot)
    notification_service = NotificationService(bot, db)

    # Register middleware
    service_mw = ServiceMiddleware(
        user_service=user_service,
        event_service=event_service,
        rig_service=rig_service,
        channel_service=channel_service,
        notification_service=notification_service,
        cache=cache,
        config=config,
    )
    dp.update.outer_middleware(service_mw)
    dp.update.outer_middleware(UserRegistrationMiddleware())

    # Bot commands
    await set_bot_commands(bot)

    # Register routers
    from app.handlers.start import start_router
    from app.handlers.lot_main import lot_main_router
    from app.handlers.lot_lottery import lot_lottery_router
    from app.handlers.rig import rig_router
    from app.handlers.top import top_router
    from app.handlers.post import post_router
    from app.handlers.quiz import quiz_router
    dp.include_router(start_router)
    dp.include_router(lot_main_router)
    dp.include_router(lot_lottery_router)
    dp.include_router(rig_router)
    dp.include_router(top_router)
    dp.include_router(post_router)
    dp.include_router(quiz_router)

    logging.info("Bot starting...")
    try:
        await dp.start_polling(bot)
    finally:
        await db.close()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
