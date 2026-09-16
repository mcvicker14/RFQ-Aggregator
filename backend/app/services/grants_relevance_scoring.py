"""Grant Engineering Relevance Score — "is this grant worth surfacing to Principal as
a possible future source of engineering work?" A fourth, separate engine from the SAM
Relevance Score, the Principal Pursuit Score, and the Early Signal Score — each
answers a different question (see each module's own docstring for its own).

Grants.gov is not primarily a source of grants Principal should apply for — it's an
early-signal source for public infrastructure funding that may later generate an
engineering RFQ (water/wastewater, drainage/flood, transportation, utility, civil
design work) once a recipient plans the resulting project. This score answers that
specific question, not "should Principal apply for this grant."

Production context: fixing Grants.gov's retrieval-time _is_relevant() keyword filter
(removed — see app/connectors/grants_gov.py's module docstring) let a live sync
persist 116 items, most not Principal-relevant, the exact same pattern the SAM.gov
relevance redesign addressed. Same architecture applies here: nothing is dropped at
fetch time, every persisted grant stays available for provenance, and this score
decides what the default Discover view surfaces — see relevance_tier()'s docstring for
the tier boundaries every caller (Discover's default filter, the dashboard's
intelligence counts) imports rather than re-deriving.

Deterministic, template-based, no LLM call — same reasoning as the other three
engines: instant, and works with zero external dependency.
"""
import re

from app.models.enums import IntelligenceCategory
from app.models.intelligence import IntelligenceItem

SOURCE_NAME = "Grants.gov"  # calculate_grants_relevance_score() no-ops for any other source

# Tier boundaries — deliberately the same numeric bands as sam_relevance_scoring.py's,
# for a consistent mental model across the app, even though the two scores measure
# different things and are never compared to each other directly.
HIGH_VALUE_THRESHOLD = 80
RELEVANT_THRESHOLD = 65
POSSIBLE_SIGNAL_THRESHOLD = 50
# Below POSSIBLE_SIGNAL_THRESHOLD = "low relevance" — kept for provenance, never shown
# in any default view.


def relevance_tier(score: int | None) -> str:
    """"unscored" for None — a non-Grants.gov item, or one not yet processed by this
    module. Callers that need "no score" to mean "always show" (Discover's default
    filter, which must never hide other sources) check for None themselves."""
    if score is None:
        return "unscored"
    if score >= HIGH_VALUE_THRESHOLD:
        return "high_value_signal"
    if score >= RELEVANT_THRESHOLD:
        return "relevant_signal"
    if score >= POSSIBLE_SIGNAL_THRESHOLD:
        return "possible_signal"
    return "low_relevance"


def _clamp(value: float, lo: int = 0, hi: int = 100) -> int:
    return int(max(lo, min(hi, round(value))))


def _word_boundary_match(word: str, text: str) -> bool:
    """For short, common-English-word phrases where plain substring matching risks a
    false positive inside an unrelated word — e.g. bare "port" would otherwise match
    inside "transportation" or "opportunity", and "road" inside "broadband". Multi-word
    phrases don't need this (a multi-word substring match essentially never collides by
    accident), so this is only used for the handful of short single-word entries below."""
    return re.search(rf"\b{re.escape(word)}\b", text) is not None


# --- Content: infrastructure/engineering themes that plausibly precede an RFQ ------
#
# One flat list (the task's own theme list wasn't split into strong/moderate tiers the
# way SAM's was) — every match contributes the same weight, capped so no single title
# carries the score by itself; several independent matches (title + description) are
# what actually moves a grant into range, not one generic word.
THEME_POINTS = 15
THEME_CAP = 45

# Multi-word or long/distinctive single-word phrases — plain substring matching is
# safe for these (negligible risk of matching inside an unrelated word).
_THEME_PHRASES_SUBSTRING: list[str] = [
    "water infrastructure", "wastewater", "sanitary sewer", "sewer rehabilitation",
    "water distribution", "water treatment", "wastewater treatment", "stormwater",
    "drainage", "flood mitigation", "flood control", "watershed", "coastal restoration",
    "resiliency", "hazard mitigation", "disaster recovery infrastructure",
    "transportation infrastructure", "public works", "utilities", "pump station",
    "lift station", "treatment plant", "water main", "sewer main", "erosion control",
    "public facility", "public facilities", "infrastructure modernization",
    "capital improvement", "community infrastructure", "environmental infrastructure",
]
# Short single words with a real collision risk inside unrelated words (port inside
# "transportation"/"opportunity"/"support"; road inside "broadband"/"abroad") — see
# _word_boundary_match().
_THEME_WORDS_BOUNDARY: list[str] = ["road", "roads", "bridge", "bridges", "port", "ports", "airport", "airports", "levee", "levees"]

