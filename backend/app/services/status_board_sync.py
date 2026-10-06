"""SOQ Status Board sync — see app/services/status_board_webhook_client.py for the
transport, and google-apps-script/status_board_sync.gs (repo root) for what actually
locates the New RFQs insertion point and writes to the spreadsheet. This module owns
the parts that don't depend on *how* the write happens: the field mapping from an
Opportunity to a Status Board row, the app-side half of duplicate protection, and
orchestrating one sync attempt end to end.

**Why the sheet-write mechanics live in Apps Script, not here:** this app holds no
Google credentials of any kind. It POSTs a shared secret plus the mapped field values
to a Google Apps Script Web App bound to the SOQ Status Board sheet; that script,
running as its own owner inside Google's infrastructure, is the only thing that ever
reads or writes the spreadsheet. This module's docstring below describes the
guarantees that division of labor produces, not the mechanics of either half — see the
webhook client and the .gs file for those.

**Duplicate protection, two layers:**
1. App-side (authoritative): StatusBoardSync has a unique constraint on opportunity_id
   -- at most one sync record ever exists per Opportunity. sync_opportunity_to_status_board()
   always checks/creates this row first; a SYNCED record short-circuits immediately
   with no webhook call at all, so a repeated click or an explicit retry after success
   is always a no-op.
2. Sheet-side (defense in depth, enforced by the Apps Script itself): every webhook
   call that isn't short-circuited sends the full row; the script re-reads the live
   New RFQs block and checks for a row already carrying this opportunity's Link (or,
   if no source_url, its Title+Client) before writing. This covers the split-brain
   case where a previous call actually wrote the row but this app's own status update
   never committed — the process died between the two, or the HTTP response was lost
   on the way back, including a low-level retry inside request_with_retry re-sending
   an already-successful request. Either way, the next attempt finds the row the
   script already wrote and reports it back as `duplicate` instead of writing again.

**What gets synced:** this module has no opinion on *which* Opportunities should be
tracked to the Status Board — that policy lives in Discover's UI (only Live
Opportunity / Pre-Solicitation cards, the two categories that are ever promotable to a
real pursuit, offer "Track + Add to Status Board" at all; see PROMOTABLE_CATEGORIES in
components/discover/intelligence-card.tsx). By the time an Opportunity reaches this
module it's already a real tracked pursuit regardless of how it was created, so syncing
it here is uniform and asks no further questions about its origin.
"""
import logging
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.agency import Agency
from app.models.enums import StatusBoardSyncStatus
from app.models.opportunity import Opportunity, StatusBoardSync
from app.services import status_board_webhook_client as webhook_client

logger = logging.getLogger(__name__)

CENTRAL_TZ = ZoneInfo("America/Chicago")  # matches the sheet's own "Due Time CST" header

# Sent to the Apps Script webhook as {"fields": {...}} keyed by name, in the same order
# as the New RFQs section's own columns. Must match COLUMN_ORDER in
# google-apps-script/status_board_sync.gs exactly — keyed by name rather than a
# positional array so a mismatch between the two sides fails loudly (a missing or
# misspelled key) instead of silently writing a value into the wrong column.
FIELD_KEYS = [
    "date_added", "due_date", "due_time", "client_project_location", "rfq_title",
    "digital_option", "standard_form", "submit_y_n", "date_submitted",
    "importance", "quality", "probability", "go_bys", "notes", "submitted_y_n", "link",
]


def _format_date(dt: datetime | None) -> str:
    if dt is None:
        return ""
    local = dt.astimezone(CENTRAL_TZ)
    return f"{local.month}/{local.day}/{local.year}"


def _format_time(dt: datetime | None) -> str:
    if dt is None:
        return ""
    local = dt.astimezone(CENTRAL_TZ)
    return local.strftime("%I:%M %p").lstrip("0")


def _client_project_location(opp: Opportunity, agency: Agency | None) -> str:
    agency_label = agency.name if agency else None
    location = ", ".join(filter(None, [opp.location_city, opp.location_state])) or None
    return ", ".join(filter(None, [agency_label, location]))


