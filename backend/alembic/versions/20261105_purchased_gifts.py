"""track gifts purchased through offers

Revision ID: 20261105_purchased_gifts
Revises: 20261104_smart_trader_percent
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20261105_purchased_gifts"
down_revision = "20261104_smart_trader_percent"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "purchased_gifts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("offer_id", sa.Uuid(), nullable=False),
        sa.Column("collection_id", sa.String(length=64), nullable=False),
        sa.Column("gift_id", sa.String(length=128), nullable=True),
        sa.Column("purchase_key", sa.String(length=128), nullable=False),
        sa.Column("amount", sa.Numeric(38, 12), nullable=False),
        sa.Column("purchased_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("raw", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["offer_id"], ["managed_offers.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("offer_id", "purchase_key", name="uq_purchased_gift_event"),
    )
    op.create_index("ix_purchased_gifts_user_purchased_at", "purchased_gifts", ["user_id", "purchased_at"])
    op.create_index("ix_purchased_gifts_user_id", "purchased_gifts", ["user_id"])
    op.create_index("ix_purchased_gifts_offer_id", "purchased_gifts", ["offer_id"])
    op.create_index("ix_purchased_gifts_collection_id", "purchased_gifts", ["collection_id"])


def downgrade() -> None:
    op.drop_table("purchased_gifts")
