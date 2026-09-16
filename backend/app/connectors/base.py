"""Connector framework. Each external data source implements IntelligenceConnector;
new sources plug in without touching the sync orchestrator, dedup engine, or any
route. See docs/PHASE2_ARCHITECTURE.md §5 and docs/DATA_INGESTION.md.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date, datetime

from app.models.enums import IntelligenceCategory


class ConnectorNotConfiguredError(RuntimeError):
    """Raised when a connector's required credential is missing. Callers should
    surface this as a 503 with setup instructions, never fall back to fake data."""


@dataclass
class RawIntelligenceItem:
    """What a connector hands back for one discovered item, before it's upserted into
    IntelligenceItem by the sync orchestrator (app/services/intelligence_sync.py).

    `fields` keys should match IntelligenceItem's own column names wherever the
    connector has the data — title, description, agency_name, location_city/state,
    naics_code, psc_code, set_aside, estimated_value_low/high, funding_amount,
    posted_at, proposal_due_at, solicitation_number, contract_number,
    funding_award_number, project_number, relevant_disciplines, etc. Any key the
    connector doesn't have is simply omitted — the sync orchestrator does not require
    every field, only `title`. `raw` keeps the original payload for `raw_metadata`.
    """

    external_id: str
    intelligence_category: IntelligenceCategory
    source_url: str | None
    retrieved_at: datetime
    fields: dict
    raw: dict = field(default_factory=dict)
    confidence: str = "verified_fact"


class IntelligenceConnector(ABC):
    key: str  # matches intelligence_sources.connector_key
    name: str  # matches intelligence_sources.name / ProvenanceMixin-style `source` label
    default_category: IntelligenceCategory

    @abstractmethod
    def is_configured(self) -> bool: ...

    @abstractmethod
    def fetch(self, since: date, **filters) -> list[RawIntelligenceItem]:
        """Return newly discovered/updated items since `since`. Raises
        ConnectorNotConfiguredError if required credentials are missing. Must never
        raise for an individual malformed item — log and skip it instead, the way
        SamGovConnector._to_raw_intelligence_item already does, so one bad record
        doesn't fail an entire sync."""
