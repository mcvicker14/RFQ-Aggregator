# API Structure

FastAPI, prefix `/api`. Interactive OpenAPI docs at `/api/docs` when the backend is
running. All routes except `/api/auth/login` and `/api/health` require a bearer JWT.
"Role" = minimum role required beyond authentication (see `docs/SECURITY.md` for the
full matrix); "any" = any authenticated user.

| Method & path | Purpose | Role |
|---|---|---|
| `POST /api/auth/login` | Email/password → JWT | public |
| `GET /api/auth/me` | Current user + role | any |
| `GET /api/dashboard/summary` | All KPI card values + chart data | any |
| `GET /api/opportunities` | List with filter/search/sort/pagination query params | any |
| `POST /api/opportunities` | Create | BD+ |
| `GET /api/opportunities/{id}` | Full profile | any |
| `PATCH /api/opportunities/{id}` | Update fields | BD+ (PM/Proposal Mgr limited to their fields) |
| `DELETE /api/opportunities/{id}` | Archive (soft) | Administrator |
| `POST /api/opportunities/{id}/stage` | Move pipeline stage | BD+ |
| `GET /api/opportunities/{id}/score` | Current Principal Pursuit Score | any |
| `POST /api/opportunities/{id}/score/recalculate` | Force recompute | BD+ |
| `GET /api/opportunities/{id}/activities` | Timeline | any |
| `GET/POST /api/opportunities/{id}/gonogo` | View / start Go-No-Go review | any / BD+ |
| `PATCH /api/gonogo/{id}` | Update criteria scores | BD+ |
| `POST /api/gonogo/{id}/decide` | Record final human decision | Executive/Administrator |
| `GET/POST /api/opportunities/{id}/tasks` | Tasks for an opportunity | any / any |
| `GET /api/tasks` | Cross-opportunity task list ("What needs attention today") | any |
| `PATCH /api/tasks/{id}` | Update/complete | any (own or assigned) |
| `GET/POST /api/opportunities/{id}/documents` | List / upload | any / any |
| `GET /api/documents/{id}/download` | Download original file | any |
| `POST /api/documents/{id}/analyze` | Run AI solicitation analysis | any |
| `GET /api/documents/{id}/analysis` | Retrieve stored analysis | any |
| `GET/POST /api/opportunities/{id}/forecast` | View / set forecast fields | any / BD+ |
| `GET /api/forecast/summary` | Aggregated pipeline/weighted/committed/target/gap | any |
| `GET/POST /api/agencies`, `/api/agencies/{id}` | Agency directory | any / BD+ |
| `GET/POST /api/companies`, `/api/companies/{id}` | Teaming partner / competitor directory | any / BD+ |
| `GET/POST /api/contacts`, `/api/contacts/{id}` | Contact CRM | any / any |
| `GET /api/pipeline-stages` | Ordered stage list | any |
| `PATCH /api/pipeline-stages` | Reorder/rename (admin) | Administrator |
| `GET /api/alerts` | Current user's in-app alerts | any |
| `PATCH /api/alerts/{id}/read` | Mark read | any |
| `GET/PATCH /api/alert-rules` | User's alert preferences | any |
| `POST /api/ingestion/sam-gov/sync` | Trigger SAM.gov sync (or 503 if unconfigured) | BD+ |
| `GET /api/ingestion/sam-gov/status` | Last sync time, configured?, result counts | any |
| `GET/PATCH /api/settings/scoring-weights` | Scoring weight profile | any / Administrator |
| `GET/POST /api/users` | User admin | any (list) / Administrator (create) |
| `GET /api/health` | Liveness/readiness (DB connectivity) | public |

Errors follow a consistent shape: `{"detail": "human-readable message"}` with the
appropriate HTTP status (`400` validation, `401` unauthenticated, `403` wrong role,
`404` not found, `409` conflict, `503` unconfigured external integration). The frontend
API client surfaces `detail` directly in error/toast states rather than a generic
"something went wrong."

Full request/response schemas are defined once as Pydantic models in
`backend/app/schemas/` and are the source of truth (visible live at `/api/docs`);
this table is a map, not a duplicate spec.
