"""Rigging service: guaranteed winner management and winner selection."""

import math
import random
from dataclasses import dataclass
from typing import Optional

from app.database import Database


def select_winners_pure(
    participants: list[dict],
    max_winners: int,
    event_type: str = "default",
) -> list[int]:
    """Pure function implementing the winner selection algorithm.

    This is the core logic extracted for testability.

    Args:
        participants: List of dicts with keys: user_id, guaranteed_winner, chance_bonus, referral_count
        max_winners: Maximum number of winners to select
        event_type: Event type ('referral' adds referral_count to weight)

    Returns:
        List of winner user_ids (shuffled to mask guaranteed winners).
    """
    if not participants or max_winners <= 0:
        return []

    # Step 1: Collect guaranteed winners
    guaranteed = [p for p in participants if p.get("guaranteed_winner")]
    winners: list[dict] = []
    winner_ids: set[int] = set()

    for p in guaranteed:
        if len(winners) >= max_winners:
            break
        winners.append(p)
        winner_ids.add(p["user_id"])

    # Step 2: Build weighted pool from remaining
    remaining_slots = max_winners - len(winners)
    if remaining_slots > 0:
        pool = [p for p in participants if p["user_id"] not in winner_ids]
        weighted_pool: list[dict] = []

        for p in pool:
            weight = 1 + (p.get("chance_bonus") or 0)
            if event_type == "referral":
                weight += (p.get("referral_count") or 0)
            weighted_pool.extend([p] * weight)

        # Step 3: Weighted random selection without replacement
        random.shuffle(weighted_pool)
        for p in weighted_pool:
            if len(winners) >= max_winners:
                break
            if p["user_id"] not in winner_ids:
                winners.append(p)
                winner_ids.add(p["user_id"])

    # Step 4: Shuffle to mask guaranteed winners
    random.shuffle(winners)

    return [w["user_id"] for w in winners]


@dataclass
class RigResult:
    """Result of a rigging operation."""
    success: bool
    message: str
    error_code: Optional[str] = None  # "not_found", "not_admin", "already_rigged", "limit_exceeded"


