from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.connectors.base import ConnectorNotConfiguredError
from app.connectors.registry import get_connector
from app.core.deps import get_current_user, require_bd_or_above
from app.db.session import get_db
from app.models.user import User
from app.services.ingestion import sync_from_connector

router = APIRouter(prefix="/api/ingestion", tags=["ingestion"])


@router.get("/sam-gov/status")
def sam_gov_status(_current: User = Depends(get_current_user)):
    connector = get_connector("sam_gov")
    return {
        "connector": connector.name,
        "configured": connector.is_configured(),
        "detail": None
        if connector.is_configured()
        else (
            "SAM.gov integration is not configured. To enable it: sign in at sam.gov, open Account "
            "Details, request a Public API Key, then add it as SAM_GOV_API_KEY in the backend "
            "environment. See docs/DATA_INGESTION.md."
        ),
    }


@router.post("/sam-gov/sync")
def sam_gov_sync(
    since_days: int = 30, db: Session = Depends(get_db), _current: User = Depends(require_bd_or_above)
):
    try:
        result = sync_from_connector(db, "sam_gov", since_days=since_days)
    except ConnectorNotConfiguredError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
    return result
