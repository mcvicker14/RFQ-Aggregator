# Data Ingestion Architecture

For the full multi-source design (Source Registry, intelligence categories,
deduplication, sync logging) see `docs/PHASE2_ARCHITECTURE.md` — this doc is the
"how it actually works today" reference.

## Connector framework

```python
class IntelligenceConnector(ABC):
    key: str            # matches intelligence_sources.connector_key
    name: str
    default_category: IntelligenceCategory

    def is_configured(self) -> bool: ...
    def fetch(self, since: date, **filters) -> list[RawIntelligenceItem]: ...
```

Each connector lives in `backend/app/connectors/<name>.py` and is registered in
`backend/app/connectors/registry.py`, keyed by the same string as its
`intelligence_sources.connector_key` row (the Source Registry — see
`docs/PHASE2_ARCHITECTURE.md` §3). A registry row with no matching connector simply
has no working code yet; that's a normal, expected state for a source that's
documented but not yet automatable (§8), not an error.

`backend/app/services/intelligence_sync.py::run_sync()` is what actually invokes a
connector, for every source, whether triggered from the Source Manager UI's "Sync
Now"/"Sync All Enabled Sources" or (in the future) a schedule:

1. Guards against two syncs running concurrently for the same source.
2. Calls `connector.fetch(since)`. A configuration or fetch failure is caught and
   logged — it marks the source unhealthy and the run failed, but never raises past
   `run_sync()`, so one bad source can't abort a "sync all" pass.
3. Upserts each returned item into `intelligence_items`, keyed on
   `(intelligence_source_id, external_id)` — de-duplication *within* one source.
   Cross-source de-duplication (the same real project reported by two different
   sources) is a separate, human-reviewable process — `app/services/dedup.py` — that
   only ever proposes a likely/possible match, never merges automatically.
4. If the item's `intelligence_category` is `LIVE_OPPORTUNITY` or
   `PRE_SOLICITATION`, promotes it into the existing `opportunities` pipeline
   (`intelligence_sync.py::promote_intelligence_item`) — inserting at pipeline stage
   "Signal Detected" for a new one, or updating changed fields on an existing one.
   `EARLY_SIGNAL` and `AWARD_INTELLIGENCE` items are never promoted; they stay
   intelligence-only.
5. **Field ownership is unchanged from the original design**: once a human edits a
   field an ingestion connector also populates, that field name is added to the
   opportunity's own `locked_fields` list, and every future sync leaves it alone
   rather than overwriting a BD staffer's research.
6. Writes an `opportunity_sources` row on every promotion, so every ingested fact on
   an opportunity stays traceable exactly as before — this table and its meaning are
   untouched by Phase 2.
7. Logs one `intelligence_sync_runs` row per attempt (fetched/created/updated/errored
   counts, status, error detail) for the Source Manager UI's history view.

## Connectors implemented today

### SAM.gov (`backend/app/connectors/sam_gov.py`)

Real integration against the public **SAM.gov Get Opportunities v2 API**
(`https://api.sam.gov/prod/opportunities/v2/search`), covering Solicitations,
Presolicitations, Combined Synopsis/Solicitation, Sources Sought, Special Notices, and
Award Notices — mapped to an intelligence category per SAM.gov's own notice `type`
(solicitations → `LIVE_OPPORTUNITY`, presolicitation/sources-sought/special →
`PRE_SOLICITATION`, award notices → `AWARD_INTELLIGENCE`; anything unrecognized
defaults to `LIVE_OPPORTUNITY`, preserving this connector's original behavior from
before Phase 2, when every notice became a pipeline opportunity).

- **Auth:** query parameter `api_key`, read from the `SAM_GOV_API_KEY` environment
  variable. Principal Engineering obtains this by signing in at sam.gov, opening
  **Account Details**, and requesting a **Public API Key** — no cost, no separate
  vendor contract.
- **Request:** `postedFrom`/`postedTo` (required by the API, max 1-year span — the
  connector pages backward in ≤1-year windows if a longer backfill is requested),
  `limit`/`offset` for pagination, `ptype` (all six substantive notice type codes —
  Sources Sought and Presolicitations are always requested, never dropped), and
  `ncode` — defaulting to the NAICS **5413\* prefix** (the whole "Architectural,
  Engineering, and Related Services" subsector SAM.gov's own filter supports
  prefix-matching on, not just the single primary code) plus Principal's configured
  secondary codes.
- **Two-stage retrieval, not just a filter.** A production incident (healthy
  connection, 0 items on manual sync) turned out to be an overly narrow default NAICS
  filter (a handful of exact codes, no NAICS-family breadth), not a broken
  integration — see the fix's detail in the module docstring. Stage 1 is the broad
  request above; Stage 2 (`_score_relevance()` in `sam_gov.py`) ranks every result
  against Principal's actual practice profile (keyword relevance, weighted
  agencies — VA/USACE/Air Force/DoD/FEMA/NRCS, Gulf Coast/Southeast region, SDVOSB/
  small-business set-asides) and drops the rare notice that only matched Stage 1 on a
  technicality, plus any Live Opportunity/Pre-Solicitation already past its own
  proposal deadline. Results are sorted best-match-first before being capped, so a
  broader Stage 1 means better results, not just more of them.
- **Response parsing is defensive on purpose.** This sandbox's network egress allowlist
  blocks documentation sites, so the field mapping in `sam_gov.py` was written from
  well-established public knowledge of this stable API rather than a live fetch of the
  current schema — verified instead with realistic fixture payloads
  (`backend/tests/test_sam_gov_connector.py`). The parser reads fields with `.get()`
  and tolerates missing/renamed keys instead of crashing, and logs any notice it can't
  fully map rather than fabricating one. **Verify field names against a real SAM.gov
  sync's `raw_metadata` the first time it runs in production**, and adjust
  `_to_raw_intelligence_item()` if anything has drifted.
- **Without a key configured:** a sync attempt fails with a clear "not configured"
  error, the source's health status shows `needs_configuration` in the Source Manager
  UI, and the rest of the app is unaffected.

### USAspending.gov and Grants.gov

See `docs/PHASE2_ARCHITECTURE.md` §8 for what's implemented and why (both are stable,
keyless public APIs — no new secret to manage for either).

## Sources documented but not yet implemented

See `docs/PHASE2_ARCHITECTURE.md` §8 for the full Wave 1 triage — every source named
in the Phase 2 spec is registered in the Source Registry with an honest status
(`needs_configuration`/`manual_only`) and research notes, even where no connector
exists yet. Several (most state/municipal portals) have no confirmed public API and
would need either a manual-entry workflow or a scraper built in compliance with that
site's terms of service — the framework supports both, but this build does not scrape
any site whose access method/terms haven't been verified first.

## Provenance

See `docs/DATABASE_SCHEMA.md` §Provenance and `docs/PHASE2_ARCHITECTURE.md` §3. Every
`intelligence_items` row carries `source`/`source_url`/`retrieved_at`/`confidence`
(the same shape as `ProvenanceMixin`, used identically on `Opportunity`) plus
`raw_metadata`, the full original payload, for audit. `intelligence_sync.py` and the
AI analysis service remain the only code paths allowed to write
`confidence != "verified_fact"`.
