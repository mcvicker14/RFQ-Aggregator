# Submit choices and explicit blank clearing — review only

Not published or deployed. Current live POI and Apps Script version 5 remain unchanged.

For N/Y rows, Change opens N, Y and Blank radio choices. For blank rows, Choose
opens N and Y only. There is no text input or Other choice. Save requires a
selected different value; Cancel discards it and reopening resets selection.
Choices and Cancel disable during saving; a synchronous guard prevents duplicate
requests. Existing stale-snapshot, identity, revision, owner-role, conflict,
uncertain-write and no-retry protections remain.

Blank was not supported by the live contract. This candidate explicitly permits
the empty string in request/result schemas, API types and the Script validator.
It passes seven null skips then an empty string to the same metadata-filtered RAW
write, targeting H only. Missing/null/arbitrary values remain rejected. Cache
readback normalizes its null representation of an empty cell to an empty string
for confirmation. The existing audit records old value and new empty string;
confirmed replay remains idempotent. No new endpoint, migration, permission,
metadata assignment, row insertion, ingestion or Go/No-Go mutation is introduced.

Google documents empty-string cell clearing and null skips:
https://developers.google.com/workspace/sheets/api/reference/rest/v4/spreadsheets.values

Local QA: 46 Script tests passed, including N/Y-to-blank in both sheet schemas;
backend 510 passed, with the same one known baseline SDVOSB KPI fixture failure;
Next production build passed. Synthetic actual React/Edge tests pass for choices,
cancel/reopen, unchanged/no-choice disable, double save, real empty-string payload,
Y-to-N, blank-to-N, conflict, unconfirmed clear, stale draft and mobile layout.

Before publication, obtain scoped approval for the UI/backend/Script clear update.
Then use the retained two-fake-row fixture only: replace Code.gs and FixtureRunner.gs
with this exact candidate; run runPoiSyntheticAcceptance. Its added Y -> blank -> N
sequence must confirm that only H clears and all other cells/formulas/links remain
unchanged. No production RFQ is a test decision; retain fixture. Existing IDs need
no reassignment and no production sheet edit pause is needed for this change.

After the fixture passes, publish a new version of the SAME existing Apps Script
deployment, preserving URL/owner/audience/secret and version 5 rollback. Its added
blank support remains backward-compatible with the existing N/Y clients. Publish
the matching POI backend and frontend only after scoped approval. Keep existing
gate settings, hosting, credentials and intake unchanged. Verify health, fresh
read identities/revisions, fixed-choice UI and unchanged source snapshots/audit
count through read-only production checks. No actual clear test in production.
