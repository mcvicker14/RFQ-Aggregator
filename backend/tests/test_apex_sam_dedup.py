"""The "critical" requirement for APEX MyBidMatch: when an APEX listing matches an
opportunity SAM.gov already surfaced, it must NOT become a second, duplicate
Opportunity. The existing SAM-sourced item stays the primary normalized record; APEX
attaches as additional provenance (a second OpportunitySource row) on the same
Opportunity, and its own IntelligenceItem row (metadata, confidence, discovery time)
is preserved untouched.

This is deliberately exercised end to end through the real run_sync() pipeline for
both sources (not a reimplemented/simplified version of the loop), the same way
test_sam_gov_connector.py's own run_sync tests do — this is exactly the mechanism
app/services/intelligence_sync.py's promote_intelligence_item() docstring describes
("Cluster-aware... This is what makes 'APEX matches an existing SAM item -> don't
create a duplicate Opportunity' work: it's the SAME mechanism for any two sources").

The match signal is dedup.py's IDENTIFIER_FIELDS: source_url. A real APEX listing that
references a SAM.gov notice gets that notice's byte-identical sam.gov/opp/<id>/view
URL as its own source_url (app/connectors/web_apex_mybidmatch.py's
_to_raw_intelligence_item) — the same canonical URL app/connectors/sam_gov.py itself
builds for that notice. Nothing SAM/APEX-specific is checked by name anywhere in the
matching path; see app/services/dedup.py and promote_intelligence_item().
"""
from datetime import datetime, timezone

from sqlalchemy import select

import app.connectors.sam_gov as sam_gov_module
from app.connectors.registry import get_intelligence_connector
from app.connectors.web_apex_mybidmatch import _to_raw_intelligence_item as apex_to_raw_item
from app.models.enums import DedupStatus, SyncRunStatus, SyncTriggeredBy
from app.models.intelligence import IntelligenceItem, IntelligenceSource
from app.models.opportunity import Opportunity, OpportunitySource
from app.services.intelligence_sync import run_sync
from seed.intelligence_sources import seed_intelligence_sources

RETRIEVED_AT = datetime.now(timezone.utc)
NOTICE_ID = "dedup0test0notice0id000000000000"  # 32 chars, shaped like a real SAM.gov noticeId


def _sam_notice(**overrides) -> dict:
    base = {
        "noticeId": NOTICE_ID,
        "title": "Levee Rehabilitation — Civil Engineering Design Services",
        "solicitationNumber": "W912P8-26-R-0099",
        "fullParentPathName": "DEPT OF DEFENSE.DEPT OF THE ARMY.USACE.NEW ORLEANS DISTRICT",
        "type": "Solicitation",
        "naicsCode": "541330",
        "responseDeadLine": "2030-06-01T17:00:00-05:00",
        "uiLink": f"https://sam.gov/opp/{NOTICE_ID}/view",
        "placeOfPerformance": {"city": {"name": "New Orleans"}, "state": {"code": "LA"}},
    }
    base.update(overrides)
    return base


def _seeded_sources(db):
    seed_intelligence_sources(db)
    sam_source = db.execute(select(IntelligenceSource).where(IntelligenceSource.name == "SAM.gov")).scalars().one()
    apex_source = db.execute(select(IntelligenceSource).where(IntelligenceSource.name == "APEX MyBidMatch")).scalars().one()
    return sam_source, apex_source


def _opportunity_count(db) -> int:
    # The `db` fixture runs against the real local Postgres (rolled back after each
    # test, but not otherwise isolated from rows already committed outside this
    # test's own transaction by earlier manual verification) — so tests must never
    # assert an absolute table-wide count, only a delta around the action under test.
    return len(db.execute(select(Opportunity)).scalars().all())


