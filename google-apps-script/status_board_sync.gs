/**
 * SOQ Status Board webhook.
 *
 * Two request shapes, both POSTs:
 *   - {secret, fields} or {secret, action:"write", fields} — one "Track + Add to
 *     Status Board" click (or retry) from the backend; inserts exactly one row into
 *     this spreadsheet's New RFQs section. The no-"action" shape is the original,
 *     still-live caller (status_board_webhook_client.py) — treated identically to
 *     action:"write" so that existing integration keeps working unchanged.
 *   - {secret, action:"read"} - returns every current New RFQs row (including
 *     existing manual rows never touched by this app) as JSON, for the backend's own
 *     Status Board page to display and poll. Read-only: never writes anything.
 *   - {secret, action:"set_submit", request_id, source_record_id,
 *      expected_revision, expected_submit, value:"Y"|"N"|""} - optional owner-driven
 *     edit of H only. Disabled until separate reviewed activation. Requires row
 *     developer metadata and the Advanced Sheets service. No credential changes
 *     or service/scope activation is performed by this source file.
 * This script is the *only* thing that ever reads or writes the sheet — the backend
 * holds no Google credentials of any kind and only knows this script's Web App URL
 * and a shared secret.
 *
 * SETUP: paste this into Extensions > Apps Script, opened FROM WITHIN the actual SOQ
 * Status Board spreadsheet (not a standalone script project) — that binding is what
 * makes SpreadsheetApp.getActiveSpreadsheet() below resolve to the right file no
 * matter who calls the deployed web app. See the chat explanation for the full
 * deploy/configure walkthrough; the short version:
 *   1. Project Settings > Script Properties > add STATUS_BOARD_WEBHOOK_SECRET.
 *   2. Deploy > New deployment > Web app > Execute as "Me", Who has access "Anyone".
 *   3. Copy the resulting /exec URL into the backend's STATUS_BOARD_WEBHOOK_URL, and
 *      the same secret from step 1 into STATUS_BOARD_WEBHOOK_SECRET.
 *   4. After any future edit to this file: Deploy > Manage deployments > edit (pencil
 *      icon) > New version — editing the code alone does NOT update the live /exec
 *      endpoint.
 *
 * WRITE-PATH SHEET STRUCTURE this script assumes (matches backend/app/services/
 * status_board_sync.py's own assumptions about the same sheet):
 *   - tab "Active" (STATUS_BOARD_SHEET_NAME below) — the workbook's other tab,
 *     "2026 Archive", is a separate sheet this script never opens, reads, or writes;
 *     getSheetByName(STATUS_BOARD_SHEET_NAME) can only ever resolve to "Active"
 *   - "New RFQs" header text in column A of row 36
 *   - existing New RFQs data rows immediately below that
 *   - exactly one blank row marking the end of New RFQs
 *   - the separate Grants mini-table (and its own sentinel/"do not fill" row)
 *     starting a few rows further down
 * This script only ever inserts a row *before* the first blank row it finds after row
 * 36 (never appends to the bottom of the sheet) and refuses to write at all — reporting
 * a structure_error instead — if it finds "Grant Title" or "ADD LINES ABOVE" before it
 * finds that blank row, or doesn't find a blank row within a generous search window.
 * If the sheet's structure ever changes, fix it there and re-verify before trusting
 * this script again; it will never silently guess a new insertion point.
 * The read path independently locates one exact New RFQs header (bounded to 500
 * rows) because submitted rows above it move the section. It never inserts rows.
 */

// The exact tab to write to — explicit, not the default-sheet fallback, so a rename
// or an extra tab (this workbook also has a separate "2026 Archive" tab) can never
// silently redirect a write. Production incident: this was "Sheet1" (a guess at the
// default name) and didn't match the real tab, failing every sync with
// structure_error: Tab 'Sheet1' was not found.
var STATUS_BOARD_SHEET_NAME = "Active";
var NEW_RFQS_HEADER_ROW = 36;
var NEW_RFQS_HEADER_TEXT = "New RFQs";
var SEARCH_WINDOW_ROWS = 120;
var SECTION_BOUNDARY_MARKERS = ["Grant Title", "ADD LINES ABOVE"];

