"""Fixture-based tests for the USAspending.gov connector. Same rationale as
test_sam_gov_connector.py: this sandbox blocks api.usaspending.gov directly, so these
exercise _to_raw_intelligence_item() against a payload shaped exactly per the fields
confirmed from the official API contract doc in
fedspendingtransparency/usaspending-api (see the module docstring in
app/connectors/usaspending.py for how that was verified) rather than a live call.
"""
from datetime import datetime, timezone

import pytest

from app.connectors.usaspending import USAspendingConnector
from app.models.enums import IntelligenceCategory

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
