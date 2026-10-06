# POI synchronization repair review — October 6, 2026

Local review candidate only. Nothing was pushed, published, deployed, ingested or
changed in the live sheet, Gmail, Render configuration, schedules or database.
BD expansion remains on hold. This concerns Principal Opportunity Intelligence,
not the separate Principal Engineering Intelligence application.

## Verified source and diagnosis

- Repository: `mcvicker14/RFQ-Aggregator`.
- Production branch read from Git: `claude/principal-opportunity-intelligence-jwitkf`.
- Verified branch head and local base: `88506e2152690c916e8bb7141889a15f0e514fb1`.
- Local review branch: `fix/poi-sync-review`; clean clone before these edits.
- No repository `AGENTS.md` or `.agents/skills` was present. Read README, ingestion,
  existing tests, deployment/configuration files and canonical POI Page health section.
- The backend sends `{secret, action: "read"}`. The checked-in script handles read
  before requiring `fields`. Follow-up read-only browser inspection opened Apps Script
  from this sheet's Extensions menu in the existing personal Google session. The bound
  project's active deployment is **version 3, September 29, 2026, 3:40 PM as displayed**.
  Project History version 3 and the saved source are identical (10,680 characters),
  have no `body.action` dispatch or read handler, require `fields` before `syncRow`,
  and contain the exact reported `Missing 'fields' object.` error. The bound script's
  app/script contract mismatch is directly verified. With Eric's follow-up approval,
  the existing Render Google sign-in succeeded without a new permission grant.
  Read-only inspection of only STATUS_BOARD_WEBHOOK_URL confirmed an exact match
  to that version-3 deployment URL; the value was re-hidden afterward.
- A fresh read-only Drive read of `Active!A33:P42` in the specified SOQ spreadsheet
  found **New RFQs at A38**, with an existing submitted record at A36. The checked-in
  shared locator requires A36. Publishing the unmodified repository script would
  therefore expose a second failure after the action mismatch is resolved.
- The old reader uses `getValues()` and converts dates with `String()`, losing sheet
  display formatting. It also treats a blank A cell as the end of the section.
- Stored row positions shift. The old matcher trusted a stored row number without
  corroboration and selected the first opportunity for a shared source URL.
- Item-processing failures, including total failures, advanced
  `last_successful_sync_at`, falsely making ingestion look current.

## Local changes

Exact changed files:

- `backend/app/services/status_board_webhook_client.py`
- `backend/app/services/status_board_read_sync.py`
- `backend/app/services/status_board_sync.py`
- `backend/app/services/intelligence_sync.py`
- `backend/tests/test_status_board_read_sync.py`
- `backend/tests/test_sync_contract_repair.py` (new)
- `google-apps-script/status_board_sync.gs`
- `google-apps-script/tests/status_board_contract.test.cjs` (new)
- `frontend/src/app/status-board/page.tsx`
- `docs/POI_SYNC_REPAIR_REVIEW.md` (new)

1. Apps Script read locator requires one exact `New RFQs` header in the first 500
   rows of `Active`, reads at most 120 section rows, preserves display strings and
   rich-text link targets, and requires a fully blank separator. Missing/duplicate
   headers, a boundary before the separator, or overflow fail closed. Reads never
   call insertion or cell-write APIs. Unknown actions cannot fall through to writes.
   Read column mapping validates the complete row-2 header contract, supporting the
   actual 15-column sheet and the original 16-column layout with Go-bys. With 15
   columns, Go-bys is empty and Notes/Submitted/Link read from M/N/O. Unknown header
   layouts fail closed. GET health exposes only protocol version/actions. Existing write layout guard and
   legacy `{secret, fields}` contract are retained.
2. Backend diagnoses the legacy read rejection without adding fields or retrying a
   write. Invalid JSON envelopes and every row are validated before cache replacement;
   malformed rows are not silently skipped. Transport error text does not echo response
   bodies or configured URLs. Valid empty snapshots remain supported.
