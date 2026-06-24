"""Unit tests for RigService: select_winners and toggle_guaranteed."""

import pytest
from unittest.mock import AsyncMock, MagicMock

from app.services.rig_service import RigService, RigResult


@pytest.mark.asyncio
async def test_select_winners_no_participants(rig_service, mock_db):
    """select_winners with no participants returns []."""
    conn = mock_db._mock_conn

    # Event exists with max_winners=3
    conn.fetchrow.return_value = {"max_winners": 3, "event_type": "contest"}
    # No participants
    conn.fetch.return_value = []

    result = await rig_service.select_winners(event_id=1)
    assert result == []


@pytest.mark.asyncio
async def test_select_winners_includes_guaranteed(rig_service, mock_db):
    """select_winners with guaranteed players includes them in winners."""
    conn = mock_db._mock_conn

    conn.fetchrow.return_value = {"max_winners": 3, "event_type": "contest"}
    conn.fetch.return_value = [
        {"user_id": 10, "guaranteed_winner": True, "chance_bonus": 0, "referral_count": 0},
        {"user_id": 20, "guaranteed_winner": False, "chance_bonus": 0, "referral_count": 0},
        {"user_id": 30, "guaranteed_winner": False, "chance_bonus": 0, "referral_count": 0},
        {"user_id": 40, "guaranteed_winner": True, "chance_bonus": 0, "referral_count": 0},
    ]

    result = await rig_service.select_winners(event_id=1)

    # Both guaranteed players must be in the result
    assert 10 in result
    assert 40 in result
    # Total winners should be min(max_winners, total_participants) = 3
    assert len(result) == 3


@pytest.mark.asyncio
async def test_select_winners_respects_max_winners(rig_service, mock_db):
    """select_winners respects max_winners limit."""
    conn = mock_db._mock_conn

    conn.fetchrow.return_value = {"max_winners": 2, "event_type": "contest"}
    conn.fetch.return_value = [
        {"user_id": 10, "guaranteed_winner": False, "chance_bonus": 0, "referral_count": 0},
        {"user_id": 20, "guaranteed_winner": False, "chance_bonus": 0, "referral_count": 0},
        {"user_id": 30, "guaranteed_winner": False, "chance_bonus": 0, "referral_count": 0},
        {"user_id": 40, "guaranteed_winner": False, "chance_bonus": 0, "referral_count": 0},
        {"user_id": 50, "guaranteed_winner": False, "chance_bonus": 0, "referral_count": 0},
    ]

    result = await rig_service.select_winners(event_id=1)

    assert len(result) == 2
    # All winners must come from participants
    for uid in result:
        assert uid in [10, 20, 30, 40, 50]


@pytest.mark.asyncio
async def test_toggle_guaranteed_non_admin_returns_error(rig_service, mock_db):
    """toggle_guaranteed with non-admin returns error with code 'not_admin'."""
    conn = mock_db._mock_conn

    # Non-admin: not in admin_ids list, not in DB admins, not the event creator
    conn.fetchval.side_effect = [None, 999]  # db_admin=None, creator_id=999

    result = await rig_service.toggle_guaranteed(event_id=1, user_id=10, admin_id=777)

    assert result.success is False
    assert result.error_code == "not_admin"


@pytest.mark.asyncio
async def test_toggle_guaranteed_valid_admin_sets_guaranteed(rig_service, mock_db):
    """toggle_guaranteed with valid admin sets guaranteed_winner for participant."""
    conn = mock_db._mock_conn

    # Admin is in config admin_ids (111 from fixture)
    # Participant exists and is NOT currently guaranteed
    conn.fetchrow.side_effect = [
        {"user_id": 10, "guaranteed_winner": False},  # participant lookup
        {"max_winners": 3},  # event lookup for limit check
    ]
    # current_guaranteed count = 0
    conn.fetchval.return_value = 0
    conn.execute.return_value = "UPDATE 1"

    result = await rig_service.toggle_guaranteed(event_id=1, user_id=10, admin_id=111)

    assert result.success is True
    assert "подкрутку" in result.message.lower() or "добавлен" in result.message.lower()


@pytest.mark.asyncio
async def test_toggle_guaranteed_at_limit_returns_limit_exceeded(rig_service, mock_db):
    """toggle_guaranteed at limit returns limit_exceeded error."""
    conn = mock_db._mock_conn

    # Admin is in config admin_ids (111)
    # Participant exists and is NOT guaranteed
    conn.fetchrow.side_effect = [
        {"user_id": 10, "guaranteed_winner": False},  # participant lookup
        {"max_winners": 2},  # event with max_winners=2
    ]
    # current guaranteed count already equals max_winners
    conn.fetchval.return_value = 2
    conn.execute.return_value = "UPDATE 1"

    result = await rig_service.toggle_guaranteed(event_id=1, user_id=10, admin_id=111)

    assert result.success is False
    assert result.error_code == "limit_exceeded"
