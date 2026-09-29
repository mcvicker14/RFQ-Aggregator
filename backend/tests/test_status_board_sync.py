"""Tests for the SOQ Status Board sync — app/services/status_board_sync.py and the
POST /api/opportunities/{id}/status-board-sync route. No real Google credentials are
used or needed: sheets_client.read_range/insert_and_write_row/is_configured are
monkeypatched onto an in-memory FakeSheet that models the verified real structure
(New RFQs header, existing data rows, one blank spacer, then a marker row standing in
for the separate Grants section) closely enough to exercise the real insertion-point
and duplicate-detection logic against it.
"""
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.core.deps import get_current_user
from app.db.session import get_db
from app.main import app
from app.models.enums import StatusBoardSyncStatus, UserRole
from app.models.opportunity import Opportunity, StatusBoardSync
from app.models.user import User
from app.services import google_sheets_client, status_board_sync


class FakeSheet:
    """In-memory stand-in for the New RFQs section of the real spreadsheet. Rows are
    keyed by 1-indexed sheet row number, exactly like the real thing: a header row,
    zero or more existing data rows, one blank spacer, then a `marker_row` containing
    text status_board_sync.py recognizes as "this is not New RFQs anymore" — standing
    in for the real Grants mini-table's own header a few rows below the spacer today.
    """

    def __init__(self, header_row: int = 36, existing_data_rows: list[list[str]] | None = None):
        self.header_row = header_row
        self.rows: dict[int, list[str]] = {header_row: ["New RFQs"]}
        data = existing_data_rows or []
        for i, row in enumerate(data):
            self.rows[header_row + 1 + i] = row
        self.marker_row = header_row + 1 + len(data) + 1  # one blank row, then the marker
        self.rows[self.marker_row] = ["Grant Title", "marks the next section"]
        self.configured = True
        self.fail_next_read = False
        self.fail_next_write = False
        self.read_calls = 0
        self.write_calls = 0

    def is_configured(self) -> bool:
        return self.configured

    def read_range(self, a1_range: str) -> list[list[str]]:
        self.read_calls += 1
        if self.fail_next_read:
            self.fail_next_read = False
            raise google_sheets_client.GoogleSheetsApiError("simulated read failure")
        max_row = max(self.rows.keys())
        return [self.rows.get(r, []) for r in range(self.header_row, max_row + 1)]

    def insert_and_write_row(self, *, sheet_id: int, row_index_0based: int, values: list[str]) -> None:
        if self.fail_next_write:
            self.fail_next_write = False
            raise google_sheets_client.GoogleSheetsApiError("simulated write failure")
        target_row = row_index_0based + 1
        shifted: dict[int, list[str]] = {}
        for r, row in self.rows.items():
            shifted[r + 1 if r >= target_row else r] = row
        shifted[target_row] = values
        self.rows = shifted
        self.write_calls += 1


@pytest.fixture()
def fake_sheet(monkeypatch):
    sheet = FakeSheet()
    monkeypatch.setattr(status_board_sync.sheets_client, "is_configured", sheet.is_configured)
    monkeypatch.setattr(status_board_sync.sheets_client, "read_range", sheet.read_range)
    monkeypatch.setattr(status_board_sync.sheets_client, "insert_and_write_row", sheet.insert_and_write_row)
    return sheet


@pytest.fixture()
def client(db):
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: User(
        id=None, email="test@example.com", full_name="Test", hashed_password="x",
        role=UserRole.ADMINISTRATOR, is_active=True,
    )
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def _make_opportunity(db, **overrides) -> Opportunity:
    defaults = dict(title="Test RFQ Opportunity")
    defaults.update(overrides)
    opp = Opportunity(**defaults)
    db.add(opp)
    db.flush()
    return opp


# --- 1. Successful app tracking + Sheet write ----------------------------------------

def test_successful_sync_writes_row_and_records_synced_status(db, fake_sheet):
    opp = _make_opportunity(
        db, source_url="https://sam.gov/opp/abc123/view",
        proposal_due_at=datetime(2026, 10, 15, 19, 0, tzinfo=timezone.utc),
    )
    db.commit()

    result = status_board_sync.sync_opportunity_to_status_board(db, opp, notes="Strong civil engineering fit.")

    assert result.status == StatusBoardSyncStatus.SYNCED
    assert result.sheet_row_number is not None
    assert result.last_error is None
    assert fake_sheet.write_calls == 1
    written = fake_sheet.rows[result.sheet_row_number]
    assert written[status_board_sync.TITLE_COLUMN_INDEX] == "Test RFQ Opportunity"
    assert written[status_board_sync.LINK_COLUMN_INDEX] == "https://sam.gov/opp/abc123/view"
    assert written[13] == "Strong civil engineering fit."  # Notes


