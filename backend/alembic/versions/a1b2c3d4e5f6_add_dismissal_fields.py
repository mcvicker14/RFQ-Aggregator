"""add dismissal fields to intelligence_items and project_clusters

Revision ID: a1b2c3d4e5f6
Revises: c2a9f1e6d4b7
Create Date: 2026-10-01 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = 'c2a9f1e6d4b7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    for table in ("intelligence_items", "project_clusters"):
        op.add_column(table, sa.Column("is_dismissed", sa.Boolean(), nullable=False, server_default=sa.false()))
        op.add_column(table, sa.Column("dismissed_at", sa.DateTime(timezone=True), nullable=True))
        op.add_column(table, sa.Column("dismissed_by_user_id", sa.UUID(), nullable=True))
        op.add_column(table, sa.Column("dismissal_reason", sa.String(length=30), nullable=True))
        # CASCADE matches fk_uuid()'s default and every other "who did this" FK to
        # users.id already in this schema (confirmed_by_user_id, triggered_by_user_id,
        # created_by_id, ...) -- not something specific to this migration.
        op.create_foreign_key(
            f"fk_{table}_dismissed_by_user_id_users", table, "users",
            ["dismissed_by_user_id"], ["id"], ondelete="CASCADE",
        )
        op.create_index(f"ix_{table}_is_dismissed", table, ["is_dismissed"])
    op.alter_column("intelligence_items", "is_dismissed", server_default=None)
    op.alter_column("project_clusters", "is_dismissed", server_default=None)


def downgrade() -> None:
    for table in ("intelligence_items", "project_clusters"):
        op.drop_index(f"ix_{table}_is_dismissed", table_name=table)
        op.drop_constraint(f"fk_{table}_dismissed_by_user_id_users", table, type_="foreignkey")
        op.drop_column(table, "dismissal_reason")
        op.drop_column(table, "dismissed_by_user_id")
        op.drop_column(table, "dismissed_at")
        op.drop_column(table, "is_dismissed")
