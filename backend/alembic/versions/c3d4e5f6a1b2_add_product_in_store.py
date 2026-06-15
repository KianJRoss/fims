"""add_product_in_store

Revision ID: c3d4e5f6a1b2
Revises: b2c3d4e5f6a1
Create Date: 2026-06-15 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op


revision: str = "c3d4e5f6a1b2"
down_revision: Union[str, None] = "b2c3d4e5f6a1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE products ADD COLUMN IF NOT EXISTS in_store BOOLEAN NOT NULL DEFAULT FALSE;")


def downgrade() -> None:
    op.execute("ALTER TABLE products DROP COLUMN IF EXISTS in_store;")
