"""Fixture-based tests for the Grants.gov connector. As documented in
app/connectors/grants_gov.py's module docstring, this sandbox blocks every source
tried for this API's exact field names, so the mapping is deliberately defensive
(_first_present tries multiple candidate field-name spellings). These tests exercise
both candidate shapes to prove that defensiveness actually works, not just one
assumed-correct shape.
"""
from datetime import datetime, timezone

import pytest

from app.connectors.grants_gov import GrantsGovConnector
from app.models.enums import IntelligenceCategory

RETRIEVED_AT = datetime.now(timezone.utc)


def test_maps_relevant_opportunity_shape_a():
    # "id"/"title"/"openDate" style, as reported by one integration.
    connector = GrantsGovConnector()
    item = {
        "id": 355123,
        "number": "EPA-R6-WATER-2026-001",
        "title": "Clean Water State Revolving Fund Capitalization Grants",
        "agencyName": "Environmental Protection Agency",
        "openDate": "01/15/2026",
        "closeDate": "04/15/2026",
        "estimatedFunding": "50000000",
    }

    raw = connector._to_raw_intelligence_item(item, RETRIEVED_AT)

    assert raw is not None
    assert raw.external_id == "355123"
    assert raw.intelligence_category == IntelligenceCategory.EARLY_SIGNAL
    assert raw.fields["title"] == "Clean Water State Revolving Fund Capitalization Grants"
    assert raw.fields["agency_name"] == "Environmental Protection Agency"
    assert raw.fields["funding_award_number"] == "EPA-R6-WATER-2026-001"
    assert raw.fields["proposal_due_at"] is not None
    assert raw.fields["posted_at"] is not None
    assert raw.fields["funding_amount"] == 50000000.0
    assert raw.source_url == "https://www.grants.gov/search-results-detail/355123"


def test_maps_relevant_opportunity_shape_b():
    # "opportunityId"/"opportunityTitle"/"postDate" style, as reported by another.
    connector = GrantsGovConnector()
    item = {
        "opportunityId": 987001,
        "opportunityNumber": "FEMA-HMGP-2026",
        "opportunityTitle": "Hazard Mitigation Grant Program — Flood Resilience",
        "agencyName": "Federal Emergency Management Agency",
        "postDate": "2026-02-01",
        "closeDate": "2026-05-01",
        "awardCeiling": "2000000",
    }

    raw = connector._to_raw_intelligence_item(item, RETRIEVED_AT)

    assert raw is not None
    assert raw.external_id == "987001"
    assert raw.fields["funding_award_number"] == "FEMA-HMGP-2026"
    assert raw.fields["funding_amount"] == 2000000.0


def test_topically_irrelevant_opportunity_is_still_persisted_not_filtered():
    # Production incident: _is_relevant() used to drop anything off-topic before
    # persistence — the same mistake round 1 of the SAM.gov fix made. Removed:
    # relevance is now decided entirely by grants_relevance_scoring.py, after
    # persistence, so nothing is silently lost. See module docstring.
    connector = GrantsGovConnector()
    item = {
        "id": 1,
        "title": "National Endowment for the Arts Literature Fellowships",
        "agencyName": "National Endowment for the Arts",
    }

    raw = connector._to_raw_intelligence_item(item, RETRIEVED_AT)

    assert raw is not None
    assert raw.fields["title"] == "National Endowment for the Arts Literature Fellowships"


def test_synopsis_and_eligible_applicants_are_folded_into_description():
    connector = GrantsGovConnector()
    item = {
        "id": 2, "title": "Clean Water State Revolving Fund", "agencyName": "Environmental Protection Agency",
        "description": "Provides capitalization grants for water infrastructure projects.",
        "eligibleApplicants": "State governments; special district governments",
    }
    raw = connector._to_raw_intelligence_item(item, RETRIEVED_AT)
    assert "water infrastructure" in raw.fields["description"]
    assert "special district governments" in raw.fields["description"]


def test_missing_description_and_eligibility_leaves_description_none():
    connector = GrantsGovConnector()
    item = {"id": 3, "title": "FY26 Formula Allocation", "agencyName": "Federal Highway Administration"}
    raw = connector._to_raw_intelligence_item(item, RETRIEVED_AT)
    assert raw.fields["description"] is None


def test_missing_id_raises_so_the_item_is_skipped_not_fabricated():
    connector = GrantsGovConnector()
    with pytest.raises(ValueError):
        connector._to_raw_intelligence_item({"title": "Water Infrastructure Grant"}, RETRIEVED_AT)


def test_is_always_configured():
    assert GrantsGovConnector().is_configured() is True
