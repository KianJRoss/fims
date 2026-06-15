"""add_catalog_page

Revision ID: f6a1b2c3d4e5
Revises: e5f6a1b2c3d4
Create Date: 2026-06-15 00:00:00.000000
"""
from typing import Sequence, Union
from alembic import op

revision: str = "f6a1b2c3d4e5"
down_revision: Union[str, None] = "e5f6a1b2c3d4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE products ADD COLUMN IF NOT EXISTS catalog_page INTEGER;")
    op.execute("CREATE INDEX IF NOT EXISTS ix_products_catalog_page ON products (catalog_page);")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_products_catalog_page;")
    op.execute("ALTER TABLE products DROP COLUMN IF EXISTS catalog_page;")
