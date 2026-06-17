"""add email accounts

Revision ID: k0e1f2a3b4c5
Revises: j9d4e5f6a7b9
Create Date: 2026-06-17 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "k0e1f2a3b4c5"
down_revision: Union[str, None] = "j9d4e5f6a7b9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "email_accounts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("host", sa.String(length=255), nullable=False),
        sa.Column("port", sa.Integer(), nullable=False, server_default="993"),
        sa.Column("email_address", sa.String(length=255), nullable=False),
        sa.Column("encrypted_password", sa.String(length=512), nullable=False),
        sa.Column("boss_email_filter", sa.String(length=255), nullable=True),
        sa.Column(
            "keyword_filter",
            sa.String(length=500),
            nullable=False,
            server_default="invoice,order,price list,catalog,fireworks,shipment",
        ),
        sa.Column("last_synced_at", sa.DateTime(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("NOW()")),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_email_accounts_is_active", "email_accounts", ["is_active"], unique=False)
    op.add_column("store_documents", sa.Column("source", sa.String(length=60), nullable=True))


def downgrade() -> None:
    op.drop_column("store_documents", "source")
    op.drop_index("ix_email_accounts_is_active", table_name="email_accounts")
    op.drop_table("email_accounts")