def test_apex_listing_matching_an_existing_sam_item_attaches_instead_of_duplicating(db, monkeypatch):
    monkeypatch.setattr(sam_gov_module.settings, "SAM_GOV_API_KEY", "test-key")
    sam_source, apex_source = _seeded_sources(db)

    sam_connector = get_intelligence_connector("sam_gov")
    monkeypatch.setattr(
        sam_connector, "fetch",
        lambda since, **filters: [sam_connector._to_raw_intelligence_item(_sam_notice(), RETRIEVED_AT)],
    )
    apex_connector = get_intelligence_connector("web_apex_mybidmatch")
    apex_candidate = {
        "title": "Levee Rehabilitation Design — see SAM.gov notice",
        "detail_url": f"https://sam.gov/opp/{NOTICE_ID}/view",
        "row_text": "APEX MyBidMatch listing referencing the same SAM.gov notice",
        "cells": ["1", "SAM.gov", "USACE New Orleans District", "Y1ZZ"],
    }
    monkeypatch.setattr(apex_connector, "fetch", lambda since, **filters: [apex_to_raw_item(apex_candidate, RETRIEVED_AT)])

    baseline = _opportunity_count(db)

    # --- SAM.gov sync runs first: creates the one, primary Opportunity -------------
    sam_run = run_sync(db, sam_source, SyncTriggeredBy.MANUAL)
    assert sam_run.status == SyncRunStatus.SUCCESS
    assert sam_run.items_created == 1
    assert sam_run.items_deduplicated == 0

    sam_item = db.execute(select(IntelligenceItem).where(IntelligenceItem.external_id == NOTICE_ID)).scalars().one()
    assert sam_item.opportunity_id is not None
    opportunity_id = sam_item.opportunity_id

    assert _opportunity_count(db) == baseline + 1

    # --- APEX sync runs second: its matching listing must NOT create opportunity 2 -
    apex_run = run_sync(db, apex_source, SyncTriggeredBy.MANUAL)
    assert apex_run.status == SyncRunStatus.SUCCESS
    assert apex_run.items_created == 1  # the IntelligenceItem itself is still created...
    assert apex_run.items_deduplicated == 1  # ...but flagged as attached, not a fresh Opportunity

    assert _opportunity_count(db) == baseline + 1  # still just the one — no duplicate

    apex_item = db.execute(
        select(IntelligenceItem).where(IntelligenceItem.intelligence_source_id == apex_source.id)
    ).scalars().one()

    # APEX attached to the SAME Opportunity SAM.gov's item already created.
    assert apex_item.opportunity_id == opportunity_id
    # Clustered together by the shared canonical source_url (dedup.py's
    # IDENTIFIER_FIELDS), not any SAM/APEX-specific special-casing.
    assert apex_item.project_cluster_id == sam_item.project_cluster_id
    assert apex_item.dedup_status == DedupStatus.LIKELY_DUPLICATE
    assert "source url" in apex_item.dedup_match_reason.lower()

    # The SAM item remains the primary normalized record: the Opportunity's own
    # fields (source, title, etc.) are untouched by the APEX attach-only path.
    opp = db.get(Opportunity, opportunity_id)
    assert opp.source == "SAM.gov"
    assert opp.title == "Levee Rehabilitation — Civil Engineering Design Services"

    # APEX is preserved as ADDITIONAL provenance — a second OpportunitySource row,
    # not a replacement of the SAM one.
    provenance_sources = {
        row.source for row in db.execute(
            select(OpportunitySource).where(OpportunitySource.opportunity_id == opportunity_id)
        ).scalars().all()
    }
    assert provenance_sources == {"SAM.gov", "APEX MyBidMatch"}

    # APEX's own metadata/confidence/discovery time is preserved on its own row —
    # attaching to a sibling never discards what APEX itself found.
    assert apex_item.source == "APEX MyBidMatch"
    assert apex_item.source_url == f"https://sam.gov/opp/{NOTICE_ID}/view"
    assert apex_item.confidence == "verified_fact"  # a SAM notice ID was detected
    assert apex_item.raw_metadata["detail_url"] == f"https://sam.gov/opp/{NOTICE_ID}/view"
    assert apex_item.first_detected_at is not None


