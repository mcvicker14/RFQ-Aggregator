# Phase 2 Architecture — Multi-Source Intelligence Platform

*Find Earlier. Pursue Smarter. Win More.*

This document is the pre-implementation plan requested before Phase 2 work began. It
covers: the architectural decision at the center of this phase, the database schema
changes, the generalized connector framework, the deduplication design, which Wave 1
sources can be built reliably today vs. deferred, production risks, and the
implementation order actually followed. Written for the same audience as
`docs/ARCHITECTURE.md` — developers (human or AI) extending this codebase. For what
Phase 2 means in plain terms, see the chat summary given alongside this doc.

## 0. What Phase 2 is, in one sentence

Turn the app from "a SAM.gov opportunity tracker" into a system that ingests many
public sources into one **intelligence** feed, tags every item with how mature/certain
it is, and only promotes the items that are real procurements into the existing
pipeline — without changing how the existing pipeline, scoring, dashboard, or documents
work today.

## 1. Current state (confirmed by re-inspecting the repo before writing this doc)

- 8 commits, clean tree, live on Render, backend `principal-oi-api` + frontend
  `principal-oi-web` + managed Postgres, per `render.yaml`.
- One migration exists: `a0624dcdd5d6_initial_schema`. Schema is ~17 model modules,
  827 lines.
- `Opportunity` (`app/models/opportunity.py`) is the CRM/pipeline record. It carries
  `ProvenanceMixin` (source, source_url, retrieved_at, confidence), `locked_fields`
  (field-ownership so ingestion never clobbers a human edit), `is_sample_data`, and a
  nullable `pipeline_stage_id`/`maturity_stage`. `OpportunitySource` is an append-only
  provenance log **scoped under an existing opportunity** (`opportunity_id` is
  `NOT NULL`) — it cannot represent something that isn't an opportunity yet.
- The connector framework (`app/connectors/base.py`) is one abstract class,
  `OpportunityConnector`, with `fetch(since) -> list[RawOpportunity]`, registered in a
  flat dict in `registry.py`. Today it has exactly one implementation, `SamGovConnector`
  (`app/connectors/sam_gov.py`), which assumes every fetched item becomes an
  `Opportunity`.
- `app/services/ingestion.py` owns upserting a `RawOpportunity` into `Opportunity` +
  `OpportunitySource`, respecting `locked_fields`, and firing the scoring engine +
  a "new opportunity" alert.
- `app/services/scoring.py` is the Principal Pursuit Score: eight deterministic
  category scorers (strategic/customer/contract/geographic fit, competitive advantage,
  financial attractiveness, competition, timing), combined by configurable weights from
  `ScoringWeightProfile`, producing a 0–100 score with plain-English bullets per
  category. No LLM call — this is intentionally template-based so it's instant and has
  no external dependency.
- `MaturityStage` (`app/models/enums.py`) already spans `RUMORED_CONCEPTUAL` through
  `AWARDED` (11 stages) — this already **is** the "extended maturity stage list" Phase
  2 asks for; it does not need new values, just a place to live outside a committed
  `Opportunity` row (see §3).
- `pg_enum()` (`app/db/base.py`) stores every enum as `VARCHAR` + `CHECK` constraint,
  not a native Postgres `ENUM` type, specifically so adding a new value later is a plain
  migration, not an `ALTER TYPE` dance. Every new enum in this phase uses it too.
- The frontend's Discover page (`frontend/src/app/discover/page.tsx`) is SAM.gov-only
  today: a status card + a "Sync Now" button hitting `/api/ingestion/sam-gov/*|`, with a
  static "Other Sources (Planned)" card as a placeholder.
- **Confirmed hard constraint**: this sandbox's network egress is blocked for every
  external data source relevant here (`api.sam.gov`, `api.usaspending.gov`,
  `api.grants.gov`, `dotd.la.gov`, `va.gov` all returned `403` via the agent proxy on
  direct test). `WebSearch` still works (routed differently), so source URLs/API shapes
  can be researched, but no connector can be live-tested from here. This shapes §8 below.

## 2. The core decision: a new landing table, not a bigger `Opportunity`

**`intelligence_items` is a new table, separate from `Opportunity`, linked by a
nullable foreign key.** This was the main design question and it has one clear answer,
for a structural reason, not a stylistic one:

`OpportunitySource` — the obvious "just reuse this" candidate — requires a `NOT NULL
opportunity_id`. An early signal (a council agenda line item, a state revolving-fund
priority list entry) or award intelligence (a completed USAspending award) very often
**never becomes an Opportunity** — award intelligence never should, and most early
signals won't pan out. A table that can only exist underneath an already-committed
Opportunity cannot represent something that might not become one. Widening
`Opportunity` itself to tolerate this (nullable pipeline fields, a "maybe" status,
etc.) would mean every existing query, the scoring engine, the dashboard, and the
pipeline board would all need new "is this even real yet" guards — the exact kind of
cross-cutting risk the user's instructions said to avoid.

