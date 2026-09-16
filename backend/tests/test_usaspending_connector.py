"""Fixture-based tests for the USAspending.gov connector. Same rationale as
test_sam_gov_connector.py: this sandbox blocks api.usaspending.gov directly, so these
exercise _to_raw_intelligence_item() against a payload shaped exactly per the fields
confirmed from the official API contract doc in
fedspendingtransparency/usaspending-api (see the module docstring in
app/connectors/usaspending.py for how that was verified) rather than a live call.
"""
from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from app.connectors.registry import get_intelligence_connector
from app.connectors.usaspending import USAspendingConnector, _extract_name
from app.models.enums import IntelligenceCategory, SourceHealthStatus, SyncRunStatus, SyncTriggeredBy
from app.models.intelligence import IntelligenceItem, IntelligenceSource
from app.services.intelligence_sync import run_sync
from seed.intelligence_sources import seed_intelligence_sources

RETRIEVED_AT = datetime.now(timezone.utc)


def _award(**overrides) -> dict:
    base = {
        "internal_id": 987654,
        "generated_internal_id": "CONT_AWD_W912P826D0007_9700",
        "Award ID": "W912P8-26-D-0007",
        "Recipient Name": "ACME ENGINEERING SERVICES LLC",
        "Award Amount": 4250000.00,
        "Description": "IDIQ FOR CIVIL ENGINEERING DESIGN SERVICES, DRAINAGE AND FLOOD CONTROL",
        "Awarding Agency": "Department of Defense",
        "Awarding Sub Agency": "Department of the Army",
        "Period of Performance Start Date": "2026-01-15",
        "Period of Performance Current End Date": "2031-01-14",
        "Place of Performance State Code": "LA",
        "Place of Performance City Code": "NEW ORLEANS",
        "NAICS": "541330",
        "PSC": "C219",
    }
    base.update(overrides)
    return base


def test_maps_award_to_award_intelligence_category():
    connector = USAspendingConnector()
    raw = connector._to_raw_intelligence_item(_award(), RETRIEVED_AT)
    assert raw.intelligence_category == IntelligenceCategory.AWARD_INTELLIGENCE


def test_full_field_mapping():
    connector = USAspendingConnector()
    raw = connector._to_raw_intelligence_item(_award(), RETRIEVED_AT)

    assert raw.external_id == "987654"
    assert raw.source_url == "https://www.usaspending.gov/award/CONT_AWD_W912P826D0007_9700"
    assert raw.fields["title"].startswith("IDIQ FOR CIVIL ENGINEERING")
    assert raw.fields["awardee_name"] == "ACME ENGINEERING SERVICES LLC"
    assert raw.fields["contract_number"] == "W912P8-26-D-0007"
    assert raw.fields["agency_name"] == "Department of Defense"
    assert raw.fields["location_state"] == "LA"
    assert raw.fields["naics_code"] == "541330"
    assert raw.fields["estimated_value_high"] == 4250000.00
    assert raw.fields["posted_at"] is not None
    assert raw.fields["is_prime_award"] is True
    assert raw.raw["internal_id"] == 987654  # full payload preserved for raw_metadata


def test_missing_description_falls_back_to_award_id():
    connector = USAspendingConnector()
    raw = connector._to_raw_intelligence_item(_award(**{"Description": None}), RETRIEVED_AT)
    assert raw.fields["title"] == "W912P8-26-D-0007"


def test_missing_internal_id_raises_so_the_item_is_skipped_not_fabricated():
    connector = USAspendingConnector()
    with pytest.raises(ValueError):
        connector._to_raw_intelligence_item(_award(**{"internal_id": None}), RETRIEVED_AT)


def test_missing_generated_internal_id_leaves_source_url_none():
    connector = USAspendingConnector()
    raw = connector._to_raw_intelligence_item(_award(**{"generated_internal_id": None}), RETRIEVED_AT)
    assert raw.source_url is None


def test_is_always_configured():
    # Keyless public API — never blocked on a missing credential.
    assert USAspendingConnector().is_configured() is True


# --- Nested-object shape: the exact production incident ---------------------------
#
# psycopg.ProgrammingError: cannot adapt type 'dict' using placeholder '%s' happened
# because "Awarding Agency" (and, per the same API pattern, "Recipient Name") comes
# back from the live API as a nested object — not the flat string the field-name-only
# contract read implied. These tests use that real shape, not the flat-string fixture
# default above, to prove the fix actually handles what production sends.

def _nested_agency(name: str, slug: str) -> dict:
    return {"name": name, "agency_slug": slug}


def test_extract_name_handles_nested_agency_object():
    assert _extract_name(_nested_agency("Department of Defense", "department-of-defense")) == "Department of Defense"


def test_extract_name_handles_flat_string():
    assert _extract_name("Department of Defense") == "Department of Defense"


def test_extract_name_handles_none():
    assert _extract_name(None) is None


def test_field_mapping_extracts_scalar_from_nested_awarding_agency():
    connector = USAspendingConnector()
    award = _award(**{"Awarding Agency": _nested_agency("Department of Defense", "department-of-defense")})

    raw = connector._to_raw_intelligence_item(award, RETRIEVED_AT)

    assert raw.fields["agency_name"] == "Department of Defense"
    assert isinstance(raw.fields["agency_name"], str)


