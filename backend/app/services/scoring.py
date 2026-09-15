"""Principal Pursuit Score engine. See docs/SCORING_METHODOLOGY.md for the full
methodology this implements. Deterministic and template-based on purpose (no LLM
call) so scoring is instant and works with zero external dependencies — the AI
solicitation reader is a separate, optional feature (app/ai/).
"""
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.agency import Agency
from app.models.company import Company, OpportunityCompany
from app.models.contact import Contact, OpportunityContact
from app.models.enums import (
    CompanyType,
    ContractType,
    OpportunityCompanyRelationship,
    SetAsideType,
)
from app.models.opportunity import Opportunity
from app.models.scoring import DEFAULT_WEIGHTS, OpportunityScore, ScoringWeightProfile

settings = get_settings()

GULF_COAST_STATES = {"LA", "MS", "AL", "TX", "FL"}
SOUTHEAST_STATES = {"GA", "SC", "NC", "TN", "AR", "KY"}

CORE_MARKET_KEYWORDS = [
    "civil engineering", "water", "wastewater", "stormwater", "drainage", "utilities",
    "utility", "transportation", "site civil", "site/civil", "surveying", "survey",
    "construction administration", "construction management", "federal facility",
    "disaster recovery", "environmental", "flood control", "levee", "pump station",
    "sewer", "potable water", "hydraulic", "hydrology", "resilience",
]

PRIORITY_AGENCY_KEYWORDS = [
    "army corps", "usace", "veterans affairs", "va medical", "fema", "nrcs",
    "natural resources conservation", "air force", "department of defense", "dod",
    "navy", "army", "military",
]


def _clamp(value: float, lo: int = 0, hi: int = 100) -> int:
    return int(max(lo, min(hi, round(value))))


def _score_strategic_fit(opp: Opportunity) -> tuple[int, list[str]]:
    bullets: list[str] = []
    score = 30  # baseline for an opportunity with no discernible match

    text = " ".join(filter(None, [opp.title, opp.scope_summary, opp.description])).lower()
    matched_keywords = sorted({kw for kw in CORE_MARKET_KEYWORDS if kw in text})

    if opp.naics_code == settings.PRINCIPAL_PRIMARY_NAICS:
        score = 95
        bullets.append(
            f"NAICS {opp.naics_code} is Principal's primary code (Engineering Services)."
        )
    elif opp.naics_code in settings.PRINCIPAL_SECONDARY_NAICS:
        score = 78
        bullets.append(f"NAICS {opp.naics_code} is one of Principal's secondary/related codes.")
    elif opp.naics_code:
        score = 45
        bullets.append(f"NAICS {opp.naics_code} is outside Principal's core code list.")
    else:
        bullets.append("No NAICS code on file yet.")

    if matched_keywords:
        bonus = min(20, 5 * len(matched_keywords))
        score = min(100, score + bonus)
        bullets.append("Scope references core disciplines: " + ", ".join(matched_keywords[:4]) + ".")
    elif opp.naics_code not in (settings.PRINCIPAL_PRIMARY_NAICS, *settings.PRINCIPAL_SECONDARY_NAICS):
        bullets.append("Scope text does not yet mention Principal's core civil/water/environmental disciplines.")

    return _clamp(score), bullets


def _score_customer_fit(opp: Opportunity, agency: Agency | None) -> tuple[int, list[str]]:
    tiers = {"1": 100, "2": 70, "3": 45}
    if agency is None:
        return 40, ["No agency on file yet — customer fit cannot be fully assessed."]

    tier_score = tiers.get(str(agency.priority_tier), 45)
    bullets = [f"{agency.name} is a tier-{agency.priority_tier} customer for Principal."]

    name_text = f"{agency.name} {agency.short_name or ''}".lower()
    if any(kw in name_text for kw in PRIORITY_AGENCY_KEYWORDS):
        tier_score = max(tier_score, 85)
        bullets.append("Agency matches Principal's priority federal customer list (USACE/VA/FEMA/NRCS/DoD).")

    return _clamp(tier_score), bullets


