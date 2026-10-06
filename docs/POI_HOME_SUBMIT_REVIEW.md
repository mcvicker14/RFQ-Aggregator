# POI homepage and owner Submit editing — local review

**Not deployed.** The live board-reading repair remains Apps Script version 4 and
POI production commit `60de69ddfc52cb42acb46c5b84f89271a8c49af8`. The local branch
is `fix/poi-sync-review`; its pre-feature commit `93520b19aa85e750d797ad0e295e34c176bb2800`
has the same tree as that production commit. No production sheet, source ingestion,
Go/No-Go, deletion exclusion, deployment, hosting, OAuth, or credentials changed.

## Result

The homepage starts with the existing New RFQs Status Board, search, named filters,
and a focused five-column view. Mobile shows the same records as a compact list
with Submit controls visible. All 16 raw fields remain accessible through All
columns. A short attention list follows. Every previous dashboard metric, chart,
priority opportunity, early signal, and full attention list remains accessible
under “Pipeline overview, intelligence and reports”; existing navigation remains.
The standalone Status Board uses the same workspace and preserves filter links.

Owner typing Y or N creates one explicit Save request. Only Administrator and
Executive roles can submit decisions; BD+ retains its existing read-refresh right.
This changes the sheet's Submit? H cell only. It does not create/restore/delete an
opportunity, alter Submit's submitted flag, or make a separate Go/No-Go decision.
All other fields, formulas, hyperlink cells, Notes, and row formatting are untouched.

## Freshness

While an authorized BD+ user has the page visible, it requests a read-only sheet
refresh every 60 seconds and on focus. Requests coalesce within 45 seconds. A
PostgreSQL transaction advisory lock serializes cache replacement across tabs,
workers, and the existing scheduler. Other roles poll the existing cache only.
Polling pauses during a decision draft or while the tab is hidden. Read failures
retain the previous cache and show an error. Snapshots older than two minutes,
unconfirmed writes, and source errors disable editing until review/refresh.

**This is near-real-time while open, not guaranteed real-time.** With the page
closed, the existing 10-minute in-process read timer runs only while the Free API
is awake. Free hosting cold starts, network latency, and Google quotas still apply.
There is no new persistent trigger, external scheduler, paid service, or competing
ingestion pipeline. The existing ingestion configuration/scheduling is unchanged.

## Write protection and boundaries

Two activation gates default OFF: backend `STATUS_BOARD_SUBMIT_EDITS_ENABLED` and
Apps Script property `POI_SUBMIT_EDITS_ENABLED`. Existing v4 read behavior and the
legacy Track + Add path remain compatible. The latter's original strict row-36
guard is unchanged; this feature must not be used to activate/retry Track + Add.

Reads never create identity metadata. An owner-only, manually run
`preparePoiSubmitIdentities` helper can assign invisible `POI_RECORD_ID_V1` UUID
metadata to the **current** New RFQs rows after separate approval. It changes no
cells. Rows without metadata, copied/duplicate identities, formula Submit cells,
missing/archived/submitted rows, unknown headers, and ambiguous layouts fail closed.
New human-entered rows need that reviewed setup before POI can edit them.

Requests contain the native identity, full row/formula SHA-256 revision, exact
previous Submit string, explicit Y/N, and a unique request ID. The script checks
the live identity/revision/previous value within New RFQs, then uses the Advanced
Sheets API's metadata-ID filter constrained to that exact single-row location on
Active. Google resolves both constraints at mutation time. A reorder before
preflight resolves correctly; a move after preflight rejects without a write.
The immutable identity prevents writing another record at the cached row number.
RAW input and seven skipped null cells target H only. Afterward the script verifies
the full row and formulas; the backend performs an independent complete read.
Success is acknowledged only if both agree. Detected conflicts or uncertainty
stay visible; no whole-row rewrite, insert, rollback of human changes, or automatic
mutation retry occurs. A durable `status_board_edits` audit records actor, old/new
values, expected revision, request identity, and confirmed/conflict/uncertain state.
Replaying a confirmed request returns its historical acknowledgement without a
second write; pending/uncertain or altered requests never replay.

**Remaining concurrency limit:** Google Sheets has no atomic old-value compare and
swap. Script locks serialize script requests, not human sheet edits. A human H edit
between preflight and mutation can be overwritten without being distinguishable
afterward. A simultaneous section rearrangement can invalidate the preflight
section boundary. Identity filtering prevents positional writes to a replacement
RFQ and limits normal archive moves, but cannot provide an absolute concurrency
guarantee for arbitrary human edits. Production writes stay disabled pending
explicit owner review of this limitation and the service/permission setup below.
No “conflict-free real-time two-way sync” claim is warranted.

