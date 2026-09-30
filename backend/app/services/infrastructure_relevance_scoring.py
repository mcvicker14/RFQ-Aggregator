"""Infrastructure Relevance Score — "is this COREWORKS/APEX listing worth putting in
front of Principal?" The shared relevance adapter for sources whose relevance concept
is genuinely the same (unlike SAM.gov's and Grants.gov's own scores, which are each
tied to source-specific fields — NAICS/notice-type for SAM, funding-instrument signal
strength for Grants): civil engineering, water/wastewater, drainage/stormwater,
utilities, roads/transportation, surveying, A/E, public works, environmental
infrastructure, airports/ports, coastal/flood/resilience. See
docs/SCORING_METHODOLOGY.md.

Same deterministic, template-based, no-LLM-call approach as the other three scoring
engines, and the same "gated no-op by source name" shape as sam_relevance_scoring.py/
grants_relevance_scoring.py — safe to call unconditionally on every item from every
source in run_sync()'s per-item loop.
"""
from app.models.intelligence import IntelligenceItem

# calculate_infrastructure_relevance_score() no-ops for any other source.
COREWORKS_SOURCE_NAME = "COREWORKS RFQwire"
APEX_SOURCE_NAME = "APEX MyBidMatch"
_APPLIES_TO_SOURCES = (COREWORKS_SOURCE_NAME, APEX_SOURCE_NAME)

# Tier boundaries — same numeric bands as the other three engines (80/65/50), measuring
# a different thing but kept consistent so "relevant" means roughly the same confidence
# level everywhere in the app.
HIGHLY_RELEVANT_THRESHOLD = 80
RELEVANT_THRESHOLD = 65
POSSIBLE_MATCH_THRESHOLD = 50


def relevance_tier(score: int | None) -> str:
    """"unscored" for None — a non-COREWORKS/APEX item, or one not yet processed by
    this module. Callers needing "no score" to mean "always show" (Discover's default
    filter) check for None themselves, same as the other three engines."""
    if score is None:
        return "unscored"
    if score >= HIGHLY_RELEVANT_THRESHOLD:
        return "highly_relevant"
    if score >= RELEVANT_THRESHOLD:
        return "relevant"
    if score >= POSSIBLE_MATCH_THRESHOLD:
        return "possible_match"
    return "low_relevance"


def _clamp(value: float, lo: int = 0, hi: int = 100) -> int:
    return int(max(lo, min(hi, round(value))))


# --- Content: the same civil/infrastructure practice areas SAM's scorer uses, plus
# the themes explicitly named for these two sources (airports/ports, coastal/flood/
# resilience overlap with SAM's list; drainage/stormwater/utilities/public works/
# environmental infrastructure are called out again here for emphasis since COREWORKS
# in particular is a regional civil/A-E digest, not a broad federal-purchasing feed).
STRONG_POINTS = 20
MODERATE_POINTS = 8
CONTENT_CAP = 45

_STRONG_POSITIVE_PHRASES: list[str] = [
    "architect-engineer", "architect engineer", "a-e services", "a/e services",
    "ae services", "engineering services", "professional engineering",
    "engineering design", "civil engineering", "civil works",
    "water system", "wastewater", "sanitary sewer", "sewer rehabilitation",
    "water main", "sewer main", "drainage", "stormwater", "flood control",
    "flood mitigation", "levee", "watershed", "utility replacement",
    "utility infrastructure", "pump station", "lift station", "treatment plant",
    "transportation engineering", "site civil", "site development",
    "topographic survey", "surveying", "construction administration",
    "construction engineering", "coastal restoration", "erosion control",
    "resiliency", "resilience", "disaster recovery", "airport", "aviation",
    "port authority", "public works", "environmental compliance",
    "environmental consulting", "architectural services", "planning services",
]
_MODERATE_POSITIVE_PHRASES: list[str] = [
    "design services", "roadway", "road improvements", "bridge",
    "infrastructure improvements", "project management", "construction management",
    "grant management", "environmental assessment",
]

NEGATIVE_POINTS_PER_HIT = 15
NEGATIVE_POINTS_CAP = 60

