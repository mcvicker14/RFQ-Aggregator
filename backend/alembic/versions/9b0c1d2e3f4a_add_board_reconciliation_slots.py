"""Persist board reconciliation slot completion and retry health."""
from alembic import op
import sqlalchemy as sa

revision = "9b0c1d2e3f4a"
down_revision = "7a8b9c0d1e2f"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("status_board_cache_state", sa.Column("last_reconciliation_attempted_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("status_board_cache_state", sa.Column("last_reconciliation_slot_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("status_board_cache_state", sa.Column("last_reconciliation_error", sa.Text(), nullable=True))


def downgrade():
    for name in ("last_reconciliation_error", "last_reconciliation_slot_at", "last_reconciliation_attempted_at"):
        op.drop_column("status_board_cache_state", name)
