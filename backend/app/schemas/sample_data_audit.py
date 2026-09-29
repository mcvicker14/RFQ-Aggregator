"""Response shape for GET /api/admin/sample-data-audit. Mirrors the (entity, hard_
blockers, informational) tuples seed/audit_sample_data.py's audit_agencies/
audit_companies already return, so this schema can't drift from what the CLI reports."""
from datetime import date, datetime

from pydantic import BaseModel


class SampleDataAuditRow(BaseModel):
    id: str
    name: str
    # Nonzero entries are why this row is in blocked_* (a real record still depends on
    # it); always present but all-zero for safe_* rows.
    hard_blockers: dict[str, int]
    # e.g. seed-pattern contacts that will cascade with it either way -- never blocks.
    informational: dict[str, int]


class OrphanTaskRow(BaseModel):
    # Non-sensitive identifying fields only -- no notes, no owner/created_by -- enough
    # to review provenance by hand. Never acted on by cleanup_sample_data.py (it has no
    # is_sample_data column and no parent to inherit sample-status from).
    id: str
    title: str
    status: str
    priority: str
    due_date: date | None
    created_at: datetime


class SampleDataAuditResponse(BaseModel):
    # table_counts() as-is: {table_name: {total, sample, real}} for the 4 flagged tables.
    counts: dict[str, dict[str, int]]
    safe_agencies: list[SampleDataAuditRow]
    blocked_agencies: list[SampleDataAuditRow]
    safe_companies: list[SampleDataAuditRow]
    blocked_companies: list[SampleDataAuditRow]
    # Tasks with no opportunity_id -- no is_sample_data column and no parent to
    # inherit sample-status from, so never auto-included in any count above.
    orphan_task_count: int
    orphan_tasks: list[OrphanTaskRow]
