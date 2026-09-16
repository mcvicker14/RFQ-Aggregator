from datetime import datetime, timedelta, timezone

import pytest

from app.connectors import registry
from app.connectors.base import IntelligenceConnector, RawIntelligenceItem
from app.models.enums import (
    ConnectorType,
    IntelligenceCategory,
    JurisdictionLevel,
    SetAsideType,
    SourceHealthStatus,
    SyncRunStatus,
    SyncTriggeredBy,
)
from app.models.intelligence import IntelligenceItem, IntelligenceSource, IntelligenceSyncRun
from app.models.opportunity import Opportunity
from app.services.intelligence_sync import SyncAlreadyRunningError, _validate_connector_fields, run_sync

NOW = datetime.now(timezone.utc)


class FakeConnector(IntelligenceConnector):
    key = "fake_source"
    name = "Fake Source"
    default_category = IntelligenceCategory.LIVE_OPPORTUNITY

    def __init__(self):
        self.items: list[RawIntelligenceItem] = []
        self.configured = True
        self.raise_on_fetch: Exception | None = None

    def is_configured(self) -> bool:
        return self.configured

    def fetch(self, since, **filters):
        if self.raise_on_fetch:
            raise self.raise_on_fetch
        return self.items


def _raw_item(external_id, category=IntelligenceCategory.LIVE_OPPORTUNITY, **fields):
    fields.setdefault("title", f"Test Opportunity {external_id}")
    return RawIntelligenceItem(
        external_id=external_id, intelligence_category=category,
        source_url=f"https://example.gov/{external_id}", retrieved_at=NOW, fields=fields,
    )


@pytest.fixture()
def fake_connector():
    connector = FakeConnector()
    registry._INTELLIGENCE_CONNECTORS[connector.key] = connector
    yield connector
    registry._INTELLIGENCE_CONNECTORS.pop(connector.key, None)


def _source(db, **overrides):
    defaults = dict(
        name="Fake Source", jurisdiction_level=JurisdictionLevel.FEDERAL,
        connector_type=ConnectorType.API, connector_key="fake_source", is_enabled=True,
    )
    defaults.update(overrides)
    src = IntelligenceSource(**defaults)
    db.add(src)
    db.flush()
    return src


def test_happy_path_creates_items_and_promotes_live_opportunities(db, fake_connector):
    source = _source(db)
    fake_connector.items = [
        _raw_item("A", solicitation_number="SOL-1", set_aside=SetAsideType.SDVOSB, location_state="LA"),
        _raw_item("B", category=IntelligenceCategory.EARLY_SIGNAL, location_state="LA"),
    ]

    run = run_sync(db, source, SyncTriggeredBy.MANUAL)

    assert run.status == SyncRunStatus.SUCCESS
    assert run.items_fetched == 2
    assert run.items_created == 2
    assert run.items_errored == 0

    item_a = db.query(IntelligenceItem).filter_by(external_id="A").one()
    item_b = db.query(IntelligenceItem).filter_by(external_id="B").one()

    assert item_a.opportunity_id is not None  # LIVE_OPPORTUNITY -> promoted
    opp = db.get(Opportunity, item_a.opportunity_id)
    assert opp.solicitation_number == "SOL-1"
    assert opp.is_sdvosb_setaside is True

    assert item_b.opportunity_id is None  # EARLY_SIGNAL -> never promoted

    assert source.health_status == SourceHealthStatus.HEALTHY
    assert source.last_result_count == 2


def test_resync_updates_existing_item_and_opportunity_not_duplicates(db, fake_connector):
    source = _source(db)
    fake_connector.items = [_raw_item("A", solicitation_number="SOL-1", title="Original Title")]
    run_sync(db, source, SyncTriggeredBy.MANUAL)

    fake_connector.items = [_raw_item("A", solicitation_number="SOL-1", title="Updated Title")]
    run2 = run_sync(db, source, SyncTriggeredBy.MANUAL)

    assert run2.items_created == 0
    assert run2.items_updated == 1
    assert db.query(IntelligenceItem).filter_by(external_id="A").count() == 1
    item = db.query(IntelligenceItem).filter_by(external_id="A").one()
    assert item.title == "Updated Title"
    assert db.query(Opportunity).filter_by(solicitation_number="SOL-1").count() == 1
    opp = db.query(Opportunity).filter_by(solicitation_number="SOL-1").one()
    assert opp.title == "Updated Title"


def test_locked_field_is_not_overwritten_on_resync(db, fake_connector):
    source = _source(db)
    fake_connector.items = [_raw_item("A", solicitation_number="SOL-LOCK", title="Original Title")]
    run_sync(db, source, SyncTriggeredBy.MANUAL)

    opp = db.query(Opportunity).filter_by(solicitation_number="SOL-LOCK").one()
    opp.locked_fields = ["title"]
    opp.title = "Human-edited title"
    db.commit()

    fake_connector.items = [_raw_item("A", solicitation_number="SOL-LOCK", title="Source tried to overwrite this")]
    run_sync(db, source, SyncTriggeredBy.MANUAL)

    db.refresh(opp)
    assert opp.title == "Human-edited title"


