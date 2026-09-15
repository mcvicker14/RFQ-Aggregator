# Roadmap

## Phase 0 — this build (MVP)

See `docs/MVP_SPEC.md`. Opportunity database & pipeline, scoring, Go/No-Go, tasks,
agencies/contacts, forecasting, documents, SAM.gov connector, AI solicitation reader,
sample data.

## Phase 1 — strengthen the MVP loop

- Email delivery for alerts (daily digest / weekly intelligence report) — needs an
  SMTP/SendGrid/SES credential from Principal; the alert data model and templates are
  already built, this is wiring a provider.
- Drag-and-drop on the Kanban board (MVP ships stage-change via a dropdown on each
  card, which is fully functional but less fluid than drag-and-drop).
  full-text search (`tsvector`) once opportunity volume makes `ILIKE` filtering slow.
- TanStack Query on the frontend if client-side caching/revalidation needs grow beyond
  what plain fetch + React state comfortably handles.

## Phase 2 — the next four modules named in the long-term spec

1. **Early Signals** (spec §3) — dedicated table + UI for pre-solicitation signals
   (appropriations, CIPs, environmental assessments, bond issues) feeding the
   `maturity_stage` field the MVP already has on `opportunities`.
2. **USASpending / FPDS ingestion** — a second `OpportunityConnector` implementation;
   feeds Agency Intelligence and Recompete Tracker with real historical award data.
3. **Recompete Tracker** (spec §11) — `contracts`/`contract_awards`/`recompetes` tables,
   expiration-window estimation, alerting 12–24 months out.
4. **Teaming Partner intelligence** (spec §9) — natural-language partner search over the
   `companies` table ("find architectural partners with VA hospital experience in the
   Southeast") using embeddings once there's enough company data to make retrieval
   meaningful.

## Phase 3 — deeper intelligence

SF330 matching (spec §8, needs `employees`/`resumes`/`past_performance` tables and a
real corpus of Principal's actual resumes/project sheets — must not launch until that
data exists, since fabricated qualifications are explicitly prohibited), Agency
Intelligence spend rollups (spec §12, needs USASpending data from Phase 2), Competitor
Intelligence beyond tagging (spec §10), Incumbent Contract Recompete alerting refined
with real obligation data, interactive opportunity map (spec §17).

## Phase 4 — AI assistant & institutional memory

Conversational "Principal Intelligence Assistant" (spec §16) with retrieval-augmented
generation over opportunities, documents, past performance, and win/loss history, citing
underlying records for every answer. This is explicitly sequenced last because it's the
feature most dependent on there being a rich, trustworthy corpus already in the system
— an assistant answering from a thin database would be more likely to produce the kind
of unsupported claim spec §16/§27/§28 prohibit.

## Explicitly not planned as scraping

Per instructions, no connector will be built that violates a source website's terms of
service. Where a state/municipal procurement portal has no public API, the plan is a
manual-entry-assisted workflow (a BD staffer pastes a link, a lightweight preview is
fetched respecting robots.txt) rather than an automated scraper — decided per source
when that phase starts.
