"""add percentage smart trader settings

Revision ID: 20261104_smart_trader_percent
Revises: 20261104_smart_trader
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20261104_smart_trader_percent"
down_revision = "20261104_smart_trader"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "automation_rules",
        sa.Column(
            "trader_min_spread_percent",
            sa.Numeric(precision=9, scale=4),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "automation_rules",
        sa.Column("smart_trader_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("automation_rules", "smart_trader_enabled")
    op.drop_column("automation_rules", "trader_min_spread_percent")
