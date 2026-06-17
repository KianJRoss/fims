"""add image_path to products

Revision ID: i8c3d4e5f6a8
Revises: h7b2c3d4e5f7
Create Date: 2026-06-16 12:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "i8c3d4e5f6a8"
down_revision: Union[str, None] = "h7b2c3d4e5f7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE products ADD COLUMN IF NOT EXISTS image_path VARCHAR(512);")


def downgrade() -> None:
    op.execute("ALTER TABLE products DROP COLUMN IF EXISTS image_path;")