So: `intelligence_items` is a universal landing zone for **everything** ingested from
any source, tagged with a required `intelligence_category`
(`LIVE_OPPORTUNITY | PRE_SOLICITATION | EARLY_SIGNAL | AWARD_INTELLIGENCE`). Only
`LIVE_OPPORTUNITY` and `PRE_SOLICITATION` items are ever auto-promoted into a real
`Opportunity` row (via the existing `ingestion.py` upsert logic, reused rather than
duplicated — see §5). `EARLY_SIGNAL` and `AWARD_INTELLIGENCE` items stay
intelligence-only. This means:

- **Zero schema changes to `Opportunity`, `OpportunitySource`, or any of the other 15
  existing tables.** The migration is five new tables and their indexes — nothing
  altered, nothing dropped, nothing backfilled.
- Every existing route, service, and page (dashboard, pipeline, scoring, Go/No-Go,
  documents, forecasting) keeps working exactly as today, untouched, because nothing
  about how `Opportunity` rows are created or read changes.
- Promotion writes both a normal `Opportunity` row *and* a normal `OpportunitySource`
  row, so the opportunity detail page's existing provenance/history UI needs no changes
  to show intelligence-sourced opportunities correctly.

## 3. New tables

All five use the existing `UUIDPKMixin`/`TimestampMixin` conventions from
`app/db/base.py`; new enums use `pg_enum()` for the same reason existing ones do.

### `intelligence_sources` (model `IntelligenceSource`) — the "Source Registry"

One row per external source, whether or not it has a working connector yet.

| Column | Type | Notes |
|---|---|---|
| `name` | `String(200)`, unique | "SAM.gov", "Louisiana DOTD Projected Letting" |
| `organization` | `String(300)`, nullable | Owning agency/entity |
| `jurisdiction_level` | enum `FEDERAL\|STATE\|LOCAL\|REGIONAL\|PRIVATE` | |
| `geographic_coverage` | `String(300)`, nullable | Free text, e.g. "St. Tammany Parish" |
| `source_url` | `String(1000)`, nullable | Human-facing page |
| `api_url` | `String(1000)`, nullable | Actual endpoint, if different |
| `connector_type` | enum `API\|RSS\|STRUCTURED_FILE\|CSV\|HTML_SCRAPE\|PDF_PARSE\|MANUAL` | |
| `connector_key` | `String(60)`, nullable, unique | Links to the Python connector registry; `NULL` = no code yet |
| `requires_auth` | `Boolean` | |
| `auth_notes` | `Text`, nullable | e.g. how to request a key |
| `is_enabled` | `Boolean`, default `False`, indexed | Nothing syncs until explicitly enabled |
| `polling_frequency_hours` | `Integer`, nullable | Data model is ready for scheduling; nothing calls it automatically yet (§7) |
| `last_attempted_sync_at` / `last_successful_sync_at` | `DateTime`, nullable | |
| `last_result_count` | `Integer`, nullable | |
| `last_error` | `Text`, nullable | |
| `health_status` | enum `NEVER_RUN\|HEALTHY\|DEGRADED\|FAILING\|NEEDS_CONFIGURATION\|MANUAL_ONLY` | |
| `terms_notes` | `Text`, nullable | robots.txt / ToS / rate-limit / licensing research |
| `parser_version` | `String(20)`, nullable | Bump when field-mapping logic changes materially |
| `default_intelligence_category` | enum, nullable | Most sources always produce one category |
| `naics_filter` | `JSONB`, nullable | List of codes this source is queried for |
| `notes` | `Text`, nullable | Research notes — the sanctioned home for "here's what this needs before it can be built" |

### `intelligence_items` (model `IntelligenceItem`)

The universal landing row. Reuses `ProvenanceMixin` exactly as `Opportunity` does
(`source` display label + `source_url` + `retrieved_at` + `confidence`) — so, like
`Opportunity`, it carries *both* a FK to the registry (`intelligence_source_id`) *and*
a denormalized source label, which is already this codebase's established pattern
(`Opportunity.agency_id` + `Opportunity.opportunity_source_label` do the same thing).

