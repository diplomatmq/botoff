"""backfill per-user settings from the shared settings

Revision ID: 20261114_user_settings_backfill
Revises: 20261114_user_settings
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20261114_user_settings_backfill"
down_revision: str | None = "20261114_user_settings"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Process-wide keys stay shared and must not be copied per account.
GLOBAL_KEYS = {"throughput"}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "user_settings" not in inspector.get_table_names():
        return

    meta = sa.MetaData()
    users = sa.Table("users", meta, autoload_with=bind)
    app_settings = sa.Table("application_settings", meta, autoload_with=bind)
    user_settings = sa.Table("user_settings", meta, autoload_with=bind)

    shared = {
        row.key: row.value
        for row in bind.execute(sa.select(app_settings.c.key, app_settings.c.value)).all()
        if row.key not in GLOBAL_KEYS
    }
    if not shared:
        return

    user_ids = [row.id for row in bind.execute(sa.select(users.c.id)).all()]
    if not user_ids:
        return

    existing = {
        (row.user_id, row.key)
        for row in bind.execute(sa.select(user_settings.c.user_id, user_settings.c.key)).all()
    }
    for user_id in user_ids:
        for key, value in shared.items():
            if (user_id, key) in existing:
                continue
            bind.execute(user_settings.insert().values(user_id=user_id, key=key, value=value))


def downgrade() -> None:
    # The copy is additive; nothing to undo.
    pass
