const { test } = require('node:test');
const assert = require('node:assert/strict');
const { createHash, randomUUID } = require('node:crypto');
const fs = require('node:fs'), path = require('node:path'), vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '..', 'status_board_sync.gs'), 'utf8');

function fixture({ enabled = true, advanced = true, withGoBys = false } = {}) {
  const grid = Array.from({ length: 160 }, () => Array(16).fill(''));
  const formulas = Array.from({ length: 160 }, () => Array(16).fill(''));
  grid[1] = ['Date Added','Due Date','Due Time CST','Client Project Location','RFQ Title','Digital Option','Standard Form','Submit? Y or N','Date Submitted','Importance (1<3)','Quality (1<3)','Probability (1<3)','Notes','Submitted Y/N','Link',''];
  if (withGoBys) { grid[1].splice(12, 0, 'Go-bys'); grid[1].pop(); }
  grid[37][0] = 'New RFQs';
  grid[38] = ['10/6/2026','10/30/2026','4 PM','Agency','Synthetic RFQ','','','N','','','','','Keep notes','','https://example.invalid/one',''];
  if (withGoBys) { grid[38].splice(12, 0, 'Go-by'); grid[38].pop(); }
  grid[39] = [...grid[38]]; grid[39][4] = 'Second RFQ';
  const ids = [{ number: 39, value: randomUUID(), id: 101 }, { number: 40, value: randomUUID(), id: 102 }];
  let writes = [], metadataWrites = 0, beforeWrite = () => {}, afterWrite = () => {};
  const sheet = {
    getMaxRows: () => grid.length, getMaxColumns: () => 29, getSheetId: () => 0,
    createDeveloperMetadataFinder: () => ({ withKey: () => ({ find: () => ids.map(m => ({
      getValue: () => m.value, getId: () => m.id,
      getLocation: () => ({ getRow: () => ({ getRow: () => m.number }) })
    })) }) }),
    getRange: (r, c, h, w) => {
      const entireRow = typeof r === 'string' && /^(\d+):\1$/.test(r);
      if (entireRow) { r = Number(r.split(':')[0]); c = 1; h = 1; w = 29; }
      return ({
      getDisplayValues: () => grid.slice(r - 1, r - 1 + h).map(row => row.slice(c - 1, c - 1 + w)),
      getFormulas: () => formulas.slice(r - 1, r - 1 + h).map(row => row.slice(c - 1, c - 1 + w)),
      getRichTextValues: () => grid.slice(r - 1, r - 1 + h).map(row => [{ getLinkUrl: () => row[withGoBys ? 15 : 14] || null }]),
      addDeveloperMetadata: (_, value) => {
        if (!entireRow) throw new Error('Adding developer metadata to arbitrary ranges is not supported');
        metadataWrites++; ids.push({ number: r, value, id: 103 });
      }
    }); }
  };
  const ctx = {
    PropertiesService: { getScriptProperties: () => ({ getProperty: key => key === 'STATUS_BOARD_WEBHOOK_SECRET' ? 'test-secret' : enabled ? 'true' : null }) },
    LockService: { getScriptLock: () => ({ tryLock: () => true, releaseLock: () => {} }) },
    SpreadsheetApp: { getActiveSpreadsheet: () => ({ getSheetByName: () => sheet, getId: () => 'synthetic-sheet' }), flush: () => {} },
    Utilities: { DigestAlgorithm: { SHA_256: 'sha256' }, Charset: { UTF_8: 'utf8' }, getUuid: randomUUID,
      computeDigest: (_, value) => [...createHash('sha256').update(value).digest()] }
  };
  if (advanced) ctx.Sheets = { Spreadsheets: { Values: { batchUpdateByDataFilter: body => {
    assert.equal(body.valueInputOption, 'RAW'); assert.equal(body.data.length, 1);
    const data = body.data[0], values = data.values[0];
    assert.deepEqual(JSON.parse(JSON.stringify(values.slice(0, 7))), Array(7).fill(null));
    assert.equal(values.length, 8); assert.match(values[7], /^[YN]?$/);
    beforeWrite();
    const target = ids.find(m => m.id === data.dataFilter.developerMetadataLookup.metadataId);
    if (!target) return { totalUpdatedCells: 0 };
    const scope = data.dataFilter.developerMetadataLookup.metadataLocation.dimensionRange;
    assert.equal(scope.dimension, 'ROWS'); assert.equal(scope.sheetId, 0);
    assert.equal(scope.endIndex - scope.startIndex, 1);
    assert.equal(data.dataFilter.developerMetadataLookup.locationMatchingStrategy, 'EXACT_LOCATION');
    if ((target.sheetId || 0) !== scope.sheetId || target.number - 1 < scope.startIndex || target.number - 1 >= scope.endIndex) return { totalUpdatedCells: 0 };
    grid[target.number - 1][7] = values[7]; writes.push({ number: target.number, value: values[7] }); afterWrite();
    return { totalUpdatedCells: 1 };
  } } } };
  vm.createContext(ctx); vm.runInContext(source, ctx);
  function post(payload) { return JSON.parse(JSON.stringify(ctx.handlePost({ postData: { contents: JSON.stringify({ secret: 'test-secret', ...payload }) } }))); }
  const first = post({ action: 'read' }).rows[0];
  const edit = { action: 'set_submit', request_id: randomUUID(), source_record_id: first.source_record_id, expected_revision: first.source_revision, expected_submit: first.submit_y_n, value: 'Y' };
  return { post, edit, grid, ids, formulas, writes, ctx, sheet, metadataWrites: () => metadataWrites,
    beforeWrite: fn => { beforeWrite = fn; }, afterWrite: fn => { afterWrite = fn; } };
}

