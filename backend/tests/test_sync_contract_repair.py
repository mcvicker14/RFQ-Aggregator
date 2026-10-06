"""Offline regression tests: synthetic HTTP, session spies; no live services."""
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import Mock

import httpx
import pytest

from app.models.enums import SourceHealthStatus, SyncRunStatus, StatusBoardMatchMethod
from app.services import intelligence_sync, status_board_read_sync as reader
from app.services import status_board_webhook_client as client
from app.services.status_board_sync import FIELD_KEYS


def row(**changes):
    return {**dict.fromkeys(FIELD_KEYS, ""), "sheet_row_number": 39, **changes}


@pytest.mark.parametrize("response", [None, [], {"ok": "true", "rows": []}, {"ok": True},
    {"ok": True, "rows": [None]}, {"ok": True, "rows": [row(sheet_row_number=None)]},
    {"ok": True, "rows": [row(sheet_row_number=True)]}, {"ok": True, "rows": [row(), row()]},
    {"ok": True, "rows": [{"sheet_row_number": 39}]},
    {"ok": True, "rows": [row(due_date={})]},
    {"ok": True, "rows": [row(rfq_title="x" * 1001)]}])
def test_invalid_snapshot_never_deletes_cache_or_advances_success(monkeypatch, response):
    prior = datetime(2026, 9, 30, tzinfo=timezone.utc)
    state = SimpleNamespace(last_sync_succeeded_at=prior, row_count=24, last_error=None)
    db = Mock()
    monkeypatch.setattr(reader, "_get_or_create_cache_state", lambda _: state)
    monkeypatch.setattr(client, "read_rows", lambda: response)
    assert reader.refresh_status_board_cache(db) is state
    assert state.last_error
    assert state.last_sync_succeeded_at == prior
    assert state.row_count == 24
    # Taking the advisory read lock is allowed; malformed input must never issue
    # the subsequent DELETE/INSERT cache replacement.
    assert len(db.execute.call_args_list) == 1
    assert "pg_try_advisory_xact_lock" in str(db.execute.call_args.args[0])
    db.add.assert_not_called()
    db.commit.assert_called_once()


def test_complete_and_empty_snapshots_validate():
    assert reader._validate_rows({"ok": True, "rows": []}) == []
    assert reader._validate_rows({"ok": True, "rows": [row(submit_y_n="N")]})[0]["submit_y_n"] == "N"


def test_stale_row_number_cannot_link_to_a_deleted_or_moved_opportunity():
    db = Mock()
    stale = SimpleNamespace(opportunity_id="old")
    assert reader._match_opportunity(db, row(), 39, {39: stale}) == (None, StatusBoardMatchMethod.UNMATCHED)
    db.execute.assert_not_called()


def test_shared_source_url_is_not_an_identity_by_itself():
    db = Mock()
    db.execute.return_value.scalars.return_value.all.return_value = [SimpleNamespace(id="a"), SimpleNamespace(id="b")]
    assert reader._match_opportunity(db, row(link="https://example.test/bulletin"), 39, {}) == (None, StatusBoardMatchMethod.UNMATCHED)


def test_confirmed_identity_overrides_a_stale_row_relationship():
    db = Mock()
    db.execute.return_value.scalars.return_value.all.return_value = [SimpleNamespace(id="correct")]
    assert reader._match_opportunity(db, row(link="https://example.test/rfq"), 39,
                                    {39: SimpleNamespace(opportunity_id="old")}) == ("correct", StatusBoardMatchMethod.SOURCE_URL)


def test_title_and_due_date_without_client_is_not_a_match():
    db = Mock()
    due = datetime(2026, 10, 8, tzinfo=timezone.utc)
    db.execute.return_value.scalars.return_value.all.return_value = [SimpleNamespace(
        id="a", title="Test", proposal_due_at=due, agency_id=None, location_city="City", location_state="LA")]
    assert reader._match_opportunity(db, row(rfq_title="Test", _due_date_parsed=due.date()), 39, {}) == (None, StatusBoardMatchMethod.UNMATCHED)


def test_read_request_to_legacy_endpoint_is_diagnosed_without_write_retry(monkeypatch):
    post = Mock(return_value={"ok": False, "error": "bad_request", "message": "Missing 'fields' object."})
    monkeypatch.setattr(client, "_post", post)
    with pytest.raises(client.StatusBoardWebhookError, match="does not support action=read"):
        client.read_rows()
    post.assert_called_once_with({"action": "read"})


@pytest.mark.parametrize("body", [None, [], {"ok": "true"}])
def test_transport_rejects_non_object_and_non_boolean_envelopes(monkeypatch, body):
    monkeypatch.setattr(client, "get_settings", lambda: SimpleNamespace(
        STATUS_BOARD_WEBHOOK_URL="https://example.test/exec", STATUS_BOARD_WEBHOOK_SECRET="synthetic-secret"))
    monkeypatch.setattr(client, "request_with_retry", lambda *a, **k: httpx.Response(200, json=body))
    with pytest.raises(client.StatusBoardWebhookError):
        client.read_rows()


@pytest.mark.parametrize("good,bad,expected", [(0, 1, SyncRunStatus.FAILURE),
    (1, 1, SyncRunStatus.PARTIAL_FAILURE), (1, 0, SyncRunStatus.SUCCESS), (0, 0, SyncRunStatus.SUCCESS)])
def test_only_fully_successful_ingestion_advances_freshness(monkeypatch, good, bad, expected):
    prior = datetime(2026, 9, 30, tzinfo=timezone.utc)
    source = SimpleNamespace(name="Synthetic", last_successful_sync_at=prior)
    run = SimpleNamespace()
    def upsert(db, source, raw):
        if raw.external_id == "bad":
            raise ValueError("synthetic invalid item")
        return SimpleNamespace(), True
    monkeypatch.setattr(intelligence_sync, "_upsert_intelligence_item", upsert)
    for name in ("calculate_sam_relevance_score", "calculate_infrastructure_relevance_score",
                 "find_and_cluster_candidates", "sync_cluster_dismissal_state",
                 "calculate_early_signal_score", "calculate_grants_relevance_score"):
        monkeypatch.setattr(intelligence_sync, name, lambda *a: None)
    monkeypatch.setattr(intelligence_sync, "promote_intelligence_item", lambda *a: (None, False))
    items = [SimpleNamespace(external_id="good", fields={}) for _ in range(good)]
    items += [SimpleNamespace(external_id="bad", fields={}) for _ in range(bad)]
    intelligence_sync._process_fetched_items(Mock(), source, run, items)
    assert run.status == expected
    assert source.last_successful_sync_at == (run.finished_at if expected == SyncRunStatus.SUCCESS else prior)
    if expected == SyncRunStatus.FAILURE:
        assert source.health_status == SourceHealthStatus.FAILING
