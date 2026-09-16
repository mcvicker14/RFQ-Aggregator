from app.connectors.base import IntelligenceConnector, OpportunityConnector
from app.connectors.sam_gov import SamGovConnector

_CONNECTORS: dict[str, OpportunityConnector] = {
    "sam_gov": SamGovConnector(),
}


def get_connector(key: str) -> OpportunityConnector:
    if key not in _CONNECTORS:
        raise KeyError(f"No connector registered for '{key}'. Available: {list(_CONNECTORS)}")
    return _CONNECTORS[key]


def list_connectors() -> dict[str, OpportunityConnector]:
    return dict(_CONNECTORS)


# Phase 2 connectors (IntelligenceConnector) live in a separate dict from the
# pre-Phase-2 ones above — populated as SAM.gov migrates and USAspending.gov/
# Grants.gov are built. A source_registry row with a connector_key not present here
# simply has no working code yet (see docs/PHASE2_ARCHITECTURE.md §5/§8).
_INTELLIGENCE_CONNECTORS: dict[str, IntelligenceConnector] = {}


def get_intelligence_connector(key: str) -> IntelligenceConnector:
    if key not in _INTELLIGENCE_CONNECTORS:
        raise KeyError(f"No intelligence connector registered for '{key}'. Available: {list(_INTELLIGENCE_CONNECTORS)}")
    return _INTELLIGENCE_CONNECTORS[key]


def list_intelligence_connectors() -> dict[str, IntelligenceConnector]:
    return dict(_INTELLIGENCE_CONNECTORS)