for (const withGoBys of [false, true]) test(`only H changes with known schema ${withGoBys ? 16 : 15}`, () => {
  const f = fixture({ withGoBys }); const before = structuredClone(f.grid);
  const result = f.post(f.edit); assert.equal(result.status, 'confirmed');
  before[38][7] = 'Y'; assert.deepEqual(f.grid, before); assert.equal(f.writes.length, 1);
  assert.equal(result.source_record_id, f.edit.source_record_id);
  assert.equal(result.source_revision, f.post({ action: 'read' }).rows[0].source_revision);
  assert.equal(f.metadataWrites(), 0);
});
test('N is an explicit supported decision, not an opportunity deletion', () => {
  const f = fixture(); f.edit.value = 'N'; assert.equal(f.post(f.edit).value, 'N'); assert.equal(f.grid[38][4], 'Synthetic RFQ');
});
for (const options of [{ enabled: false }, { advanced: false }]) test(`activation gate ${JSON.stringify(options)} fails closed`, () => {
  const f = fixture(options); assert.equal(f.post(f.edit).error, 'needs_configuration'); assert.equal(f.writes.length, 0);
});
for (const field of ['submit_y_n', 'notes', 'rfq_title', 'due_date']) test(`concurrent ${field} change conflicts without writes`, () => {
  const f = fixture(); const index = { submit_y_n: 7, notes: 12, rfq_title: 4, due_date: 1 }[field];
  f.grid[38][index] = 'Changed by owner'; assert.equal(f.post(f.edit).error, 'conflict'); assert.equal(f.writes.length, 0);
});
test('row reorder before saving resolves source identity, not cached row number', () => {
  const f = fixture(); [f.grid[38], f.grid[39]] = [f.grid[39], f.grid[38]]; f.ids[0].number = 40; f.ids[1].number = 39;
  assert.equal(f.post(f.edit).status, 'confirmed'); assert.equal(f.grid[39][7], 'Y'); assert.equal(f.grid[38][7], 'N');
});
test('row move between preflight and write rejects without touching either record', () => {
  const f = fixture(); f.beforeWrite(() => { [f.grid[38], f.grid[39]] = [f.grid[39], f.grid[38]]; f.ids[0].number = 40; f.ids[1].number = 39; });
  assert.equal(f.post(f.edit).error, 'uncertain'); assert.equal(f.writes.length, 0); assert.equal(f.grid[38][7], 'N'); assert.equal(f.grid[39][7], 'N');
});
test('deleted then recreated identical row cannot reuse old identity', () => {
  const f = fixture(); f.ids.splice(0, 1); assert.equal(f.post(f.edit).error, 'conflict'); assert.equal(f.writes.length, 0);
});
test('deletion between preflight and write does not write the replacement row', () => {
  const f = fixture(); f.beforeWrite(() => f.ids.splice(0, 1)); assert.equal(f.post(f.edit).error, 'uncertain'); assert.equal(f.writes.length, 0);
});
test('a concurrent move outside New RFQs or into Archive has no matching write target', () => {
  for (const archive of [false, true]) {
    const f = fixture(); f.beforeWrite(() => { if (archive) f.ids[0].sheetId = 99; else f.ids[0].number = 5; });
    assert.equal(f.post(f.edit).error, 'uncertain'); assert.equal(f.writes.length, 0);
  }
});
test('archived or submitted RFQ is not editable', () => {
  const f = fixture(); f.grid[38][13] = 'Y'; assert.equal(f.post(f.edit).error, 'conflict'); assert.equal(f.writes.length, 0);
  f.grid[38][13] = ''; f.grid[37][0] = 'Submitted'; f.grid[40][0] = 'New RFQs'; assert.equal(f.post(f.edit).error, 'conflict');
});
test('duplicate identity is unusable', () => {
  const f = fixture(); f.ids[1].value = f.ids[0].value; assert.equal(f.post(f.edit).error, 'conflict'); assert.equal(f.writes.length, 0);
});
test('formula Submit cell is never replaced', () => {
  const f = fixture(); f.formulas[38][7] = '=IF(A1,"N","Y")'; f.edit.expected_revision = f.post({ action: 'read' }).rows[0].source_revision;
  assert.equal(f.post(f.edit).error, 'conflict'); assert.equal(f.writes.length, 0);
});
for (const payload of [{ value: '=' }, { value: 'yes' }, { fields: { notes: 'bad' } }, { value: null }, { value: undefined }]) test(`invalid edit ${JSON.stringify(payload)} never writes`, () => {
  const f = fixture(); assert.equal(f.post({ ...f.edit, ...payload }).error, 'bad_request'); assert.equal(f.writes.length, 0);
});