def _score_contract_fit(opp: Opportunity) -> tuple[int, list[str]]:
    bullets = []

    set_aside_scores = {
        SetAsideType.SDVOSB: 100,
        SetAsideType.EIGHT_A: 75,
        SetAsideType.HUBZONE: 75,
        SetAsideType.SMALL_BUSINESS: 72,
        SetAsideType.WOSB: 68,
        SetAsideType.EDWOSB: 68,
        SetAsideType.UNRESTRICTED: 55,
        SetAsideType.OTHER: 45,
    }
    sa_score = set_aside_scores.get(opp.set_aside, 45)
    if opp.set_aside == SetAsideType.SDVOSB:
        bullets.append("Restricted to SDVOSBs — Principal's own socioeconomic status is a direct advantage here.")
    elif opp.set_aside == SetAsideType.UNRESTRICTED:
        bullets.append("Unrestricted competition — no socioeconomic set-aside advantage.")
    else:
        bullets.append(f"Set-aside: {opp.set_aside.value.replace('_', ' ').title()}.")

    contract_type_scores = {
        ContractType.AE_BROOKS_ACT: 90,
        ContractType.IDIQ: 88,
        ContractType.MATOC: 85,
        ContractType.SATOC: 85,
        ContractType.TASK_ORDER: 80,
        ContractType.DESIGN_BUILD: 45,
        ContractType.CONSTRUCTION: 35,
        ContractType.OTHER: 50,
    }
    ct_score = contract_type_scores.get(opp.contract_type, 50)
    if opp.contract_type in (ContractType.IDIQ, ContractType.MATOC, ContractType.SATOC):
        bullets.append(f"{opp.contract_type.value.upper()} vehicle — strong potential for recurring task orders.")

    return _clamp(0.55 * sa_score + 0.45 * ct_score), bullets


def _score_geographic_fit(opp: Opportunity, profile: ScoringWeightProfile) -> tuple[int, list[str]]:
    priorities = profile.geographic_priorities or {}
    state = (opp.location_state or "").upper()

    if not state:
        return 50, ["No project location on file yet."]

    if state in priorities:
        return _clamp(priorities[state]), [f"{state} is one of Principal's highest-priority geographies."]

    if state in GULF_COAST_STATES:
        val = priorities.get("_gulf_coast_default", 70)
        return _clamp(val), [f"{state} is within Principal's Gulf Coast target region."]

    if state in SOUTHEAST_STATES:
        val = priorities.get("_southeast_default", 55)
        return _clamp(val), [f"{state} is within the broader Southeast target region."]

    val = priorities.get("_national_default", 35)
    return _clamp(val), [f"{state} is outside Principal's core regions — scored as a national opportunity."]


def _score_competitive_advantage(
    opp: Opportunity, incumbent: Company | None, teaming_count: int, avg_relationship: float | None
) -> tuple[int, list[str]]:
    bullets = []
    score = 50.0

    if opp.is_sdvosb_setaside:
        score += 25
        bullets.append("SDVOSB set-aside directly leverages Principal's certification.")

    if incumbent is not None and incumbent.company_type == CompanyType.OWN_FIRM:
        score += 20
        bullets.append("Principal is the incumbent — strong continuity advantage.")
    elif incumbent is not None:
        score -= 15
        bullets.append(f"An incumbent ({incumbent.name}) already holds this work.")

    if teaming_count > 0:
        score += min(15, teaming_count * 7)
        bullets.append(f"{teaming_count} potential teaming partner(s) already identified for this pursuit.")

    if avg_relationship is not None:
        score += (avg_relationship - 3) * 8  # relationship_strength is 1-5, 3 = neutral
        if avg_relationship >= 4:
            bullets.append("Existing contacts on this opportunity show strong relationship strength.")
        elif avg_relationship <= 2:
            bullets.append("Existing contacts on this opportunity show weak relationship strength.")

    if not bullets:
        bullets.append("No competitive-advantage signals on file yet (teaming, relationships, incumbency).")

    return _clamp(score), bullets


