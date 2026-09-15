# Site Map / Navigation

Primary left-nav (per long-term spec §24), with MVP scope noted:

| Nav item | MVP? | Route | Purpose |
|---|---|---|---|
| Dashboard | ✅ | `/` | Executive KPI dashboard |
| Opportunities | ✅ | `/opportunities`, `/opportunities/[id]` | Searchable database + full profile page |
| Pipeline | ✅ | `/pipeline` | Kanban + table by stage |
| Go/No-Go | ✅ | `/opportunities/[id]/go-no-go` (panel on the opportunity page) | Formal decision tool |
| Tasks | ✅ | `/tasks` | "What needs attention today" + full task list |
| Agencies | ✅ (light) | `/agencies`, `/agencies/[id]` | Agency + office directory tied to opportunities |
| Companies | ✅ (light) | `/companies`, `/companies/[id]` | Teaming partners / competitors / firms |
| Contacts | ✅ | `/contacts`, `/contacts/[id]` | CRM contacts tied to opportunities |
| Documents | ✅ | `/opportunities/[id]` (Documents tab); no separate global doc search in MVP | Per-opportunity document repository |
| Reports / Forecast | ✅ | `/forecast` | Revenue/pipeline forecasting views |
| Discover (SAM.gov sync) | ✅ | `/discover` | Manual + connector-driven opportunity discovery |
| Early Signals | 🧭 Phase 2 | `/signals` | Not built; `maturity_stage` field exists on opportunities today as groundwork |
| Recompetes | 🧭 Phase 2 | `/recompetes` | Not built (needs contract/award data model) |
| AI Assistant | 🧭 Phase 2 (chat UI); AI solicitation reader **is** in MVP | `/opportunities/[id]` (Documents tab → "Analyze with AI") | Conversational assistant deferred; document analysis shipped |
| Settings | ✅ (minimal) | `/settings` | Users/roles, scoring weights, pipeline stage admin |

Auth: `/login`. Unauthenticated users are redirected to `/login`; all other routes
require a session.

## Opportunity profile page tabs

`/opportunities/[id]` — Overview · Score · Go/No-Go · Tasks · Contacts & Team ·
Documents · Forecast · Timeline

## Route → role visibility

See `docs/SECURITY.md` for the RBAC matrix. Every route above is reachable by every
role; what differs is which actions (edit, delete, record Go/No-Go decision, change
scoring weights) are permitted, enforced on the backend and reflected in the UI by
disabling/hiding controls the current user cannot use.