# --- 2. Duplicate prevention in the app -----------------------------------------------

def test_second_sync_call_short_circuits_no_duplicate(db, fake_sheet):
    opp = _make_opportunity(db, source_url="https://sam.gov/opp/dup-app/view")
    db.commit()

    first = status_board_sync.sync_opportunity_to_status_board(db, opp)
    second = status_board_sync.sync_opportunity_to_status_board(db, opp)

    assert first.id == second.id
    assert first.sheet_row_number == second.sheet_row_number
    assert fake_sheet.write_calls == 1  # only the first call ever touched the sheet

    rows_in_db = db.query(StatusBoardSync).filter(StatusBoardSync.opportunity_id == opp.id).count()
    assert rows_in_db == 1


# --- 3. Duplicate prevention in the Google Sheet (split-brain case) ------------------

def test_existing_sheet_row_detected_by_link_prevents_duplicate_write(db, fake_sheet):
    # The sheet already has a row for this exact opportunity (e.g. a prior write
    # succeeded on the Sheet side but this app's own status update never committed) --
    # no StatusBoardSync row exists yet in the DB.
    link = "https://sam.gov/opp/already-there/view"
    fake_sheet.rows[37] = ["9/1/2026", "9/20/2026", "2:00 PM", "USACE", "Already Tracked RFQ",
                            "", "", "", "", "", "", "", "", "", "", link]
    fake_sheet.marker_row = 39
    fake_sheet.rows[39] = ["Grant Title", "marks the next section"]
    fake_sheet.rows.pop(38, None)  # ensure row 38 (the blank spacer) has no stale entry

    opp = _make_opportunity(db, title="Already Tracked RFQ", source_url=link)
    db.commit()

    result = status_board_sync.sync_opportunity_to_status_board(db, opp)

    assert result.status == StatusBoardSyncStatus.SYNCED
    assert result.sheet_row_number == 37
    assert fake_sheet.write_calls == 0  # found the existing row, never wrote a new one


# --- 4. Rapid/repeated button clicks --------------------------------------------------

def test_rapid_repeated_calls_produce_exactly_one_sheet_row(db, fake_sheet):
    opp = _make_opportunity(db, source_url="https://sam.gov/opp/rapid-click/view")
    db.commit()

    results = [status_board_sync.sync_opportunity_to_status_board(db, opp) for _ in range(5)]

    assert fake_sheet.write_calls == 1
    row_numbers = {r.sheet_row_number for r in results}
    assert row_numbers == {results[0].sheet_row_number}
    assert db.query(StatusBoardSync).filter(StatusBoardSync.opportunity_id == opp.id).count() == 1


# --- 5. Missing optional fields --------------------------------------------------------

def test_missing_optional_fields_are_blank_not_invented(db, fake_sheet):
    opp = _make_opportunity(
        db, title="Minimal Opportunity",
        source_url=None, proposal_due_at=None, location_city=None, location_state=None, agency_id=None,
    )
    db.commit()

    result = status_board_sync.sync_opportunity_to_status_board(db, opp)

    assert result.status == StatusBoardSyncStatus.SYNCED
    written = fake_sheet.rows[result.sheet_row_number]
    assert written[1] == "" and written[2] == ""  # Due Date / Due Time
    assert written[3] == ""  # Client / Project Location -- no agency, no location
    assert written[15] == ""  # Link
    assert "None" not in written  # never literally stringifies a missing value
    for cell in written:
        assert cell is not None


# --- 6. Google Sheet write failure -----------------------------------------------------

def test_sheet_write_failure_marks_failed_with_clear_error(db, fake_sheet):
    fake_sheet.fail_next_write = True
    opp = _make_opportunity(db, source_url="https://sam.gov/opp/write-fail/view")
    db.commit()

    result = status_board_sync.sync_opportunity_to_status_board(db, opp)

    assert result.status == StatusBoardSyncStatus.FAILED
    assert result.last_error and "simulated write failure" in result.last_error
    assert result.sheet_row_number is None
    assert result.attempt_count == 1


# --- 7. App save success but Sheet write failure — Opportunity stays intact -----------

def test_opportunity_record_intact_after_sheet_write_failure(db, fake_sheet):
    fake_sheet.fail_next_write = True
    opp = _make_opportunity(db, title="Must Survive A Sheet Failure", source_url="https://sam.gov/opp/survive/view")
    db.commit()
    opp_id = opp.id

    result = status_board_sync.sync_opportunity_to_status_board(db, opp)
    assert result.status == StatusBoardSyncStatus.FAILED

    reloaded = db.get(Opportunity, opp_id)
    assert reloaded is not None
    assert reloaded.title == "Must Survive A Sheet Failure"
    assert reloaded.source_url == "https://sam.gov/opp/survive/view"


