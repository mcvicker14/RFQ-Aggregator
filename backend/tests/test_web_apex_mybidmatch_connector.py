"""Tests for the APEX MyBidMatch connector. Written against synthetic HTML shaped to
match OutreachSystems' OWN public documentation of the mybidmatch.com platform (a
per-subscriber table: # / Source / Agency / FSG / Title / Keywords, Title holding the
detail link) — NOT the real subscriber page, which this sandbox's network egress
policy blocks fetching (confirmed against multiple unrelated domains too; see
app/connectors/web_apex_mybidmatch.py's module docstring). _parse_page() is exercised
against both documented-shape HTML and deliberately-wrong shapes (no table, JS-empty
body) to prove it degrades to an honest "found nothing, here's why" diagnostic rather
than fabricating data — the thing that most needs proving given the parser itself is
unverified. Whoever gets real page access next should add a fixture captured from the
live page and confirm it against these same functions.
"""
from datetime import date, datetime, timedelta, timezone

import httpx
from sqlalchemy import select

import app.connectors.web_apex_mybidmatch as apex_module
from app.connectors.registry import get_intelligence_connector
from app.connectors.web_apex_mybidmatch import (
    ApexMyBidMatchConnector,
    PAGE_URL,
    _extract_money,
    _extract_naics,
    _extract_sam_notice_id,
    _looks_javascript_rendered,
    _map_set_aside,
    _parse_loose_date,
    _parse_page,
    _to_raw_intelligence_item,
)
from app.models.enums import IntelligenceCategory, SetAsideType, SyncRunStatus, SyncTriggeredBy
from app.models.intelligence import IntelligenceItem, IntelligenceSource
from app.services.intelligence_sync import run_sync
from seed.intelligence_sources import seed_intelligence_sources

RETRIEVED_AT = datetime.now(timezone.utc)
SAM_ID = "11112222333344445555666677778888"  # 32 chars, shaped like a real SAM.gov noticeId


# --- _to_raw_intelligence_item(): field mapping, directly (mirrors test_sam_gov_connector.py) ---

def _candidate(**overrides) -> dict:
    base = {
        "title": "Drainage Improvements Design-Build",
        "detail_url": "https://mybidmatch.outreachsystems.com/detail/12345",
        "row_text": "Due: 11/15/2026 NAICS 541330 Total Small Business Est. Value $250,000",
        "cells": ["1", "SAM.gov", "USACE New Orleans District", "Y1ZZ", "Drainage Improvements Design-Build", "Keywords here"],
    }
    base.update(overrides)
    return base


def test_maps_full_candidate_with_agency_naics_set_aside_deadline_and_value():
    raw = _to_raw_intelligence_item(_candidate(), RETRIEVED_AT)

    assert raw.fields["title"] == "Drainage Improvements Design-Build"
    assert raw.fields["agency_name"] == "USACE New Orleans District"  # cells[2]
    assert raw.fields["naics_code"] == "541330"
    assert raw.fields["set_aside"] == SetAsideType.SMALL_BUSINESS
    assert raw.fields["proposal_due_at"] == datetime(2026, 11, 15, tzinfo=timezone.utc)
    assert raw.fields["estimated_value_high"] == 250_000.0
    assert raw.intelligence_category == IntelligenceCategory.LIVE_OPPORTUNITY


def test_sam_notice_detected_in_detail_url_produces_byte_identical_sam_source_url():
    # Matches the EXACT format app/connectors/sam_gov.py itself builds
    # (f"https://sam.gov/opp/{notice_id}/view") — required for dedup.py's
    # canonical-source_url identifier match to catch the duplicate.
    candidate = _candidate(detail_url=f"https://sam.gov/opp/{SAM_ID}/view", row_text="no sam link in the visible text")
    raw = _to_raw_intelligence_item(candidate, RETRIEVED_AT)

    assert raw.source_url == f"https://sam.gov/opp/{SAM_ID}/view"
    assert raw.confidence == "verified_fact"
    assert raw.raw["sam_notice_id_detected"] == SAM_ID
    assert raw.external_id == SAM_ID


def test_sam_notice_detected_in_row_text_even_without_a_sam_detail_url():
    candidate = _candidate(
        detail_url="https://mybidmatch.outreachsystems.com/detail/12345",
        row_text=f"See https://sam.gov/opp/{SAM_ID}/view for full notice",
    )
    raw = _to_raw_intelligence_item(candidate, RETRIEVED_AT)
    assert raw.source_url == f"https://sam.gov/opp/{SAM_ID}/view"
    assert raw.confidence == "verified_fact"