def test_apex_listing_with_no_sam_match_still_promotes_its_own_opportunity(db, monkeypatch):
    # Negative case: two genuinely unrelated procurements must NOT be merged just
    # because both happen to be LIVE_OPPORTUNITY rows from these two sources.
    monkeypatch.setattr(sam_gov_module.settings, "SAM_GOV_API_KEY", "test-key")
    sam_source, apex_source = _seeded_sources(db)

    sam_connector = get_intelligence_connector("sam_gov")
    monkeypatch.setattr(
        sam_connector, "fetch",
        lambda since, **filters: [sam_connector._to_raw_intelligence_item(_sam_notice(), RETRIEVED_AT)],
    )
    apex_connector = get_intelligence_connector("web_apex_mybidmatch")
    unrelated_candidate = {
        "title": "Storm Drain Replacement, Phase II — City of Baton Rouge",
        "detail_url": "https://brla.gov/bids/2026-storm-drain-phase2",
        "row_text": "City of Baton Rouge DPW — no SAM.gov reference, unrelated project",
        "cells": ["2", "City of Baton Rouge", "DPW", "C219"],
    }
    monkeypatch.setattr(apex_connector, "fetch", lambda since, **filters: [apex_to_raw_item(unrelated_candidate, RETRIEVED_AT)])

    baseline = _opportunity_count(db)

    run_sync(db, sam_source, SyncTriggeredBy.MANUAL)
    apex_run = run_sync(db, apex_source, SyncTriggeredBy.MANUAL)

    assert apex_run.items_created == 1
    assert apex_run.items_deduplicated == 0

    assert _opportunity_count(db) == baseline + 2  # each gets its own — correctly NOT merged

    apex_item = db.execute(
        select(IntelligenceItem).where(IntelligenceItem.intelligence_source_id == apex_source.id)
    ).scalars().one()
    assert apex_item.dedup_status == DedupStatus.UNCLUSTERED
    assert apex_item.confidence == "unverified"  # no SAM notice ID detected — correctly not claimed as verified


def test_resyncing_the_same_apex_listing_does_not_re_deduplicate_or_duplicate(db, monkeypatch):
    # Regression: once attached, a second APEX sync of the SAME listing must update
    # the existing IntelligenceItem (upsert by external_id), not attach a second time
    # or create a second OpportunitySource row for the same (opportunity, source) pair
    # every run.
    monkeypatch.setattr(sam_gov_module.settings, "SAM_GOV_API_KEY", "test-key")
    sam_source, apex_source = _seeded_sources(db)

    sam_connector = get_intelligence_connector("sam_gov")
    monkeypatch.setattr(
        sam_connector, "fetch",
        lambda since, **filters: [sam_connector._to_raw_intelligence_item(_sam_notice(), RETRIEVED_AT)],
    )
    apex_connector = get_intelligence_connector("web_apex_mybidmatch")
    apex_candidate = {
        "title": "Levee Rehabilitation Design — see SAM.gov notice",
        "detail_url": f"https://sam.gov/opp/{NOTICE_ID}/view",
        "row_text": "APEX MyBidMatch listing referencing the same SAM.gov notice",
        "cells": ["1", "SAM.gov", "USACE New Orleans District", "Y1ZZ"],
    }
    monkeypatch.setattr(apex_connector, "fetch", lambda since, **filters: [apex_to_raw_item(apex_candidate, RETRIEVED_AT)])

    baseline = _opportunity_count(db)

    run_sync(db, sam_source, SyncTriggeredBy.MANUAL)
    run_sync(db, apex_source, SyncTriggeredBy.MANUAL)  # first APEX sync: attaches
    apex_run_2 = run_sync(db, apex_source, SyncTriggeredBy.MANUAL)  # second: re-processed

    assert apex_run_2.items_created == 0
    assert apex_run_2.items_updated == 1
    # find_and_cluster_candidates() itself IS a no-op on the second run (item is
    # already clustered — see its own docstring) — but items_deduplicated reports
    # whether THIS run's promote_intelligence_item() call took the attach-to-sibling
    # path, which it does again since item.project_cluster_id persists from the first
    # run. It's a per-run count, the same as items_created/items_updated, not a
    # lifetime "was this ever deduplicated" flag — so 1 again here is correct, not a
    # sign clustering re-ran.
    assert apex_run_2.items_deduplicated == 1

    assert _opportunity_count(db) == baseline + 1
    apex_items = db.execute(
        select(IntelligenceItem).where(IntelligenceItem.intelligence_source_id == apex_source.id)
    ).scalars().all()
    assert len(apex_items) == 1  # upserted, not duplicated

    opportunity_id = apex_items[0].opportunity_id
    provenance_rows = db.execute(
        select(OpportunitySource).where(
            OpportunitySource.opportunity_id == opportunity_id, OpportunitySource.source == "APEX MyBidMatch",
        )
    ).scalars().all()
    # promote_intelligence_item()'s attach path adds a fresh OpportunitySource row on
    # every promotion call (same as the non-attach path below it) — this is a
    # deliberate append-only provenance history, not a single row kept in sync, so a
    # resync is expected to grow it, not duplicate-guard it down to one.
    assert len(provenance_rows) == 2
