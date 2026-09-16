"""Sync orchestration + logging for the intelligence platform. See
docs/PHASE2_ARCHITECTURE.md §7. run_sync() is the one entry point every "Sync Now" /
"Sync All Enabled Sources" action calls — it owns the concurrency guard, per-source
and per-item error isolation (a bad source or a bad item is logged and skipped, never
raised past this function), and IntelligenceSyncRun logging.

promote_intelligence_item() is the Phase 2 equivalent of the pre-Phase-2
ingestion.py::_upsert_opportunity — same locked-fields/agency-resolution/scoring
behavior, reading from an IntelligenceItem instead of a RawOpportunity. It lives here
rather than in ingestion.py because ingestion.py (and the OpportunityConnector
interface it was built for) is retired once SAM.gov migrates onto this pipeline.
"""
import logging
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import inspect as sa_inspect
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Session

from app.connectors.registry import get_intelligence_connector
from app.models.agency import Agency
from app.models.alert import Alert
from app.models.enums import (
    ActivityType,
    AlertCategory,
    IntelligenceCategory,
    MaturityStage,
    OpportunityStatus,
    SetAsideType,
    SourceHealthStatus,
    SyncRunStatus,
    SyncTriggeredBy,
)
from app.models.intelligence import IntelligenceItem, IntelligenceSource, IntelligenceSyncRun
from app.models.opportunity import Opportunity, OpportunitySource
from app.models.pipeline import PipelineStage
from app.services.activities import log_activity
from app.services.dedup import find_and_cluster_candidates
from app.services.early_signal_scoring import calculate_early_signal_score
from app.services.scoring import calculate_score

logger = logging.getLogger(__name__)

CONCURRENCY_GUARD_MINUTES = 15
DEFAULT_SINCE_DAYS = 30

# Fields ingestion is allowed to touch on re-sync. Mirrors ingestion.py's
# SYNCABLE_FIELDS — anything else on Opportunity is either purely internal
# (internal_notes, assigned_user_id) or derived, and is left alone.
SYNCABLE_FIELDS = {
    "title", "solicitation_number", "location_city", "location_state",
    "naics_code", "psc_code", "set_aside", "proposal_due_at",
}

PROMOTABLE_CATEGORIES = {IntelligenceCategory.LIVE_OPPORTUNITY, IntelligenceCategory.PRE_SOLICITATION}


class SyncAlreadyRunningError(RuntimeError):
    """A sync for this source is already RUNNING within the concurrency-guard window."""


def _resolve_agency_for_item(db: Session, item: IntelligenceItem) -> Agency | None:
    if item.agency_id:
        return db.get(Agency, item.agency_id)
    if not item.agency_name:
        return None
    name = item.agency_name.strip()
    agency = db.execute(select(Agency).where(Agency.name == name)).scalars().first()
    if agency is None:
        # Agency has no source/confidence columns — that provenance lives on the
        # OpportunitySource row promote_intelligence_item() writes below, not here.
        agency = Agency(name=name)
        db.add(agency)
        db.flush()
    return agency


def _signal_detected_stage(db: Session) -> PipelineStage | None:
    return db.execute(select(PipelineStage).where(PipelineStage.name == "Signal Detected")).scalars().first()