def test_no_sam_notice_detected_falls_back_to_apex_detail_url_as_unverified():
    candidate = _candidate(detail_url="https://somecity.gov/bids/98765", row_text="no sam reference at all")
    raw = _to_raw_intelligence_item(candidate, RETRIEVED_AT)

    assert raw.source_url == "https://somecity.gov/bids/98765"
    assert raw.confidence == "unverified"
    assert raw.external_id == "https://somecity.gov/bids/98765"


def test_missing_title_returns_none_rather_than_a_blank_item():
    assert _to_raw_intelligence_item(_candidate(title=""), RETRIEVED_AT) is None
    assert _to_raw_intelligence_item(_candidate(title="   "), RETRIEVED_AT) is None


def test_missing_agency_cell_degrades_gracefully():
    raw = _to_raw_intelligence_item(_candidate(cells=["1", "SAM.gov"]), RETRIEVED_AT)
    assert raw.fields["agency_name"] is None


def test_no_deadline_or_money_in_row_text_leaves_fields_none_not_fabricated():
    candidate = _candidate(row_text="Drainage improvements, various locations")
    raw = _to_raw_intelligence_item(candidate, RETRIEVED_AT)
    assert raw.fields["proposal_due_at"] is None
    assert raw.fields["estimated_value_high"] is None


def test_raw_metadata_preserves_full_row_text_and_detail_url_for_provenance():
    candidate = _candidate()
    raw = _to_raw_intelligence_item(candidate, RETRIEVED_AT)
    assert raw.raw["row_text"] == candidate["row_text"]
    assert raw.raw["detail_url"] == candidate["detail_url"]


# --- Field-level helper functions --------------------------------------------------

def test_extract_sam_notice_id_matches_opp_view_url():
    assert _extract_sam_notice_id(f"https://sam.gov/opp/{SAM_ID}/view") == SAM_ID


def test_extract_sam_notice_id_returns_none_for_non_sam_text():
    assert _extract_sam_notice_id("https://somecity.gov/bids/98765") is None


def test_map_set_aside_recognizes_each_documented_keyword():
    assert _map_set_aside("Service-Disabled Veteran Owned Small Business") == SetAsideType.SDVOSB
    assert _map_set_aside("SDVOSB set-aside") == SetAsideType.SDVOSB
    assert _map_set_aside("8(a) sole source") == SetAsideType.EIGHT_A
    assert _map_set_aside("HUBZone set-aside") == SetAsideType.HUBZONE
    assert _map_set_aside("Women-Owned Small Business") == SetAsideType.WOSB
    assert _map_set_aside(None) == SetAsideType.UNRESTRICTED
    assert _map_set_aside("full and open competition") == SetAsideType.UNRESTRICTED


def test_extract_naics_requires_word_boundary_label():
    assert _extract_naics("NAICS: 541330") == "541330"
    assert _extract_naics("primary NAICS code 237990 for this bid") == "237990"
    assert _extract_naics("no code mentioned") is None


def test_extract_money_handles_thousands_and_millions_suffixes():
    assert _extract_money("Est. Value $250,000") == 250_000.0
    assert _extract_money("approx $1.2M") == 1_200_000.0
    assert _extract_money("around $500k") == 500_000.0
    assert _extract_money("no value given") is None


def test_parse_loose_date_finds_the_date_even_with_leading_text():
    # Regression: an earlier version required the WHOLE (truncated) string to be
    # exactly the date, which almost never matched on a realistic row with a
    # title/agency ahead of the date. Must search, not full-match.
    assert _parse_loose_date("Drainage Improvements Due: 11/15/2026 more text after") == datetime(2026, 11, 15, tzinfo=timezone.utc)
    assert _parse_loose_date("Posted 2026-09-01, response due December 3, 2026") == datetime(2026, 9, 1, tzinfo=timezone.utc)
    assert _parse_loose_date("nothing resembling a date") is None


# --- _parse_page(): structural extraction strategies --------------------------------

_DOCUMENTED_TABLE_HTML = f"""
<html><body>
<table>
<tr><th>#</th><th>Source</th><th>Agency</th><th>FSG</th><th>Title</th><th>Keywords</th></tr>
<tr>
  <td>1</td><td>SAM.gov</td><td>USACE New Orleans District</td><td>Y1ZZ</td>
  <td><a href="https://sam.gov/opp/{SAM_ID}/view">Drainage Improvements Design-Build</a></td>
  <td>NAICS 541330 drainage engineering Due: 11/15/2026</td>
</tr>
<tr>
  <td>2</td><td>City of Baton Rouge</td><td>DPW</td><td>C219</td>
  <td><a href="/detail/456">Wastewater Lift Station Rehabilitation</a></td>
  <td>NAICS 237110 utilities</td>
</tr>
</table>
</body></html>
"""