def test_connector_not_configured_marks_run_and_source(db, fake_connector):
    source = _source(db)
    fake_connector.configured = False

    run = run_sync(db, source, SyncTriggeredBy.MANUAL)

    assert run.status == SyncRunStatus.FAILURE
    assert source.health_status == SourceHealthStatus.NEEDS_CONFIGURATION
    assert "not configured" in run.error_detail.lower()


def test_fetch_failure_does_not_raise_and_marks_source_failing(db, fake_connector):
    source = _source(db)
    fake_connector.raise_on_fetch = ConnectionError("simulated network failure")

    run = run_sync(db, source, SyncTriggeredBy.MANUAL)  # must not raise

    assert run.status == SyncRunStatus.FAILURE
    assert source.health_status == SourceHealthStatus.FAILING
    assert "simulated network failure" in run.error_detail


def test_one_bad_item_is_skipped_without_failing_the_rest(db, fake_connector):
    source = _source(db)
    fake_connector.items = [
        _raw_item("GOOD-1"),
        _raw_item("BAD-1", this_is_not_a_real_column="boom"),  # TypeError on construction
        _raw_item("GOOD-2"),
    ]

    run = run_sync(db, source, SyncTriggeredBy.MANUAL)

    assert run.status == SyncRunStatus.PARTIAL_FAILURE
    assert run.items_created == 2
    assert run.items_errored == 1
    assert db.query(IntelligenceItem).filter_by(external_id="GOOD-1").count() == 1
    assert db.query(IntelligenceItem).filter_by(external_id="GOOD-2").count() == 1
    assert db.query(IntelligenceItem).filter_by(external_id="BAD-1").count() == 0


def test_concurrency_guard_blocks_overlapping_sync(db, fake_connector):
    source = _source(db)
    db.add(IntelligenceSyncRun(
        intelligence_source_id=source.id, started_at=datetime.now(timezone.utc),
        status=SyncRunStatus.RUNNING, triggered_by=SyncTriggeredBy.MANUAL,
    ))
    db.commit()

    with pytest.raises(SyncAlreadyRunningError):
        run_sync(db, source, SyncTriggeredBy.MANUAL)


def test_stale_running_run_outside_guard_window_does_not_block(db, fake_connector):
    source = _source(db)
    stale_start = datetime.now(timezone.utc) - timedelta(minutes=30)
    db.add(IntelligenceSyncRun(
        intelligence_source_id=source.id, started_at=stale_start,
        status=SyncRunStatus.RUNNING, triggered_by=SyncTriggeredBy.MANUAL,
    ))
    db.commit()
    fake_connector.items = [_raw_item("A")]

    run = run_sync(db, source, SyncTriggeredBy.MANUAL)  # must not raise

    assert run.status == SyncRunStatus.SUCCESS


def test_unregistered_connector_key_raises_value_error(db):
    source = _source(db, connector_key="does_not_exist_yet")

    with pytest.raises(ValueError):
        run_sync(db, source, SyncTriggeredBy.MANUAL)


# --- Shared dict/list-into-non-JSONB-column defense --------------------------------
#
# Production once hit psycopg.ProgrammingError: cannot adapt type 'dict' because a
# connector (USAspending) handed a nested object straight through to a VARCHAR
# column. The USAspending-specific fix lives in app/connectors/usaspending.py, but
# this defense in _upsert_intelligence_item protects every connector — current and
# future — from the same failure mode. These tests use a generic FakeConnector, not
# USAspending, to prove that.

def test_validate_connector_fields_raises_specific_error_for_dict_in_non_jsonb_column():
    with pytest.raises(ValueError, match="agency_name"):
        _validate_connector_fields("Test Source", {"agency_name": {"name": "Department of Defense"}})


def test_validate_connector_fields_allows_dict_in_a_real_jsonb_column():
    _validate_connector_fields("Test Source", {"raw_metadata": {"anything": "goes"}})  # must not raise


def test_validate_connector_fields_allows_plain_scalars():
    _validate_connector_fields(
        "Test Source", {"agency_name": "Department of Defense", "estimated_value_high": 100.0, "posted_at": None}
    )  # must not raise


def test_bad_connector_field_type_is_skipped_not_a_raw_db_crash(db, fake_connector):
    """The end-to-end version of the two tests above: run_sync must never surface a
    connector's dict-into-VARCHAR mistake as an uncaught DBAPI error — it's caught and
    isolated exactly like any other single-item mapping failure (same shape as
    test_one_bad_item_is_skipped_without_failing_the_rest above), so one bad item never
    takes down an entire sync."""
    source = _source(db)
    fake_connector.items = [
        _raw_item("GOOD-1"),
        _raw_item("BAD-1", agency_name={"name": "Department of Defense", "agency_slug": "dod"}),
        _raw_item("GOOD-2"),
    ]

    run = run_sync(db, source, SyncTriggeredBy.MANUAL)  # must not raise

    assert run.status == SyncRunStatus.PARTIAL_FAILURE
    assert run.items_created == 2
    assert run.items_errored == 1
    assert db.query(IntelligenceItem).filter_by(external_id="GOOD-1").count() == 1
    assert db.query(IntelligenceItem).filter_by(external_id="GOOD-2").count() == 1
    assert db.query(IntelligenceItem).filter_by(external_id="BAD-1").count() == 0
