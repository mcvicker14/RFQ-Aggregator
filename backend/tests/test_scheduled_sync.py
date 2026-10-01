"""Tests for the scheduling layer that's new in this change: COREWORKS RFQwire's
rolling polling interval and APEX MyBidMatch's daily 6:00 PM America/Chicago sync (see
app/services/scheduled_sync.py's module docstring for the three-layer design this is
part of — this file covers the pure decision functions, the orchestrator that applies
them against real seeded sources, and the shared-secret-authenticated route an external
scheduler calls).

The DST-correctness tests are the reason this schedule uses zoneinfo instead of a fixed
UTC-offset cron expression: 6:00 PM America/Chicago is UTC-6 (00:00 UTC next day) in
January and UTC-5 (23:00 UTC same day) in July, a full hour apart in UTC terms for the
exact same local wall-clock trigger time.
"""
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.config import get_settings
from app.db.session import get_db
from app.main import app
from app.models.enums import SyncRunStatus, SyncTriggeredBy
from app.models.intelligence import IntelligenceSource, IntelligenceSyncRun
from app.services.scheduled_sync import (
    APEX_SYNC_HOUR_LOCAL,
    CENTRAL_TZ,
    SCHEDULED_SOURCE_NAMES,
    run_due_scheduled_syncs,
    should_run_apex_sync_now,
    should_run_polling_sync_now,
)
from app.connectors.registry import get_intelligence_connector
from app.connectors.base import RawIntelligenceItem
from seed.intelligence_sources import seed_intelligence_sources

WINTER_CST = (2026, 1, 15)  # America/Chicago is UTC-6 here — no DST
SUMMER_CDT = (2026, 7, 15)  # America/Chicago is UTC-5 here — DST in effect


def _local(date_tuple, hour, minute=0) -> datetime:
    year, month, day = date_tuple
    return datetime(year, month, day, hour, minute, tzinfo=CENTRAL_TZ).astimezone(timezone.utc)


# --- should_run_apex_sync_now(): pure function, both DST regimes -------------------

def test_before_6pm_local_is_never_due_in_either_dst_regime():
    for regime in (WINTER_CST, SUMMER_CDT):
        assert should_run_apex_sync_now(_local(regime, 17, 59), None) is False


def test_at_6pm_local_with_no_prior_run_is_due_in_either_dst_regime():
    for regime in (WINTER_CST, SUMMER_CDT):
        assert should_run_apex_sync_now(_local(regime, APEX_SYNC_HOUR_LOCAL, 0), None) is True


def test_after_6pm_local_already_run_earlier_today_is_not_due_again():
    for regime in (WINTER_CST, SUMMER_CDT):
        last_run = _local(regime, 18, 0)
        later_same_day = _local(regime, 23, 30)
        assert should_run_apex_sync_now(later_same_day, last_run) is False


def test_after_6pm_local_last_run_was_a_prior_calendar_day_is_due_again():
    for regime in (WINTER_CST, SUMMER_CDT):
        year, month, day = regime
        last_run = _local(regime, 18, 5)
        next_day_6pm = datetime(year, month, day + 1, APEX_SYNC_HOUR_LOCAL, 0, tzinfo=CENTRAL_TZ).astimezone(timezone.utc)
        assert should_run_apex_sync_now(next_day_6pm, last_run) is True


def test_shortly_after_midnight_is_not_due_even_if_24_hours_have_passed_since_last_run():
    # Clock-time based, not interval-based: a run at 6:05pm yesterday does NOT make
    # 12:30am today "due" even though >24h haven't yet elapsed — it's just before
    # today's 6pm local threshold. Distinguishes this from should_run_polling_sync_now.
    last_run = _local(WINTER_CST, 18, 5)
    early_next_morning = datetime(2026, 1, 16, 0, 30, tzinfo=CENTRAL_TZ).astimezone(timezone.utc)
    assert should_run_apex_sync_now(early_next_morning, last_run) is False


def test_the_same_utc_instant_is_treated_differently_depending_on_the_local_calendar_date():
    # Sanity-checks that this is genuinely computing America/Chicago's own calendar
    # day, not doing UTC-day arithmetic that happens to look similar.
    utc_instant = datetime(2026, 1, 16, 1, 0, tzinfo=timezone.utc)  # 7:00pm Jan 15 Central (CST)
    assert utc_instant.astimezone(CENTRAL_TZ).date() == datetime(2026, 1, 15).date()
    assert should_run_apex_sync_now(utc_instant, None) is True


# --- should_run_polling_sync_now(): COREWORKS's rolling-interval gate ---------------

def test_polling_with_no_frequency_configured_is_never_due():
    now = datetime.now(timezone.utc)
    assert should_run_polling_sync_now(now, None, None) is False
    assert should_run_polling_sync_now(now, None, 0) is False


