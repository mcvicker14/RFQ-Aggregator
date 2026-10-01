"""Named predicates shared between the Dashboard's Status Board section
(app/services/dashboard.py) and the Status Board page's own filtered views
(app/api/routes/status_board.py, the `filter` query param) -- the single source of
truth for "which rows does this Dashboard count actually represent," mirroring
app/services/dashboard_filters.py's exact role for the Opportunities KPIs (see that
module's own docstring for the same reasoning, applied here to StatusBoardRow instead
of Opportunity).

DUE_SOON_DAYS is imported from dashboard_filters.py rather than redefined, so "Due
Soon" means the same window everywhere in this app, Status Board included.
"""
from datetime import date, datetime, timedelta

from sqlalchemy import Select, and_, or_

from app.models.opportunity import StatusBoardRow
from app.services.dashboard_filters import DUE_SOON_DEFAULT_DAYS

STATUS_BOARD_FILTER_NAMES = {
    "all_active",
    "submit_y",
    "submit_n_blank",
    "submitted",
    "not_submitted",
    "due_soon",
    "past_due",
}


def _is_blank_or_n(column):
    return or_(column.is_(None), column == "", column.ilike("n"))


def apply_status_board_filter(stmt: Select, filter_name: str, today: date | None = None) -> Select:
    """Applies one named Status Board filter on top of an existing StatusBoardRow
    SELECT. `today` must be the same date the caller used for any other Status-Board
    numbers in the same request (same reasoning as apply_kpi_filter's `now`) --
    defaults to the real current UTC date when the caller has no other shared instant
    to pass (the Dashboard and the Status Board route both pass their own `today`
    explicitly so a count and its drill-down link can never see different dates)."""
    today = today or datetime.now().date()

    if filter_name == "all_active":
        return stmt
    if filter_name == "submit_y":
        return stmt.where(StatusBoardRow.is_submit_y.is_(True))
    if filter_name == "submit_n_blank":
        return stmt.where(_is_blank_or_n(StatusBoardRow.submit_y_n))
    if filter_name == "submitted":
        return stmt.where(StatusBoardRow.is_submitted_y.is_(True))
    if filter_name == "not_submitted":
        return stmt.where(StatusBoardRow.is_submitted_y.is_(False))
    if filter_name == "due_soon":
        soon = today + timedelta(days=DUE_SOON_DEFAULT_DAYS)
        return stmt.where(
            StatusBoardRow.due_date_parsed.isnot(None),
            StatusBoardRow.due_date_parsed >= today,
            StatusBoardRow.due_date_parsed <= soon,
        )
    if filter_name == "past_due":
        return stmt.where(
            and_(
                StatusBoardRow.due_date_parsed.isnot(None),
                StatusBoardRow.due_date_parsed < today,
                StatusBoardRow.is_submitted_y.is_(False),
            )
        )
    return stmt
