# Principal Opportunity Intelligence

**Find Earlier. Pursue Smarter. Win More.**

A business-development intelligence platform built for Principal Engineering — an
SDVOSB civil engineering firm pursuing federal, state, local, and private A/E work.
It's meant to replace scattered spreadsheets and inboxes with one place to find,
score, track, and win engineering opportunities.

This README is written for anyone opening this project for the first time,
technical or not. For build details, see the `docs/` folder.

## What's actually built right now

This is a working application, not a mockup — every screen described below is
connected to a real database and a real backend. It covers:

1. A professional dashboard showing pipeline health at a glance.
2. A searchable database of every opportunity Principal is tracking.
3. A full profile page for each opportunity — dates, contacts, documents, everything.
4. A pipeline board (and table) showing what stage every pursuit is in, from an
   early signal all the way through won or lost.
5. Search, filtering, and sorting across opportunities.
6. The **Principal Pursuit Score** — a 0–100 score on every opportunity, with a
   plain-English explanation of why it scored that way.
7. A **Go/No-Go** decision tool — the software recommends, a person decides.
8. Tasks and follow-up dates tied to each opportunity, plus a "what's due today"
   view.
9. Agencies and contacts, linked to the opportunities they're associated with.
10. Revenue forecasting — weighted pipeline value, by month/quarter/agency/market.
11. A document library on every opportunity, with an AI tool that reads an uploaded
    RFP/RFQ and pulls out the scope, deadlines, evaluation factors, and red flags.
12. That same AI-reading tool, ready to go as soon as an AI provider key is added.
13. A set of realistic **SAMPLE opportunities** so you can see the app in action —
    every one of them is clearly labeled `SAMPLE DATA` so it's never confused with
    a real pursuit.
14. **A multi-source intelligence platform**, not just a SAM.gov tracker:
    - The **Source Registry** (`Intelligence Sources` in the sidebar) tracks every
      public source worth watching — SAM.gov, USAspending.gov, and Grants.gov are
      wired up and working today; dozens more (Louisiana state/local sources, USACE
      districts, federal forecasts, funding programs) are registered with an honest
      "needs configuration" status so nothing is faked.
    - Every incoming item is tagged **Live Opportunity**, **Pre-Solicitation**,
      **Early Signal**, or **Award Intelligence** — only the first two ever become a
      pipeline opportunity; early signals and competitor award history stay
      intelligence-only until they're genuinely relevant.
    - The **Discover** page is a filterable, sortable feed across all of that.
    - A deterministic **Early Signal Score** estimates how likely a signal is to
      turn into a real pursuit — separate from, and answering a different question
      than, the Principal Pursuit Score.
    - Possible duplicate reports of the same real-world project (e.g. an early
      funding signal that later becomes a live solicitation) are proposed, never
      auto-merged, and show up as a **Project Intelligence Timeline** on the
      opportunity's own page once one of them is promoted.
    - The Dashboard's new Intelligence section surfaces what's new since your last
      visit and which early signals deserve attention before a competitor gets there
      first.

See `docs/PHASE2_ARCHITECTURE.md` for the full design of all of this. The remaining
long-term vision (teaming-partner search, a conversational AI assistant, an
interactive opportunity map, and more) is documented in `docs/ROADMAP.md`, sequenced
into phases.

## Two things only you can do

Everything in this app works today with one exception: two optional features need a
credential that only Principal Engineering can obtain (they're free to get, but they
require an account only you control). Until they're added, the app says so plainly
in the interface — it never fakes a result.

1. **SAM.gov sync** (pulls new federal opportunities in automatically). To turn this
   on: sign in at [sam.gov](https://sam.gov), go to your Account Details page, and
   request a **Public API Key** (no cost). Give that key to whoever is hosting the
   app, to be set as `SAM_GOV_API_KEY`.
2. **AI solicitation reading** (uploads an RFP and gets a summary + red flags). To
   turn this on: create an account at
   [console.anthropic.com](https://console.anthropic.com/settings/keys) and generate
   an API key. This has a small usage cost (pay-as-you-go, based on how many
   documents get analyzed). Give that key to be set as `ANTHROPIC_API_KEY`.

Both are added to a configuration file (`backend/.env`) that is never uploaded to
GitHub — see **Keeping secrets safe** below.

## Using it on the web

The application is meant to be hosted somewhere permanent so it's reachable from an
ordinary browser, any time — see **`docs/DEPLOYMENT.md`** for the step-by-step guide
(written for a non-technical reader) to putting it on Render, a hosting provider with
a free tier that needs no credit card to start.

## Running it yourself, locally

The rest of this section is a technical setup guide for whoever is hosting/running
this day to day, or for testing changes before they go live. In short, the
application has three parts that all need to be running at the same time: a
database, a backend, and a frontend (the part you actually look at in a browser).

### Quick start (for a developer setting this up)

Prerequisites: Python 3.11+, Node.js 20+, and a PostgreSQL 16 database.

```bash
# 1. Backend
cd backend
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env            # then edit .env with real values
alembic upgrade head            # creates all the database tables
python -m seed.seed             # loads sample data + creates your login
uvicorn app.main:app --reload   # runs the backend at http://localhost:8000

# 2. Frontend (in a second terminal)
cd frontend
npm install
cp .env.local.example .env.local
npm run dev                     # runs the app at http://localhost:3000
```

Then open `http://localhost:3000` in a browser. The seed script prints an
administrator email/password the first time it runs — that's your login.

A `docker-compose.yml` is also provided for a more turnkey deployment once this is
hosted somewhere permanent (see `docs/ARCHITECTURE.md` for what that needs).

### Keeping secrets safe

Real passwords and API keys live only in files named `.env` (backend) and
`.env.local` (frontend) — these are deliberately excluded from Git (via
`.gitignore`) so they can never end up on GitHub. `.env.example` files show what's
needed, with no real values, and are safe to share.

## Where things live

```
backend/     The application server (Python/FastAPI) and the database schema
frontend/    The web application you interact with (Next.js/React)
docs/        Architecture, database schema, scoring methodology, security, roadmap
```

The two folders `rfq_aggregator_starter/` and `rfq_program/` are earlier
placeholder scaffolding that predates this build; they're left as-is and are not
part of the running application.

## Questions this project's docs answer

- **How do I put this on the web?** `docs/DEPLOYMENT.md`
- **How is it built, and why?** `docs/ARCHITECTURE.md`
- **What does the database look like?** `docs/DATABASE_SCHEMA.md`
- **How does the 0–100 score work?** `docs/SCORING_METHODOLOGY.md`
- **How does data get pulled in from SAM.gov?** `docs/DATA_INGESTION.md`
- **What's protected, and how?** `docs/SECURITY.md`
- **What's the API surface?** `docs/API_STRUCTURE.md`
- **What's next, in what order?** `docs/ROADMAP.md`