# Deliberately NOT included anywhere above: bare "community", "development", "public",
# "planning", "resilience" (note: not "resiliency", a different word — see module
# docstring) — the task is explicit that these generic terms must never carry a grant
# to relevance by themselves. Every place "public"/"community" appears above, it's
# inside a specific compound (e.g. "public works", "community infrastructure`) that
# means something narrower than the bare word.


def _score_content(text: str) -> tuple[int, list[str]]:
    text = text.lower()
    hits = [p for p in _THEME_PHRASES_SUBSTRING if p in text]
    hits += [w for w in _THEME_WORDS_BOUNDARY if _word_boundary_match(w, text)]
    return min(THEME_POINTS * len(hits), THEME_CAP), hits


# --- Recipient type: plausible future buyers of engineering services ---------------
#
# A grant whose eligible/likely recipient is a public entity that would itself
# commission A/E work later is a stronger signal than one going to, say, a university
# lab or a nonprofit — independent of the grant's stated theme.
RECIPIENT_POINTS = 12
RECIPIENT_CAP = 30

_RECIPIENT_PHRASES: list[str] = [
    "state government", "parish government", "county government", "municipal",
    "public utility", "public utilities", "water district", "sewer district",
    "drainage district", "levee district", "port authority", "airport authority",
    "transportation authority", "tribal government", "tribal nation",
    "public infrastructure agency",
]


def _score_recipient(text: str) -> tuple[int, list[str]]:
    text = text.lower()
    hits = [p for p in _RECIPIENT_PHRASES if p in text]
    return min(RECIPIENT_POINTS * len(hits), RECIPIENT_CAP), hits


# --- Negative themes: clearly-not-an-engineering-signal categories -----------------
NEGATIVE_POINTS_PER_HIT = 15
NEGATIVE_POINTS_CAP = 60

_NEGATIVE_PHRASES: list[str] = [
    "biomedical research", "medical research", "behavioral health", "social services",
    "education program", "scholarship", "humanities", "arts and culture",
    "workforce training", "workforce development", "academic research",
    "law enforcement", "public health program", "scientific research",
    "agricultural research", "farm program", "nonprofit service delivery",
]
# "agriculture grants without water/civil/infrastructure implications" (the task's own
# phrasing) can't be detected by keyword matching alone — a negative-phrase match here
# is a penalty, never a veto (see calculate_grants_relevance_score), so a genuinely
# infrastructure-relevant program that happens to also touch agriculture/research
# (e.g. an NRCS watershed program) can still score well on its real positive signal.


def _score_negative(text: str) -> tuple[int, list[str]]:
    text = text.lower()
    hits = [p for p in _NEGATIVE_PHRASES if p in text]
    return min(NEGATIVE_POINTS_PER_HIT * len(hits), NEGATIVE_POINTS_CAP), hits


# --- Funding size: a bigger program is a stronger signal, but only once scope is
# already established — a $50M grant for scholarships is still a $0 signal here.
FUNDING_BONUS_GATE = 15
_FUNDING_TIERS: list[tuple[float, int]] = [(10_000_000, 12), (1_000_000, 6)]


def _score_funding_size(funding_amount: float | None, scope_points: int) -> tuple[int, str | None]:
    if scope_points < FUNDING_BONUS_GATE or not funding_amount:
        return 0, None
    for floor, points in _FUNDING_TIERS:
        if funding_amount >= floor:
            return points, f"${funding_amount:,.0f} program — large enough to plausibly fund real infrastructure work"
    return 0, None


# --- Award vs. Opportunity: only ever "award" if the connector genuinely set
# awardee_name — never inferred/guessed. Grants.gov's own data model is about funding
# *opportunities* (forecasted/posted/closed/archived statuses — confirmed no "awarded"
# status exists), not specific-recipient awards, so every current Grants.gov item is
# honestly "opportunity". If a future data source or connector enhancement ever does
# provide a real recipient, setting awardee_name is what flips this — not a guess made
# here. Gated the same way as the funding bonus: a random populated awardee_name on an
# otherwise off-topic item must not manufacture relevance out of nothing.
AWARD_BONUS = 15


