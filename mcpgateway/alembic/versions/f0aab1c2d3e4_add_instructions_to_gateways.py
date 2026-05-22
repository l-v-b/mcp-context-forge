# -*- coding: utf-8 -*-
"""Add `instructions` column to gateways table.

Stores the upstream MCP server's `instructions` field (returned during the
client-side `initialize` call) so virtual servers can surface it to their
own downstream clients. Nullable; existing rows stay valid without a
backfill.

Revision ID: f0aab1c2d3e4
Revises: w7x8y9z0a1b2
Create Date: 2026-05-22 12:00:00.000000
"""

# Standard
from typing import Sequence, Union

# Third-Party
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "f0aab1c2d3e4"
down_revision: Union[str, Sequence[str], None] = "w7x8y9z0a1b2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not inspector.has_table("gateways"):
        print("Fresh database detected. Skipping add-instructions migration.")
        return

    columns = [col["name"] for col in inspector.get_columns("gateways")]
    if "instructions" not in columns:
        op.add_column("gateways", sa.Column("instructions", sa.Text(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if inspector.has_table("gateways"):
        columns = [col["name"] for col in inspector.get_columns("gateways")]
        if "instructions" in columns:
            op.drop_column("gateways", "instructions")
