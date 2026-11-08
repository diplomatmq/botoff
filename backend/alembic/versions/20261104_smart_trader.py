"""add smart trader spread and cached maximum offers

Revision ID: 20261104_smart_trader
Revises: 20261103_orphan_managed_offers
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20261104_smart_trader"
down_revision = "20261103_orphan_managed_offers"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("automation_rules", sa.Column("trader_min_spread_percent", sa.Numeric(precision=9, scale=4), nullable=False, server_default="0"))
    op.add_column("automation_rules", sa.Column("smart_trader_enabled", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("collections_cache", sa.Column("max_offer", sa.Numeric(precision=18, scale=8), nullable=True))
    op.add_column("models_cache", sa.Column("max_offer", sa.Numeric(precision=18, scale=8), nullable=True))


def downgrade() -> None:
    op.drop_column("models_cache", "max_offer")
    op.drop_column("collections_cache", "max_offer")
    op.drop_column("automation_rules", "trader_min_spread")