def promote_intelligence_item(db: Session, item: IntelligenceItem) -> Opportunity | None:
    """Create-or-update the Opportunity this item represents, and write a normal
    OpportunitySource row so the opportunity detail page's existing provenance UI
    needs no changes. No-op (returns None) for EARLY_SIGNAL/AWARD_INTELLIGENCE items —
    those never become a pipeline entry on their own (§2/§5).

    Known limitation, left for later: this does not yet check whether item's
    project_cluster has an already-promoted sibling and attach to that same
    Opportunity — it only matches on solicitation_number/external_id, same as the
    pre-Phase-2 behavior. Cluster-aware promotion is a natural follow-up, not required
    for this pass.
    """
    if item.intelligence_category not in PROMOTABLE_CATEGORIES:
        return None

    existing = db.get(Opportunity, item.opportunity_id) if item.opportunity_id else None
    if existing is None and item.solicitation_number:
        existing = db.execute(
            select(Opportunity).where(Opportunity.solicitation_number == item.solicitation_number)
        ).scalars().first()
    if existing is None:
        existing = db.execute(
            select(Opportunity).where(Opportunity.external_notice_id == item.external_id)
        ).scalars().first()

    agency = _resolve_agency_for_item(db, item)

    if existing is None:
        signal_stage = _signal_detected_stage(db)
        opp = Opportunity(
            title=item.title,
            solicitation_number=item.solicitation_number,
            location_city=item.location_city,
            location_state=item.location_state,
            naics_code=item.naics_code,
            psc_code=item.psc_code,
            set_aside=item.set_aside or SetAsideType.UNRESTRICTED,
            proposal_due_at=item.proposal_due_at,
            opportunity_source_label=item.source,
            external_notice_id=item.external_id,
            agency_id=agency.id if agency else None,
            maturity_stage=item.maturity_stage or MaturityStage.SOLICITATION_RELEASED,
            status=OpportunityStatus.ACTIVE,
            pipeline_stage_id=signal_stage.id if signal_stage else None,
            source=item.source,
            source_url=item.source_url,
            retrieved_at=item.retrieved_at,
            confidence=item.confidence,
            is_sdvosb_setaside=item.set_aside == SetAsideType.SDVOSB,
        )
        db.add(opp)
        db.flush()
        item.opportunity_id = opp.id
        log_activity(
            db, opp.id, ActivityType.INGESTED,
            f"Discovered via {item.source}", extra_data={"external_id": item.external_id},
        )
        db.add(Alert(
            user_id=None, category=AlertCategory.NEW_MATCHING_OPPORTUNITY,
            title=f"New opportunity from {item.source}: {opp.title}",
            body=f"{opp.solicitation_number or 'No solicitation number yet'} — {opp.location_state or 'location TBD'}",
            opportunity_id=opp.id,
        ))
    else:
        changed = False
        for field_name in SYNCABLE_FIELDS:
            if field_name in existing.locked_fields:
                continue
            new_value = getattr(item, field_name, None)
            if new_value is None:
                continue
            if getattr(existing, field_name) != new_value:
                setattr(existing, field_name, new_value)
                changed = True
                if field_name == "set_aside":
                    existing.is_sdvosb_setaside = new_value == SetAsideType.SDVOSB
        item.opportunity_id = existing.id
        if changed:
            existing.retrieved_at = item.retrieved_at
            log_activity(db, existing.id, ActivityType.AMENDED, f"Updated via {item.source} sync")
        opp = existing

    db.add(OpportunitySource(
        opportunity_id=opp.id, source=item.source, source_url=item.source_url,
        retrieved_at=item.retrieved_at, confidence=item.confidence, raw_snapshot=item.raw_metadata,
    ))
    calculate_score(db, opp)
    db.flush()
    return opp


_INTELLIGENCE_ITEM_COLUMNS = {c.key: c for c in sa_inspect(IntelligenceItem).columns}


def _validate_connector_fields(source_name: str, fields: dict) -> None:
    """Defends every connector, not just one, against the failure mode that produced
    `psycopg.ProgrammingError: cannot adapt type 'dict'` in production: a connector
    passing a structured value (a nested object from the source API) straight through
    into a column that isn't JSONB. Left unchecked, that only surfaces as a cryptic
    low-level DBAPI error at db.flush() — this turns it into an immediate, specific
    error naming the connector, the field, and the value, raised before it ever
    reaches the database. A connector fixing its own mapping (extracting a scalar, or
    routing genuinely structured data into raw_metadata) is always the real fix;
    this is the safety net for the next connector that gets it wrong. See
    docs/PHASE2_ARCHITECTURE.md §6/§13.
    """
    for key, value in fields.items():
        if not isinstance(value, (dict, list)):
            continue
        column = _INTELLIGENCE_ITEM_COLUMNS.get(key)
        if column is None or isinstance(column.type, JSONB):
            continue  # unknown key (ORM will raise its own clear error) or a real JSON column
        raise ValueError(
            f"{source_name} connector produced a {type(value).__name__} for field '{key}', but "
            f"IntelligenceItem.{key} is a {type(column.type).__name__} column, not JSONB. "
            f"The connector's field mapping needs to extract a scalar (e.g. value.get('name')) "
            f"instead of passing the raw object through. Value: {value!r}"
        )


def _upsert_intelligence_item(db: Session, source: IntelligenceSource, raw) -> tuple[IntelligenceItem, bool]:
    _validate_connector_fields(source.name, raw.fields)

    existing = db.execute(
        select(IntelligenceItem).where(
            IntelligenceItem.intelligence_source_id == source.id,
            IntelligenceItem.external_id == raw.external_id,
        )
    ).scalars().first()

    now = datetime.now(timezone.utc)
    if existing is None:
        item = IntelligenceItem(
            intelligence_source_id=source.id,
            external_id=raw.external_id,
            intelligence_category=raw.intelligence_category,
            source=source.name,
            source_url=raw.source_url,
            retrieved_at=raw.retrieved_at,
            confidence=raw.confidence,
            raw_metadata=raw.raw,
            first_detected_at=now,
            last_seen_at=now,
            **raw.fields,
        )
        db.add(item)
        db.flush()
        return item, True

    for key, value in raw.fields.items():
        setattr(existing, key, value)
    existing.source_url = raw.source_url
    existing.retrieved_at = raw.retrieved_at
    existing.confidence = raw.confidence
    existing.raw_metadata = raw.raw
    existing.last_seen_at = now
    db.flush()
    return existing, False


