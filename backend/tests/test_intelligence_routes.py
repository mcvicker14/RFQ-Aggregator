from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.connectors import registry
from app.connectors.base import IntelligenceConnector, RawIntelligenceItem
from app.core.deps import get_current_user
from app.db.session import get_db
from app.main import app
from app.models.enums import ConnectorType, IntelligenceCategory, JurisdictionLevel, UserRole
from app.models.intelligence import IntelligenceSource
from app.models.user import User

NOW = datetime.now(timezone.utc)


class FakeConnector(IntelligenceConnector):
    key = "route_test_source"
    name = "Route Test Source"
    default_category = IntelligenceCategory.LIVE_OPPORTUNITY

    def is_configured(self) -> bool:
        return True

    def fetch(self, since, **filters):
        return [RawIntelligenceItem(
            external_id="RT-1", intelligence_category=IntelligenceCategory.LIVE_OPPORTUNITY,
            source_url=None, retrieved_at=NOW, fields={"title": "Route Test Item"},
        )]


@pytest.fixture()
def client(db):
    def _fake_user(role):
        def _dep():
            return User(id=None, email="test@example.com", full_name="Test", hashed_password="x", role=role, is_active=True)
        return _dep

    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = _fake_user(UserRole.ADMINISTRATOR)
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


@pytest.fixture()
def fake_connector():
    registry._INTELLIGENCE_CONNECTORS["route_test_source"] = FakeConnector()
    yield
    registry._INTELLIGENCE_CONNECTORS.pop("route_test_source", None)


def _source(db, **overrides):
    defaults = dict(
        name="Route Test Source", jurisdiction_level=JurisdictionLevel.FEDERAL,
        connector_type=ConnectorType.API, connector_key="route_test_source", is_enabled=True,
    )
    defaults.update(overrides)
    src = IntelligenceSource(**defaults)
    db.add(src)
    db.flush()
    return src


def test_list_sources_serializes_correctly(client, db):
    _source(db)
    db.commit()

    response = client.get("/api/intelligence/sources")

    assert response.status_code == 200
    body = response.json()
    assert any(s["name"] == "Route Test Source" for s in body)
    row = next(s for s in body if s["name"] == "Route Test Source")
    assert row["jurisdiction_level"] == "federal"
    assert row["connector_type"] == "api"
    assert row["health_status"] == "never_run"


def test_update_source_toggles_enabled(client, db):
    source = _source(db, is_enabled=False)
    db.commit()

    response = client.patch(f"/api/intelligence/sources/{source.id}", json={"is_enabled": True})

    assert response.status_code == 200
    assert response.json()["is_enabled"] is True


def test_sync_source_endpoint_runs_and_returns_run(client, db, fake_connector):
    source = _source(db)
    db.commit()

    response = client.post(f"/api/intelligence/sources/{source.id}/sync")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "success"
    assert body["items_created"] == 1


def test_sync_source_without_connector_returns_400(client, db):
    source = _source(db, connector_key=None, connector_type=ConnectorType.MANUAL)
    db.commit()

    response = client.post(f"/api/intelligence/sources/{source.id}/sync")

    assert response.status_code == 400


def test_sync_source_missing_returns_404(client, db):
    import uuid
    response = client.post(f"/api/intelligence/sources/{uuid.uuid4()}/sync")
    assert response.status_code == 404


def test_sync_all_endpoint_reports_results(client, db, fake_connector):
    # Disable every other enabled+connected source first (within this test's own
    # transaction, rolled back after) so this assertion holds regardless of what the
    # Source Registry seed has already committed to the shared local database — e.g.
    # SAM.gov is enabled by seed_intelligence_sources but has no connector registered
    # in this test process, which would otherwise show up as a second attempted source.
    for other in db.execute(
        select(IntelligenceSource).where(
            IntelligenceSource.is_enabled.is_(True), IntelligenceSource.connector_key.isnot(None)
        )
    ).scalars().all():
        other.is_enabled = False

    _source(db)
    db.commit()

    response = client.post("/api/intelligence/sync-all")

    assert response.status_code == 200
    body = response.json()
    assert body["sources_attempted"] == 1
    assert body["sources_succeeded"] == 1


def test_sync_runs_endpoint_lists_recent_runs(client, db, fake_connector):
    source = _source(db)
    db.commit()
    client.post(f"/api/intelligence/sources/{source.id}/sync")

    response = client.get("/api/intelligence/sync-runs", params={"source_id": str(source.id)})

    assert response.status_code == 200
    assert len(response.json()) == 1
