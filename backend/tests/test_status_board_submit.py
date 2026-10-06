"""Synthetic PostgreSQL, RBAC, audit and independent readback tests; no live calls."""
from datetime import datetime, timezone
from uuid import uuid4
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import select, func, text
from app.db.session import engine
from app.core.config import get_settings
from app.core.deps import get_current_user
from app.db.session import get_db
from app.main import app
from app.models.enums import UserRole
from app.models.user import User
from app.models.opportunity import Opportunity, StatusBoardRow, StatusBoardCacheState
from app.models.status_board_edit import StatusBoardEdit
from app.schemas.opportunity import StatusBoardSubmitEdit
from app.services import status_board_webhook_client as webhook
from app.services.status_board_read_sync import refresh_status_board_cache, _validate_rows
from app.services.status_board_submit import set_board_submit
from app.services.status_board_sync import FIELD_KEYS


@pytest.fixture
def board(db, monkeypatch):
    monkeypatch.setattr(get_settings(), "STATUS_BOARD_SUBMIT_EDITS_ENABLED", True)
    row = {key: "" for key in FIELD_KEYS}
    row.update(sheet_row_number=39, rfq_title="Synthetic RFQ", submit_y_n="N", notes="Do not touch",
               source_record_id=str(uuid4()), source_revision="a" * 64)
    calls = []
    monkeypatch.setattr(webhook, "read_rows", lambda: {"ok": True, "rows": [dict(row)]})
    def write(payload):
        calls.append(payload)
        row["submit_y_n"] = payload["value"]
        row["source_revision"] = "b" * 64
        return {"ok": True, "status": "confirmed", **payload, "source_revision": row["source_revision"]}
    monkeypatch.setattr(webhook, "set_submit", write)
    refresh_status_board_cache(db)
    actor = User(email=f"synthetic-{uuid4()}@example.invalid", full_name="Synthetic Owner", hashed_password="unused", role=UserRole.EXECUTIVE)
    db.add(actor); db.commit()
    edit = StatusBoardSubmitEdit(request_id=uuid4(), source_record_id=row["source_record_id"],
        expected_revision=row["source_revision"], expected_submit="N", value="Y")
    return actor, edit, row, calls


def test_confirmed_edit_has_durable_actor_audit_and_does_not_change_opportunities(db, board):
    actor, edit, row, calls = board
    before = db.execute(select(func.count()).select_from(Opportunity)).scalar()
    result = set_board_submit(db, actor, edit)
    assert result.status == "confirmed" and len(calls) == 1
    audit = db.execute(select(StatusBoardEdit).where(StatusBoardEdit.request_id == str(edit.request_id))).scalar_one()
    assert (audit.actor_id, audit.old_value, audit.new_value, audit.status) == (actor.id, "N", "Y", "confirmed")
    cached = db.execute(select(StatusBoardRow).where(StatusBoardRow.source_record_id == row["source_record_id"])).scalar_one()
    assert cached.notes == "Do not touch" and cached.submit_y_n == "Y"
    assert db.execute(select(func.count()).select_from(Opportunity)).scalar() == before


def test_exact_replay_returns_prior_ack_without_second_sheet_write(db, board):
    actor, edit, _, calls = board
    set_board_submit(db, actor, edit); set_board_submit(db, actor, edit)
    assert len(calls) == 1
    with pytest.raises(HTTPException) as exc:
        set_board_submit(db, actor, edit.model_copy(update={"value": "N"}))
    assert exc.value.status_code == 409 and len(calls) == 1


def test_timeout_is_uncertain_and_never_replayed(db, board, monkeypatch):
    actor, edit, _, calls = board
    def timeout(payload):
        calls.append(payload)
        raise webhook.StatusBoardWebhookError("synthetic timeout")
    monkeypatch.setattr(webhook, "set_submit", timeout)
    for _ in range(2):
        with pytest.raises(HTTPException): set_board_submit(db, actor, edit)
    audit = db.execute(select(StatusBoardEdit).where(StatusBoardEdit.request_id == str(edit.request_id))).scalar_one()
    assert audit.status == "uncertain" and len(calls) == 1


@pytest.mark.parametrize("mismatch", ["source_record_id", "request_id", "value", "source_revision", "status"])
def test_wrong_ack_or_readback_never_claims_success(db, board, monkeypatch, mismatch):
    actor, edit, row, calls = board
    def wrong(payload):
        calls.append(payload)
        return {"ok": True, "status": "confirmed", **payload, "source_revision": "a" * 64, mismatch: "wrong"}
    monkeypatch.setattr(webhook, "set_submit", wrong)
    with pytest.raises(HTTPException) as exc: set_board_submit(db, actor, edit)
    assert exc.value.status_code == 502 and len(calls) == 1
    assert db.execute(select(StatusBoardEdit).where(StatusBoardEdit.request_id == str(edit.request_id))).scalar_one().status == "uncertain"