| Column | Type | Notes |
|---|---|---|
| `intelligence_source_id` | FK → `intelligence_sources.id`, not null | |
| `external_id` | `String(200)`, not null | Source's own ID; unique together with `intelligence_source_id` |
| `title` | `String(500)`, not null | |
| `description` | `Text`, nullable | |
| `agency_name` | `String(300)`, nullable | Free text — not every source resolves cleanly to an `Agency` row |
| `agency_id` | FK → `agencies.id`, nullable | Set when resolved |
| `jurisdiction_level` | enum, nullable | |
| `location_city` / `location_state` | `String`, nullable | Mirrors `Opportunity` |
| `latitude` / `longitude` | `Numeric(9,6)`, nullable | Per spec §2 |
| `naics_code` / `psc_code` | `String(10)`, nullable | |
| `set_aside` | enum `SetAsideType`, nullable | Reused from the existing enum |
| `estimated_value_low` / `estimated_value_high` | `Numeric(14,2)`, nullable | |
| `funding_amount` | `Numeric(14,2)`, nullable | For grants/CDBG-style early signals |
| `posted_at` | `DateTime`, nullable | Source's own publish date |
| `proposal_due_at` | `DateTime`, nullable, indexed | |
| `estimated_solicitation_date` / `estimated_award_date` | `Date`, nullable | |
| `estimated_time_to_procurement` | enum `MONTHS_0_3\|MONTHS_3_6\|MONTHS_6_12\|MONTHS_12_24\|UNKNOWN` | Always shown in the UI labeled as an estimate |
| `maturity_stage` | enum `MaturityStage`, nullable | Reused as-is (§1) |
| `intelligence_category` | enum, not null, indexed | `LIVE_OPPORTUNITY\|PRE_SOLICITATION\|EARLY_SIGNAL\|AWARD_INTELLIGENCE` |
| `solicitation_number` / `contract_number` / `funding_award_number` / `project_number` | `String(120)`, nullable | Identifier fields dedup matches on |
| `incumbent_company_id` / `incumbent_name` | FK/`String`, nullable | |
| `awardee_company_id` / `awardee_name` / `is_prime_award` | FK/`String`/`Boolean`, nullable | Award-intelligence fields |
| `relevant_disciplines` | `JSONB`, nullable | List of strings |
| `early_signal_score` / `early_signal_score_rationale` | `Integer`/`JSONB`, nullable | See §6; only meaningful for `EARLY_SIGNAL` items |
| `raw_metadata` | `JSONB`, nullable | Full raw source payload, for audit |
| `first_detected_at` | `DateTime`, not null, default now | When **we** first saw it |
| `last_seen_at` | `DateTime`, not null, default now | Bumped every sync that still finds it — a silent disappearance is itself a signal |
| `opportunity_id` | FK → `opportunities.id`, nullable, indexed | Set once promoted (§5) |
| `dedup_status` | enum `UNCLUSTERED\|LIKELY_DUPLICATE\|POSSIBLE_DUPLICATE\|CONFIRMED_SAME_PROJECT`, default `UNCLUSTERED` | See §6 |
| `project_cluster_id` | FK → `project_clusters.id`, nullable, indexed | |
| `dedup_match_reason` | `Text`, nullable | Plain-English "why the algorithm thinks these match" |
| `is_sample_data` | `Boolean`, not null, default `False`, indexed | Consistency with `Opportunity`; nothing seeds sample intelligence this phase |

Unique constraint: `(intelligence_source_id, external_id)` — this is the within-source
dedup; §6 is the *cross*-source case.

### `project_clusters` (model `ProjectCluster`)

Deliberately thin — the real state lives on each `intelligence_items` row
(`dedup_status`, `dedup_match_reason`), because merging must never delete or combine
rows (spec requirement: preserve every underlying source). This table is just the
grouping anchor: `representative_title`, `notes`, `confirmed_by_user_id`,
`confirmed_at` (set only when a human confirms the cluster — see §6).

### `intelligence_sync_runs` (model `IntelligenceSyncRun`)

`intelligence_source_id` (FK, indexed), `started_at`, `finished_at` (nullable —
`NULL` means still running), `status` (`RUNNING|SUCCESS|PARTIAL_FAILURE|FAILURE`),
`items_fetched/created/updated/unchanged/errored` (integers), `error_detail`,
`triggered_by` (`MANUAL|SCHEDULED`), `triggered_by_user_id` (nullable FK).

### `app_settings` (model `AppSetting`)

Minimal key-value: `key` (`String(80)`, **primary key**), `value` (`JSONB`),
`updated_at`, `updated_by_user_id`. Seeded with one row,
`hide_sample_data_by_default = false` — i.e. **zero behavior change** until an
administrator explicitly flips it (§9).

## 4. Migration plan

One new Alembic revision, `down_revision` pointing at the existing
`a0624dcdd5d6_initial_schema` (the only migration that exists today). Contents:

- `CREATE TABLE` for all five tables above, with every FK, index, and the
  `(intelligence_source_id, external_id)` unique constraint specified in §3.
- No `ALTER TABLE` on any existing table — confirmed in §2, this is the entire point
  of the design.
- A `downgrade()` that drops the five new tables (in FK-safe order) — mirroring the
  existing migration's structure, not a partial/placeholder one.
- Run and verified against the same local Postgres instance used for the original
  schema before anything is committed, exactly as the first migration was.
- Render's Docker `CMD` already runs `alembic upgrade head` on every boot
  (`backend/Dockerfile`) and is idempotent — no deployment-process change needed; the
  new tables appear automatically on the next deploy.

## 5. Connector framework, generalized