_NEGATIVE_PHRASES: list[str] = [
    "information technology", "it services", "cybersecurity", "software development",
    "cloud services", "medical supplies", "pharmaceutical", "laboratory equipment",
    "janitorial", "food service", "uniforms", "motor vehicle", "weapon system",
    "ammunition", "aircraft parts", "office supplies", "staffing services",
    "personnel augmentation", "temporary staffing", "training services",
    "accounting services", "legal services", "telecommunications", "custodial",
    "groundskeeping", "landscaping maintenance", "furniture",
]


def _score_content(text: str) -> tuple[int, list[str], list[str]]:
    text = text.lower()
    strong_hits = [p for p in _STRONG_POSITIVE_PHRASES if p in text]
    moderate_hits = [p for p in _MODERATE_POSITIVE_PHRASES if p in text]
    negative_hits = [p for p in _NEGATIVE_PHRASES if p in text]
    raw_points = STRONG_POINTS * len(strong_hits) + MODERATE_POINTS * len(moderate_hits)
    return min(raw_points, CONTENT_CAP), strong_hits + moderate_hits, negative_hits


# --- Geography: Louisiana and Mississippi highest — COREWORKS's own explicit regional
# focus — then the broader Gulf Coast/Southeast/Mississippi Valley footprint SAM's
# scorer already uses, kept consistent rather than redefined.
_STATE_POINTS: dict[str, int] = {
    "LA": 15, "MS": 15,  # COREWORKS's named regional focus
    "TX": 6, "AL": 6, "FL": 6, "GA": 6,  # Gulf Coast / Southeast
    "AR": 4, "TN": 4, "MO": 4, "KY": 4,  # Mississippi Valley
}


def _score_geography(location_state: str | None) -> tuple[int, str | None]:
    if not location_state:
        return 0, None
    points = _STATE_POINTS.get(location_state.strip().upper())
    if not points:
        return 0, None
    return points, location_state.strip().upper()


def _why_relevant(positive_hits: list[str], geography_label: str | None) -> str:
    parts: list[str] = []
    if geography_label:
        parts.append(f"Located in {geography_label}.")
    if positive_hits:
        shown = ", ".join(dict.fromkeys(positive_hits))[:200]
        parts.append(f"Scope includes {shown}.")
    if not parts:
        return (
            "No strong Principal-relevant keyword or geography signal was found in the "
            "available title/description — review the source listing directly before deciding."
        )
    return " ".join(parts)


def _why_not_fit(negative_hits: list[str], tier: str) -> str | None:
    if negative_hits:
        return (
            f"The available text also references {', '.join(dict.fromkeys(negative_hits))[:150]}, "
            "which falls outside Principal's core practice — read the full listing before assuming fit."
        )
    if tier in ("possible_match", "low_relevance"):
        return "Limited Principal-specific signal was found in the available text — worth a quick manual check rather than treating this as a confirmed fit."
    return None


def calculate_infrastructure_relevance_score(item: IntelligenceItem) -> IntelligenceItem:
    """No-op for anything not sourced from COREWORKS RFQwire or APEX MyBidMatch —
    mirrors the other three engines' "safe to call unconditionally for every item"
    pattern. Does not call db.flush(); the caller (run_sync) is already inside a
    per-item transaction it commits itself."""
    if item.source not in _APPLIES_TO_SOURCES:
        return item

    text = " ".join(filter(None, [item.title, item.description]))
    content_points, positive_hits, negative_hits = _score_content(text)
    geography_points, geography_label = _score_geography(item.location_state)

    negative_penalty = min(NEGATIVE_POINTS_PER_HIT * len(negative_hits), NEGATIVE_POINTS_CAP)
    raw = content_points + geography_points - negative_penalty
    score = _clamp(raw)
    tier = relevance_tier(score)

    item.infrastructure_relevance_score = score
    item.infrastructure_relevance_rationale = {
        "tier": tier,
        "components": {
            "content": content_points,
            "geography": geography_points,
            "negative_penalty": -negative_penalty,
        },
        "matched_positive_phrases": positive_hits,
        "matched_negative_phrases": negative_hits,
        "why_relevant": _why_relevant(positive_hits, geography_label),
        "why_not_fit": _why_not_fit(negative_hits, tier),
        "disclaimer": (
            "An estimate of whether this listing is worth Principal's attention — not a "
            "measure of pursuit quality (that's the Principal Pursuit Score, which only applies "
            "once this becomes a tracked opportunity). Read the source listing before deciding."
        ),
    }
    return item
