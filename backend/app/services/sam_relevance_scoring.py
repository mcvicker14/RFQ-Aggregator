"""SAM Relevance Score — "is this SAM.gov notice even worth putting in front of
Principal?" A separate question from early_signal_score (a different axis, for
EARLY_SIGNAL items only — see early_signal_scoring.py) and from the Principal Pursuit
Score (app/services/scoring.py, lives on Opportunity, answers "how attractive is this
actual pursuit" once something has already cleared this bar). See
docs/SCORING_METHODOLOGY.md.

Production context: broadening SAM.gov's retrieval (the NAICS-family + all-notice-type
fix) resolved a zero-results incident, but a live sync of 355 records then showed the
predictable next problem — SAM.gov's own NAICS/notice-type tagging is self-reported by
the posting agency and often imprecise, so a broad-but-correctly-filtered fetch still
pulls in a lot of genuinely unrelated federal purchasing. This is Stage 2: nothing is
dropped before persistence (every fetched, non-expired record is kept for intelligence
and auditability — see sam_gov.py), but every SAM-sourced item is scored so the default
Discover view can show what a business-development analyst would actually put in front
of Principal, while every record stays fully inspectable behind a filter.

Deterministic, template-based, no LLM call — same reasoning as the other two scoring
engines: instant, and works with zero external dependency. Matching is phrase/substring
based, case-insensitive; this catches most real-world phrasing (including plurals, since
e.g. "water main" is a substring of "water mains") without the fragility of trying to
hand-write exhaustive linguistic rules.
"""
from app.models.enums import IntelligenceCategory, SetAsideType
from app.models.intelligence import IntelligenceItem

SOURCE_NAME = "SAM.gov"  # calculate_sam_relevance_score() no-ops for any other source

# Tier boundaries — the single source of truth. Every caller that needs to know
# whether a score counts as "the default view should show this" imports these rather
# than re-deriving them, so the promotion gate, Discover's default filter, and the
# dashboard's intelligence counts can never drift out of sync with each other.
HIGHLY_RELEVANT_THRESHOLD = 80
RELEVANT_THRESHOLD = 65
POSSIBLE_MATCH_THRESHOLD = 50
# Below POSSIBLE_MATCH_THRESHOLD = "low relevance" — kept for provenance (never
# deleted), never shown in any default view.


def relevance_tier(score: int | None) -> str:
    """"unscored" for None — a non-SAM item, or a SAM item not yet processed by this
    module. Callers that need "no score" to mean "always show" (e.g. Discover's
    default filter, which must never hide non-SAM sources) check for None themselves
    rather than branching on this string."""
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


# --- Content: Principal's actual practice, by phrase --------------------------------
#
# Strong phrases are near-unambiguous core A/E/civil scope; moderate phrases are
# broader-but-still-meaningful. Content contribution is capped (see CONTENT_CAP) so a
# title needs either one strong hit or several moderate ones to score well on content
# alone — matching "give substantial weight," not "any single generic word is enough."
# Deliberately excludes bare, generic terms ("services", "professional services",
# "construction", "IDIQ" alone) per the explicit instruction not to let those carry a
# record on their own — only phrases specific enough to indicate real engineering/civil
# scope are listed.
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
    "topographic survey", "construction administration", "construction engineering",
    "ce&i", "idiq engineering", "civil idiq", "a/e idiq", "coastal restoration",
    "erosion control", "resiliency", "disaster recovery",
]
_MODERATE_POSITIVE_PHRASES: list[str] = [
    "design services", "roadway", "road improvements", "surveying",
    "infrastructure improvements", "airfield infrastructure",
    "military installation infrastructure", "va medical center utilities",
]

# Categories a record should score very low on if they're clearly the primary scope.
# Substring-matched the same way as the positive list — a record that also happens to
# mention one of these isn't automatically zeroed out (see NEGATIVE_POINTS_PER_HIT and
# the overall clamp), but it's pulled down hard, especially when there's little or no
# positive signal to offset it.
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


