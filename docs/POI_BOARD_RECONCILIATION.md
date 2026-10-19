# POI board reconciliation

Reconcile the current Google Sheets New RFQs block at 09:00, 12:00, 16:00 and
20:00 America/Chicago daily. Python `ZoneInfo` handles daylight saving changes.
Delayed checks reconcile the latest due slot once, rather than replaying missed
snapshots. A successful slot and its cache replacement commit together under the
existing PostgreSQL advisory lock. Failures retain the previous cache, do not
complete the slot, and can retry after five minutes.

The dedicated `/api/status-board/reconciliation-check` endpoint uses
`STATUS_BOARD_RECONCILIATION_SECRET` and accepts no fields or decisions. This is a
dedicated board-only credential, not the intake scheduler credential. It runs no APEX,
COREWORKS or SAM intake. Their routes, schedules and workflow remain unchanged.
The existing ten-minute board process job checks due slots when reconciliation
is enabled; otherwise it retains its former read-only behavior. Existing visible
browser refreshes and explicit Y/N/blank saves remain unchanged and immediate.

`poi-board-reconciliation.yml` belongs on GitHub's default branch as well as the
reviewed POI branch. It calls the deployed POI API, not the legacy main app. Its
UTC windows cover both Central offsets, then its Python guard admits only the
four intended local hours. Four checks within each due hour provide retries.
The database makes repeated checks idempotent. The job targets the existing public
POI API URL and uses repository secret `STATUS_BOARD_RECONCILIATION_SECRET`, matching
the API environment key of the same name. Inspection found no existing scheduler
credential. Owner approval and secure entry are required for this new, narrowly
scoped credential; implementation work alone does not create or activate it.
Missing configuration fails before sending a request. The repository is public,
so standard GitHub-hosted Actions runs do not
introduce a new paid service. Do not configure billing, a new account or scope.

GitHub can delay or drop scheduled runs and Free Render can cold-start. This is
four daily target windows with retry and catch-up, not guaranteed exact-minute
delivery. If an entire window is missed, the next successful window imports the
current sheet. A separate reminder does not execute this application operation.

## One source metadata writer

Owner setup and the authenticated `reconcile` Apps Script action share
`ensurePoiSubmitIdentities_()`, under ScriptLock. It validates all POI-key metadata
across the workbook, rejecting malformed locations/UUIDs, duplicate UUIDs and
multiple identities on one row. It assigns UUIDs only to missing current New RFQs
rows in one atomic metadata-only batch. It never writes cells, decisions,
formulas, links or formatting; existing identities are never removed or replaced.
Read-only `read` calls do not assign IDs. The existing Advanced Sheets service is
required; no additional OAuth scope is intended.

ScriptLock does not exclude human Sheets edits. Before/after snapshots compare
section boundaries, displayed values, formulas and links. A detected race stops
cache acceptance. Only newly generated, still-unpublished tentative UUIDs from
that invocation may be discarded so a later retry can use the current structure.
Pre-existing metadata, human edits and all records remain intact. If tentative
cleanup cannot be confirmed, report `uncertain` and require owner inspection;
never guess, restore cells, reuse old IDs or overwrite a decision. This is
conflict detection and safe retry, not atomic compare-and-swap with human edits.

Immediate Submit edits retain their immutable metadata target, optimistic full
revision, expected prior value, audit and independent readback. Scheduled jobs
receive no cached decisions and never reconcile Y/N by last-writer-wins.

## Activation and verification

1. Complete the separately authorized browser repair and obtain the coordinator's
   publication release. Do not overlap live Apps Script mutations.
2. Pass synthetic Apps Script contracts, local PostgreSQL tests and migration
   checks. Test DST boundaries, 23-to-26 replacement, stable IDs, retries, locks,
   malformed metadata, row moves and preservation of immediate decision edits.
3. Obtain explicit approval for one new board-only credential after reporting the
   existing scheduler credential is absent. The owner securely enters the same value
   as `STATUS_BOARD_RECONCILIATION_SECRET` in the existing Render API environment
   and GitHub repository Actions secrets. It authorizes only the dedicated board
   due-slot check; it cannot authorize intake or Submit edits. Never enter it in
   chat, source code or logs. Do not create a token, account, OAuth scope or paid
   service. Keep reconciliation disabled until all publication gates pass.
4. Publish the reviewed source as a new version of the same existing Apps Script
   deployment, preserving execution identity, audience, URL and existing properties.
   Verify existing Advanced Sheets access suffices without a permission prompt.
5. Fast-forward only the deployed POI branch from the verified current head. Its
   existing Render deployment runs the additive migration. Leave the reconciliation
   flag false until exact deploy commit and Script version are confirmed.
6. Publish only the reviewed board workflow file to default `main`, preserving all
   unrelated main files and the existing intake workflow. Verify Actions is enabled
   and the workflow can use the existing configuration. Do not merge POI application
   code into main or change the repository's default branch.
7. Merge the single API environment key `STATUS_BOARD_RECONCILIATION_ENABLED=true`
   without fetching/replacing other environment values. Verify its activation deploy
   and run the supported board workflow once. Compare current source snapshots and
   all cache identities/revisions/fields; inspect slot completion and job logs.
8. Observe the next scheduled slot without a desktop/browser dependency. Until that
   run is observed, describe publication/activation separately from scheduled proof.

Rollback: disable the reconciliation flag and board workflow, preserving metadata,
decisions, records and additive migration columns. Restore the prior Script version
and application commit if needed; never roll back source data or strip existing IDs.

GitHub schedule behavior:
https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule
Google batch atomicity and concurrent collaboration caveat:
https://developers.google.com/workspace/sheets/api/reference/rest/v4/spreadsheets/batchUpdate
# October 19 identity compatibility repair

Advanced Sheets metadata search can omit `dimensionRange.sheetId` for sheet zero.
The strict inventory now resolves only an absent field through the exact native
DeveloperMetadata ID, corroborating its key, UUID and single-row range before
using the native sheet ID. Explicit invalid values, mismatches, duplicate IDs,
duplicate values and ambiguous row assignments still fail closed. The response
is normalized in memory; existing metadata is never rewritten for this case.

The scheduled workflow sends one request per check and requires HTTP 200,
`reason=completed`, no error and a timezone-aware slot at least as recent as the
latest due Central-time slot. Failed, disabled, busy, malformed and stale results
fail the job. A curl retry can no longer hide a first failure behind a later
retry-wait HTTP 200. The existing later scheduled checks provide retry/backoff.

Local validation: `node --test google-apps-script/tests/status_board_submit.test.cjs`
(57 tests), and `python google-apps-script/tests/test_board_workflow.py` (6 tests).
The existing Google synthetic fixture passed all 15 reconciliation checks and
25 Submit checks on October 19, 2026 at 16:01:49 and 16:04:13 UTC respectively.
Production backfill/deployment evidence is retained in the existing canonical
software status Page, not in a second tracker. Preserve the prior deployment as
the rollback target; disable the existing reconciliation flag/workflow first if
verification fails. Never undo successful identity assignments merely to roll
back code, and never replay cached decisions into the Sheet.
