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
    SamGovConnector,
    _extract_place_of_performance,
    _is_expired_opportunity,
    _map_notice_type,
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


def test_fetch_runs_diagnostic_probes_then_queries_each_naics_code_separately(monkeypatch):
    # Regression test for the round-2 incident: ncode is documented as one exact code,
    # not a prefix or a combined list, and ptype must be repeated query keys, not
    # comma-joined. This proves fetch() actually sends requests that way, plus runs
    # the three diagnostic probes first.
    captured = []

    def fake_request(client, method, url, params=None, **kwargs):
        captured.append(dict(params))
        return _fake_response({"opportunitiesData": [], "totalRecords": 0, "page_metadata": {"hasNext": False}})

    monkeypatch.setattr(sam_gov_module, "request_with_retry", fake_request)
    monkeypatch.setattr(sam_gov_module.settings, "SAM_GOV_API_KEY", "test-key")

    connector = SamGovConnector()
    connector.fetch(since=date.today() - timedelta(days=30))

    # Probes: A (baseline, no ncode/ptype), B (+ exact 541330), C (+ ptype list).
    probe_a, probe_b, probe_c = captured[0], captured[1], captured[2]
    assert "ncode" not in probe_a and "ptype" not in probe_a
    assert probe_b["ncode"] == "541330" and "ptype" not in probe_b
    assert probe_c["ncode"] == "541330"
    assert probe_c["ptype"] == sam_gov_module.NOTICE_TYPE_CODES

    # Every call after the 3 probes is a real per-NAICS-code retrieval query.
    real_calls = captured[3:]
    expected_codes = set(sam_gov_module.DEFAULT_NAICS_FILTER) | set(sam_gov_module.settings.PRINCIPAL_SECONDARY_NAICS)
    assert {c["ncode"] for c in real_calls} == expected_codes
    for call in real_calls:
        assert isinstance(call["ncode"], str) and "," not in call["ncode"]  # one exact code, never combined
        assert call["ptype"] == sam_gov_module.NOTICE_TYPE_CODES  # a list, not a comma-joined string

    # Never leaks the API key into anything the connector records for diagnostics.
    assert "test-key" not in str(connector.last_run_diagnostics)


def test_probe_never_returns_the_api_key(monkeypatch):
    def fake_request(client, method, url, params=None, **kwargs):
        assert params["api_key"] == "super-secret-key"  # the request itself still needs it
        return _fake_response({"opportunitiesData": [], "totalRecords": 42})

    monkeypatch.setattr(sam_gov_module, "request_with_retry", fake_request)
    monkeypatch.setattr(sam_gov_module.settings, "SAM_GOV_API_KEY", "super-secret-key")

    with httpx.Client() as client:
        result = sam_gov_module._probe(client, date.today() - timedelta(days=1), date.today())

    assert result == {"status_code": 200, "total_records": 42}
    assert "super-secret-key" not in str(result)


def test_probe_handles_non_200_without_raising(monkeypatch):
    def fake_request(client, method, url, params=None, **kwargs):
        return _fake_response({"error": "bad request"}, status_code=400)

    monkeypatch.setattr(sam_gov_module, "request_with_retry", fake_request)
    monkeypatch.setattr(sam_gov_module.settings, "SAM_GOV_API_KEY", "test-key")

    with httpx.Client() as client:
        result = sam_gov_module._probe(client, date.today() - timedelta(days=1), date.today())

    assert result["status_code"] == 400
    assert result["total_records"] is None


def test_run_diagnostic_probes_uses_a_full_year_window_regardless_of_since(monkeypatch):
    captured_windows = []

    def fake_request(client, method, url, params=None, **kwargs):
        captured_windows.append((params["postedFrom"], params["postedTo"]))
        return _fake_response({"opportunitiesData": [], "totalRecords": 0})

    monkeypatch.setattr(sam_gov_module, "request_with_retry", fake_request)
    monkeypatch.setattr(sam_gov_module.settings, "SAM_GOV_API_KEY", "test-key")

    with httpx.Client() as client:
        probes = sam_gov_module._run_diagnostic_probes(client)

    assert set(probes.keys()) == {"A_baseline_date_range_only", "B_exact_naics_541330", "C_naics_plus_notice_types"}
    assert len(captured_windows) == 3
    for posted_from_str, posted_to_str in captured_windows:
        posted_from = datetime.strptime(posted_from_str, "%m/%d/%Y").date()
        posted_to = datetime.strptime(posted_to_str, "%m/%d/%Y").date()
        assert (posted_to - posted_from).days == sam_gov_module.DIAGNOSTIC_PROBE_WINDOW_DAYS


