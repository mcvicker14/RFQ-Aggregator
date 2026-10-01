"""Discover "Dismiss / Not Interested" — see app/services/dismissal.py.

Covers the user's explicit test list: dismiss an untracked item, persistence across a
reload, suppression surviving a resync, a SAM/APEX duplicate cluster staying
suppressed, an unrelated item being unaffected, the Dismissed view, Restore, a tracked
Opportunity never being touched, and normal Discover counts excluding dismissed items.
"""
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

import app.connectors.sam_gov as sam_gov_module
from app.connectors.registry import get_intelligence_connector
from app.connectors.web_apex_mybidmatch import _extract_sam_notice_id, _to_raw_intelligence_item
from app.core.deps import get_current_user
from app.db.session import get_db
from app.main import app
from app.models.enums import (
    ConnectorType,
    DismissalReason,
    IntelligenceCategory,
    JurisdictionLevel,
    SyncRunStatus,
    SyncTriggeredBy,
    UserRole,
)
from app.models.intelligence import IntelligenceItem, IntelligenceSource, ProjectCluster
from app.models.opportunity import Opportunity
from app.models.user import User
from app.services.dedup import find_and_cluster_candidates
from app.services.dismissal import (
    ItemAlreadyTrackedError,
    dismiss_item,
    effective_is_dismissed,
    restore_item,
    sync_cluster_dismissal_state,
)
from app.services.intelligence_sync import run_sync
from seed.intelligence_sources import seed_intelligence_sources

NOW = datetime.now(timezone.utc)
TEST_USER_ID = None  # matches the client fixture's test user — a nullable FK, fine in tests


def apex_to_raw_item(candidate, retrieved_at):
    """Integration fixtures represent validated FSG C article output, not index rows —
    see tests/test_apex_sam_dedup.py, same pattern."""
    return _to_raw_intelligence_item({**candidate, "fsg": "C",
        "article_number": candidate["detail_url"],
        "sam_notice_id": _extract_sam_notice_id(candidate["detail_url"]),
        "category": IntelligenceCategory.LIVE_OPPORTUNITY,
        "fields": {"title": candidate["title"], "agency_name": candidate["cells"][2]}}, retrieved_at)


@pytest.fixture()
def client(db):
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: User(
        id=None, email="test@example.com", full_name="Test", hashed_password="x",
        role=UserRole.VIEWER, is_active=True,
    )
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def _source(db, **overrides):
    defaults = dict(name="Dismissal Test Source", jurisdiction_level=JurisdictionLevel.FEDERAL, connector_type=ConnectorType.API)
    defaults.update(overrides)
    src = IntelligenceSource(**defaults)
    db.add(src)
    db.flush()
    return src


def _item(db, source, **overrides):
    defaults = dict(
        intelligence_source_id=source.id, external_id=overrides.pop("external_id", "X"),
        title="Test Item", intelligence_category=IntelligenceCategory.LIVE_OPPORTUNITY,
        source=source.name, retrieved_at=NOW,
    )
    defaults.update(overrides)
    item = IntelligenceItem(**defaults)
    db.add(item)
    db.flush()
    return item


# --- dismiss_item() / restore_item(): direct service-level behavior ----------------

def test_dismiss_untracked_item(db):
    source = _source(db)
    item = _item(db, source, external_id="A")

    dismiss_item(db, item, TEST_USER_ID, DismissalReason.TOO_SMALL)

    assert item.is_dismissed is True
    assert item.dismissed_at is not None
    assert item.dismissal_reason == DismissalReason.TOO_SMALL


def test_dismiss_rejects_an_already_tracked_item(db):
    source = _source(db)
    opp = Opportunity(title="Tracked pursuit")
    db.add(opp)
    db.flush()
    item = _item(db, source, external_id="A", opportunity_id=opp.id)

    with pytest.raises(ItemAlreadyTrackedError):
        dismiss_item(db, item, TEST_USER_ID)

    # Nothing touched — neither the item nor the Opportunity it's tracked as.
    assert item.is_dismissed is False
    assert db.get(Opportunity, opp.id) is not None


def test_restore_clears_both_item_and_cluster_flags(db):
    source = _source(db)
    cluster = ProjectCluster(representative_title="X")
    db.add(cluster)
    db.flush()
    item = _item(db, source, external_id="A", project_cluster_id=cluster.id)

    dismiss_item(db, item, TEST_USER_ID)
    assert cluster.is_dismissed is True

    restore_item(db, item, TEST_USER_ID)

    assert item.is_dismissed is False
    assert item.dismissed_at is None
    assert item.dismissal_reason is None
    db.refresh(cluster)
    assert cluster.is_dismissed is False


