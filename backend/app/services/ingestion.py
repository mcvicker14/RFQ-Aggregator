"""Ingestion orchestration: calls a connector, de-dupes against existing
opportunities, writes provenance, and never overwrites a field a human has since
edited by hand. See docs/DATA_INGESTION.md §Connector framework and §Field ownership.
"""
import logging
from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.connectors.base import RawOpportunity
from app.connectors.registry import get_connector
from app.models.agency import Agency, AgencyOffice
from app.models.alert import Alert
from app.models.enums import ActivityType, AlertCategory, MaturityStage, OpportunityStatus, SetAsideType
from app.models.opportunity import Opportunity, OpportunitySource
from app.models.pipeline import PipelineStage
from app.services.activities import log_activity
from app.services.scoring import calculate_score

logger = logging.getLogger(__name__)

# Fields ingestion is allowed to touch. Anything else on Opportunity is left alone —
# it's either purely internal (internal_notes, assigned_user_id) or derived.
SYNCABLE_FIELDS = {
    "title", "solicitation_number", "location_city", "location_state",
    "naics_code", "psc_code", "set_aside", "proposal_due_at",
}


@dataclass
class IngestionResult:
    connector: str
    total_fetched: int
    created: int
    updated: int
    unchanged: int


def _find_or_create_agency(db: Session, agency_path: str | None) -> tuple[Agency | None, AgencyOffice | None]:
    if not agency_path:
        return None, None
    # Heuristic parse of SAM.gov's dot-delimited fullParentPathName: first segment is
    # the top-level department (stable across notices), last segment is typically the
    # specific office/district. See module docstring on sam_gov.py for the caveat that
    # this schema assumption should be verified against live data.
    segments = [s.strip() for s in agency_path.split(".") if s.strip()]
    if not segments:
        return None, None

    agency_name = segments[0].title()
    agency = db.execute(select(Agency).where(Agency.name == agency_name)).scalars().first()
    if agency is None:
        agency = Agency(name=agency_name, agency_type="federal", source="SAM.gov", confidence="verified_fact")
        db.add(agency)
        db.flush()

    office = None
    if len(segments) > 1:
        office_name = segments[-1].title()
        office = db.execute(
            select(AgencyOffice).where(AgencyOffice.agency_id == agency.id, AgencyOffice.name == office_name)
        ).scalars().first()
        if office is None:
            office = AgencyOffice(agency_id=agency.id, name=office_name)
            db.add(office)
            db.flush()

    return agency, office


def _signal_detected_stage(db: Session) -> PipelineStage | None:
    return db.execute(select(PipelineStage).where(PipelineStage.name == "Signal Detected")).scalars().first()


def _upsert_opportunity(db: Session, raw: RawOpportunity) -> tuple[Opportunity, bool]:
    existing = None
    external_id = raw.fields.get("external_notice_id")
    if external_id:
        existing = db.execute(
            select(Opportunity).where(Opportunity.external_notice_id == external_id)
        ).scalars().first()
    if existing is None and raw.fields.get("solicitation_number"):
        existing = db.execute(
            select(Opportunity).where(Opportunity.solicitation_number == raw.fields["solicitation_number"])
        ).scalars().first()

    agency, office = _find_or_create_agency(db, raw.fields.get("agency_path"))

    if existing is None:
        signal_stage = _signal_detected_stage(db)
        opp = Opportunity(
            title=raw.fields.get("title", "(untitled)"),
            solicitation_number=raw.fields.get("solicitation_number"),
            location_city=raw.fields.get("location_city"),
            location_state=raw.fields.get("location_state"),
            naics_code=raw.fields.get("naics_code"),
            psc_code=raw.fields.get("psc_code"),
            set_aside=raw.fields.get("set_aside"),
            proposal_due_at=raw.fields.get("proposal_due_at"),
            opportunity_source_label=raw.fields.get("opportunity_source_label", raw.source),
            external_notice_id=external_id,
            agency_id=agency.id if agency else None,
            agency_office_id=office.id if office else None,
            maturity_stage=MaturityStage.SOLICITATION_RELEASED,
            status=OpportunityStatus.ACTIVE,
            pipeline_stage_id=signal_stage.id if signal_stage else None,
            source=raw.source,
            source_url=raw.source_url,
            retrieved_at=raw.retrieved_at,
            confidence=raw.confidence,
            is_sdvosb_setaside=raw.fields.get("set_aside") == SetAsideType.SDVOSB,
        )
        db.add(opp)
        db.flush()
        log_activity(
            db, opp.id, ActivityType.INGESTED,
            f"Discovered via {raw.source}", extra_data={"external_id": external_id},
        )
        return opp, True

    changed = False
    for field_name in SYNCABLE_FIELDS:
        if field_name in existing.locked_fields:
            continue
        new_value = raw.fields.get(field_name)
        if new_value is None:
            continue
        if getattr(existing, field_name) != new_value:
            setattr(existing, field_name, new_value)
            changed = True
            if field_name == "set_aside":
                existing.is_sdvosb_setaside = new_value == SetAsideType.SDVOSB

    if changed:
        existing.retrieved_at = raw.retrieved_at
        log_activity(db, existing.id, ActivityType.AMENDED, f"Updated via {raw.source} sync")
    db.flush()
    return existing, False


def sync_from_connector(db: Session, connector_key: str, since_days: int = 30) -> IngestionResult:
    connector = get_connector(connector_key)
    since = date.today() - timedelta(days=since_days)
    raw_items = connector.fetch(since)

    created = updated = unchanged = 0
    for raw in raw_items:
        opp, was_created = _upsert_opportunity(db, raw)

        db.add(
            OpportunitySource(
                opportunity_id=opp.id,
                source=raw.source,
                source_url=raw.source_url,
                retrieved_at=raw.retrieved_at,
                confidence=raw.confidence,
                raw_snapshot=raw.raw,
            )
        )

        calculate_score(db, opp)

        if was_created:
            created += 1
            db.add(
                Alert(
                    user_id=None,
                    category=AlertCategory.NEW_MATCHING_OPPORTUNITY,
                    title=f"New opportunity from {raw.source}: {opp.title}",
                    body=f"{opp.solicitation_number or 'No solicitation number yet'} — {opp.location_state or 'location TBD'}",
                    opportunity_id=opp.id,
                )
            )
        else:
            updated += 1

    db.commit()
    return IngestionResult(
        connector=connector_key,
        total_fetched=len(raw_items),
        created=created,
        updated=updated,
        unchanged=len(raw_items) - created - updated,
    )
