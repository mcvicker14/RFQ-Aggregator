"""add items_deduplicated and infrastructure_relevance_score/rationale

Revision ID: c2a9f1e6d4b7
Revises: 8dfbfb9cc829
Create Date: 2026-09-30 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = 'c2a9f1e6d4b7'
down_revision: Union[str, None] = '8dfbfb9cc829'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'intelligence_sync_runs',
        sa.Column('items_deduplicated', sa.Integer(), nullable=False, server_default='0'),
    )
    op.alter_column('intelligence_sync_runs', 'items_deduplicated', server_default=None)

    op.add_column('intelligence_items', sa.Column('infrastructure_relevance_score', sa.Integer(), nullable=True))
    op.add_column(
        'intelligence_items', sa.Column('infrastructure_relevance_rationale', postgresql.JSONB(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column('intelligence_items', 'infrastructure_relevance_rationale')
    op.drop_column('intelligence_items', 'infrastructure_relevance_score')
    op.drop_column('intelligence_sync_runs', 'items_deduplicated')