def test_polling_with_no_prior_run_is_immediately_due():
    now = datetime.now(timezone.utc)
    assert should_run_polling_sync_now(now, None, 3) is True


def test_polling_before_the_interval_has_elapsed_is_not_due():
    now = datetime.now(timezone.utc)
    last_run = now - timedelta(hours=2)
    assert should_run_polling_sync_now(now, last_run, 3) is False


def test_polling_at_or_after_the_interval_has_elapsed_is_due():
    now = datetime.now(timezone.utc)
    assert should_run_polling_sync_now(now, now - timedelta(hours=3), 3) is True  # exact boundary
    assert should_run_polling_sync_now(now, now - timedelta(hours=5), 3) is True


# --- run_due_scheduled_syncs(): real seeded sources, connectors' HTTP layer mocked --

def _empty_raw_items(since, **filters) -> list[RawIntelligenceItem]:
    return []


def _seed_and_mock(db, monkeypatch):
    seed_intelligence_sources(db)
    # last_attempted_sync_at is runtime state seed_intelligence_sources() deliberately
    # never overwrites on an existing row (same reason as polling_frequency_hours in
    # test_coreworks_uses_its_own_polling_frequency_not_the_apex_clock_gate below) --
    # this shared dev database's two real source rows carry a REAL, recent timestamp
    # from actual manual "Sync Now" verification clicks, which is later than every
    # fixed WINTER_CST/SUMMER_CDT test date below and would make a "never synced, due
    # now" test scenario spuriously look "already synced today, not due." Reset to a
    # guaranteed-clean baseline so every test in this file is independent of whatever
    # this database's rows happen to carry already.
    for name in SCHEDULED_SOURCE_NAMES:
        db.execute(
            select(IntelligenceSource).where(IntelligenceSource.name == name)
        ).scalars().one().last_attempted_sync_at = None
    monkeypatch.setattr(get_intelligence_connector("gmail_coreworks"), "fetch", _empty_raw_items)
    monkeypatch.setattr(get_intelligence_connector("web_apex_mybidmatch"), "fetch", _empty_raw_items)


def _source(db, name: str) -> IntelligenceSource:
    return db.execute(select(IntelligenceSource).where(IntelligenceSource.name == name)).scalars().one()


def test_only_the_two_scheduled_sources_are_ever_considered(db, monkeypatch):
    _seed_and_mock(db, monkeypatch)
    due_now = _local(WINTER_CST, APEX_SYNC_HOUR_LOCAL, 5)  # APEX due; COREWORKS (never-run) also due

    results = run_due_scheduled_syncs(db, now=due_now)

    assert {r["source"] for r in results} == set(SCHEDULED_SOURCE_NAMES)
    assert "SAM.gov" not in {r["source"] for r in results}
    assert "Grants.gov" not in {r["source"] for r in results}


def test_apex_actually_runs_via_the_real_run_sync_pipeline_when_due(db, monkeypatch):
    _seed_and_mock(db, monkeypatch)
    apex = _source(db, "APEX MyBidMatch")
    assert apex.last_attempted_sync_at is None

    results = run_due_scheduled_syncs(db, now=_local(WINTER_CST, APEX_SYNC_HOUR_LOCAL, 5))

    apex_result = next(r for r in results if r["source"] == "APEX MyBidMatch")
    assert apex_result["ran"] is True

    # Most recent run, not .one() -- this shared dev database's real APEX source row
    # may already carry sync history from actual manual "Sync Now" activity outside
    # this test's own transaction (same reason last_attempted_sync_at is reset above);
    # what this test needs to confirm is only that THIS call produced a new run shaped
    # the way the real pipeline produces one.
    run = db.execute(
        select(IntelligenceSyncRun)
        .where(IntelligenceSyncRun.intelligence_source_id == apex.id)
        .order_by(IntelligenceSyncRun.started_at.desc())
        .limit(1)
    ).scalars().one()
    assert run.triggered_by == SyncTriggeredBy.SCHEDULED
    assert run.status == SyncRunStatus.SUCCESS
    db.refresh(apex)
    assert apex.last_attempted_sync_at is not None  # what makes the next check's "not due again today" true


def test_apex_not_yet_due_before_6pm_local_is_skipped_with_a_reason(db, monkeypatch):
    _seed_and_mock(db, monkeypatch)
    results = run_due_scheduled_syncs(db, now=_local(WINTER_CST, 12, 0))
    apex_result = next(r for r in results if r["source"] == "APEX MyBidMatch")
    assert apex_result["ran"] is False
    assert "not due" in apex_result["reason"].lower()


