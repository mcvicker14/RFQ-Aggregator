from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.core.deps import get_current_user
from app.db.session import get_db
from app.main import app
from app.models.enums import ConnectorType, IntelligenceCategory, JurisdictionLevel, UserRole
from app.models.intelligence import IntelligenceItem, IntelligenceSource
from app.models.opportunity import Opportunity
from app.models.user import User

NOW = datetime.now(timezone.utc)


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
    defaults = dict(name="Route Test Items Source", jurisdiction_level=JurisdictionLevel.FEDERAL, connector_type=ConnectorType.API)
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


def test_list_filters_by_category(client, db):
    source = _source(db)
    _item(db, source, external_id="A", intelligence_category=IntelligenceCategory.LIVE_OPPORTUNITY, title="Live one")
    _item(db, source, external_id="B", intelligence_category=IntelligenceCategory.EARLY_SIGNAL, title="Signal one")
    db.commit()

    response = client.get("/api/intelligence/items", params={"category": "early_signal", "source_id": str(source.id)})

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["title"] == "Signal one"


def test_list_search_matches_title(client, db):
    source = _source(db)
    _item(db, source, external_id="A", title="Drainage Improvements Phase 1")
    _item(db, source, external_id="B", title="Unrelated Roadway Project")
    db.commit()

    response = client.get("/api/intelligence/items", params={"q": "drainage", "source_id": str(source.id)})

    assert response.status_code == 200
    assert len(response.json()) == 1


def test_list_excludes_sample_data_when_requested(client, db):
    source = _source(db)
    _item(db, source, external_id="A", is_sample_data=True, title="Sample item")
    _item(db, source, external_id="B", is_sample_data=False, title="Real item")
    db.commit()

    response = client.get("/api/intelligence/items", params={"include_sample_data": False, "source_id": str(source.id)})

    assert response.status_code == 200
    titles = [i["title"] for i in response.json()]
    assert titles == ["Real item"]


def test_list_sorts_with_nulls_last_regardless_of_direction(client, db):
    source = _source(db)
    _item(db, source, external_id="A", title="No score", early_signal_score=None,
          intelligence_category=IntelligenceCategory.EARLY_SIGNAL)
    _item(db, source, external_id="B", title="High score", early_signal_score=90,
          intelligence_category=IntelligenceCategory.EARLY_SIGNAL)
    _item(db, source, external_id="C", title="Low score", early_signal_score=20,
          intelligence_category=IntelligenceCategory.EARLY_SIGNAL)
    db.commit()

    desc = client.get("/api/intelligence/items", params={"sort_by": "early_signal_score", "sort_dir": "desc", "source_id": str(source.id)})
    asc = client.get("/api/intelligence/items", params={"sort_by": "early_signal_score", "sort_dir": "asc", "source_id": str(source.id)})

    assert [i["title"] for i in desc.json()] == ["High score", "Low score", "No score"]
    assert [i["title"] for i in asc.json()] == ["Low score", "High score", "No score"]


def test_unpromoted_only_filter_excludes_items_linked_to_an_opportunity(client, db):
    existing_opp = db.query(Opportunity).first()  # any seeded sample opportunity
    source = _source(db)
    _item(db, source, external_id="A", title="Promoted", opportunity_id=existing_opp.id)
    _item(db, source, external_id="B", title="Not yet promoted")
    db.commit()

    response = client.get("/api/intelligence/items", params={"unpromoted_only": True, "source_id": str(source.id)})

    assert response.status_code == 200
    titles = [i["title"] for i in response.json()]
    assert titles == ["Not yet promoted"]
