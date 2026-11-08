"""keep managed offers after rule deletion

Revision ID: 20261103_orphan_managed_offers
Revises: 90ceb832e405
"""
from __future__ import annotations

from alembic import op

revision = "20261103_orphan_managed_offers"
down_revision = "90ceb832e405"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("managed_offers") as batch:
        batch.alter_column("rule_id", nullable=True)
        batch.create_foreign_key(
            "fk_managed_offers_rule_id_automation_rules",
            "automation_rules",
            ["rule_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    with op.batch_alter_table("managed_offers") as batch:
        batch.drop_constraint("fk_managed_offers_rule_id_automation_rules", type_="foreignkey")
        batch.alter_column("rule_id", nullable=False)
