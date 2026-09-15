# System Architecture — Principal Opportunity Intelligence

*Find Earlier. Pursue Smarter. Win More.*

This document describes the technical architecture of the platform. It is written for
developers (human or AI) who will extend this codebase. For a plain-English overview,
see the root `README.md`.

## 1. Scope of this build

The full long-term product vision is large (see `docs/ROADMAP.md`). This codebase
implements the **MVP**: an opportunity database, pipeline, scoring engine, Go/No-Go
tool, tasks, agencies/contacts, revenue forecasting, document storage, a SAM.gov
ingestion connector, and an AI solicitation-analysis service. Everything is built as
**real, working code** — nothing is a mockup. Where a feature depends on a credential
Principal Engineering has not yet supplied (a SAM.gov API key, an Anthropic API key,
cloud storage), the code path is fully implemented and will work the moment the
credential is configured; the UI states plainly when it is not yet configured rather
than faking a result.

## 2. High-level architecture

```
┌─────────────────────────┐        ┌──────────────────────────┐        ┌──────────────┐
│        Frontend         │  HTTPS │          Backend          │  SQL   │  PostgreSQL  │
│  Next.js 14 (App Router)│ ─────► │  FastAPI (Python 3.11)    │ ─────► │   Database    │
│  React + TypeScript     │ ◄───── │  SQLAlchemy 2.0 + Alembic │ ◄───── │              │
│  Tailwind CSS + shadcn/ui│  JSON │  JWT auth, RBAC            │        └──────────────┘
└─────────────────────────┘        │  Service layer:            │
                                    │   - scoring engine          │        ┌──────────────┐
                                    │   - SAM.gov connector       │ ─────► │  File storage │
                                    │   - AI solicitation reader  │        │  local disk   │
                                    │   - forecasting             │        │  (S3/Azure    │
                                    │   - alerts                  │        │   pluggable)  │
                                    └──────────────┬─────────────┘        └──────────────┘
                                                   │
                                     ┌─────────────┴──────────────┐
                                     │   External integrations     │
                                     │   - SAM.gov Opportunities API│
                                     │   - Anthropic Claude API     │
                                     │   (both optional at runtime; │
                                     │    app degrades gracefully)  │
                                     └───────────────────────────┘
```

### Why this stack

The long-term spec allows "Python FastAPI or Node.js" for the backend. This build uses
**FastAPI** because: the existing repository already had a FastAPI/Python stub
(`rfq_aggregator_starter/`), Python has the strongest libraries for document parsing
(PDF/DOCX) and data science-flavored scoring logic, and FastAPI's Pydantic schemas give
us request/response validation "for free," which matters for an app whose core value is
data integrity and provenance.

The frontend uses **Next.js 14 (App Router) + TypeScript + Tailwind + shadcn/ui**
exactly as specified — a component library suited to dense, professional data
interfaces rather than a "playful startup" look.

### Monorepo layout

```
/backend          FastAPI application (see docs/API_STRUCTURE.md)
/frontend          Next.js application
/docs               Architecture & planning documents (this folder)
/rfq_aggregator_starter, /rfq_program   Pre-existing placeholder stubs, left untouched
```

The two legacy folders (`rfq_aggregator_starter/`, `rfq_program/`) predate this build
and contained only placeholder files (a one-line FastAPI app, a `print()` statement, an
empty YAML file). They were not deleted — nothing of substance would be lost or gained
either way — but all real application code lives in `/backend` and `/frontend`.

## 3. Backend architecture

```
backend/app/
  main.py                 FastAPI app factory, middleware, router registration
  core/
    config.py             Settings (pydantic-settings), reads environment variables
    security.py           Password hashing, JWT issue/verify
    deps.py                FastAPI dependencies: current user, role guards, DB session
  db/
    base.py                 Declarative base, naming conventions
    session.py              Engine + session factory
  models/                  SQLAlchemy ORM models, one module per domain
  schemas/                 Pydantic request/response schemas
  api/routes/              One router per resource (thin: validation + delegation)
  services/                Business logic (scoring, forecasting, alerts, storage)
  connectors/              Pluggable external data-source connectors (see below)
  ai/                       AI solicitation reader (document parsing + LLM extraction)
alembic/                   Versioned schema migrations
seed/                       Sample-data seeding script (clearly flagged SAMPLE DATA)
tests/                       Pytest smoke tests
```