def test_dismissing_a_clustered_item_dismisses_the_whole_cluster(db):
    source = _source(db)
    cluster = ProjectCluster(representative_title="Same procurement")
    db.add(cluster)
    db.flush()
    sam_item = _item(db, source, external_id="A", project_cluster_id=cluster.id)
    apex_item = _item(db, source, external_id="B", project_cluster_id=cluster.id)

    dismiss_item(db, sam_item, TEST_USER_ID, DismissalReason.DUPLICATE)

    assert cluster.is_dismissed is True
    # The sibling's OWN row is untouched — suppression comes from the cluster check,
    # not a fan-out write to every member.
    assert apex_item.is_dismissed is False
    assert effective_is_dismissed(apex_item, cluster) is True


def test_dismissing_an_untracked_sibling_never_hides_a_tracked_one(db):
    # The key safety rule: a cluster containing an actively tracked item must never
    # become cluster-dismissed by dismissing a DIFFERENT, untracked copy — that would
    # make an active pursuit silently vanish from Discover.
    source = _source(db)
    cluster = ProjectCluster(representative_title="Same procurement")
    db.add(cluster)
    db.flush()
    opp = Opportunity(title="Active pursuit")
    db.add(opp)
    db.flush()
    tracked_item = _item(db, source, external_id="A", project_cluster_id=cluster.id, opportunity_id=opp.id)
    untracked_item = _item(db, source, external_id="B", project_cluster_id=cluster.id)

    dismiss_item(db, untracked_item, TEST_USER_ID)

    assert untracked_item.is_dismissed is True
    assert cluster.is_dismissed is False  # not cluster-wide — a sibling is tracked
    assert effective_is_dismissed(tracked_item, cluster) is False  # tracked -> never dismissed
    assert effective_is_dismissed(untracked_item, cluster) is True  # its own flag still hides it


def test_unrelated_item_is_unaffected_by_a_different_dismissal(db):
    source = _source(db)
    dismissed = _item(db, source, external_id="A", title="Dismiss me")
    unrelated = _item(db, source, external_id="B", title="Leave me alone")

    dismiss_item(db, dismissed, TEST_USER_ID)

    assert unrelated.is_dismissed is False
    assert unrelated.project_cluster_id is None


# --- sync_cluster_dismissal_state(): propagation at sync time -----------------------

def test_sync_time_propagation_inherits_dismissal_onto_a_newly_clustered_item(db):
    # item was dismissed BEFORE any duplicate was ever seen (unclustered) -- a later
    # sync that clusters a new item with it must inherit the dismissal immediately.
    source = _source(db)
    old_item = _item(db, source, external_id="A", title="Drainage project", location_state="LA", agency_name="USACE")
    dismiss_item(db, old_item, TEST_USER_ID, DismissalReason.WRONG_GEOGRAPHY)
    assert old_item.project_cluster_id is None  # confirmed still unclustered

    new_item = _item(db, source, external_id="B", title="Drainage project", location_state="LA", agency_name="USACE")
    find_and_cluster_candidates(db, new_item)
    assert new_item.project_cluster_id is not None  # confirms dedup.py's own matching linked them

    sync_cluster_dismissal_state(db, new_item)

    assert new_item.is_dismissed is True
    cluster = db.get(ProjectCluster, new_item.project_cluster_id)
    assert cluster.is_dismissed is True
    assert cluster.dismissal_reason == DismissalReason.WRONG_GEOGRAPHY


def test_sync_time_propagation_is_a_noop_when_a_cluster_sibling_is_tracked(db):
    source = _source(db)
    cluster = ProjectCluster(representative_title="X")
    db.add(cluster)
    db.flush()
    opp = Opportunity(title="Active pursuit")
    db.add(opp)
    db.flush()
    _item(db, source, external_id="A", project_cluster_id=cluster.id, opportunity_id=opp.id)
    sibling = _item(db, source, external_id="B", project_cluster_id=cluster.id, is_dismissed=True)

    sync_cluster_dismissal_state(db, sibling)

    assert cluster.is_dismissed is False


# --- Full pipeline: dismissal must survive a resync, including a SAM/APEX cluster ---

