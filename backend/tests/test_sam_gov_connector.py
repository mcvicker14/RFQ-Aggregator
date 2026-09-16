"""Fixture-based tests for the SAM.gov connector's mapping logic. This sandbox's
network egress blocks api.sam.gov (and even SAM.gov's own documentation sites), so
these exercise _to_raw_intelligence_item()/_map_notice_type() against realistic
saved-shape payloads rather than a live call — see the module docstring in
app/connectors/sam_gov.py and docs/PHASE2_ARCHITECTURE.md §13 for why, and what to
check (raw_metadata on the resulting rows) after the first real production sync.
"""
from datetime import date, datetime, timedelta, timezone

import httpx
from sqlalchemy import select

import app.connectors.sam_gov as sam_gov_module
from app.connectors.base import RawIntelligenceItem
from app.connectors.registry import get_intelligence_connector
from app.connectors.sam_gov import (
    MIN_RELEVANCE_SCORE,
    SamGovConnector,
    _extract_place_of_performance,
    _is_expired_opportunity,
    _map_notice_type,
    _score_relevance,
)
from app.models.enums import IntelligenceCategory, SetAsideType, SourceHealthStatus, SyncRunStatus, SyncTriggeredBy
from app.models.intelligence import IntelligenceItem, IntelligenceSource
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


# --- Stage 2: relevance scoring -----------------------------------------------------
#
# Diagnosed production incident: a healthy, connected SAM.gov source returned 0 items
# on manual sync. Root cause was an overly narrow Stage 1 query (exact NAICS codes,
# no notice-type breadth), not a broken integration — see the module docstring for the
# full investigation. These tests cover the redesign: a broader Stage 1 query plus
# Stage 2 relevance ranking/filtering so "broader" doesn't mean "flooded with noise."

def test_score_relevance_strong_match_scores_high():
    notice = _sam_notice(
        title="Water Main and Sewer Main Replacement — Civil Engineering Design Services",
        fullParentPathName="DEPT OF VETERANS AFFAIRS.VISN 16",
        naicsCode="541330",
        typeOfSetAsideDescription="Service-Disabled Veteran-Owned Small Business (SDVOSB) Set-Aside",
    )
    score = _score_relevance(notice)
    # Multiple keyword hits (water/sewer/civil engineering/design services) + NAICS
    # family + VA agency + LA region (default fixture) + SDVOSB — every bonus firing.
    assert score >= 10


def test_score_relevance_bare_in_family_notice_still_clears_the_floor():
    # No keywords, no weighted agency, no region, no set-aside — only NAICS-family
    # membership. Stage 1 already guarantees that membership, so this must still pass:
    # the floor isn't meant to re-litigate what Stage 1 already decided.
    notice = _sam_notice(
        title="Task Order 0004",
        fullParentPathName="GENERAL SERVICES ADMINISTRATION",
        naicsCode="541330",
        typeOfSetAsideDescription=None,
        placeOfPerformance={},
        officeAddress={},
    )
    assert _score_relevance(notice) >= MIN_RELEVANCE_SCORE


def test_score_relevance_off_topic_non_family_notice_falls_below_floor():
    notice = _sam_notice(
        title="Janitorial Supplies Blanket Purchase Agreement",
        fullParentPathName="GENERAL SERVICES ADMINISTRATION",
        naicsCode="325611",  # Soap and cleaning compound manufacturing — unrelated
        typeOfSetAsideDescription=None,
        placeOfPerformance={},
        officeAddress={},
    )
    assert _score_relevance(notice) < MIN_RELEVANCE_SCORE


def test_score_relevance_naics_family_prefix_bonus():
    in_family = _sam_notice(naicsCode="541370", title="", fullParentPathName="", typeOfSetAsideDescription=None, placeOfPerformance={}, officeAddress={})
    out_of_family = _sam_notice(naicsCode="325611", title="", fullParentPathName="", typeOfSetAsideDescription=None, placeOfPerformance={}, officeAddress={})
    assert _score_relevance(in_family) > _score_relevance(out_of_family)


def test_score_relevance_weighted_agency_bonus():
    usace = _sam_notice(fullParentPathName="DEPT OF DEFENSE.DEPT OF THE ARMY.USACE.NEW ORLEANS DISTRICT")
    other = _sam_notice(fullParentPathName="DEPT OF AGRICULTURE.SOME OFFICE")
    assert _score_relevance(usace) > _score_relevance(other)