**Layering rule:** routes never talk to the database directly — they call a service
function, which uses the ORM. This keeps business logic (like score calculation or
weighted pipeline math) testable and reusable outside the HTTP layer (e.g. from a
future scheduled ingestion job).

### Connector framework (for section "data ingestion")

`backend/app/connectors/base.py` defines an abstract `OpportunityConnector` with a
single method, `fetch(since: date) -> list[RawOpportunity]`. Each data source (SAM.gov
today; USASpending, state portals, agency forecasts, etc. in later phases) implements
this interface and is registered in `backend/app/connectors/registry.py`. The ingestion
service normalizes whatever a connector returns into the common `Opportunity` model and
**always writes an `OpportunitySource` provenance record** (source name, source URL,
retrieved date, confidence) — see `docs/DATA_INGESTION.md`. Adding a new source later
means writing one new connector class; nothing else in the app changes.

### AI solicitation reader

`backend/app/ai/` wraps the Anthropic Messages API behind a small interface
(`SolicitationAnalyzer`). Given extracted document text, it asks the model to return a
**strict JSON schema** (scope, deliverables, disciplines, dates, evaluation factors,
top-10 list, red flags) with instructions to leave a field `null`/"not stated" rather
than invent a value. Every AI-derived field is stored with a pointer back to the source
document and is visually marked as AI-extracted, per the "never fabricate procurement
information" requirement. If `ANTHROPIC_API_KEY` is not configured, the endpoint returns
a `503` with a clear "AI analysis is not configured" message and the frontend shows an
explicit not-configured state — it does not pretend to analyze the document.

## 4. Frontend architecture

```
frontend/src/
  app/                    Next.js App Router pages (one folder per route)
  components/
    ui/                    shadcn/ui primitives
    layout/                App shell: sidebar nav, top bar, breadcrumbs
    opportunities/, dashboard/, pipeline/, tasks/, ...   Feature components
  lib/
    api/                   Typed API client (fetch wrappers per resource)
    auth.ts                 Session/token handling
    utils.ts
  types/                    Shared TypeScript types mirroring backend schemas
```

Server state (opportunities, tasks, etc.) is fetched via a small typed API client and
React state/`useEffect`/route handlers — no heavier data-fetching library was added for
the MVP to keep the dependency surface small; this is a documented place to introduce
TanStack Query later if caching needs grow (see `docs/ROADMAP.md`).

## 5. Data provenance (cross-cutting)

Every record that originates outside a human typing it into the app (an ingested
opportunity, an AI-extracted field) carries `source`, `source_url`, `retrieved_at`, and
`confidence`. The UI never presents an AI- or connector-derived fact without a "View
Source" affordance. See `docs/DATA_INGESTION.md` §Provenance.

## 6. Security

See `docs/SECURITY.md` for the full model: authentication, RBAC, secret handling,
upload validation, and what is explicitly deferred (SSO).

## 7. Deployment shape (target, not exercised in this sandbox)

- **Database:** managed PostgreSQL (Azure Database for PostgreSQL, AWS RDS, etc.)
- **Backend:** containerized FastAPI app (Dockerfile included) behind HTTPS
- **Frontend:** containerized Next.js app, or Vercel
- **File storage:** local disk by default (dev); the `StorageBackend` interface in
  `backend/app/services/storage.py` has a second implementation point for S3/Azure Blob
  — swapping it in is a config change, not a rewrite.
- **docker-compose.yml** at the repo root runs Postgres + backend + frontend together
  for local development. This sandbox does not have a Docker daemon available, so the
  compose file was written to mirror the exact configuration that *was* validated by
  running Postgres, the backend, and the frontend directly — but the compose path
  itself has not been executed end-to-end. Note this before relying on it for a first
  deployment.