def test_fetch_attaches_last_run_diagnostics_with_the_documented_shape(monkeypatch):
    monkeypatch.setattr(sam_gov_module, "request_with_retry", lambda *a, **kw: _fake_response({"opportunitiesData": [], "totalRecords": 0}))
    monkeypatch.setattr(sam_gov_module.settings, "SAM_GOV_API_KEY", "test-key")

    connector = SamGovConnector()
    assert connector.last_run_diagnostics is None  # nothing yet before the first fetch()

    connector.fetch(since=date.today() - timedelta(days=30))

    diagnostics = connector.last_run_diagnostics
    assert diagnostics is not None
    assert set(diagnostics["probes"].keys()) == {"A_baseline_date_range_only", "B_exact_naics_541330", "C_naics_plus_notice_types"}
    retrieval = diagnostics["retrieval"]
    assert len(retrieval["date_window"]) == 2
    assert set(retrieval["naics_codes_queried"]) == set(sam_gov_module.DEFAULT_NAICS_FILTER) | set(sam_gov_module.settings.PRINCIPAL_SECONDARY_NAICS)
    assert retrieval["notice_type_codes"] == sam_gov_module.NOTICE_TYPE_CODES
    assert set(retrieval["total_records_by_naics"]) == set(retrieval["naics_codes_queried"])
    assert retrieval["pages_fetched"] >= len(retrieval["naics_codes_queried"])
    assert retrieval["candidates_collected"] == 0
    assert retrieval["records_returned"] == 0


def test_fetch_deduplicates_the_same_notice_returned_by_multiple_naics_queries(monkeypatch):
    # A real, multi-disciplinary IDIQ could plausibly satisfy more than one of the
    # NAICS codes queried separately — must be merged once, not duplicated.
    notice = _sam_notice(
        title="Civil Engineering Design Services — Drainage Improvements",
        fullParentPathName="DEPT OF VETERANS AFFAIRS.VISN 16",
    )
    monkeypatch.setattr(
        sam_gov_module, "request_with_retry",
        lambda *a, **kw: _fake_response({"opportunitiesData": [notice], "totalRecords": 1}),
    )
    monkeypatch.setattr(sam_gov_module.settings, "SAM_GOV_API_KEY", "test-key")

    results = SamGovConnector().fetch(since=date.today() - timedelta(days=30))

    assert len(results) == 1
    assert results[0].external_id == "abc123"


def test_fetch_keeps_every_non_expired_notice_regardless_of_topical_relevance(monkeypatch):
    # Production, round 3: a live sync of 355 records showed most of what SAM.gov's own
    # NAICS/notice-type tagging lets through isn't Principal-relevant — but the fix for
    # that is Stage 2 scoring *after* persistence (app/services/sam_relevance_scoring.py),
    # not dropping records here. fetch() itself must keep everything not expired,
    # on-topic or not, for intelligence/auditability — see the module docstring.
    relevant = _sam_notice(
        noticeId="relevant-1",
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
        title="Civil Engineering Services — should be filtered for being expired",
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
    payload = {
        "opportunitiesData": [bare, off_topic, expired, relevant],
        "totalRecords": 4,
        "page_metadata": {"hasNext": False},
    }

    monkeypatch.setattr(sam_gov_module, "request_with_retry", lambda *a, **kw: _fake_response(payload))
    monkeypatch.setattr(sam_gov_module.settings, "SAM_GOV_API_KEY", "test-key")

    results = SamGovConnector().fetch(since=date.today() - timedelta(days=30))

    external_ids = {r.external_id for r in results}
    assert external_ids == {"relevant-1", "bare-1", "off-topic-1"}  # everything except the expired one
    assert "expired-1" not in external_ids  # past its own deadline — the one thing still filtered here


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
