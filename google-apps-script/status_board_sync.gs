/**
 * SOQ Status Board webhook.
 *
 * Two request shapes, both POSTs:
 *   - {secret, fields} or {secret, action:"write", fields} — one "Track + Add to
 *     Status Board" click (or retry) from the backend; inserts exactly one row into
 *     this spreadsheet's New RFQs section. The no-"action" shape is the original,
 *     still-live caller (status_board_webhook_client.py) — treated identically to
 *     action:"write" so that existing integration keeps working unchanged.
 *   - {secret, action:"read"} — returns every current New RFQs row (including
 *     existing manual rows never touched by this app) as JSON, for the backend's own
 *     Status Board page to display and poll. Read-only: never writes anything.
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
  if (action !== "read" && action !== "write") {
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

  var rows = block.existingRows.map(function (dataRow, i) {
    var row = { sheet_row_number: block.headerRow + 1 + i };
    COLUMN_ORDER.forEach(function (key) {
      var value = dataRow[block.columns[key]];
      row[key] = value === null || value === undefined ? "" : String(value);
    });
    // Display text may be "click here"; preserve the actual hyperlink separately.
    var richLink = block.links[i][0];
    row.link = (richLink && richLink.getLinkUrl()) || row.link;
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
        ok: true, headerRow: start, columns: columns, existingRows: values.slice(start, i),
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
