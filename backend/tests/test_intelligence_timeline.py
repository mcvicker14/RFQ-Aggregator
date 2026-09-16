from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.core.deps import get_current_user
from app.db.session import get_db
from app.main import app
from app.models.enums import ConnectorType, IntelligenceCategory, JurisdictionLevel, UserRole
from app.models.intelligence import IntelligenceItem, IntelligenceSource, ProjectCluster
from app.models.opportunity import Opportunity
from app.models.user import User
from app.services.opportunities import get_intelligence_timeline

NOW = datetime.now(timezone.utc)


def _source(db, **overrides):
    defaults = dict(name="Timeline Test Source", jurisdiction_level=JurisdictionLevel.FEDERAL, connector_type=ConnectorType.API)
    defaults.update(overrides)
    src = IntelligenceSource(**defaults)
    db.add(src)
    db.flush()
    return src


def _item(db, source, **overrides):
    defaults = dict(
        intelligence_source_id=source.id, external_id=overrides.pop("external_id", "X"),
        title="Test Item", intelligence_category=IntelligenceCategory.LIVE_OPPORTUNITY,
        source=source.name, retrieved_at=NOW, first_detected_at=NOW, last_seen_at=NOW,
    )
    defaults.update(overrides)
    item = IntelligenceItem(**defaults)
    db.add(item)
    db.flush()
    return item


def test_timeline_includes_directly_promoted_items(db):
    opp = db.query(Opportunity).first()
    source = _source(db)
    _item(db, source, external_id="A", opportunity_id=opp.id)
    _item(db, source, external_id="B", opportunity_id=None)  # unrelated

    timeline = get_intelligence_timeline(db, opp.id)

    assert [i.external_id for i in timeline] == ["A"]


def test_timeline_includes_cluster_mates_even_without_their_own_opportunity_id(db):
    opp = db.query(Opportunity).first()
    cluster = ProjectCluster(representative_title="Shared project")
    db.add(cluster)
    db.flush()
    source = _source(db)
    early_signal = _item(
        db, source, external_id="EARLY", opportunity_id=None, project_cluster_id=cluster.id,
        intelligence_category=IntelligenceCategory.EARLY_SIGNAL, first_detected_at=NOW - timedelta(days=30),
    )
    promoted = _item(
        db, source, external_id="LIVE", opportunity_id=opp.id, project_cluster_id=cluster.id,
        first_detected_at=NOW,
    )
    unrelated = _item(db, source, external_id="UNRELATED", opportunity_id=None)

    timeline = get_intelligence_timeline(db, opp.id)

    external_ids = [i.external_id for i in timeline]
    assert external_ids == ["EARLY", "LIVE"]  # oldest first
    assert "UNRELATED" not in external_ids


def test_timeline_is_empty_for_an_opportunity_with_no_intelligence(db):
    opp = db.query(Opportunity).first()
    assert get_intelligence_timeline(db, opp.id) == []


@pytest.fixture()
def client(db):
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: User(
        id=None, email="test@example.com", full_name="Test", hashed_password="x", role=UserRole.VIEWER, is_active=True
    )
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def test_timeline_route_returns_ordered_items(client, db):
    opp = db.query(Opportunity).first()
    source = _source(db)
    _item(db, source, external_id="A", opportunity_id=opp.id, first_detected_at=NOW)
    db.commit()

    response = client.get(f"/api/opportunities/{opp.id}/intelligence-timeline")

    assert response.status_code == 200
    assert len(response.json()) == 1


def test_timeline_route_404s_for_missing_opportunity(client):
    import uuid
    response = client.get(f"/api/opportunities/{uuid.uuid4()}/intelligence-timeline")
    assert response.status_code == 404