# --- NAICS: primary strongest, related modest, everything else nothing -------------
#
# 541330 is Principal's primary code and gets the strongest weight. Related codes
# (architecture/surveying/environmental — plausible parts of an A/E team per the
# user's own framing) contribute a modest bonus, never enough alone to clear even the
# Possible Match floor. No prefix matching against the "54" sector or any other
# NAICS-sector-level credit — that's the exact failure mode this score exists to
# correct (broad SAM retrieval already lets through anything NAICS-54-tagged; this
# stage must not just wave all of it through again).
NAICS_PRIMARY_POINTS = 30
NAICS_RELATED_POINTS = 12
NAICS_PRIMARY = "541330"
NAICS_RELATED = {
    "541310",  # Architectural Services
    "541320",  # Landscape Architecture Services
    "541340",  # Drafting Services
    "541360",  # Geophysical Surveying and Mapping Services
    "541370",  # Surveying and Mapping (except Geophysical) Services
    "541380",  # Testing Laboratories and Services
    "541620",  # Environmental Consulting Services
}


def _score_naics(naics_code: str | None) -> tuple[int, str | None]:
    if not naics_code:
        return 0, None
    code = naics_code.strip()
    if code == NAICS_PRIMARY:
        return NAICS_PRIMARY_POINTS, f"NAICS {code} is Principal's primary code"
    if code in NAICS_RELATED:
        return NAICS_RELATED_POINTS, f"NAICS {code} is a related-discipline code"
    return 0, None


# --- Agency: Principal's strategic customers ----------------------------------------
#
# Matched against agency_name (the top-level department segment — see sam_gov.py's
# fullParentPathName handling). Point values are kept well below either visibility
# floor on their own ("agency alone must not make an irrelevant procurement surface")
# — even the highest tier only matters once combined with real content/NAICS signal.
AGENCY_HIGHEST_POINTS = 15
AGENCY_STRONG_POINTS = 10
_AGENCY_HIGHEST = ["veterans affairs", "army corps of engineers", "usace"]
_AGENCY_STRONG = [
    "air force", "department of defense", "federal emergency management", "fema",
    "natural resources conservation", "nrcs",
]


def _score_agency(agency_name: str | None) -> tuple[int, str | None]:
    if not agency_name:
        return 0, None
    text = agency_name.lower()
    if any(k in text for k in _AGENCY_HIGHEST):
        return AGENCY_HIGHEST_POINTS, agency_name
    if any(k in text for k in _AGENCY_STRONG):
        return AGENCY_STRONG_POINTS, agency_name
    return 0, None


# --- Geography: Louisiana highest, then Gulf Coast/Southeast/Mississippi Valley -----
_STATE_POINTS: dict[str, int] = {
    "LA": 8,
    "TX": 5, "MS": 5, "AL": 5, "FL": 5, "GA": 5,  # Gulf Coast / Southeast
    "AR": 4, "TN": 4, "MO": 4, "KY": 4,  # Mississippi Valley
}


def _score_geography(location_state: str | None) -> tuple[int, str | None]:
    if not location_state:
        return 0, None
    points = _STATE_POINTS.get(location_state.strip().upper())
    if not points:
        return 0, None
    return points, location_state.strip().upper()


# --- Notice type: Sources Sought / Presolicitation get positioning value, not a
# penalty for not yet being a released solicitation. AWARD_INTELLIGENCE and
# LIVE_OPPORTUNITY are both neutral here (the "already released" case is the norm this
# bonus is relative to, and award-notice relevance is purely about topical fit).
PRE_SOLICITATION_BONUS = 8
_NOTICE_TYPE_LABEL = {
    IntelligenceCategory.PRE_SOLICITATION: "Sources Sought/Presolicitation",
    IntelligenceCategory.LIVE_OPPORTUNITY: "solicitation",
    IntelligenceCategory.AWARD_INTELLIGENCE: "award notice",
}


def _score_notice_type(category: IntelligenceCategory) -> int:
    return PRE_SOLICITATION_BONUS if category == IntelligenceCategory.PRE_SOLICITATION else 0


# --- Set-aside: only after the technical scope already looks relevant --------------
#
# SET_ASIDE_GATE is checked against content+NAICS points only (never agency/geography)
# — an SDVOSB set-aside on an obviously-unrelated procurement must not be rescued into
# relevance just because Principal happens to hold that status.
SET_ASIDE_GATE = 15
SDVOSB_POINTS = 12
SMALL_BUSINESS_POINTS = 6