def _score_financial_attractiveness(opp: Opportunity) -> tuple[int, list[str]]:
    fee = opp.estimated_fee
    if fee is None and opp.estimated_value_high:
        fee = float(opp.estimated_value_high) * 0.08  # rough A/E fee-as-%-of-construction heuristic, clearly a fallback estimate

    if fee is None:
        return 50, ["Estimated fee not yet entered — financial attractiveness is a neutral placeholder."]

    fee = float(fee)
    if fee >= 500_000:
        score, note = 95, "very large"
    elif fee >= 200_000:
        score, note = 80, "large"
    elif fee >= 75_000:
        score, note = 62, "solid"
    elif fee >= 25_000:
        score, note = 45, "modest"
    else:
        score, note = 30, "small"

    bullets = [f"Estimated fee of ${fee:,.0f} is a {note} pursuit by Principal's standards."]
    if opp.contract_type in (ContractType.IDIQ, ContractType.MATOC, ContractType.SATOC):
        score = min(100, score + 10)
        bullets.append("Multiple-award/task-order vehicle increases the realistic lifetime value.")
    return _clamp(score), bullets


def _score_competition(
    opp: Opportunity, incumbent: Company | None, competitor_count: int
) -> tuple[int, list[str]]:
    score = 60.0
    bullets = []

    if competitor_count == 0:
        bullets.append("No competitors identified yet — treat this as an unknown, not a confirmed light field.")
    else:
        score -= min(35, competitor_count * 8)
        bullets.append(f"{competitor_count} likely/confirmed competitor(s) on file.")

    if opp.set_aside != SetAsideType.UNRESTRICTED:
        score += 20
        bullets.append("Set-aside restriction narrows the competitive field.")

    if incumbent is not None and incumbent.company_type != CompanyType.OWN_FIRM:
        score -= 10
        bullets.append("An incumbent other than Principal is likely to re-compete aggressively.")

    return _clamp(score), bullets


def _score_timing(opp: Opportunity) -> tuple[int, list[str]]:
    if opp.proposal_due_at is None:
        return 50, ["No proposal due date on file yet."]

    now = datetime.now(timezone.utc)
    due = opp.proposal_due_at
    if due.tzinfo is None:
        due = due.replace(tzinfo=timezone.utc)
    days_left = (due - now).days

    if days_left < 0:
        return 10, ["Proposal due date has already passed."]
    if days_left >= 45:
        score, note = 90, "ample time"
    elif days_left >= 30:
        score, note = 75, "adequate time"
    elif days_left >= 14:
        score, note = 55, "tight but workable time"
    elif days_left >= 7:
        score, note = 35, "very tight time"
    else:
        score, note = 15, "almost no time"

    return score, [f"{days_left} day(s) until proposal due — {note} to prepare an SF330 and arrange teaming."]


def _compose_narrative(category_scores: dict[str, int], category_rationale: dict[str, list[str]]) -> tuple[str, str]:
    ranked = sorted(category_scores.items(), key=lambda kv: kv[1], reverse=True)
    strongest = [c for c, s in ranked if s >= 65][:2]
    weakest_cat, weakest_score = ranked[-1]

    if strongest:
        reasons = []
        for cat in strongest:
            if category_rationale.get(cat):
                reasons.append(category_rationale[cat][0].rstrip("."))
        why = "Strong fit because " + "; and because ".join(reasons) + "." if reasons else "Multiple factors score favorably for this opportunity."
    else:
        why = "No category scores strongly yet; the pursuit rationale will sharpen as more information is added."

    if weakest_score < 65 and category_rationale.get(weakest_cat):
        concern = category_rationale[weakest_cat][0]
    else:
        concern = "No major concern identified from the data on file."

    return why, concern


