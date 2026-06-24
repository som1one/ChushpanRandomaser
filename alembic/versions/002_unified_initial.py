"""Unified bot initial schema - all tables

Revision ID: 002
Revises: 001
Create Date: 2024-01-15

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '002'
down_revision: Union[str, None] = '001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- users ---
    op.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id BIGINT PRIMARY KEY,
            username TEXT,
            language VARCHAR(5) DEFAULT 'RU',
            first_visit TIMESTAMPTZ DEFAULT NOW(),
            subscription BOOLEAN DEFAULT FALSE,
            fastconnect_email TEXT,
            fastconnect_password TEXT,
            participated_count INTEGER DEFAULT 0,
            participated_wins INTEGER DEFAULT 0,
            no_repeat_block BOOLEAN DEFAULT FALSE,
            fc_premium_only BOOLEAN DEFAULT FALSE,
            fc_no_repeat_winner BOOLEAN DEFAULT FALSE,
            fc_intrigue INTEGER DEFAULT 0
        );
    """)

    # --- admins ---
    op.execute("""
        CREATE TABLE IF NOT EXISTS admins (
            id SERIAL PRIMARY KEY,
            user_id BIGINT UNIQUE NOT NULL,
            username TEXT,
            added_by BIGINT,
            created_at TIMESTAMPTZ DEFAULT NOW()
        );
    """)

    # --- channels ---
    op.execute("""
        CREATE TABLE IF NOT EXISTS channels (
            channel_id BIGINT PRIMARY KEY,
            username TEXT NOT NULL UNIQUE,
            owner_id BIGINT NOT NULL,
            is_active BOOLEAN DEFAULT TRUE,
            added_at TIMESTAMPTZ DEFAULT NOW()
        );
    """)

    # --- events ---
    op.execute("""
        CREATE TABLE IF NOT EXISTS events (
            event_id SERIAL PRIMARY KEY,
            creator_id BIGINT NOT NULL,
            channel_id BIGINT DEFAULT 0,
            event_type VARCHAR(20) NOT NULL,
            title TEXT,
            description TEXT,
            media_id TEXT,
            media_type VARCHAR(20),
            max_winners INTEGER DEFAULT 1,
            max_tickets INTEGER,
            winning_ticket_number INTEGER,
            created_at TIMESTAMPTZ DEFAULT NOW(),
            updated_at TIMESTAMPTZ DEFAULT NOW(),
            finish_at TIMESTAMPTZ,
            is_active BOOLEAN DEFAULT FALSE,
            auto_bytes BOOLEAN DEFAULT FALSE,
            byte_interval INTEGER DEFAULT 60,
            last_byte_time TIMESTAMPTZ,
            auto_bytes_notify BOOLEAN DEFAULT FALSE,
            hide_button_after_finish BOOLEAN DEFAULT FALSE,
            show_participants_counter BOOLEAN DEFAULT FALSE,
            participation_button_text TEXT DEFAULT 'Участвовать!',
            button_style VARCHAR(10) DEFAULT 'single',
            post_chat_id BIGINT,
            post_message_id BIGINT,
            premium_only BOOLEAN DEFAULT FALSE,
            no_repeat_winner BOOLEAN DEFAULT FALSE,
            intrigue INTEGER DEFAULT 0,
            required_event_id INTEGER,
            notify_winners BOOLEAN DEFAULT TRUE,
            vote_channel_required BOOLEAN DEFAULT FALSE,
            scheduled_publish_at TIMESTAMPTZ
        );
    """)

    # --- event_participants ---
    op.execute("""
        CREATE TABLE IF NOT EXISTS event_participants (
            id SERIAL PRIMARY KEY,
            event_id INTEGER NOT NULL REFERENCES events(event_id) ON DELETE CASCADE,
            user_id BIGINT NOT NULL,
            ticket_number INTEGER,
            referral_count INTEGER DEFAULT 0,
            joined_at TIMESTAMPTZ DEFAULT NOW(),
            inviter_id BIGINT,
            winner BOOLEAN DEFAULT FALSE,
            chance_bonus INTEGER DEFAULT 0,
            guaranteed_winner BOOLEAN DEFAULT FALSE,
            UNIQUE(event_id, user_id),
            UNIQUE(event_id, ticket_number)
        );
    """)

    # --- sponsors ---
    op.execute("""
        CREATE TABLE IF NOT EXISTS sponsors (
            sponsor_id SERIAL PRIMARY KEY,
            event_id INTEGER NOT NULL REFERENCES events(event_id) ON DELETE CASCADE,
            username TEXT NOT NULL
        );
    """)

    # --- quizzes ---
    op.execute("""
        CREATE TABLE IF NOT EXISTS quizzes (
            quiz_id SERIAL PRIMARY KEY,
            creator_id BIGINT NOT NULL,
            channel_id BIGINT,
            question TEXT NOT NULL,
            allow_vote_change BOOLEAN DEFAULT TRUE,
            max_votes INTEGER,
            created_at TIMESTAMPTZ DEFAULT NOW(),
            is_active BOOLEAN DEFAULT FALSE,
            columns_count INTEGER DEFAULT 2,
            photo_id TEXT,
            post_chat_id BIGINT,
            post_message_id BIGINT
        );
    """)

    # --- quiz_options ---
    op.execute("""
        CREATE TABLE IF NOT EXISTS quiz_options (
            option_id SERIAL PRIMARY KEY,
            quiz_id INTEGER NOT NULL REFERENCES quizzes(quiz_id) ON DELETE CASCADE,
            option_text TEXT NOT NULL,
            votes_count INTEGER DEFAULT 0
        );
    """)

    # --- quiz_answers ---
    op.execute("""
        CREATE TABLE IF NOT EXISTS quiz_answers (
            id SERIAL PRIMARY KEY,
            quiz_id INTEGER NOT NULL REFERENCES quizzes(quiz_id) ON DELETE CASCADE,
            user_id BIGINT NOT NULL,
            chosen_option_id INTEGER REFERENCES quiz_options(option_id),
            answered_at TIMESTAMPTZ DEFAULT NOW(),
            UNIQUE(quiz_id, user_id)
        );
    """)

    # --- ad_templates ---
    op.execute("""
        CREATE TABLE IF NOT EXISTS ad_templates (
            template_id SERIAL PRIMARY KEY,
            text TEXT,
            media_type VARCHAR(20),
            file_id TEXT,
            button_text TEXT,
            button_url TEXT,
            created_at TIMESTAMPTZ DEFAULT NOW()
        );
    """)

    # --- event_bytes ---
    op.execute("""
        CREATE TABLE IF NOT EXISTS event_bytes (
            id SERIAL PRIMARY KEY,
            event_id INTEGER NOT NULL REFERENCES events(event_id) ON DELETE CASCADE,
            chat_id BIGINT NOT NULL,
            message_id BIGINT NOT NULL
        );
    """)

    # --- indexes ---
    op.execute("CREATE INDEX IF NOT EXISTS idx_channels_owner ON channels(owner_id);")
    op.execute("CREATE INDEX IF NOT EXISTS idx_events_creator ON events(creator_id);")
    op.execute("CREATE INDEX IF NOT EXISTS idx_events_active ON events(is_active) WHERE is_active = TRUE;")
    op.execute("CREATE INDEX IF NOT EXISTS idx_events_finish ON events(finish_at) WHERE is_active = TRUE AND finish_at IS NOT NULL;")
    op.execute("CREATE INDEX IF NOT EXISTS idx_events_scheduled ON events(scheduled_publish_at) WHERE scheduled_publish_at IS NOT NULL AND is_active = FALSE;")
    op.execute("CREATE INDEX IF NOT EXISTS idx_participants_event ON event_participants(event_id);")
    op.execute("CREATE INDEX IF NOT EXISTS idx_participants_user ON event_participants(user_id);")
    op.execute("CREATE INDEX IF NOT EXISTS idx_participants_guaranteed ON event_participants(event_id) WHERE guaranteed_winner = TRUE;")
    op.execute("CREATE INDEX IF NOT EXISTS idx_sponsors_event ON sponsors(event_id);")


