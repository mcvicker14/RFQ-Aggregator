"""add status_board_rows and status_board_cache_state

Revision ID: f3c7b2a9d1e4
Revises: a1b2c3d4e5f6
Create Date: 2026-10-01 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'f3c7b2a9d1e4'
down_revision: Union[str, None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "status_board_rows",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sheet_row_number", sa.Integer(), nullable=False),
        sa.Column("date_added", sa.String(length=50), nullable=True),
        sa.Column("due_date", sa.String(length=50), nullable=True),
        sa.Column("due_time", sa.String(length=50), nullable=True),
        sa.Column("client_project_location", sa.String(length=500), nullable=True),
        sa.Column("rfq_title", sa.String(length=1000), nullable=False),
        sa.Column("digital_option", sa.String(length=200), nullable=True),
        sa.Column("standard_form", sa.String(length=200), nullable=True),
        sa.Column("submit_y_n", sa.String(length=10), nullable=True),
        sa.Column("date_submitted", sa.String(length=50), nullable=True),
        sa.Column("importance", sa.String(length=200), nullable=True),
        sa.Column("quality", sa.String(length=200), nullable=True),
        sa.Column("probability", sa.String(length=200), nullable=True),
        sa.Column("go_bys", sa.String(length=500), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("submitted_y_n", sa.String(length=10), nullable=True),
        sa.Column("link", sa.String(length=1000), nullable=True),
        sa.Column("date_added_parsed", sa.Date(), nullable=True),
        sa.Column("due_date_parsed", sa.Date(), nullable=True),
        sa.Column("is_submit_y", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("is_submitted_y", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("opportunity_id", sa.UUID(), nullable=True),
        sa.Column("match_method", sa.String(length=30), nullable=False, server_default="unmatched"),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["opportunity_id"], ["opportunities.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_status_board_rows_sheet_row_number", "status_board_rows", ["sheet_row_number"])
    op.create_index("ix_status_board_rows_date_added_parsed", "status_board_rows", ["date_added_parsed"])
    op.create_index("ix_status_board_rows_due_date_parsed", "status_board_rows", ["due_date_parsed"])
    op.create_index("ix_status_board_rows_is_submit_y", "status_board_rows", ["is_submit_y"])
    op.create_index("ix_status_board_rows_is_submitted_y", "status_board_rows", ["is_submitted_y"])
    op.create_index("ix_status_board_rows_match_method", "status_board_rows", ["match_method"])
    op.alter_column("status_board_rows", "is_submit_y", server_default=None)
    op.alter_column("status_board_rows", "is_submitted_y", server_default=None)
    op.alter_column("status_board_rows", "match_method", server_default=None)

    op.create_table(
        "status_board_cache_state",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_sync_attempted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_sync_succeeded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("row_count", sa.Integer(), nullable=False, server_default="0"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.alter_column("status_board_cache_state", "row_count", server_default=None)


def downgrade() -> None:
    op.drop_table("status_board_cache_state")
    op.drop_index("ix_status_board_rows_match_method", table_name="status_board_rows")
    op.drop_index("ix_status_board_rows_is_submitted_y", table_name="status_board_rows")
    op.drop_index("ix_status_board_rows_is_submit_y", table_name="status_board_rows")
    op.drop_index("ix_status_board_rows_due_date_parsed", table_name="status_board_rows")
    op.drop_index("ix_status_board_rows_date_added_parsed", table_name="status_board_rows")
    op.drop_index("ix_status_board_rows_sheet_row_number", table_name="status_board_rows")
    op.drop_table("status_board_rows")
