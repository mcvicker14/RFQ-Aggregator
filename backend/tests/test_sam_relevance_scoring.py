"""Tests for the SAM Relevance Score engine (app/services/sam_relevance_scoring.py).

Includes two illustrative fixture sets at the bottom — ten built to score Highly
Relevant and ten built to be correctly rejected — directly requested as part of
verifying "the model's judgment actually resembles how [the user] would look for
Principal business." These are realistic, hand-built fixtures modeled on the user's
own keyword/agency/negative-category lists, run through pytest -v for a readable,
quotable report — NOT a re-score of real production data, which this sandbox cannot
reach (no network path to Render's database). See the task's closing summary for how
to get the real 355-record breakdown.
"""
from datetime import datetime, timezone

import pytest

from app.models.enums import IntelligenceCategory, SetAsideType
from app.models.intelligence import IntelligenceItem
from app.services.sam_relevance_scoring import (
    HIGHLY_RELEVANT_THRESHOLD,
    POSSIBLE_MATCH_THRESHOLD,
    RELEVANT_THRESHOLD,
    SOURCE_NAME,
    calculate_sam_relevance_score,
    relevance_tier,
)

NOW = datetime.now(timezone.utc)


def _item(**overrides) -> IntelligenceItem:
    defaults = dict(
        source=SOURCE_NAME,
        title="Untitled Notice",
        description=None,
        naics_code=None,
        agency_name=None,
        location_state=None,
        set_aside=None,
        intelligence_category=IntelligenceCategory.LIVE_OPPORTUNITY,
        external_id="x", intelligence_source_id=None,
        retrieved_at=NOW, first_detected_at=NOW, last_seen_at=NOW,
    )
    defaults.update(overrides)
    return IntelligenceItem(**defaults)


# --- Core behavior -------------------------------------------------------------------

def test_no_op_for_non_sam_source():
    item = _item(source="USAspending.gov", title="Civil Engineering Design Services", naics_code="541330")
    calculate_sam_relevance_score(item)
    assert item.sam_relevance_score is None
    assert item.sam_relevance_rationale is None


def test_relevance_tier_boundaries():
    assert relevance_tier(None) == "unscored"
    assert relevance_tier(HIGHLY_RELEVANT_THRESHOLD) == "highly_relevant"
    assert relevance_tier(HIGHLY_RELEVANT_THRESHOLD - 1) == "relevant"
    assert relevance_tier(RELEVANT_THRESHOLD) == "relevant"
    assert relevance_tier(RELEVANT_THRESHOLD - 1) == "possible_match"
    assert relevance_tier(POSSIBLE_MATCH_THRESHOLD) == "possible_match"
    assert relevance_tier(POSSIBLE_MATCH_THRESHOLD - 1) == "low_relevance"
    assert relevance_tier(0) == "low_relevance"
    assert relevance_tier(100) == "highly_relevant"


def test_score_is_always_clamped_to_0_100_range():
    # Deliberately packed with every negative phrase at once, no positive signal.
    from app.services.sam_relevance_scoring import _NEGATIVE_PHRASES
    item = _item(title=" ".join(_NEGATIVE_PHRASES), naics_code="000000")
    calculate_sam_relevance_score(item)
    assert 0 <= item.sam_relevance_score <= 100

    from app.services.sam_relevance_scoring import _STRONG_POSITIVE_PHRASES
    item2 = _item(
        title=" ".join(_STRONG_POSITIVE_PHRASES), naics_code="541330", agency_name="Department of Veterans Affairs",
        location_state="LA", set_aside=SetAsideType.SDVOSB, intelligence_category=IntelligenceCategory.PRE_SOLICITATION,
    )
    calculate_sam_relevance_score(item2)
    assert 0 <= item2.sam_relevance_score <= 100


# --- The user's explicit correctness requirements -------------------------------------

def test_naics_541330_alone_does_not_reach_relevant():
    # "A 541330 record can still be irrelevant if the actual scope does not fit
    # Principal" / "Do not let NAICS sector 54 alone make a record relevant."
    item = _item(title="Task Order 0004", naics_code="541330")
    calculate_sam_relevance_score(item)
    assert item.sam_relevance_score < RELEVANT_THRESHOLD


