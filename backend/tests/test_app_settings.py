from app.models.enums import OpportunityStatus
from app.models.opportunity import Opportunity
from app.services.app_settings import HIDE_SAMPLE_DATA_KEY, get_setting, hide_sample_data_by_default, set_setting
from app.services.dashboard import build_dashboard_summary


def test_get_setting_returns_default_when_unset(db):
    assert get_setting(db, "some_key_never_set", "the_default") == "the_default"


def test_set_then_get_setting_round_trips(db):
    set_setting(db, "a_test_key", {"nested": True}, updated_by_user_id=None)
    assert get_setting(db, "a_test_key", None) == {"nested": True}


def test_set_setting_is_upsert_not_duplicate(db):
    set_setting(db, HIDE_SAMPLE_DATA_KEY, True, None)
    set_setting(db, HIDE_SAMPLE_DATA_KEY, False, None)
    assert hide_sample_data_by_default(db) is False


def test_hide_sample_data_defaults_to_false(db):
    assert hide_sample_data_by_default(db) is False


def test_dashboard_includes_sample_opportunities_by_default(db):
    summary = build_dashboard_summary(db)
    sample_count = db.query(Opportunity).filter_by(is_sample_data=True).count()
    assert sample_count > 0  # sanity: the seeded sample data is actually there
    assert summary.kpis.total_active_opportunities >= sample_count


def test_dashboard_excludes_sample_opportunities_when_setting_enabled(db):
    baseline = build_dashboard_summary(db)

    set_setting(db, HIDE_SAMPLE_DATA_KEY, True, None)
    summary = build_dashboard_summary(db)

    live_active_count = db.query(Opportunity).filter_by(is_sample_data=False, status=OpportunityStatus.ACTIVE).count()
    assert summary.kpis.total_active_opportunities == live_active_count
    assert summary.kpis.total_active_opportunities < baseline.kpis.total_active_opportunities