3. Row-number relationships require a corroborating identity match. Shared URLs and
   identifiers cannot choose the first of several candidates; title/date fallback
   requires a client/location and a unique match. This affects display links only;
   no opportunity, exclusion or pursuit decision is created or changed.
4. Only fully successful ingestion advances the source's last-success timestamp.
   Total item-processing failures report failing health; partial failures remain
   degraded. Existing ingestion selection and promotion behavior is unchanged.
5. Status Board Refresh reapplies the displayed filter/search/sort controls and does
   not claim there is a previously synchronized board before the first success.
6. Status Board time formatting uses portable `%I` with a leading-zero trim,
   preserving its output on Linux and supporting Windows. Existing read-test dates
   use portable `%m/%d/%Y` instead of platform-specific unpadded directives.

## Ingestion configuration and hosting findings

These are application findings, separate from dot's daily scans. Production freshness
timestamps in the delegation are evidence supplied by the parent inspection, not
new ingestion runs performed here.

| Component | Existing behavior | Remaining limitation |
| --- | --- | --- |
| SAM.gov | Manual sync; requires `SAM_GOV_API_KEY` | No SAM job in this branch's scheduler. Do not enable a new pipeline as part of this repair. |
| APEX MyBidMatch | In-process check every 15 minutes, due after 18:00 America/Chicago; respects source enabled flag | Free-service sleep interrupts checks. A failed/morning attempt also consumes that day's existing attempt-based gate. No retry/schedule policy was changed. |
| External APEX check | `.github/workflows/scheduled-sync.yml` calls `/api/intelligence/scheduled-sync-check` using existing secret names | GitHub repository default is `main`; this workflow is absent there (read returned 404). The file on the POI branch alone cannot run on cron. Existing Actions run history and secret presence were not verified. |
| COREWORKS | Apps Script owns three-hour push trigger; manual app pull requires `COREWORKS_APPS_SCRIPT_URL` and `COREWORKS_WEBHOOK_SECRET` | Script creates/applies Gmail labels, and manual fetch invokes `mark_processed` before database item processing. Do not activate it under read-only Gmail authorization. No credential, trigger or OAuth change was made. |
| Status Board | In-process read cache tick every **10** minutes and authenticated manual refresh | Free API can sleep; no external board schedule. The 15-minute tick is ingestion, not board refresh. |

