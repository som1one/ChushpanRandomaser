"""Тесты для модуля app.config."""

import os
from unittest.mock import patch

from app.config import DatabaseConfig, BotConfig, load_config


class TestDatabaseConfig:
    def test_defaults(self):
        cfg = DatabaseConfig(
            host="localhost", port=5432, user="u", password="p", database="db"
        )
        assert cfg.min_pool_size == 5
        assert cfg.max_pool_size == 20

    def test_custom_pool_sizes(self):
        cfg = DatabaseConfig(
            host="h", port=5433, user="u", password="p", database="d",
            min_pool_size=2, max_pool_size=10,
        )
        assert cfg.min_pool_size == 2
        assert cfg.max_pool_size == 10


class TestBotConfig:
    def test_fields(self):
        db = DatabaseConfig(host="h", port=5432, user="u", password="p", database="d")
        cfg = BotConfig(token="tok", db=db, admin_ids=[1, 2], use_cache=True, cache_ttl=60)
        assert cfg.token == "tok"
        assert cfg.admin_ids == [1, 2]
        assert cfg.use_cache is True
        assert cfg.cache_ttl == 60


class TestLoadConfig:
    @patch.dict(os.environ, {
        "BOT_TOKEN": "test_token_123",
        "DB_HOST": "dbhost",
        "DB_PORT": "5433",
        "DB_USER": "myuser",
        "DB_PASSWORD": "mypass",
        "DB_NAME": "mydb",
        "ADMIN_IDS": "111,222,333",
        "USE_CACHE": "false",
        "CACHE_TTL": "120",
    }, clear=False)
    def test_loads_all_env_vars(self):
        cfg = load_config()
        assert cfg.token == "test_token_123"
        assert cfg.db.host == "dbhost"
        assert cfg.db.port == 5433
        assert cfg.db.user == "myuser"
        assert cfg.db.password == "mypass"
        assert cfg.db.database == "mydb"
        assert cfg.admin_ids == [111, 222, 333]
        assert cfg.use_cache is False
        assert cfg.cache_ttl == 120

    @patch.dict(os.environ, {"BOT_TOKEN": "tok", "ADMIN_IDS": ""}, clear=False)
    def test_empty_admin_ids(self):
        cfg = load_config()
        assert cfg.admin_ids == []

    @patch.dict(os.environ, {"BOT_TOKEN": "tok", "USE_CACHE": "1"}, clear=False)
    def test_use_cache_truthy_values(self):
        cfg = load_config()
        assert cfg.use_cache is True

    @patch.dict(os.environ, {"BOT_TOKEN": "tok", "USE_CACHE": "yes"}, clear=False)
    def test_use_cache_yes(self):
        cfg = load_config()
        assert cfg.use_cache is True

    @patch.dict(os.environ, {"BOT_TOKEN": "tok", "USE_CACHE": "no"}, clear=False)
    def test_use_cache_falsy(self):
        cfg = load_config()
        assert cfg.use_cache is False

    @patch.dict(os.environ, {"BOT_TOKEN": "tok", "ADMIN_IDS": " 42 , 99 "}, clear=False)
    def test_admin_ids_with_spaces(self):
        cfg = load_config()
        assert cfg.admin_ids == [42, 99]
