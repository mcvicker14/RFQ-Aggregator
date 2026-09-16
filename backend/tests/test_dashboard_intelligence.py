from datetime import datetime, timedelta, timezone

from app.models.enums import ConnectorType, IntelligenceCategory, JurisdictionLevel, SourceHealthStatus
from app.models.intelligence import IntelligenceItem, IntelligenceSource
from app.models.opportunity import Opportunity
from app.models.user import User
from app.services.dashboard import build_dashboard_summary

NOW = datetime.now(timezone.utc)


def _source(db, **overrides):
    defaults = dict(name="Dashboard Test Source", jurisdiction_level=JurisdictionLevel.FEDERAL, connector_type=ConnectorType.API)
    defaults.update(overrides)
    src = IntelligenceSource(**defaults)
    db.add(src)
    db.flush()
    return src


def _item(db, source, **overrides):
    defaults = dict(
        intelligence_source_id=source.id, external_id=overrides.pop("external_id", "X"),
        title="Test Item", intelligence_category=IntelligenceCategory.EARLY_SIGNAL,
        source=source.name, retrieved_at=NOW, first_detected_at=NOW, last_seen_at=NOW,
    )
    defaults.update(overrides)
    item = IntelligenceItem(**defaults)
    db.add(item)
    db.flush()
    return item


def test_category_counts(db):
    user = db.query(User).first()
    source = _source(db)
    _item(db, source, external_id="A", intelligence_category=IntelligenceCategory.LIVE_OPPORTUNITY)
    _item(db, source, external_id="B", intelligence_category=IntelligenceCategory.LIVE_OPPORTUNITY)
    _item(db, source, external_id="C", intelligence_category=IntelligenceCategory.EARLY_SIGNAL)

    summary = build_dashboard_summary(db, user)

    assert summary.intelligence.live_opportunity_count == 2
    assert summary.intelligence.early_signal_count == 1
    assert summary.intelligence.pre_solicitation_count == 0
    assert summary.intelligence.award_intelligence_count == 0


def test_new_this_week_counts_only_recent_items(db):
    user = db.query(User).first()
    source = _source(db)
    _item(db, source, external_id="A", first_detected_at=NOW)
    _item(db, source, external_id="B", first_detected_at=NOW - timedelta(days=10))

    summary = build_dashboard_summary(db, user)

    assert summary.intelligence.new_this_week == 1


def test_sources_checked_today_and_with_errors(db):
    # Cleared first, within this test's own (rolled-back-after) transaction: the seeded
    # Source Registry already has real rows in the shared local database from manual
    # testing earlier the same day (e.g. a live "Sync Now" attempt against SAM.gov),
    # which would otherwise inflate these counts unpredictably depending on what else
    # ran today. Isolating from that, rather than asserting loose inequalities, keeps
    # this test meaningful and exact.
    db.execute(IntelligenceSource.__table__.update().values(last_attempted_sync_at=None, health_status=SourceHealthStatus.NEVER_RUN))

    user = db.query(User).first()
    _source(db, name="Checked Today", last_attempted_sync_at=NOW, health_status=SourceHealthStatus.HEALTHY)
    _source(db, name="Checked Yesterday", last_attempted_sync_at=NOW - timedelta(days=1), health_status=SourceHealthStatus.HEALTHY)
    _source(db, name="Failing Source", last_attempted_sync_at=NOW, health_status=SourceHealthStatus.FAILING)
    _source(db, name="Degraded Source", health_status=SourceHealthStatus.DEGRADED)

    summary = build_dashboard_summary(db, user)

    assert summary.intelligence.sources_checked_today == 2  # "Checked Today" + "Failing Source"
    assert summary.intelligence.sources_with_errors == 2  # "Failing Source" + "Degraded Source"


def test_new_intelligence_since_last_view_advances_the_marker(db):
    user = db.query(User).first()
    user.intelligence_last_viewed_at = None
    source = _source(db)
    _item(db, source, external_id="A")

    first_summary = build_dashboard_summary(db, user)
    assert first_summary.intelligence.new_intelligence_since_last_view == 1
    assert first_summary.intelligence.last_viewed_at is None  # reports the *old* (unset) value

    second_summary = build_dashboard_summary(db, user)
    assert second_summary.intelligence.new_intelligence_since_last_view == 0  # nothing new since the first call
    assert second_summary.intelligence.last_viewed_at is not None  # now reflects the first call's timestamp


