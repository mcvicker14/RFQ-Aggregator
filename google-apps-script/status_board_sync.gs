/**
 * SOQ Status Board webhook.
 *
 * Receives one POST per "Track + Add to Status Board" click (or retry) from the
 * Principal Opportunity Intelligence backend and inserts exactly one row into this
 * spreadsheet's New RFQs section. This script is the *only* thing that ever reads or
 * writes the sheet — the backend holds no Google credentials of any kind and only
 * knows this script's Web App URL and a shared secret.
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
 * VERIFIED SHEET STRUCTURE this script assumes (matches backend/app/services/
 * status_board_sync.py's own assumptions about the same sheet):
 *   - tab "Sheet1"
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
 */

var SHEET_TAB_NAME = "Sheet1";
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
  return jsonOutput({ ok: true, message: "SOQ Status Board webhook is live. POST a row to sync it." });
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

  var fields = body.fields;
  if (!fields || typeof fields !== "object") {
    return { ok: false, error: "bad_request", message: "Missing 'fields' object." };
  }

  // Serializes concurrent doPost runs against this sheet so two near-simultaneous
  // requests can never both compute the same insertion point and both write there —
  // the second one waits, then re-reads live state (and will correctly see the
  // first one's row as a duplicate if it's for the same opportunity).
  var lock = LockService.getScriptLock();
  var gotLock = lock.tryLock(10000);
  if (!gotLock) {
    return { ok: false, error: "locked", message: "Another Status Board sync is in progress — safe to retry." };
  }
  try {
    return syncRow(fields);
  } finally {
    lock.releaseLock();
  }
}

function syncRow(fields) {
  var row = COLUMN_ORDER.map(function (key) {
    var value = fields[key];
    return value === null || value === undefined ? "" : String(value);
  });

  var sheet = SpreadsheetApp.getActiveSpreadsheet().getSheetByName(SHEET_TAB_NAME);
  if (!sheet) {
    return { ok: false, error: "structure_error", message: "Tab '" + SHEET_TAB_NAME + "' was not found in this spreadsheet." };
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

  var existingRows = dataRows.slice(0, targetOffset);
  var targetRow = NEW_RFQS_HEADER_ROW + 1 + targetOffset;

  var duplicateRow = findExistingRow(existingRows, fields);
  if (duplicateRow !== null) {
    return { ok: true, status: "duplicate", row: duplicateRow };
  }

  sheet.insertRowBefore(targetRow);
  sheet.getRange(targetRow, 1, 1, row.length).setValues([row]);
  return { ok: true, status: "inserted", row: targetRow };
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
