"""Temporary admin-only, read-only endpoint exposing the exact same audit
`python -m seed.audit_sample_data` produces, for hosts (e.g. Render's free tier, which
has no Shell) where that CLI can't be run directly against the deployed database.

Calls seed/audit_sample_data.py's own functions directly rather than reimplementing
any of its logic -- this endpoint cannot disagree with the CLI because it IS the CLI's
logic, just returned as JSON instead of printed. See that module's docstring for the
full identification/safety reasoning.

Read-only: only SELECTs run underneath this route (table_counts/audit_agencies/
audit_companies/orphan_task_count never write anything), and nothing here imports
seed/cleanup_sample_data.py or sqlalchemy's `delete`. Deletion stays a CLI-only,
--yes-gated, human-run step. Safe to delete this route (and its entry in app/main.py)
once production's sample data has been reviewed and cleaned up -- nothing else in the
app depends on it.
"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.deps import require_admin
from app.db.session import get_db
from app.models.user import User
from app.schemas.sample_data_audit import SampleDataAuditResponse, SampleDataAuditRow
from seed.audit_sample_data import audit_agencies, audit_companies, orphan_task_count, table_counts

router = APIRouter(prefix="/api/admin", tags=["admin"])


def _rows(entries) -> list[SampleDataAuditRow]:
    return [
        SampleDataAuditRow(id=str(entity.id), name=entity.name, hard_blockers=hard, informational=info)
        for entity, hard, info in entries
    ]


@router.get("/sample-data-audit", response_model=SampleDataAuditResponse)
def get_sample_data_audit(db: Session = Depends(get_db), _admin: User = Depends(require_admin)):
    safe_agencies, blocked_agencies = audit_agencies(db)
    safe_companies, blocked_companies = audit_companies(db)
    return SampleDataAuditResponse(
        counts=table_counts(db),
        safe_agencies=_rows(safe_agencies),
        blocked_agencies=_rows(blocked_agencies),
        safe_companies=_rows(safe_companies),
        blocked_companies=_rows(blocked_companies),
        orphan_task_count=orphan_task_count(db),
    )