def test_bare_naics_54_sector_code_not_in_related_set_gets_no_naics_credit():
    # 541511 (Custom Computer Programming) is under NAICS sector 54 but is not
    # Principal's primary code nor in the related-discipline set — must get zero
    # NAICS credit, proving there's no accidental "54" prefix matching anywhere.
    in_related_set = _item(title="", naics_code="541370")  # Surveying — related
    not_related = _item(title="", naics_code="541511")  # IT programming — sector 54, not related
    calculate_sam_relevance_score(in_related_set)
    calculate_sam_relevance_score(not_related)
    assert in_related_set.sam_relevance_score > not_related.sam_relevance_score
    assert not_related.sam_relevance_score == 0


def test_agency_alone_must_not_surface_an_irrelevant_procurement():
    # VA (highest agency tier) posting something with clear negative signal and zero
    # positive content/NAICS signal must still land low.
    item = _item(title="Uniforms and Laundry Services", agency_name="Department of Veterans Affairs")
    calculate_sam_relevance_score(item)
    assert item.sam_relevance_score < POSSIBLE_MATCH_THRESHOLD


def test_generic_services_terms_do_not_carry_a_record():
    item = _item(title="Professional Services Support Contract", naics_code="561499")
    calculate_sam_relevance_score(item)
    assert item.sam_relevance_score < POSSIBLE_MATCH_THRESHOLD


def test_set_aside_bonus_gated_behind_scope_relevance():
    no_scope_signal = _item(title="Task Order 0009", set_aside=SetAsideType.SDVOSB)
    with_scope_signal = _item(title="Civil Engineering Design Services", naics_code="541330", set_aside=SetAsideType.SDVOSB)
    without_set_aside = _item(title="Civil Engineering Design Services", naics_code="541330", set_aside=None)

    calculate_sam_relevance_score(no_scope_signal)
    calculate_sam_relevance_score(with_scope_signal)
    calculate_sam_relevance_score(without_set_aside)

    assert no_scope_signal.sam_relevance_score == 0  # set-aside alone contributes nothing
    assert with_scope_signal.sam_relevance_score > without_set_aside.sam_relevance_score  # but adds once scope is real


def test_sdvosb_scores_higher_than_plain_small_business_given_equal_scope():
    sdvosb = _item(title="Civil Engineering Design Services", naics_code="541330", set_aside=SetAsideType.SDVOSB)
    small_biz = _item(title="Civil Engineering Design Services", naics_code="541330", set_aside=SetAsideType.SMALL_BUSINESS)
    calculate_sam_relevance_score(sdvosb)
    calculate_sam_relevance_score(small_biz)
    assert sdvosb.sam_relevance_score > small_biz.sam_relevance_score


def test_related_naics_scores_lower_than_primary_given_equal_everything_else():
    primary = _item(title="", naics_code="541330")
    related = _item(title="", naics_code="541310")  # Architectural Services
    calculate_sam_relevance_score(primary)
    calculate_sam_relevance_score(related)
    assert primary.sam_relevance_score > related.sam_relevance_score


def test_sources_sought_gets_strategic_bonus_over_an_otherwise_identical_solicitation():
    presolicitation = _item(
        title="Civil Engineering Design Services", naics_code="541330",
        intelligence_category=IntelligenceCategory.PRE_SOLICITATION,
    )
    solicitation = _item(
        title="Civil Engineering Design Services", naics_code="541330",
        intelligence_category=IntelligenceCategory.LIVE_OPPORTUNITY,
    )
    calculate_sam_relevance_score(presolicitation)
    calculate_sam_relevance_score(solicitation)
    assert presolicitation.sam_relevance_score > solicitation.sam_relevance_score


def test_negative_phrase_pulls_down_an_otherwise_relevant_notice():
    clean = _item(title="Civil Engineering Design Services for Water Main Replacement", naics_code="541330")
    mixed = _item(
        title="Civil Engineering Design Services for Water Main Replacement, including Staffing Services",
        naics_code="541330",
    )
    calculate_sam_relevance_score(clean)
    calculate_sam_relevance_score(mixed)
    assert mixed.sam_relevance_score < clean.sam_relevance_score


# --- Explanation text ------------------------------------------------------------------

def test_why_relevant_mentions_agency_and_matched_scope():
    item = _item(
        title="Water Main and Sanitary Sewer Replacement — Civil Engineering Design Services",
        naics_code="541330", agency_name="Department of Veterans Affairs", location_state="LA",
        set_aside=SetAsideType.SDVOSB, intelligence_category=IntelligenceCategory.PRE_SOLICITATION,
    )
    calculate_sam_relevance_score(item)
    why = item.sam_relevance_rationale["why_relevant"]
    assert "Veterans Affairs" in why
    assert "sdvosb" in why.lower() or "sdvosbs" in why.lower()