def test_intelligence_counts_exclude_low_relevance_sam_items_by_default(db):
    # "Do not include hidden low-relevance records in dashboard opportunity counts" —
    # a SAM.gov item scored below RELEVANT_THRESHOLD must not inflate the intelligence
    # KPIs a user reads as "what's new," the same default Discover applies.
    user = db.query(User).first()
    source = _source(db)
    _item(db, source, external_id="A", intelligence_category=IntelligenceCategory.LIVE_OPPORTUNITY, sam_relevance_score=85)
    _item(db, source, external_id="B", intelligence_category=IntelligenceCategory.LIVE_OPPORTUNITY, sam_relevance_score=20)
    # Not from SAM.gov (no score at all) — never excluded by this filter.
    _item(db, source, external_id="C", intelligence_category=IntelligenceCategory.LIVE_OPPORTUNITY, sam_relevance_score=None)

    summary = build_dashboard_summary(db, user)

    assert summary.intelligence.live_opportunity_count == 2  # A (relevant) + C (unscored, not SAM) — not B


def test_intelligence_counts_exclude_low_relevance_grants_items_by_default(db):
    # Same rule as the SAM.gov test above, independently, for Grants.gov: a grant
    # scored below its own RELEVANT_THRESHOLD must not inflate the intelligence KPIs.
    user = db.query(User).first()
    source = _source(db)
    _item(db, source, external_id="A", intelligence_category=IntelligenceCategory.EARLY_SIGNAL, grants_relevance_score=85)
    _item(db, source, external_id="B", intelligence_category=IntelligenceCategory.EARLY_SIGNAL, grants_relevance_score=20)
    # Not from Grants.gov (no score at all) — never excluded by this filter.
    _item(db, source, external_id="C", intelligence_category=IntelligenceCategory.EARLY_SIGNAL, grants_relevance_score=None)

    summary = build_dashboard_summary(db, user)

    assert summary.intelligence.early_signal_count == 2  # A (relevant) + C (unscored, not Grants.gov) — not B


def test_high_priority_signals_excludes_promoted_and_unscored_items(db):
    user = db.query(User).first()
    existing_opp = db.query(Opportunity).first()
    source = _source(db)
    _item(db, source, external_id="A", early_signal_score=90)  # unpromoted, scored -> included
    _item(db, source, external_id="B", early_signal_score=40)  # lower score, still included but ranked lower
    _item(db, source, external_id="C", early_signal_score=None)  # unscored -> excluded
    _item(db, source, external_id="D", early_signal_score=95, opportunity_id=existing_opp.id)  # promoted -> excluded
    _item(db, source, external_id="E", early_signal_score=80, intelligence_category=IntelligenceCategory.LIVE_OPPORTUNITY)  # wrong category -> excluded

    summary = build_dashboard_summary(db, user)

    external_ids = [i.external_id for i in summary.high_priority_signals]
    assert external_ids == ["A", "B"]


def test_high_priority_signals_excludes_low_relevance_grants_items(db):
    # A Grants.gov record can carry a high early_signal_score (how likely to become a
    # real procurement) while still being topically irrelevant to Principal (low
    # grants_relevance_score) — this widget must respect the relevance floor too, not
    # just early_signal_score, the same way the intelligence KPI counts do above.
    user = db.query(User).first()
    source = _source(db)
    _item(db, source, external_id="A", early_signal_score=90, grants_relevance_score=85)  # relevant -> included
    _item(db, source, external_id="B", early_signal_score=95, grants_relevance_score=10)  # irrelevant -> excluded despite high signal score
    _item(db, source, external_id="C", early_signal_score=70, grants_relevance_score=None)  # not Grants.gov -> included

    summary = build_dashboard_summary(db, user)

    external_ids = {i.external_id for i in summary.high_priority_signals}
    assert external_ids == {"A", "C"}
