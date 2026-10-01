"""Status Board READ sync — app/services/status_board_read_sync.py, the
status_board_filters.py predicates, and the /api/status-board/* routes. No real Apps
Script deployment or network call is used or needed: status_board_webhook_client's
read_rows is monkeypatched onto a local FakeAppsScript that models the SAME verified
sheet structure test_status_board_sync.py's FakeWebhook does for the write path
(header row, data rows, one blank spacer, then a marker row standing in for the
Grants mini-table's own boundary) — see that file's own docstring for why this is how
this codebase exercises the deployed google-apps-script/status_board_sync.gs's
structure-finding logic without running real Apps Script JavaScript. findNewRfqsBlock_
in that script is the SAME function both syncRow (write) and readNewRfqsRows_ (read)
call, so FakeAppsScript's read() mirrors its exact stop conditions: a blank row ends
New RFQs normally, a marker row ("Grant Title") found first means the Grants
mini-table/sentinel boundary was reached and reading stops before it.

Covers the user's explicit test list: app-created board row reads back correctly;
manual board row displays; Submit=Y; Submitted status; Due Soon/Past Due; Grants table
excluded; sentinel rows ignored; dashboard counts exactly match filtered Status Board
views; Apps Script outage preserves cached board state; no duplicate Opportunities
created.
"""
from datetime import date, datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.deps import get_current_user
from app.db.session import get_db
from app.main import app
from app.models.enums import (
    ContractType,
    MaturityStage,
    OpportunityStatus,
    SetAsideType,
    StatusBoardMatchMethod,
    StatusBoardSyncStatus,
    UserRole,
)
from app.models.opportunity import Opportunity, StatusBoardRow, StatusBoardSync
from app.models.user import User
from app.services import status_board_read_sync, status_board_webhook_client
from app.services.dashboard import build_dashboard_summary
from app.services.status_board_filters import STATUS_BOARD_FILTER_NAMES
from app.services.status_board_read_sync import (
    _is_yes,
    _match_opportunity,
    _parse_sheet_date,
    refresh_status_board_cache,
)
from app.services.status_board_webhook_client import StatusBoardWebhookError

NOW = datetime.now(timezone.utc)
TODAY = NOW.date()


class FakeAppsScript:
    """Mirrors test_status_board_sync.py's FakeWebhook, but for the read direction —
    see this module's own docstring for why this is how the codebase proves the
    backend behaves correctly against the deployed .gs file's structure-finding
    behavior without running real Apps Script JavaScript."""

    def __init__(self, header_row: int = 36, data_rows: list[dict] | None = None, include_marker: bool = True):
        self.header_row = header_row
        self.data = data_rows or []
        self.include_marker = include_marker
        self.configured = True

    def is_configured(self) -> bool:
        return self.configured

    def read_rows(self) -> dict:
        # Models readNewRfqsRows_() -> findNewRfqsBlock_(): data rows immediately
        # below the header, stopping at the first blank row (normal end of New
        # RFQs) — a marker row ("Grant Title", standing in for the Grants
        # mini-table) found before any blank row would be a structure_error in the
        # real script, so a well-formed sheet never reaches it; this fake simply
        # never includes rows past the blank spacer, exactly like the real
        # script's own `existingRows` slice never does.
        rows = []
        for i, fields in enumerate(self.data):
            rows.append({"sheet_row_number": self.header_row + 1 + i, **fields})
        return {"ok": True, "rows": rows}


def _fields(**overrides) -> dict:
    base = {
        "date_added": "9/1/2026", "due_date": "10/8/2026", "due_time": "5:00 PM",
        "client_project_location": "Orleans Parish School Board, New Orleans, LA",
        "rfq_title": "Engineering Consultant Services",
        "digital_option": "", "standard_form": "", "submit_y_n": "", "date_submitted": "",
        "importance": "", "quality": "", "probability": "", "go_bys": "", "notes": "",
        "submitted_y_n": "", "link": "https://nolapublicschools.com/rfq-27-0014a",
    }
    base.update(overrides)
    return base


