/**
 * COREWORKS RFQwire mail bridge.
 *
 * Runs entirely inside the Gmail account that receives forwarded COREWORKS RFQwire
 * digest emails. This script is the ONLY thing with Gmail access anywhere in this
 * integration — the Principal Opportunity Intelligence backend holds no Gmail/Google
 * credentials of any kind. It never parses a listing itself; it only finds whole
 * forwarded messages that plausibly ARE a COREWORKS digest, does one lightweight
 * sender check, and hands the raw plaintext body to the backend, which does all the
 * real parsing in Python (see app/connectors/gmail_coreworks.py — same regex logic
 * that previously ran against Gmail API results fetched via OAuth, now fed by this
 * script instead).
 *
 * Two ways this script is used:
 *   1. PUSH (automatic): a time-driven trigger (installTrigger() below, every 3 hours)
 *      calls autoPushCoreworksMail(), which scans, POSTs anything new straight to the
 *      backend's /api/intelligence/coreworks-ingest webhook, and labels each message
 *      processed ONLY after the backend confirms it was received (HTTP 200, ok:true)
 *      — so a failed push never loses a message, it just gets retried on the next
 *      scan (scan + label are never applied speculatively).
 *   2. PULL (on demand): the backend's own "Sync Now" button calls this script's Web
 *      App /exec URL with {action: "scan"} to get new messages back directly, parses
 *      them itself, then calls back with {action: "mark_processed"} once it has fully
 *      consumed them — same safety property (label only follows confirmed success).
 *
 * SETUP (full walkthrough in the chat explanation; short version):
 *   1. From a browser signed into the Gmail account that receives the COREWORKS
 *      forwards: script.google.com > New project. Paste this whole file in
 *      (replacing the default Code.gs contents). Save.
 *   2. Project Settings (gear icon) > Script Properties > add two properties:
 *        COREWORKS_SHARED_SECRET = <a long random string you generate yourself>
 *        BACKEND_INGEST_URL = https://<your-render-backend>/api/intelligence/coreworks-ingest
 *   3. Deploy > New deployment > Web app. Execute as "Me", Who has access "Anyone".
 *      Authorize when prompted — this is Apps Script's own one-click consent screen
 *      (you approving your own script reading your own Gmail), never a Google Cloud
 *      OAuth client/consent-screen setup, and no credential of any kind leaves Google.
 *   4. Copy the resulting /exec URL into the backend's COREWORKS_APPS_SCRIPT_URL, and
 *      the SAME secret from step 2 into the backend's COREWORKS_WEBHOOK_SECRET
 *      (Render environment variables — never paste a secret into chat).
 *   5. Run installTrigger() once from the Apps Script editor's toolbar (select it in
 *      the function dropdown, click Run) to install the every-3-hours automatic push.
 *      Authorize again if prompted.
 *   6. After any future edit to this file: Deploy > Manage deployments > edit (pencil
 *      icon) > New version — editing the code alone does NOT update the live /exec
 *      endpoint (same gotcha as the Status Board script).
 *
 * VERIFIED STRUCTURE this script assumes about the forwarded emails (matches
 * app/connectors/gmail_coreworks.py's own module docstring, built from two real
 * forwarded COREWORKS emails): the Gmail ENVELOPE sender is always the forwarder
 * (never RFQwire@dbacoreworks.com), so sender confirmation here — and, independently
 * and authoritatively, again in Python — is done by looking for the embedded
 * "From: ... <...@dbacoreworks.com>" (or "Ralph Fontcuberta") line inside the
 * forwarded body text, never the envelope From address.
 */

// ---- Configuration -------------------------------------------------------------

// Same Gmail search syntax app/connectors/gmail_coreworks.py's now-retired
// GMAIL_SEARCH_QUERY constant used — kept here since this script is what actually
// searches now. Deliberately does not use `from:` alone, for the reason above.
var BASE_SEARCH_QUERY = '(subject:COREWORKS OR subject:RFQwire OR "dbacoreworks.com")';
var PROCESSED_LABEL_NAME = "COREWORKS-Processed";
var MAX_MESSAGES_PER_SCAN = 50;
// Matches DEFAULT_SINCE_DAYS in backend/app/services/intelligence_sync.py — both the
// backend's on-demand pull and this script's own automatic push bound their Gmail
// search to the same window; the PROCESSED_LABEL_NAME exclusion is what actually
// prevents re-sending, this is only a sanity bound on how far back a search ever looks.
var AUTO_PUSH_LOOKBACK_DAYS = 30;

