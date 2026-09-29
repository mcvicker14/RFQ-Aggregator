"""SOQ Status Board sync — see app/services/google_sheets_client.py for the underlying
Sheets API mechanism. This module owns everything specific to *this* spreadsheet: the
New RFQs section's exact location and columns, the field mapping from an Opportunity to
a row, the insertion-point search that keeps New RFQs and the separate Grants mini-
table (and its "DO NOT FILL THE LAST LINE" sentinel row) untouched, and the two-layer
duplicate protection described below. Structure verified directly against the live
workbook at https://docs.google.com/spreadsheets/d/12KpUjFjx4AnoJt1KOlj9qFuQXZaTFGrVX-c3ExJ55GE
before this module was written — see the constants below and PR/commit description for
the row-by-row evidence.

**Duplicate protection, two layers:**
1. App-side (authoritative): StatusBoardSync has a unique constraint on opportunity_id
   -- at most one sync record ever exists per Opportunity. sync_opportunity_to_status_board()
   always checks/creates this row first; a SYNCED record short-circuits immediately
   with no Sheets API call at all, so a repeated click or an explicit retry after
   success is always a no-op.
2. Sheet-side (defense in depth, for the split-brain case where a previous write
   actually landed on the Sheet but this app's own status update didn't commit
   afterward — e.g. the process died between the two, or the Sheets call succeeded but
   the HTTP response back to this app was lost): every sync attempt re-reads the live
   New RFQs block and checks for a row already carrying this opportunity's Link (or,
   if no source_url, its Title+Client) before writing a new one. If found, that row is
   adopted as the synced state instead of writing a duplicate.

**Insertion point:** never a generic "append to the bottom of the sheet" — that would
land inside or past the separate Grants mini-table and its sentinel row. Every attempt
re-reads the New RFQs header (row 36) forward and finds the first row with nothing in
column A; that is always exactly the single blank spacer row that separates New RFQs
from the Grants section (see _find_insertion_point's docstring for why this invariant
holds across repeated inserts, not just the first one). If the fetched range runs out
before finding a blank row, or a known section-boundary marker turns up where a data
row was expected, this raises StatusBoardSheetStructureError rather than guessing — no
write happens, and the failure is recorded with a clear, specific reason.

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
from app.services import google_sheets_client as sheets_client

logger = logging.getLogger(__name__)

CENTRAL_TZ = ZoneInfo("America/Chicago")  # matches the sheet's own "Due Time CST" header

# --- Verified sheet structure — see module docstring ---------------------------------
SHEET_TAB_NAME = "Sheet1"  # the workbook's only tab
SHEET_GRID_ID = 0  # confirmed from the workbook URL's own #gid=0 fragment
NEW_RFQS_HEADER_ROW = 36  # 1-indexed; column A of this row reads exactly "New RFQs"
NEW_RFQS_HEADER_TEXT = "New RFQs"
# How far past the header this module will ever read while searching for the section's
# end. Generous enough to survive many future inserts (each one only ever shifts rows
# below the header down by one — see _find_insertion_point), small enough that reading
# it can never itself be mistaken for "the whole sheet."
SEARCH_WINDOW_ROWS = 120
# Text that must never appear inside what this module treats as New RFQs data — if it
# does, the sheet's structure has changed since it was last verified and this module
# refuses to guess at a safe row. "Grant Title" is the separate Grants mini-table's own
# header (verified at row 53 today); "ADD LINES ABOVE" is that table's own sentinel row
# telling a human never to fill below it — this module extends the same rule to itself.
SECTION_BOUNDARY_MARKERS = ("Grant Title", "ADD LINES ABOVE")

NEW_RFQS_COLUMNS = [
    "Date Added", "Due Date", "Due Time", "Client / Project Location", "RFQ Title",
    "Digital Option", "Standard Form", "Submit? Y or N", "Date Submitted",
    "Importance (1<3)", "Quality (1<3)", "Probability (1<3)", "Go-By(s)", "Notes",
    "Submitted Y/N", "Link",
]
LINK_COLUMN_INDEX = 15
TITLE_COLUMN_INDEX = 4
CLIENT_COLUMN_INDEX = 3


class StatusBoardSheetStructureError(RuntimeError):
    """The New RFQs section could not be safely located — e.g. its header text has
    changed, a section-boundary marker turned up before any blank row did, or no blank
    row was found within SEARCH_WINDOW_ROWS. Never guessed past; no write is attempted."""


def _row_is_blank(row: list[str]) -> bool:
    return not row or not (row[0] or "").strip()


def _row_boundary_marker(row: list[str]) -> str | None:
    joined = " ".join(cell for cell in row if cell)
    for marker in SECTION_BOUNDARY_MARKERS:
        if marker in joined:
            return marker
    return None


def _find_insertion_point(rows: list[list[str]]) -> tuple[int, list[list[str]]]:
    """`rows` is the raw values.get() response for
    Sheet1!A{NEW_RFQS_HEADER_ROW}:P{NEW_RFQS_HEADER_ROW + SEARCH_WINDOW_ROWS}, i.e.
    rows[0] is the "New RFQs" header row itself. Returns (target_row, existing_rows):
    target_row is the 1-indexed sheet row the next entry belongs at, and existing_rows
    are the New RFQs data rows already present (rows 37..target_row-1), for the
    duplicate scan. Raises StatusBoardSheetStructureError instead of ever returning a
    guess.

    Why "first blank row after the header" is always correct, not just the first time:
    every write this module performs is a true row *insertion*
    (google_sheets_client.insert_and_write_row), which shifts the single blank spacer
    row between New RFQs and the Grants section down by exactly one row each time — so
    the invariant "exactly one blank row, immediately after the last New RFQs entry"
    holds before the first tracked item and after every one since.
    """
    if not rows or (rows[0][0] if rows[0] else "") != NEW_RFQS_HEADER_TEXT:
        raise StatusBoardSheetStructureError(
            f"Row {NEW_RFQS_HEADER_ROW} of {SHEET_TAB_NAME} no longer reads "
            f"'{NEW_RFQS_HEADER_TEXT}' — refusing to guess where the New RFQs section is."
        )

    data_rows = rows[1:]
    for offset, row in enumerate(data_rows):
        marker = _row_boundary_marker(row)
        if marker:
            raise StatusBoardSheetStructureError(
                f"Found '{marker}' at row {NEW_RFQS_HEADER_ROW + 1 + offset} while still "
                "searching for a blank row after New RFQs — the section may have grown "
                "without its usual blank spacer before the next section. Refusing to write."
            )
        if _row_is_blank(row):
            return NEW_RFQS_HEADER_ROW + 1 + offset, data_rows[:offset]

    raise StatusBoardSheetStructureError(
        f"No blank row found in the {SEARCH_WINDOW_ROWS} rows after New RFQs (row "
        f"{NEW_RFQS_HEADER_ROW}) — refusing to write past the end of what was verified safe."
    )


def _find_existing_row(existing_rows: list[list[str]], link: str, title: str, client: str) -> int | None:
    """Returns the 1-indexed sheet row of an existing New RFQs entry that already
    represents this same opportunity, or None. Link match is authoritative when
    available (the strongest identifier the sheet itself can carry — an Opportunity ID
    or solicitation number has no column here); Title+Client is the fallback for a row
    with no source_url to compare."""
    link = (link or "").strip()
    title_key = (title or "").strip().lower()
    client_key = (client or "").strip().lower()
    for offset, row in enumerate(existing_rows):
        row_link = (row[LINK_COLUMN_INDEX] if len(row) > LINK_COLUMN_INDEX else "").strip()
        if link and row_link and row_link == link:
            return NEW_RFQS_HEADER_ROW + 1 + offset
        if not link:
            row_title = (row[TITLE_COLUMN_INDEX] if len(row) > TITLE_COLUMN_INDEX else "").strip().lower()
            row_client = (row[CLIENT_COLUMN_INDEX] if len(row) > CLIENT_COLUMN_INDEX else "").strip().lower()
            if title_key and row_title == title_key and row_client == client_key:
                return NEW_RFQS_HEADER_ROW + 1 + offset
    return None


def _format_date(dt: datetime | None) -> str:
    if dt is None:
        return ""
    local = dt.astimezone(CENTRAL_TZ)
    return f"{local.month}/{local.day}/{local.year}"


def _format_time(dt: datetime | None) -> str:
    if dt is None:
        return ""
    local = dt.astimezone(CENTRAL_TZ)
    return local.strftime("%-I:%M %p")


def _client_project_location(opp: Opportunity, agency: Agency | None) -> str:
    agency_label = agency.name if agency else None
    location = ", ".join(filter(None, [opp.location_city, opp.location_state])) or None
    return ", ".join(filter(None, [agency_label, location]))


def _build_row(opp: Opportunity, agency: Agency | None, notes: str | None, now: datetime) -> list[str]:
    due = opp.proposal_due_at
    return [
        _format_date(now),                         # Date Added
        _format_date(due),                          # Due Date
        _format_time(due),                          # Due Time
        _client_project_location(opp, agency),      # Client / Project Location
        opp.title,                                  # RFQ Title
        "",                                         # Digital Option — not reliably known
        "",                                         # Standard Form — not reliably known
        "",                                         # Submit? Y or N — blank by default
        "",                                         # Date Submitted — blank
        "",                                         # Importance — blank
        "",                                         # Quality — blank
        "",                                         # Probability — blank
        "",                                         # Go-By(s) — blank
        (notes or "").strip(),                      # Notes
        "",                                         # Submitted Y/N — matches every existing New RFQs row
        opp.source_url or "",                       # Link
    ]


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
    """Idempotently syncs one Opportunity to the New RFQs section. Safe to call
    repeatedly — a rapid double-click, an explicit retry, or an accidental re-invocation
    for an opportunity that's already synced all resolve to the same StatusBoardSync
    row and never produce a second Sheets write. Always returns the current
    StatusBoardSync row; check its `.status` to see whether this particular call
    actually wrote anything or short-circuited.
    """
    sync = get_or_create_pending_sync(db, opportunity.id)

    if sync.status == StatusBoardSyncStatus.SYNCED:
        return sync  # already done — no Sheets API call, guaranteed no duplicate

    if not sheets_client.is_configured():
        sync.status = StatusBoardSyncStatus.FAILED
        sync.last_error = "Status Board sync is not configured (GOOGLE_SERVICE_ACCOUNT_JSON is not set)."
        sync.last_attempted_at = datetime.now(timezone.utc)
        db.commit()
        return sync

    now = datetime.now(timezone.utc)
    sync.attempt_count += 1
    sync.last_attempted_at = now

    try:
        agency = db.get(Agency, opportunity.agency_id) if opportunity.agency_id else None
        client_location = _client_project_location(opportunity, agency)

        window_end = NEW_RFQS_HEADER_ROW + SEARCH_WINDOW_ROWS
        raw_rows = sheets_client.read_range(f"{SHEET_TAB_NAME}!A{NEW_RFQS_HEADER_ROW}:P{window_end}")
        target_row, existing_rows = _find_insertion_point(raw_rows)

        existing_row_number = _find_existing_row(
            existing_rows, opportunity.source_url or "", opportunity.title, client_location
        )
        if existing_row_number is not None:
            sync.status = StatusBoardSyncStatus.SYNCED
            sync.sheet_row_number = existing_row_number
            sync.synced_at = now
            sync.last_error = None
        else:
            row_values = _build_row(opportunity, agency, notes, now)
            sheets_client.insert_and_write_row(
                sheet_id=SHEET_GRID_ID, row_index_0based=target_row - 1, values=row_values
            )
            sync.status = StatusBoardSyncStatus.SYNCED
            sync.sheet_row_number = target_row
            sync.synced_at = now
            sync.last_error = None
    except (sheets_client.GoogleSheetsNotConfiguredError, sheets_client.GoogleSheetsApiError, StatusBoardSheetStructureError) as exc:
        sync.status = StatusBoardSyncStatus.FAILED
        sync.last_error = str(exc)
        logger.warning("Status Board sync failed for opportunity %s: %s", opportunity.id, exc)

    db.commit()
    return sync
