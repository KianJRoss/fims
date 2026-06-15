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
    op.add_column(
        "sales",
        sa.Column(
            "receipt_token",
            sa.String(length=36),
            nullable=False,
            server_default=sa.text("gen_random_uuid()::text"),
        ),
    )
    op.add_column("sales", sa.Column("payment_method", sa.String(length=30), nullable=True))
    op.add_column("sales", sa.Column("card_last4", sa.String(length=4), nullable=True))
    op.add_column("sales", sa.Column("receipt_html", sa.Text(), nullable=True))
    op.create_index("ix_sales_receipt_token", "sales", ["receipt_token"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_sales_receipt_token", table_name="sales")
    op.drop_column("sales", "receipt_html")
    op.drop_column("sales", "card_last4")
    op.drop_column("sales", "payment_method")
    op.drop_column("sales", "receipt_token")