// Same keys, same order, as FIELD_KEYS in backend/app/services/status_board_sync.py —
// if you ever change one side, change the other to match, or rows will land in the
// wrong columns.
var COLUMN_ORDER = [
  "date_added", "due_date", "due_time", "client_project_location", "rfq_title",
  "digital_option", "standard_form", "submit_y_n", "date_submitted",
  "importance", "quality", "probability", "go_bys", "notes", "submitted_y_n", "link"
];
var LINK_KEY = "link";
var TITLE_KEY = "rfq_title";
var CLIENT_KEY = "client_project_location";
var POI_RECORD_KEY = "POI_RECORD_ID_V1";


function doPost(e) {
  var response;
  try {
    response = handlePost(e);
  } catch (err) {
    response = { ok: false, error: "internal_error", message: String(err) };
  }
  return jsonOutput(response);
}

// Lets you sanity-check the deployment itself (open the /exec URL in a browser) before
// wiring up the backend at all.
function doGet(e) {
  return jsonOutput({ ok: true, protocol_version: 2, actions: ["read", "write"] });
}

function handlePost(e) {
  var body;
  try {
    body = JSON.parse(e.postData.contents);
  } catch (err) {
    return { ok: false, error: "bad_request", message: "Request body was not valid JSON." };
  }

  var expectedSecret = PropertiesService.getScriptProperties().getProperty("STATUS_BOARD_WEBHOOK_SECRET");
  if (!expectedSecret) {
    return { ok: false, error: "not_configured", message: "STATUS_BOARD_WEBHOOK_SECRET script property is not set." };
  }
  if (!body || body.secret !== expectedSecret) {
    return { ok: false, error: "unauthorized", message: "Missing or incorrect secret." };
  }

  var action = body.action || "write"; // no action given = write, for the existing deployed caller
  if (action !== "read" && action !== "write" && action !== "set_submit" && action !== "reconcile") {
    return { ok: false, error: "bad_request", message: "Unsupported action." };
  }

  // Serializes concurrent doPost runs against this sheet so two near-simultaneous
  // requests can never both compute the same insertion point and both write there —
  // the second one waits, then re-reads live state (and will correctly see the
  // first one's row as a duplicate if it's for the same opportunity). A read takes
  // the same lock too, so it can never observe a write that's only half-applied.
  var lock = LockService.getScriptLock();
  var gotLock = lock.tryLock(10000);
  if (!gotLock) {
    return { ok: false, error: "locked", message: "Another Status Board sync is in progress — safe to retry." };
  }
  try {
    if (action === "read") {
      return readNewRfqsRows_();
    }
    if (action === "reconcile") {
      if (Object.keys(body).some(function (key) { return key !== "secret" && key !== "action"; }))
        return { ok: false, error: "bad_request", message: "Reconciliation accepts no row values or decisions." };
      return reconcileNewRfqsRows_();
    }
    if (action === "set_submit") return setSubmit_(body);
    var fields = body.fields;
    if (!fields || typeof fields !== "object") {
      return { ok: false, error: "bad_request", message: "Missing 'fields' object." };
    }
    return syncRow(fields);
  } finally {
    lock.releaseLock();
  }
}

/**
 * Locates the New RFQs block (header row, existing data rows, the blank-row
 * insertion point) exactly once — shared by syncRow (write) and readNewRfqsRows_
 * (read) so the two paths can never disagree about where New RFQs starts, ends, or
 * what counts as a structural problem. Returns { ok: true, sheet, existingRows,
 * targetOffset, targetRow } on success, or the same { ok: false, error:
 * "structure_error", message } shape syncRow has always returned on any structural
 * problem — unchanged from before this was extracted, including never writing past
 * what this search verified safe.
 */
