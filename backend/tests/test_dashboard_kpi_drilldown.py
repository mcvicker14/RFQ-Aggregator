"""Proves the "critical data rule" behind the Dashboard's clickable KPIs: the exact
predicate build_dashboard_summary() uses to compute a KPI's count
(app/services/dashboard_filters.py) is what the Opportunities route's `kpi` query
param applies, so a Dashboard number and the record set behind its "click to view"
link can never drift apart. See dashboard_filters.py's own module docstring.
"""
import pytest
from fastapi.testclient import TestClient

from app.core.deps import get_current_user
from app.db.session import get_db
from app.main import app
from app.models.enums import OpportunityStatus, UserRole
from app.models.opportunity import Opportunity
from app.models.pipeline import PipelineStage
from app.models.user import User
from app.services.app_settings import HIDE_SAMPLE_DATA_KEY, set_setting
from app.services.dashboard import build_dashboard_summary
from app.services.dashboard_filters import KPI_FILTER_NAMES

# Maps every named kpi filter to the exact KpiCards field build_dashboard_summary()
# computes it from -- kept next to KPI_FILTER_NAMES so a new kpi value added there
# fails test_every_kpi_filter_name_is_covered_by_this_test_file until it's wired in
# here too, rather than silently shipping without a drift check.
_KPI_TO_SUMMARY_FIELD = {
    "due_soon": lambda s: s.kpis.due_within_30_days,
    "awaiting_go_no_go": lambda s: s.kpis.awaiting_go_no_go,
    "active_proposals": lambda s: s.kpis.active_proposals,
    "interviews_pending": lambda s: s.kpis.interviews_pending,
    "awards_pending": lambda s: s.kpis.awards_pending,
    "sdvosb": lambda s: s.kpis.sdvosb_setaside_count,
    "limited_competition": lambda s: s.kpis.sole_source_or_limited_competition_count,
    "recompete": lambda s: s.kpis.recompete_count,
    "early_stage": lambda s: s.kpis.early_stage_count,
    "discovered_this_week": lambda s: s.kpis.discovered_this_week,
}


@pytest.fixture()
def client(db):
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: User(
        id=None, email="test@example.com", full_name="Test", hashed_password="x",
        role=UserRole.VIEWER, is_active=True,
    )
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def test_every_kpi_filter_name_is_covered_by_this_test_file():
    assert set(_KPI_TO_SUMMARY_FIELD) == KPI_FILTER_NAMES


@pytest.mark.parametrize("kpi", sorted(KPI_FILTER_NAMES))
def test_kpi_drilldown_count_matches_dashboard_count_on_ambient_data(client, db, kpi):
    # Against whatever the seeded sample pipeline happens to contain right now -- the
    # invariant under test (dashboard count == drill-down count) has to hold no matter
    # what the data looks like, not just in one hand-picked scenario.
    user = db.query(User).first()
    summary = build_dashboard_summary(db, user)
    expected = _KPI_TO_SUMMARY_FIELD[kpi](summary)

    response = client.get("/api/opportunities", params={"kpi": kpi, "limit": 2000})

    assert response.status_code == 200
    assert len(response.json()) == expected


def test_sdvosb_kpi_drilldown_matches_a_deterministic_nonzero_count(client, db):
    opps = db.query(Opportunity).limit(3).all()
    assert len(opps) >= 2
    db.execute(Opportunity.__table__.update().values(is_sdvosb_setaside=False))
    for opp in opps[:2]:
        opp.is_sdvosb_setaside = True
    db.commit()

    summary = build_dashboard_summary(db, db.query(User).first())
    assert summary.kpis.sdvosb_setaside_count == 2

    response = client.get("/api/opportunities", params={"kpi": "sdvosb", "limit": 2000})
    assert len(response.json()) == 2


def test_recompete_kpi_drilldown_matches_zero_count(client, db):
    # The zero-count case: a clickable KPI card only stays safely non-interactive at
    # count 0 if 0 truly means an empty result set, never a hidden truncation.
    db.execute(Opportunity.__table__.update().values(incumbent_company_id=None))
    db.commit()

    summary = build_dashboard_summary(db, db.query(User).first())
    assert summary.kpis.recompete_count == 0

    response = client.get("/api/opportunities", params={"kpi": "recompete", "limit": 2000})
    assert response.status_code == 200
    assert response.json() == []


def test_awaiting_go_no_go_kpi_drilldown_matches_stage_based_count(client, db):
    # The one compound predicate (spans Opportunity + PipelineStage + GoNoGoReview) --
    # exercised via awaiting_go_no_go_clause() on both sides, not just the simpler
    # single-column filters the other kpi values use.
    stage = db.query(PipelineStage).filter(PipelineStage.name == "Go/No-Go").first()
    assert stage is not None
    opp = db.query(Opportunity).first()
    opp.pipeline_stage_id = stage.id
    db.commit()

    summary = build_dashboard_summary(db, db.query(User).first())
    expected = summary.kpis.awaiting_go_no_go
    assert expected >= 1

    response = client.get("/api/opportunities", params={"kpi": "awaiting_go_no_go", "limit": 2000})
    assert len(response.json()) == expected


def test_invalid_kpi_value_is_rejected(client, db):
    response = client.get("/api/opportunities", params={"kpi": "not_a_real_kpi"})
    assert response.status_code == 422


def test_kpi_filter_composes_with_other_filters(client, db):
    # A Dashboard drill-down link only ever sets `kpi` (+ include_sample_data), but the
    # destination page's own manual filters must still AND with it, not replace it --
    # otherwise "narrow further" on a filtered page would silently widen back out.
    db.execute(Opportunity.__table__.update().values(is_sdvosb_setaside=False))
    opp = db.query(Opportunity).first()
    opp.is_sdvosb_setaside = True
    opp.title = "Unique Composable Filter Title"
    db.commit()

    matching = client.get("/api/opportunities", params={"kpi": "sdvosb", "q": "Unique Composable Filter Title"})
    nonmatching = client.get("/api/opportunities", params={"kpi": "sdvosb", "q": "Definitely Not A Real Title"})

    assert len(matching.json()) == 1
    assert len(nonmatching.json()) == 0


def test_include_samples_reflects_admin_setting_and_flows_into_drilldown(client, db):
    # Turn on the admin "hide sample data by default" setting, then verify: (1) the
    # Dashboard's own summary excludes sample-data opportunities and reports
    # include_samples=False, and (2) the Opportunities route, given that exact
    # include_samples value (as the frontend always does, never a hardcoded default),
    # returns the identical count -- proving the two can't drift even when this
    # setting is flipped after the frontend's own default was chosen.
    opp = db.query(Opportunity).first()
    opp.is_sample_data = True
    db.commit()
    set_setting(db, HIDE_SAMPLE_DATA_KEY, True, None)

    summary = build_dashboard_summary(db, db.query(User).first())
    assert summary.include_samples is False

    expected_total = db.query(Opportunity).filter(
        Opportunity.status == OpportunityStatus.ACTIVE, Opportunity.is_sample_data.is_(False)
    ).count()
    assert summary.kpis.total_active_opportunities == expected_total

    response = client.get(
        "/api/opportunities", params={"limit": 2000, "include_sample_data": summary.include_samples}
    )
    assert len(response.json()) == expected_total