// Loose, defense-in-depth pre-filter — the real, authoritative confirmation happens in
// Python against the same embedded header block (see _find_original_sender_and_body in
// app/connectors/gmail_coreworks.py). This only needs to avoid sending obviously
// unrelated mail; it deliberately does not replicate that function's full parsing.
var SENDER_CONFIRM_PATTERN = /From:[^\n]*?(dbacoreworks\.com|Ralph\s+Fontcuberta)/i;


// ---- Entry points ---------------------------------------------------------------

function doPost(e) {
  var response;
  try {
    response = handlePost(e);
  } catch (err) {
    response = { ok: false, error: "internal_error", message: String(err) };
  }
  return jsonOutput(response);
}

function doGet(e) {
  return jsonOutput({ ok: true, message: "COREWORKS RFQwire mail bridge is live. POST {action:'scan'} to use it." });
}

function handlePost(e) {
  var body;
  try {
    body = JSON.parse(e.postData.contents);
  } catch (err) {
    return { ok: false, error: "bad_request", message: "Request body was not valid JSON." };
  }

  var expectedSecret = getSharedSecret_();
  if (!expectedSecret) {
    return { ok: false, error: "not_configured", message: "COREWORKS_SHARED_SECRET script property is not set." };
  }
  if (!body || body.secret !== expectedSecret) {
    return { ok: false, error: "unauthorized", message: "Missing or incorrect secret." };
  }

  if (body.action === "scan") {
    var since = body.since ? new Date(body.since + "T00:00:00Z") : daysAgo_(AUTO_PUSH_LOOKBACK_DAYS);
    var messages = scanAndCollect_(since);
    return { ok: true, messages: messages };
  }
  if (body.action === "mark_processed") {
    var ids = Array.isArray(body.message_ids) ? body.message_ids : [];
    var marked = markProcessedMessageIds_(ids);
    return { ok: true, marked: marked };
  }
  return { ok: false, error: "bad_request", message: "Unknown or missing 'action' — expected 'scan' or 'mark_processed'." };
}


// ---- Automatic push (time-driven trigger) ----------------------------------------

/**
 * Installed by installTrigger() to run every 3 hours. Finds new COREWORKS messages,
 * pushes them straight to the backend without waiting to be asked, and labels each
 * message processed only once the backend has confirmed it received them — see the
 * module docstring's safety note. Safe to run as often as you like; a run that finds
 * nothing new is a normal, frequent, silent no-op.
 */
function autoPushCoreworksMail() {
  var backendUrl = PropertiesService.getScriptProperties().getProperty("BACKEND_INGEST_URL");
  var secret = getSharedSecret_();
  if (!backendUrl || !secret) {
    Logger.log("autoPushCoreworksMail: BACKEND_INGEST_URL or COREWORKS_SHARED_SECRET not set — skipping.");
    return;
  }

  var messages = scanAndCollect_(daysAgo_(AUTO_PUSH_LOOKBACK_DAYS));
  if (messages.length === 0) {
    return;
  }

  var response = UrlFetchApp.fetch(backendUrl, {
    method: "post",
    contentType: "application/json",
    payload: JSON.stringify({ secret: secret, messages: messages }),
    muteHttpExceptions: true,
    followRedirects: true,
  });

  if (response.getResponseCode() !== 200) {
    Logger.log("autoPushCoreworksMail: backend ingest failed (HTTP " + response.getResponseCode() + "): " +
      response.getContentText().slice(0, 500) + " — leaving messages unlabeled for retry.");
    return;
  }
  var parsed;
  try {
    parsed = JSON.parse(response.getContentText());
  } catch (err) {
    Logger.log("autoPushCoreworksMail: backend response was not valid JSON — leaving messages unlabeled for retry.");
    return;
  }
  if (!parsed.ok) {
    Logger.log("autoPushCoreworksMail: backend reported failure — leaving messages unlabeled for retry. " +
      JSON.stringify(parsed));
    return;
  }

  var ids = messages.map(function (m) { return m.id; });
  markProcessedMessageIds_(ids);
  Logger.log("autoPushCoreworksMail: pushed " + messages.length + " message(s), sync_run_id=" + parsed.sync_run_id);
}