function findNewRfqsBlock_() {
  var sheet = SpreadsheetApp.getActiveSpreadsheet().getSheetByName(STATUS_BOARD_SHEET_NAME);
  if (!sheet) {
    return { ok: false, error: "structure_error", message: "Tab '" + STATUS_BOARD_SHEET_NAME + "' was not found in this spreadsheet." };
  }

  var maxRows = sheet.getMaxRows();
  var windowHeight = Math.min(SEARCH_WINDOW_ROWS + 1, maxRows - NEW_RFQS_HEADER_ROW + 1);
  if (windowHeight < 1) {
    return { ok: false, error: "structure_error", message: "Sheet has fewer rows than expected before row " + NEW_RFQS_HEADER_ROW + "." };
  }
  var windowRows = sheet.getRange(NEW_RFQS_HEADER_ROW, 1, windowHeight, COLUMN_ORDER.length).getValues();

  var header = windowRows[0];
  if (String(header[0] || "").trim() !== NEW_RFQS_HEADER_TEXT) {
    return {
      ok: false, error: "structure_error",
      message: "Row " + NEW_RFQS_HEADER_ROW + " does not read '" + NEW_RFQS_HEADER_TEXT + "' — refusing to guess where New RFQs is."
    };
  }

  var dataRows = windowRows.slice(1);
  var targetOffset = -1;
  for (var i = 0; i < dataRows.length; i++) {
    var marker = boundaryMarkerIn(dataRows[i]);
    if (marker) {
      return {
        ok: false, error: "structure_error",
        message: "Found '" + marker + "' at row " + (NEW_RFQS_HEADER_ROW + 1 + i) +
          " before finding a blank row after New RFQs — refusing to write."
      };
    }
    if (isBlankRow(dataRows[i])) {
      targetOffset = i;
      break;
    }
  }
  if (targetOffset === -1) {
    return {
      ok: false, error: "structure_error",
      message: "No blank row found within " + SEARCH_WINDOW_ROWS + " rows after row " + NEW_RFQS_HEADER_ROW +
        " — refusing to write past what was verified safe."
    };
  }

  return {
    ok: true,
    sheet: sheet,
    existingRows: dataRows.slice(0, targetOffset),
    targetOffset: targetOffset,
    targetRow: NEW_RFQS_HEADER_ROW + 1 + targetOffset,
  };
}

function syncRow(fields) {
  var row = COLUMN_ORDER.map(function (key) {
    var value = fields[key];
    return value === null || value === undefined ? "" : String(value);
  });

  var block = findNewRfqsBlock_();
  if (!block.ok) {
    return block;
  }

  var duplicateRow = findExistingRow(block.existingRows, fields);
  if (duplicateRow !== null) {
    return { ok: true, status: "duplicate", row: duplicateRow };
  }

  block.sheet.insertRowBefore(block.targetRow);
  block.sheet.getRange(block.targetRow, 1, 1, row.length).setValues([row]);
  return { ok: true, status: "inserted", row: block.targetRow };
}

/**
 * Returns every current New RFQs row — app-originated AND pre-existing manual rows
 * alike, no distinction made here; the backend decides app-vs-manual display itself
 * from its own StatusBoardSync records (see app/services/status_board_read_sync.py).
 * Read-only: never writes, never labels, never reorders anything.
 */
function readNewRfqsRows_() {
  var block = findReadBlock_();
  if (!block.ok) {
    return block;
  }

  var identities = recordIdentities_(block.sheet);
  var rows = block.existingRows.map(function (dataRow, i) {
    var row = { sheet_row_number: block.headerRow + 1 + i };
    COLUMN_ORDER.forEach(function (key) {
      var value = dataRow[block.columns[key]];
      row[key] = value === null || value === undefined ? "" : String(value);
    });
    // Display text may be "click here"; preserve the actual hyperlink separately.
    var richLink = block.links[i][0];
    row.link = (richLink && richLink.getLinkUrl()) || row.link;
    var identity = identities[row.sheet_row_number];
    row.source_record_id = identity ? identity.value : null;
    row.source_revision = identity ? revision_(row, block.sheet.getRange(row.sheet_row_number, 1, 1, 16).getFormulas()[0]) : null;
    return row;
  });
  return { ok: true, protocol_version: 2, rows: rows };
}

