"""Конфигурация бота. Загружает переменные окружения из .env файла."""

import os
from dataclasses import dataclass

from dotenv import load_dotenv


@dataclass
class DatabaseConfig:
    """Конфигурация подключения к PostgreSQL."""

    host: str
    port: int
    user: str
    password: str
    database: str
    min_pool_size: int = 5
    max_pool_size: int = 20


@dataclass
class BotConfig:
    """Основная конфигурация бота."""

    token: str
    db: DatabaseConfig
    admin_ids: list[int]
    use_cache: bool
    cache_ttl: int


def load_config() -> BotConfig:
    """Загружает конфигурацию из переменных окружения (.env файл).

    Переменные:
        BOT_TOKEN — токен Telegram бота
        DB_HOST — хост PostgreSQL (по умолчанию localhost)
        DB_PORT — порт PostgreSQL (по умолчанию 5432)
        DB_USER — пользователь БД (по умолчанию postgres)
        DB_PASSWORD — пароль БД (по умолчанию postgres)
        DB_NAME — имя базы данных (по умолчанию giveaway_bot)
        ADMIN_IDS — ID администраторов через запятую
        USE_CACHE — включить TTL-кэш (true/1 для включения)
        CACHE_TTL — время жизни кэша в секундах (по умолчанию 300)
    """
    load_dotenv()

    token = os.getenv("BOT_TOKEN", "")

    db_config = DatabaseConfig(
        host=os.getenv("DB_HOST", "localhost"),
        port=int(os.getenv("DB_PORT", "5432")),
        user=os.getenv("DB_USER", "postgres"),
        password=os.getenv("DB_PASSWORD", "postgres"),
        database=os.getenv("DB_NAME", "giveaway_bot"),
    )

    admin_ids_str = os.getenv("ADMIN_IDS", "")
    if admin_ids_str.strip():
        admin_ids = [int(x.strip()) for x in admin_ids_str.split(",") if x.strip()]
    else:
        admin_ids = []

    use_cache_str = os.getenv("USE_CACHE", "true").lower()
    use_cache = use_cache_str in ("true", "1", "yes")

    cache_ttl = int(os.getenv("CACHE_TTL", "300"))

    return BotConfig(
        token=token,
        db=db_config,
        admin_ids=admin_ids,
        use_cache=use_cache,
        cache_ttl=cache_ttl,
    )
