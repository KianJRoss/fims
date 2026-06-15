"""seed price types

Revision ID: 1a2b3c4d5e6f
Revises: 0f1e2d3c4b5a
Create Date: 2026-06-15 09:05:00.000000
"""
from typing import Sequence, Union

from alembic import op


revision: str = "1a2b3c4d5e6f"
down_revision: Union[str, None] = "0f1e2d3c4b5a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        INSERT INTO price_types (name, code, requires_auth, sort_order) VALUES
            ('Retail', 'RETAIL', FALSE, 1),
            ('Sale', 'SALE', FALSE, 2),
            ('Wholesale', 'WHOLESALE', TRUE, 3),
            ('Cost', 'COST', TRUE, 4),
            ('Employee', 'EMPLOYEE', TRUE, 5),
            ('Clearance', 'CLEARANCE', FALSE, 6)
        ON CONFLICT DO NOTHING;
        """
    )


def downgrade() -> None:
    op.execute("DELETE FROM price_types WHERE code IN ('RETAIL', 'SALE', 'WHOLESALE', 'COST', 'EMPLOYEE', 'CLEARANCE');")
