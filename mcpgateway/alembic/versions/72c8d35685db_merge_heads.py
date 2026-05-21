"""merge_heads

Revision ID: 72c8d35685db
Revises: 51d4f5e82d88, e28566875fa4
Create Date: 2026-05-21 16:41:32.845788

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '72c8d35685db'  # pragma: allowlist secret
down_revision: Union[str, Sequence[str], None] = ('51d4f5e82d88', 'e28566875fa4')  # pragma: allowlist secret
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