def test_coreworks_uses_its_own_polling_frequency_not_the_apex_clock_gate(db, monkeypatch):
    _seed_and_mock(db, monkeypatch)
    coreworks = _source(db, "COREWORKS RFQwire")
    # polling_frequency_hours is runtime/admin state seed_intelligence_sources()
    # deliberately never overwrites on an existing row (see its own module docstring)
    # — set explicitly here so this test exercises the scheduling behavior for a
    # properly-configured row regardless of whatever this shared dev database's row
    # happens to carry already.
    coreworks.polling_frequency_hours = 3
    db.flush()

    # COREWORKS has no 6pm gate — any time of day, with no prior run, it's due.
    results = run_due_scheduled_syncs(db, now=_local(WINTER_CST, 9, 0))
    coreworks_result = next(r for r in results if r["source"] == "COREWORKS RFQwire")
    assert coreworks_result["ran"] is True


def test_disabled_source_is_skipped_even_when_otherwise_due(db, monkeypatch):
    _seed_and_mock(db, monkeypatch)
    apex = _source(db, "APEX MyBidMatch")
    apex.is_enabled = False
    db.flush()

    results = run_due_scheduled_syncs(db, now=_local(WINTER_CST, APEX_SYNC_HOUR_LOCAL, 5))
    apex_result = next(r for r in results if r["source"] == "APEX MyBidMatch")
    assert apex_result["ran"] is False
    assert "disabled" in apex_result["reason"].lower()


def test_a_sync_already_running_is_reported_not_raised(db, monkeypatch):
    _seed_and_mock(db, monkeypatch)
    apex = _source(db, "APEX MyBidMatch")
    db.add(IntelligenceSyncRun(
        intelligence_source_id=apex.id, started_at=datetime.now(timezone.utc),
        status=SyncRunStatus.RUNNING, triggered_by=SyncTriggeredBy.MANUAL,
    ))
    db.flush()

    results = run_due_scheduled_syncs(db, now=_local(WINTER_CST, APEX_SYNC_HOUR_LOCAL, 5))
    apex_result = next(r for r in results if r["source"] == "APEX MyBidMatch")
    assert apex_result["ran"] is False
    assert "already in progress" in apex_result["reason"].lower()


def test_defaults_now_to_the_real_current_time_when_omitted(db, monkeypatch):
    _seed_and_mock(db, monkeypatch)
    results = run_due_scheduled_syncs(db)  # must not raise
    assert {r["source"] for r in results} == set(SCHEDULED_SOURCE_NAMES)


# --- POST /api/intelligence/scheduled-sync-check: shared-secret-authenticated route -

def _client(db):
    app.dependency_overrides[get_db] = lambda: db
    return TestClient(app)


def test_route_reports_503_when_secret_is_not_configured(db, monkeypatch):
    monkeypatch.setattr(get_settings(), "SCHEDULED_SYNC_SECRET", None)
    try:
        response = _client(db).post("/api/intelligence/scheduled-sync-check", json={})
        assert response.status_code == 503
    finally:
        app.dependency_overrides.clear()


def test_route_rejects_wrong_secret_with_401(db, monkeypatch):
    monkeypatch.setattr(get_settings(), "SCHEDULED_SYNC_SECRET", "correct-secret")
    try:
        response = _client(db).post("/api/intelligence/scheduled-sync-check", json={"secret": "wrong"})
        assert response.status_code == 401
    finally:
        app.dependency_overrides.clear()


def test_route_rejects_missing_secret_with_401_when_one_is_configured(db, monkeypatch):
    monkeypatch.setattr(get_settings(), "SCHEDULED_SYNC_SECRET", "correct-secret")
    try:
        response = _client(db).post("/api/intelligence/scheduled-sync-check", json={})
        assert response.status_code == 401
    finally:
        app.dependency_overrides.clear()


def test_route_runs_due_syncs_and_returns_results_with_the_correct_secret(db, monkeypatch):
    _seed_and_mock(db, monkeypatch)
    monkeypatch.setattr(get_settings(), "SCHEDULED_SYNC_SECRET", "correct-secret")
    try:
        response = _client(db).post("/api/intelligence/scheduled-sync-check", json={"secret": "correct-secret"})
        assert response.status_code == 200
        body = response.json()
        assert "checked_at" in body
        assert {r["source"] for r in body["results"]} == set(SCHEDULED_SOURCE_NAMES)
    finally:
        app.dependency_overrides.clear()


def test_route_never_leaks_the_secret_back_in_the_response(db, monkeypatch):
    _seed_and_mock(db, monkeypatch)
    monkeypatch.setattr(get_settings(), "SCHEDULED_SYNC_SECRET", "super-secret-value")
    try:
        response = _client(db).post("/api/intelligence/scheduled-sync-check", json={"secret": "super-secret-value"})
        assert "super-secret-value" not in response.text
    finally:
        app.dependency_overrides.clear()
