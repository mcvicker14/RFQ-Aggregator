# Principal Pursuit Score — Methodology

Every opportunity gets a score from **0–100**, recalculated whenever a scored field
changes. Implementation: `backend/app/services/scoring.py`.

This is one of four separate scoring engines, each answering a different question —
this doc covers only the Pursuit Score ("how attractive is this actual pursuit," which
only applies once something is a tracked Opportunity). The other three are documented
in `docs/PHASE2_ARCHITECTURE.md`: **Early Signal Score** (§10 — "how likely is this to
become a real procurement at all"), **SAM Relevance Score** (§10a — "is this SAM.gov
notice even worth putting in front of Principal," which gates whether a fetched
SAM.gov notice is promoted into an Opportunity in the first place), and **Grant
Engineering Relevance Score** (§10b — "could this Grants.gov funding realistically
lead to a future engineering procurement," which gates default visibility for a
source that is never itself auto-promoted).

## Weighted categories

| Category | Default weight | Signals considered |
|---|---|---|
| Strategic Fit | 20% | Scope keywords/discipline tags matching Principal's core markets: civil, water/wastewater, stormwater, drainage, utilities, transportation, site-civil, surveying, construction administration, federal facility infrastructure, disaster recovery, environmental/infrastructure overlap |
| Customer Fit | 15% | Agency on Principal's priority list (USACE, VA, FEMA, USDA NRCS, Air Force, DoD, plus municipal/parish/state) scores higher; configurable per-agency multiplier |
| Contract Fit | 15% | A/E (Brooks Act) procurement, IDIQ/MATOC/SATOC, task order, set-aside type (SDVOSB set-aside scores highest given Principal's status), JV/mentor-protégé/subconsultant opportunities all scored |
| Geographic Fit | 10% | Configurable region scoring: Louisiana (highest), Gulf Coast, Southeast US, Mississippi Valley, active USACE districts, then national |
| Competitive Advantage | 15% | SDVOSB status relevance, matching past performance on file, local experience, existing agency relationships, teaming partner strength, staff resume match |
| Financial Attractiveness | 10% | Estimated fee size, contract ceiling, duration, recurring/task-order/follow-on likelihood |
| Competition | 10% | Estimated competitor count, incumbent presence, set-aside narrowing the field, geographic/license/clearance restrictions |
| Timing | 5% | Days until proposal due vs. estimated SF330 prep time, teaming feasibility in the window, current staff capacity |

Weights live in `scoring_weight_profiles` (not hard-coded), editable from
`/settings` by an Administrator. `backend/app/services/scoring.py` exposes each
category as an independent function returning `(sub_score_0_to_100, rationale_bullets)`
so the weighting can change without touching the scoring logic itself.

## Output

```json
{
  "score": 87,
  "band": "high",                      // high (≥75) / medium (50-74) / low (<50)
  "category_scores": { "strategic_fit": 92, "customer_fit": 85, ... },
  "why_it_scores_highly": "Strong fit because the opportunity involves civil utility
     design for a VA medical facility, is restricted to SDVOSBs, falls within
     Principal's core federal strategy, and closely aligns with existing water and
     utility past performance.",
  "primary_concern": "Prime requires in-house architecture capability, so Principal
     may need an architectural teaming partner.",
  "computed_at": "...",
  "weight_profile_id": "..."
}
```

`why_it_scores_highly` and `primary_concern` are generated from the highest- and
lowest-scoring categories using **template-based natural-language rules**, not a live
LLM call — scoring must be instant, deterministic, and free of external dependency so
it works even when no AI provider is configured. (The AI solicitation reader, a
separate feature, does use an LLM — see `docs/DATA_INGESTION.md` and
`backend/app/ai/`.) Each rationale bullet links back to the specific field that drove
it (e.g. "SDVOSB set-aside" → `opportunities.set_aside`), so nothing in the explanation
is unverifiable.

## Opportunity Maturity (spec §3)

A coarser, MVP-scope version of the "Early Signals" lifecycle. `opportunities.maturity_stage`
is one of:

```
rumored_conceptual → funding_identified → planning → procurement_forecast →
sources_sought_rfi → solicitation_expected → solicitation_released →
proposal_submitted → interview_negotiation → award_pending → awarded
```

Set manually today (a dropdown on the opportunity form); SAM.gov-ingested opportunities
default to `solicitation_released` or `sources_sought_rfi` based on the notice type.
Full automatic signal detection (funding/appropriation/CIP tracking) is Phase 2 — see
`docs/ROADMAP.md`.

## Human-in-the-loop guardrail (spec §28)

The score and its explanation are a **decision aid**, never a decision. They feed the
Go/No-Go tool's "AI Recommendation Factors" panel, but the GO/CONDITIONAL GO/NO-GO
outcome is always recorded as a choice a named human made at a specific time
(`gonogo_reviews.decided_by`, `decided_at`) — the API rejects a Go/No-Go review that
doesn't have both.
