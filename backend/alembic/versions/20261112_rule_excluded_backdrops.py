"""add excluded backdrops to automation rules

Revision ID: 20261112_rule_excluded_backdrops
Revises: 20261110_attribute_photos
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20261112_rule_excluded_backdrops"
down_revision: str | None = "20261110_attribute_photos"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("automation_rules")}
    if "excluded_backdrops" not in columns:
        op.add_column(
            "automation_rules",
            sa.Column("excluded_backdrops", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("automation_rules")}
    if "excluded_backdrops" in columns:
        op.drop_column("automation_rules", "excluded_backdrops")
