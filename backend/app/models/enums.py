import enum


class UserRole(str, enum.Enum):
    ADMINISTRATOR = "administrator"
    EXECUTIVE = "executive"
    BUSINESS_DEVELOPMENT = "business_development"
    PROJECT_MANAGER = "project_manager"
    PROPOSAL_MANAGER = "proposal_manager"
    VIEWER = "viewer"


class CompanyType(str, enum.Enum):
    OWN_FIRM = "own_firm"
    TEAMING_PARTNER = "teaming_partner"
    COMPETITOR = "competitor"
    PRIME = "prime"
    SUBCONSULTANT = "subconsultant"
    OTHER = "other"


class OpportunityCompanyRelationship(str, enum.Enum):
    INCUMBENT = "incumbent"
    TEAMING_PARTNER = "teaming_partner"
    CONFIRMED_COMPETITOR = "confirmed_competitor"
    HISTORICAL_COMPETITOR = "historical_competitor"
    LIKELY_COMPETITOR = "likely_competitor"
    POSSIBLE_COMPETITOR = "possible_competitor"
    SUBCONSULTANT = "subconsultant"
    PRIME = "prime"


class ContactRole(str, enum.Enum):
    CONTRACTING_OFFICER = "contracting_officer"
    PROGRAM_MANAGER = "program_manager"
    SMALL_BUSINESS_SPECIALIST = "small_business_specialist"
    TECHNICAL_CONTACT = "technical_contact"
    AGENCY_ENGINEER = "agency_engineer"
    TEAMING_PARTNER_CONTACT = "teaming_partner_contact"
    MUNICIPAL_OFFICIAL = "municipal_official"
    OTHER = "other"


class SetAsideType(str, enum.Enum):
    UNRESTRICTED = "unrestricted"
    SDVOSB = "sdvosb"
    SMALL_BUSINESS = "small_business"
    EIGHT_A = "eight_a"
    HUBZONE = "hubzone"
    WOSB = "wosb"
    EDWOSB = "edwosb"
    OTHER = "other"


class ContractType(str, enum.Enum):
    AE_BROOKS_ACT = "ae_brooks_act"
    IDIQ = "idiq"
    MATOC = "matoc"
    SATOC = "satoc"
    TASK_ORDER = "task_order"
    DESIGN_BUILD = "design_build"
    CONSTRUCTION = "construction"
    OTHER = "other"


class MaturityStage(str, enum.Enum):
    RUMORED_CONCEPTUAL = "rumored_conceptual"
    FUNDING_IDENTIFIED = "funding_identified"
    PLANNING = "planning"
    PROCUREMENT_FORECAST = "procurement_forecast"
    SOURCES_SOUGHT_RFI = "sources_sought_rfi"
    SOLICITATION_EXPECTED = "solicitation_expected"
    SOLICITATION_RELEASED = "solicitation_released"
    PROPOSAL_SUBMITTED = "proposal_submitted"
    INTERVIEW_NEGOTIATION = "interview_negotiation"
    AWARD_PENDING = "award_pending"
    AWARDED = "awarded"


class OpportunityStatus(str, enum.Enum):
    ACTIVE = "active"
    ARCHIVED = "archived"


class ConfidenceLevel(str, enum.Enum):
    VERIFIED_FACT = "verified_fact"
    INFERRED = "inferred"
    AI_GENERATED = "ai_generated"
    UNVERIFIED = "unverified"


class GoNoGoOutcome(str, enum.Enum):
    GO = "go"
    CONDITIONAL_GO = "conditional_go"
    NO_GO = "no_go"


class TaskStatus(str, enum.Enum):
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class TaskPriority(str, enum.Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    URGENT = "urgent"


class DocumentCategory(str, enum.Enum):
    SOLICITATION = "solicitation"
    AMENDMENT = "amendment"
    SCOPE = "scope"
    PLANS = "plans"
    AGENCY_DOCUMENT = "agency_document"
    PROPOSAL_DRAFT = "proposal_draft"
    SF330 = "sf330"
    TEAMING_AGREEMENT = "teaming_agreement"
    RESUME = "resume"
    PROJECT_SHEET = "project_sheet"
    DEBRIEF = "debrief"
    AWARD_DOCUMENT = "award_document"
    OTHER = "other"


class ActivityType(str, enum.Enum):
    CREATED = "created"
    STAGE_CHANGED = "stage_changed"
    SCORE_RECALCULATED = "score_recalculated"
    FIELD_UPDATED = "field_updated"
    DOCUMENT_UPLOADED = "document_uploaded"
    AI_ANALYSIS_COMPLETED = "ai_analysis_completed"
    GONOGO_STARTED = "gonogo_started"
    GONOGO_DECIDED = "gonogo_decided"
    TASK_CREATED = "task_created"
    TASK_COMPLETED = "task_completed"
    NOTE = "note"
    INGESTED = "ingested"
    AMENDED = "amended"


class AlertCategory(str, enum.Enum):
    NEW_MATCHING_OPPORTUNITY = "new_matching_opportunity"
    NEW_SOURCES_SOUGHT = "new_sources_sought"
    DEADLINE_APPROACHING = "deadline_approaching"
    OPPORTUNITY_AMENDED = "opportunity_amended"
    GONOGO_NEEDED = "gonogo_needed"
    TASK_DUE = "task_due"
    RECOMPETE_APPROACHING = "recompete_approaching"
    OTHER = "other"
