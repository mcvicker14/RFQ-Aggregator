from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.core.deps import get_current_user
from app.db.session import get_db
from app.main import app
from app.models.enums import ConnectorType, IntelligenceCategory, JurisdictionLevel, UserRole
from app.models.intelligence import IntelligenceItem, IntelligenceSource
from app.models.opportunity import Opportunity
from app.models.scoring import OpportunityScore
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


def test_source_id_filter_shows_only_that_sources_items(client, db):
    source_a = _source(db, name="Source Filter Test A")
    source_b = _source(db, name="Source Filter Test B")
    _item(db, source_a, external_id="A1", title="From source A")
    _item(db, source_b, external_id="B1", title="From source B")
    db.commit()

    response = client.get("/api/intelligence/items", params={"source_id": str(source_a.id)})

    assert [i["title"] for i in response.json()] == ["From source A"]


def test_source_id_filter_combines_with_grants_relevance_tier_and_sort(client, db):
    # Exactly the combination requested: Source = one source, Relevance tier active,
    # sorted by Grant Engineering Relevance Score -- proves the three controls work
    # together rather than fighting each other.
    grants_source = _source(db, name="Source Filter Test Grants")
    other_source = _source(db, name="Source Filter Test Other")
    _item(db, grants_source, external_id="G1", title="Grants high", grants_relevance_score=90,
          intelligence_category=IntelligenceCategory.EARLY_SIGNAL)
    _item(db, grants_source, external_id="G2", title="Grants low", grants_relevance_score=20,
          intelligence_category=IntelligenceCategory.EARLY_SIGNAL)
    # Same high score, but a different source -- must never leak into a source_id-scoped view.
    _item(db, other_source, external_id="O1", title="Other source high", grants_relevance_score=90,
          intelligence_category=IntelligenceCategory.EARLY_SIGNAL)
    db.commit()

    response = client.get(
        "/api/intelligence/items",
        params={
            "source_id": str(grants_source.id), "grants_relevance_tier": "relevant_signal",
            "sort_by": "grants_relevance_score", "sort_dir": "desc",
        },
    )

    assert [i["title"] for i in response.json()] == ["Grants high"]


# --- sam_relevance_tier: the default-view filter -------------------------------------

def test_default_sam_relevance_tier_hides_low_scoring_sam_items(client, db):
    source = _source(db)
    _item(db, source, external_id="A", title="Highly relevant", sam_relevance_score=85)
    _item(db, source, external_id="B", title="Relevant", sam_relevance_score=65)
    _item(db, source, external_id="C", title="Possible match", sam_relevance_score=55)
    _item(db, source, external_id="D", title="Low relevance", sam_relevance_score=20)
    db.commit()

    response = client.get("/api/intelligence/items", params={"source_id": str(source.id)})  # default tier

    titles = {i["title"] for i in response.json()}
    assert titles == {"Highly relevant", "Relevant"}


def test_sam_relevance_tier_never_hides_items_with_no_sam_score(client, db):
    # A non-SAM source (or a SAM item not yet scored) has sam_relevance_score=None —
    # the default filter must never treat that as "hide it," only real sources
    # (currently only SAM.gov) that actually score low should be hidden.
    source = _source(db)
    _item(db, source, external_id="A", title="Unscored item", sam_relevance_score=None)
    db.commit()

    response = client.get("/api/intelligence/items", params={"source_id": str(source.id)})

    assert [i["title"] for i in response.json()] == ["Unscored item"]


def test_sam_relevance_tier_all_shows_everything(client, db):
    source = _source(db)
    _item(db, source, external_id="A", title="Low relevance", sam_relevance_score=5)
    db.commit()

    response = client.get(
        "/api/intelligence/items", params={"source_id": str(source.id), "sam_relevance_tier": "all"}
    )

    assert [i["title"] for i in response.json()] == ["Low relevance"]