The metadata/null-write behavior follows Google's primary documentation:
[metadata filters](https://developers.google.com/workspace/sheets/api/reference/rest/v4/DataFilter),
[metadata-addressed writes](https://developers.google.com/workspace/sheets/api/reference/rest/v4/spreadsheets.values/batchUpdateByDataFilter),
[null inputs are skipped](https://developers.google.com/workspace/sheets/api/reference/rest/v4/spreadsheets.values),
[Apps Script row metadata](https://developers.google.com/apps-script/reference/spreadsheet/range).
The new Google API path is tested synthetically, not against a live Google fixture.

## Validation

- PostgreSQL full suite: **508 passed, 1 failed**. The only failure is the previously
  reproduced baseline `test_sdvosb_kpi_drilldown_matches_a_deterministic_nonzero_count`
  (expected 2, actual 1). Its stale ORM/bulk-update fixture behavior was not changed.
  Includes actual migration, durable audit, RBAC/validation, replay protection,
  rejected/stale/deleted/ambiguous/submitted records, independent readback, timeout,
  coalescing, and cross-connection advisory-lock checks. Disposable loopback PG
  stopped afterward; zero test listeners remain.
- Actual Apps Script source in Node VM: **40 passed** (16 existing read/legacy tests,
  24 new owner-edit tests). Covers both known schemas, H-only writes, reordering
  before the write and rejection of movement during the write, deletion/recreation,
  movement out of section/into Archive,
  duplicate IDs, formulas, concurrent Notes/formula changes, malformed requests,
  activation gates, and read-without-metadata-mutation.
- Actual React/Next UI in installed Edge with intercepted synthetic API data:
  desktop/mobile prominence, collapsed-feature access, full columns, search,
  filter preservation, lowercase typing normalized to Y, invalid input disabled,
  narrow payload and confirmation, persistent conflict/no retry, stale disablement,
  visible polling, draft/hidden-tab polling pause, no horizontal page overflow,
  and no browser exceptions pass. No production login or sheet mutation used.
- Production Next build passes; final build result recorded with the review bundle.
  Before screenshot uses the exact previous homepage source at `60de69d`, on a
  temporary local route removed before final build. Screenshots use synthetic data;
  local dev Google-font fetch was restricted and used the fallback font.
- `git diff --check` passes. No AGENTS.md or repository-specific skill was found.

Screenshots are local in the task's `poi-ui-artifacts` folder:
`home-before-desktop.png`, `home-after-desktop.png`, `home-after-mobile.png`.
Library upload was attempted with the current Library helper; its host reported
`Library prepare_uploads is not available`. No screenshot was uploaded by that
attempt. The local screenshots remain reviewable.

## Exact rollout plan — approval required, not executed

1. Review this candidate and screenshots, the baseline test limitation, the
   concurrency limitation, and optional write activation. Authorize the specific
   new publication separately from the already deployed read repair.
2. Verify remote POI branch still heads at `60de69ddfc52cb42acb46c5b84f89271a8c49af8`.
   Publish the reviewed candidate tree as a non-force child of that exact commit
   to `claude/principal-opportunity-intelligence-jwitkf`; stop/re-review if changed.
   Existing Render auto-deploy handles API `srv-dakv91dbedkc73am5i9g` and frontend
   `srv-dakv8n5bedkc73am4f90` in workspace `tea-d4av3ahr0fns73ej8dmg`.
   The unchanged backend Docker command runs `alembic upgrade head`, then
   `python -m seed.seed`, then uvicorn at container start. Verify `ENV=production`
   and migration `7a8b9c0d1e2f` succeeds; production seed skips sample data. Do not
   apply the repository Blueprint (its old DB plan does not reflect the live paid
   DB). Keep both write gates OFF. No plans, branches, hosting tiers, or schedules
   change. The prominent homepage and read refresh can ship separately with writes
   still disabled.
3. If owner approves the optional write path, review current Apps Script scopes
   and enable its Advanced Sheets service in the **existing** project only. If
   Google requests broader scopes/authorization, stop for the owner's explicit
   approval; do not create tokens, accounts, credentials, or unattended permissions.
   Validate the metadata-addressed API against an owner-approved isolated Google
   test fixture first. The local mock tests do not replace that integration check.
4. Publish this exact reviewed `status_board_sync.gs` as a new version of the
   existing version-4 deployment, preserving deployment ID, execute-as owner,
   audience, webhook URL, and secret. Keep version 4 for rollback. Do not create
   a second script, a new webhook, or an onEdit/time trigger.
5. For identity setup, have the owner coordinate a short edit pause on the real
   sheet. Capture exact current Active and Archive cell/formula/link snapshots.
   With approved metadata-only effects, run `preparePoiSubmitIdentities` once.
   Verify cells/formulas/links are unchanged, UUID identities are unique, and
   current rows match the sheet. Do not restore the earlier count of 24; the last
   original repair verification had 23 current New RFQs and 32 Submitted above it.
6. Turn `POI_SUBMIT_EDITS_ENABLED=true` and backend
   `STATUS_BOARD_SUBMIT_EDITS_ENABLED=true` on only after steps 3–5 succeed and
   the owner accepts the stated concurrency limit. Existing API env update may
   redeploy/restart; verify exact candidate commit and service health afterward.
7. Verify production **reads only**: homepage/board cache matches fresh source,
   current filters are retained, while-open refresh timestamp advances, and
   failed read behavior remains truthful. Confirm sheet/pipeline fingerprints
   unchanged. Do not run production ingestion, Track + Add, or live Y/N test
   writes. A future owner's real Submit action or expressly approved disposable
   production fixture is a separate bounded authorization.

Rollback: turn both write gates OFF first; return the existing Apps Script
deployment to version 4 and Render API/frontend to the recorded `60de69d` deploys
(`dep-db2kphff3r2c73b9glq0`, `dep-db2kphff3r2c73b9gln0`). Retain additive columns,
audit history, and source metadata; old code ignores them. Do not downgrade/drop
audit data or revert human sheet decisions. Source metadata creates no active
trigger or automatic mutation.
