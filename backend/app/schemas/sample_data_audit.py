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


class SampleDataCleanupRequest(BaseModel):
    # Must equal CLEANUP_CONFIRM_VALUE (app/api/routes/sample_data_cleanup.py) exactly,
    # or this call is treated as a dry run -- missing, blank, or any near-miss value
    # (wrong case, extra whitespace, "yes"/"true"/etc.) all fail closed to dry-run, not
    # an error. There is no other way to make this endpoint delete anything.
    confirm: str | None = None


class SampleDataCleanupResponse(BaseModel):
    performed: bool  # False = dry run, nothing changed. True = the deletion ran.
    confirm_value_required: str  # tells the caller the exact string this endpoint needs
    report_text: str  # the identical human-readable report `python -m seed.cleanup_sample_data` prints
    before_counts: dict[str, dict[str, int]]
    after_counts: dict[str, dict[str, int]] | None  # only set when performed=True
    deleted: dict[str, int] | None  # only set when performed=True
    safe_agencies: list[SampleDataAuditRow]
    blocked_agencies: list[SampleDataAuditRow]
    safe_companies: list[SampleDataAuditRow]
    blocked_companies: list[SampleDataAuditRow]
    # Always returned, on both a dry run and a real deletion -- proof this table was
    # never touched either way (see OrphanTaskRow).
    orphan_task_count: int
    orphan_tasks: list[OrphanTaskRow]
