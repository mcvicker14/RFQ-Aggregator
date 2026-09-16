"""Tests for the Grant Engineering Relevance Score engine
(app/services/grants_relevance_scoring.py).

Includes two illustrative fixture sets at the bottom -- ten built to plausibly lead to
future engineering procurement and ten built to be correctly rejected -- directly
requested as part of validating "that the system is surfacing plausible future
engineering work, not generic government funding." These are realistic, hand-built
fixtures modeled on the user's own theme/recipient/negative-category lists, run
through pytest -v for a readable, quotable report -- NOT a re-score of the real 116
production Grants.gov records, which this sandbox cannot reach (no network path to
Render's database). See the task's closing summary for how to get the real breakdown.
"""
from app.models.enums import IntelligenceCategory
from app.models.intelligence import IntelligenceItem
from datetime import datetime, timezone

import pytest

from app.services.grants_relevance_scoring import (
    HIGH_VALUE_THRESHOLD,
    POSSIBLE_SIGNAL_THRESHOLD,
    RELEVANT_THRESHOLD,
    SOURCE_NAME,
    calculate_grants_relevance_score,
    relevance_tier,
)

NOW = datetime.now(timezone.utc)


def _item(**overrides) -> IntelligenceItem:
    defaults = dict(
        source=SOURCE_NAME,
        title="Untitled Grant Opportunity",
        description=None,
        funding_amount=None,
        awardee_name=None,
        intelligence_category=IntelligenceCategory.EARLY_SIGNAL,
        external_id="x", intelligence_source_id=None,
        retrieved_at=NOW, first_detected_at=NOW, last_seen_at=NOW,
    )
    defaults.update(overrides)
    return IntelligenceItem(**defaults)


# --- Core behavior -------------------------------------------------------------------

def test_no_op_for_non_grants_source():
    item = _item(source="SAM.gov", title="Water Infrastructure Wastewater Treatment Program", funding_amount=5_000_000)
    calculate_grants_relevance_score(item)
    assert item.grants_relevance_score is None
    assert item.grants_relevance_rationale is None


def test_relevance_tier_boundaries():
    assert relevance_tier(None) == "unscored"
    assert relevance_tier(HIGH_VALUE_THRESHOLD) == "high_value_signal"
    assert relevance_tier(HIGH_VALUE_THRESHOLD - 1) == "relevant_signal"
    assert relevance_tier(RELEVANT_THRESHOLD) == "relevant_signal"
    assert relevance_tier(RELEVANT_THRESHOLD - 1) == "possible_signal"
    assert relevance_tier(POSSIBLE_SIGNAL_THRESHOLD) == "possible_signal"
    assert relevance_tier(POSSIBLE_SIGNAL_THRESHOLD - 1) == "low_relevance"
    assert relevance_tier(0) == "low_relevance"
    assert relevance_tier(100) == "high_value_signal"


def test_score_is_always_clamped_to_0_100_range():
    from app.services.grants_relevance_scoring import _NEGATIVE_PHRASES
    item = _item(title=" ".join(_NEGATIVE_PHRASES))
    calculate_grants_relevance_score(item)
    assert 0 <= item.grants_relevance_score <= 100

    from app.services.grants_relevance_scoring import _RECIPIENT_PHRASES, _THEME_PHRASES_SUBSTRING
    item2 = _item(
        title=" ".join(_THEME_PHRASES_SUBSTRING), description=" ".join(_RECIPIENT_PHRASES),
        funding_amount=50_000_000, awardee_name="Example Recipient",
    )
    calculate_grants_relevance_score(item2)
    assert 0 <= item2.grants_relevance_score <= 100


# --- The user's explicit correctness requirements -------------------------------------

def test_generic_terms_alone_score_zero():
    # "Do not let generic terms like: community, development, public, planning,
    # resilience -- make a grant relevant by themselves."
    item = _item(title="Community Development and Public Planning Resilience Grant")
    calculate_grants_relevance_score(item)
    assert item.grants_relevance_score == 0
    assert item.grants_relevance_rationale["components"]["content"] == 0
    assert item.grants_relevance_rationale["components"]["recipient"] == 0


