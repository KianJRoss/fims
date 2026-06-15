"""add_video_url_fields

Revision ID: 6f8d3b2a9c11
Revises: 971c32055cad
Create Date: 2026-06-15 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "6f8d3b2a9c11"
down_revision: Union[str, None] = "971c32055cad"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "product_videos",
        sa.Column("source", sa.String(length=20), nullable=False, server_default=sa.text("'LOCAL'")),
    )
    op.add_column("product_videos", sa.Column("url", sa.String(length=1024), nullable=True))
    op.add_column("product_videos", sa.Column("youtube_id", sa.String(length=128), nullable=True))
    op.create_index(op.f("ix_product_videos_youtube_id"), "product_videos", ["youtube_id"], unique=False)
    op.add_column("product_videos", sa.Column("title", sa.String(length=255), nullable=True))
    op.add_column("product_videos", sa.Column("thumbnail_url", sa.String(length=1024), nullable=True))
    op.add_column("product_videos", sa.Column("search_query", sa.String(length=512), nullable=True))
    op.add_column(
        "product_videos",
        sa.Column("confirmed", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )


def downgrade() -> None:
    op.drop_column("product_videos", "confirmed")
    op.drop_column("product_videos", "search_query")
    op.drop_column("product_videos", "thumbnail_url")
    op.drop_column("product_videos", "title")
    op.drop_index(op.f("ix_product_videos_youtube_id"), table_name="product_videos")
    op.drop_column("product_videos", "youtube_id")
    op.drop_column("product_videos", "url")
    op.drop_column("product_videos", "source")
