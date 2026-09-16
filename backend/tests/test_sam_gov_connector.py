"""Fixture-based tests for the SAM.gov connector's mapping logic. This sandbox's
network egress blocks api.sam.gov (and even SAM.gov's own documentation sites), so
these exercise _to_raw_intelligence_item()/_map_notice_type() against realistic
saved-shape payloads rather than a live call — see the module docstring in
app/connectors/sam_gov.py and docs/PHASE2_ARCHITECTURE.md §13 for why, and what to
check (raw_metadata on the resulting rows) after the first real production sync.
"""
from datetime import datetime, timezone

from sqlalchemy import select

from app.connectors.registry import get_intelligence_connector
from app.connectors.sam_gov import SamGovConnector, _map_notice_type
from app.models.enums import IntelligenceCategory, SetAsideType, SourceHealthStatus, SyncRunStatus, SyncTriggeredBy
from app.models.intelligence import IntelligenceSource
from app.services.intelligence_sync import run_sync
from seed.intelligence_sources import seed_intelligence_sources

RETRIEVED_AT = datetime.now(timezone.utc)


def _sam_notice(**overrides) -> dict:
    base = {
        "noticeId": "abc123",
        "title": "Civil Engineering Design Services — Drainage Improvements",
        "solicitationNumber": "W912P8-26-R-0001",
        "fullParentPathName": "DEPT OF DEFENSE.DEPT OF THE ARMY.USACE.NEW ORLEANS DISTRICT",
        "type": "Solicitation",
        "naicsCode": "541330",
        "classificationCode": "C219",
        "typeOfSetAsideDescription": "Total Small Business Set-Aside",
        "responseDeadLine": "2026-11-15T17:00:00-06:00",
        "uiLink": "https://sam.gov/opp/abc123/view",
        "placeOfPerformance": {
            "city": {"name": "New Orleans"},
            "state": {"code": "LA"},
        },
        "officeAddress": {"city": "New Orleans", "state": "LA"},
    }
    base.update(overrides)
    return base


def test_map_notice_type_known_types():
    assert _map_notice_type("Solicitation") == IntelligenceCategory.LIVE_OPPORTUNITY
    assert _map_notice_type("Combined Synopsis/Solicitation") == IntelligenceCategory.LIVE_OPPORTUNITY
    assert _map_notice_type("Presolicitation") == IntelligenceCategory.PRE_SOLICITATION
    assert _map_notice_type("Sources Sought") == IntelligenceCategory.PRE_SOLICITATION
    assert _map_notice_type("Special Notice") == IntelligenceCategory.PRE_SOLICITATION
    assert _map_notice_type("Award Notice") == IntelligenceCategory.AWARD_INTELLIGENCE


def test_map_notice_type_is_case_insensitive():
    assert _map_notice_type("solicitation") == IntelligenceCategory.LIVE_OPPORTUNITY
    assert _map_notice_type("SOURCES SOUGHT") == IntelligenceCategory.PRE_SOLICITATION


def test_map_notice_type_unknown_or_missing_defaults_to_live_opportunity():
    assert _map_notice_type("Some New Notice Type SAM.gov Adds Later") == IntelligenceCategory.LIVE_OPPORTUNITY
    assert _map_notice_type(None) == IntelligenceCategory.LIVE_OPPORTUNITY
    assert _map_notice_type("") == IntelligenceCategory.LIVE_OPPORTUNITY


def test_solicitation_maps_to_live_opportunity_with_full_fields():
    connector = SamGovConnector()
    raw = connector._to_raw_intelligence_item(_sam_notice(), RETRIEVED_AT)

    assert raw.external_id == "abc123"
    assert raw.intelligence_category == IntelligenceCategory.LIVE_OPPORTUNITY
    assert raw.source_url == "https://sam.gov/opp/abc123/view"
    assert raw.fields["title"] == "Civil Engineering Design Services — Drainage Improvements"
    assert raw.fields["solicitation_number"] == "W912P8-26-R-0001"
    assert raw.fields["agency_name"] == "Dept Of Defense"  # first path segment, title-cased
    assert raw.fields["location_city"] == "New Orleans"
    assert raw.fields["location_state"] == "LA"
    assert raw.fields["naics_code"] == "541330"
    assert raw.fields["set_aside"] == SetAsideType.SMALL_BUSINESS
    assert raw.fields["proposal_due_at"] is not None
    assert raw.raw["noticeId"] == "abc123"  # full payload preserved for raw_metadata


