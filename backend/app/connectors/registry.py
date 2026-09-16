from app.connectors.base import IntelligenceConnector
from app.connectors.sam_gov import SamGovConnector

# A source_registry row's connector_key not present here simply has no working code
# yet (see docs/PHASE2_ARCHITECTURE.md §5/§8) — the Source Manager UI and
# intelligence_sync.run_sync() both treat that as "nothing to sync," not an error.
_INTELLIGENCE_CONNECTORS: dict[str, IntelligenceConnector] = {
    "sam_gov": SamGovConnector(),
}


def get_intelligence_connector(key: str) -> IntelligenceConnector:
    if key not in _INTELLIGENCE_CONNECTORS:
        raise KeyError(f"No intelligence connector registered for '{key}'. Available: {list(_INTELLIGENCE_CONNECTORS)}")
    return _INTELLIGENCE_CONNECTORS[key]


def list_intelligence_connectors() -> dict[str, IntelligenceConnector]:
    return dict(_INTELLIGENCE_CONNECTORS)
