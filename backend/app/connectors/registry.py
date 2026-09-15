from app.connectors.base import OpportunityConnector
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