def test_table_rows_strategy_matches_the_documented_layout():
    candidates, diagnostics = _parse_page(_DOCUMENTED_TABLE_HTML, PAGE_URL)

    assert diagnostics["strategy_used"] == "table_rows"
    assert diagnostics["likely_javascript_rendered"] is False
    assert len(candidates) == 2
    titles = {c["title"] for c in candidates}
    assert titles == {"Drainage Improvements Design-Build", "Wastewater Lift Station Rehabilitation"}


def test_table_rows_strategy_resolves_relative_detail_urls_against_base():
    candidates, _ = _parse_page(_DOCUMENTED_TABLE_HTML, PAGE_URL)
    by_title = {c["title"]: c for c in candidates}
    assert by_title["Wastewater Lift Station Rehabilitation"]["detail_url"] == str(httpx.URL(PAGE_URL).join("/detail/456"))


def test_table_rows_strategy_skips_the_header_row():
    candidates, _ = _parse_page(_DOCUMENTED_TABLE_HTML, PAGE_URL)
    assert not any(c["title"] in ("#", "Source", "Title") for c in candidates)


_GENERIC_LIST_HTML = """
<html><body>
<div id="results">
  <div class="bid-row">Posted 9/1/2026 — <a href="https://city.gov/bids/1">Storm Drain Replacement Project, Phase II</a></div>
  <div class="bid-row"><a href="https://city.gov/bids/2">Airport Runway Resurfacing</a> — closing soon, NAICS 237310</div>
</div>
</body></html>
"""


def test_generic_listing_fallback_used_when_no_table_present():
    candidates, diagnostics = _parse_page(_GENERIC_LIST_HTML, PAGE_URL)

    assert diagnostics["strategy_used"] == "generic_listing_items"
    titles = {c["title"] for c in candidates}
    assert titles == {"Storm Drain Replacement Project, Phase II", "Airport Runway Resurfacing"}


def test_generic_listing_fallback_skips_elements_that_are_just_the_bare_link():
    html = '<html><body><li><a href="https://city.gov/bids/1">Storm Drain Replacement</a></li></body></html>'
    candidates, _ = _parse_page(html, PAGE_URL)
    assert candidates == []  # element's whole text IS the link — not a listing row with extra fields


_JS_RENDERED_HTML = """
<html><body>
<div id="root"></div>
<script>%s</script>
</body></html>
""" % ("x" * 6000)


def test_javascript_rendered_page_returns_empty_with_explicit_diagnostic_not_fabricated_rows():
    candidates, diagnostics = _parse_page(_JS_RENDERED_HTML, PAGE_URL)

    assert candidates == []
    assert diagnostics["likely_javascript_rendered"] is True
    assert "javascript" in diagnostics["note"].lower()
    assert "strategy_used" not in diagnostics  # never even attempted — would be misleading


_EMPTY_STATIC_HTML = "<html><body><p>Please log in to view your matches.</p></body></html>"


def test_neither_strategy_matches_returns_empty_with_explanatory_note():
    candidates, diagnostics = _parse_page(_EMPTY_STATIC_HTML, PAGE_URL)

    assert candidates == []
    assert diagnostics["strategy_used"] is None
    assert diagnostics["candidates_found"] == 0
    assert "re-verified" in diagnostics["note"]


def test_feed_link_is_recorded_in_diagnostics_but_not_required_to_exist():
    html_with_feed = '<html><head><link rel="alternate" type="application/rss+xml" href="/feed.xml"></head><body>%s</body></html>' % _DOCUMENTED_TABLE_HTML
    candidates, diagnostics = _parse_page(html_with_feed, PAGE_URL)
    assert diagnostics["feed_link_found"] == "/feed.xml"

    _, diagnostics_no_feed = _parse_page(_DOCUMENTED_TABLE_HTML, PAGE_URL)
    assert diagnostics_no_feed["feed_link_found"] is None


# --- fetch(): HTTP layer mocked, everything downstream runs for real ---------------

def _fake_response(text: str, status_code: int = 200, url: str = PAGE_URL) -> httpx.Response:
    return httpx.Response(status_code, text=text, request=httpx.Request("GET", url))


def test_is_configured_is_always_true_no_credentials_needed():
    assert ApexMyBidMatchConnector().is_configured() is True


