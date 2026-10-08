"""Synthetic local Postgres and mocked Apps Script only; no production calls."""
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from app.core.config import get_settings
from app.models.opportunity import Opportunity, StatusBoardCacheState, StatusBoardRow
from app.services import status_board_webhook_client as webhook
from app.services.status_board_read_sync import refresh_status_board_cache
from app.services.status_board_reconciliation import latest_due_slot, run_due_board_reconciliation
from app.services.status_board_sync import FIELD_KEYS


def at(value):
    return datetime.fromisoformat(value)


@pytest.mark.parametrize("now,expected", [
    ("2026-07-01T13:59:59+00:00", "2026-07-01T01:00:00+00:00"),
    ("2026-07-01T14:00:00+00:00", "2026-07-01T14:00:00+00:00"),
    ("2026-07-01T17:00:00+00:00", "2026-07-01T17:00:00+00:00"),
    ("2026-07-01T21:00:00+00:00", "2026-07-01T21:00:00+00:00"),
    ("2026-07-02T01:00:00+00:00", "2026-07-02T01:00:00+00:00"),
    ("2026-01-01T15:00:00+00:00", "2026-01-01T15:00:00+00:00"),
    ("2026-01-01T18:00:00+00:00", "2026-01-01T18:00:00+00:00"),
    ("2026-01-01T22:00:00+00:00", "2026-01-01T22:00:00+00:00"),
    ("2026-01-02T02:00:00+00:00", "2026-01-02T02:00:00+00:00"),
    ("2026-03-08T13:59:59+00:00", "2026-03-08T02:00:00+00:00"),
    ("2026-03-08T14:00:00+00:00", "2026-03-08T14:00:00+00:00"),
    ("2026-11-01T14:59:59+00:00", "2026-11-01T01:00:00+00:00"),
    ("2026-11-01T15:00:00+00:00", "2026-11-01T15:00:00+00:00"),
])
def test_central_slots_follow_dst_including_transition_days(now, expected):
    assert latest_due_slot(at(now)) == at(expected)


def test_schedule_requires_aware_time():
    with pytest.raises(ValueError):
        latest_due_slot(datetime(2026, 10, 8))


def snapshot(size=26):
    return {"ok": True, "protocol_version": 2, "rows": [
        {**dict.fromkeys(FIELD_KEYS, ""), "sheet_row_number": 40 + i,
         "rfq_title": ["Port Arthur P26-061", "Athens RFQ27-6501", "Oconaluftee 12441926Q0040", "Calcasieu"][i]
                      if i < 4 else f"Synthetic RFQ {i}",
         "client_project_location": "Synthetic Agency", "submit_y_n": "Y" if i % 3 == 0 else "N" if i % 3 == 1 else "",
         "notes": "Owner notes", "link": f"https://example.invalid/{i}",
         "source_record_id": str(uuid4()), "source_revision": f"{i:064x}"}
        for i in range(size)]}


@pytest.fixture()
def enabled(monkeypatch):
    monkeypatch.setattr(get_settings(), "STATUS_BOARD_RECONCILIATION_ENABLED", True)


def test_disabled_schedule_calls_no_transport(db, monkeypatch):
    monkeypatch.setattr(get_settings(), "STATUS_BOARD_RECONCILIATION_ENABLED", False)
    monkeypatch.setattr(webhook, "reconcile_rows", lambda: pytest.fail("disabled"))
    assert run_due_board_reconciliation(db)["reason"] == "disabled"


def test_latest_slot_replaces_23_with_26_and_never_creates_opportunities_or_replays_decisions(db, enabled, monkeypatch):
    source = snapshot()
    monkeypatch.setattr(webhook, "read_rows", lambda: {**source, "rows": source["rows"][:23]})
    refresh_status_board_cache(db)
    original_opportunities = db.scalar(select(func.count()).select_from(Opportunity))
    calls = []
    monkeypatch.setattr(webhook, "reconcile_rows", lambda: calls.append(True) or source)
    monkeypatch.setattr(webhook, "set_submit", lambda *_: pytest.fail("no decision replay"))
    monkeypatch.setattr(webhook, "sync_row", lambda *_: pytest.fail("no Track/Add"))
    now = at("2026-10-08T21:05:00+00:00")
    result = run_due_board_reconciliation(db, now)
    assert result["reason"] == "completed" and result["slot_at"] == at("2026-10-08T21:00:00+00:00")
    rows = db.scalars(select(StatusBoardRow)).all()
    assert len(rows) == 26 and len({r.source_record_id for r in rows}) == 26
    for raw in source["rows"]:
        actual = next(r for r in rows if r.source_record_id == raw["source_record_id"])
        assert actual.rfq_title == raw["rfq_title"] and (actual.submit_y_n or "") == raw["submit_y_n"]
        assert actual.notes == raw["notes"] and actual.link == raw["link"]
    assert db.scalar(select(func.count()).select_from(Opportunity)) == original_opportunities
    run_due_board_reconciliation(db, now + timedelta(minutes=20))
    assert len(calls) == 1


