"""Tests for the SOQ Status Board sync — app/services/status_board_sync.py and the
POST /api/opportunities/{id}/status-board-sync route. No real Apps Script deployment
or network call is used or needed: status_board_webhook_client's is_configured/
sync_row are monkeypatched onto an in-memory FakeWebhook that reproduces the same
insertion-point search and duplicate check the deployed google-apps-script/
status_board_sync.gs performs, modeling the verified real structure (New RFQs header,
existing data rows, one blank spacer, then a marker row standing in for the separate
Grants section) closely enough to exercise the real request/response contract against
it — including the failure shapes (structure_error, unauthorized, locked) the actual
Apps Script can return.
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
from app.services import status_board_sync, status_board_webhook_client


class FakeWebhook:
    """In-memory stand-in for the deployed Apps Script webhook. Rows are keyed by
    1-indexed sheet row number, exactly like the real thing: a header row, zero or
    more existing New RFQs data rows, one blank spacer, then a `marker_row` containing
    text the real script treats as "this is not New RFQs anymore" — standing in for
    the Grants mini-table's own header a few rows below the spacer today.
    """

    def __init__(self, header_row: int = 36, existing_fields_rows: list[dict] | None = None):
        self.header_row = header_row
        self.rows: dict[int, list[str]] = {header_row: ["New RFQs"]}
        data = existing_fields_rows or []
        for i, fields in enumerate(data):
            self.rows[header_row + 1 + i] = self._fields_to_row(fields)
        self.marker_row = header_row + 1 + len(data) + 1  # one blank row, then the marker
        self.rows[self.marker_row] = ["Grant Title", "marks the next section"]
        self.configured = True
        self.fail_next_call = False
        self.call_count = 0
        self.insert_count = 0

    @staticmethod
    def _fields_to_row(fields: dict) -> list[str]:
        return [fields.get(k, "") for k in status_board_sync.FIELD_KEYS]

    def is_configured(self) -> bool:
        return self.configured

    def sync_row(self, fields: dict) -> dict:
        """Mirrors google-apps-script/status_board_sync.gs's syncRow(): search for the
        first blank row after the header, refusing to go further if a boundary marker
        turns up first; check the existing rows for a Link (or Title+Client) match
        before writing; insert-and-shift on an actual new row."""
        self.call_count += 1
        if self.fail_next_call:
            self.fail_next_call = False
            raise status_board_webhook_client.StatusBoardWebhookError("simulated webhook failure")

        max_row = max(self.rows.keys())
        window = [self.rows.get(r, []) for r in range(self.header_row, max_row + 1)]
        header, data_rows = window[0], window[1:]

        if not header or (header[0] if header else "") != "New RFQs":
            return {"ok": False, "error": "structure_error", "message": "Row does not read 'New RFQs'."}

        target_offset = None
        for i, row in enumerate(data_rows):
            joined = " ".join(c for c in row if c)
            if "Grant Title" in joined or "ADD LINES ABOVE" in joined:
                return {
                    "ok": False, "error": "structure_error",
                    "message": f"Found 'Grant Title' at row {self.header_row + 1 + i} before finding a blank row.",
                }
            if not row or not (row[0] or "").strip():
                target_offset = i
                break
        if target_offset is None:
            return {"ok": False, "error": "structure_error", "message": "No blank row found."}

        existing_rows = data_rows[:target_offset]
        target_row = self.header_row + 1 + target_offset

        link_idx = status_board_sync.FIELD_KEYS.index("link")
        title_idx = status_board_sync.FIELD_KEYS.index("rfq_title")
        client_idx = status_board_sync.FIELD_KEYS.index("client_project_location")
        link = (fields.get("link") or "").strip()
        title = (fields.get("rfq_title") or "").strip().lower()
        client = (fields.get("client_project_location") or "").strip().lower()
        for i, row in enumerate(existing_rows):
            row_link = (row[link_idx] if len(row) > link_idx else "").strip()
            if link and row_link and row_link == link:
                return {"ok": True, "status": "duplicate", "row": self.header_row + 1 + i}
            if not link:
                row_title = (row[title_idx] if len(row) > title_idx else "").strip().lower()
                row_client = (row[client_idx] if len(row) > client_idx else "").strip().lower()
                if title and row_title == title and row_client == client:
                    return {"ok": True, "status": "duplicate", "row": self.header_row + 1 + i}

        row_values = self._fields_to_row(fields)
        shifted: dict[int, list[str]] = {}
        for r, row in self.rows.items():
            shifted[r + 1 if r >= target_row else r] = row
        shifted[target_row] = row_values
        self.rows = shifted
        self.insert_count += 1
        return {"ok": True, "status": "inserted", "row": target_row}


def cell(webhook: FakeWebhook, row_number: int, key: str) -> str:
    return webhook.rows[row_number][status_board_sync.FIELD_KEYS.index(key)]


@pytest.fixture()
def fake_webhook(monkeypatch):
    webhook = FakeWebhook()
    monkeypatch.setattr(status_board_sync.webhook_client, "is_configured", webhook.is_configured)
    monkeypatch.setattr(status_board_sync.webhook_client, "sync_row", webhook.sync_row)
    return webhook


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


# --- 1. Successful track + webhook sync -----------------------------------------------

def test_successful_sync_writes_row_and_records_synced_status(db, fake_webhook):
    opp = _make_opportunity(
        db, source_url="https://sam.gov/opp/abc123/view",
        proposal_due_at=datetime(2026, 10, 15, 19, 0, tzinfo=timezone.utc),
    )
    db.commit()

    result = status_board_sync.sync_opportunity_to_status_board(db, opp, notes="Strong civil engineering fit.")

    assert result.status == StatusBoardSyncStatus.SYNCED
    assert result.sheet_row_number is not None
    assert result.last_error is None
    assert fake_webhook.insert_count == 1
    assert cell(fake_webhook, result.sheet_row_number, "rfq_title") == "Test RFQ Opportunity"
    assert cell(fake_webhook, result.sheet_row_number, "link") == "https://sam.gov/opp/abc123/view"
    assert cell(fake_webhook, result.sheet_row_number, "notes") == "Strong civil engineering fit."


# --- 2. Duplicate prevention in the app -------------------------------------------------

def test_second_sync_call_short_circuits_no_duplicate(db, fake_webhook):
    opp = _make_opportunity(db, source_url="https://sam.gov/opp/dup-app/view")
    db.commit()

    first = status_board_sync.sync_opportunity_to_status_board(db, opp)
    second = status_board_sync.sync_opportunity_to_status_board(db, opp)

    assert first.id == second.id
    assert first.sheet_row_number == second.sheet_row_number
    assert fake_webhook.call_count == 1  # second call never even reached the webhook

    rows_in_db = db.query(StatusBoardSync).filter(StatusBoardSync.opportunity_id == opp.id).count()
    assert rows_in_db == 1


# --- 3. Duplicate prevention in the Google Sheet (split-brain case) --------------------

def test_existing_sheet_row_detected_by_link_prevents_duplicate_write(db, fake_webhook):
    # The sheet already has a row for this exact opportunity (e.g. a prior webhook call
    # actually wrote it but this app's own status update never committed) -- no
    # StatusBoardSync row exists yet in the DB.
    link = "https://sam.gov/opp/already-there/view"
    fake_webhook.rows[37] = fake_webhook._fields_to_row(
        {"date_added": "9/1/2026", "rfq_title": "Already Tracked RFQ", "link": link}
    )
    fake_webhook.marker_row = 39
    fake_webhook.rows[39] = ["Grant Title", "marks the next section"]
    fake_webhook.rows.pop(38, None)  # ensure row 38 (the blank spacer) has no stale entry

    opp = _make_opportunity(db, title="Already Tracked RFQ", source_url=link)
    db.commit()

    result = status_board_sync.sync_opportunity_to_status_board(db, opp)

    assert result.status == StatusBoardSyncStatus.SYNCED
    assert result.sheet_row_number == 37
    assert fake_webhook.insert_count == 0  # found the existing row, never wrote a new one
    assert fake_webhook.call_count == 1  # but the webhook was still called once, and reported "duplicate"


# --- 4. Rapid/repeated button clicks ----------------------------------------------------

def test_rapid_repeated_calls_produce_exactly_one_sheet_row(db, fake_webhook):
    opp = _make_opportunity(db, source_url="https://sam.gov/opp/rapid-click/view")
    db.commit()

    results = [status_board_sync.sync_opportunity_to_status_board(db, opp) for _ in range(5)]

    assert fake_webhook.insert_count == 1
    row_numbers = {r.sheet_row_number for r in results}
    assert row_numbers == {results[0].sheet_row_number}
    assert db.query(StatusBoardSync).filter(StatusBoardSync.opportunity_id == opp.id).count() == 1


# --- 5. Missing optional fields ----------------------------------------------------------

def test_missing_optional_fields_are_blank_not_invented(db, fake_webhook):
    opp = _make_opportunity(
        db, title="Minimal Opportunity",
        source_url=None, proposal_due_at=None, location_city=None, location_state=None, agency_id=None,
    )
    db.commit()

    result = status_board_sync.sync_opportunity_to_status_board(db, opp)

    assert result.status == StatusBoardSyncStatus.SYNCED
    row_number = result.sheet_row_number
    assert cell(fake_webhook, row_number, "due_date") == ""
    assert cell(fake_webhook, row_number, "due_time") == ""
    assert cell(fake_webhook, row_number, "client_project_location") == ""  # no agency, no location
    assert cell(fake_webhook, row_number, "link") == ""
    written = fake_webhook.rows[row_number]
    assert "None" not in written  # never literally stringifies a missing value
    for value in written:
        assert value is not None


# --- 6. Webhook failure --------------------------------------------------------------------

def test_webhook_failure_marks_failed_with_clear_error(db, fake_webhook):
    fake_webhook.fail_next_call = True
    opp = _make_opportunity(db, source_url="https://sam.gov/opp/write-fail/view")
    db.commit()

    result = status_board_sync.sync_opportunity_to_status_board(db, opp)

    assert result.status == StatusBoardSyncStatus.FAILED
    assert result.last_error and "simulated webhook failure" in result.last_error
    assert result.sheet_row_number is None
    assert result.attempt_count == 1


def test_webhook_unauthorized_response_marks_failed_with_clear_error(db, fake_webhook, monkeypatch):
    # Simulates the deployed Apps Script rejecting a mismatched/rotated secret -- a
    # structured {"ok": false, ...} response, not a transport failure.
    monkeypatch.setattr(
        status_board_sync.webhook_client, "sync_row",
        lambda fields: {"ok": False, "error": "unauthorized", "message": "Missing or incorrect secret."},
    )
    opp = _make_opportunity(db, source_url="https://sam.gov/opp/bad-secret/view")
    db.commit()

    result = status_board_sync.sync_opportunity_to_status_board(db, opp)

    assert result.status == StatusBoardSyncStatus.FAILED
    assert result.last_error and "unauthorized" in result.last_error.lower()


# --- 7. App save success but Sheet write failure — Opportunity stays intact -----------

def test_opportunity_record_intact_after_sheet_write_failure(db, fake_webhook):
    fake_webhook.fail_next_call = True
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

def test_retry_after_failure_succeeds_without_duplicate(db, fake_webhook):
    fake_webhook.fail_next_call = True
    opp = _make_opportunity(db, source_url="https://sam.gov/opp/retry-me/view")
    db.commit()

    failed = status_board_sync.sync_opportunity_to_status_board(db, opp)
    assert failed.status == StatusBoardSyncStatus.FAILED
    assert fake_webhook.insert_count == 0

    retried = status_board_sync.sync_opportunity_to_status_board(db, opp)
    assert retried.status == StatusBoardSyncStatus.SYNCED
    assert retried.id == failed.id  # same StatusBoardSync row, not a second one
    assert retried.attempt_count == 2
    assert fake_webhook.insert_count == 1
    assert db.query(StatusBoardSync).filter(StatusBoardSync.opportunity_id == opp.id).count() == 1


# --- 9. Already-tracked (already-synced) opportunity never re-sent to the Sheet -------

def test_already_synced_opportunity_never_touches_the_sheet_again(db, fake_webhook):
    opp = _make_opportunity(db, source_url="https://sam.gov/opp/already-synced/view")
    db.commit()
    first = status_board_sync.sync_opportunity_to_status_board(db, opp)
    assert first.status == StatusBoardSyncStatus.SYNCED
    calls_after_first_sync = fake_webhook.call_count

    again = status_board_sync.sync_opportunity_to_status_board(db, opp)

    assert again.sheet_row_number == first.sheet_row_number
    assert fake_webhook.insert_count == 1
    assert fake_webhook.call_count == calls_after_first_sync  # short-circuited before calling the webhook at all


# --- Sentinel / structure protection — assumptions on the app side ---------------------
# The insertion-point search and sentinel/Grants protection actually run inside the
# deployed Apps Script (see google-apps-script/status_board_sync.gs), which pytest
# can't execute directly. What belongs here, and is tested below, is that this app
# correctly trusts and surfaces a structure_error the script reports rather than
# retrying blindly, silently succeeding, or crashing.

def test_missing_blank_spacer_fails_safely_without_writing(db, fake_webhook):
    # Simulate the sheet having been edited so New RFQs data runs directly into the
    # Grants section's own header, with no blank spacer row in between.
    fake_webhook.rows[37] = fake_webhook._fields_to_row(
        {"date_added": "9/1/2026", "rfq_title": "Some RFQ", "client_project_location": "Client"}
    )
    fake_webhook.rows[38] = ["Grant Title", "no spacer before this"]
    fake_webhook.marker_row = 38

    opp = _make_opportunity(db, source_url="https://sam.gov/opp/no-spacer/view")
    db.commit()

    result = status_board_sync.sync_opportunity_to_status_board(db, opp)

    assert result.status == StatusBoardSyncStatus.FAILED
    assert result.last_error and "Grant Title" in result.last_error
    assert fake_webhook.insert_count == 0


def test_structure_error_response_is_never_retried_automatically(db, fake_webhook, monkeypatch):
    # A structure_error is a refusal to guess, not a transient failure -- confirms this
    # app records it as FAILED (available for a manual Retry) rather than looping.
    calls = {"n": 0}

    def fail_once_then_ok(fields):
        calls["n"] += 1
        return {"ok": False, "error": "structure_error", "message": "No blank row found."}

    monkeypatch.setattr(status_board_sync.webhook_client, "sync_row", fail_once_then_ok)
    opp = _make_opportunity(db, source_url="https://sam.gov/opp/structure-error/view")
    db.commit()

    result = status_board_sync.sync_opportunity_to_status_board(db, opp)

    assert result.status == StatusBoardSyncStatus.FAILED
    assert calls["n"] == 1  # exactly one attempt -- no hidden retry loop


def test_not_configured_fails_clearly_without_touching_the_sheet(db, fake_webhook):
    fake_webhook.configured = False
    opp = _make_opportunity(db, source_url="https://sam.gov/opp/not-configured/view")
    db.commit()

    result = status_board_sync.sync_opportunity_to_status_board(db, opp)

    assert result.status == StatusBoardSyncStatus.FAILED
    assert result.last_error and "not configured" in result.last_error.lower()
    assert fake_webhook.call_count == 0


# --- Route-level wiring ------------------------------------------------------------------

def test_route_syncs_and_is_idempotent_on_repeat_call(client, db, fake_webhook):
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
    assert fake_webhook.insert_count == 1


def test_route_reports_failure_without_500_and_opportunity_stays(client, db, fake_webhook):
    fake_webhook.fail_next_call = True
    opp = _make_opportunity(db, source_url="https://sam.gov/opp/route-fail/view")
    db.commit()
    opp_id = opp.id

    response = client.post(f"/api/opportunities/{opp.id}/status-board-sync", json={})

    assert response.status_code == 200  # a sync failure is a normal, clearly-reported result, not a 500
    assert response.json()["status"] == "failed"
    assert client.get(f"/api/opportunities/{opp_id}").status_code == 200  # Opportunity intact
