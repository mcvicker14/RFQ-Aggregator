"""Status Board READ sync — the reverse direction of app/services/status_board_sync.py
(Sheet -> app, not app -> Sheet). Populates StatusBoardRow, a read-through cache of
every current New RFQs row, by calling the same Apps Script's new read action (see
app/services/status_board_webhook_client.py's read_rows() and
google-apps-script/status_board_sync.gs's readNewRfqsRows_()). This module never
writes to the Sheet — see docs/SECURITY.md and that module's own docstring for why the
write path works the way it does; this is purely additive.

**Cache replace semantics, full-success-only:** a successful read always reflects the
Sheet's CURRENT complete state, so every successful call deletes every existing
StatusBoardRow and inserts a fresh set, in one DB transaction. A failed call (Apps
Script down, misconfigured, malformed response) changes NOTHING in StatusBoardRow --
the previously-cached board state keeps displaying exactly as it was, with
StatusBoardCacheState.last_error/last_sync_attempted_at recording the failure for the
UI to surface. This is the literal mechanism behind "a temporary Google failure must
not wipe previously synchronized board state."

**Opportunity matching, in the exact preference order the product spec requires** (see
StatusBoardMatchMethod in app/models/enums.py for what each tier means and why
SYNC_RELATIONSHIP alone means "app-originated"):
1. SYNC_RELATIONSHIP: a stored row relationship corroborated by the unique identity
   match below. Row numbers move when people insert, delete or submit rows; alone
   they cannot identify an opportunity.
2. SOURCE_URL: the row's Link matches an Opportunity.source_url.
3. SOLICITATION_NUMBER: a leading "(IDENTIFIER) Title..." token in the row's RFQ Title
   (the same shape COREWORKS listings themselves use, see
   app/connectors/gmail_coreworks.py's _LEADING_IDENTIFIER for the proven real-world
   pattern this mirrors) matches Opportunity.solicitation_number -- most useful for
   OLD manual rows typed in before this app existed, which still carry that verbatim
   prefix; an app-created row's rfq_title never does (gmail_coreworks.py already
   strips it into its own field before the title ever reaches an Opportunity).
4. TITLE_CLIENT_DUE_DATE: the "controlled fallback" -- requires all three of title,
   client/location, and due date to line up, never title alone.
A row matching no tier stays unmatched (opportunity_id NULL) and still displays, as a
"Manual Status Board Entry" per is_manual_entry -- matching here is for linking/
display only and never creates an Opportunity, so a bad match's worst case is a wrong
display label, never duplicated or corrupted pipeline data.
"""
import logging
import re
from datetime import date, datetime, timezone

from sqlalchemy import delete, select, text
from sqlalchemy.orm import Session

from app.models.agency import Agency
from app.models.enums import StatusBoardMatchMethod, StatusBoardSyncStatus
from app.models.opportunity import Opportunity, StatusBoardCacheState, StatusBoardRow, StatusBoardSync
from app.services import status_board_webhook_client as webhook_client
from app.services.status_board_sync import FIELD_KEYS

logger = logging.getLogger(__name__)

# "(27-0014A) Engineering Consultant Services" / "(RFQ 26-ENGSRV-65) Title..." -- same
# shape as gmail_coreworks.py's _LEADING_IDENTIFIER, kept as its own small pattern here
# rather than importing a connector-internal regex into an unrelated module.
_LEADING_IDENTIFIER = re.compile(r"^\(([^()]{1,40})\)\s*\S")


def _parse_sheet_date(value: str | None) -> date | None:
    """Parses the exact "M/D/YYYY" shape status_board_sync.py's own _format_date()
    writes (no zero-padding, e.g. "10/8/2026") -- never guesses at any other format,
    since this app never writes a date in any other shape and a human-typed date in a
    different format simply won't parse (date_added_parsed stays None, which only
    affects filtering/sorting, never the raw displayed value)."""
    if not value or not value.strip():
        return None
    try:
        month, day, year = value.strip().split("/")
        return date(int(year), int(month), int(day))
    except (ValueError, TypeError):
        return None


def _is_yes(value: str | None) -> bool:
    return bool(value) and value.strip().upper().startswith("Y")


def _normalize(value: str | None) -> str:
    return (value or "").strip().lower()


