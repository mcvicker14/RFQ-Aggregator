/** Fixture ONLY. Add as a separate file in the synthetic sheet's bound project.
 * Never add this runner to production. No Web App deployment is necessary.
 * Stop at any new Google permission prompt for separate owner approval.
 */
function runPoiSyntheticAcceptance() {
  var ss = SpreadsheetApp.getActiveSpreadsheet();
  if (!ss || ss.getId() !== '1VrBeOJp9H7J3GJub9y2UzIOeUna53yU4M_MeJALz098')
    throw new Error('This runner is restricted to the approved synthetic fixture.');
  if (typeof Sheets === 'undefined') throw new Error('Advanced Sheets service is not enabled.');
  var sheet = ss.getSheetByName('Active');
  var report = [];
  function check(value, label) { if (!value) throw new Error('FAIL: ' + label); report.push(label); }
  function snapshot() {
    SpreadsheetApp.flush();
    var range = sheet.getRange(1, 1, sheet.getMaxRows(), sheet.getMaxColumns());
    return { values: range.getValues(), formulas: range.getFormulas(),
      links: range.getRichTextValues().map(function (row) { return row.map(function (v) { return v ? v.getLinkUrl() : null; }); }),
      backgrounds: range.getBackgrounds(), formats: range.getNumberFormats(),
      notes: range.getNotes() };
  }
  function same(before, label, number, value) {
    if (number) before.values[number - 1][7] = value;
    check(JSON.stringify(before) === JSON.stringify(snapshot()), label);
  }
  var props = PropertiesService.getScriptProperties();
  // Synthetic value in the fixture project only. Never read/copy production secret.
  props.setProperty('STATUS_BOARD_WEBHOOK_SECRET', 'poi-synthetic-fixture-only');
  props.setProperty('POI_SUBMIT_EDITS_ENABLED', 'true');
  function post(body) {
    body.secret = 'poi-synthetic-fixture-only';
    return handlePost({ postData: { contents: JSON.stringify(body) } });
  }
  function rows() {
    var read = post({ action: 'read' });
    if (!read.ok || !Array.isArray(read.rows)) throw new Error('Fixture read failed.');
    return read.rows;
  }
  function first() { return rows().filter(function (r) { return r.rfq_title === 'SYNTHETIC POI RFQ A'; })[0]; }
  function edit(row, value) { return { action: 'set_submit', request_id: Utilities.getUuid(),
    source_record_id: row.source_record_id, expected_revision: row.source_revision,
    expected_submit: row.submit_y_n, value: value }; }
  function rejected(body, label) {
    var before = snapshot(), result = post(body);
    check(result.ok === false && result.error === 'conflict', label);
    same(before, label + ' changes no cells');
  }
  try {
    var before = snapshot();
    check(rows().length === 2 && rows().every(function (r) { return /^SYNTHETIC POI RFQ [AB]$/.test(r.rfq_title); }), 'exactly two fake RFQs');
    preparePoiSubmitIdentities(); same(before, 'metadata setup changes no cells/formulas/links/formatting');
    check(rows().every(function (r) { return r.source_record_id && /^[a-f0-9]{64}$/.test(r.source_revision); }), 'both identities and revisions available');
    ['Y', 'N'].forEach(function (value) {
      var row = first(), prior = snapshot(), result = post(edit(row, value));
      check(result.ok === true && result.status === 'confirmed' && result.value === value, 'confirmed ' + value);
      same(prior, 'only H changes for ' + value, row.sheet_row_number, value);
    });
    var conflict = edit(first(), 'Y'); conflict.expected_submit = 'Y'; rejected(conflict, 'old value conflict');
    var row = first(), h = sheet.getRange(row.sheet_row_number, 8);
    h.setFormula('="N"'); SpreadsheetApp.flush();
    rejected(edit(first(), 'Y'), 'formula H rejected'); h.setValue('N');
    row = first(); var move = edit(row, 'Y');
    sheet.moveRows(sheet.getRange(41, 1, 1, sheet.getMaxColumns()), 40); SpreadsheetApp.flush();
    before = snapshot(); var moved = first(), result = post(move);
    check(moved.sheet_row_number === 41 && result.ok === true && result.status === 'confirmed', 'reordered row resolved by identity');
    same(before, 'reordered edit changes only intended H', 41, 'Y');
    sheet.moveRows(sheet.getRange(41, 1, 1, sheet.getMaxColumns()), 40); SpreadsheetApp.flush();
    first(); sheet.getRange(40, 8).setValue('N');
    row = first(); var otherRow = rows().filter(function (r) { return r.rfq_title === 'SYNTHETIC POI RFQ B'; })[0];
    sheet.getRange(otherRow.sheet_row_number, 1, 1, sheet.getMaxColumns()).addDeveloperMetadata(POI_RECORD_KEY, row.source_record_id);
    rejected(edit(row, 'Y'), 'duplicate identity rejected');
    sheet.createDeveloperMetadataFinder().withKey(POI_RECORD_KEY).find().forEach(function (m) {
      if (m.getValue() === row.source_record_id && m.getLocation().getRow().getRow() === otherRow.sheet_row_number) m.remove();
    });
    row = first(); var deleted = edit(row, 'Y');
    var stored = sheet.getRange(row.sheet_row_number, 1, 1, sheet.getMaxColumns()).getValues();
    sheet.deleteRows(row.sheet_row_number, 1); SpreadsheetApp.flush();
    rejected(deleted, 'deleted identity rejected');
    sheet.insertRowsBefore(40, 1); sheet.getRange(40, 1, 1, sheet.getMaxColumns()).setValues(stored);
    SpreadsheetApp.flush(); rejected(deleted, 'identical recreated row does not reuse old identity');
    preparePoiSubmitIdentities();
    row = first(); var submitted = edit(row, 'Y'); sheet.getRange(row.sheet_row_number, 14).setValue('Y');
    rejected(submitted, 'submitted row rejected'); sheet.getRange(row.sheet_row_number, 14).setValue('');
    check(rows().length === 2, 'two fake RFQs retained');
    check(sheet.getRange(41, 12).getFormula() === '=1+1', 'other-row formula retained');
    Logger.log(JSON.stringify({ ok: true, fixture_id: ss.getId(), checks: report, production_writes: 0 }));
    return { ok: true, checks: report };
  } finally {
    // Fixture is retained. Disable its write gate after testing, including failure.
    props.setProperty('POI_SUBMIT_EDITS_ENABLED', 'false');
  }
}
