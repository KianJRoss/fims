"""add product aliases

Revision ID: j9d4e5f6a7b9
Revises: i8c3d4e5f6a8
Create Date: 2026-06-17 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "j9d4e5f6a7b9"
down_revision: Union[str, None] = "i8c3d4e5f6a8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "product_aliases",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("product_id", sa.String(length=36), nullable=False),
        sa.Column("alias_name", sa.String(length=255), nullable=False),
        sa.Column("source", sa.String(length=60), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("product_id", "alias_name", name="uq_product_aliases_product_id_alias_name"),
    )
    op.create_index(
        "ix_product_aliases_alias_name", "product_aliases", ["alias_name"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_product_aliases_alias_name", table_name="product_aliases")
    op.drop_table("product_aliases")