def _sam_notice(**overrides) -> dict:
    base = {
        "noticeId": "dismissal-test-notice",
        "title": "Levee Rehabilitation — Civil Engineering Design Services",
        "solicitationNumber": "W912P8-26-R-0099",
        "fullParentPathName": "DEPT OF DEFENSE.DEPT OF THE ARMY.USACE.NEW ORLEANS DISTRICT",
        "type": "Solicitation",
        "naicsCode": "541330",
        "responseDeadLine": "2030-06-01T17:00:00-05:00",
        "uiLink": "https://sam.gov/opp/dismissal0test0notice0id000000000/view",
        "placeOfPerformance": {"city": {"name": "New Orleans"}, "state": {"code": "LA"}},
    }
    base.update(overrides)
    return base


NOTICE_ID = "dismissal0test0notice0id000000000"[:32]  # 32-char SAM noticeId shape


def _run_sam_sync(db, monkeypatch):
    monkeypatch.setattr(sam_gov_module.settings, "SAM_GOV_API_KEY", "test-key")
    seed_intelligence_sources(db)
    connector = get_intelligence_connector("sam_gov")
    notice = _sam_notice(noticeId=NOTICE_ID, uiLink=f"https://sam.gov/opp/{NOTICE_ID}/view")
    monkeypatch.setattr(connector, "fetch", lambda since, **filters: [connector._to_raw_intelligence_item(notice, NOW)])
    source = db.execute(select(IntelligenceSource).where(IntelligenceSource.name == "SAM.gov")).scalars().one()
    return run_sync(db, source, SyncTriggeredBy.MANUAL), source


def test_dismissal_survives_a_resync_of_the_same_item(db, monkeypatch):
    run_sync_result, source = _run_sam_sync(db, monkeypatch)
    assert run_sync_result.status == SyncRunStatus.SUCCESS

    item = db.execute(select(IntelligenceItem).where(IntelligenceItem.external_id == NOTICE_ID)).scalars().one()
    opportunity_id = item.opportunity_id
    assert opportunity_id is not None  # promoted by the first sync, as normal

    # Untrack it (simulating a human rejecting/never-tracking scenario isn't needed
    # here — dismissal.py's own guard is tested above; this test is specifically about
    # a resync not undoing a dismissal that was valid when it happened) so Dismiss is
    # actually possible, then dismiss it and resync again.
    item.opportunity_id = None
    db.commit()
    dismiss_item(db, item, TEST_USER_ID, DismissalReason.NOT_PURSUING)

    connector = get_intelligence_connector("sam_gov")
    notice = _sam_notice(noticeId=NOTICE_ID, uiLink=f"https://sam.gov/opp/{NOTICE_ID}/view")
    monkeypatch.setattr(connector, "fetch", lambda since, **filters: [connector._to_raw_intelligence_item(notice, NOW)])
    second_run = run_sync(db, source, SyncTriggeredBy.MANUAL)

    assert second_run.status == SyncRunStatus.SUCCESS
    db.refresh(item)
    assert item.is_dismissed is True  # resync never cleared it
    assert item.opportunity_id is None  # and never silently re-promoted it either


def test_sam_apex_duplicate_cluster_stays_suppressed_across_sources(db, monkeypatch):
    # The scenario named explicitly: dismiss SAM's copy, then a LATER APEX sync
    # surfaces the same procurement (matched via the canonical source_url) — the APEX
    # copy must come in already suppressed, not reappear as a "new" item.
    monkeypatch.setattr(sam_gov_module.settings, "SAM_GOV_API_KEY", "test-key")
    seed_intelligence_sources(db)
    sam_source = db.execute(select(IntelligenceSource).where(IntelligenceSource.name == "SAM.gov")).scalars().one()
    apex_source = db.execute(select(IntelligenceSource).where(IntelligenceSource.name == "APEX MyBidMatch")).scalars().one()

    sam_connector = get_intelligence_connector("sam_gov")
    notice = _sam_notice(noticeId=NOTICE_ID, uiLink=f"https://sam.gov/opp/{NOTICE_ID}/view")
    monkeypatch.setattr(sam_connector, "fetch", lambda since, **filters: [sam_connector._to_raw_intelligence_item(notice, NOW)])
    run_sync(db, sam_source, SyncTriggeredBy.MANUAL)

    sam_item = db.execute(select(IntelligenceItem).where(IntelligenceItem.external_id == NOTICE_ID)).scalars().one()
    sam_item.opportunity_id = None  # untrack so it's dismissable (see test above)
    db.commit()
    dismiss_item(db, sam_item, TEST_USER_ID)

    apex_connector = get_intelligence_connector("web_apex_mybidmatch")
    apex_candidate = {
        "title": "Levee Rehabilitation Design — see SAM.gov notice",
        "detail_url": f"https://sam.gov/opp/{NOTICE_ID}/view",
        "row_text": "APEX MyBidMatch listing referencing the same SAM.gov notice",
        "cells": ["1", "SAM.gov", "USACE New Orleans District", "Y1ZZ"],
    }
    monkeypatch.setattr(apex_connector, "fetch", lambda since, **filters: [apex_to_raw_item(apex_candidate, NOW)])
    apex_run = run_sync(db, apex_source, SyncTriggeredBy.MANUAL)

    assert apex_run.status == SyncRunStatus.SUCCESS
    apex_item = db.execute(
        select(IntelligenceItem).where(IntelligenceItem.intelligence_source_id == apex_source.id)
    ).scalars().one()
    assert apex_item.project_cluster_id == sam_item.project_cluster_id  # clustered via source_url, unchanged dedup.py logic
    assert apex_item.is_dismissed is True  # inherited immediately, not just via the cluster-join at read time
    assert apex_item.opportunity_id is None  # never silently promoted despite matching a would-be-promotable cluster


