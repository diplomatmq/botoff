"""raise the rebid step of existing rules to 0.01

Revision ID: 20261115_rebid_step_default
Revises: 20261114_user_settings_backfill
"""
from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal

from alembic import op
import sqlalchemy as sa


revision: str = "20261115_rebid_step_default"
down_revision: str | None = "20261114_user_settings_backfill"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD_DEFAULT = Decimal("0.00001")
NEW_DEFAULT = Decimal("0.01")


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "automation_rules" not in inspector.get_table_names():
        return

    meta = sa.MetaData()
    rules = sa.Table("automation_rules", meta, autoload_with=bind)
    bind.execute(
        rules.update()
        .where(rules.c.min_step <= OLD_DEFAULT)
        .values(min_step=NEW_DEFAULT)
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "automation_rules" not in inspector.get_table_names():
        return

    meta = sa.MetaData()
    rules = sa.Table("automation_rules", meta, autoload_with=bind)
    bind.execute(
        rules.update()
        .where(rules.c.min_step == NEW_DEFAULT)
        .values(min_step=OLD_DEFAULT)
    )