`OpportunityConnector` is retired in place (not kept alongside a new interface —
keeping two parallel connector abstractions for the same job would be exactly the kind
of premature-compatibility-shim the project avoids elsewhere). `app/connectors/base.py`
becomes:

```python
@dataclass
class RawIntelligenceItem:
    external_id: str
    intelligence_category: IntelligenceCategory   # connector's best default; sync layer can remap per-item
    source_url: str | None
    retrieved_at: datetime
    fields: dict          # normalized keys matching IntelligenceItem's columns
    raw: dict = field(default_factory=dict)
    confidence: str = "verified_fact"

class IntelligenceConnector(ABC):
    key: str        # matches intelligence_sources.connector_key
    name: str
    default_category: IntelligenceCategory

    @abstractmethod
    def is_configured(self) -> bool: ...

    @abstractmethod
    def fetch(self, since: date, **filters) -> list[RawIntelligenceItem]: ...
```

`connectors/registry.py` becomes a dict keyed by `connector_key`, and a row in
`intelligence_sources` with `connector_key = NULL` simply has no code yet — the sync
orchestrator (§7) skips it, and the Source Manager UI never offers a "Sync Now" button
for it. `connectors/http_retry.py` is a new small shared helper (exponential backoff on
timeouts/5xx/connection errors, max 3 attempts) used by every HTTP-based connector, so
retry logic isn't duplicated per-connector.