def _build_fields(opp: Opportunity, agency: Agency | None, notes: str | None, now: datetime) -> dict[str, str]:
    due = opp.proposal_due_at
    fields = {
        "date_added": _format_date(now),
        "due_date": _format_date(due),
        "due_time": _format_time(due),
        "client_project_location": _client_project_location(opp, agency),
        "rfq_title": opp.title,
        "digital_option": "",        # Digital Option — not reliably known
        "standard_form": "",         # Standard Form — not reliably known
        "submit_y_n": "",            # Submit? Y or N — blank by default
        "date_submitted": "",        # Date Submitted — blank
        "importance": "",            # Importance — blank
        "quality": "",               # Quality — blank
        "probability": "",           # Probability — blank
        "go_bys": "",                # Go-By(s) — blank
        "notes": (notes or "").strip(),
        "submitted_y_n": "",         # Submitted Y/N — matches every existing New RFQs row
        "link": opp.source_url or "",
    }
    assert list(fields.keys()) == FIELD_KEYS
    return fields


def get_or_create_pending_sync(db: Session, opportunity_id) -> StatusBoardSync:
    """Fetches this opportunity's StatusBoardSync row, creating one if it doesn't
    exist yet. Races with a concurrent request for the *same* opportunity are resolved
    by the table's unique constraint: the loser's insert fails, rolls back, and adopts
    whatever the winner is doing instead of creating a second row."""
    sync = db.execute(
        select(StatusBoardSync).where(StatusBoardSync.opportunity_id == opportunity_id)
    ).scalar_one_or_none()
    if sync is not None:
        return sync

    sync = StatusBoardSync(opportunity_id=opportunity_id, status=StatusBoardSyncStatus.PENDING)
    db.add(sync)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        sync = db.execute(
            select(StatusBoardSync).where(StatusBoardSync.opportunity_id == opportunity_id)
        ).scalar_one()
    return sync


def sync_opportunity_to_status_board(db: Session, opportunity: Opportunity, notes: str | None = None) -> StatusBoardSync:
    """Idempotently syncs one Opportunity to the New RFQs section via the Apps Script
    webhook. Safe to call repeatedly — a rapid double-click, an explicit retry, or an
    accidental re-invocation for an opportunity that's already synced all resolve to
    the same StatusBoardSync row and never produce a second sheet row. Always returns
    the current StatusBoardSync row; check its `.status` to see whether this
    particular call actually wrote anything or short-circuited.
    """
    sync = get_or_create_pending_sync(db, opportunity.id)

    if sync.status == StatusBoardSyncStatus.SYNCED:
        return sync  # already done — no webhook call, guaranteed no duplicate

    if not webhook_client.is_configured():
        sync.status = StatusBoardSyncStatus.FAILED
        sync.last_error = (
            "Status Board sync is not configured (STATUS_BOARD_WEBHOOK_URL / "
            "STATUS_BOARD_WEBHOOK_SECRET are not set)."
        )
        sync.last_attempted_at = datetime.now(timezone.utc)
        db.commit()
        return sync

    now = datetime.now(timezone.utc)
    sync.attempt_count += 1
    sync.last_attempted_at = now

    try:
        agency = db.get(Agency, opportunity.agency_id) if opportunity.agency_id else None
        fields = _build_fields(opportunity, agency, notes, now)
        result = webhook_client.sync_row(fields)

        if not result.get("ok"):
            sync.status = StatusBoardSyncStatus.FAILED
            sync.last_error = "{}: {}".format(
                result.get("error", "error"),
                result.get("message", "Status Board webhook reported a failure."),
            )
        else:
            sync.status = StatusBoardSyncStatus.SYNCED
            sync.sheet_row_number = result.get("row")
            sync.synced_at = now
            sync.last_error = None
    except (webhook_client.StatusBoardWebhookNotConfiguredError, webhook_client.StatusBoardWebhookError) as exc:
        sync.status = StatusBoardSyncStatus.FAILED
        sync.last_error = str(exc)
        logger.warning("Status Board sync failed for opportunity %s: %s", opportunity.id, exc)

    db.commit()
    return sync