def test_resiliency_is_scored_but_bare_resilience_is_not():
    # "resiliency" (a theme word) and "resilience" (a forbidden generic term) are
    # different literal substrings -- confirms they're not accidentally conflated.
    resiliency_item = _item(title="Coastal Resiliency Infrastructure Program")
    resilience_item = _item(title="Community Resilience Planning Grant")
    calculate_grants_relevance_score(resiliency_item)
    calculate_grants_relevance_score(resilience_item)
    assert resiliency_item.grants_relevance_score > 0
    assert resilience_item.grants_relevance_score == 0


def test_content_alone_cannot_reach_relevant_threshold():
    # THEME_CAP (45) is deliberately below RELEVANT_THRESHOLD (65) -- a title packed
    # with every theme phrase still isn't enough by itself.
    from app.services.grants_relevance_scoring import _THEME_PHRASES_SUBSTRING
    item = _item(title=" ".join(_THEME_PHRASES_SUBSTRING))
    calculate_grants_relevance_score(item)
    assert item.grants_relevance_score < RELEVANT_THRESHOLD


def test_recipient_alone_cannot_reach_relevant_threshold():
    # RECIPIENT_CAP (30) is also below RELEVANT_THRESHOLD -- a plausible-buyer recipient
    # type with zero technical scope isn't enough by itself either. Deliberately uses
    # only the recipient phrases with no topical overlap with _THEME_PHRASES_SUBSTRING
    # or _THEME_WORDS_BOUNDARY -- "drainage district", "public utilities", "port
    # authority", "airport authority", and "levee district" are excluded here because
    # they legitimately also read as infrastructure-theme signal ("drainage", "port",
    # etc. are self-describing), which is correct scoring behavior, not something this
    # "recipient with truly zero content signal" test should be fighting.
    clean_recipient_phrases = [
        "state government", "parish government", "county government", "municipal",
        "public utility", "water district", "sewer district", "transportation authority",
        "tribal government", "tribal nation", "public infrastructure agency",
    ]
    item = _item(title="Grant Program", description=" ".join(clean_recipient_phrases))
    calculate_grants_relevance_score(item)
    assert item.grants_relevance_rationale["components"]["content"] == 0  # confirms genuinely content-free
    assert item.grants_relevance_score < RELEVANT_THRESHOLD


def test_content_and_recipient_together_can_reach_relevant():
    item = _item(
        title="Watershed Engineering, Hazard Mitigation, and Erosion Control Infrastructure Grant",
        description="Eligible applicants include water district and public utility entities.",
    )
    calculate_grants_relevance_score(item)
    assert item.grants_relevance_score >= RELEVANT_THRESHOLD


def test_funding_size_bonus_gated_behind_scope_relevance():
    # "Funding size must not override an irrelevant technical scope."
    no_scope_signal = _item(title="Grant Program", funding_amount=50_000_000)
    with_scope_signal = _item(
        title="Water Infrastructure and Wastewater Treatment Program", funding_amount=50_000_000,
        description="Eligible applicants: state government, municipal.",
    )
    without_funding = _item(
        title="Water Infrastructure and Wastewater Treatment Program", funding_amount=None,
        description="Eligible applicants: state government, municipal.",
    )
    calculate_grants_relevance_score(no_scope_signal)
    calculate_grants_relevance_score(with_scope_signal)
    calculate_grants_relevance_score(without_funding)

    assert no_scope_signal.grants_relevance_score == 0  # funding size alone contributes nothing
    assert with_scope_signal.grants_relevance_score > without_funding.grants_relevance_score  # but adds once scope is real


def test_larger_funding_tier_scores_higher_than_smaller_given_equal_scope():
    base = dict(title="Water Infrastructure and Wastewater Treatment Program", description="state government, municipal")
    small = _item(**base, funding_amount=2_000_000)
    large = _item(**base, funding_amount=25_000_000)
    below_gate = _item(**base, funding_amount=500_000)
    calculate_grants_relevance_score(small)
    calculate_grants_relevance_score(large)
    calculate_grants_relevance_score(below_gate)
    assert large.grants_relevance_score > small.grants_relevance_score > below_gate.grants_relevance_score


