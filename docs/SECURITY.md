# Security Architecture

## Authentication (MVP)

Local email/password authentication with hashed passwords (bcrypt via `passlib`) and
short-lived **JWT access tokens** (`backend/app/core/security.py`), issued on
`POST /api/auth/login` and required (as a bearer token) on every other endpoint.

**Microsoft 365 / Google Workspace SSO (spec §25/§21) is not implemented in this
build.** It requires Principal's own Azure AD / Google Workspace tenant credentials
(an app registration only Principal's IT admin can create), which this sandbox
cannot obtain or fabricate. Local email/password auth (above) is the only sign-in
method right now. Adding SSO later means introducing an OAuth2/OIDC flow (e.g. via
Authlib against Microsoft's `/common/v2.0` endpoint) alongside the existing
JWT-based auth — a new, scoped piece of work, not a rewrite of what's here.

## Roles & permissions (spec §21)

| Role | Can view | Can edit opportunities | Go/No-Go decision | Manage users/settings | Delete records |
|---|---|---|---|---|---|
| Administrator | everything | yes | yes | yes | yes |
| Executive | everything | yes | yes | no | no |
| Business Development | everything | yes | no (can submit AI-assisted recommendation, not record final decision) | no | no |
| Project Manager | everything | yes (own opportunities + assigned) | no | no | no |
| Proposal Manager | everything | yes (proposal-stage fields) | no | no | no |
| Viewer | everything | no | no | no | no |

Enforced server-side via a `require_role(...)` FastAPI dependency on every mutating
route (`backend/app/core/deps.py`) — the frontend hiding a button is a UX nicety, not
the security boundary. `docs/API_STRUCTURE.md` marks each endpoint's required role.

## Secrets

- Nothing is committed to the repository. `backend/.env.example` and
  `frontend/.env.local.example` list every variable name the app reads, with no real
  values.
- Real secrets (`DATABASE_URL`, `JWT_SECRET_KEY`, `SAM_GOV_API_KEY`,
  `ANTHROPIC_API_KEY`, storage credentials) are read only from environment variables
  (`backend/app/core/config.py` via `pydantic-settings`) — never hard-coded, never
  logged. The FastAPI startup check fails loudly (not silently) if `JWT_SECRET_KEY` is
  left at its insecure default outside of `ENV=development`.
- `.gitignore` excludes `.env`, `.env.local`, `*.pem`, `*.key`, and the local upload
  directory.

## File uploads

`backend/app/services/storage.py` validates uploaded documents by extension and MIME
sniffing (PDF, DOCX, DOC, XLSX, images) before storage, enforces a size limit, and
stores files outside the web root at a generated path (not the user-supplied filename)
to prevent path traversal; the original filename is kept only as metadata.

## Input validation & injection

- All request/response shapes are Pydantic schemas — FastAPI rejects malformed input
  before it reaches a service function.
- All database access goes through SQLAlchemy's parameterized query builder; no raw SQL
  string interpolation anywhere in the codebase.
- The frontend is React (auto-escapes output), and any user-generated HTML (there is
  none rendered as raw HTML in this MVP) would need explicit sanitization before that
  changes.

## Transport & headers

CORS is restricted to the configured frontend origin (`backend/app/main.py`); in
production this should sit behind HTTPS (terminated at a load balancer/reverse proxy —
not something this sandbox can provision, noted in `docs/ARCHITECTURE.md` §7).

## What's explicitly deferred

SSO, per-field audit logging beyond the `activities` timeline, at-rest encryption
beyond what the hosting platform provides by default, and a formal secrets manager
(Key Vault/Secrets Manager) integration — `config.py` is written so swapping the source
of environment variables for a secrets manager later doesn't change application code.