def run_sync(
    db: Session,
    source: IntelligenceSource,
    triggered_by: SyncTriggeredBy,
    triggered_by_user_id=None,
    since_days: int = DEFAULT_SINCE_DAYS,
) -> IntelligenceSyncRun:
    """Never raises past this point for a connector/fetch/per-item failure — a failing
    source must not crash 'sync all enabled sources'. Does raise SyncAlreadyRunningError
    (caller's job to turn into a 409) and ValueError if the source has no connector
    registered (caller's job to turn into a 400 — the UI shouldn't offer Sync for such
    a source in the first place)."""
    if source.connector_key is None:
        raise ValueError(f"'{source.name}' has no connector implemented yet — nothing to sync.")
    try:
        connector = get_intelligence_connector(source.connector_key)
    except KeyError as exc:
        # Same category of problem as connector_key being None from the caller's
        # perspective (a source that isn't wired up yet) — one exception type for it.
        raise ValueError(f"'{source.name}' has no connector implemented yet — nothing to sync.") from exc

    cutoff = datetime.now(timezone.utc) - timedelta(minutes=CONCURRENCY_GUARD_MINUTES)
    already_running = db.execute(
        select(IntelligenceSyncRun).where(
            IntelligenceSyncRun.intelligence_source_id == source.id,
            IntelligenceSyncRun.status == SyncRunStatus.RUNNING,
            IntelligenceSyncRun.started_at >= cutoff,
        )
    ).scalars().first()
    if already_running is not None:
        raise SyncAlreadyRunningError(
            f"A sync for '{source.name}' is already in progress (started "
            f"{already_running.started_at.isoformat()})."
        )

    run = IntelligenceSyncRun(
        intelligence_source_id=source.id,
        started_at=datetime.now(timezone.utc),
        status=SyncRunStatus.RUNNING,
        triggered_by=triggered_by,
        triggered_by_user_id=triggered_by_user_id,
    )
    db.add(run)
    source.last_attempted_sync_at = run.started_at
    db.commit()
    db.refresh(run)

    if not connector.is_configured():
        run.status = SyncRunStatus.FAILURE
        run.error_detail = "Connector is not configured (missing credentials)."
        run.finished_at = datetime.now(timezone.utc)
        source.health_status = SourceHealthStatus.NEEDS_CONFIGURATION
        source.last_error = run.error_detail
        db.commit()
        return run

    try:
        raw_items = connector.fetch(date.today() - timedelta(days=since_days))
    except Exception as exc:
        logger.exception("Sync failed for source '%s'", source.name)
        run.status = SyncRunStatus.FAILURE
        run.error_detail = str(exc)[:2000]
        run.finished_at = datetime.now(timezone.utc)
        source.health_status = SourceHealthStatus.FAILING
        source.last_error = run.error_detail
        db.commit()
        return run

    fetched = created = updated = errored = 0
    for raw in raw_items:
        fetched += 1
        try:
            item, was_created = _upsert_intelligence_item(db, source, raw)
            promote_intelligence_item(db, item)
            calculate_early_signal_score(db, item)
            find_and_cluster_candidates(db, item)
            db.commit()
            created += was_created
            updated += not was_created
        except Exception:
            db.rollback()
            logger.exception(
                "Failed to process one item (external_id=%r) from '%s' — skipped, sync continues",
                getattr(raw, "external_id", "<unknown>"), source.name,
            )
            errored += 1

    run.items_fetched = fetched
    run.items_created = created
    run.items_updated = updated
    run.items_unchanged = max(0, fetched - created - updated - errored)
    run.items_errored = errored
    if errored == 0:
        run.status = SyncRunStatus.SUCCESS
    elif created or updated:
        run.status = SyncRunStatus.PARTIAL_FAILURE
    else:
        run.status = SyncRunStatus.FAILURE
    run.finished_at = datetime.now(timezone.utc)

    source.last_successful_sync_at = run.finished_at
    source.last_result_count = fetched
    source.last_error = None if errored == 0 else f"{errored} item(s) failed to process — see recent sync runs for detail."
    source.health_status = SourceHealthStatus.HEALTHY if errored == 0 else SourceHealthStatus.DEGRADED
    db.commit()
    db.refresh(run)
    return run