def test_sam_relevance_tier_highly_relevant_excludes_merely_relevant(client, db):
    source = _source(db)
    _item(db, source, external_id="A", title="Highly relevant", sam_relevance_score=90)
    _item(db, source, external_id="B", title="Just relevant", sam_relevance_score=70)
    db.commit()

    response = client.get(
        "/api/intelligence/items", params={"source_id": str(source.id), "sam_relevance_tier": "highly_relevant"}
    )

    assert [i["title"] for i in response.json()] == ["Highly relevant"]


def test_sort_by_sam_relevance_score(client, db):
    source = _source(db)
    _item(db, source, external_id="A", title="Mid", sam_relevance_score=70, sam_relevance_rationale={})
    _item(db, source, external_id="B", title="High", sam_relevance_score=95, sam_relevance_rationale={})
    db.commit()

    response = client.get(
        "/api/intelligence/items",
        params={"source_id": str(source.id), "sort_by": "sam_relevance_score", "sam_relevance_tier": "all"},
    )

    assert [i["title"] for i in response.json()] == ["High", "Mid"]


# --- grants_relevance_tier: the default-view filter, independent of the SAM one ----

def test_default_grants_relevance_tier_hides_low_scoring_grants(client, db):
    source = _source(db)
    _item(db, source, external_id="A", title="High value", grants_relevance_score=85)
    _item(db, source, external_id="B", title="Relevant", grants_relevance_score=65)
    _item(db, source, external_id="C", title="Possible", grants_relevance_score=55)
    _item(db, source, external_id="D", title="Low relevance", grants_relevance_score=20)
    db.commit()

    response = client.get("/api/intelligence/items", params={"source_id": str(source.id)})  # default tier

    titles = {i["title"] for i in response.json()}
    assert titles == {"High value", "Relevant"}


def test_grants_relevance_tier_never_hides_items_with_no_grants_score(client, db):
    source = _source(db)
    _item(db, source, external_id="A", title="Unscored item", grants_relevance_score=None)
    db.commit()

    response = client.get("/api/intelligence/items", params={"source_id": str(source.id)})

    assert [i["title"] for i in response.json()] == ["Unscored item"]


def test_grants_relevance_tier_all_shows_everything(client, db):
    source = _source(db)
    _item(db, source, external_id="A", title="Low relevance", grants_relevance_score=5)
    db.commit()

    response = client.get(
        "/api/intelligence/items", params={"source_id": str(source.id), "grants_relevance_tier": "all"}
    )

    assert [i["title"] for i in response.json()] == ["Low relevance"]


def test_sam_and_grants_relevance_filters_are_independent(client, db):
    # A low-scoring SAM item and a low-scoring Grants.gov item in the same query —
    # each filter only ever hides its own source's items.
    source = _source(db)
    _item(db, source, external_id="A", title="Low SAM", sam_relevance_score=10)
    _item(db, source, external_id="B", title="Low Grants", grants_relevance_score=10)
    _item(db, source, external_id="C", title="Neither scored", intelligence_category=IntelligenceCategory.EARLY_SIGNAL)
    db.commit()

    response = client.get("/api/intelligence/items", params={"source_id": str(source.id)})  # both defaults

    assert [i["title"] for i in response.json()] == ["Neither scored"]


def test_sort_by_grants_relevance_score(client, db):
    source = _source(db)
    _item(db, source, external_id="A", title="Mid", grants_relevance_score=70, grants_relevance_rationale={})
    _item(db, source, external_id="B", title="High", grants_relevance_score=95, grants_relevance_rationale={})
    db.commit()

    response = client.get(
        "/api/intelligence/items",
        params={"source_id": str(source.id), "sort_by": "grants_relevance_score", "grants_relevance_tier": "all"},
    )

    assert [i["title"] for i in response.json()] == ["High", "Mid"]