def _score_award_signal(awardee_name: str | None, scope_points: int) -> tuple[int, str]:
    if awardee_name and scope_points >= FUNDING_BONUS_GATE:
        return AWARD_BONUS, "award"
    return 0, "opportunity"


def _why_relevant(
    item: IntelligenceItem, theme_hits: list[str], recipient_hits: list[str],
    funding_note: str | None, signal_type: str,
) -> str:
    parts: list[str] = []
    if theme_hits:
        shown = ", ".join(dict.fromkeys(theme_hits))[:200]
        parts.append(f"This program funds {shown} and could generate downstream engineering procurement.")
    if recipient_hits:
        shown = ", ".join(dict.fromkeys(recipient_hits))[:150]
        parts.append(f"Eligible/likely recipients include {shown} — plausible future buyers of engineering services.")
    if signal_type == "award":
        parts.append(f"{item.awardee_name} has actually received this funding, not just an open program.")
    if funding_note:
        parts.append(funding_note.capitalize() + ".")
    if not parts:
        return "No strong infrastructure/engineering theme or recipient signal was found in the available title/description — review the source listing directly before deciding."
    return " ".join(parts)


def _why_not_fit(
    item: IntelligenceItem, negative_hits: list[str], signal_type: str, tier: str,
) -> str | None:
    if negative_hits:
        return (
            f"The available text also references {', '.join(dict.fromkeys(negative_hits))[:150]}, "
            "which falls outside Principal's engineering/infrastructure focus — read the full listing "
            "before assuming fit."
        )
    if signal_type == "opportunity" and tier in ("high_value_signal", "relevant_signal"):
        # Grants.gov's connector doesn't populate location_state (see its module
        # docstring) — this deliberately doesn't claim to have checked one. "no
        # Louisiana recipient identified yet" (the task's own example) is Principal's
        # fixed home market, not a per-item location lookup this data doesn't support.
        return (
            "This is a national funding opportunity, not a confirmed local award — real engineering work "
            "depends on a Louisiana-area (or otherwise Principal-relevant) recipient actually receiving "
            "and planning against this funding."
        )
    if tier in ("possible_signal", "low_relevance"):
        return "Limited infrastructure-specific signal was found in the available text — worth a quick manual check rather than treating this as a confirmed lead."
    return None


def calculate_grants_relevance_score(item: IntelligenceItem) -> IntelligenceItem:
    """No-op for anything not sourced from Grants.gov — mirrors
    calculate_sam_relevance_score()/calculate_early_signal_score()'s "safe to call
    unconditionally for every item" pattern. Does not call db.flush(); the caller
    (run_sync) is already inside a per-item transaction it commits itself."""
    if item.source != SOURCE_NAME:
        return item

    text = " ".join(filter(None, [item.title, item.description]))
    content_points, theme_hits = _score_content(text)
    recipient_points, recipient_hits = _score_recipient(text)
    negative_points, negative_hits = _score_negative(text)
    scope_points = content_points + recipient_points
    funding_points, funding_note = _score_funding_size(item.funding_amount, scope_points)
    award_points, signal_type = _score_award_signal(item.awardee_name, scope_points)

    negative_penalty = min(negative_points, NEGATIVE_POINTS_CAP)
    raw = content_points + recipient_points + funding_points + award_points - negative_penalty
    score = _clamp(raw)
    tier = relevance_tier(score)

    item.grants_relevance_score = score
    item.grants_relevance_rationale = {
        "tier": tier,
        "signal_type": signal_type,  # "opportunity" or "award" — see _score_award_signal()
        "components": {
            "content": content_points,
            "recipient": recipient_points,
            "funding_size": funding_points,
            "award_signal": award_points,
            "negative_penalty": -negative_penalty,
        },
        "matched_theme_phrases": theme_hits,
        "matched_recipient_phrases": recipient_hits,
        "matched_negative_phrases": negative_hits,
        "why_relevant": _why_relevant(item, theme_hits, recipient_hits, funding_note, signal_type),
        "why_not_fit": _why_not_fit(item, negative_hits, signal_type, tier),
        "disclaimer": (
            "An estimate of whether this Grants.gov listing could plausibly lead to future engineering "
            "procurement — not a measure of whether Principal should apply for the grant itself, and not "
            "the Early Signal Score (which separately estimates how likely this is to turn into a real "
            "procurement at all). Read the source listing before deciding."
        ),
    }
    return item