def test_fetch_returns_mapped_items_and_attaches_diagnostics(monkeypatch):
    monkeypatch.setattr(apex_module, "request_with_retry", lambda *a, **kw: _fake_response(_DOCUMENTED_TABLE_HTML))

    connector = ApexMyBidMatchConnector()
    results = connector.fetch(since=date.today() - timedelta(days=1))

    assert len(results) == 2
    assert connector.last_run_diagnostics["strategy_used"] == "table_rows"
    assert connector.last_run_diagnostics["candidates_found"] == 2
    assert connector.last_run_diagnostics["records_returned"] == 2
    assert connector.last_run_diagnostics["mapping_errors"] == 0
    assert connector.last_run_diagnostics["redirected"] is False


def test_fetch_handles_non_200_without_raising(monkeypatch):
    monkeypatch.setattr(apex_module, "request_with_retry", lambda *a, **kw: _fake_response("nope", status_code=503))

    connector = ApexMyBidMatchConnector()
    results = connector.fetch(since=date.today() - timedelta(days=1))

    assert results == []
    assert connector.last_run_diagnostics["status_code"] == 503


def test_fetch_records_redirect_in_diagnostics(monkeypatch):
    final_url = "https://mybidmatch.outreachsystems.com/go/expired"
    monkeypatch.setattr(apex_module, "request_with_retry", lambda *a, **kw: _fake_response(_EMPTY_STATIC_HTML, url=final_url))

    connector = ApexMyBidMatchConnector()
    connector.fetch(since=date.today() - timedelta(days=1))

    assert connector.last_run_diagnostics["redirected"] is True
    assert connector.last_run_diagnostics["final_url"] == final_url


def test_fetch_isolates_one_mapping_failure_from_the_rest(monkeypatch):
    monkeypatch.setattr(apex_module, "request_with_retry", lambda *a, **kw: _fake_response(_DOCUMENTED_TABLE_HTML))

    real_mapper = apex_module._to_raw_intelligence_item

    def flaky_mapper(candidate, retrieved_at):
        if candidate["title"] == "Drainage Improvements Design-Build":
            raise ValueError("simulated mapping failure")
        return real_mapper(candidate, retrieved_at)

    monkeypatch.setattr(apex_module, "_to_raw_intelligence_item", flaky_mapper)

    connector = ApexMyBidMatchConnector()
    results = connector.fetch(since=date.today() - timedelta(days=1))

    assert len(results) == 1
    assert results[0].fields["title"] == "Wastewater Lift Station Rehabilitation"
    assert connector.last_run_diagnostics["mapping_errors"] == 1


def test_fetch_caps_results_at_the_limit_parameter(monkeypatch):
    monkeypatch.setattr(apex_module, "request_with_retry", lambda *a, **kw: _fake_response(_DOCUMENTED_TABLE_HTML))

    connector = ApexMyBidMatchConnector()
    results = connector.fetch(since=date.today() - timedelta(days=1), limit=1)

    assert len(results) == 1


def test_connection_failure_raises_connector_not_configured_error_not_a_bare_exception(monkeypatch):
    def boom(*a, **kw):
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(apex_module, "request_with_retry", boom)

    from app.connectors.base import ConnectorNotConfiguredError
    connector = ApexMyBidMatchConnector()
    try:
        connector.fetch(since=date.today() - timedelta(days=1))
        assert False, "expected ConnectorNotConfiguredError"
    except ConnectorNotConfiguredError as exc:
        assert "re-verified" in str(exc)


def test_apex_mybidmatch_is_registered_under_its_connector_key():
    connector = get_intelligence_connector("web_apex_mybidmatch")
    assert isinstance(connector, ApexMyBidMatchConnector)


# --- run_sync(): provenance + dedup-on-resync through the real pipeline -------------

def test_run_sync_persists_item_and_prevents_duplicate_on_resync(db, monkeypatch):
    connector = get_intelligence_connector("web_apex_mybidmatch")
    monkeypatch.setattr(
        connector, "fetch",
        lambda since, **filters: [_to_raw_intelligence_item(_candidate(detail_url="https://city.gov/bids/1"), RETRIEVED_AT)],
    )

    seed_intelligence_sources(db)
    source = db.execute(select(IntelligenceSource).where(IntelligenceSource.name == "APEX MyBidMatch")).scalars().one()

    run1 = run_sync(db, source, SyncTriggeredBy.MANUAL)
    assert run1.status == SyncRunStatus.SUCCESS
    assert run1.items_created == 1

    run2 = run_sync(db, source, SyncTriggeredBy.MANUAL)
    assert run2.items_created == 0
    assert run2.items_updated == 1

    rows = db.execute(
        select(IntelligenceItem).where(IntelligenceItem.intelligence_source_id == source.id)
    ).scalars().all()
    assert len(rows) == 1
