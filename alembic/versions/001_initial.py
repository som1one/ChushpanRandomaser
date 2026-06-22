"""Initial migration - all tables

Revision ID: 001
Revises:
Create Date: 2024-01-01

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '001'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # bot_user
    op.create_table(
        'bot_user',
        sa.Column('user_id', sa.String(), primary_key=True),
        sa.Column('user_name', sa.String(), nullable=True),
        sa.Column('language', sa.String(), nullable=True),
    )

    # draw_progress
    op.create_table(
        'draw_progress',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('user_id', sa.String(), nullable=True),
        sa.Column('chanel_id', sa.String(), nullable=True),
        sa.Column('chanel_name', sa.String(), nullable=True),
        sa.Column('text', sa.String(), nullable=True),
        sa.Column('file_type', sa.String(), nullable=True),
        sa.Column('file_id', sa.String(), nullable=True),
        sa.Column('winers_count', sa.Integer(), nullable=True),
        sa.Column('post_time', sa.String(), nullable=True),
        sa.Column('end_time', sa.String(), nullable=True),
    )

    # notposted
    op.create_table(
        'notposted',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('user_id', sa.String(), nullable=True),
        sa.Column('chanel_id', sa.String(), nullable=True),
        sa.Column('chanel_name', sa.String(), nullable=True),
        sa.Column('text', sa.String(), nullable=True),
        sa.Column('file_type', sa.String(), nullable=True),
        sa.Column('file_id', sa.String(), nullable=True),
        sa.Column('winers_count', sa.Integer(), nullable=True),
        sa.Column('post_time', sa.String(), nullable=True),
        sa.Column('end_time', sa.String(), nullable=True),
    )

    # draw_ (active draws)
    op.create_table(
        'draw_',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('user_id', sa.String(), nullable=True),
        sa.Column('message_id', sa.String(), nullable=True),
        sa.Column('chanel_id', sa.String(), nullable=True),
        sa.Column('chanel_name', sa.String(), nullable=True),
        sa.Column('text', sa.String(), nullable=True),
        sa.Column('file_type', sa.String(), nullable=True),
        sa.Column('file_id', sa.String(), nullable=True),
        sa.Column('winers_count', sa.Integer(), nullable=True),
        sa.Column('post_time', sa.String(), nullable=True),
        sa.Column('end_time', sa.String(), nullable=True),
    )

    # channel (subscribe check)
    op.create_table(
        'channel',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('draw_id', sa.Integer(), nullable=True),
        sa.Column('user_id', sa.String(), nullable=True),
        sa.Column('channel_id', sa.String(), nullable=True),
    )

    # players
    op.create_table(
        'players',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('draw_id', sa.Integer(), nullable=True),
        sa.Column('user_id', sa.String(), nullable=True),
        sa.Column('user_name', sa.String(), nullable=True),
        sa.Column('is_rigged', sa.Boolean(), nullable=False, server_default='false'),
    )

    # admins
    op.create_table(
        'admins',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('user_id', sa.String(), nullable=False, unique=True),
        sa.Column('user_name', sa.String(), nullable=True),
        sa.Column('added_by', sa.String(), nullable=True),
    )

    # user_state
    op.create_table(
        'user_state',
        sa.Column('user_id', sa.Integer(), primary_key=True),
        sa.Column('state', sa.String(), nullable=True),
        sa.Column('arg', sa.String(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table('user_state')
    op.drop_table('admins')
    op.drop_table('players')
    op.drop_table('channel')
    op.drop_table('draw_')
    op.drop_table('notposted')
    op.drop_table('draw_progress')
    op.drop_table('bot_user')