// Read-only locator: submitted rows above New RFQs move the section down over time.
// Require one exact header in a bounded window; never infer an insertion location.
// The legacy write locator above deliberately retains its original strict guard.
function findReadBlock_() {
  var sheet = SpreadsheetApp.getActiveSpreadsheet().getSheetByName(STATUS_BOARD_SHEET_NAME);
  if (!sheet) return { ok: false, error: "structure_error", message: "Active tab not found." };
  var height = Math.min(sheet.getMaxRows(), 500);
  var values = sheet.getRange(1, 1, height, COLUMN_ORDER.length).getDisplayValues();
  var columns = readColumns_(values[1] || []);
  if (!columns) {
    return { ok: false, error: "structure_error", message: "Unrecognized Status Board column headers in row 2." };
  }
  var headers = [];
  values.forEach(function (row, i) {
    if (String(row[0]).trim() === NEW_RFQS_HEADER_TEXT) headers.push(i);
  });
  if (headers.length !== 1) {
    return { ok: false, error: "structure_error", message: "Expected exactly one New RFQs header within first 500 rows." };
  }
  var start = headers[0] + 1;
  for (var i = start; i < Math.min(values.length, start + SEARCH_WINDOW_ROWS); i++) {
    if (boundaryMarkerIn(values[i])) {
      return { ok: false, error: "structure_error", message: "Section boundary reached before blank separator." };
    }
    if (values[i].every(function (cell) { return String(cell).trim() === ""; })) {
      return {
        ok: true, sheet: sheet, headerRow: start, columns: columns, existingRows: values.slice(start, i),
        links: i === start ? [] : sheet.getRange(start + 1, columns[LINK_KEY] + 1, i - start, 1).getRichTextValues()
      };
    }
  }
  return { ok: false, error: "structure_error", message: "No blank separator within bounded New RFQs read window." };
}

// Verified live sheet has Notes/Submitted/Link in M/N/O, with no Go-bys.
// Accept only the complete known 15- or 16-column header contract; never guess
// from data, shift values into the wrong fields, or alter the legacy write path.
function readColumns_(header) {
  var labels = ["dateadded", "duedate", "duetimecst", "clientprojectlocation",
    "rfqtitle", "digitaloption", "standardform", "submityorn", "datesubmitted",
    "importance13", "quality13", "probability13", "gobys", "notes", "submittedyn", "link"];
  var normalized = header.map(function (cell) {
    return String(cell).toLowerCase().replace(/[^a-z0-9]/g, "");
  });
  var withGoBys = normalized[12] === "gobys";
  var keys = COLUMN_ORDER.filter(function (key) { return withGoBys || key !== "go_bys"; });
  var expected = labels.filter(function (label) { return withGoBys || label !== "gobys"; });
  if (expected.some(function (label, i) { return normalized[i] !== label; }) ||
      normalized.slice(expected.length).some(function (label) { return label !== ""; })) return null;
  var columns = {};
  keys.forEach(function (key, i) { columns[key] = i; });
  return columns;
}

// Metadata belongs to the sheet row, rather than a cached row number. Reads never
// create it. Duplicate/copied identities are deliberately unusable for editing.
function recordIdentities_(sheet) {
  var result = {}, values = {}, all = [];
  if (!sheet.createDeveloperMetadataFinder) return result;
  sheet.createDeveloperMetadataFinder().withKey(POI_RECORD_KEY).find().forEach(function (m) {
    var range = m.getLocation().getRow();
    var value = m.getValue();
    if (!range || !/^[a-f0-9-]{36}$/.test(value)) return;
    var number = range.getRow();
    all.push({ number: number, value: value, id: m.getId() });
    values[value] = (values[value] || 0) + 1;
  });
  all.forEach(function (m) {
    if (values[m.value] !== 1 || Object.prototype.hasOwnProperty.call(result, m.number)) result[m.number] = null;
    else result[m.number] = m;
  });
  return result;
}

function revision_(row, formulas) {
  var canonical = COLUMN_ORDER.map(function (key) { return row[key] || ""; });
  canonical.push(formulas);
  return Utilities.computeDigest(Utilities.DigestAlgorithm.SHA_256, JSON.stringify(canonical), Utilities.Charset.UTF_8)
    .map(function (b) { return ((b + 256) % 256).toString(16).padStart(2, "0"); }).join("");
}