def downgrade() -> None:
    # Drop indexes first
    op.execute("DROP INDEX IF EXISTS idx_sponsors_event;")
    op.execute("DROP INDEX IF EXISTS idx_participants_guaranteed;")
    op.execute("DROP INDEX IF EXISTS idx_participants_user;")
    op.execute("DROP INDEX IF EXISTS idx_participants_event;")
    op.execute("DROP INDEX IF EXISTS idx_events_scheduled;")
    op.execute("DROP INDEX IF EXISTS idx_events_finish;")
    op.execute("DROP INDEX IF EXISTS idx_events_active;")
    op.execute("DROP INDEX IF EXISTS idx_events_creator;")
    op.execute("DROP INDEX IF EXISTS idx_channels_owner;")

    # Drop tables
    op.execute("DROP TABLE IF EXISTS event_bytes;")
    op.execute("DROP TABLE IF EXISTS ad_templates;")
    op.execute("DROP TABLE IF EXISTS quiz_answers;")
    op.execute("DROP TABLE IF EXISTS quiz_options;")
    op.execute("DROP TABLE IF EXISTS quizzes;")
    op.execute("DROP TABLE IF EXISTS sponsors;")
    op.execute("DROP TABLE IF EXISTS event_participants;")
    op.execute("DROP TABLE IF EXISTS events;")
    op.execute("DROP TABLE IF EXISTS channels;")
    op.execute("DROP TABLE IF EXISTS admins;")
    op.execute("DROP TABLE IF EXISTS users;")