def _match_opportunity(
    db: Session, row: dict, sheet_row_number: int, synced_by_row: dict[int, StatusBoardSync],
) -> tuple:
    opportunity_id, method = _match_by_identity(db, row)
    sync = synced_by_row.get(sheet_row_number)
    if opportunity_id is not None and sync is not None and sync.opportunity_id == opportunity_id:
        return opportunity_id, StatusBoardMatchMethod.SYNC_RELATIONSHIP
    return opportunity_id, method


def _match_by_identity(db: Session, row: dict) -> tuple:
    """Ambiguous shared bulletin URLs/identifiers must not choose an arbitrary row."""

    link = (row.get("link") or "").strip()
    if link:
        candidates = db.execute(select(Opportunity).where(Opportunity.source_url == link)).scalars().all()
        if len(candidates) == 1:
            return candidates[0].id, StatusBoardMatchMethod.SOURCE_URL

    title = row.get("rfq_title") or ""
    identifier_match = _LEADING_IDENTIFIER.match(title)
    if identifier_match is not None:
        identifier = identifier_match.group(1).strip()
        candidates = db.execute(
            select(Opportunity).where(Opportunity.solicitation_number == identifier)
        ).scalars().all()
        if len(candidates) == 1:
            return candidates[0].id, StatusBoardMatchMethod.SOLICITATION_NUMBER

    due = row.get("_due_date_parsed")
    if title and due is not None:
        client = _normalize(row.get("client_project_location"))
        candidates = db.execute(
            select(Opportunity).where(Opportunity.proposal_due_at.isnot(None))
        ).scalars().all()
        matches = []
        for opp in candidates:
            if _normalize(opp.title) != _normalize(title):
                continue
            if opp.proposal_due_at.date() != due:
                continue
            # Mirrors status_board_sync.py's own _client_project_location(): agency
            # fetched by id (Opportunity carries no agency relationship object), not
            # required to match exactly -- a loose substring either direction, since
            # a human-typed sheet cell and this app's own formatting rarely agree on
            # punctuation/ordering even when they mean the same client.
            opp_agency = db.get(Agency, opp.agency_id) if opp.agency_id else None
            opp_location = ", ".join(filter(None, [opp.location_city, opp.location_state]))
            opp_client_parts = [p for p in (opp_agency.name if opp_agency else None, opp_location) if p]
            if not client or not opp_client_parts or not any(_normalize(p) in client or client in _normalize(p) for p in opp_client_parts):
                continue
            matches.append(opp)
        if len(matches) == 1:
            return matches[0].id, StatusBoardMatchMethod.TITLE_CLIENT_DUE_DATE

    return None, StatusBoardMatchMethod.UNMATCHED


def _get_or_create_cache_state(db: Session) -> StatusBoardCacheState:
    state = db.execute(select(StatusBoardCacheState)).scalars().first()
    if state is None:
        state = StatusBoardCacheState()
        db.add(state)
        db.flush()
    return state


def _validate_rows(result: dict) -> list[dict]:
    """Validate the entire snapshot before any cache deletion, never skip bad rows."""
    if not isinstance(result, dict) or result.get("ok") is not True or not isinstance(result.get("rows"), list):
        raise ValueError("Status Board read returned an invalid snapshot envelope.")
    seen = set()
    record_ids = set()
    for row in result["rows"]:
        if not isinstance(row, dict):
            raise ValueError("Status Board read returned a non-object row.")
        number = row.get("sheet_row_number")
        if type(number) is not int or number < 1 or number in seen:
            raise ValueError("Status Board read returned a missing, invalid or duplicate row number.")
        seen.add(number)
        record_id = row.get("source_record_id")
        revision = row.get("source_revision")
        if record_id is not None:
            if not isinstance(record_id, str) or not re.fullmatch(r"[a-f0-9-]{36}", record_id) or record_id in record_ids:
                raise ValueError("Status Board returned an invalid or duplicate source identity.")
            record_ids.add(record_id)
        if revision is not None and (not isinstance(revision, str) or not re.fullmatch(r"[a-f0-9]{64}", revision)):
            raise ValueError("Status Board returned an invalid source revision.")
        for key in FIELD_KEYS:
            value = row.get(key)
            if key not in row or (value is not None and not isinstance(value, str)):
                raise ValueError(f"Status Board read returned an invalid {key} field.")
            limit = getattr(StatusBoardRow.__table__.columns[key].type, "length", None)
            if limit and value is not None and len(value) > limit:
                raise ValueError(f"Status Board read returned an oversized {key} field.")
    return result["rows"]