// New action is isolated from Track + Add. Requires reviewed activation and the
// Advanced Sheets service; never falls back to a positional or whole-row write.
function setSubmit_(body) {
  if (PropertiesService.getScriptProperties().getProperty("POI_SUBMIT_EDITS_ENABLED") !== "true" || typeof Sheets === "undefined")
    return { ok: false, error: "needs_configuration", message: "Submit editing is not enabled." };
  var allowed = ["secret", "action", "request_id", "source_record_id", "expected_revision", "expected_submit", "value"];
  if (Object.keys(body).some(function (key) { return allowed.indexOf(key) < 0; }) ||
      !/^[a-f0-9-]{36}$/.test(body.source_record_id || "") || !/^[a-f0-9-]{36}$/.test(body.request_id || "") ||
      !/^[a-f0-9]{64}$/.test(body.expected_revision || "") || typeof body.expected_submit !== "string" ||
      (body.value !== "Y" && body.value !== "N" && body.value !== ""))
    return { ok: false, error: "bad_request", message: "Only an explicit Y, N or blank Submit choice is supported." };
  var before = readNewRfqsRows_();
  if (!before.ok) return before;
  var matches = before.rows.filter(function (r) { return r.source_record_id === body.source_record_id; });
  if (matches.length !== 1) return editConflict_();
  var row = matches[0];
  if (row.source_revision !== body.expected_revision || row.submit_y_n !== body.expected_submit ||
      /^Y/i.test(row.submitted_y_n.trim())) return editConflict_();
  var sheet = SpreadsheetApp.getActiveSpreadsheet().getSheetByName(STATUS_BOARD_SHEET_NAME);
  var cell = sheet.getRange(row.sheet_row_number, 8, 1, 1);
  if (cell.getFormulas()[0][0]) return editConflict_();
  var formulas = sheet.getRange(row.sheet_row_number, 1, 1, 16).getFormulas()[0];
  if (revision_(row, formulas) !== body.expected_revision) return editConflict_();
  var identity = recordIdentities_(sheet)[row.sheet_row_number];
  if (!identity || identity.value !== body.source_record_id) return editConflict_();
  var block = findReadBlock_();
  if (!block.ok || row.sheet_row_number <= block.headerRow || row.sheet_row_number > block.headerRow + block.existingRows.length)
    return editConflict_();
  // Google resolves the immutable metadata ID AND exact verified location at
  // write time. A moved/deleted row cannot cause a positional replacement write.
  // Nulls are skipped, so H is the ONLY cell changed; RAW prevents formulas.
  // Google offers no atomic old-value CAS: concurrent human edits in the small
  // read/write window remain possible. Readback detects differences, never rolls
  // back someone else's work, and reports uncertainty instead of silently retrying.
  var updated = Sheets.Spreadsheets.Values.batchUpdateByDataFilter({
    valueInputOption: "RAW",
    data: [{ dataFilter: { developerMetadataLookup: { metadataId: identity.id,
      metadataLocation: { dimensionRange: { sheetId: sheet.getSheetId(), dimension: "ROWS",
        startIndex: row.sheet_row_number - 1, endIndex: row.sheet_row_number } },
      locationMatchingStrategy: "EXACT_LOCATION" } },
      majorDimension: "ROWS", values: [[null, null, null, null, null, null, null, body.value]] }]
  }, SpreadsheetApp.getActiveSpreadsheet().getId());
  if (updated.totalUpdatedCells !== 1) return { ok: false, error: "uncertain", message: "Refresh and inspect the sheet before trying again." };
  SpreadsheetApp.flush();
  var after = readNewRfqsRows_();
  var expectedAfter = Object.assign({}, row, { submit_y_n: body.value });
  var checked = after.ok ? after.rows.filter(function (r) { return r.source_record_id === body.source_record_id; }) : [];
  if (checked.length !== 1 || checked[0].submit_y_n !== body.value || checked[0].source_revision !== revision_(expectedAfter, formulas) ||
      COLUMN_ORDER.some(function (key) { return key !== "submit_y_n" && checked[0][key] !== row[key]; }))
    return { ok: false, error: "uncertain", message: "Concurrent sheet changes detected. Refresh and inspect before trying again." };
  return { ok: true, status: "confirmed", source_record_id: body.source_record_id,
    request_id: body.request_id, value: body.value, source_revision: checked[0].source_revision };
}

