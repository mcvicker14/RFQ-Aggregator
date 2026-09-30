"""Temporary admin-only endpoint that performs the one-time production sample-data
cleanup from hosts (e.g. Render's free tier) with no Shell and no way to run
`python -m seed.cleanup_sample_data --yes` directly against the deployed database.

Calls seed/cleanup_sample_data.py's own `cleanup()` function directly -- the exact
same deletion statements, in the exact same order, gated by the exact same
audit_agencies/audit_companies safe/blocked determination from seed/audit_sample_data.py
-- rather than reimplementing any of it. This route cannot disagree with the CLI
because it IS the CLI's logic; it only adds an HTTP-appropriate confirmation gate on
top. See seed/cleanup_sample_data.py and seed/audit_sample_data.py for the full
identification/safety reasoning (what is_sample_data=True means, why an Agency/Company
with a real dependent is preserved, why an orphan Task can never be touched).

Every call -- dry run or real -- re-runs audit_agencies/audit_companies/table_counts
against the database's CURRENT state. Nothing here trusts a previous audit's numbers.

DRY RUN (default): POST with no body, or {"confirm": <anything other than
CLEANUP_CONFIRM_VALUE>}. Runs cleanup(db, confirm=False) -- table_counts and the safe/
blocked breakdown only, zero writes -- and returns it as JSON, identical in substance
to GET /api/admin/sample-data-audit (see that route for the read-only equivalent).

REAL DELETION: POST with exactly {"confirm": "DELETE_SAMPLE_DATA"}. Any other value
(missing, blank, wrong case, extra whitespace) is a dry run, not an error -- this fails
closed. There is no other way to make this endpoint delete anything, and nothing else
this app exposes can trigger it.

Narrowly scoped on purpose: this route only ever calls seed/cleanup_sample_data.py's
cleanup(), which only ever touches opportunities/intelligence_items (by their own
is_sample_data flag) and agencies/companies (only the audit's safe list, never a
blocked one) -- see that module for why a Task can never be deleted by it. This is not
a generic admin-delete endpoint and never will be; it exists only for this one cleanup
and should be deleted (this file and its entry in app/main.py) once production's sample
data has been reviewed and cleaned up.
"""
import io
from contextlib import redirect_stdout

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.routes.sample_data_audit import audit_rows, orphan_task_rows
from app.core.deps import require_admin
from app.db.session import get_db
from app.models.user import User
from app.schemas.sample_data_audit import SampleDataCleanupRequest, SampleDataCleanupResponse
from seed.audit_sample_data import orphan_tasks
from seed.cleanup_sample_data import cleanup

router = APIRouter(prefix="/api/admin", tags=["admin"])

CLEANUP_CONFIRM_VALUE = "DELETE_SAMPLE_DATA"


@router.post("/sample-data-cleanup", response_model=SampleDataCleanupResponse)
def post_sample_data_cleanup(
    payload: SampleDataCleanupRequest = SampleDataCleanupRequest(),
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    confirmed = payload.confirm == CLEANUP_CONFIRM_VALUE

    report = io.StringIO()
    with redirect_stdout(report):
        result = cleanup(db, confirm=confirmed)

    # Re-checked fresh after cleanup() returns -- on a real deletion this proves the
    # orphan Task(s) are still there; on a dry run it's simply the current state.
    orphans = orphan_task_rows(orphan_tasks(db))

    return SampleDataCleanupResponse(
        performed=result["performed"],
        confirm_value_required=CLEANUP_CONFIRM_VALUE,
        report_text=report.getvalue(),
        before_counts=result["before_counts"],
        after_counts=result["after_counts"],
        deleted=result["deleted"],
        safe_agencies=audit_rows(result["safe_agencies"]),
        blocked_agencies=audit_rows(result["blocked_agencies"]),
        safe_companies=audit_rows(result["safe_companies"]),
        blocked_companies=audit_rows(result["blocked_companies"]),
        orphan_task_count=len(orphans),
        orphan_tasks=orphans,
    )