def _score_set_aside(set_aside: SetAsideType | None, scope_points: int) -> tuple[int, str | None]:
    if scope_points < SET_ASIDE_GATE or set_aside is None:
        return 0, None
    if set_aside == SetAsideType.SDVOSB:
        return SDVOSB_POINTS, "is restricted to SDVOSBs"
    if set_aside in (SetAsideType.SMALL_BUSINESS, SetAsideType.EIGHT_A, SetAsideType.HUBZONE, SetAsideType.WOSB, SetAsideType.EDWOSB):
        return SMALL_BUSINESS_POINTS, "carries a small-business set-aside"
    return 0, None


def _why_relevant(
    item: IntelligenceItem, positive_hits: list[str], naics_reason: str | None,
    agency_label: str | None, set_aside_label: str | None,
) -> str:
    parts: list[str] = []
    lead_bits = [b for b in (agency_label, _NOTICE_TYPE_LABEL.get(item.intelligence_category)) if b]
    lead = " ".join(lead_bits)
    if naics_reason:
        lead = f"{lead} ({naics_reason})" if lead else naics_reason.capitalize()
    if lead:
        parts.append(lead.strip() + ".")

    if positive_hits:
        shown = ", ".join(dict.fromkeys(positive_hits))[:200]  # de-dup, keep it short
        sentence = f"Scope includes {shown}"
        if set_aside_label:
            sentence += f", and the notice {set_aside_label}"
        parts.append(sentence + ".")
    elif set_aside_label:
        parts.append(f"The notice {set_aside_label}.")

    if not parts:
        return "No strong Principal-relevant keyword, NAICS, or agency signal was found in the available title/description — review the source notice directly before deciding."
    return " ".join(parts)


def _why_not_fit(
    item: IntelligenceItem, negative_hits: list[str], naics_related_only: bool, tier: str,
) -> str | None:
    if negative_hits:
        return (
            f"The available text also references {', '.join(dict.fromkeys(negative_hits))[:150]}, "
            "which falls outside Principal's core practice — read the full notice before assuming fit."
        )
    if naics_related_only:
        return (
            f"NAICS {item.naics_code} is a related, not primary, code for Principal — the scope may "
            "lean toward a discipline (e.g. architecture, surveying, or environmental) that would "
            "likely require a teaming partner."
        )
    if tier in ("possible_match", "low_relevance"):
        return "Limited Principal-specific signal was found in the available text — worth a quick manual check rather than treating this as a confirmed fit."
    return None


def calculate_sam_relevance_score(item: IntelligenceItem) -> IntelligenceItem:
    """No-op for anything not sourced from SAM.gov — mirrors calculate_early_signal_score's
    "safe to call unconditionally for every item" pattern. Does not call db.flush();
    the caller (run_sync) is already inside a per-item transaction it commits itself."""
    if item.source != SOURCE_NAME:
        return item

    text = " ".join(filter(None, [item.title, item.description]))
    content_points, positive_hits, negative_hits = _score_content(text)
    naics_points, naics_reason = _score_naics(item.naics_code)
    agency_points, agency_label = _score_agency(item.agency_name)
    geography_points, _ = _score_geography(item.location_state)
    notice_type_points = _score_notice_type(item.intelligence_category)
    scope_points = content_points + naics_points
    set_aside_points, set_aside_label = _score_set_aside(item.set_aside, scope_points)

    negative_penalty = min(NEGATIVE_POINTS_PER_HIT * len(negative_hits), NEGATIVE_POINTS_CAP)
    raw = (
        content_points + naics_points + agency_points + geography_points
        + notice_type_points + set_aside_points - negative_penalty
    )
    score = _clamp(raw)
    tier = relevance_tier(score)

    item.sam_relevance_score = score
    item.sam_relevance_rationale = {
        "tier": tier,
        "components": {
            "content": content_points,
            "naics": naics_points,
            "agency": agency_points,
            "geography": geography_points,
            "notice_type": notice_type_points,
            "set_aside": set_aside_points,
            "negative_penalty": -negative_penalty,
        },
        "matched_positive_phrases": positive_hits,
        "matched_negative_phrases": negative_hits,
        "why_relevant": _why_relevant(item, positive_hits, naics_reason, agency_label, set_aside_label),
        "why_not_fit": _why_not_fit(item, negative_hits, naics_points == NAICS_RELATED_POINTS, tier),
        "disclaimer": (
            "An estimate of whether this SAM.gov notice is worth Principal's attention — not a "
            "measure of pursuit quality (that's the Principal Pursuit Score, which only applies "
            "once this becomes a tracked opportunity). Read the source notice before deciding."
        ),
    }
    return item