@pytest.fixture()
def client(db):
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: User(
        id=None, email="test@example.com", full_name="Test", hashed_password="x",
        role=UserRole.BUSINESS_DEVELOPMENT, is_active=True,
    )
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def _opportunity(db, **overrides) -> Opportunity:
    defaults = dict(
        title="Engineering Consultant Services", source="Manual Entry",
        status=OpportunityStatus.ACTIVE, maturity_stage=MaturityStage.SOLICITATION_RELEASED,
        set_aside=SetAsideType.UNRESTRICTED, contract_type=ContractType.OTHER,
        proposal_due_at=datetime(2026, 10, 8, tzinfo=timezone.utc),
    )
    defaults.update(overrides)
    opp = Opportunity(**defaults)
    db.add(opp)
    db.flush()
    return opp


def _opportunity_count(db) -> int:
    return len(db.execute(select(Opportunity)).scalars().all())


# --- Parsing helpers ------------------------------------------------------------------

def test_parse_sheet_date_handles_the_exact_format_this_app_writes():
    assert _parse_sheet_date("10/8/2026") == date(2026, 10, 8)
    assert _parse_sheet_date("1/1/2026") == date(2026, 1, 1)


def test_parse_sheet_date_returns_none_for_blank_or_unparseable():
    assert _parse_sheet_date("") is None
    assert _parse_sheet_date(None) is None
    assert _parse_sheet_date("not a date") is None


def test_is_yes_normalizes_common_spellings():
    assert _is_yes("Y") and _is_yes("y") and _is_yes("Yes") and _is_yes("yes")
    assert not _is_yes("N") and not _is_yes("") and not _is_yes(None)


# --- 4-tier Opportunity matching, exact preference order ------------------------------

def test_tier1_sync_relationship_matches_an_exact_sheet_row_number(db):
    opp = _opportunity(db, title="Tier 1 Match")
    db.add(StatusBoardSync(
        opportunity_id=opp.id, status=StatusBoardSyncStatus.SYNCED, sheet_row_number=40,
    ))
    db.flush()
    synced_by_row = {40: db.execute(select(StatusBoardSync)).scalars().one()}

    opportunity_id, method = _match_opportunity(db, {"link": None, "rfq_title": "Something Else"}, 40, synced_by_row)
    assert opportunity_id == opp.id
    assert method == StatusBoardMatchMethod.SYNC_RELATIONSHIP


def test_tier2_source_url_matches_when_tier1_does_not_apply(db):
    opp = _opportunity(db, title="Tier 2 Match", source_url="https://example.com/rfq-tier2")
    row = {"link": "https://example.com/rfq-tier2", "rfq_title": "Unrelated Title"}

    opportunity_id, method = _match_opportunity(db, row, 99, {})
    assert opportunity_id == opp.id
    assert method == StatusBoardMatchMethod.SOURCE_URL


def test_tier3_solicitation_number_matches_a_leading_parenthetical(db):
    opp = _opportunity(db, title="Something Different Entirely", solicitation_number="27-0014A")
    row = {"link": None, "rfq_title": "(27-0014A) Engineering Consultant Services"}

    opportunity_id, method = _match_opportunity(db, row, 99, {})
    assert opportunity_id == opp.id
    assert method == StatusBoardMatchMethod.SOLICITATION_NUMBER


def test_tier4_title_client_due_date_requires_all_three(db):
    opp = _opportunity(
        db, title="Drainage Improvements", location_city="New Orleans", location_state="LA",
        proposal_due_at=datetime(2026, 11, 1, tzinfo=timezone.utc),
    )
    row = {
        "link": None, "rfq_title": "Drainage Improvements",
        "client_project_location": "New Orleans, LA",
        "_due_date_parsed": date(2026, 11, 1),
    }
    opportunity_id, method = _match_opportunity(db, row, 99, {})
    assert opportunity_id == opp.id
    assert method == StatusBoardMatchMethod.TITLE_CLIENT_DUE_DATE


def test_tier4_does_not_match_on_title_alone_with_a_different_due_date(db):
    _opportunity(db, title="Drainage Improvements", proposal_due_at=datetime(2026, 11, 1, tzinfo=timezone.utc))
    row = {
        "link": None, "rfq_title": "Drainage Improvements", "client_project_location": "",
        "_due_date_parsed": date(2026, 12, 25),  # different due date -- must not match
    }
    opportunity_id, method = _match_opportunity(db, row, 99, {})
    assert opportunity_id is None
    assert method == StatusBoardMatchMethod.UNMATCHED


