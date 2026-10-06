"""Source identities and durable human Submit edits; no opportunity changes."""
from alembic import op
import sqlalchemy as sa

revision = "7a8b9c0d1e2f"
down_revision = "f3c7b2a9d1e4"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("status_board_rows", sa.Column("source_record_id", sa.String(36)))
    op.add_column("status_board_rows", sa.Column("source_revision", sa.String(64)))
    op.create_table("status_board_edits",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("request_id", sa.String(36), nullable=False, unique=True),
        sa.Column("actor_id", sa.UUID(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("source_record_id", sa.String(36), nullable=False),
        sa.Column("expected_revision", sa.String(64), nullable=False),
        sa.Column("old_value", sa.String(10), nullable=False),
        sa.Column("new_value", sa.String(1), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("result_revision", sa.String(64)))


def downgrade():
    op.drop_table("status_board_edits")
    op.drop_column("status_board_rows", "source_revision")
    op.drop_column("status_board_rows", "source_record_id")
