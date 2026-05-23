"""merge instructions head with main

Revision ID: 97ffbae5e0d7
Revises: e28566875fa4, f0aab1c2d3e4
Create Date: 2026-05-23 11:53:22.727771

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '97ffbae5e0d7'
down_revision: Union[str, Sequence[str], None] = ('e28566875fa4', 'f0aab1c2d3e4')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