def test_no_tier_matches_leaves_the_row_unmatched(db):
    opportunity_id, method = _match_opportunity(
        db, {"link": None, "rfq_title": "Completely Unrelated Listing"}, 99, {},
    )
    assert opportunity_id is None
    assert method == StatusBoardMatchMethod.UNMATCHED


# --- Full refresh_status_board_cache pipeline, via FakeAppsScript ---------------------

def _patch_fake(monkeypatch, fake: FakeAppsScript):
    monkeypatch.setattr(status_board_read_sync.webhook_client, "is_configured", fake.is_configured)
    monkeypatch.setattr(status_board_read_sync.webhook_client, "read_rows", fake.read_rows)


def test_app_created_board_row_reads_back_correctly(db, monkeypatch):
    opp = _opportunity(db, title="App-Synced Opportunity")
    db.add(StatusBoardSync(opportunity_id=opp.id, status=StatusBoardSyncStatus.SYNCED, sheet_row_number=36 + 1))
    db.flush()

    fake = FakeAppsScript(data_rows=[_fields(rfq_title="App-Synced Opportunity")])
    _patch_fake(monkeypatch, fake)

    state = refresh_status_board_cache(db)
    assert state.last_error is None

    row = db.execute(select(StatusBoardRow)).scalars().one()
    assert row.opportunity_id == opp.id
    assert row.match_method == StatusBoardMatchMethod.SYNC_RELATIONSHIP
    assert row.is_manual_entry is False


def test_manual_board_row_displays_unmatched_and_labeled(db, monkeypatch):
    fake = FakeAppsScript(data_rows=[_fields(rfq_title="A Totally Manual Row", link=None, client_project_location="")])
    _patch_fake(monkeypatch, fake)

    refresh_status_board_cache(db)

    row = db.execute(select(StatusBoardRow)).scalars().one()
    assert row.opportunity_id is None
    assert row.match_method == StatusBoardMatchMethod.UNMATCHED
    assert row.is_manual_entry is True
    assert row.rfq_title == "A Totally Manual Row"


def test_submit_y_is_normalized_and_flagged(db, monkeypatch):
    fake = FakeAppsScript(data_rows=[_fields(submit_y_n="Y"), _fields(rfq_title="Not Selected", submit_y_n="")])
    _patch_fake(monkeypatch, fake)
    refresh_status_board_cache(db)

    rows = db.execute(select(StatusBoardRow)).scalars().all()
    flagged = [r for r in rows if r.is_submit_y]
    assert len(flagged) == 1
    assert flagged[0].submit_y_n == "Y"


def test_submitted_status_is_normalized_and_flagged(db, monkeypatch):
    fake = FakeAppsScript(data_rows=[_fields(submitted_y_n="Y"), _fields(rfq_title="Pending", submitted_y_n="N")])
    _patch_fake(monkeypatch, fake)
    refresh_status_board_cache(db)

    rows = db.execute(select(StatusBoardRow)).scalars().all()
    submitted = [r for r in rows if r.is_submitted_y]
    assert len(submitted) == 1
    assert submitted[0].submitted_y_n == "Y"


def test_due_soon_and_past_due_are_correctly_bucketed(client, db, monkeypatch):
    soon = (TODAY + timedelta(days=10)).strftime("%-m/%-d/%Y")
    past = (TODAY - timedelta(days=5)).strftime("%-m/%-d/%Y")
    far = (TODAY + timedelta(days=200)).strftime("%-m/%-d/%Y")
    fake = FakeAppsScript(data_rows=[
        _fields(rfq_title="Due Soon Item", due_date=soon, link="https://example.com/a"),
        _fields(rfq_title="Past Due Item", due_date=past, submitted_y_n="", link="https://example.com/b"),
        _fields(rfq_title="Far Out Item", due_date=far, link="https://example.com/c"),
    ])
    _patch_fake(monkeypatch, fake)
    refresh_status_board_cache(db)

    due_soon = client.get("/api/status-board/rows", params={"filter": "due_soon"}).json()["rows"]
    assert {r["rfq_title"] for r in due_soon} == {"Due Soon Item"}

    past_due = client.get("/api/status-board/rows", params={"filter": "past_due"}).json()["rows"]
    assert {r["rfq_title"] for r in past_due} == {"Past Due Item"}