def test_grants_relevance_score_and_early_signal_score_are_distinct_fields(client, db):
    # Locks in the data contract Discover's UI fix depends on: a Grants.gov item
    # carries grants_relevance_score ("could this plausibly lead to engineering work")
    # and early_signal_score ("how mature/actionable is this signal") as two separate,
    # independently valued response fields -- never aliased to each other, and each
    # returned even when they happen to differ, so the frontend can label and display
    # both distinctly instead of a user mistaking one score for the other.
    source = _source(db)
    _item(
        db, source, external_id="A", title="Distinct scores",
        intelligence_category=IntelligenceCategory.EARLY_SIGNAL,
        grants_relevance_score=81, grants_relevance_rationale={}, early_signal_score=64,
    )
    db.commit()

    response = client.get(
        "/api/intelligence/items",
        params={"source_id": str(source.id), "grants_relevance_tier": "all"},
    )

    body = response.json()[0]
    assert body["grants_relevance_score"] == 81
    assert body["early_signal_score"] == 64
    assert body["grants_relevance_score"] != body["early_signal_score"]


def test_source_id_filter_combines_with_grants_relevance_tier_sort_and_ascending_direction(client, db):
    # Complements test_source_id_filter_combines_with_grants_relevance_tier_and_sort
    # (which only checks descending) -- proves sort_dir genuinely drives the ordering
    # by Grant Engineering Relevance Score rather than coincidentally matching
    # insertion order, the same causal check used to verify the Discover UI fix live.
    source = _source(db)
    _item(db, source, external_id="A", title="High", grants_relevance_score=90,
          intelligence_category=IntelligenceCategory.EARLY_SIGNAL)
    _item(db, source, external_id="B", title="Mid", grants_relevance_score=70,
          intelligence_category=IntelligenceCategory.EARLY_SIGNAL)
    db.commit()

    desc = client.get(
        "/api/intelligence/items",
        params={
            "source_id": str(source.id), "grants_relevance_tier": "relevant_signal",
            "sort_by": "grants_relevance_score", "sort_dir": "desc",
        },
    )
    asc = client.get(
        "/api/intelligence/items",
        params={
            "source_id": str(source.id), "grants_relevance_tier": "relevant_signal",
            "sort_by": "grants_relevance_score", "sort_dir": "asc",
        },
    )

    assert [i["title"] for i in desc.json()] == ["High", "Mid"]
    assert [i["title"] for i in asc.json()] == ["Mid", "High"]


# --- pursuit_score: joined from the latest OpportunityScore, not an IntelligenceItem column --

def _score_opportunity(db, opportunity_id, score, computed_at):
    db.add(OpportunityScore(
        opportunity_id=opportunity_id, score=score, band="high" if score >= 75 else "medium",
        category_scores={}, category_rationale={}, why_it_scores_highly="x", primary_concern="y",
        computed_at=computed_at,
    ))


def test_sort_by_pursuit_score_uses_the_latest_score_per_opportunity(client, db):
    opp = db.query(Opportunity).first()
    source = _source(db)
    promoted = _item(db, source, external_id="A", title="Promoted, well-scored", opportunity_id=opp.id)
    _item(db, source, external_id="B", title="Never promoted")
    # Two scores for the same opportunity, at different times — only the latest counts.
    _score_opportunity(db, opp.id, score=40, computed_at=NOW - timedelta(days=5))
    _score_opportunity(db, opp.id, score=91, computed_at=NOW)
    db.commit()

    response = client.get(
        "/api/intelligence/items", params={"source_id": str(source.id), "sort_by": "pursuit_score"}
    )

    body = response.json()
    assert [i["title"] for i in body] == ["Promoted, well-scored", "Never promoted"]  # NULLs last
    by_title = {i["title"]: i["pursuit_score"] for i in body}
    assert by_title["Promoted, well-scored"] == 91  # the later score, not the earlier 40
    assert by_title["Never promoted"] is None


def test_pursuit_score_is_populated_regardless_of_sort_by(client, db):
    opp = db.query(Opportunity).first()
    source = _source(db)
    _item(db, source, external_id="A", title="Promoted", opportunity_id=opp.id)
    _score_opportunity(db, opp.id, score=77, computed_at=NOW)
    db.commit()

    response = client.get("/api/intelligence/items", params={"source_id": str(source.id)})  # default sort

    assert response.json()[0]["pursuit_score"] == 77