def test_score_relevance_gulf_coast_region_bonus():
    louisiana = _sam_notice(placeOfPerformance={"city": {"name": "New Orleans"}, "state": {"code": "LA"}})
    other_state = _sam_notice(placeOfPerformance={"city": {"name": "Chicago"}, "state": {"code": "IL"}})
    assert _score_relevance(louisiana) > _score_relevance(other_state)


def test_score_relevance_sdvosb_scores_higher_than_plain_small_business():
    sdvosb = _sam_notice(typeOfSetAsideDescription="Service-Disabled Veteran-Owned Small Business Set-Aside")
    small_biz = _sam_notice(typeOfSetAsideDescription="Total Small Business Set-Aside")
    assert _score_relevance(sdvosb) > _score_relevance(small_biz)


def test_extract_place_of_performance_falls_back_to_office_address():
    notice = _sam_notice(placeOfPerformance={}, officeAddress={"city": "Baton Rouge", "state": "LA"})
    assert _extract_place_of_performance(notice) == ("Baton Rouge", "LA")


# --- Staleness (the "active/inactive" investigation point) -------------------------

def _raw(category, proposal_due_at=None) -> RawIntelligenceItem:
    return RawIntelligenceItem(
        external_id="x", intelligence_category=category, source_url=None,
        retrieved_at=RETRIEVED_AT, fields={"title": "t", "proposal_due_at": proposal_due_at},
    )


def test_is_expired_opportunity_true_for_past_deadline():
    past = datetime.now(timezone.utc) - timedelta(days=30)
    assert _is_expired_opportunity(_raw(IntelligenceCategory.LIVE_OPPORTUNITY, past)) is True


def test_is_expired_opportunity_false_for_future_deadline():
    future = datetime.now(timezone.utc) + timedelta(days=30)
    assert _is_expired_opportunity(_raw(IntelligenceCategory.LIVE_OPPORTUNITY, future)) is False


def test_is_expired_opportunity_false_when_no_deadline_known():
    assert _is_expired_opportunity(_raw(IntelligenceCategory.PRE_SOLICITATION, None)) is False


def test_is_expired_opportunity_exempts_award_intelligence():
    past = datetime.now(timezone.utc) - timedelta(days=3000)
    assert _is_expired_opportunity(_raw(IntelligenceCategory.AWARD_INTELLIGENCE, past)) is False


# --- fetch(): the real query logic, end to end --------------------------------------
#
# Mocks only the HTTP layer (request_with_retry) so fetch() itself — Stage 1's param
# construction and Stage 2's collect/filter/sort/cap — runs for real, the same way the
# production code path does.

def _fake_response(payload: dict, status_code: int = 200) -> httpx.Response:
    return httpx.Response(status_code, json=payload)


def test_fetch_queries_naics_family_prefix_and_all_substantive_notice_types(monkeypatch):
    captured = []

    def fake_request(client, method, url, params=None, **kwargs):
        captured.append(params)
        return _fake_response({"opportunitiesData": [], "totalRecords": 0, "page_metadata": {"hasNext": False}})

    monkeypatch.setattr(sam_gov_module, "request_with_retry", fake_request)
    monkeypatch.setattr(sam_gov_module.settings, "SAM_GOV_API_KEY", "test-key")

    SamGovConnector().fetch(since=date.today() - timedelta(days=30))

    assert captured, "expected at least one request to SAM.gov"
    params = captured[0]
    assert "5413" in params["ncode"].split(",")
    assert set(params["ptype"].split(",")) == {"o", "p", "k", "r", "s", "a"}