def calculate_score(
    db: Session, opportunity: Opportunity, profile: ScoringWeightProfile | None = None
) -> OpportunityScore:
    if profile is None:
        profile = db.execute(
            select(ScoringWeightProfile).where(ScoringWeightProfile.is_active.is_(True))
        ).scalars().first()
    weights = (profile.weights if profile else None) or DEFAULT_WEIGHTS

    agency = db.get(Agency, opportunity.agency_id) if opportunity.agency_id else None
    incumbent = db.get(Company, opportunity.incumbent_company_id) if opportunity.incumbent_company_id else None

    links = db.execute(
        select(OpportunityCompany).where(OpportunityCompany.opportunity_id == opportunity.id)
    ).scalars().all()
    teaming_count = sum(1 for link in links if link.relationship_type == OpportunityCompanyRelationship.TEAMING_PARTNER)
    competitor_count = sum(
        1
        for link in links
        if link.relationship_type
        in (
            OpportunityCompanyRelationship.CONFIRMED_COMPETITOR,
            OpportunityCompanyRelationship.HISTORICAL_COMPETITOR,
            OpportunityCompanyRelationship.LIKELY_COMPETITOR,
            OpportunityCompanyRelationship.POSSIBLE_COMPETITOR,
        )
    )

    contact_links = db.execute(
        select(OpportunityContact).where(OpportunityContact.opportunity_id == opportunity.id)
    ).scalars().all()
    linked_contacts = [db.get(Contact, link.contact_id) for link in contact_links]
    strengths = [c.relationship_strength for c in linked_contacts if c and c.relationship_strength]
    avg_relationship = sum(strengths) / len(strengths) if strengths else None

    strategic_fit, strategic_bullets = _score_strategic_fit(opportunity)
    customer_fit, customer_bullets = _score_customer_fit(opportunity, agency)
    contract_fit, contract_bullets = _score_contract_fit(opportunity)
    geographic_fit, geo_bullets = _score_geographic_fit(opportunity, profile) if profile else (50, ["No weight profile configured."])
    competitive_advantage, comp_adv_bullets = _score_competitive_advantage(
        opportunity, incumbent, teaming_count, avg_relationship
    )
    financial_attractiveness, financial_bullets = _score_financial_attractiveness(opportunity)
    competition, competition_bullets = _score_competition(opportunity, incumbent, competitor_count)
    timing, timing_bullets = _score_timing(opportunity)

    category_scores = {
        "strategic_fit": strategic_fit,
        "customer_fit": customer_fit,
        "contract_fit": contract_fit,
        "geographic_fit": geographic_fit,
        "competitive_advantage": competitive_advantage,
        "financial_attractiveness": financial_attractiveness,
        "competition": competition,
        "timing": timing,
    }
    category_rationale = {
        "strategic_fit": strategic_bullets,
        "customer_fit": customer_bullets,
        "contract_fit": contract_bullets,
        "geographic_fit": geo_bullets,
        "competitive_advantage": comp_adv_bullets,
        "financial_attractiveness": financial_bullets,
        "competition": competition_bullets,
        "timing": timing_bullets,
    }

    total_weight = sum(weights.get(cat, 0) for cat in category_scores) or 100
    overall = sum(category_scores[cat] * weights.get(cat, 0) for cat in category_scores) / total_weight
    overall = _clamp(overall)
    band = "high" if overall >= 75 else "medium" if overall >= 50 else "low"

    why, concern = _compose_narrative(category_scores, category_rationale)

    existing = db.execute(
        select(OpportunityScore).where(OpportunityScore.opportunity_id == opportunity.id)
    ).scalars().first()
    record = existing or OpportunityScore(opportunity_id=opportunity.id)
    record.weight_profile_id = profile.id if profile else None
    record.score = overall
    record.band = band
    record.category_scores = category_scores
    record.category_rationale = category_rationale
    record.why_it_scores_highly = why
    record.primary_concern = concern

    if not existing:
        db.add(record)
    db.flush()
    return record