/** Run once from the editor to install the every-3-hours automatic push trigger. */
function installTrigger() {
  var existing = ScriptApp.getProjectTriggers().filter(function (t) {
    return t.getHandlerFunction() === "autoPushCoreworksMail";
  });
  existing.forEach(function (t) { ScriptApp.deleteTrigger(t); });
  ScriptApp.newTrigger("autoPushCoreworksMail").timeBased().everyHours(3).create();
  Logger.log("Installed: autoPushCoreworksMail every 3 hours.");
}


// ---- Shared scan/label logic ------------------------------------------------------

/**
 * Searches Gmail for COREWORKS-plausible, not-yet-processed messages received on/after
 * `since`, keeps only the ones whose body passes the lightweight sender pre-check, and
 * returns {"id", "body_text", "internal_date_ms"} for each — never labels anything
 * (labeling only ever follows confirmed downstream success; see callers).
 */
function scanAndCollect_(since) {
  var query = BASE_SEARCH_QUERY + ' -label:"' + PROCESSED_LABEL_NAME + '" after:' + formatDateForSearch_(since);
  var threads = GmailApp.search(query, 0, MAX_MESSAGES_PER_SCAN);

  var results = [];
  for (var t = 0; t < threads.length && results.length < MAX_MESSAGES_PER_SCAN; t++) {
    var messages = threads[t].getMessages();
    for (var m = 0; m < messages.length && results.length < MAX_MESSAGES_PER_SCAN; m++) {
      var message = messages[m];
      var bodyText = message.getPlainBody();
      if (!SENDER_CONFIRM_PATTERN.test(bodyText)) {
        continue; // not a plausible COREWORKS forward — never sent, never labeled
      }
      results.push({
        id: message.getId(),
        body_text: bodyText,
        internal_date_ms: message.getDate().getTime(),
      });
    }
  }
  return results;
}

/**
 * Labels each given message's THREAD as processed — Gmail's Apps Script API only
 * exposes labeling at thread granularity, not per-message. In the overwhelmingly
 * common case (each forward is its own thread, confirmed against real COREWORKS
 * emails) this is exactly message-level. The rare case where one thread holds two+
 * distinct COREWORKS forwards (e.g. someone replied-forward instead of starting a new
 * message) still can't lose data: a message not included in this call's `ids` keeps
 * its thread off the processed label, so the WHOLE thread — including any
 * already-handled message in it — is simply found and safely (idempotently)
 * re-sent next scan, never silently dropped.
 */
function markProcessedMessageIds_(ids) {
  var label = getOrCreateProcessedLabel_();
  var marked = 0;
  for (var i = 0; i < ids.length; i++) {
    try {
      var message = GmailApp.getMessageById(ids[i]);
      if (message) {
        message.getThread().addLabel(label);
        marked++;
      }
    } catch (err) {
      Logger.log("markProcessedMessageIds_: failed to label message " + ids[i] + ": " + err);
    }
  }
  return marked;
}

function getOrCreateProcessedLabel_() {
  var label = GmailApp.getUserLabelByName(PROCESSED_LABEL_NAME);
  return label || GmailApp.createLabel(PROCESSED_LABEL_NAME);
}

function getSharedSecret_() {
  return PropertiesService.getScriptProperties().getProperty("COREWORKS_SHARED_SECRET");
}

function daysAgo_(days) {
  var d = new Date();
  d.setDate(d.getDate() - days);
  return d;
}

function formatDateForSearch_(date) {
  return Utilities.formatDate(date, "America/Chicago", "yyyy/MM/dd");
}

function jsonOutput(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj)).setMimeType(ContentService.MimeType.JSON);
}


/**
 * Manual smoke test — select this function in the Apps Script editor's toolbar
 * dropdown and click Run. Scans without labeling or pushing anything anywhere, and
 * logs what it found, so you can confirm Gmail search/permissions work before wiring
 * up the backend at all. View > Logs (or Executions) afterward.
 */
function testScan() {
  var messages = scanAndCollect_(daysAgo_(AUTO_PUSH_LOOKBACK_DAYS));
  Logger.log("Found " + messages.length + " candidate message(s):");
  messages.forEach(function (m) {
    Logger.log(" - id=" + m.id + " received=" + new Date(m.internal_date_ms) + " bodyPreview=" +
      m.body_text.slice(0, 120).replace(/\n/g, " "));
  });
}