def test_retry_after_failure_retains_cache_and_deduplicates_only_success(db, enabled, monkeypatch):
    source = snapshot(2)
    monkeypatch.setattr(webhook, "read_rows", lambda: source)
    refresh_status_board_cache(db)
    before = db.scalars(select(StatusBoardRow)).all()
    ids = {r.id for r in before}
    calls = []
    monkeypatch.setattr(webhook, "reconcile_rows", lambda: calls.append(True) or {"ok": False, "error": "conflict", "message": "Human edit; retry"})
    now = at("2026-10-08T17:00:00+00:00")
    assert run_due_board_reconciliation(db, now)["reason"] == "failed"
    state = db.scalars(select(StatusBoardCacheState)).one()
    assert state.last_reconciliation_slot_at is None and state.last_reconciliation_error
    assert {r.id for r in db.scalars(select(StatusBoardRow)).all()} == ids
    assert run_due_board_reconciliation(db, now + timedelta(minutes=1))["reason"] == "busy_or_retry_wait"
    assert len(calls) == 1
    monkeypatch.setattr(webhook, "reconcile_rows", lambda: calls.append(True) or source)
    assert run_due_board_reconciliation(db, now + timedelta(minutes=5))["reason"] == "completed"
    assert state.last_reconciliation_error is None and len(calls) == 2


@pytest.mark.parametrize("bad", ["missing_identity", "duplicate_identity", "malformed_rows"])
def test_invalid_reconciliation_never_advances_slot_or_replaces_cache(db, enabled, monkeypatch, bad):
    source = snapshot(2)
    if bad == "missing_identity": source["rows"][0]["source_record_id"] = None
    if bad == "duplicate_identity": source["rows"][1]["source_record_id"] = source["rows"][0]["source_record_id"]
    if bad == "malformed_rows": source["rows"] = [{}]
    monkeypatch.setattr(webhook, "reconcile_rows", lambda: source)
    assert run_due_board_reconciliation(db, at("2026-10-08T17:00:00+00:00"))["reason"] == "failed"
    assert db.scalars(select(StatusBoardCacheState)).one().last_reconciliation_slot_at is None


def test_manual_refresh_does_not_consume_a_scheduled_slot(db, enabled, monkeypatch):
    source = snapshot(1)
    monkeypatch.setattr(webhook, "read_rows", lambda: source)
    refresh_status_board_cache(db)
    state = db.scalars(select(StatusBoardCacheState)).one()
    assert state.last_reconciliation_slot_at is None and state.last_reconciliation_attempted_at is None


def test_shared_cache_lock_prevents_a_competing_reconciliation_transport(db, enabled, monkeypatch):
    from app.db.session import SessionLocal
    from sqlalchemy import text
    assert db.execute(text("SELECT pg_try_advisory_xact_lock(710042001)")).scalar()
    monkeypatch.setattr(webhook, "reconcile_rows", lambda: pytest.fail("another writer owns lock"))
    with SessionLocal() as other:
        assert run_due_board_reconciliation(other, at("2026-10-08T17:00:00+00:00"))["reason"] == "busy_or_retry_wait"


def test_reconcile_transport_sends_only_action_and_existing_secret(monkeypatch):
    calls = []
    monkeypatch.setattr(webhook, "_post", lambda payload: calls.append(payload) or {"ok": True, "rows": []})
    assert webhook.reconcile_rows()["ok"] and calls == [{"action": "reconcile"}]


@pytest.mark.parametrize("secret,expected", [(None, 401), ("wrong", 401), ("existing-test-secret", 200)])
def test_board_endpoint_authenticates_without_intake_calls(monkeypatch, secret, expected):
    from fastapi.testclient import TestClient
    from app.main import app
    from app.db.session import get_db
    from app.api.routes import status_board
    monkeypatch.setattr(get_settings(), "SCHEDULED_SYNC_SECRET", "existing-test-secret")
    calls = []
    monkeypatch.setattr(status_board, "run_due_board_reconciliation", lambda _: calls.append(True) or {"reason": "completed", "slot_at": None, "last_error": None})
    app.dependency_overrides[get_db] = lambda: object()
    try:
        response = TestClient(app).post("/api/status-board/reconciliation-check", json={"secret": secret})
        assert response.status_code == expected
        assert calls == ([True] if expected == 200 else [])
        assert "existing-test-secret" not in response.text
    finally:
        app.dependency_overrides.clear()


def test_board_endpoint_reports_failure_and_forbids_decision_payloads(monkeypatch):
    from fastapi.testclient import TestClient
    from app.main import app
    from app.db.session import get_db
    from app.api.routes import status_board
    monkeypatch.setattr(get_settings(), "SCHEDULED_SYNC_SECRET", "existing-test-secret")
    calls = []
    monkeypatch.setattr(status_board, "run_due_board_reconciliation", lambda _: calls.append(True) or {"reason": "failed", "slot_at": None, "last_error": "identity validation failed"})
    app.dependency_overrides[get_db] = lambda: object()
    try:
        client = TestClient(app)
        assert client.post("/api/status-board/reconciliation-check", json={"secret": "existing-test-secret"}).status_code == 503
        assert client.post("/api/status-board/reconciliation-check", json={"secret": "existing-test-secret", "value": "Y"}).status_code == 422
        assert calls == [True]
    finally:
        app.dependency_overrides.clear()
