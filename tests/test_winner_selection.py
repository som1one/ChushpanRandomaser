"""Property-based tests for the winner selection algorithm using hypothesis.

Tests verify the core invariants of select_winners_pure():
1. Winner count never exceeds max_winners
2. No duplicate winners in results
3. Guaranteed winners are always included (when count <= max_winners)
4. Empty participant list returns empty
"""

import pytest
from hypothesis import given, strategies as st, settings, assume

from app.services.rig_service import select_winners_pure


# --- Hypothesis Strategies ---

def participant_strategy(
    user_id_st=st.integers(min_value=1, max_value=10000),
    guaranteed_st=st.booleans(),
    chance_bonus_st=st.integers(min_value=0, max_value=5),
    referral_count_st=st.integers(min_value=0, max_value=5),
):
    """Strategy generating a single participant dict."""
    return st.fixed_dictionaries({
        "user_id": user_id_st,
        "guaranteed_winner": guaranteed_st,
        "chance_bonus": chance_bonus_st,
        "referral_count": referral_count_st,
    })


def unique_participants_strategy(min_size=1, max_size=50):
    """Strategy generating a list of participants with unique user_ids."""
    return st.lists(
        st.integers(min_value=1, max_value=100000),
        min_size=min_size,
        max_size=max_size,
        unique=True,
    ).flatmap(lambda ids: st.tuples(
        st.just(ids),
        st.lists(st.booleans(), min_size=len(ids), max_size=len(ids)),
        st.lists(st.integers(min_value=0, max_value=5), min_size=len(ids), max_size=len(ids)),
        st.lists(st.integers(min_value=0, max_value=5), min_size=len(ids), max_size=len(ids)),
    )).map(lambda t: [
        {
            "user_id": uid,
            "guaranteed_winner": gw,
            "chance_bonus": cb,
            "referral_count": rc,
        }
        for uid, gw, cb, rc in zip(t[0], t[1], t[2], t[3])
    ])


# --- Property Tests ---


class TestWinnerCountNeverExceedsMax:
    """**Validates: Requirements 4.2, 4.3**"""

    @given(
        participants=unique_participants_strategy(min_size=1, max_size=50),
        max_winners=st.integers(min_value=1, max_value=100),
    )
    @settings(max_examples=200)
    def test_winner_count_at_most_max_winners(self, participants, max_winners):
        """Property 2: len(result) == min(max_winners, len(participants))"""
        result = select_winners_pure(participants, max_winners)
        expected_count = min(max_winners, len(participants))
        assert len(result) == expected_count

    @given(
        max_winners=st.integers(min_value=1, max_value=100),
    )
    @settings(max_examples=50)
    def test_winner_count_never_exceeds_max_with_few_participants(self, max_winners):
        """When participants < max_winners, result has all participants."""
        participants = [
            {"user_id": i, "guaranteed_winner": False, "chance_bonus": 0, "referral_count": 0}
            for i in range(1, 4)  # Only 3 participants
        ]
        result = select_winners_pure(participants, max_winners)
        assert len(result) <= max_winners
        assert len(result) == min(max_winners, len(participants))


class TestNoDuplicateWinners:
    """**Validates: Requirements 4.4**"""

    @given(
        participants=unique_participants_strategy(min_size=1, max_size=50),
        max_winners=st.integers(min_value=1, max_value=100),
    )
    @settings(max_examples=200)
    def test_no_duplicate_user_ids_in_results(self, participants, max_winners):
        """Property 3: All user_ids in result are unique."""
        result = select_winners_pure(participants, max_winners)
        assert len(result) == len(set(result))

    @given(
        participants=unique_participants_strategy(min_size=1, max_size=50),
        max_winners=st.integers(min_value=1, max_value=100),
        event_type=st.sampled_from(["default", "referral"]),
    )
    @settings(max_examples=200)
    def test_no_duplicates_with_referral_weights(self, participants, max_winners, event_type):
        """No duplicates even when weighted pool has repeated entries."""
        result = select_winners_pure(participants, max_winners, event_type=event_type)
        assert len(result) == len(set(result))


class TestGuaranteedWinnersAlwaysIncluded:
    """**Validates: Requirements 4.1**"""

    @given(
        participants=unique_participants_strategy(min_size=1, max_size=50),
        max_winners=st.integers(min_value=1, max_value=100),
    )
    @settings(max_examples=200)
    def test_guaranteed_winners_always_in_result(self, participants, max_winners):
        """Property 1: When len(guaranteed) <= max_winners, all guaranteed are in result."""
        guaranteed_ids = {p["user_id"] for p in participants if p["guaranteed_winner"]}

        # Only assert when guaranteed count doesn't exceed max_winners
        assume(len(guaranteed_ids) <= max_winners)

        result = select_winners_pure(participants, max_winners)
        for gid in guaranteed_ids:
            assert gid in result, (
                f"Guaranteed winner {gid} not in result {result}"
            )

    @given(
        num_guaranteed=st.integers(min_value=1, max_value=10),
        num_regular=st.integers(min_value=0, max_value=20),
        max_winners=st.integers(min_value=1, max_value=30),
    )
    @settings(max_examples=200)
    def test_guaranteed_win_with_explicit_counts(self, num_guaranteed, num_regular, max_winners):
        """Explicit construction: guaranteed players always win if count <= max_winners."""
        assume(num_guaranteed <= max_winners)

        participants = []
        for i in range(num_guaranteed):
            participants.append({
                "user_id": i + 1,
                "guaranteed_winner": True,
                "chance_bonus": 0,
                "referral_count": 0,
            })
        for i in range(num_regular):
            participants.append({
                "user_id": num_guaranteed + i + 1,
                "guaranteed_winner": False,
                "chance_bonus": 0,
                "referral_count": 0,
            })

        result = select_winners_pure(participants, max_winners)
        guaranteed_ids = set(range(1, num_guaranteed + 1))
        assert guaranteed_ids.issubset(set(result))


class TestEmptyParticipantsReturnsEmpty:
    """**Validates: Requirements 4.8**"""

    @given(
        max_winners=st.integers(min_value=1, max_value=100),
    )
    @settings(max_examples=50)
    def test_empty_participants_returns_empty(self, max_winners):
        """Property: Empty participant list always returns empty result."""
        result = select_winners_pure([], max_winners)
        assert result == []

    def test_empty_participants_deterministic(self):
        """Trivial case: no participants means no winners."""
        assert select_winners_pure([], 5) == []
        assert select_winners_pure([], 1) == []
        assert select_winners_pure([], 100) == []


class TestWinnersAreSubsetOfParticipants:
    """**Validates: Requirements 4.5**"""

    @given(
        participants=unique_participants_strategy(min_size=1, max_size=50),
        max_winners=st.integers(min_value=1, max_value=100),
        event_type=st.sampled_from(["default", "referral"]),
    )
    @settings(max_examples=200)
    def test_winners_subset_of_participants(self, participants, max_winners, event_type):
        """Property 4: Every winner must be from the participants list."""
        participant_ids = {p["user_id"] for p in participants}
        result = select_winners_pure(participants, max_winners, event_type=event_type)
        for winner_id in result:
            assert winner_id in participant_ids, (
                f"Winner {winner_id} not in participant set {participant_ids}"
            )