**`SamGovConnector` migrates onto this interface** (task in §10): its `fetch()` keeps
its existing NAICS-filtered query mechanism unchanged (that part isn't broken, so it
isn't touched), but `_to_raw_opportunity` becomes `_to_raw_intelligence_item`, adding a
notice-type → category mapping (`Solicitation`/`Combined Synopsis/Solicitation` →
`LIVE_OPPORTUNITY`; `Presolicitation`/`Sources Sought`/`Special Notice` →
`PRE_SOLICITATION`; `Award Notice` → `AWARD_INTELLIGENCE`; unknown → `LIVE_OPPORTUNITY`,
preserving today's behavior as the safe default). This is the one behavior change to
existing SAM.gov output: award notices, if SAM.gov ever returns any, stop being
mis-promoted into the pipeline as if they were live solicitations. Solicitations —
the overwhelming majority of what SAM.gov returns, and the entire current dataset —
promote exactly as before.

**Promotion** (`intelligence_items` → `Opportunity`) reuses `ingestion.py`'s existing
`_upsert_opportunity` logic rather than duplicating it — that function already does
everything promotion needs (locked-fields respect, agency resolution, scoring,
new-opportunity alert). It's adjusted to accept an `IntelligenceItem` instead of a
`RawOpportunity`. The rule is deterministic, not AI judgment: `LIVE_OPPORTUNITY` and
`PRE_SOLICITATION` auto-promote; `EARLY_SIGNAL` and `AWARD_INTELLIGENCE` never do.
Manually promoting a promising early signal by hand is a natural later addition, out of
scope for this pass.

## 6. Entity resolution / deduplication

Runs once per newly-created-or-updated `intelligence_item` at the end of a sync (not a
full-table rescan every time). `app/services/dedup.py`,
`find_and_cluster_candidates(db, item)`:

1. **Exact identifier match** (`solicitation_number`, `contract_number`,
   `funding_award_number`, or `project_number`, case-insensitive, both non-null) against
   other items → strongest signal.
2. **Agency + location match** (`agency_id` or fuzzy `agency_name`, plus
   `location_state`) as a corroborating signal.
3. **Title similarity** via `difflib.SequenceMatcher(None, a, b).ratio()` — stdlib,
   no new dependency, same tier of tool as the rest of this codebase's deterministic
   logic.
4. **Date proximity** (`proposal_due_at`/`posted_at` within ~21 days) as a third
   corroborating signal, never sole evidence.

Classification is deliberately conservative: **the algorithm only ever writes
`LIKELY_DUPLICATE` or `POSSIBLE_DUPLICATE`, never `CONFIRMED_SAME_PROJECT`.** That
state is a human action (a click in the timeline/dedup UI), matching the spec's
explicit "do not auto-merge" requirement in its strongest form — even a near-certain
identifier match stops at "likely," not "confirmed." Matched items get the same
`project_cluster_id` (creating a new `project_clusters` row if neither has one yet);
each item's own `dedup_match_reason` records the plain-English reason
(e.g. "Same solicitation number; same agency; dates 4 days apart"). No row is ever
deleted or merged into another — clustering only ever sets `project_cluster_id` and
`dedup_status`, so every underlying source item is always still there and inspectable.

## 7. Sync orchestration & logging

`app/services/intelligence_sync.py`, `run_sync(db, source, triggered_by, user=None)`:

1. **Concurrency guard**: refuse to start if an `intelligence_sync_runs` row for this
   source is already `RUNNING` and started within the last 15 minutes (generous — some
   sources page through a year of data); returns a clear "sync already in progress"
   error instead. This is what makes "Sync All Enabled Sources" safe against overlap.
2. Writes an `intelligence_sync_runs` row with `status=RUNNING` immediately and commits
   — so a crash mid-sync still leaves a visible, truthful "was running" record rather
   than silence.
3. Calls `connector.fetch(since)` inside try/except. **A total failure here is caught,
   logged to `error_detail`, marks the source `health_status=FAILING`, commits, and
   returns — it does not raise further.** This is what lets "sync all" continue to the
   next source when one connector is down, per the spec's explicit "a failing connector
   must not crash the overall system."
4. Per-item: upsert into `intelligence_items` (unique on `(source, external_id)` —
   update + bump `last_seen_at` if it exists, else create with
   `first_detected_at = last_seen_at = now`), run promotion (§5) if the category
   qualifies, run the dedup pass (§6). Each item is wrapped in its own try/except
   (mirroring the existing SAM.gov per-notice pattern) and counted as `items_errored`
   rather than aborting the run.
5. Finishes with `status = SUCCESS` (zero errors), `PARTIAL_FAILURE` (some items
   errored), or `FAILURE` (fetch itself failed); updates the source's
   `last_successful_sync_at` / `last_result_count` / `health_status` accordingly.

**Not built this pass, on purpose**: an actual background scheduler (cron/Celery) that
calls this automatically on `polling_frequency_hours`. The column exists so the data
model is ready, but nothing calls it yet — sync is triggered only by an admin action
(Source Manager UI's "Sync Now" / "Sync All Enabled"), exactly like today's
SAM.gov-only Discover page already works. Real scheduling needs a worker process, which
is a Render service-topology change the user asked not to make without strong
justification — and it isn't needed to prove any of these connectors actually work.

## 8. Wave 1 source feasibility triage

**Reliable today — implemented this pass, via stable, documented, keyless public JSON
APIs:**

| Source | Category | Notes |
|---|---|---|
| SAM.gov | `LIVE_OPPORTUNITY`/`PRE_SOLICITATION`/`AWARD_INTELLIGENCE` | Refactored onto the new pipeline (§5); already has a working `SAM_GOV_API_KEY` in production |
| USAspending.gov | `AWARD_INTELLIGENCE` only, never promoted | `POST api.usaspending.gov/api/v2/search/spending_by_award/`, no key. This endpoint's *returned fields* omit NAICS/description even though `naics_codes` is an accepted *filter* parameter — filtering and returned fields are independent, so filtering still works; precision instead leans on priority-agency + Gulf Coast/Louisiana place-of-performance filters |
| Grants.gov | `EARLY_SIGNAL` | `POST api.grants.gov/v1/api/search2`, no key. Filtered by keyword (water, wastewater, stormwater, drainage, infrastructure, transportation, resilience, disaster recovery) — a grant landing at a Louisiana parish is exactly the "chase it before everyone else knows to chase it" signal the RFQ that follows is downstream of |

All three add **zero new secrets** to manage — none require an API key.

**Needs scraping/document parsing/nonstandard access — registered in
`intelligence_sources` this pass with accurate `NEEDS_CONFIGURATION`/notes, NOT
implemented:** LA DOTD Projected/Posted Letting (state portal, no documented JSON API),
VA Forecast, USACE district forecasts (New Orleans/Vicksburg/Mobile/Memphis/
Galveston/Nashville/Jacksonville), DHS/FEMA APFS — these federal forecast systems
publish as downloadable Excel/PDF documents on individual agency pages, not APIs; LaPAC,
CPRA, CWSRF/DWSRF (published as periodic PDF "intended use plans"). The ~15
Northshore/Greater New Orleans local sources (St. Tammany, Slidell, Mandeville,
Covington, New Orleans, SWBNO, Port NOLA, MSY, the four surrounding parishes, Port of
South Louisiana) are registered too, but per the spec's own instruction, building them
means *first* identifying whether each uses a common procurement platform (Beacon,
Central Bidding, OpenGov, Bonfire, IonWave, BidNet, PlanetBids, Public Purchase) so one
connector serves many — that research cannot happen from this sandbox (the target
domains are blocked outbound) or reliably enough via search alone to commit to a page
structure I cannot verify. Building against a guess is exactly what the spec says not
to do, so these stay `NEEDS_CONFIGURATION`/`MANUAL_ONLY` with research notes, not fake
connectors.

**Deferred entirely, not even registered** — the ~20-city "Next Louisiana Expansion"
list and the local-document (council agenda/CIP/budget) AI monitor. The spec's own
language was "architect for but not build" — the schema already supports adding either
as ordinary rows/connectors later; hand-entering ~20 speculative rows with no real
URLs this pass would violate the same "don't implement until verified" principle and
would clutter the Source Manager UI with unresearched entries.

## 9. Sample vs. live data

`intelligence_items.is_sample_data` mirrors `Opportunity.is_sample_data` for
consistency (no sample intelligence is seeded this phase — only real Wave 1 connectors
write to this table). `app_settings.hide_sample_data_by_default` starts `false`
(§3) — the dashboard aggregation in `app/services/dashboard.py` currently includes
`is_sample_data` opportunities in every KPI/chart unconditionally, which is a real gap
against the spec's "do not mix sample records into production metrics unless
explicitly included." Rather than silently change live dashboard numbers, this phase
wires dashboard aggregation to **check the setting**: while it's `false` (the shipped
default), behavior is byte-for-byte identical to today; once an administrator flips it
on (Settings page), the dashboard and list views start excluding sample data — giving
the user real control at the moment they decide there's enough live data to do so,
rather than a decision made for them.

## 10. Early Signal Score

Separate, deterministic engine (`app/services/early_signal_scoring.py`), same pattern
as `scoring.py` (category scores + plain-English bullets + narrative), but answering a
different question — not "how good a fit for Principal" (that's the Pursuit Score,
which only exists post-promotion) but "**how likely is this to turn into a real
procurement at all**":

- **Funding certainty** — is there an identified/appropriated amount, or is this a
  rumor/conceptual CIP line item?
- **Specificity** — a named project/location/scope vs. a vague program-level mention.
- **Source reliability** — a government budget/CIP document outranks a news mention.
- **Signal strength from timeline** — uses `estimated_time_to_procurement`, always
  displayed as a labeled estimate, never certainty.

0–100 score + low/medium/high band, same shape as the Pursuit Score's output, so the
frontend can reuse the same score-badge component for both.

## 10a. SAM Relevance Score

A third, separate engine (`app/services/sam_relevance_scoring.py`), added after a
production incident: fixing SAM.gov's retrieval (broad NAICS-family + all-notice-type
querying — see §5/§8's connector notes) made a live sync return 355 records, and most
of them weren't Principal-relevant — SAM.gov's own NAICS/notice-type tagging is
self-reported by the posting agency and often imprecise. This score answers a third,
different question from the other two: not "how likely to become a procurement"
(Early Signal Score) or "how good a fit once it's a tracked pursuit" (Pursuit Score),
but "**is this SAM.gov notice even worth putting in front of Principal at all**."

- **Populated only for `source == "SAM.gov"`** — every other source's items have
  `sam_relevance_score = NULL` and are never filtered by it (see below).
- **Computed after persistence, not as a retrieval filter.** SAM.gov's connector keeps
  every fetched, non-expired notice for intelligence/auditability (§5/§8) — nothing is
  dropped at fetch time for being off-topic. `intelligence_sync.run_sync()` calls
  `calculate_sam_relevance_score()` right after upsert, *before*
  `promote_intelligence_item()`, so promotion can consult the result.
- **Gates promotion, not just visibility.** A SAM item scored below `RELEVANT_THRESHOLD`
  (65) is never promoted into a real `Opportunity` — see `promote_intelligence_item()`'s
  own docstring. This keeps Pipeline/Dashboard/Go-No-Go from being flooded the same way
  Discover would be; the `IntelligenceItem` itself is never deleted, only left
  unpromoted, and a human can still find it via Discover's "All SAM Records" filter.
- **Components**: phrase-matched content relevance (title/description against
  Principal's positive/negative phrase lists, capped so no single generic word
  carries a record), NAICS (541330 strongest, a related-discipline set modest, no
  sector-level "54" credit at all), agency tier (VA/USACE highest, Air Force/DoD/
  FEMA/NRCS strong — deliberately small point values, since none of these may decide
  relevance alone), Gulf Coast/Southeast/Mississippi Valley geography, a Sources
  Sought/Presolicitation strategic-positioning bonus, and a set-aside bonus that's
  gated behind already-established content/NAICS relevance (an SDVOSB set-aside on an
  obviously unrelated procurement must not be rescued into relevance).
- **Tiers**: 80–100 Highly Relevant, 65–79 Relevant (together, "the default Discover
  view"), 50–64 Possible Match (behind an explicit filter), below 50 Low Relevance
  (kept for provenance, never shown by default). `HIGHLY_RELEVANT_THRESHOLD`/
  `RELEVANT_THRESHOLD`/`POSSIBLE_MATCH_THRESHOLD` in `sam_relevance_scoring.py` are the
  single source of truth every caller (the promotion gate, the Discover API's default
  filter, the dashboard's intelligence counts) imports rather than re-deriving.
- **Explanation, not just a number**: `sam_relevance_rationale` (JSONB) carries a
  component breakdown plus two generated sentences — `why_relevant` (which matched
  keywords/agency/NAICS/set-aside drove the score) and `why_not_fit` (a matched
  negative phrase, a related-not-primary NAICS possibly needing a teaming partner, or
  a general "limited signal, worth a manual check" caveat — `None` when there's no
  meaningful caveat). Template-based, like the other two engines — no LLM call.

## 10b. Grant Engineering Relevance Score

A fourth, separate engine (`app/services/grants_relevance_scoring.py`), added after the
same class of production incident as §10a: Grants.gov's retrieval-time `_is_relevant()`
keyword filter (a pre-persistence hard filter) let a live sync return 116 records, most
not Principal-relevant, and — being pre-persistence — silently dropped whatever it
rejected with no provenance at all. Same fix shape as SAM: broad retrieval, drop the
pre-persistence filter, score after persistence.

Grants.gov is architecturally unlike Principal's other sources: it's not a list of
procurements or grants for Principal to pursue directly — it's an **early-signal
source for public infrastructure funding** that may, once a recipient plans the funded
project, generate a future engineering RFQ (water/wastewater, drainage/flood,
transportation, utility, civil design). This score answers that specific question:
"**could this funding realistically lead to a future procurement for engineering
services**" — not "should Principal apply for this grant," which none of the four
scores answer.

- **Populated only for `source == "Grants.gov"`** — every other source's items have
  `grants_relevance_score = NULL` and are never filtered by it, mirroring
  `sam_relevance_score`'s isolation.
- **Computed after persistence, not as a retrieval filter.** The connector's
  `_to_raw_intelligence_item()` always returns an item now (it used to return `None`
  for anything the old keyword filter rejected); `intelligence_sync.run_sync()` calls
  `calculate_grants_relevance_score()` in the same per-item loop as
  `calculate_sam_relevance_score()`, right after upsert.
- **No promotion gate needed.** Unlike SAM items, Grants.gov items are always created
  with `default_category = IntelligenceCategory.EARLY_SIGNAL`, and `EARLY_SIGNAL` was
  already outside `PROMOTABLE_CATEGORIES` before this change — a grant was never
  auto-promoted into an `Opportunity` regardless of any score. This score instead gates
  *default visibility* (Discover's filter, the dashboard's intelligence counts and
  high-priority-signals widget) and feeds into the existing Early Signal Score
  calculation for items that clear it, exactly as instructed: "classify as early
  signal, do not automatically promote."
- **Components**: infrastructure/engineering theme phrases in title+description (water/
  wastewater/sewer, drainage/flood/stormwater, transportation/roads/bridges, utilities,
  hazard mitigation/disaster recovery, coastal restoration, capital improvement, etc. —
  capped so no single phrase carries a record), recipient-type phrases (state/parish/
  county government, municipal, public utility, water/sewer/drainage/levee district,
  port/airport/transportation authority, tribal government — valuable because these are
  plausible *future buyers* of engineering services, independent of the funded theme),
  a funding-size bonus gated behind already-established content/recipient scope (a
  large program with an irrelevant technical scope gets no bonus), and an award-signal
  bonus, also gated the same way, that only ever fires when the connector has genuinely
  set `awardee_name` — **never inferred**. Grants.gov's own data model (Forecasted/
  Posted/Closed/Archived opportunity statuses) has no "Awarded" status with recipient
  data, so every current Grants.gov item honestly reports `signal_type: "opportunity"`,
  never a guessed `"award"`. Negative theme phrases (biomedical/medical research,
  behavioral health, social services, education/scholarship, humanities/arts, workforce
  training, academic/scientific research, law enforcement, non-infrastructure public
  health, agricultural research, nonprofit service delivery) apply as a penalty, not a
  veto — a genuinely infrastructure-relevant program that also touches one of these
  (e.g. an NRCS watershed program with an agricultural-research component) can still
  clear the relevance floor. Generic terms the task explicitly called out — bare
  "community," "development," "public," "planning," "resilience" — are deliberately
  absent from every phrase list, so they contribute nothing by themselves; a title built
  entirely from them scores exactly 0.
- **Tiers**: 80–100 High-Value Engineering Signal, 65–79 Relevant Infrastructure Signal
  (together, the default Discover view), 50–64 Possible Engineering Signal (behind an
  explicit filter), below 50 Low Relevance (kept for provenance, never shown by
  default) — the same numeric bands as §10a's SAM tiers, for a consistent mental model,
  even though the two scores measure unrelated things and are never compared directly.
  `HIGH_VALUE_THRESHOLD`/`RELEVANT_THRESHOLD`/`POSSIBLE_SIGNAL_THRESHOLD` in
  `grants_relevance_scoring.py` are the single source of truth every caller imports
  rather than re-derives (aliased on import wherever a file already imports SAM's
  same-named constants, e.g. `dashboard.py`, `intelligence_items.py`).
- **Explanation, not just a number**: `grants_relevance_rationale` (JSONB) carries a
  component breakdown, `signal_type` (`"opportunity"` or `"award"`), and two generated
  sentences — `why_relevant` (matched theme/recipient phrases, and the awardee name
  when a real award signal exists) and `why_not_fit` (a matched negative phrase, a
  "national opportunity, not a confirmed local award" caveat for an unconfirmed
  opportunity-type record that otherwise scores well, or a general "limited signal"
  caveat — `None` when there's no meaningful caveat). Template-based, like the other
  three engines — no LLM call.

## 11. API and frontend surface

**New backend routes**: `intelligence_sources.py` (registry CRUD for admins + sync
triggers — `POST /api/intelligence/sync/{key}`, `POST /api/intelligence/sync-all`,
`GET /api/intelligence/sync-runs`), `intelligence_items.py` (the Discover feed: filters
for category/source/agency/geography/NAICS/discipline/maturity/score/set-aside/
due-date/value/live-vs-sample; sort by newest/highest-score/largest-value/soonest-
deadline). `app/api/routes/ingestion.py` (today's SAM.gov-only endpoints) is retired
and folded into `intelligence_sources.py` in the same change that updates the Discover
page — keeping both the old and new endpoints alive for the same underlying action
would be a compatibility shim with exactly one caller to update.

**Frontend**: new `frontend/src/app/sources/page.tsx` (Source Manager UI — table of
every registry row, health badges, per-row and "sync all" triggers); rewritten
`discover/page.tsx` (category-badged feed + the filter/sort bar above); dashboard
additions (new counts by category, sources checked today / with errors, high-priority
signals, "New Intelligence Since Last Login" via a new `users.intelligence_last_viewed_at`
column, "Projects We Should Get Ahead Of" = high-scoring unpromoted early signals);
opportunity detail page gains a Project Intelligence Timeline section (every
intelligence item sharing this `opportunity_id` or `project_cluster_id`, sorted by
`first_detected_at`); Settings page gains the hide-sample-data admin toggle.

## 12. Security

No new secrets: all three Wave 1 connectors built this pass are keyless. The existing
rules continue unchanged — backend-only env vars for any future source that does need a
key, `.env.example` documents names/descriptions never values, a missing optional key
disables only that one connector (`is_configured()` returning `False`, `health_status`
showing `NEEDS_CONFIGURATION`), never the app.

## 13. Production risks

- **Migration risk**: minimized by construction — five new tables, zero `ALTER` on
  existing ones (§2, §4).
- **Performance**: indexes specified up front (§3) on every column list/filter/sort
  will actually use — `intelligence_category`, `intelligence_source_id`,
  `opportunity_id`, `dedup_status`, `project_cluster_id`, `proposal_due_at`, plus the
  `(intelligence_source_id, external_id)` unique constraint — rather than retrofitting
  after a slow query shows up.
- **Sync reliability**: per-source and per-item error isolation, concurrency guard,
  retry/backoff (§7) — a bad source degrades to `FAILING`, it doesn't take the app down.
- **Rate-limit/cost courtesy**: every connector bounds its own lookback window and page
  size (mirroring SAM.gov's existing ≤1-year windowing) rather than pulling
  unboundedly, even where no key/quota is enforced.
- **Testing under the sandbox's network restriction**: each new connector gets
  fixture-based unit tests (hand-built realistic payloads from documented schemas)
  verifying the normalization logic deterministically. The live HTTP path cannot be
  exercised from here — that was true for the original SAM.gov connector too — so live
  verification happens the same way it did then: the user (or a manual sync) runs it
  against the deployed Render app, and `raw_metadata` on the resulting rows is the
  first thing to check if a source's real shape has drifted from what's documented.
- **Rollback**: purely additive migration means `alembic downgrade` cleanly drops just
  the five new tables.

## 14. Implementation order

1. Database schema + migration (this is additive-only and touches nothing existing —
   lowest-risk starting point).
2. Generalized connector framework (`IntelligenceConnector`, `RawIntelligenceItem`,
   registry).
3. Entity resolution / dedup engine.
4. Sync orchestration + logging service.
5. Source Manager UI (admin page) — built before the registry is populated, so every
   later step is immediately visible/testable through it.
6. Discover page upgrade (intelligence-category UI, filters, sort).
7. Sample/live separation improvements (`app_settings`, the hide-sample toggle, wiring
   the dashboard to respect it).
8. Seed `intelligence_sources` with the full Wave 1 list from §8, accurate status for
   every row (enabled+working for the 3 reliable sources; `NEEDS_CONFIGURATION`/
   `MANUAL_ONLY` with research notes for everything else named in the spec's Wave 1).
9. Refactor `SamGovConnector` onto the new pipeline (category-per-notice-type mapping).
10. `USAspendingConnector`.
11. `GrantsGovConnector`.
12. Early Signal Score engine (comes after the connectors that actually produce
    `EARLY_SIGNAL` items, so it has real data to be meaningful against).
13. Dashboard intelligence extensions ("New Since Last Login," "Get Ahead Of," etc.).
14. Project Intelligence Timeline on the opportunity detail page.
15. End-to-end test pass and production-style frontend build, with commits pushed in
    logical stages throughout — not saved for the end.