def test_fetch_ranks_best_match_first_drops_expired_and_below_floor(monkeypatch):
    strong = _sam_notice(
        noticeId="strong-1",
        title="Water Main Replacement — Civil Engineering Design Services",
        fullParentPathName="DEPT OF VETERANS AFFAIRS.VISN 16",
        type="Solicitation",
        responseDeadLine="2030-06-01T17:00:00-05:00",
    )
    bare = _sam_notice(
        noticeId="bare-1",
        title="Task Order 0004",
        fullParentPathName="GENERAL SERVICES ADMINISTRATION",
        typeOfSetAsideDescription=None,
        placeOfPerformance={},
        officeAddress={},
        type="Solicitation",
        responseDeadLine="2030-06-01T17:00:00-05:00",
    )
    expired = _sam_notice(
        noticeId="expired-1",
        title="Civil Engineering Services — should be filtered for being expired, not irrelevance",
        type="Solicitation",
        responseDeadLine="2020-01-01T17:00:00-05:00",
    )
    off_topic = _sam_notice(
        noticeId="off-topic-1",
        title="Janitorial Supplies",
        fullParentPathName="GENERAL SERVICES ADMINISTRATION",
        naicsCode="325611",
        typeOfSetAsideDescription=None,
        placeOfPerformance={},
        officeAddress={},
        type="Solicitation",
        responseDeadLine="2030-06-01T17:00:00-05:00",
    )
    # Deliberately unsorted arrival order, to prove fetch() does the sorting itself.
    payload = {
        "opportunitiesData": [bare, off_topic, expired, strong],
        "totalRecords": 4,
        "page_metadata": {"hasNext": False},
    }

    monkeypatch.setattr(sam_gov_module, "request_with_retry", lambda *a, **kw: _fake_response(payload))
    monkeypatch.setattr(sam_gov_module.settings, "SAM_GOV_API_KEY", "test-key")

    results = SamGovConnector().fetch(since=date.today() - timedelta(days=30))

    external_ids = [r.external_id for r in results]
    assert external_ids[0] == "strong-1"  # highest relevance score sorts first
    assert "bare-1" in external_ids  # NAICS-family membership alone still clears the floor
    assert "expired-1" not in external_ids  # past its own deadline
    assert "off-topic-1" not in external_ids  # non-family NAICS, no relevance signal at all


def test_fetch_still_returns_sources_sought_and_presolicitations(monkeypatch):
    sources_sought = _sam_notice(
        noticeId="ss-1", type="Sources Sought",
        title="Sources Sought: Engineering Services for Levee Rehabilitation",
        fullParentPathName="DEPT OF DEFENSE.DEPT OF THE ARMY.USACE.NEW ORLEANS DISTRICT",
    )
    presolicitation = _sam_notice(
        noticeId="pre-1", type="Presolicitation",
        title="Presolicitation: Wastewater Treatment Plant Upgrade",
        fullParentPathName="DEPT OF VETERANS AFFAIRS.VISN 16",
    )
    payload = {
        "opportunitiesData": [sources_sought, presolicitation],
        "totalRecords": 2,
        "page_metadata": {"hasNext": False},
    }
    monkeypatch.setattr(sam_gov_module, "request_with_retry", lambda *a, **kw: _fake_response(payload))
    monkeypatch.setattr(sam_gov_module.settings, "SAM_GOV_API_KEY", "test-key")

    results = SamGovConnector().fetch(since=date.today() - timedelta(days=30))

    by_id = {r.external_id: r for r in results}
    assert by_id["ss-1"].intelligence_category == IntelligenceCategory.PRE_SOLICITATION
    assert by_id["pre-1"].intelligence_category == IntelligenceCategory.PRE_SOLICITATION


# --- run_sync(): provenance + dedup through the real pipeline, SAM.gov-shaped -------

def test_run_sync_persists_relevant_notice_and_prevents_duplicate_on_resync(db, monkeypatch):
    connector = get_intelligence_connector("sam_gov")
    assert isinstance(connector, SamGovConnector)
    monkeypatch.setattr(sam_gov_module.settings, "SAM_GOV_API_KEY", "test-key")

    notice = _sam_notice(
        title="Water Main Replacement — Civil Engineering Design Services",
        fullParentPathName="DEPT OF VETERANS AFFAIRS.VISN 16",
    )
    monkeypatch.setattr(
        connector, "fetch",
        lambda since, **filters: [connector._to_raw_intelligence_item(notice, RETRIEVED_AT)],
    )

    seed_intelligence_sources(db)
    source = db.execute(select(IntelligenceSource).where(IntelligenceSource.name == "SAM.gov")).scalars().one()

    run1 = run_sync(db, source, SyncTriggeredBy.MANUAL)
    assert run1.status == SyncRunStatus.SUCCESS
    assert run1.items_created == 1
    assert source.health_status == SourceHealthStatus.HEALTHY

    item = db.execute(select(IntelligenceItem).where(IntelligenceItem.external_id == "abc123")).scalars().one()
    assert item.source == "SAM.gov"  # provenance: which source found this
    assert item.source_url == "https://sam.gov/opp/abc123/view"
    assert item.raw_metadata["noticeId"] == "abc123"  # full original payload preserved
    assert item.is_sample_data is False  # never confused with SAMPLE DATA
    assert item.opportunity_id is not None  # LIVE_OPPORTUNITY promotes

    run2 = run_sync(db, source, SyncTriggeredBy.MANUAL)
    assert run2.items_created == 0
    assert run2.items_updated == 1  # re-processed, not duplicated
    rows = db.execute(select(IntelligenceItem).where(IntelligenceItem.external_id == "abc123")).scalars().all()
    assert len(rows) == 1
