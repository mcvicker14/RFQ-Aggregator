"""POST /api/intelligence/coreworks-ingest — the push half of the COREWORKS Apps
Script integration (see app/api/routes/coreworks_ingest.py and
app/connectors/gmail_coreworks.py). The Apps Script's own time-driven trigger calls
this directly with raw message content; this route parses it
(parse_messages_to_raw_items) and runs it through the exact same ingest_pushed_items /
run_sync per-item pipeline every other source uses, logged as a SyncRun with
triggered_by=webhook.

No real Apps Script deployment or network call is used or needed — this tests the
route's own auth, plumbing, and the dedup/idempotency guarantee for the push path
specifically (the underlying (source_id, external_id) upsert key itself is already
covered extensively elsewhere, e.g. test_apex_sam_dedup.py).
"""
from datetime import datetime, timezone

from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from app.core.config import get_settings
from app.db.session import get_db
from app.main import app
from app.models.enums import SyncRunStatus, SyncTriggeredBy
from app.models.intelligence import IntelligenceItem, IntelligenceSource, IntelligenceSyncRun
from seed.intelligence_sources import seed_intelligence_sources

ONE_LISTING_FORWARD = """Begin forwarded message:

From: Ralph Fontcuberta <RFQwire@dbacoreworks.com>
Date: September 12, 2026 at 8:00:00 AM CDT
To: Eric McVicker <eric.mcvicker@pi-aec.com>
Subject: COREWORKS RFQwire * 2026 September 12 (Saturday) (AM)

COREWORKS RFQwire

New/Revised Listings Added: 2026 September 12 (Saturday)

__________________

NEW & REVISED LISTINGS | 2026 September 12 (Saturday)

LOUISIANA

2026 October 2 (LA) Jefferson Parish; Engineering Services for Drainage Improvements (RFQ<https://jeffparish.net/documents/rfq-drainage-2026/download>)

____________________________________

RFQ Tracking and Form Response * Since 1992
"""


def _client(db):
    app.dependency_overrides[get_db] = lambda: db
    return TestClient(app)


def _ingest(db, secret, messages):
    try:
        return _client(db).post(
            "/api/intelligence/coreworks-ingest", json={"secret": secret, "messages": messages},
        )
    finally:
        app.dependency_overrides.clear()


def _one_message(msg_id="apps-script-msg-1"):
    return [{"id": msg_id, "body_text": ONE_LISTING_FORWARD, "internal_date_ms": None}]


def test_503_when_secret_is_not_configured(db, monkeypatch):
    monkeypatch.setattr(get_settings(), "COREWORKS_WEBHOOK_SECRET", None)
    response = _ingest(db, "anything", [])
    assert response.status_code == 503


def test_401_when_secret_is_wrong(db, monkeypatch):
    monkeypatch.setattr(get_settings(), "COREWORKS_WEBHOOK_SECRET", "correct-secret")
    response = _ingest(db, "wrong-secret", [])
    assert response.status_code == 401


def test_401_when_secret_is_missing(db, monkeypatch):
    monkeypatch.setattr(get_settings(), "COREWORKS_WEBHOOK_SECRET", "correct-secret")
    response = _ingest(db, None, [])
    assert response.status_code == 401


def test_503_when_coreworks_source_is_not_seeded(db, monkeypatch):
    monkeypatch.setattr(get_settings(), "COREWORKS_WEBHOOK_SECRET", "correct-secret")
    # This shared dev database already has a real, previously-seeded "COREWORKS
    # RFQwire" row from actual manual verification earlier in this project (same
    # reason test_scheduled_sync.py resets runtime fields rather than assuming a
    # clean slate) — remove it within this test's own rolled-back-at-teardown
    # transaction (see tests/conftest.py's db fixture: join_transaction_mode=
    # "create_savepoint" means this can never affect the real shared database) so
    # "not seeded" is genuinely reproduced for this one test. ondelete=CASCADE on
    # intelligence_source_id takes any dependent rows with it.
    db.execute(delete(IntelligenceSource).where(IntelligenceSource.name == "COREWORKS RFQwire"))
    db.flush()

    response = _ingest(db, "correct-secret", _one_message())
    assert response.status_code == 503


