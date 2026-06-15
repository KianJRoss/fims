"""add receipt fields to sales

Revision ID: 0f1e2d3c4b5a
Revises: f6a1b2c3d4e5
Create Date: 2026-06-15 09:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0f1e2d3c4b5a"
down_revision: Union[str, None] = "f6a1b2c3d4e5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto;")
    op.execute("""
        ALTER TABLE sales
            ADD COLUMN IF NOT EXISTS receipt_token VARCHAR(36) DEFAULT gen_random_uuid()::text NOT NULL,
            ADD COLUMN IF NOT EXISTS payment_method VARCHAR(30),
            ADD COLUMN IF NOT EXISTS card_last4 VARCHAR(4),
            ADD COLUMN IF NOT EXISTS receipt_html TEXT;
    """)
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS ix_sales_receipt_token ON sales (receipt_token);
    """)


def downgrade() -> None:
    op.drop_index("ix_sales_receipt_token", table_name="sales")
    op.drop_column("sales", "receipt_html")
    op.drop_column("sales", "card_last4")
    op.drop_column("sales", "payment_method")
    op.drop_column("sales", "receipt_token")
