"""Tests for FastClick atomic winner selection under simulated concurrency."""

import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.handlers.fastclick import on_fast_join_click


def _make_callback(event_id: int, user_id: int = 999, is_premium: bool = False):
    """Create a mock CallbackQuery for fast_join:{event_id}."""
    callback = AsyncMock()
    callback.data = f"fast_join:{event_id}"
    callback.from_user = MagicMock()
    callback.from_user.id = user_id
    callback.from_user.full_name = "Test User"
    callback.from_user.is_premium = is_premium
    callback.message = AsyncMock()
    callback.bot = AsyncMock()
    return callback


def _make_event_row(
    event_id: int = 1,
    is_active: bool = True,
    premium_only: bool = False,
    no_repeat_winner: bool = False,
):
    """Create a mock event row dict (simulates asyncpg Record)."""
    return {
        "event_id": event_id,
        "event_type": "fastclick",
        "is_active": is_active,
        "premium_only": premium_only,
        "no_repeat_winner": no_repeat_winner,
        "title": "Test FastClick",
        "description": "Test description",
        "post_chat_id": -1001234,
        "post_message_id": 100,
        "participation_button_text": "Участвовать!",
    }


def _setup_transaction_mock(conn):
    """Configure conn.transaction() to return an async context manager.

    asyncpg's conn.transaction() is a regular (non-async) call that returns
    an object supporting `async with`. We mock it with a MagicMock that
    returns an object with __aenter__/__aexit__.
    """
    mock_tx_ctx = MagicMock()
    mock_tx_ctx.__aenter__ = AsyncMock(return_value=None)
    mock_tx_ctx.__aexit__ = AsyncMock(return_value=None)
    conn.transaction = MagicMock(return_value=mock_tx_ctx)
    return mock_tx_ctx


@pytest.mark.asyncio
async def test_fast_join_rejects_when_event_inactive(mock_db):
    """fast_join handler checks event is active before proceeding."""
    callback = _make_callback(event_id=1, user_id=500)

    # Setup event_service mock
    event_service = AsyncMock()
    event_service.get_sponsors = AsyncMock(return_value=[])
    # Pre-check returns inactive event
    event_service.get_event = AsyncMock(
        return_value=_make_event_row(is_active=False)
    )
    event_service.db = mock_db

    user_service = AsyncMock()

    await on_fast_join_click(callback, event_service, user_service)

    # Should answer with "already finished" alert
    callback.answer.assert_called_once()
    call_kwargs = callback.answer.call_args
    assert "завершён" in str(call_kwargs)
    # Should NOT attempt to acquire a DB connection for the transaction
    mock_db.acquire.assert_not_called()


@pytest.mark.asyncio
async def test_fast_join_records_exactly_one_winner(mock_db):
    """fast_join records exactly one winner via INSERT within the transaction."""
    callback = _make_callback(event_id=1, user_id=777)

    event_service = AsyncMock()
    event_service.get_sponsors = AsyncMock(return_value=[])
    event_service.get_event = AsyncMock(
        return_value=_make_event_row(is_active=True)
    )
    event_service.db = mock_db

    user_service = AsyncMock()

    conn = mock_db._mock_conn
    _setup_transaction_mock(conn)

    # SELECT FOR UPDATE returns active event
    conn.fetchrow.return_value = _make_event_row(is_active=True)

    await on_fast_join_click(callback, event_service, user_service)

    # Verify that INSERT for winner was called exactly once
    insert_calls = [
        call for call in conn.execute.call_args_list
        if "INSERT INTO event_participants" in str(call)
    ]
    assert len(insert_calls) == 1
    # Verify it was marked as winner=TRUE
    assert "TRUE" in str(insert_calls[0])

    # Verify the user was congratulated
    callback.answer.assert_called()
    congrats_call = callback.answer.call_args
    assert "победител" in str(congrats_call).lower()


@pytest.mark.asyncio
async def test_fast_join_deactivates_event_after_winner_recorded(mock_db):
    """fast_join deactivates the event after the winner is recorded."""
    callback = _make_callback(event_id=5, user_id=888)

    event_service = AsyncMock()
    event_service.get_sponsors = AsyncMock(return_value=[])
    event_service.get_event = AsyncMock(
        return_value=_make_event_row(event_id=5, is_active=True)
    )
    event_service.db = mock_db

    user_service = AsyncMock()

    conn = mock_db._mock_conn
    _setup_transaction_mock(conn)

    # SELECT FOR UPDATE returns active event
    conn.fetchrow.return_value = _make_event_row(event_id=5, is_active=True)

    await on_fast_join_click(callback, event_service, user_service)

    # Verify that UPDATE events SET is_active=FALSE was called
    deactivate_calls = [
        call for call in conn.execute.call_args_list
        if "is_active=FALSE" in str(call)
    ]
    assert len(deactivate_calls) == 1
    # Verify the correct event_id was deactivated
    assert 5 in deactivate_calls[0][0]


@pytest.mark.asyncio
async def test_fast_join_no_repeat_winner_blocks_previous_winner(mock_db):
    """fast_join blocks user who already won when no_repeat_winner is enabled."""
    callback = _make_callback(event_id=2, user_id=666)

    event_service = AsyncMock()
    event_service.get_sponsors = AsyncMock(return_value=[])
    event_service.get_event = AsyncMock(
        return_value=_make_event_row(event_id=2, is_active=True, no_repeat_winner=True)
    )
    event_service.db = mock_db

    user_service = AsyncMock()

    conn = mock_db._mock_conn
    _setup_transaction_mock(conn)

    # SELECT FOR UPDATE returns event with no_repeat_winner enabled
    conn.fetchrow.return_value = _make_event_row(
        event_id=2, is_active=True, no_repeat_winner=True
    )
    # User has no_repeat_block=True (already won before)
    conn.fetchval.return_value = True

    await on_fast_join_click(callback, event_service, user_service)

    # Should answer with "already won" alert
    callback.answer.assert_called()
    block_call = callback.answer.call_args
    assert "выигрывали" in str(block_call) or "повторная" in str(block_call)

    # INSERT should NOT have been called — winner blocked
    insert_calls = [
        call for call in conn.execute.call_args_list
        if "INSERT INTO event_participants" in str(call)
    ]
    assert len(insert_calls) == 0
