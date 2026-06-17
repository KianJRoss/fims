"""merge needs_data_review and email accounts heads

Revision ID: 69888783a2f3
Revises: j9k0l1m2n3o4, k0e1f2a3b4c5
Create Date: 2026-06-17 21:00:47.117019

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '69888783a2f3'
down_revision: Union[str, None] = ('j9k0l1m2n3o4', 'k0e1f2a3b4c5')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
