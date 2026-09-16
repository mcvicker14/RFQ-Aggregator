"""Tests for Discover's "Track Opportunity" action: creating an Opportunity with
source_intelligence_item_id set must stamp that same IntelligenceItem.opportunity_id --
the one field Discover reads to decide whether to show "Tracked" instead of offering to
create a duplicate. See app/schemas/opportunity.py::OpportunityCreate and
app/services/opportunities.py::create_opportunity().
"""
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.core.deps import get_current_user
from app.db.session import get_db
from app.main import app
from app.models.enums import ConnectorType, IntelligenceCategory, JurisdictionLevel, UserRole
from app.models.intelligence import IntelligenceItem, IntelligenceSource
from app.models.user import User
from app.schemas.opportunity import OpportunityCreate
from app.services import opportunities as opportunities_service

NOW = datetime.now(timezone.utc)


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


def _source(db, **overrides):
    defaults = dict(name="Track Test Source", jurisdiction_level=JurisdictionLevel.FEDERAL, connector_type=ConnectorType.API)
    defaults.update(overrides)
    src = IntelligenceSource(**defaults)
    db.add(src)
    db.flush()
    return src


def _item(db, source, **overrides):
    defaults = dict(
        intelligence_source_id=source.id, external_id=overrides.pop("external_id", "TRACK-X"),
        title="Test Item", intelligence_category=IntelligenceCategory.EARLY_SIGNAL,
        source=source.name, retrieved_at=NOW,
    )
    defaults.update(overrides)
    item = IntelligenceItem(**defaults)
    db.add(item)
    db.flush()
    return item


def test_create_opportunity_service_stamps_source_item(db):
    user = db.query(User).first()
    source = _source(db)
    item = _item(db, source, title="Watershed study early signal")
    db.commit()
    assert item.opportunity_id is None

    payload = OpportunityCreate(title=item.title, source_intelligence_item_id=item.id)
    opp = opportunities_service.create_opportunity(db, payload, user)

    db.refresh(item)
    assert item.opportunity_id == opp.id


def test_create_opportunity_without_source_item_id_is_unaffected(db):
    # Every existing caller (the plain "New Opportunity" dialog) never sends this field
    # -- confirms the new optional field changes nothing when absent.
    user = db.query(User).first()
    payload = OpportunityCreate(title="Manually entered opportunity")
    opp = opportunities_service.create_opportunity(db, payload, user)
    assert opp.title == "Manually entered opportunity"


def test_create_opportunity_route_accepts_source_item_id_and_links_it(client, db):
    source = _source(db)
    item = _item(db, source, title="Route-level track test")
    db.commit()

    response = client.post(
        "/api/opportunities",
        json={"title": item.title, "source_intelligence_item_id": str(item.id)},
    )

    assert response.status_code == 201
    opp_id = response.json()["id"]
    db.refresh(item)
    assert str(item.opportunity_id) == opp_id


def test_tracked_item_is_not_offered_as_duplicate_by_the_items_list(client, db):
    # Mirrors exactly what Discover checks client-side (item.opportunity_id truthy ->
    # render "Tracked" instead of a "Track Opportunity" button).
    source = _source(db)
    item = _item(db, source, title="Duplicate guard check")
    db.commit()

    before = client.get("/api/intelligence/items", params={"source_id": str(source.id)}).json()
    assert before[0]["opportunity_id"] is None

    client.post("/api/opportunities", json={"title": item.title, "source_intelligence_item_id": str(item.id)})

    after = client.get("/api/intelligence/items", params={"source_id": str(source.id)}).json()
    assert after[0]["opportunity_id"] is not None


def test_unknown_source_item_id_does_not_fail_opportunity_creation(client, db):
    # A stale/invalid id (item deleted between page load and click, say) must never
    # take down opportunity creation -- it's a best-effort back-link, not a hard FK.
    import uuid

    response = client.post(
        "/api/opportunities",
        json={"title": "Created despite bogus link", "source_intelligence_item_id": str(uuid.uuid4())},
    )
    assert response.status_code == 201