def test_live_sheet_conflict_is_audited_and_refreshes_cache(db, board, monkeypatch):
    actor, edit, row, _ = board
    row["submit_y_n"] = "?"
    monkeypatch.setattr(webhook, "set_submit", lambda _: {"ok": False, "error": "conflict"})
    with pytest.raises(HTTPException) as exc: set_board_submit(db, actor, edit)
    assert exc.value.status_code == 409
    assert db.execute(select(StatusBoardRow).where(StatusBoardRow.source_record_id == row["source_record_id"])).scalar_one().submit_y_n == "?"


@pytest.mark.parametrize("change", ["deleted", "revision", "submitted", "duplicate"])
def test_stale_missing_submitted_or_ambiguous_cache_stops_before_write(db, board, change):
    actor, edit, row, calls = board
    cached = db.execute(select(StatusBoardRow).where(StatusBoardRow.source_record_id == row["source_record_id"])).scalar_one()
    if change == "deleted": db.delete(cached)
    elif change == "revision": cached.source_revision = "c" * 64
    elif change == "submitted": cached.is_submitted_y = True
    else:
        db.add(StatusBoardRow(source_record_id=cached.source_record_id, source_revision=cached.source_revision,
            sheet_row_number=40, rfq_title="Duplicate", last_synced_at=datetime.now(timezone.utc)))
    db.commit()
    with pytest.raises(HTTPException) as exc: set_board_submit(db, actor, edit)
    assert exc.value.status_code == 409 and not calls


def test_disabled_gate_no_audit_no_transport(db, board, monkeypatch):
    actor, edit, _, calls = board
    monkeypatch.setattr(get_settings(), "STATUS_BOARD_SUBMIT_EDITS_ENABLED", False)
    with pytest.raises(HTTPException) as exc: set_board_submit(db, actor, edit)
    assert exc.value.status_code == 503 and not calls


@pytest.mark.parametrize("role", [UserRole.VIEWER, UserRole.BUSINESS_DEVELOPMENT, UserRole.PROJECT_MANAGER, UserRole.PROPOSAL_MANAGER])
def test_only_owner_decision_roles_can_write(db, board, role):
    actor, edit, _, calls = board; actor.role = role
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: actor
    try:
        response = TestClient(app).patch("/api/status-board/submit", json=edit.model_dump(mode="json"))
        assert response.status_code == 403 and not calls
    finally: app.dependency_overrides.clear()


def test_route_validation_rejects_other_fields_or_values(db, board):
    actor, edit, _, calls = board
    app.dependency_overrides[get_db] = lambda: db; app.dependency_overrides[get_current_user] = lambda: actor
    try:
        client = TestClient(app)
        for extra in [{"value": "yes"}, {"value": "=1"}, {"notes": "overwrite"}, {"sheet_row_number": 39}]:
            assert client.patch("/api/status-board/submit", json={**edit.model_dump(mode="json"), **extra}).status_code == 422
        assert not calls
    finally: app.dependency_overrides.clear()


def test_refresh_requests_coalesce_within_45_seconds(db, board, monkeypatch):
    reads = []
    monkeypatch.setattr(webhook, "read_rows", lambda: reads.append(True))
    refresh_status_board_cache(db, minimum_interval_seconds=45)
    assert not reads


def test_duplicate_source_id_snapshot_is_rejected(board):
    _, _, row, _ = board
    with pytest.raises(ValueError): _validate_rows({"ok": True, "rows": [row, {**row, "sheet_row_number": 40}]})


def test_other_connection_refresh_lock_preserves_cache_until_released(db, monkeypatch):
    state = db.execute(select(StatusBoardCacheState)).scalars().first()
    if state is None:
        state = StatusBoardCacheState(row_count=99); db.add(state)
    else: state.row_count = 99
    db.commit()
    reads = []
    def read():
        reads.append(True)
        return {"ok": True, "rows": []}
    monkeypatch.setattr(webhook, "read_rows", read)
    with engine.connect() as other:
        transaction = other.begin()
        other.execute(text("SELECT pg_advisory_xact_lock(710042001)"))
        assert refresh_status_board_cache(db).row_count == 99
        assert not reads
        transaction.rollback()
    assert refresh_status_board_cache(db).row_count == 0
    assert len(reads) == 1
