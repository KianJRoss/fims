"""add_legacy_kiosk_videos

Lookup table for the old Red Rhino / PyroSalesman kiosk's barcode->video mapping
(recovered from redrhino.db). Lets the video Remote fall back to the legacy clip
when a scanned barcode isn't a FIMS product (or its FIMS product has no playable
video). Populated by scripts/load_legacy_kiosk_videos.py — this migration only
creates the empty table.

Revision ID: e6f7a8b9c0d1
Revises: d5e6f7a8b9c0
Create Date: 2026-06-27 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "e6f7a8b9c0d1"
down_revision: Union[str, None] = "d5e6f7a8b9c0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "legacy_kiosk_videos",
        # The GTIN exactly as stored in the legacy kiosk DB.
        sa.Column("gtin", sa.Text(), primary_key=True),
        # GTIN with leading zeros stripped, so a UPC-A (12-digit) scan matches an
        # EAN-13 ("0"+UPC) stored value and vice-versa.
        sa.Column("gtin_norm", sa.Text(), nullable=False),
        sa.Column("video_filename", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=True),
    )
    op.create_index(
        "ix_legacy_kiosk_videos_gtin_norm",
        "legacy_kiosk_videos",
        ["gtin_norm"],
    )


def downgrade() -> None:
    op.drop_index("ix_legacy_kiosk_videos_gtin_norm", table_name="legacy_kiosk_videos")
    op.drop_table("legacy_kiosk_videos")