def refresh_status_board_cache(db: Session, *, minimum_interval_seconds: int = 0) -> StatusBoardCacheState:
    """Entry point for both the manual "Refresh Status Board" action and the
    automatic poll (see app/api/routes/status_board.py and app/main.py). Always
    returns the current StatusBoardCacheState; check .last_error to see whether THIS
    call succeeded -- a prior successful cache is never discarded by a failed one."""
    # Serialize complete cache replacement across scheduler, tabs and workers.
    # Transaction-scoped lock releases on commit/error; never leaks pooled locks.
    if not db.execute(text("SELECT pg_try_advisory_xact_lock(710042001)")).scalar():
        return db.execute(select(StatusBoardCacheState)).scalars().first() or StatusBoardCacheState(row_count=0)
    state = _get_or_create_cache_state(db)
    now = datetime.now(timezone.utc)
    if minimum_interval_seconds and state.last_sync_attempted_at and \
            (now - state.last_sync_attempted_at).total_seconds() < minimum_interval_seconds:
        db.commit()
        return state
    state.last_sync_attempted_at = now

    try:
        result = webhook_client.read_rows()
    except (webhook_client.StatusBoardWebhookNotConfiguredError, webhook_client.StatusBoardWebhookError) as exc:
        state.last_error = str(exc)
        db.commit()
        logger.warning("Status Board read-sync failed: %s", exc)
        return state

    if isinstance(result, dict) and result.get("ok") is False:
        state.last_error = "{}: {}".format(
            result.get("error", "error"), result.get("message", "Status Board read reported a failure."),
        )
        db.commit()
        logger.warning("Status Board read-sync reported failure: %s", state.last_error)
        return state

    try:
        raw_rows = _validate_rows(result)
    except ValueError as exc:
        state.last_error = str(exc)
        db.commit()
        logger.warning("Status Board read-sync malformed response: %s", state.last_error)
        return state

    synced_by_row = {
        s.sheet_row_number: s
        for s in db.execute(
            select(StatusBoardSync).where(
                StatusBoardSync.status == StatusBoardSyncStatus.SYNCED,
                StatusBoardSync.sheet_row_number.isnot(None),
            )
        ).scalars().all()
    }

    new_rows = []
    for raw in raw_rows:
        sheet_row_number = raw.get("sheet_row_number")
        due_parsed = _parse_sheet_date(raw.get("due_date"))
        date_added_parsed = _parse_sheet_date(raw.get("date_added"))
        match_row = {**raw, "_due_date_parsed": due_parsed}
        opportunity_id, match_method = _match_opportunity(db, match_row, sheet_row_number, synced_by_row)
        new_rows.append(StatusBoardRow(
            source_record_id=raw.get("source_record_id"),
            source_revision=raw.get("source_revision"),
            sheet_row_number=sheet_row_number,
            date_added=raw.get("date_added") or None,
            due_date=raw.get("due_date") or None,
            due_time=raw.get("due_time") or None,
            client_project_location=raw.get("client_project_location") or None,
            rfq_title=raw.get("rfq_title") or "",
            digital_option=raw.get("digital_option") or None,
            standard_form=raw.get("standard_form") or None,
            submit_y_n=raw.get("submit_y_n") or None,
            date_submitted=raw.get("date_submitted") or None,
            importance=raw.get("importance") or None,
            quality=raw.get("quality") or None,
            probability=raw.get("probability") or None,
            go_bys=raw.get("go_bys") or None,
            notes=raw.get("notes") or None,
            submitted_y_n=raw.get("submitted_y_n") or None,
            link=raw.get("link") or None,
            date_added_parsed=date_added_parsed,
            due_date_parsed=due_parsed,
            is_submit_y=_is_yes(raw.get("submit_y_n")),
            is_submitted_y=_is_yes(raw.get("submitted_y_n")),
            opportunity_id=opportunity_id,
            match_method=match_method,
            last_synced_at=now,
        ))

    # Full replace, same transaction as the state update below -- either both land or
    # (on any exception past this point) neither does, per the module's own
    # full-success-only cache guarantee.
    db.execute(delete(StatusBoardRow))
    for row in new_rows:
        db.add(row)

    state.last_sync_succeeded_at = now
    state.last_error = None
    state.row_count = len(new_rows)
    db.commit()
    return state