function editConflict_() {
  return { ok: false, error: "conflict", message: "The sheet row changed or is no longer editable. Refresh and review it." };
}

// Owner setup and the authenticated scheduled reconciliation share ONE writer.
// Reads and explicit Submit edits never create metadata or replay decisions.
function preparePoiSubmitIdentities() {
  var lock = LockService.getScriptLock();
  if (!lock.tryLock(10000)) throw new Error("Another sync is running.");
  try {
    var result = ensurePoiSubmitIdentities_();
    if (!result.ok) throw new Error(result.message);
    return result;
  } finally { lock.releaseLock(); }
}

function reconcileNewRfqsRows_() {
  var prepared = ensurePoiSubmitIdentities_();
  if (!prepared.ok) return prepared;
  var result = readNewRfqsRows_();
  if (result.ok && result.rows.some(function (row) { return !row.source_record_id || !row.source_revision; }))
    return { ok: false, error: "conflict", message: "New RFQs changed during reconciliation; retry from the current sheet." };
  if (result.ok) result.identities_added = prepared.identities_added;
  return result;
}

// Strict inventory includes Archive so copied/malformed identities cannot be
// silently accepted or overwritten. No metadata is deleted, repaired or reused.
function strictPoiIdentityInventory_() {
  var spreadsheet = SpreadsheetApp.getActiveSpreadsheet();
  var searched = Sheets.Spreadsheets.DeveloperMetadata.search({ dataFilters: [
    { developerMetadataLookup: { metadataKey: POI_RECORD_KEY } }
  ] }, spreadsheet.getId());
  var rows = {}, values = {}, ids = {}, entries = [];
  (searched.matchedDeveloperMetadata || []).forEach(function (match) {
    var metadata = match.developerMetadata, location = metadata && metadata.location;
    var range = location && location.dimensionRange;
    if (!metadata || metadata.metadataKey !== POI_RECORD_KEY ||
        !/^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/.test(metadata.metadataValue || "") ||
        !range || range.dimension !== "ROWS" || !Number.isInteger(range.sheetId) ||
        !Number.isInteger(range.startIndex) || range.startIndex < 0 || range.endIndex !== range.startIndex + 1 ||
        !Number.isInteger(metadata.metadataId) || metadata.metadataId < 0)
      throw new Error("Malformed POI identity metadata; owner review required.");
    var key = range.sheetId + ":" + range.startIndex;
    if (rows[key] || values[metadata.metadataValue] || ids[metadata.metadataId])
      throw new Error("Ambiguous POI identity metadata; owner review required.");
    rows[key] = metadata;
    values[metadata.metadataValue] = true;
    ids[metadata.metadataId] = true;
    entries.push(metadata);
  });
  entries.sort(function (left, right) { return left.metadataId - right.metadataId; });
  return { rows: rows, entries: entries };
}

function poiSourceSnapshot_(block) {
  var height = block.existingRows.length;
  return JSON.stringify({ header: block.headerRow, columns: block.columns, values: block.existingRows,
    formulas: height ? block.sheet.getRange(block.headerRow + 1, 1, height, 16).getFormulas() : [],
    links: block.links.map(function (row) { return row.map(function (link) { return link && link.getLinkUrl(); }); }) });
}

function poiIdentitySnapshot_(inventory) {
  // Advanced-service response objects have no stable property enumeration order.
  // Compare the complete identity semantics, not incidental JSON key ordering.
  return JSON.stringify(inventory.entries.map(function (metadata) {
    var range = metadata.location.dimensionRange;
    return [metadata.metadataId, metadata.metadataKey, metadata.metadataValue,
      metadata.visibility || null, range.sheetId, range.dimension, range.startIndex, range.endIndex];
  }));
}

