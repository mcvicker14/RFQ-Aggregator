# Data Ingestion Architecture

## Connector framework

```python
class OpportunityConnector(ABC):
    name: str
    def fetch(self, since: date, **filters) -> list[RawOpportunity]: ...
    def normalize(self, raw: RawOpportunity) -> OpportunityCreate: ...
```

Each connector lives in `backend/app/connectors/<name>.py`, is registered in
`backend/app/connectors/registry.py`, and is invoked by
`backend/app/services/ingestion.py`, which:

1. Calls `fetch()`.
2. De-duplicates against existing `opportunities` (by `solicitation_number` +
   `agency_id`, falling back to a title/agency/date fuzzy match).
3. Inserts new opportunities at stage "Signal Detected" and updates changed fields on
   existing ones (never silently overwrites a field a human has since edited by hand —
   see "field ownership" below).
4. Writes an `opportunity_sources` row every time, so every ingested fact is traceable.
5. Generates an `alert` for each new match against a user's saved alert rules.

**Field ownership:** once a human edits a field on an opportunity that ingestion also
populates (e.g. `estimated_value`), that field is marked `locked_by_user = true` in an
edit-tracking column and future syncs stop overwriting it, only flagging a conflict as
an activity-log entry. This avoids the common integration failure mode where a nightly
sync clobbers a BD staffer's research.

## Connectors implemented in this MVP

### SAM.gov (`backend/app/connectors/sam_gov.py`)

Real integration against the public **SAM.gov Get Opportunities v2 API**
(`https://api.sam.gov/prod/opportunities/v2/search`), which covers Solicitations,
Presolicitations, Combined Synopsis/Solicitation, Sources Sought, and Special Notices —
i.e. spec §2's SAM.gov, Sources Sought, RFI, and Presolicitation sources in one API.

- **Auth:** query parameter `api_key`, read from the `SAM_GOV_API_KEY` environment
  variable. Principal Engineering obtains this by signing in at sam.gov, opening
  **Account Details**, and requesting a **Public API Key** — no cost, no separate
  vendor contract.
- **Request:** `postedFrom`/`postedTo` (required by the API, max 1-year span — the
  connector pages backward in ≤1-year windows if a longer backfill is requested),
  `limit`/`offset` for pagination, optional `ncode` (NAICS), `state`, `title`, `ptype`
  filters. `backend/app/connectors/sam_gov.py` also accepts an app-level NAICS/keyword
  filter list (seeded with Principal's markets — civil, water/wastewater, environmental
  engineering NAICS codes) so a sync doesn't pull in irrelevant notices.
- **Response parsing is defensive on purpose.** This sandbox's network egress allowlist
  blocks documentation sites, so the field mapping in `sam_gov.py` was written from
  well-established public knowledge of this stable API rather than a live fetch of the
  current schema. The parser reads fields with `.get()` and tolerates missing/renamed
  keys instead of crashing, logs any notice it can't fully map, and the module docstring
  says explicitly: **verify field names against the live SAM.gov API response the first
  time real ingestion is run**, and adjust `_map_fields()` if anything has drifted.
- **Rate limits:** SAM.gov gives non-federal accounts on the order of 10 calls/day. The
  sync endpoint is manually triggered (a "Sync Now" button on `/discover`) rather than
  polling continuously, and the service caches the last sync window to avoid redundant
  calls.
- **Without a key configured:** `POST /api/ingestion/sam-gov/sync` returns
  `503 {"detail": "SAM.gov integration is not configured. Add SAM_GOV_API_KEY to the
  backend environment."}`. The `/discover` page shows this state plainly with setup
  instructions, and still allows manual opportunity entry.

## Connectors documented but not implemented (Phase 2+)

Everything else in long-term spec §2 (USASpending/FPDS, state/parish/municipal
procurement portals, agency forecasts, FEMA/USACE/VA program announcements, grants,
appropriations) gets a connector class later using the same `OpportunityConnector`
interface. Several of these (most state/municipal portals) have no public API and would
need either a manual-entry workflow or a scraper built in compliance with that site's
terms of service — the framework supports both, but per instructions this build does not
scrape any site whose terms would prohibit it.

## Provenance (spec §27)

See `docs/DATABASE_SCHEMA.md` §Provenance. This is enforced at the service layer, not
just convention: `ingestion.py` and the AI analysis service are the only two code paths
allowed to write `confidence != "verified_fact"`, and both are required (by a check in
`services/opportunities.py`) to also write `source`/`source_url`/`retrieved_at` in the
same transaction as the fact they're recording.
