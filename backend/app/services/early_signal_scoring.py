"""Early Signal Score — a separate, deterministic engine from the Principal Pursuit
Score (app/services/scoring.py). Answers a different question: not "how good a fit
for Principal" (that only applies once something is a real Opportunity) but "how
likely is this EARLY_SIGNAL item to develop into an actual procurement at all." Always
an estimate, never certainty — see docs/PHASE2_ARCHITECTURE.md §10. No LLM call, same
reasoning as the Pursuit Score: instant, and works with zero external dependency.
"""
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.enums import ConnectorType, IntelligenceCategory, JurisdictionLevel, MaturityStage
from app.models.intelligence import IntelligenceItem, IntelligenceSource

DEFAULT_WEIGHTS = {
    "funding_certainty": 35,
    "specificity": 30,
    "source_reliability": 15,
    "timing_concreteness": 20,
}

# Bonus/penalty by maturity stage — how far along the funding/planning process this
# signal claims to be. Stages at or past SOURCES_SOUGHT_RFI aren't really "early
# signals" anymore in practice, but the bonus keeps climbing in case one is ever
# mis-categorized rather than producing a discontinuity.
_MATURITY_ADJUSTMENT: dict[MaturityStage, int] = {
    MaturityStage.RUMORED_CONCEPTUAL: -10,
    MaturityStage.FUNDING_IDENTIFIED: 15,
    MaturityStage.PLANNING: 20,
    MaturityStage.PROCUREMENT_FORECAST: 25,
    MaturityStage.SOURCES_SOUGHT_RFI: 30,
}


def _clamp(value: float, lo: int = 0, hi: int = 100) -> int:
    return int(max(lo, min(hi, round(value))))


def _score_funding_certainty(item: IntelligenceItem) -> tuple[int, list[str]]:
    bullets: list[str] = []
    score = 30.0  # baseline: no funding signal at all

    if item.funding_amount and item.funding_amount > 0:
        score = 85.0
        bullets.append(f"Funding amount of ${float(item.funding_amount):,.0f} is identified.")
    else:
        bullets.append("No specific funding amount identified yet.")

    if item.maturity_stage in _MATURITY_ADJUSTMENT:
        score += _MATURITY_ADJUSTMENT[item.maturity_stage]
        bullets.append(f"Maturity stage: {item.maturity_stage.value.replace('_', ' ').title()}.")

    return _clamp(score), bullets


def _score_specificity(item: IntelligenceItem) -> tuple[int, list[str]]:
    score = 40.0
    bullets: list[str] = []

    if item.location_city or item.location_state:
        location = " ".join(filter(None, [item.location_city, item.location_state]))
        score += 25
        bullets.append(f"Specific location identified ({location}).")
    else:
        bullets.append("No specific location identified yet.")

    description_length = len(item.description or "")
    if description_length >= 200:
        score += 20
        bullets.append("Detailed description available.")
    elif description_length >= 50:
        score += 10
    else:
        bullets.append("Little descriptive detail available yet.")

    if item.agency_name or item.agency_id:
        score += 10
        bullets.append(f"Specific agency identified: {item.agency_name or 'on file'}.")

    return _clamp(score), bullets


def _score_source_reliability(source: IntelligenceSource | None) -> tuple[int, list[str]]:
    if source is None:
        return 40, ["Source record not found — reliability cannot be fully assessed."]

    score = 50.0
    bullets = [f"Source: {source.name} ({source.jurisdiction_level.value.title()})."]

    if source.jurisdiction_level in (JurisdictionLevel.FEDERAL, JurisdictionLevel.STATE):
        score += 25
    elif source.jurisdiction_level == JurisdictionLevel.LOCAL:
        score += 15

    if source.connector_type in (ConnectorType.API, ConnectorType.STRUCTURED_FILE, ConnectorType.CSV):
        score += 15
        bullets.append("Sourced via a structured official feed, not a manual or inferred read.")

    return _clamp(score), bullets


def _score_timing_concreteness(item: IntelligenceItem) -> tuple[int, list[str]]:
    known_dates = [
        d for d in (item.proposal_due_at, item.posted_at, item.estimated_solicitation_date, item.estimated_award_date)
        if d is not None
    ]
    if not known_dates:
        return 30, ["No dates associated with this signal yet — timing is unknown."]

    score = 55.0 + 15 * min(len(known_dates), 3)
    bullets = [f"{len(known_dates)} date(s) on file for this signal."]

    if item.proposal_due_at:
        now = datetime.now(timezone.utc)
        due = item.proposal_due_at if item.proposal_due_at.tzinfo else item.proposal_due_at.replace(tzinfo=timezone.utc)
        days_left = (due - now).days
        if 0 <= days_left <= 60:
            bullets.append(f"Due date is {days_left} day(s) away — timely to act on now.")
        elif days_left < 0:
            bullets.append("Due date has passed — this specific window may have closed.")

    return _clamp(score), bullets


def calculate_early_signal_score(db: Session, item: IntelligenceItem) -> IntelligenceItem:
    """No-op for anything that isn't an EARLY_SIGNAL item — safe to call unconditionally
    from the sync orchestrator for every item, the same pattern promote_intelligence_item
    uses for its own category check."""
    if item.intelligence_category != IntelligenceCategory.EARLY_SIGNAL:
        return item

    source = db.get(IntelligenceSource, item.intelligence_source_id)

    funding_score, funding_bullets = _score_funding_certainty(item)
    specificity_score, specificity_bullets = _score_specificity(item)
    reliability_score, reliability_bullets = _score_source_reliability(source)
    timing_score, timing_bullets = _score_timing_concreteness(item)

    category_scores = {
        "funding_certainty": funding_score,
        "specificity": specificity_score,
        "source_reliability": reliability_score,
        "timing_concreteness": timing_score,
    }
    category_rationale = {
        "funding_certainty": funding_bullets,
        "specificity": specificity_bullets,
        "source_reliability": reliability_bullets,
        "timing_concreteness": timing_bullets,
    }

    total_weight = sum(DEFAULT_WEIGHTS.values())
    overall = _clamp(sum(category_scores[cat] * DEFAULT_WEIGHTS[cat] for cat in category_scores) / total_weight)
    band = "high" if overall >= 70 else "medium" if overall >= 45 else "low"

    item.early_signal_score = overall
    item.early_signal_score_rationale = {
        "band": band,
        "category_scores": category_scores,
        "category_rationale": category_rationale,
        "disclaimer": (
            "An estimate of how likely this signal is to develop into a pursuable "
            "procurement — not a certainty, and not a measure of fit for Principal "
            "(that's the Principal Pursuit Score, which only applies once this "
            "becomes a real opportunity)."
        ),
    }
    db.flush()
    return item