// Tentative IDs are not exposed to POI until the whole operation is confirmed.
// If a human moves/inserts a row during the batch, remove ONLY UUIDs generated
// by this invocation (known absent from the preflight inventory). Never remove
// any pre-existing identity, cell, decision or record.
function discardTentativePoiIdentities_(created) {
  if (!created.length) return;
  var values = created.map(function (entry) { return entry.value; });
  var filters = values.map(function (value) { return { developerMetadataLookup: {
    metadataKey: POI_RECORD_KEY, metadataValue: value
  } }; });
  var spreadsheetId = SpreadsheetApp.getActiveSpreadsheet().getId();
  var result = Sheets.Spreadsheets.DeveloperMetadata.search({ dataFilters: filters }, spreadsheetId);
  var requests = [], seen = {};
  (result.matchedDeveloperMetadata || []).forEach(function (match) {
    var metadata = match.developerMetadata;
    if (!metadata || metadata.metadataKey !== POI_RECORD_KEY || values.indexOf(metadata.metadataValue) < 0 ||
        !Number.isInteger(metadata.metadataId)) throw new Error("Tentative identity cleanup could not be verified.");
    if (seen[metadata.metadataId]) return;
    seen[metadata.metadataId] = true;
    requests.push({ deleteDeveloperMetadata: { dataFilter: { developerMetadataLookup: {
      metadataId: metadata.metadataId, metadataKey: POI_RECORD_KEY, metadataValue: metadata.metadataValue
    } } } });
  });
  if (requests.length) Sheets.Spreadsheets.batchUpdate({ requests: requests }, spreadsheetId);
  if ((Sheets.Spreadsheets.DeveloperMetadata.search({ dataFilters: filters }, spreadsheetId).matchedDeveloperMetadata || []).length)
    throw new Error("Tentative identity cleanup was not confirmed.");
}

function ensurePoiSubmitIdentities_() {
  if (typeof Sheets === "undefined" || !Sheets.Spreadsheets.DeveloperMetadata || !Sheets.Spreadsheets.batchUpdate)
    return { ok: false, error: "needs_configuration", message: "Existing Advanced Sheets service is required for metadata reconciliation." };
  var wrote = false, created = [];
  try {
    var block = findReadBlock_();
    if (!block.ok) return block;
    var before = poiSourceSnapshot_(block), inventory = strictPoiIdentityInventory_();
    var sheetId = block.sheet.getSheetId(), requests = [];
    var existingValues = inventory.entries.map(function (metadata) { return metadata.metadataValue; });
    block.existingRows.forEach(function (_, i) {
      var index = block.headerRow + i;
      if (inventory.rows[sheetId + ":" + index]) return;
      var value = Utilities.getUuid();
      if (existingValues.indexOf(value) >= 0) throw new Error("Duplicate generated identity; retry without changes.");
      existingValues.push(value); created.push({ index: index, value: value });
      requests.push({ createDeveloperMetadata: { developerMetadata: {
        metadataKey: POI_RECORD_KEY, metadataValue: value, visibility: "DOCUMENT",
        location: { dimensionRange: { sheetId: sheetId, dimension: "ROWS", startIndex: index, endIndex: index + 1 } }
      } } });
    });
    // ScriptLock excludes competing app writers. It does NOT exclude a human
    // editing the sheet; revalidate before one atomic metadata-only batch, then
    // verify afterward. A detected race stops caching, never rewrites cells.
    var preflight = findReadBlock_();
    if (!preflight.ok || poiSourceSnapshot_(preflight) !== before)
      return { ok: false, error: "conflict", stage: "source_preflight", message: "Sheet values, formulas, links or section changed before reconciliation; retry." };
    if (poiIdentitySnapshot_(strictPoiIdentityInventory_()) !== poiIdentitySnapshot_(inventory))
      return { ok: false, error: "conflict", stage: "identity_preflight", message: "Identity metadata changed before reconciliation; retry." };
    if (requests.length) {
      wrote = true; // A transport failure may occur after Google accepted the batch.
      Sheets.Spreadsheets.batchUpdate({ requests: requests }, SpreadsheetApp.getActiveSpreadsheet().getId());
    }
    SpreadsheetApp.flush();
    var after = findReadBlock_(), checked = strictPoiIdentityInventory_();
    if (!after.ok || poiSourceSnapshot_(after) !== before ||
        inventory.entries.some(function (metadata) {
          var range = metadata.location.dimensionRange;
          var actual = checked.rows[range.sheetId + ":" + range.startIndex];
          return !actual || actual.metadataId !== metadata.metadataId || actual.metadataValue !== metadata.metadataValue;
        }) || created.some(function (entry) {
          var actual = checked.rows[sheetId + ":" + entry.index];
          return !actual || actual.metadataValue !== entry.value;
        })) {
      discardTentativePoiIdentities_(created);
      return { ok: false, error: "conflict", message: "Concurrent sheet change detected; inspect metadata before retrying. No cells were overwritten." };
    }
    return { ok: true, identities_added: created.length };
  } catch (error) {
    if (wrote) {
      try {
        discardTentativePoiIdentities_(created);
        return { ok: false, error: "conflict", message: "Reconciliation changed concurrently or was interrupted; tentative IDs were discarded. Retry from the current sheet." };
      } catch (cleanupError) {
        return { ok: false, error: "uncertain", message: "Tentative metadata cleanup was not confirmed; owner inspection required. No cells were overwritten." };
      }
    }
    return { ok: false, error: "identity_error", message: "Identity validation failed before changes; inspect malformed or ambiguous POI metadata." };
  }
}