def test_award_signal_requires_both_awardee_name_and_scope():
    # Award vs. Opportunity: never inferred from awardee_name alone if scope is empty.
    awardee_no_scope = _item(title="Grant Program", awardee_name="City of Example")
    calculate_grants_relevance_score(awardee_no_scope)
    assert awardee_no_scope.grants_relevance_score == 0
    assert awardee_no_scope.grants_relevance_rationale["signal_type"] == "opportunity"


def test_award_scores_higher_than_otherwise_identical_opportunity():
    base = dict(title="Water Infrastructure and Wastewater Treatment Program", description="state government, municipal")
    opportunity = _item(**base, awardee_name=None)
    award = _item(**base, awardee_name="City of Example")
    calculate_grants_relevance_score(opportunity)
    calculate_grants_relevance_score(award)
    assert opportunity.grants_relevance_rationale["signal_type"] == "opportunity"
    assert award.grants_relevance_rationale["signal_type"] == "award"
    assert award.grants_relevance_score > opportunity.grants_relevance_score


def test_award_status_never_inferred_when_grants_gov_provides_no_recipient_data():
    # Grants.gov's own data model has no "Awarded" status with recipient data (see
    # module docstring) -- every current item leaves awardee_name unset, so this must
    # honestly default to "opportunity", never guessed from theme/recipient strength.
    item = _item(title="Water Infrastructure and Wastewater Treatment Program", description="state government, municipal, public utility")
    calculate_grants_relevance_score(item)
    assert item.awardee_name is None
    assert item.grants_relevance_rationale["signal_type"] == "opportunity"


def test_negative_phrase_pulls_down_an_otherwise_relevant_grant():
    clean = _item(title="Water Infrastructure and Wastewater Treatment Program", description="state government, municipal")
    mixed = _item(
        title="Water Infrastructure and Wastewater Treatment Program",
        description="state government, municipal; also includes a workforce training component",
    )
    calculate_grants_relevance_score(clean)
    calculate_grants_relevance_score(mixed)
    assert mixed.grants_relevance_score < clean.grants_relevance_score


def test_negative_phrase_is_a_penalty_not_a_veto_for_a_strong_infrastructure_signal():
    # The module docstring's own claim: an NRCS-style watershed program that also
    # touches agricultural research should still clear the possible-signal floor, not
    # be zeroed out the way a purely negative-themed grant would be.
    item = _item(
        title="Watershed Engineering, Hazard Mitigation, and Erosion Control Infrastructure Grant",
        description="Program includes an agricultural research component; eligible recipients include water district and public utility entities.",
    )
    calculate_grants_relevance_score(item)
    assert "agricultural research" in item.grants_relevance_rationale["matched_negative_phrases"]
    assert item.grants_relevance_score >= POSSIBLE_SIGNAL_THRESHOLD  # penalized, not zeroed


# --- Explanation text ------------------------------------------------------------------

def test_why_relevant_mentions_theme_and_recipient():
    item = _item(
        title="Water Infrastructure and Wastewater Treatment Program",
        description="Eligible applicants: state government, municipal.",
    )
    calculate_grants_relevance_score(item)
    why = item.grants_relevance_rationale["why_relevant"]
    assert "water infrastructure" in why.lower() or "wastewater" in why.lower()
    assert "state government" in why.lower() or "municipal" in why.lower()


def test_why_relevant_mentions_awardee_when_award_signal_present():
    item = _item(
        title="Water Infrastructure and Wastewater Treatment Program",
        description="Eligible applicants: state government, municipal.",
        awardee_name="City of Example",
    )
    calculate_grants_relevance_score(item)
    assert "City of Example" in item.grants_relevance_rationale["why_relevant"]


def test_why_not_fit_surfaces_matched_negative_phrases():
    item = _item(
        title="Water Infrastructure and Wastewater Treatment Program",
        description="state government, municipal; also includes a scholarship component",
    )
    calculate_grants_relevance_score(item)
    why_not = item.grants_relevance_rationale["why_not_fit"]
    assert why_not is not None
    assert "scholarship" in why_not.lower()


