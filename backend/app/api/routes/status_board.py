"""Status Board cached reads, immediate Submit edits and scheduled reconciliation.
Writing full rows to the sheet (one row per
"Track + Add to Status Board" click) happens elsewhere, unchanged — see
app/services/status_board_sync.py and its routes on opportunities.py/
intelligence_items.py. Reconciliation assigns source metadata and replaces the cache;
it never copies cached decisions back to the sheet.
"""
import hmac

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.deps import get_current_user, require_bd_or_above, require_decision_maker
from app.db.session import get_db
from app.models.opportunity import StatusBoardCacheState, StatusBoardRow
from app.models.user import User
from app.schemas.opportunity import StatusBoardListResponse, StatusBoardRowRead, StatusBoardSubmitEdit, StatusBoardSubmitResult
from app.services.status_board_filters import STATUS_BOARD_FILTER_NAMES, apply_status_board_filter
from app.services.status_board_read_sync import refresh_status_board_cache
from app.services.status_board_submit import set_board_submit
from app.services.status_board_reconciliation import run_due_board_reconciliation

router = APIRouter(prefix="/api/status-board", tags=["status-board"])


class BoardReconciliationCheck(BaseModel):
    model_config = ConfigDict(extra="forbid")
    secret: str | None = None


@router.post("/reconciliation-check")
def check_board_reconciliation(payload: BoardReconciliationCheck, response: Response,
                               db: Session = Depends(get_db)):
    """Dedicated board-only credential; no intake or decision-write authority."""
    configured = get_settings().STATUS_BOARD_RECONCILIATION_SECRET
    if not configured:
        raise HTTPException(503, "Board reconciliation credential is not configured.")
    if not payload.secret or not hmac.compare_digest(payload.secret.encode("utf-8"), configured.encode("utf-8")):
        raise HTTPException(401, "Invalid or missing board reconciliation credential.")
    result = run_due_board_reconciliation(db)
    if result["reason"] == "failed":
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return result

_SORT_COLUMNS = {
    "due_date": StatusBoardRow.due_date_parsed,
    "date_added": StatusBoardRow.date_added_parsed,
    "client": StatusBoardRow.client_project_location,
    "submit_status": StatusBoardRow.is_submit_y,
    "importance": StatusBoardRow.importance,
    "probability": StatusBoardRow.probability,
}


def _get_cache_state(db: Session) -> StatusBoardCacheState | None:
    return db.execute(select(StatusBoardCacheState)).scalars().first()


def _build_list_response(
    db: Session, filter: str, client: str | None, location: str | None, sort: str, order: str,
) -> StatusBoardListResponse:
    """Plain function (no FastAPI Query() defaults) so both routes below can call it
    directly with real argument values — a route handler can't call another route
    handler positionally/by-keyword and expect FastAPI's Query(...) markers to resolve
    themselves outside of an actual request."""
    stmt = select(StatusBoardRow)
    stmt = apply_status_board_filter(stmt, filter)
    for substring in (client, location):
        if substring:
            stmt = stmt.where(StatusBoardRow.client_project_location.ilike(f"%{substring}%"))

    column = _SORT_COLUMNS[sort]
    ordered = column.desc() if order == "desc" else column.asc()
    stmt = stmt.order_by(ordered.nulls_last())

    rows = db.execute(stmt).scalars().all()
    state = _get_cache_state(db)

    return StatusBoardListResponse(
        submit_edits_enabled=get_settings().STATUS_BOARD_SUBMIT_EDITS_ENABLED,
        rows=[StatusBoardRowRead.model_validate(r) for r in rows],
        last_sync_attempted_at=state.last_sync_attempted_at if state else None,
        last_sync_succeeded_at=state.last_sync_succeeded_at if state else None,
        last_error=state.last_error if state else None,
        sheet_url=get_settings().STATUS_BOARD_SHEET_URL,
    )


@router.get("/rows", response_model=StatusBoardListResponse)
def list_status_board_rows(
    filter: str = Query("all_active", pattern="^(" + "|".join(STATUS_BOARD_FILTER_NAMES) + ")$"),
    client: str | None = Query(None, description="Case-insensitive substring match against Client/Project Location."),
    location: str | None = Query(None, description="Case-insensitive substring match against Client/Project Location (same column as `client` — the sheet has one combined field, not separate client/location cells)."),
    sort: str = Query("due_date", pattern="^(" + "|".join(_SORT_COLUMNS) + ")$"),
    order: str = Query("asc", pattern="^(asc|desc)$"),
    db: Session = Depends(get_db),
    _current: User = Depends(get_current_user),
):
    return _build_list_response(db, filter, client, location, sort, order)


@router.post("/refresh", response_model=StatusBoardListResponse)
def refresh_status_board(db: Session = Depends(get_db), _current: User = Depends(require_bd_or_above)):
    refresh_status_board_cache(db, minimum_interval_seconds=45)
    return _build_list_response(db, "all_active", None, None, "due_date", "asc")


@router.patch("/submit", response_model=StatusBoardSubmitResult)
def edit_status_board_submit(edit: StatusBoardSubmitEdit, db: Session = Depends(get_db),
                             current: User = Depends(require_decision_maker)):
    return set_board_submit(db, current, edit)
