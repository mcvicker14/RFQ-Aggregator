from datetime import datetime, timedelta, timezone

from app.connectors import registry
from app.connectors.base import IntelligenceConnector, RawIntelligenceItem
from app.models.enums import (
    ConnectorType,
    IntelligenceCategory,
    JurisdictionLevel,
    MaturityStage,
    SyncTriggeredBy,
)
from app.models.intelligence import IntelligenceItem, IntelligenceSource
from app.services.early_signal_scoring import calculate_early_signal_score
from app.services.intelligence_sync import run_sync

NOW = datetime.now(timezone.utc)


def _source(db, **overrides):
    defaults = dict(
        name="Test Federal Source", jurisdiction_level=JurisdictionLevel.FEDERAL, connector_type=ConnectorType.API,
    )
    defaults.update(overrides)
    src = IntelligenceSource(**defaults)
    db.add(src)
    db.flush()
    return src


def _item(db, source, **overrides):
    defaults = dict(
        intelligence_source_id=source.id, external_id="EARLY-1", title="Watershed Flood Mitigation Program",
        intelligence_category=IntelligenceCategory.EARLY_SIGNAL, source=source.name, retrieved_at=NOW,
    )
    defaults.update(overrides)
    item = IntelligenceItem(**defaults)
    db.add(item)
    db.flush()
    return item


def test_non_early_signal_item_is_not_scored(db):
    source = _source(db)
    item = _item(db, source, intelligence_category=IntelligenceCategory.LIVE_OPPORTUNITY)

    calculate_early_signal_score(db, item)

    assert item.early_signal_score is None
    assert item.early_signal_score_rationale is None


def test_strong_signal_scores_high(db):
    source = _source(db, jurisdiction_level=JurisdictionLevel.FEDERAL, connector_type=ConnectorType.API)
    item = _item(
        db, source,
        funding_amount=5_000_000,
        maturity_stage=MaturityStage.PROCUREMENT_FORECAST,
        location_city="Slidell", location_state="LA",
        description="A" * 300,
        agency_name="FEMA",
        proposal_due_at=NOW + timedelta(days=20),
        posted_at=NOW - timedelta(days=5),
    )

    calculate_early_signal_score(db, item)

    assert item.early_signal_score is not None
    assert item.early_signal_score >= 70
    assert item.early_signal_score_rationale["band"] == "high"
    assert "disclaimer" in item.early_signal_score_rationale
    assert "not a certainty" in item.early_signal_score_rationale["disclaimer"]


def test_weak_signal_scores_low(db):
    source = _source(db, jurisdiction_level=JurisdictionLevel.LOCAL, connector_type=ConnectorType.MANUAL)
    item = _item(db, source, maturity_stage=MaturityStage.RUMORED_CONCEPTUAL)

    calculate_early_signal_score(db, item)

    assert item.early_signal_score is not None
    assert item.early_signal_score < 45
    assert item.early_signal_score_rationale["band"] == "low"


class _FakeSignalConnector(IntelligenceConnector):
    key = "early_signal_test_source"
    name = "Early Signal Test Source"
    default_category = IntelligenceCategory.EARLY_SIGNAL

    def is_configured(self):
        return True

    def fetch(self, since, **filters):
        return [RawIntelligenceItem(
            external_id="ES-1", intelligence_category=IntelligenceCategory.EARLY_SIGNAL,
            source_url=None, retrieved_at=NOW,
            fields={"title": "Regional Watershed Initiative Funding", "funding_amount": 2_000_000},
        )]


def test_wired_into_sync_produces_a_score_for_early_signal_items(db):
    # End-to-end through run_sync, not just the isolated scoring function — proves
    # calculate_early_signal_score is actually called, and called after the item has
    # been persisted (so intelligence_source_id lookups work).
    registry._INTELLIGENCE_CONNECTORS["early_signal_test_source"] = _FakeSignalConnector()
    try:
        source = _source(db, name="Early Signal Test Source", connector_key="early_signal_test_source")
        source.is_enabled = True
        db.flush()

        run_sync(db, source, SyncTriggeredBy.MANUAL)

        item = db.query(IntelligenceItem).filter_by(external_id="ES-1").one()
        assert item.early_signal_score is not None
        assert item.opportunity_id is None  # never promoted
    finally:
        registry._INTELLIGENCE_CONNECTORS.pop("early_signal_test_source", None)