def test_field_mapping_extracts_scalar_from_nested_recipient_name():
    connector = USAspendingConnector()
    award = _award(**{"Recipient Name": {"name": "ACME ENGINEERING SERVICES LLC", "recipient_hash": "abc-123"}})

    raw = connector._to_raw_intelligence_item(award, RETRIEVED_AT)

    assert raw.fields["awardee_name"] == "ACME ENGINEERING SERVICES LLC"
    assert isinstance(raw.fields["awardee_name"], str)


def test_field_mapping_survives_full_production_shaped_award():
    """The exact combination that failed in production: nested Awarding Agency and
    Recipient Name alongside the rest of a realistic award. Nothing in raw.fields
    should be a dict/list once mapping is done — that's what intelligence_sync.py's
    _validate_connector_fields() would otherwise reject at sync time."""
    connector = USAspendingConnector()
    award = _award(
        **{
            "Awarding Agency": _nested_agency("Department of Defense", "department-of-defense"),
            "Awarding Sub Agency": _nested_agency("Department of the Army", "department-of-the-army"),
            "Recipient Name": {"name": "ACME ENGINEERING SERVICES LLC", "recipient_hash": "abc-123"},
        }
    )

    raw = connector._to_raw_intelligence_item(award, RETRIEVED_AT)

    for key, value in raw.fields.items():
        assert not isinstance(value, (dict, list)), f"field '{key}' is still a {type(value).__name__}: {value!r}"
    assert raw.fields["agency_name"] == "Department of Defense"
    assert raw.fields["awardee_name"] == "ACME ENGINEERING SERVICES LLC"


# --- End-to-end through the real pipeline ------------------------------------------
#
# Real registered connector + real run_sync(), monkeypatching only the network call
# (connector.fetch), so these prove the whole chain — registry lookup, field mapping,
# _validate_connector_fields(), IntelligenceItem persistence, and re-sync/upsert — the
# same way test_sam_gov_connector.py's end-to-end test does.

def _seeded_usaspending_source(db) -> IntelligenceSource:
    seed_intelligence_sources(db)
    return db.execute(select(IntelligenceSource).where(IntelligenceSource.name == "USAspending.gov")).scalars().one()


def test_run_sync_persists_production_shaped_award_end_to_end(db, monkeypatch):
    connector = get_intelligence_connector("usaspending")
    assert isinstance(connector, USAspendingConnector)
    award = _award(
        **{
            "Awarding Agency": _nested_agency("Department of Defense", "department-of-defense"),
            "Recipient Name": {"name": "ACME ENGINEERING SERVICES LLC", "recipient_hash": "abc-123"},
        }
    )
    monkeypatch.setattr(connector, "fetch", lambda since, **filters: [connector._to_raw_intelligence_item(award, RETRIEVED_AT)])

    source = _seeded_usaspending_source(db)
    run = run_sync(db, source, SyncTriggeredBy.MANUAL)

    assert run.status == SyncRunStatus.SUCCESS
    assert run.items_fetched == 1
    assert run.items_created == 1
    assert run.items_errored == 0
    assert source.health_status == SourceHealthStatus.HEALTHY

    item = db.execute(select(IntelligenceItem).where(IntelligenceItem.external_id == "987654")).scalars().one()
    assert item.agency_name == "Department of Defense"
    assert item.awardee_name == "ACME ENGINEERING SERVICES LLC"
    assert item.intelligence_category == IntelligenceCategory.AWARD_INTELLIGENCE
    assert item.opportunity_id is None  # AWARD_INTELLIGENCE never promotes


def test_run_sync_processing_same_award_twice_updates_not_duplicates(db, monkeypatch):
    connector = get_intelligence_connector("usaspending")
    award = _award(**{"Awarding Agency": _nested_agency("Department of Defense", "department-of-defense")})
    monkeypatch.setattr(connector, "fetch", lambda since, **filters: [connector._to_raw_intelligence_item(award, RETRIEVED_AT)])

    source = _seeded_usaspending_source(db)
    run1 = run_sync(db, source, SyncTriggeredBy.MANUAL)
    assert run1.items_created == 1
    assert run1.items_updated == 0

    run2 = run_sync(db, source, SyncTriggeredBy.MANUAL)
    assert run2.items_created == 0
    assert run2.items_updated == 1

    rows = db.execute(select(IntelligenceItem).where(IntelligenceItem.external_id == "987654")).scalars().all()
    assert len(rows) == 1


def test_run_sync_with_updated_amount_reflects_latest_value_on_resync(db, monkeypatch):
    connector = get_intelligence_connector("usaspending")
    source = _seeded_usaspending_source(db)

    award_v1 = _award(**{"Award Amount": 4250000.00})
    monkeypatch.setattr(connector, "fetch", lambda since, **filters: [connector._to_raw_intelligence_item(award_v1, RETRIEVED_AT)])
    run_sync(db, source, SyncTriggeredBy.MANUAL)

    award_v2 = _award(**{"Award Amount": 4750000.00})
    monkeypatch.setattr(connector, "fetch", lambda since, **filters: [connector._to_raw_intelligence_item(award_v2, RETRIEVED_AT)])
    run_sync(db, source, SyncTriggeredBy.MANUAL)

    item = db.execute(select(IntelligenceItem).where(IntelligenceItem.external_id == "987654")).scalars().one()
    assert float(item.estimated_value_high) == 4750000.00