def test_why_not_fit_flags_related_naics_as_possibly_needing_a_teaming_partner():
    item = _item(title="Architectural Design Services", naics_code="541310")
    calculate_sam_relevance_score(item)
    why_not = item.sam_relevance_rationale["why_not_fit"]
    assert why_not is not None
    assert "teaming partner" in why_not.lower()


def test_why_not_fit_surfaces_matched_negative_phrases():
    item = _item(title="Civil Engineering Design Services and Janitorial Support", naics_code="541330")
    calculate_sam_relevance_score(item)
    why_not = item.sam_relevance_rationale["why_not_fit"]
    assert why_not is not None
    assert "janitorial" in why_not.lower()


def test_confidently_relevant_item_has_no_why_not_fit_caveat():
    item = _item(
        title="IDIQ for Civil Engineering Design Services — Flood Control and Levee Rehabilitation",
        naics_code="541330", agency_name="U.S. Army Corps of Engineers", location_state="LA",
        intelligence_category=IntelligenceCategory.PRE_SOLICITATION,
    )
    calculate_sam_relevance_score(item)
    assert item.sam_relevance_rationale["why_not_fit"] is None


def test_rationale_never_includes_raw_component_scores_as_the_only_explanation():
    # Every scored item gets a components breakdown (for the UI/debugging) AND a
    # generated narrative — the narrative must never be empty.
    item = _item(title="Civil Engineering Design Services", naics_code="541330")
    calculate_sam_relevance_score(item)
    rationale = item.sam_relevance_rationale
    assert set(rationale["components"]) == {
        "content", "naics", "agency", "geography", "notice_type", "set_aside", "negative_penalty",
    }
    assert rationale["why_relevant"]


# --- Illustrative fixture sets: 10 highly-relevant, 10 correctly-rejected -----------
#
# Hand-built from the user's own keyword/agency/negative-category lists, not real
# production data (this sandbox cannot reach the live 355-record production dataset —
# see the task's closing summary). Run with -v for a quotable, per-example report.

HIGHLY_RELEVANT_FIXTURES = [
    pytest.param(
        dict(
            title="Architect-Engineer Services for Water and Sanitary Sewer Replacement",
            naics_code="541330", agency_name="Department of Veterans Affairs", location_state="LA",
            set_aside=SetAsideType.SDVOSB, intelligence_category=IntelligenceCategory.PRE_SOLICITATION,
        ),
        id="VA Sources Sought - water/sewer A-E, SDVOSB",
    ),
    pytest.param(
        dict(
            title="IDIQ for Civil Engineering Design Services, Flood Control and Levee Rehabilitation",
            naics_code="541330", agency_name="U.S. Army Corps of Engineers", location_state="LA",
            intelligence_category=IntelligenceCategory.LIVE_OPPORTUNITY,
        ),
        id="USACE Solicitation - flood control/levee IDIQ",
    ),
    pytest.param(
        dict(
            title="A/E IDIQ for Airfield Infrastructure and Site Civil Design",
            naics_code="541330", agency_name="Department of the Air Force", location_state="MS",
            intelligence_category=IntelligenceCategory.PRE_SOLICITATION,
        ),
        id="Air Force Presolicitation - airfield/site civil A-E IDIQ",
    ),
    pytest.param(
        dict(
            title="Disaster Recovery Infrastructure Engineering Support — Watershed and Drainage Design",
            naics_code="541330", agency_name="Federal Emergency Management Agency", location_state="LA",
            intelligence_category=IntelligenceCategory.PRE_SOLICITATION,
        ),
        id="FEMA Sources Sought - disaster recovery watershed/drainage",
    ),
    pytest.param(
        dict(
            title="Construction Administration and Engineering Services for Pump Station Rehabilitation",
            naics_code="541330", agency_name="U.S. Army Corps of Engineers", location_state="TX",
            set_aside=SetAsideType.SDVOSB, intelligence_category=IntelligenceCategory.LIVE_OPPORTUNITY,
        ),
        id="USACE Solicitation - CA + pump station, SDVOSB",
    ),
    pytest.param(
        dict(
            title="Engineering Design Services for VA Medical Center Utility Infrastructure — Water Main and Sewer Main Replacement",
            naics_code="541330", agency_name="Department of Veterans Affairs", location_state="LA",
            intelligence_category=IntelligenceCategory.LIVE_OPPORTUNITY,
        ),
        id="VA Solicitation - medical center utility infrastructure",
    ),
    pytest.param(
        dict(
            title="Watershed Engineering and Erosion Control Design Services",
            naics_code="541330", agency_name="Natural Resources Conservation Service", location_state="AR",
            intelligence_category=IntelligenceCategory.PRE_SOLICITATION,
        ),
        id="NRCS Sources Sought - watershed/erosion control",
    ),
    pytest.param(
        dict(
            title="Coastal Restoration and Resiliency Engineering Design",
            naics_code="541330", agency_name="U.S. Army Corps of Engineers", location_state="LA",
            set_aside=SetAsideType.SMALL_BUSINESS, intelligence_category=IntelligenceCategory.LIVE_OPPORTUNITY,
        ),
        id="USACE Solicitation - coastal restoration/resiliency",
    ),
    pytest.param(
        dict(
            title="Transportation Engineering and Roadway Improvements — Military Installation Infrastructure",
            naics_code="541330", agency_name="Department of the Air Force", location_state="GA",
            intelligence_category=IntelligenceCategory.LIVE_OPPORTUNITY,
        ),
        id="Air Force Solicitation - transportation/roadway installation infra",
    ),
    pytest.param(
        dict(
            title="Civil Engineering IDIQ — Stormwater and Site Development Design Services",
            naics_code="541330", agency_name="Department of Veterans Affairs", location_state="LA",
            set_aside=SetAsideType.SDVOSB, intelligence_category=IntelligenceCategory.PRE_SOLICITATION,
        ),
        id="VA Sources Sought - civil IDIQ, stormwater/site development",
    ),
]