GitHub scheduled workflows run on the default branch and may be delayed/dropped:
[GitHub schedule documentation](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule).
Render Free services spin down after 15 minutes without inbound traffic:
[Render Free documentation](https://render.com/docs/free).
Paid database service does not keep the Free API process running.

Intentional-deletion exclusions across sources are an operating requirement from the
canonical Page, not a verified complete production exclusion ledger. This patch does
not infer deleted identities from missing sheet rows, restore rows, re-enable sources,
or change Submit Y/N. Existing dismissal behavior remains intact. Review exact record
effects and stable exclusion evidence before any new production ingestion run.

## Verification

- Actual `.gs` executed in Node VM with synthetic SpreadsheetApp, properties and lock
  services: **16 tests passed** after the pre-rollout column-contract correction. Tests cover shifted headers, display fields, links,
  missing Date Added, ambiguity/boundaries, empty section, authorization, unsupported
  actions, preserved legacy write contract and fail-closed shifted write layout.
- Backend offline suite: **250 passed, 237 database-dependent tests deselected**;
  includes **24 new repair tests**. One third-party Starlette/AnyIO deprecation warning.
  Existing connector/parser/scoring/scheduler unit tests were included.
- With explicit follow-up approval, downloaded the official PostgreSQL/EDB portable
  Windows 18.6 binary archive into this task workspace. Its SHA-256 matched EDB's
  published checksum: `e2246ba91d22345bc3d017586c09ede52d9df180b1eeb480f050445f1cad84e2`.
  No installer, Windows service, firewall, global PATH or production credentials.
  Disposable cluster listened only on 127.0.0.1:65432. All existing migrations and
  the repository's synthetic reference/admin/demo seed completed locally.
- Full backend suite: **486 passed, 1 failed**, one third-party deprecation warning.
  All Status Board and repair tests passed against PostgreSQL. The remaining unchanged
  `test_sdvosb_kpi_drilldown_matches_a_deterministic_nonzero_count` fails with 1 vs 2.
  It also fails identically when run from an untouched archive of deployed commit
  `88506e2`. Its Core-table bulk update leaves loaded ORM flag values stale before
  assignments; this unrelated test was not changed. This is not a wholly green suite.
  Initial missing-demo-fixture and Windows-format failures were resolved and rerun.
- Database shutdown succeeded after candidate and baseline runs; no test listener
  remained. Logs: `../pg-test-runtime/candidate-pytest.log` and
  `../pg-test-runtime/pytest.log` (baseline reproduction). Lifecycle harness:
  `../pg-test-runtime/run-tests.ps1`. No production authenticated end-to-end test ran.
- Frontend `tsc --noEmit` passed. Next.js production build passed, including lint,
  type validation and generation of 16 static pages. Initial sandbox build could not
  fetch the existing Inter font; the authorized network-enabled rerun passed without
  source or dependency-version changes. `git diff --check` passed.

Run targeted offline checks from the repository root after installing requirements
in a local virtual environment (Windows additionally needs `tzdata`):

```powershell
$env:DATABASE_URL='postgresql+psycopg://test:test@127.0.0.1:65432/poi_test'
$env:PYTHONPATH='backend'
.\.venv\Scripts\python.exe -m pytest backend/tests/test_sync_contract_repair.py -q
node --test google-apps-script/tests/status_board_contract.test.cjs
```

The broad offline run used pytest collection to deselect every test whose resolved
fixture names contain `db`; no repository test fixtures were altered. Full integration
check was subsequently completed as above. To repeat, provision a disposable local
PostgreSQL, set only its DATABASE_URL and a synthetic ADMIN_INITIAL_PASSWORD,
run `alembic upgrade head`, `python -m seed.seed` (including synthetic demos), and
`python -m pytest tests -q` from backend.
Never use production DATABASE_URL for that command or the repository seed script.

## Exact proposed deployment sequence — requires Eric's explicit approval

1. Review completed PostgreSQL/frontend checks and the baseline-reproduced test failure. Review this
   diff against the deployed base. Re-fetch the POI branch before merging; if it has
   advanced, preserve later edits, rebase/review and rerun checks. No schema change is
   required by this patch.
2. Reconfirm the already verified existing bound Apps Script deployment ID,
   published version and workbook binding to the supplied SOQ spreadsheet. Compare
   the live code with this candidate and preserve any live-only edits. Verify the
   configured backend URL targets that same `/exec` deployment; keep existing secrets
   private and unchanged. Do not create a new credential or deployment/account.
3. After approval, update the reviewed Status Board script through **Manage deployments
   → edit existing deployment → New version**, retaining its URL, execution identity,
   access and existing script property. Do not run `testSyncRow`, change sheet cells,
   or modify the COREWORKS script. Script save alone does not update `/exec`.
4. Verify GET protocol/actions, then one authenticated `action: read` request with the
   existing secret. This request must have no `fields`. Confirm section/header and
   complete rows, date display and links against a fresh read-only sheet view; do not
   hard-code today's row count as a permanent expected value. If validation fails,
   stop without changing the cache or trying a write fallback.
5. Only after explicit approval to push/deploy, publish the reviewed candidate to the
   POI deployed branch and deploy the API and frontend. Both services may auto-deploy
   on push, so approval must cover that effect. Check Render service identities:
   API `srv-dakv91dbedkc73am5i9g`, web `srv-dakv8n5bedkc73am4f90`; do not deploy legacy main.
6. Use the authenticated Status Board Refresh once. Expected writes are **only** cache
   snapshot replacement plus its sync-state timestamps/error/count. Verify successful
   time, complete row count, Submit decisions, links, filters and dashboard counts;
   confirm no opportunity or sheet records were created. Do not click Sync All,
   source Sync Now, Track/Add, or the scheduled-sync endpoint.
7. Leave ingestion schedules and source configuration unchanged during board acceptance.
   Separately review the missing default-branch APEX workflow and exact ingestion
   effects/exclusions before authorizing any workflow publication or wake-up check.
   SAM scheduling and a compliant read-only COREWORKS design remain separate decisions.

Rollback: redeploy API/frontend base `88506e2152690c916e8bb7141889a15f0e514fb1`
and, if necessary, select the previously recorded Apps Script deployment version.
There is no schema migration to reverse. Preserve cache data as last-known state;
do not roll back the database or sheet, which could erase unrelated user work.

## Remaining release blockers

- Apps Script source/version and Render URL attribution are verified; no remaining
  source-access or credential blocker. Render confirms the POI branch, deployed
  commit and Free runtime. Existing `autoDeploy=yes` makes a branch push a deployment.
- The legacy **write** locator remains row-36-bound; it will reject the present row-38
  layout. This patch repairs read synchronization only and retains that write guard.
  Do not claim Track/Add write acceptance from these read tests.
- The full suite retains one baseline-reproduced unrelated dashboard test failure.
  Live authenticated read acceptance remains outstanding and requires rollout approval.
- Fresh ingestion is not restored by this local patch. Cron publication, production
  data effects, Gmail mutation incompatibility and exclusion completeness need review.
- No source-access blocker: existing Git access worked; no new credentials were made.

## Follow-up: Track/Add effects and smallest remaining approvals

The original sheet guard rejects row 38 before `insertRowBefore` or `setValues`; the
synthetic script test verifies zero sheet writes on that path. The local candidate
retains the guard. No live write call or source activation was performed.

However, `frontend/src/app/discover/page.tsx::handleTrack` first calls
`opportunitiesApi.create`, then calls the Status Board sync endpoint.
`backend/app/services/opportunities.py::create_opportunity` commits the Opportunity,
source-item link, activity and score before the later sheet request. Consequently,
**a failed sheet insertion does not mean Track/Add was a no-op**. The app opportunity
persists. Retry/Add for an already tracked item does not create another opportunity
through that UI path, but can update its sync attempt/error state. A previously SYNCED
record short-circuits without checking whether its sheet row was intentionally deleted.
It must not be reset automatically to restore a missing row. The read repair does not
change Submit decisions, dismissal records, write-sync records or opportunity creation.

Follow-up approvals completed:

1. **Database tests:** Eric approved the official portable local PostgreSQL runtime.
   Migrations, synthetic seed and full regression run completed; database stopped.
2. **Endpoint attribution:** Eric approved existing Render sign-in and read-only URL
   inspection. Exact deployment URL match confirmed; no new credential/permission.
3. **Rollout:** Eric approved the tested candidate at 10:21 CDT. The preflight found
   a material column-contract gap; rollout paused under the explicit stop-on-risk-change
   instruction. The revised local mapping below needs review before publication.
   Do not publish a script version,
   push the auto-deployed branch, run ingestion or enable sheet writes as verification.
   The separate write-layout/exclusion issue remains blocked for operational acceptance;
   changing the constant to 38 alone would be brittle and would not establish
   deletion-preservation safety.


## Approved rollout preflight: paused before publication (10:26 CDT)

Eric approved the bounded POI read-sync rollout at 10:21 CDT, preserving hosting,
permissions, source records and ingestion configuration. The branch re-fetch still
returned deployed base `88506e2152690c916e8bb7141889a15f0e514fb1`. Both existing
Render services remained live on that base:

- API rollback deployment: `dep-dav7jbdg1s2s73dfvtl0`.
- Frontend rollback deployment: `dep-dav7jbdg1s2s73dfvtu0`.
- Apps Script rollback: existing version 3; no source save or deployment action taken.

A fresh read-only `Active!A1:P70` snapshot exposed a material issue missed by the
original synthetic fixture: the actual sheet has **15 fields**, with Notes in M,
Submitted Y/N in N and Link in O. There is no Go-bys column. The prior tested reader
would have mislabeled those values and missed links; it was not published.

The revised local reader checks the complete row-2 header sequence, including the
exact observed labels normalized only for whitespace/punctuation, and supports only
the verified 15-column layout or original 16-column Go-bys layout. It maps each field
and rich hyperlink by validated index. It never edits the sheet. Synthetic fixtures
now mirror the live header and make rich-link mocks column-sensitive; all **16**
actual-script tests pass. These include both layouts and rejection of unexpected
headers. Backend/frontend changes are unchanged from the earlier validation.

The fresh snapshot contains **23 New RFQs (rows 39-61)**, **32 Submitted RFQs
(rows 5-36)**, and the New RFQs header remains A38. New RFQs Submit values:
5 Y, 15 N, 1 question mark, 2 blank. Earlier reported 24 New RFQs is no longer the
current count; do not restore a missing item to force agreement with that old count.

Read-only database preflight fingerprint (complete row JSON, ordered by ID):

| Table | Count | MD5 comparison fingerprint |
| --- | ---: | --- |
| opportunities | 416 | c352e8bc5aa0364961fd977b1f0aae19 |
| intelligence_items | 2620 | f97af001b1234bb8a7ca184fc106be5e |
| project_clusters | 122 | 13cbc6de3263ee96429f034e55bb443d |
| status_board_syncs | 2 | d1ad9c13ed72d40b68d2ab75f67d80ae |
| intelligence_sources | 51 | 41c6cbc9e56f6e70073200d3681d904a |

Cache remains zero rows, no successful sync; last observed attempt
2026-10-06 14:44:04.787375 UTC reported Missing 'fields' object. No live refresh,
production ingestion, sheet/Gmail write, source save, Git commit/push or deployment
occurred in this rollout attempt. The explicit instruction to stop on a material
risk change is the reason for returning this revised, tested local candidate.


## Rollout continuation: automatic approval review blocker

The parent clarified that the 15-column read correction is within Eric's existing
approval; it needs no separate scope approval. Final 16 Apps Script tests passed
again, and a fresh Git fetch still resolved to deployed base 88506e2. The existing
bound script source was copied read-only and exactly matched preserved version 3
(10,680 characters).

Automatic approval review rejected pasting the tested replacement into the live
Apps Script editor because the deployment approval arrived through a delegated task.
To verify authorization, the supported read_thread tool read the originating task:
it showed the specific request to deploy the read repair to POI and its existing
Apps Script and Eric's userMessage 'Yes to POI'. The same paste was retried once
with that evidence; automatic review rejected it again because the evidence was
in tool output rather than direct user-authored text in this local task.

No alternative mutation route was attempted. A fresh editor copy after rejection
still exactly equals version 3. No source save, deployment, Git commit/push, live
refresh, ingestion, or sheet/Gmail write occurred. This is an approval-review
execution blocker, not a new technical scope request. Direct confirmation in this
local task (or equivalent trusted approval supported by the platform) is required
to unblock the consequential publication action. Both POI services remain on 88506e2.

## Direct rollout approval received

Eric successfully submitted direct approval in this task to deploy the POI board-reading repair to the existing Apps Script and POI services and verify the read-only refresh. The prior approval-attribution blocker is superseded. This runtime currently exposes no browser-control or Apps Script publishing capability; service deployment can proceed through existing Git/Render access, but script publication and authenticated UI refresh require that capability to return. No new credentials or permissions will be created.