# --- Route-level: Dismissed view, Restore, default-feed exclusion, 409 on tracked ---

def test_dismiss_route_hides_item_from_default_discover_view(client, db):
    source = _source(db)
    item = _item(db, source, external_id="A", title="Hide me")
    db.commit()

    before = client.get("/api/intelligence/items", params={"source_id": str(source.id)}).json()
    assert len(before) == 1

    resp = client.post(f"/api/intelligence/items/{item.id}/dismiss", json={"reason": "too_small"})
    assert resp.status_code == 200
    assert resp.json()["is_dismissed"] is True

    after = client.get("/api/intelligence/items", params={"source_id": str(source.id)}).json()
    assert after == []


def test_dismiss_route_rejects_tracked_item_with_409_and_keeps_opportunity(client, db):
    source = _source(db)
    opp = Opportunity(title="Active pursuit")
    db.add(opp)
    db.flush()
    item = _item(db, source, external_id="A", opportunity_id=opp.id)
    db.commit()

    resp = client.post(f"/api/intelligence/items/{item.id}/dismiss", json={})

    assert resp.status_code == 409
    assert db.get(Opportunity, opp.id) is not None  # never deleted
    db.refresh(item)
    assert item.is_dismissed is False


def test_dismissed_view_shows_only_dismissed_items_and_active_view_excludes_them(client, db):
    source = _source(db)
    dismissed = _item(db, source, external_id="A", title="Dismissed one")
    active = _item(db, source, external_id="B", title="Still active")
    db.commit()
    client.post(f"/api/intelligence/items/{dismissed.id}/dismiss", json={})

    dismissed_view = client.get(
        "/api/intelligence/items", params={"source_id": str(source.id), "view": "dismissed"}
    ).json()
    active_view = client.get(
        "/api/intelligence/items", params={"source_id": str(source.id), "view": "active"}
    ).json()

    assert [i["title"] for i in dismissed_view] == ["Dismissed one"]
    assert [i["title"] for i in active_view] == ["Still active"]


def test_restore_route_returns_item_to_default_discover_view(client, db):
    source = _source(db)
    item = _item(db, source, external_id="A")
    db.commit()
    client.post(f"/api/intelligence/items/{item.id}/dismiss", json={})
    assert client.get("/api/intelligence/items", params={"source_id": str(source.id)}).json() == []

    resp = client.post(f"/api/intelligence/items/{item.id}/restore")

    assert resp.status_code == 200
    assert resp.json()["is_dismissed"] is False
    restored = client.get("/api/intelligence/items", params={"source_id": str(source.id)}).json()
    assert [i["title"] for i in restored] == [item.title]


def test_dismiss_route_404s_for_an_unknown_item(client, db):
    import uuid
    resp = client.post(f"/api/intelligence/items/{uuid.uuid4()}/dismiss", json={})
    assert resp.status_code == 404


def test_tracked_item_is_never_hidden_by_a_dismissed_cluster_sibling(client, db):
    source = _source(db)
    cluster = ProjectCluster(representative_title="Same procurement")
    db.add(cluster)
    db.flush()
    opp = Opportunity(title="Active pursuit")
    db.add(opp)
    db.flush()
    tracked = _item(db, source, external_id="A", title="Tracked copy", project_cluster_id=cluster.id, opportunity_id=opp.id)
    untracked = _item(db, source, external_id="B", title="Untracked copy", project_cluster_id=cluster.id)
    db.commit()

    client.post(f"/api/intelligence/items/{untracked.id}/dismiss", json={})

    active_view = client.get("/api/intelligence/items", params={"source_id": str(source.id)}).json()
    assert [i["title"] for i in active_view] == ["Tracked copy"]
