"""add needs_data_review to products

Revision ID: j9k0l1m2n3o4
Revises: i8c3d4e5f6a8
Create Date: 2026-06-17 16:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "j9k0l1m2n3o4"
down_revision: Union[str, None] = "i8c3d4e5f6a8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE products ADD COLUMN IF NOT EXISTS needs_data_review BOOLEAN NOT NULL DEFAULT FALSE;"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE products DROP COLUMN IF EXISTS needs_data_review;")