for (const withGoBys of [false, true]) for (const old of ['N', 'Y']) test(`explicit blank clears only H from ${old}, schema ${withGoBys ? 16 : 15}`, () => {
  const f = fixture({ withGoBys }); f.grid[38][7] = old;
  const row = f.post({ action: 'read' }).rows[0], before = structuredClone(f.grid);
  const result = f.post({ ...f.edit, expected_submit: old, expected_revision: row.source_revision, value: '' });
  assert.equal(result.status, 'confirmed'); assert.equal(result.value, '');
  before[38][7] = ''; assert.deepEqual(f.grid, before);
  assert.equal(f.writes.length, 1); assert.equal(f.post({ action: 'read' }).rows[0].submit_y_n, '');
});
test('unknown schema prevents edit', () => {
  const f = fixture(); f.grid[1][7] = 'Unknown'; assert.equal(f.post(f.edit).error, 'structure_error'); assert.equal(f.writes.length, 0);
});
test('concurrent Notes or formula changes after write produce uncertainty, never rollback', () => {
  for (const formula of [false, true]) {
    const f = fixture(); f.afterWrite(() => { if (formula) f.formulas[38][10] = '=1'; else f.grid[38][12] = 'Human notes'; });
    assert.equal(f.post(f.edit).error, 'uncertain'); assert.equal(f.writes.length, 1);
  }
});
test('identities are never assigned on read; manual helper adds only missing metadata', () => {
  const f = fixture(); f.ids.splice(0, 1); f.post({ action: 'read' }); assert.equal(f.metadataWrites(), 0);
  const before = structuredClone(f.grid); f.ctx.preparePoiSubmitIdentities(); assert.equal(f.metadataWrites(), 1); assert.deepEqual(f.grid, before);
});

test('numeric full-width grid range is not an unbounded entire-row metadata location', () => {
  const f = fixture();
  assert.throws(() => f.sheet.getRange(39, 1, 1, 29).addDeveloperMetadata('test', randomUUID()), /arbitrary ranges/);
  assert.equal(f.metadataWrites(), 0);
});