# --- 8. Retry after Sheet failure without creating duplicates -------------------------

def test_retry_after_failure_succeeds_without_duplicate(db, fake_sheet):
    fake_sheet.fail_next_write = True
    opp = _make_opportunity(db, source_url="https://sam.gov/opp/retry-me/view")
    db.commit()

    failed = status_board_sync.sync_opportunity_to_status_board(db, opp)
    assert failed.status == StatusBoardSyncStatus.FAILED
    assert fake_sheet.write_calls == 0

    retried = status_board_sync.sync_opportunity_to_status_board(db, opp)
    assert retried.status == StatusBoardSyncStatus.SYNCED
    assert retried.id == failed.id  # same StatusBoardSync row, not a second one
    assert retried.attempt_count == 2
    assert fake_sheet.write_calls == 1
    assert db.query(StatusBoardSync).filter(StatusBoardSync.opportunity_id == opp.id).count() == 1


# --- 9. Existing tracked (already-synced) opportunity re-sent to the Sheet -----------

def test_already_synced_opportunity_never_touches_the_sheet_again(db, fake_sheet):
    opp = _make_opportunity(db, source_url="https://sam.gov/opp/already-synced/view")
    db.commit()
    first = status_board_sync.sync_opportunity_to_status_board(db, opp)
    assert first.status == StatusBoardSyncStatus.SYNCED
    reads_after_first_sync = fake_sheet.read_calls

    again = status_board_sync.sync_opportunity_to_status_board(db, opp)

    assert again.sheet_row_number == first.sheet_row_number
    assert fake_sheet.write_calls == 1
    assert fake_sheet.read_calls == reads_after_first_sync  # short-circuited before even reading


# --- Sentinel / structure protection (fail-safe, per explicit requirement) -----------

def test_missing_blank_spacer_fails_safely_without_writing(db, fake_sheet):
    # Simulate the sheet having been edited so New RFQs data runs directly into the
    # Grants section's own header, with no blank spacer row in between.
    fake_sheet.rows[37] = ["9/1/2026", "9/20/2026", "2:00 PM", "Client", "Some RFQ",
                            "", "", "", "", "", "", "", "", "", "", ""]
    fake_sheet.rows[38] = ["Grant Title", "no spacer before this"]
    fake_sheet.marker_row = 38

    opp = _make_opportunity(db, source_url="https://sam.gov/opp/no-spacer/view")
    db.commit()

    result = status_board_sync.sync_opportunity_to_status_board(db, opp)

    assert result.status == StatusBoardSyncStatus.FAILED
    assert result.last_error and "Grant Title" in result.last_error
    assert fake_sheet.write_calls == 0


def test_not_configured_fails_clearly_without_touching_the_sheet(db, fake_sheet):
    fake_sheet.configured = False
    opp = _make_opportunity(db, source_url="https://sam.gov/opp/not-configured/view")
    db.commit()

    result = status_board_sync.sync_opportunity_to_status_board(db, opp)

    assert result.status == StatusBoardSyncStatus.FAILED
    assert result.last_error and "not configured" in result.last_error.lower()
    assert fake_sheet.read_calls == 0
    assert fake_sheet.write_calls == 0


# --- Route-level wiring ----------------------------------------------------------------

def test_route_syncs_and_is_idempotent_on_repeat_call(client, db, fake_sheet):
    opp = _make_opportunity(db, source_url="https://sam.gov/opp/route-test/view")
    db.commit()

    response = client.post(f"/api/opportunities/{opp.id}/status-board-sync", json={"notes": "From Discover"})
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "synced"
    assert body["sheet_row_number"] is not None

    response2 = client.post(f"/api/opportunities/{opp.id}/status-board-sync", json={})
    assert response2.status_code == 200
    assert response2.json()["sheet_row_number"] == body["sheet_row_number"]
    assert fake_sheet.write_calls == 1


def test_route_reports_failure_without_500_and_opportunity_stays(client, db, fake_sheet):
    fake_sheet.fail_next_write = True
    opp = _make_opportunity(db, source_url="https://sam.gov/opp/route-fail/view")
    db.commit()
    opp_id = opp.id

    response = client.post(f"/api/opportunities/{opp.id}/status-board-sync", json={})

    assert response.status_code == 200  # a sync failure is a normal, clearly-reported result, not a 500
    assert response.json()["status"] == "failed"
    assert client.get(f"/api/opportunities/{opp_id}").status_code == 200  # Opportunity intact