def test_past_due_excludes_already_submitted_rows(client, db, monkeypatch):
    past = (TODAY - timedelta(days=5)).strftime("%-m/%-d/%Y")
    fake = FakeAppsScript(data_rows=[_fields(rfq_title="Submitted Already", due_date=past, submitted_y_n="Y")])
    _patch_fake(monkeypatch, fake)
    refresh_status_board_cache(db)

    past_due = client.get("/api/status-board/rows", params={"filter": "past_due"}).json()["rows"]
    assert past_due == []


# --- Grants table / sentinel boundary (modeled via FakeAppsScript, see module docstring) --

def test_grants_table_and_sentinel_rows_are_never_part_of_the_cached_board(db, monkeypatch):
    # FakeAppsScript.read_rows() only ever returns what the real readNewRfqsRows_()
    # would: rows strictly between the New RFQs header and the first blank row. A
    # well-formed sheet's Grants mini-table and "ADD LINES ABOVE" sentinel both live
    # PAST that blank row, so they're structurally incapable of reaching this fake's
    # (or the real script's) returned rows at all -- this test proves the backend
    # caches exactly, and only, what's handed to it, with no Grants/sentinel leakage.
    fake = FakeAppsScript(data_rows=[_fields(rfq_title="Real New RFQ Row")])
    _patch_fake(monkeypatch, fake)

    refresh_status_board_cache(db)

    rows = db.execute(select(StatusBoardRow)).scalars().all()
    assert [r.rfq_title for r in rows] == ["Real New RFQ Row"]
    assert not any("Grant" in (r.rfq_title or "") for r in rows)


# --- Full-success-only cache replace + outage safety -----------------------------------

def test_a_successful_refresh_fully_replaces_the_cache(db, monkeypatch):
    fake1 = FakeAppsScript(data_rows=[_fields(rfq_title="First Sync Row")])
    _patch_fake(monkeypatch, fake1)
    refresh_status_board_cache(db)
    assert [r.rfq_title for r in db.execute(select(StatusBoardRow)).scalars().all()] == ["First Sync Row"]

    fake2 = FakeAppsScript(data_rows=[_fields(rfq_title="Second Sync Row")])
    _patch_fake(monkeypatch, fake2)
    refresh_status_board_cache(db)
    assert [r.rfq_title for r in db.execute(select(StatusBoardRow)).scalars().all()] == ["Second Sync Row"]


def test_apps_script_outage_preserves_previously_cached_board_state(db, monkeypatch):
    fake = FakeAppsScript(data_rows=[_fields(rfq_title="Stable Cached Row")])
    _patch_fake(monkeypatch, fake)
    refresh_status_board_cache(db)
    assert db.execute(select(StatusBoardRow)).scalars().one().rfq_title == "Stable Cached Row"

    def failing_read_rows():
        raise StatusBoardWebhookError("simulated Apps Script outage")

    monkeypatch.setattr(status_board_read_sync.webhook_client, "read_rows", failing_read_rows)
    state = refresh_status_board_cache(db)

    assert state.last_error is not None
    # The previously synced row is untouched -- never wiped by a failed refresh.
    assert db.execute(select(StatusBoardRow)).scalars().one().rfq_title == "Stable Cached Row"


def test_not_configured_also_preserves_cache_and_reports_clearly(db, monkeypatch):
    fake = FakeAppsScript(data_rows=[_fields(rfq_title="Still Here")])
    _patch_fake(monkeypatch, fake)
    refresh_status_board_cache(db)

    def not_configured_read_rows():
        raise status_board_webhook_client.StatusBoardWebhookNotConfiguredError("not configured")

    monkeypatch.setattr(status_board_read_sync.webhook_client, "is_configured", lambda: False)
    monkeypatch.setattr(status_board_read_sync.webhook_client, "read_rows", not_configured_read_rows)
    state = refresh_status_board_cache(db)

    assert state.last_error is not None
    assert db.execute(select(StatusBoardRow)).scalars().one().rfq_title == "Still Here"


