"""User service: account management, stats, settings."""

import datetime
from app.database import Database


class UserService:
    def __init__(self, db: Database):
        self.db = db

    async def ensure_user_exists(self, user_id: int) -> None:
        """Create user record if not exists."""
        async with self.db.acquire() as conn:
            row = await conn.fetchrow("SELECT user_id FROM users WHERE user_id=$1", user_id)
            if not row:
                now = datetime.datetime.now(datetime.timezone.utc)
                await conn.execute(
                    "INSERT INTO users(user_id, first_visit) VALUES ($1, $2) ON CONFLICT DO NOTHING",
                    user_id, now
                )

    async def get_user(self, user_id: int) -> dict | None:
        """Get user record by ID."""
        async with self.db.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM users WHERE user_id=$1", user_id)
            return dict(row) if row else None

    async def update_subscription(self, user_id: int, subscribed: bool) -> None:
        """Update user subscription status."""
        await self.ensure_user_exists(user_id)
        async with self.db.acquire() as conn:
            await conn.execute(
                "UPDATE users SET subscription=$1 WHERE user_id=$2",
                subscribed, user_id
            )

    async def increment_participation(self, user_id: int) -> None:
        """Increment user's participated_count."""
        async with self.db.acquire() as conn:
            await conn.execute(
                "UPDATE users SET participated_count = participated_count + 1 WHERE user_id=$1",
                user_id
            )

    async def increment_wins(self, user_id: int) -> None:
        """Increment user's participated_wins."""
        async with self.db.acquire() as conn:
            await conn.execute(
                "UPDATE users SET participated_wins = participated_wins + 1 WHERE user_id=$1",
                user_id
            )

    async def get_user_participation_stats(self, user_id: int, event_type: str) -> tuple[int, int]:
        """Get (total_participations, wins) for a specific event type."""
        query = """
            SELECT
                COUNT(*) as total,
                COUNT(*) FILTER (WHERE ep.winner = true) as wins
            FROM event_participants ep
            JOIN events e ON ep.event_id = e.event_id
            WHERE ep.user_id = $1 AND e.event_type = $2
        """
        async with self.db.acquire() as conn:
            row = await conn.fetchrow(query, user_id, event_type)
            if not row:
                return (0, 0)
            return (row["total"] or 0, row["wins"] or 0)

    async def get_user_language(self, user_id: int) -> str:
        """Get user's language preference."""
        async with self.db.acquire() as conn:
            lang = await conn.fetchval(
                "SELECT language FROM users WHERE user_id=$1", user_id
            )
            return lang or "RU"

    async def set_user_language(self, user_id: int, language: str) -> None:
        """Set user's language preference."""
        await self.ensure_user_exists(user_id)
        async with self.db.acquire() as conn:
            await conn.execute(
                "UPDATE users SET language=$1 WHERE user_id=$2",
                language, user_id
            )

    async def check_user_is_participant(self, user_id: int, event_id: int) -> bool:
        """Check if user participates in an event."""
        async with self.db.acquire() as conn:
            result = await conn.fetchval(
                "SELECT 1 FROM event_participants WHERE user_id=$1 AND event_id=$2",
                user_id, event_id
            )
            return result is not None

    async def get_user_block_status(self, user_id: int) -> bool:
        """Check if user is blocked from FastClick wins."""
        async with self.db.acquire() as conn:
            blocked = await conn.fetchval(
                "SELECT no_repeat_block FROM users WHERE user_id=$1", user_id
            )
            return blocked or False

    async def get_fastclick_settings(self, user_id: int) -> dict:
        """Get user's FastClick personal settings."""
        await self.ensure_user_exists(user_id)
        async with self.db.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT fc_premium_only, fc_no_repeat_winner, fc_intrigue FROM users WHERE user_id=$1",
                user_id
            )
            return dict(row) if row else {"fc_premium_only": False, "fc_no_repeat_winner": False, "fc_intrigue": 0}

    async def toggle_fc_premium(self, user_id: int) -> None:
        """Toggle FastClick premium-only setting."""
        await self.ensure_user_exists(user_id)
        async with self.db.acquire() as conn:
            await conn.execute(
                "UPDATE users SET fc_premium_only = NOT fc_premium_only WHERE user_id=$1",
                user_id
            )

    async def toggle_fc_no_repeat(self, user_id: int) -> None:
        """Toggle FastClick no-repeat-winner setting."""
        await self.ensure_user_exists(user_id)
        async with self.db.acquire() as conn:
            await conn.execute(
                "UPDATE users SET fc_no_repeat_winner = NOT fc_no_repeat_winner WHERE user_id=$1",
                user_id
            )

    async def update_fc_intrigue(self, user_id: int, value: int) -> None:
        """Update FastClick intrigue animation value."""
        await self.ensure_user_exists(user_id)
        async with self.db.acquire() as conn:
            await conn.execute(
                "UPDATE users SET fc_intrigue=$1 WHERE user_id=$2",
                value, user_id
            )

    async def set_fastconnect_email(self, user_id: int, email: str) -> None:
        """Set FastConnect email for account protection."""
        async with self.db.acquire() as conn:
            await conn.execute(
                "UPDATE users SET fastconnect_email=$1 WHERE user_id=$2", email, user_id
            )

    async def set_fastconnect_password(self, user_id: int, password: str) -> None:
        """Set FastConnect password."""
        async with self.db.acquire() as conn:
            await conn.execute(
                "UPDATE users SET fastconnect_password=$1 WHERE user_id=$2", password, user_id
            )

    async def remove_fastconnect_password(self, user_id: int) -> None:
        """Remove FastConnect password."""
        async with self.db.acquire() as conn:
            await conn.execute(
                "UPDATE users SET fastconnect_password=NULL WHERE user_id=$1", user_id
            )

    async def attempt_fastconnect_login(self, new_user_id: int, email: str, password: str) -> bool:
        """Attempt FastConnect login. On success, migrates data from old account."""
        async with self.db.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT user_id FROM users WHERE fastconnect_email=$1 AND fastconnect_password=$2",
                email, password
            )
            if not row:
                return False

            old_user_id = row["user_id"]
            if old_user_id == new_user_id:
                return True

            await self.migrate_user_data(old_user_id, new_user_id)
            return True

    async def migrate_user_data(self, old_user_id: int, new_user_id: int) -> None:
        """Transfer all data from old account to new account in a transaction."""
        await self.ensure_user_exists(new_user_id)

        async with self.db.acquire() as conn:
            async with conn.transaction():
                # Transfer events ownership
                await conn.execute(
                    "UPDATE events SET creator_id=$1 WHERE creator_id=$2",
                    new_user_id, old_user_id
                )
                # Transfer participations
                await conn.execute(
                    "UPDATE event_participants SET user_id=$1 WHERE user_id=$2",
                    new_user_id, old_user_id
                )

                # Merge stats
                old_stats = await conn.fetchrow(
                    "SELECT participated_count, participated_wins FROM users WHERE user_id=$1",
                    old_user_id
                )
                oc = old_stats["participated_count"] if old_stats else 0
                ow = old_stats["participated_wins"] if old_stats else 0

                new_stats = await conn.fetchrow(
                    "SELECT participated_count, participated_wins FROM users WHERE user_id=$1",
                    new_user_id
                )
                nc = new_stats["participated_count"] if new_stats else 0
                nw = new_stats["participated_wins"] if new_stats else 0

                await conn.execute(
                    "UPDATE users SET participated_count=$1, participated_wins=$2 WHERE user_id=$3",
                    oc + nc, ow + nw, new_user_id
                )

                # Clear old account
                await conn.execute(
                    """UPDATE users SET fastconnect_email=NULL, fastconnect_password=NULL,
                       participated_count=0, participated_wins=0, subscription=FALSE
                       WHERE user_id=$1""",
                    old_user_id
                )