def test_successful_ingest_creates_item_and_a_webhook_triggered_sync_run(db, monkeypatch):
    monkeypatch.setattr(get_settings(), "COREWORKS_WEBHOOK_SECRET", "correct-secret")
    seed_intelligence_sources(db)

    response = _ingest(db, "correct-secret", _one_message())

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["items_fetched"] == 1
    assert body["items_created"] == 1
    assert body["items_updated"] == 0

    source = db.execute(
        select(IntelligenceSource).where(IntelligenceSource.name == "COREWORKS RFQwire")
    ).scalars().one()
    # Scoped to this fixture's own distinctive title -- see
    # test_pushing_the_same_message_twice_updates_not_duplicates for why this never
    # assumes the source has no OTHER, unrelated items already.
    item = db.execute(
        select(IntelligenceItem).where(
            IntelligenceItem.intelligence_source_id == source.id,
            IntelligenceItem.title.contains("Drainage Improvements"),
        )
    ).scalars().one()
    assert "Jefferson Parish" in item.agency_name

    # Most recent run, not .one() -- this shared dev database's real COREWORKS source
    # row may already carry sync history from actual manual "Sync Now" activity
    # outside this test's own transaction (same reason test_scheduled_sync.py's
    # equivalent APEX assertion uses order_by(...).limit(1)); what this test needs to
    # confirm is only that THIS call produced a new run shaped the way the real
    # push pipeline produces one.
    run = db.execute(
        select(IntelligenceSyncRun)
        .where(IntelligenceSyncRun.intelligence_source_id == source.id)
        .order_by(IntelligenceSyncRun.started_at.desc())
        .limit(1)
    ).scalars().one()
    assert str(run.id) == body["sync_run_id"]
    assert run.triggered_by == SyncTriggeredBy.WEBHOOK
    assert run.status == SyncRunStatus.SUCCESS


def test_pushing_the_same_message_twice_updates_not_duplicates(db, monkeypatch):
    monkeypatch.setattr(get_settings(), "COREWORKS_WEBHOOK_SECRET", "correct-secret")
    seed_intelligence_sources(db)

    first = _ingest(db, "correct-secret", _one_message("msg-A"))
    assert first.json()["items_created"] == 1

    # A later re-listing of the exact same opportunity, pushed from a DIFFERENT Gmail
    # message id (the real-world "same listing appears in a later email" case) --
    # dedup keys on the listing's own derived external_id (solicitation/URL/client+
    # title+due-date), never the Gmail message id, so this must update, not duplicate.
    second = _ingest(db, "correct-secret", _one_message("msg-B"))
    assert second.status_code == 200
    assert second.json()["items_created"] == 0
    assert second.json()["items_updated"] == 1

    source = db.execute(
        select(IntelligenceSource).where(IntelligenceSource.name == "COREWORKS RFQwire")
    ).scalars().one()
    # Scoped to this fixture's own distinctive title, not an absolute count of every
    # item for the source — this shared dev database's real COREWORKS source row may
    # already carry other, unrelated items (same reasoning as the SyncRun query
    # above); what matters here is that exactly ONE item was ever created, not zero.
    items = db.execute(
        select(IntelligenceItem).where(
            IntelligenceItem.intelligence_source_id == source.id,
            IntelligenceItem.title.contains("Drainage Improvements"),
        )
    ).scalars().all()
    assert len(items) == 1  # never duplicated


def test_empty_messages_list_is_a_successful_no_op(db, monkeypatch):
    monkeypatch.setattr(get_settings(), "COREWORKS_WEBHOOK_SECRET", "correct-secret")
    seed_intelligence_sources(db)

    response = _ingest(db, "correct-secret", [])

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["items_fetched"] == 0


def test_409_when_a_sync_is_already_running_for_coreworks(db, monkeypatch):
    monkeypatch.setattr(get_settings(), "COREWORKS_WEBHOOK_SECRET", "correct-secret")
    seed_intelligence_sources(db)
    source = db.execute(
        select(IntelligenceSource).where(IntelligenceSource.name == "COREWORKS RFQwire")
    ).scalars().one()
    db.add(IntelligenceSyncRun(
        intelligence_source_id=source.id, started_at=datetime.now(timezone.utc),
        status=SyncRunStatus.RUNNING, triggered_by=SyncTriggeredBy.MANUAL,
    ))
    db.flush()

    response = _ingest(db, "correct-secret", _one_message())
    assert response.status_code == 409


def test_secret_is_never_leaked_back_in_the_response(db, monkeypatch):
    monkeypatch.setattr(get_settings(), "COREWORKS_WEBHOOK_SECRET", "super-secret-value")
    seed_intelligence_sources(db)
    response = _ingest(db, "super-secret-value", _one_message())
    assert "super-secret-value" not in response.text
