"""add packing and product costing

Revision ID: h7b2c3d4e5f7
Revises: 2b3c4d5e6f7g
Create Date: 2026-06-16 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "h7b2c3d4e5f7"
down_revision: Union[str, None] = "2b3c4d5e6f7g"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE products ADD COLUMN IF NOT EXISTS packing VARCHAR(20);")
    op.create_table(
        "product_costing",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("product_id", sa.String(length=36), nullable=False),
        sa.Column("boxes_per_case", sa.Integer(), nullable=False),
        sa.Column("units_per_box", sa.Integer(), nullable=False),
        sa.Column("case_cost", sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column("markup_multiplier", sa.Numeric(precision=6, scale=4), nullable=False),
        sa.Column("retail_price", sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("product_id", name="uq_product_costing_product_id"),
    )


def downgrade() -> None:
    op.drop_table("product_costing")
    op.execute("ALTER TABLE products DROP COLUMN IF EXISTS packing;")
