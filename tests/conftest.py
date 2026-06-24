"""Test fixtures for the unified giveaway bot."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from app.config import DatabaseConfig, BotConfig
from app.database import Database
from app.services.user_service import UserService
from app.services.rig_service import RigService, RigResult
from app.services.event_service import EventService


@pytest.fixture
def mock_db():
    """Mock database with a mock pool and acquire context manager."""
    db = MagicMock(spec=Database)
    mock_conn = AsyncMock()
    mock_pool_ctx = AsyncMock()
    mock_pool_ctx.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_pool_ctx.__aexit__ = AsyncMock(return_value=None)
    db.acquire.return_value = mock_pool_ctx
    db._mock_conn = mock_conn  # expose for assertions
    return db


@pytest.fixture
def mock_bot():
    """Mock aiogram Bot."""
    bot = AsyncMock()
    bot.get_me = AsyncMock(return_value=MagicMock(id=123456, username="test_bot"))
    bot.get_chat = AsyncMock(return_value=MagicMock(id=1, full_name="Test User", username="testuser"))
    return bot


@pytest.fixture
def config():
    """Test bot config."""
    return BotConfig(
        token="test_token",
        db=DatabaseConfig(host="localhost", port=5432, user="test", password="test", database="test_db"),
        admin_ids=[111, 222],
        use_cache=False,
        cache_ttl=60,
    )


@pytest.fixture
def user_service(mock_db):
    return UserService(mock_db)


@pytest.fixture
def rig_service(mock_db, config):
    return RigService(mock_db, config.admin_ids)


@pytest.fixture
def event_service(mock_db, mock_bot, rig_service):
    return EventService(mock_db, mock_bot, rig_service)