CORRECTLY_REJECTED_FIXTURES = [
    pytest.param(dict(title="Information Technology Support Services", naics_code="541512"), id="IT support services"),
    pytest.param(dict(title="Cybersecurity Assessment and Monitoring Services", naics_code="541512", agency_name="Department of Defense"), id="cybersecurity assessment"),
    pytest.param(dict(title="Medical Supplies and Pharmaceutical Distribution", naics_code="424210", agency_name="Department of Veterans Affairs"), id="medical supplies (VA-labeled)"),
    pytest.param(dict(title="Janitorial and Custodial Services", naics_code="561720", agency_name="Department of the Air Force"), id="janitorial (Air Force-labeled)"),
    pytest.param(dict(title="Office Supplies Blanket Purchase Agreement", naics_code="339940"), id="office supplies BPA"),
    pytest.param(dict(title="Uniforms and Laundry Services", naics_code="315210", agency_name="Department of Defense"), id="uniforms/laundry (DoD-labeled)"),
    pytest.param(dict(title="Temporary Staffing Services", naics_code="561320"), id="temporary staffing"),
    pytest.param(dict(title="Motor Vehicle Fleet Maintenance", naics_code="811111"), id="motor vehicle fleet maintenance"),
    pytest.param(dict(title="Legal Services Support", naics_code="541110", agency_name="Department of Defense"), id="legal services (DoD-labeled)"),
    pytest.param(dict(title="Software Development and Cloud Services", naics_code="541511"), id="software development/cloud"),
]


@pytest.mark.parametrize("fields", [p.values[0] for p in HIGHLY_RELEVANT_FIXTURES], ids=[p.id for p in HIGHLY_RELEVANT_FIXTURES])
def test_highly_relevant_fixture_scores_at_least_relevant(fields):
    item = _item(**fields)
    calculate_sam_relevance_score(item)
    assert item.sam_relevance_score >= RELEVANT_THRESHOLD, (
        f"expected >= {RELEVANT_THRESHOLD}, got {item.sam_relevance_score} "
        f"(rationale: {item.sam_relevance_rationale})"
    )


@pytest.mark.parametrize("fields", [p.values[0] for p in CORRECTLY_REJECTED_FIXTURES], ids=[p.id for p in CORRECTLY_REJECTED_FIXTURES])
def test_correctly_rejected_fixture_scores_below_possible_match(fields):
    item = _item(**fields)
    calculate_sam_relevance_score(item)
    assert item.sam_relevance_score < POSSIBLE_MATCH_THRESHOLD, (
        f"expected < {POSSIBLE_MATCH_THRESHOLD}, got {item.sam_relevance_score} "
        f"(rationale: {item.sam_relevance_rationale})"
    )