class RigService:
    def __init__(self, db: Database, admin_ids: list[int]):
        self.db = db
        self.admin_ids = admin_ids

    async def can_manage_event(self, event_id: int, admin_id: int) -> bool:
        """Check if admin_id can manage (rig) the given event.

        Access rules: super-admin (in admin_ids list), DB-stored admin, or event creator.
        """
        # Check if admin is in the config admin list
        if admin_id in self.admin_ids:
            return True

        async with self.db.acquire() as conn:
            # Check if admin exists in DB admins table
            db_admin = await conn.fetchval(
                "SELECT 1 FROM admins WHERE user_id=$1", admin_id
            )
            if db_admin:
                return True

            # Check if admin is the event creator
            creator_id = await conn.fetchval(
                "SELECT creator_id FROM events WHERE event_id=$1", event_id
            )
            return creator_id == admin_id

    async def get_participants_page(
        self, event_id: int, page: int = 0, page_size: int = 8
    ) -> tuple[list[dict], int]:
        """Get a page of participants for the rig panel.

        Returns (participants_on_page, total_pages).
        Each participant dict has: user_id, username, guaranteed_winner, chance_bonus.
        """
        async with self.db.acquire() as conn:
            total = await conn.fetchval(
                "SELECT COUNT(*) FROM event_participants WHERE event_id=$1",
                event_id
            )
            total_pages = max(1, math.ceil(total / page_size))

            offset = page * page_size
            rows = await conn.fetch(
                """SELECT ep.user_id, u.username, ep.guaranteed_winner, ep.chance_bonus
                   FROM event_participants ep
                   LEFT JOIN users u ON ep.user_id = u.user_id
                   WHERE ep.event_id=$1
                   ORDER BY ep.id ASC
                   LIMIT $2 OFFSET $3""",
                event_id, page_size, offset
            )
            participants = [
                {
                    "user_id": row["user_id"],
                    "username": row["username"],
                    "guaranteed_winner": row["guaranteed_winner"],
                    "chance_bonus": row["chance_bonus"],
                }
                for row in rows
            ]
            return participants, total_pages

    async def select_winners(self, event_id: int) -> list[int]:
        """Select winners with guaranteed-winner priority.

        Algorithm:
        1. Collect guaranteed winners (up to max_winners)
        2. Build weighted pool from remaining: base weight 1 + chance_bonus + referral_count (for referral events)
        3. Weighted random selection without replacement for remaining slots
        4. Shuffle all winners to mask guaranteed ones
        """
        async with self.db.acquire() as conn:
            event = await conn.fetchrow(
                "SELECT max_winners, event_type FROM events WHERE event_id=$1", event_id
            )
            if not event:
                return []

            max_winners = event["max_winners"] or 1
            event_type = event["event_type"]

            all_participants = await conn.fetch(
                """SELECT user_id, guaranteed_winner, chance_bonus, referral_count
                   FROM event_participants WHERE event_id=$1""",
                event_id
            )

        if not all_participants:
            return []

        return select_winners_pure(
            [dict(p) for p in all_participants], max_winners, event_type
        )

    async def set_chance_bonus(self, event_id: int, user_id: int, bonus: int) -> bool:
        """Set chance_bonus for a participant. Returns True if participant exists."""
        async with self.db.acquire() as conn:
            result = await conn.execute(
                "UPDATE event_participants SET chance_bonus=$1 WHERE event_id=$2 AND user_id=$3",
                bonus, event_id, user_id
            )
            return "UPDATE 1" in result

    async def get_guaranteed_players(self, event_id: int) -> list[dict]:
        """Get all guaranteed winners for an event."""
        async with self.db.acquire() as conn:
            rows = await conn.fetch(
                """SELECT ep.user_id, u.username
                   FROM event_participants ep
                   LEFT JOIN users u ON ep.user_id = u.user_id
                   WHERE ep.event_id=$1 AND ep.guaranteed_winner=TRUE
                   ORDER BY ep.id ASC""",
                event_id
            )
            return [{"user_id": r["user_id"], "username": r["username"]} for r in rows]

    async def toggle_guaranteed(self, event_id: int, user_id: int, admin_id: int) -> RigResult:
        """Toggle guaranteed_winner status for a participant.

        - Checks admin permissions via can_manage_event()
        - Checks participant exists
        - If currently guaranteed: removes flag
        - If not guaranteed: checks count < max_winners before setting
        """
        if not await self.can_manage_event(event_id, admin_id):
            return RigResult(success=False, message="Нет прав", error_code="not_admin")

        async with self.db.acquire() as conn:
            # Get participant
            participant = await conn.fetchrow(
                "SELECT user_id, guaranteed_winner FROM event_participants WHERE event_id=$1 AND user_id=$2",
                event_id, user_id
            )
            if participant is None:
                return RigResult(success=False, message="Участник не найден", error_code="not_found")

            if participant["guaranteed_winner"]:
                # Unset guaranteed
                await conn.execute(
                    "UPDATE event_participants SET guaranteed_winner=FALSE WHERE event_id=$1 AND user_id=$2",
                    event_id, user_id
                )
                return RigResult(success=True, message="Подкрутка снята")
            else:
                # Check limit
                event = await conn.fetchrow(
                    "SELECT max_winners FROM events WHERE event_id=$1", event_id
                )
                if not event:
                    return RigResult(success=False, message="Событие не найдено", error_code="not_found")

                current_guaranteed = await conn.fetchval(
                    "SELECT COUNT(*) FROM event_participants WHERE event_id=$1 AND guaranteed_winner=TRUE",
                    event_id
                )
                if current_guaranteed >= event["max_winners"]:
                    return RigResult(
                        success=False,
                        message=f"Лимит подкрутки ({event['max_winners']}) исчерпан",
                        error_code="limit_exceeded"
                    )

                await conn.execute(
                    "UPDATE event_participants SET guaranteed_winner=TRUE WHERE event_id=$1 AND user_id=$2",
                    event_id, user_id
                )
                return RigResult(success=True, message="Участник добавлен в подкрутку")