def test_why_not_fit_flags_national_opportunity_without_confirmed_local_recipient():
    item = _item(
        title="Water Infrastructure and Wastewater Treatment Program",
        description="Eligible applicants: state government, municipal, public utility.",
        awardee_name=None,
    )
    calculate_grants_relevance_score(item)
    assert item.grants_relevance_rationale["tier"] in ("high_value_signal", "relevant_signal")
    why_not = item.grants_relevance_rationale["why_not_fit"]
    assert why_not is not None
    assert "not a confirmed local award" in why_not.lower()


def test_why_not_fit_gives_limited_signal_caveat_for_possible_signal_tier():
    item = _item(
        title="Drainage and Stormwater Watershed Improvement Grant",
        description="Eligible applicants include municipal government entities.",
    )
    calculate_grants_relevance_score(item)
    assert item.grants_relevance_rationale["tier"] == "possible_signal"
    why_not = item.grants_relevance_rationale["why_not_fit"]
    assert why_not is not None
    assert "limited infrastructure-specific signal" in why_not.lower()


def test_confidently_relevant_award_item_has_no_why_not_fit_caveat():
    item = _item(
        title="Transportation Infrastructure Investment — Roads and Bridges Capital Improvement Program",
        description="Awarded to City of Example municipal government for public works capital improvement projects.",
        funding_amount=20_000_000, awardee_name="City of Example",
    )
    calculate_grants_relevance_score(item)
    assert item.grants_relevance_rationale["tier"] in ("high_value_signal", "relevant_signal")
    assert item.grants_relevance_rationale["why_not_fit"] is None


def test_rationale_has_expected_component_keys_and_a_non_empty_narrative():
    item = _item(title="Water Infrastructure and Wastewater Treatment Program", description="state government, municipal")
    calculate_grants_relevance_score(item)
    rationale = item.grants_relevance_rationale
    assert set(rationale["components"]) == {"content", "recipient", "funding_size", "award_signal", "negative_penalty"}
    assert rationale["why_relevant"]
    assert rationale["disclaimer"]
    assert rationale["tier"] == relevance_tier(item.grants_relevance_score)


# --- Illustrative fixture sets: 10 plausible-engineering-signal, 10 correctly-rejected -
#
# Hand-built from the user's own theme/recipient/negative-category lists, not real
# production data (this sandbox cannot reach the live 116-record production dataset --
# see the task's closing summary). Run with -v for a quotable, per-example report.

PLAUSIBLE_SIGNAL_FIXTURES = [
    pytest.param(
        dict(
            title="Water and Sanitary Sewer Infrastructure Improvement Grant Program",
            description="Eligible applicants include state government, municipal, and public utility entities for "
                         "wastewater treatment and water distribution system upgrades.",
            funding_amount=15_000_000,
        ),
        id="Water/sewer infrastructure — state/municipal/utility, $15M",
    ),
    pytest.param(
        dict(
            title="Flood Control and Levee Rehabilitation Infrastructure Program",
            description="Grants available to county government and levee district applicants for flood mitigation "
                         "and drainage improvements.",
            funding_amount=5_000_000,
        ),
        id="Flood control/levee — county/levee district, $5M",
    ),
    pytest.param(
        dict(
            title="Hazard Mitigation Grant Program — Disaster Recovery Infrastructure for Public Facilities",
            description="Open to parish government and state government applicants for resiliency and coastal "
                         "restoration infrastructure investments.",
        ),
        id="FEMA-style hazard mitigation — parish/state government",
    ),
    pytest.param(
        dict(
            title="Transportation Infrastructure Investment — Roads and Bridges Capital Improvement Program",
            description="Awarded to City of Example municipal government for public works capital improvement projects.",
            funding_amount=20_000_000, awardee_name="City of Example",
        ),
        id="Transportation/roads/bridges — confirmed award, $20M",
    ),
    pytest.param(
        dict(
            title="Stormwater Management and Drainage District Infrastructure Grant",
            description="Eligible applicants: drainage district, water district, and sewer district entities.",
            funding_amount=2_000_000,
        ),
        id="Stormwater/drainage — water/sewer/drainage district, $2M",
    ),
    pytest.param(
        dict(
            title="Port and Airport Infrastructure Resiliency Improvement Program",
            description="Open to port authority and airport authority applicants for erosion control and site "
                         "infrastructure needs.",
        ),
        id="Port/airport authority — resiliency/erosion control",
    ),
    pytest.param(
        dict(
            title="Tribal Water Treatment Plant Infrastructure Modernization Award",
            description="Funded project awarded to the Example Tribal Nation for treatment plant upgrades and "
                         "pump station rehabilitation.",
            funding_amount=12_000_000, awardee_name="Example Tribal Nation",
        ),
        id="Tribal water treatment plant — confirmed award, $12M",
    ),
    pytest.param(
        dict(
            title="Watershed Restoration and Coastal Resiliency Infrastructure Initiative",
            description="State government and county government entities are eligible to apply for environmental "
                         "infrastructure and hazard mitigation projects.",
            funding_amount=3_000_000,
        ),
        id="Watershed/coastal resiliency — state/county government, $3M",
    ),
    pytest.param(
        dict(
            title="Water Main and Sewer Main Replacement Capital Improvement Grant",
            description="Public utility and municipal applicants are eligible for this capital improvement funding "
                         "opportunity.",
            funding_amount=25_000_000,
        ),
        id="Water/sewer main replacement — public utility/municipal, $25M",
    ),
    pytest.param(
        dict(
            title="Airport Authority Public Facilities and Transportation Infrastructure Award",
            description="This funded project was awarded to the Example Airport Authority for public facility and "
                         "site infrastructure improvements including erosion control.",
            awardee_name="Example Airport Authority",
        ),
        id="Airport authority — public facilities/transportation, confirmed award",
    ),
]

