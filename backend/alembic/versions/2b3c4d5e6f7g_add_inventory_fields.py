"""add_inventory_fields

Revision ID: 2b3c4d5e6f7g
Revises: 1a2b3c4d5e6f
Create Date: 2026-06-15 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "2b3c4d5e6f7g"
down_revision: Union[str, None] = "1a2b3c4d5e6f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto;")
    op.execute("ALTER TABLE products ADD COLUMN IF NOT EXISTS in_store BOOLEAN NOT NULL DEFAULT FALSE;")
    op.add_column("product_videos", sa.Column("video_filename", sa.String(length=255), nullable=True))
    op.add_column(
        "product_videos",
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.execute(
        """
        UPDATE product_videos
        SET video_filename = COALESCE(video_filename, original_filename, file_path)
        WHERE video_filename IS NULL;
        """
    )
    op.alter_column("product_videos", "video_filename", nullable=False)
    op.create_unique_constraint(
        "uq_product_videos_product_id_video_filename",
        "product_videos",
        ["product_id", "video_filename"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_product_videos_product_id_video_filename", "product_videos", type_="unique")
    op.drop_column("product_videos", "created_at")
    op.drop_column("product_videos", "video_filename")
    op.execute("ALTER TABLE products DROP COLUMN IF EXISTS in_store;")
