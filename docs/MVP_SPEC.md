# MVP Feature Specification

Scope for this build, as directed by Principal Engineering leadership. Supersedes the
generic "MVP 1–5" grouping in the original long-term spec with a concrete, itemized
list.

1. **Executive dashboard** — KPI cards, pipeline charts, Highest Priority Opportunities,
   What Needs Attention Today.
2. **Opportunity database** — full CRUD, list view with search/filter/sort.
3. **Opportunity detail/profile page** — all fields from long-term spec §6 that don't
   depend on an unbuilt module (SF330 matching, competitor deep-intel), plus a timeline
   of activity.
4. **Pipeline** — the 16 default stages (spec §18), Kanban and table views, editable by
   admins.
5. **Search, filters, sorting** — across opportunities; agencies/companies/contacts get
   basic search too.
6. **Principal Pursuit Score (0–100)** — full weighted methodology from spec §4,
   configurable weights, explanation + primary concern text.
7. **Go/No-Go tool** — configurable 1–5 criteria, AI recommendation factors, human
   decision recorded with author + timestamp.
8. **Tasks** — owner, deadline, priority, status, linked opportunity, notes.
9. **Agencies & contacts** — tied to opportunities; light profiles (not full Agency
   Intelligence dashboards — that's Phase 3).
10. **Revenue/pipeline forecasting** — per-opportunity forecast fields, weighted value,
    aggregate views by month/quarter/year/agency/market.
11. **Document repository** — per-opportunity upload/download, categorized, versioned by
    re-upload.
12. **SAM.gov integration** — real connector code against the public Opportunities API;
    functional the moment a `SAM_GOV_API_KEY` is configured; clearly marked
    not-configured otherwise.
13. **AI solicitation analysis** — real Claude API integration; functional the moment an
    `ANTHROPIC_API_KEY` is configured; clearly marked not-configured otherwise.
14. **Sample data** — realistic, clearly labeled `SAMPLE DATA`, covering VA, USACE,
    FEMA, NRCS, municipal, and Air Force opportunities with a mix of SDVOSB/small
    business/unrestricted/sources-sought/presolicitation/recompete types.

## Explicitly out of scope for this build (see `docs/ROADMAP.md`)

Early Signals module, USASpending/FPDS ingestion, Recompete Tracker, SF330 matching,
Teaming Partner natural-language search, Competitor Intelligence beyond basic tagging,
Agency Intelligence spend rollups, conversational AI assistant (chat), interactive US
map, Microsoft 365/Google SSO, email digests (the alert *data model* and in-app
notifications are built; outbound email is a documented integration point, not wired to
a real mail provider).

## Definition of done for this MVP

- A BD staffer can log in, see a real (seeded) pipeline on the dashboard, open an
  opportunity, read/edit every field, score it, run a Go/No-Go, add tasks, attach a
  document, and see it reflected in forecasting — all against a real Postgres database
  through a real API, no mock data in the frontend.
- Every button either works or is visibly disabled with an explanation; nothing is a
  dead click.
- The app is honest about what is and is not connected to a live external source.
