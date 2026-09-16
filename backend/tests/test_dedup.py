from datetime import datetime, timedelta, timezone

from app.models.enums import ConnectorType, DedupStatus, IntelligenceCategory, JurisdictionLevel
from app.models.intelligence import IntelligenceItem, IntelligenceSource, ProjectCluster
from app.models.user import User
from app.services.dedup import confirm_cluster, find_and_cluster_candidates, reject_cluster

NOW = datetime.now(timezone.utc)


def _source(db, name="Test Source"):
    src = IntelligenceSource(name=name, jurisdiction_level=JurisdictionLevel.FEDERAL, connector_type=ConnectorType.API)
    db.add(src)
    db.flush()
    return src


def _item(db, source, **overrides):
    defaults = dict(
        intelligence_source_id=source.id,
        external_id=overrides.pop("external_id", f"EXT-{id(overrides)}"),
        title="Drainage Improvements Phase 1",
        intelligence_category=IntelligenceCategory.EARLY_SIGNAL,
        source=source.name,
        retrieved_at=NOW,
        location_state="LA",
        agency_name="USACE New Orleans District",
    )
    defaults.update(overrides)
    item = IntelligenceItem(**defaults)
    db.add(item)
    db.flush()
    return item


def test_identifier_exact_match_clusters_as_likely(db):
    source = _source(db)
    a = _item(db, source, external_id="A", solicitation_number="W912P8-24-R-0001")
    b = _item(db, source, external_id="B", title="Completely different title", solicitation_number="w912p8-24-r-0001")

    find_and_cluster_candidates(db, b)

    assert b.dedup_status == DedupStatus.LIKELY_DUPLICATE
    assert b.project_cluster_id is not None
    assert b.project_cluster_id == a.project_cluster_id
    assert "solicitation number" in b.dedup_match_reason.lower()


def test_high_title_similarity_same_agency_state_is_likely(db):
    source = _source(db)
    a = _item(db, source, external_id="A", title="St. Tammany Parish Drainage Improvements Phase 1")
    b = _item(db, source, external_id="B", title="St Tammany Parish Drainage Improvements Phase 1 ")

    find_and_cluster_candidates(db, b)

    assert b.dedup_status == DedupStatus.LIKELY_DUPLICATE
    assert b.project_cluster_id == a.project_cluster_id


def test_moderate_similarity_with_close_dates_is_possible(db):
    source = _source(db)
    a = _item(
        db, source, external_id="A", title="Slidell Pump Station Rehabilitation",
        proposal_due_at=NOW + timedelta(days=30),
    )
    b = _item(
        db, source, external_id="B", title="Pump Station Rehab Project near Slidell area",
        proposal_due_at=NOW + timedelta(days=35),
    )

    find_and_cluster_candidates(db, b)

    assert b.dedup_status == DedupStatus.POSSIBLE_DUPLICATE
    assert b.project_cluster_id == a.project_cluster_id


def test_moderate_similarity_without_close_dates_does_not_cluster(db):
    source = _source(db)
    _item(
        db, source, external_id="A", title="Slidell Pump Station Rehabilitation",
        proposal_due_at=NOW + timedelta(days=30),
    )
    b = _item(
        db, source, external_id="B", title="Pump Station Rehab Project near Slidell area",
        proposal_due_at=None,
    )

    find_and_cluster_candidates(db, b)

    assert b.dedup_status == DedupStatus.UNCLUSTERED
    assert b.project_cluster_id is None


def test_reordered_words_still_match_as_likely(db):
    # Two sources rarely phrase the same project identically — this is the realistic
    # case the plain difflib ratio alone was too strict for (character-sequence
    # matching penalizes reordering heavily even when every word matches).
    source = _source(db)
    a = _item(db, source, external_id="A", title="Slidell Pump Station Rehabilitation Project")
    b = _item(db, source, external_id="B", title="Pump Station Rehabilitation, City of Slidell")

    find_and_cluster_candidates(db, b)

    assert b.dedup_status == DedupStatus.LIKELY_DUPLICATE
    assert b.project_cluster_id == a.project_cluster_id


def test_different_agency_and_state_does_not_cluster(db):
    source = _source(db)
    _item(db, source, external_id="A", title="Drainage Improvements Phase 1", location_state="LA", agency_name="USACE New Orleans District")
    b = _item(db, source, external_id="B", title="Drainage Improvements Phase 1", location_state="MS", agency_name="Mississippi DOT")

    find_and_cluster_candidates(db, b)

    assert b.dedup_status == DedupStatus.UNCLUSTERED


def test_already_clustered_item_is_not_reprocessed(db):
    source = _source(db)
    cluster = ProjectCluster(representative_title="Existing cluster")
    db.add(cluster)
    db.flush()
    item = _item(db, source, external_id="A", project_cluster_id=cluster.id, dedup_status=DedupStatus.CONFIRMED_SAME_PROJECT)

    find_and_cluster_candidates(db, item)  # should be a no-op — must not touch an already-decided item

    assert item.dedup_status == DedupStatus.CONFIRMED_SAME_PROJECT
    assert item.project_cluster_id == cluster.id


def test_linking_never_downgrades_an_existing_confirmed_match(db):
    source = _source(db)
    cluster = ProjectCluster(representative_title="Confirmed project")
    db.add(cluster)
    db.flush()
    a = _item(
        db, source, external_id="A", title="Confirmed Levee Repair",
        project_cluster_id=cluster.id, dedup_status=DedupStatus.CONFIRMED_SAME_PROJECT,
    )
    b = _item(db, source, external_id="B", title="Confirmed Levee Repai")  # near-identical title -> LIKELY match

    find_and_cluster_candidates(db, b)

    assert a.dedup_status == DedupStatus.CONFIRMED_SAME_PROJECT  # unchanged, not downgraded
    assert b.project_cluster_id == cluster.id
    assert b.dedup_status == DedupStatus.LIKELY_DUPLICATE


def test_confirm_cluster_sets_status_and_cluster_metadata(db):
    source = _source(db)
    user = db.query(User).first()
    cluster = ProjectCluster(representative_title="Needs confirmation")
    db.add(cluster)
    db.flush()
    item = _item(db, source, external_id="A", project_cluster_id=cluster.id, dedup_status=DedupStatus.LIKELY_DUPLICATE)

    confirm_cluster(db, item, user.id if user else None)

    assert item.dedup_status == DedupStatus.CONFIRMED_SAME_PROJECT
    db.refresh(cluster)
    assert cluster.confirmed_at is not None


def test_reject_cluster_detaches_only_the_one_item(db):
    source = _source(db)
    cluster = ProjectCluster(representative_title="Wrongly grouped")
    db.add(cluster)
    db.flush()
    a = _item(db, source, external_id="A", project_cluster_id=cluster.id, dedup_status=DedupStatus.LIKELY_DUPLICATE)
    b = _item(db, source, external_id="B", project_cluster_id=cluster.id, dedup_status=DedupStatus.LIKELY_DUPLICATE)

    reject_cluster(db, b)

    assert b.project_cluster_id is None
    assert b.dedup_status == DedupStatus.UNCLUSTERED
    assert a.project_cluster_id == cluster.id  # untouched
    assert a.dedup_status == DedupStatus.LIKELY_DUPLICATE  # untouched
