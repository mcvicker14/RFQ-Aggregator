# Database Schema

PostgreSQL, accessed through SQLAlchemy 2.0 models (`backend/app/models/`) and
versioned with Alembic (`backend/alembic/versions/`). Every table has `id` (UUID primary
key), `created_at`, `updated_at`. Tables sourced from outside the app additionally carry
`source`, `source_url`, `retrieved_at`, `confidence` (see §Provenance below).

Status: **✅ Implemented** = real table + migration + API + UI in this MVP.
**🧭 Planned** = documented target for a later phase, not yet a table.

## Entity list

| Table | Status | Notes |
|---|---|---|
| `users` | ✅ | Roles per `docs/SECURITY.md` |
| `companies` | ✅ | Unifies *Organizations / Companies / Teaming Partners / Competitors* from the long-term spec — see §Design decisions |
| `company_socioeconomic_flags` | ✅ | Stored as columns on `companies` (sdvosb, wosb, hubzone, edwosb, eight_a, dbe, small_business) rather than a separate table — simpler for a boolean flag set of fixed size |
| `agencies` | ✅ | |
| `agency_offices` | ✅ | FK to `agencies` |
| `contacts` | ✅ | |
| `opportunity_contacts` | ✅ | join table, carries `role` (contracting_officer, program_manager, small_business_specialist, technical_contact, other) |
| `opportunity_companies` | ✅ | join table, carries `relationship` (incumbent, teaming_partner, confirmed_competitor, historical_competitor, likely_competitor, possible_competitor, subconsultant, prime) and `confidence` |
| `opportunities` | ✅ | core entity, see below |
| `opportunity_sources` | ✅ | provenance record per ingestion event |
| `opportunity_documents` | ✅ | uploaded/ingested files |
| `opportunity_scores` | ✅ | current Principal Pursuit Score + factor breakdown (JSON) |
| `scoring_weight_profiles` | ✅ | configurable weights used by the scoring engine |
| `gonogo_reviews` | ✅ | header record: status, decided_by, decided_at |
| `gonogo_criteria_scores` | ✅ | line items (1–5) belonging to a review |
| `tasks` | ✅ | BD task system |
| `activities` | ✅ | opportunity timeline/audit trail (stage changes, notes, uploads, score changes) |
| `pipeline_stages` | ✅ | ordered, admin-editable list; seeded with the 16 default stages |
| `revenue_forecasts` | ✅ | one row per opportunity: value, fee, probability, expected dates |
| `alerts` | ✅ | generated in-app notifications |
| `alert_rules` | ✅ | per-user configuration of which events generate an alert |
| `ai_solicitation_analyses` | ✅ | structured AI extraction result, linked to a document |
| `naics_codes` | ✅ | small reference table seeded with the codes relevant to Principal's markets |
| `disciplines` | ✅ | reference table (civil, water/wastewater, structural, etc.) |
| `opportunity_disciplines` | ✅ | join table |
| `win_loss_reviews` | ✅ | captured when an opportunity reaches Won/Lost/No Bid |
| `contracts` / `contract_awards` / `recompetes` | 🧭 | Incumbent Recompete Tracker (spec §11) — Phase 2 |
| `employees` / `resumes` / `past_performance` | 🧭 | SF330 Intelligence (spec §8) — Phase 2 |
| `early_signals` | 🧭 | Early Signals / Opportunity Maturity (spec §3) — Phase 2; `opportunities.maturity_stage` already carries a coarser version of this for the MVP |
| agency-level spend rollups | 🧭 | Agency Intelligence (spec §12) — Phase 3, needs USASpending/FPDS ingestion first |

## Core table: `opportunities`

Columns map directly to the "Opportunity Profile Page" fields in the long-term spec
(§6): `title`, `agency_id`, `agency_office_id`, `solicitation_number`, `location_city`,
`location_state`, `naics_code`, `psc_code`, `set_aside`, `contract_type`,
`estimated_value_low`, `estimated_value_high`, `estimated_fee`, `contract_duration_months`,
`proposal_due_at`, `questions_due_at`, `site_visit_at`, `industry_day_at`,
`sources_sought_due_at`, `incumbent_company_id`, `description`, `scope_summary`,
`opportunity_source` (free text: SAM.gov, referral, agency forecast, etc.),
`pipeline_stage_id`, `maturity_stage` (enum, see `docs/SCORING_METHODOLOGY.md` §Opportunity
Maturity), `is_sdvosb_setaside`, `is_sample_data`, `status` (active/archived),
`created_by`, plus provenance columns.

## Design decisions

1. **`companies` unifies four spec entities.** The long-term spec lists `Organizations`,
   `Companies`, `Teaming Partners`, and `Competitors` as separate tables. In practice
   they are the same shape (a firm, with NAICS codes, socioeconomic status, locations,
   contacts) that plays *different roles on different opportunities*. Modeling that as
   one `companies` table plus a `company_type` tag and a per-opportunity
   `opportunity_companies.relationship` join avoids duplicating a firm's record every
   time its role changes (a teaming partner on one pursuit can be a competitor on the
   next). This is the normalized version of what the spec describes, not a scope cut —
   nothing in spec §9/§10 requires four physical tables.
2. **UUID primary keys** so records created offline (e.g. a future disconnected
   ingestion job) never collide on insert.
3. **`pipeline_stages` is a table, not an enum**, because spec §18 explicitly requires
   administrators to customize stages.
4. **Soft status, not soft delete.** Opportunities are never hard-deleted from the
   pipeline (institutional memory is a named long-term goal, spec §31); a `status`
   column marks `archived`.

## Provenance columns (spec §27)

`opportunity_sources`, and any AI-derived row (`ai_solicitation_analyses`), always
populate:

- `source` — e.g. `"SAM.gov"`, `"Manual Entry"`, `"AI Extraction (Claude)"`
- `source_url` — deep link back to the original notice/document where one exists
- `retrieved_at` — timestamp the data was pulled
- `confidence` — `verified_fact | inferred | ai_generated | unverified`

The frontend renders a "View Source" affordance anywhere one of these fields is shown,
per spec §27/§28. Manually entered data (a BD staffer typing in a field) is stored with
`source = "Manual Entry"` and `confidence = "verified_fact"` — the human is the source.

## Migrations

Run from `backend/`:

```
alembic upgrade head        # apply all migrations
alembic revision --autogenerate -m "message"   # create a new migration after model changes
```

The initial migration (`0001_initial_schema`) creates every ✅ table above plus indexes
on foreign keys and the columns the UI filters/sorts by (`pipeline_stage_id`,
`proposal_due_at`, `agency_id`, score).
