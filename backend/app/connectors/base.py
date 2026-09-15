"""Connector framework. Each external data source implements OpportunityConnector;
new sources plug in without touching the ingestion service or any route. See
docs/DATA_INGESTION.md.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date, datetime


@dataclass
class RawOpportunity:
    """What a connector hands back for one discovered notice, before it's mapped onto
    the Opportunity model. `raw` keeps the original payload for the provenance log."""

    external_id: str
    source: str
    source_url: str | None
    retrieved_at: datetime
    fields: dict  # already-normalized keys matching OpportunityCreate, best-effort
    raw: dict = field(default_factory=dict)
    confidence: str = "verified_fact"


class ConnectorNotConfiguredError(RuntimeError):
    """Raised when a connector's required credential is missing. Callers should
    surface this as a 503 with setup instructions, never fall back to fake data."""


class OpportunityConnector(ABC):
    name: str

    @abstractmethod
    def is_configured(self) -> bool: ...

    @abstractmethod
    def fetch(self, since: date, **filters) -> list[RawOpportunity]:
        """Return newly discovered/updated notices since `since`. Raises
        ConnectorNotConfiguredError if required credentials are missing."""
