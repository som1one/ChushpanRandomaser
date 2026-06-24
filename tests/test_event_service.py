"""Unit tests for EventService.add_participant and finish_event."""

import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.asyncio
async def test_add_participant_returns_false_if_user_already_exists(event_service, mock_db):
    """add_participant returns False when user is already participating."""
    conn = mock_db._mock_conn
    # Simulate existing participant found
    conn.fetchval.return_value = 1

    result = await event_service.add_participant(event_id=1, user_id=100)

    assert result is False
    conn.fetchval.assert_called_once_with(
        "SELECT 1 FROM event_participants WHERE event_id=$1 AND user_id=$2",
        1, 100
    )
    # INSERT should never be called
    conn.execute.assert_not_called()


@pytest.mark.asyncio
async def test_add_participant_inserts_successfully_for_new_user(event_service, mock_db):
    """add_participant inserts a new participant and returns True."""
    conn = mock_db._mock_conn
    # No existing participant
    conn.fetchval.return_value = None
    conn.execute.return_value = None
    # get_event called for lottery check — return non-lottery event
    conn.fetchrow.return_value = {
        "event_id": 1,
        "event_type": "contest",
        "winning_ticket_number": None,
        "is_active": True,
    }

    result = await event_service.add_participant(event_id=1, user_id=200)

    assert result is True
    # Should have called INSERT for participant
    insert_calls = [
        call for call in conn.execute.call_args_list
        if "INSERT INTO event_participants" in str(call)
    ]
    assert len(insert_calls) >= 1

    # Should have incremented user stats
    stats_calls = [
        call for call in conn.execute.call_args_list
        if "participated_count" in str(call)
    ]
    assert len(stats_calls) >= 1


@pytest.mark.asyncio
async def test_add_participant_increments_referral_count_when_inviter_provided(event_service, mock_db):
    """add_participant increments the inviter's referral_count when inviter_id is given."""
    conn = mock_db._mock_conn
    # No existing participant
    conn.fetchval.return_value = None
    conn.execute.return_value = None
    # get_event returns non-lottery event
    conn.fetchrow.return_value = {
        "event_id": 1,
        "event_type": "referral",
        "winning_ticket_number": None,
        "is_active": True,
    }

    result = await event_service.add_participant(
        event_id=1, user_id=300, inviter_id=400
    )

    assert result is True
    # Check that referral_count update was called for the inviter
    referral_calls = [
        call for call in conn.execute.call_args_list
        if "referral_count" in str(call)
    ]
    assert len(referral_calls) >= 1
    # Verify inviter_id is in the args
    referral_call = referral_calls[0]
    assert 400 in referral_call[0] or (
        len(referral_call) > 1 and 400 in referral_call[1].values()
    ) or 400 in (referral_call[0] if isinstance(referral_call[0], tuple) else referral_call[0])


@pytest.mark.asyncio
async def test_finish_event_returns_none_if_event_inactive(event_service, mock_db):
    """finish_event returns None when event is not active."""
    conn = mock_db._mock_conn
    # get_event returns inactive event
    conn.fetchrow.return_value = {
        "event_id": 1,
        "event_type": "contest",
        "is_active": False,
        "title": "Test",
        "description": "Test desc",
        "post_chat_id": None,
        "post_message_id": None,
        "notify_winners": True,
        "media_id": None,
    }

    result = await event_service.finish_event(event_id=1)

    assert result is None


@pytest.mark.asyncio
async def test_finish_event_deactivates_event_and_selects_winners(event_service, mock_db, mock_bot):
    """finish_event deactivates the event and selects winners via rig_service."""
    conn = mock_db._mock_conn

    # get_event returns active event
    conn.fetchrow.return_value = {
        "event_id": 1,
        "event_type": "contest",
        "is_active": True,
        "title": "Test Contest",
        "description": "A test contest",
        "post_chat_id": -1001234,
        "post_message_id": 555,
        "notify_winners": True,
        "media_id": None,
        "auto_bytes": False,
    }
    # fetch for byte_messages returns empty
    conn.fetch.return_value = []
    conn.execute.return_value = None

    # Mock rig_service.select_winners to return winner ids
    event_service.rig_service.select_winners = AsyncMock(return_value=[100, 200])

    # Mock bot methods
    mock_bot.get_chat.return_value = MagicMock(full_name="Winner User")
    mock_bot.send_message.return_value = None
    mock_bot.edit_message_text.return_value = None

    result = await event_service.finish_event(event_id=1)

    assert result is not None
    winner_ids, edit_success = result
    assert winner_ids == [100, 200]

    # Verify event was deactivated (UPDATE is_active=FALSE call)
    deactivate_calls = [
        call for call in conn.execute.call_args_list
        if "is_active=FALSE" in str(call)
    ]
    assert len(deactivate_calls) >= 1

    # Verify rig_service.select_winners was called
    event_service.rig_service.select_winners.assert_called_once_with(1)

    # Verify winners were notified
    assert mock_bot.send_message.call_count >= 2