CORRECTLY_REJECTED_FIXTURES = [
    pytest.param(
        dict(title="Biomedical Research Innovation Grant Program",
             description="Supports medical research institutions advancing clinical science."),
        id="biomedical/medical research",
    ),
    pytest.param(
        dict(title="Behavioral Health and Social Services Support Grant",
             description="Funding for community behavioral health and social services programs."),
        id="behavioral health/social services",
    ),
    pytest.param(
        dict(title="Scholarship and Education Program Grant for Underserved Students"),
        id="education program/scholarship",
    ),
    pytest.param(
        dict(title="Humanities and Arts and Culture Preservation Grant"),
        id="humanities/arts and culture",
    ),
    pytest.param(
        dict(title="Workforce Training and Workforce Development Initiative"),
        id="workforce training/development",
    ),
    pytest.param(
        dict(title="Scientific Research and Academic Research Fellowship Program"),
        id="scientific/academic research",
    ),
    pytest.param(
        dict(title="Law Enforcement Training and Equipment Grant Program"),
        id="law enforcement",
    ),
    pytest.param(
        dict(title="Public Health Program for Community Wellness Initiatives"),
        id="public health program (non-infrastructure)",
    ),
    pytest.param(
        dict(title="Agricultural Research and Farm Program Support Grant"),
        id="agricultural research/farm program",
    ),
    pytest.param(
        dict(title="Community Development and Public Planning Resilience Grant"),
        id="generic terms only (community/development/public/planning/resilience)",
    ),
]


@pytest.mark.parametrize("fields", [p.values[0] for p in PLAUSIBLE_SIGNAL_FIXTURES], ids=[p.id for p in PLAUSIBLE_SIGNAL_FIXTURES])
def test_plausible_signal_fixture_scores_at_least_relevant(fields):
    item = _item(**fields)
    calculate_grants_relevance_score(item)
    assert item.grants_relevance_score >= RELEVANT_THRESHOLD, (
        f"expected >= {RELEVANT_THRESHOLD}, got {item.grants_relevance_score} "
        f"(rationale: {item.grants_relevance_rationale})"
    )


@pytest.mark.parametrize("fields", [p.values[0] for p in CORRECTLY_REJECTED_FIXTURES], ids=[p.id for p in CORRECTLY_REJECTED_FIXTURES])
def test_correctly_rejected_fixture_scores_below_possible_signal(fields):
    item = _item(**fields)
    calculate_grants_relevance_score(item)
    assert item.grants_relevance_score < POSSIBLE_SIGNAL_THRESHOLD, (
        f"expected < {POSSIBLE_SIGNAL_THRESHOLD}, got {item.grants_relevance_score} "
        f"(rationale: {item.grants_relevance_rationale})"
    )
