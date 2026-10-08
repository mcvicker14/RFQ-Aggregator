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
    ['Y', '', 'N'].forEach(function (value) {
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
    sheet.getRange(otherRow.sheet_row_number + ':' + otherRow.sheet_row_number).addDeveloperMetadata(POI_RECORD_KEY, row.source_record_id);
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

/** Existing synthetic project ONLY. Exercises the actual Google metadata API. */
function runPoiSyntheticReconciliationAcceptance() {
  var ss = SpreadsheetApp.getActiveSpreadsheet();
  if (!ss || ss.getId() !== '1VrBeOJp9H7J3GJub9y2UzIOeUna53yU4M_MeJALz098')
    throw new Error('This runner is restricted to the approved synthetic fixture.');
  var sheet = ss.getSheetByName('Active'), report = [], createdRow = null;
  function check(value, label) { if (!value) throw new Error('FAIL: ' + label); report.push(label); }
  function snapshot() {
    SpreadsheetApp.flush();
    var range = sheet.getRange(1, 1, sheet.getMaxRows(), sheet.getMaxColumns());
    return JSON.stringify({ values: range.getValues(), formulas: range.getFormulas(),
      links: range.getRichTextValues().map(function (row) { return row.map(function (v) { return v ? v.getLinkUrl() : null; }); }),
      backgrounds: range.getBackgrounds(), formats: range.getNumberFormats(), notes: range.getNotes() });
  }
  PropertiesService.getScriptProperties().setProperty('STATUS_BOARD_WEBHOOK_SECRET', 'poi-synthetic-fixture-only');
  function post(body) {
    body.secret = 'poi-synthetic-fixture-only';
    return handlePost({ postData: { contents: JSON.stringify(body) } });
  }
  var initial = post({ action: 'read' }), original = snapshot();
  check(initial.ok && initial.rows.length === 2 && initial.rows.every(function (row) {
    return /^SYNTHETIC POI RFQ [AB]$/.test(row.rfq_title) && row.source_record_id;
  }), 'exactly two identified synthetic RFQs');
  var originalIds = {};
  initial.rows.forEach(function (row) { originalIds[row.rfq_title] = row.source_record_id; });
  try {
    var block = findReadBlock_();
    if (!block.ok) throw new Error('Fixture section could not be verified.');
    createdRow = block.headerRow + block.existingRows.length + 1;
    sheet.insertRowsBefore(createdRow, 1);
    sheet.getRange(createdRow, 1, 1, 16).setValues([
      ['', '11/4/2026', '2:00 PM', 'Synthetic manual agency', 'SYNTHETIC POI RFQ C', '', '', 'Y', '', '', '', '', 'Retain manual notes', '', 'https://example.invalid/manual-c', '']
    ]);
    sheet.getRange(createdRow, 11).setFormula('=1+1');
    sheet.getRange(createdRow + ':' + createdRow).addDeveloperMetadata(POI_RECORD_KEY, 'malformed-fixture-only');
    var before = snapshot(), invalid = post({ action: 'reconcile' });
    check(invalid.ok === false && invalid.error === 'identity_error', 'malformed metadata fails before assignment');
    check(snapshot() === before, 'rejection preserves all fixture cells');
    sheet.createDeveloperMetadataFinder().withKey(POI_RECORD_KEY).find().forEach(function (metadata) {
      if (metadata.getValue() === 'malformed-fixture-only') metadata.remove();
    });
    before = snapshot();
    var result = post({ action: 'reconcile' });
    check(result.ok && result.identities_added === 1 && result.rows.length === 3, 'one manual row receives exactly one identity: ' +
      JSON.stringify({ ok: result.ok, error: result.error, stage: result.stage, message: result.message,
        identities_added: result.identities_added, row_count: result.rows && result.rows.length }));
    check(snapshot() === before, 'assignment preserves values formulas links formatting and decisions');
    check(result.rows.every(function (row) { return row.source_record_id && /^[a-f0-9]{64}$/.test(row.source_revision); }), 'all three IDs and revisions available');
    check(result.rows.filter(function (row) { return originalIds[row.rfq_title]; }).every(function (row) {
      return row.source_record_id === originalIds[row.rfq_title];
    }), 'pre-existing IDs preserved');
    var manual = result.rows.filter(function (row) { return row.rfq_title === 'SYNTHETIC POI RFQ C'; })[0];
    check(manual.submit_y_n === 'Y' && manual.link === 'https://example.invalid/manual-c', 'manual decision and link preserved');
    result = post({ action: 'reconcile' });
    check(result.ok && result.identities_added === 0, 'second reconciliation is idempotent');
    check(snapshot() === before, 'idempotent retry changes no cells');
    check(post({ action: 'reconcile', value: 'N' }).error === 'bad_request', 'cached decisions are forbidden');
    sheet.moveRows(sheet.getRange(createdRow, 1, 1, sheet.getMaxColumns()), block.headerRow + 1);
    createdRow = block.headerRow + 1; SpreadsheetApp.flush(); before = snapshot();
    result = post({ action: 'reconcile' });
    check(result.ok && result.identities_added === 0, 'row movement needs no duplicate IDs');
    check(result.rows.filter(function (row) { return row.rfq_title === 'SYNTHETIC POI RFQ C'; })[0].source_record_id === manual.source_record_id, 'manual identity follows row movement');
    check(snapshot() === before, 'movement reconciliation changes no cells');
  } finally {
    // Remove only the extra synthetic test record; production is never referenced.
    if (createdRow !== null) sheet.deleteRows(createdRow, 1);
    SpreadsheetApp.flush();
  }
  check(snapshot() === original, 'original two-row fixture restored unchanged');
  Logger.log(JSON.stringify({ ok: true, checks: report, production_writes: 0 }));
  return { ok: true, checks: report };
}