def test_presolicitation_maps_to_pre_solicitation():
    connector = SamGovConnector()
    raw = connector._to_raw_intelligence_item(_sam_notice(type="Presolicitation"), RETRIEVED_AT)
    assert raw.intelligence_category == IntelligenceCategory.PRE_SOLICITATION


def test_sources_sought_maps_to_pre_solicitation():
    connector = SamGovConnector()
    raw = connector._to_raw_intelligence_item(_sam_notice(type="Sources Sought"), RETRIEVED_AT)
    assert raw.intelligence_category == IntelligenceCategory.PRE_SOLICITATION


def test_award_notice_maps_to_award_intelligence():
    connector = SamGovConnector()
    raw = connector._to_raw_intelligence_item(_sam_notice(type="Award Notice"), RETRIEVED_AT)
    assert raw.intelligence_category == IntelligenceCategory.AWARD_INTELLIGENCE


def test_missing_optional_fields_do_not_crash_mapping():
    # A minimal, sparse notice — every .get() in the mapper should degrade gracefully
    # rather than raising, matching the "unmapped notices are reported, not fabricated"
    # promise in the connector's module docstring.
    connector = SamGovConnector()
    sparse = {"noticeId": "sparse-1"}

    raw = connector._to_raw_intelligence_item(sparse, RETRIEVED_AT)

    assert raw.external_id == "sparse-1"
    assert raw.fields["title"] == "(untitled SAM.gov notice)"
    assert raw.fields["agency_name"] is None
    assert raw.fields["set_aside"] == SetAsideType.UNRESTRICTED
    assert raw.fields["proposal_due_at"] is None


def test_sam_gov_is_registered_under_its_connector_key():
    # Confirms the real wiring, not a fake — this is the same lookup
    # intelligence_sync.run_sync() performs for any source whose connector_key is
    # "sam_gov" (which seed_intelligence_sources sets on the real "SAM.gov" row).
    connector = get_intelligence_connector("sam_gov")
    assert isinstance(connector, SamGovConnector)


def test_run_sync_against_the_real_seeded_sam_gov_source_without_a_key(db, monkeypatch):
    # End-to-end through the real pipeline (seeded source row -> real registry lookup
    # -> real SamGovConnector), stopping short of an actual HTTP call since no API key
    # is configured in this environment — proving the whole chain is wired correctly
    # without needing the network access this sandbox doesn't have.
    import app.connectors.sam_gov as sam_gov_module
    monkeypatch.setattr(sam_gov_module.settings, "SAM_GOV_API_KEY", None)

    seed_intelligence_sources(db)
    source = db.execute(select(IntelligenceSource).where(IntelligenceSource.name == "SAM.gov")).scalars().one()

    run = run_sync(db, source, SyncTriggeredBy.MANUAL)

    assert run.status == SyncRunStatus.FAILURE
    assert source.health_status == SourceHealthStatus.NEEDS_CONFIGURATION
    assert "not configured" in run.error_detail.lower()


def test_is_configured_reflects_api_key(monkeypatch):
    import app.connectors.sam_gov as sam_gov_module

    connector = SamGovConnector()

    monkeypatch.setattr(sam_gov_module.settings, "SAM_GOV_API_KEY", None)
    assert connector.is_configured() is False

    monkeypatch.setattr(sam_gov_module.settings, "SAM_GOV_API_KEY", "test-key")
    assert connector.is_configured() is True