function isBlankRow(row) {
  return !row[0] || String(row[0]).trim() === "";
}

function boundaryMarkerIn(row) {
  var joined = row.filter(function (cell) { return cell; }).join(" ");
  for (var i = 0; i < SECTION_BOUNDARY_MARKERS.length; i++) {
    if (joined.indexOf(SECTION_BOUNDARY_MARKERS[i]) !== -1) return SECTION_BOUNDARY_MARKERS[i];
  }
  return null;
}

// Link match is authoritative when available (the strongest identifier the sheet
// itself can carry); Title+Client is the fallback for a row with no source URL.
function findExistingRow(existingRows, fields) {
  var linkIdx = COLUMN_ORDER.indexOf(LINK_KEY);
  var titleIdx = COLUMN_ORDER.indexOf(TITLE_KEY);
  var clientIdx = COLUMN_ORDER.indexOf(CLIENT_KEY);

  var link = String(fields[LINK_KEY] || "").trim();
  var title = String(fields[TITLE_KEY] || "").trim().toLowerCase();
  var client = String(fields[CLIENT_KEY] || "").trim().toLowerCase();

  for (var i = 0; i < existingRows.length; i++) {
    var r = existingRows[i];
    var rowLink = String(r[linkIdx] || "").trim();
    if (link && rowLink && rowLink === link) {
      return NEW_RFQS_HEADER_ROW + 1 + i;
    }
    if (!link) {
      var rowTitle = String(r[titleIdx] || "").trim().toLowerCase();
      var rowClient = String(r[clientIdx] || "").trim().toLowerCase();
      if (title && rowTitle === title && rowClient === client) {
        return NEW_RFQS_HEADER_ROW + 1 + i;
      }
    }
  }
  return null;
}

function jsonOutput(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj)).setMimeType(ContentService.MimeType.JSON);
}

/**
 * Manual smoke test — select this function in the Apps Script editor's toolbar
 * dropdown and click Run. Inserts one throwaway test row (or reports a duplicate),
 * without needing the backend or a network call, so you can confirm the insertion
 * logic and sheet permissions work before wiring up Render at all. Check the New RFQs
 * section afterward, then delete the test row.
 */
function testSyncRow() {
  var result = syncRow({
    date_added: Utilities.formatDate(new Date(), "America/Chicago", "M/d/yyyy"),
    due_date: "",
    due_time: "",
    client_project_location: "Apps Script Test",
    rfq_title: "TEST ROW — safe to delete",
    digital_option: "",
    standard_form: "",
    submit_y_n: "",
    date_submitted: "",
    importance: "",
    quality: "",
    probability: "",
    go_bys: "",
    notes: "Inserted by testSyncRow() — delete this row.",
    submitted_y_n: "",
    link: "https://example.com/apps-script-test"
  });
  Logger.log(JSON.stringify(result));
}

/**
 * Manual smoke test for the read path — select and Run from the editor's toolbar.
 * Logs every current New RFQs row without needing the backend or a network call.
 */
function testReadNewRfqs() {
  var result = readNewRfqsRows_();
  Logger.log(JSON.stringify(result));
}