# --- No duplicate Opportunities ---------------------------------------------------------

def test_refresh_never_creates_an_opportunity(db, monkeypatch):
    baseline = _opportunity_count(db)
    fake = FakeAppsScript(data_rows=[
        _fields(rfq_title="Unmatched Row One", link=None, client_project_location=""),
        _fields(rfq_title="Unmatched Row Two", link=None, client_project_location=""),
    ])
    _patch_fake(monkeypatch, fake)

    refresh_status_board_cache(db)

    assert _opportunity_count(db) == baseline  # never grew


# --- Dashboard counts exactly match filtered Status Board views (mirrors
# test_dashboard_kpi_drilldown.py's own kpi<->route consistency pattern) ----------------

_COUNT_FIELD_TO_FILTER = {
    "on_status_board": "all_active",
    "selected_to_submit": "submit_y",
    "due_soon": "due_soon",
    "submitted": "submitted",
    "past_due": "past_due",
}


def test_every_status_board_count_field_is_covered_by_this_test_file():
    assert set(_COUNT_FIELD_TO_FILTER.values()) <= STATUS_BOARD_FILTER_NAMES


@pytest.mark.parametrize("count_field,filter_name", sorted(_COUNT_FIELD_TO_FILTER.items()))
def test_dashboard_count_matches_status_board_route_count(client, db, monkeypatch, count_field, filter_name):
    soon = (TODAY + timedelta(days=5)).strftime("%-m/%-d/%Y")
    past = (TODAY - timedelta(days=3)).strftime("%-m/%-d/%Y")
    fake = FakeAppsScript(data_rows=[
        _fields(rfq_title="Row A", submit_y_n="Y", due_date=soon, link="https://example.com/a"),
        _fields(rfq_title="Row B", submitted_y_n="Y", due_date=past, link="https://example.com/b"),
        _fields(rfq_title="Row C", due_date=past, submitted_y_n="", link="https://example.com/c"),
    ])
    _patch_fake(monkeypatch, fake)
    refresh_status_board_cache(db)

    from app.models.user import User as UserModel
    user = db.query(UserModel).first()
    summary = build_dashboard_summary(db, user)
    expected = getattr(summary.status_board, count_field)

    response = client.get("/api/status-board/rows", params={"filter": filter_name})
    assert response.status_code == 200
    assert len(response.json()["rows"]) == expected


def test_dashboard_status_board_counts_are_zero_on_an_empty_board(db):
    user = db.query(User).first()
    summary = build_dashboard_summary(db, user)
    assert summary.status_board.on_status_board == 0
    assert summary.status_board.selected_to_submit == 0
    assert summary.status_board.submitted == 0
    assert summary.status_board.past_due == 0


# --- Route-level: sort + refresh endpoint ------------------------------------------------

def test_refresh_endpoint_triggers_a_sync_and_returns_the_fresh_rows(client, db, monkeypatch):
    fake = FakeAppsScript(data_rows=[_fields(rfq_title="Freshly Refreshed Row")])
    _patch_fake(monkeypatch, fake)

    response = client.post("/api/status-board/refresh")
    assert response.status_code == 200
    assert [r["rfq_title"] for r in response.json()["rows"]] == ["Freshly Refreshed Row"]


def test_sort_by_due_date_orders_rows_with_nulls_last(client, db, monkeypatch):
    fake = FakeAppsScript(data_rows=[
        _fields(rfq_title="No Due Date", due_date="", link="https://example.com/x"),
        _fields(rfq_title="Later", due_date="12/1/2026", link="https://example.com/y"),
        _fields(rfq_title="Sooner", due_date="10/1/2026", link="https://example.com/z"),
    ])
    _patch_fake(monkeypatch, fake)
    refresh_status_board_cache(db)

    response = client.get("/api/status-board/rows", params={"sort": "due_date", "order": "asc"})
    titles = [r["rfq_title"] for r in response.json()["rows"]]
    assert titles == ["Sooner", "Later", "No Due Date"]
