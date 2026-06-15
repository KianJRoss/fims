"""add_video_download_status

Revision ID: a1b2c3d4e5f6
Revises: 6f8d3b2a9c11
Create Date: 2026-06-15 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, None] = "6f8d3b2a9c11"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "product_videos",
        sa.Column("download_status", sa.String(length=20), server_default="pending", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("product_videos", "download_status")
