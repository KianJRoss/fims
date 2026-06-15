"""add_no_video_confirmed

Revision ID: d4e5f6a1b2c3
Revises: c3d4e5f6a1b2
Create Date: 2026-06-15 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op


revision: str = "d4e5f6a1b2c3"
down_revision: Union[str, None] = "c3d4e5f6a1b2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE products ADD COLUMN IF NOT EXISTS no_video_confirmed BOOLEAN NOT NULL DEFAULT FALSE;")


def downgrade() -> None:
    op.execute("ALTER TABLE products DROP COLUMN IF EXISTS no_video_confirmed;")
