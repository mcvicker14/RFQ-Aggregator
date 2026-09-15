"""Import every model module so Base.metadata is fully populated for Alembic
autogenerate and for `Base.metadata.create_all()` in tests."""

from app.db.base import Base  # noqa: F401
from app.models.activity import Activity  # noqa: F401
from app.models.agency import Agency, AgencyOffice  # noqa: F401
from app.models.alert import Alert, AlertRule  # noqa: F401
from app.models.company import Company, OpportunityCompany  # noqa: F401
from app.models.contact import Contact, OpportunityContact  # noqa: F401
from app.models.document import AiSolicitationAnalysis, OpportunityDocument  # noqa: F401
from app.models.forecast import RevenueForecast, RevenueTarget  # noqa: F401
from app.models.gonogo import GoNoGoCriteriaScore, GoNoGoReview  # noqa: F401
from app.models.opportunity import Opportunity, OpportunitySource  # noqa: F401
from app.models.pipeline import PipelineStage  # noqa: F401
from app.models.reference import Discipline, NaicsCode, OpportunityDiscipline  # noqa: F401
from app.models.scoring import OpportunityScore, ScoringWeightProfile  # noqa: F401
from app.models.task import Task  # noqa: F401
from app.models.user import User  # noqa: F401
from app.models.winloss import WinLossReview  # noqa: F401

__all__ = [
    "Base",
    "Activity",
    "Agency",
    "AgencyOffice",
    "Alert",
    "AlertRule",
    "Company",
    "OpportunityCompany",
    "Contact",
    "OpportunityContact",
    "AiSolicitationAnalysis",
    "OpportunityDocument",
    "RevenueForecast",
    "RevenueTarget",
    "GoNoGoCriteriaScore",
    "GoNoGoReview",
    "Opportunity",
    "OpportunitySource",
    "PipelineStage",
    "Discipline",
    "NaicsCode",
    "OpportunityDiscipline",
    "OpportunityScore",
    "ScoringWeightProfile",
    "Task",
    "User",
    "WinLossReview",
]
