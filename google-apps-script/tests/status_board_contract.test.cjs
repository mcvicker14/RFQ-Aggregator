const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '..', 'status_board_sync.gs'), 'utf8');

function fixture({ header = 38, extraHeader = false, missingDate = false, boundary = false, empty = false, withGoBys = false } = {}) {
  const blank = () => Array(16).fill('');
  const grid = Array.from({ length: 200 }, blank);
  grid[1] = ['Date\n Added', 'Due Date', 'Due Time \n CST', 'Client/\n Project Location',
    'RFQ Title', 'Digital\n Option', 'Standard\n Form', 'Submit? Y or N', 'Date\n Submitted',
    'Importance\n  (1<3)', 'Quality\n  (1<3)', 'Probability\n (1<3)', 'Notes', 'Submitted\n Y/N', 'Link', ''];
  if (withGoBys) { grid[1].splice(12, 0, 'Go-bys'); grid[1].pop(); }
  grid[header - 1][0] = 'New RFQs';
  if (extraHeader) grid[9][0] = 'New RFQs';
  if (!empty) {
    grid[header] = ['10/1/2026', '10/8/2026', '4:00 PM', 'Synthetic Agency, LA', 'Test RFQ', '', '', 'N', '', '', '', '', 'Keep decision', 'Y', 'click here', ''];
    if (withGoBys) { grid[header].splice(12, 0, 'Example reference'); grid[header].pop(); }
    if (missingDate) grid[header][0] = '';
  }
  grid[header + (boundary ? 1 : 2)][0] = 'Grant Title';
  let writes = 0, locks = 0;
  const sheet = {
    getMaxRows: () => grid.length,
    getRange: (r, c, h, w) => ({
      getDisplayValues: () => grid.slice(r - 1, r - 1 + h).map(row => row.slice(c - 1, c - 1 + w)),
      getValues: () => grid.slice(r - 1, r - 1 + h).map(row => row.slice(c - 1, c - 1 + w).map(
        (value, i) => c + i <= 2 && /^\d+\/\d+\/\d{4}$/.test(value)
          ? new Date('2026-10-08T05:00:00Z') : value)),
      getRichTextValues: () => Array.from({ length: h }, () => [{ getLinkUrl: () => c === (withGoBys ? 16 : 15) ? 'https://example.test/rfq' : null }]),
      setValues: () => { writes++; }
    }),
    insertRowBefore: () => { writes++; }
  };
  const ctx = vm.createContext({
    PropertiesService: { getScriptProperties: () => ({ getProperty: () => 'synthetic-secret' }) },
    LockService: { getScriptLock: () => ({ tryLock: () => { locks++; return true; }, releaseLock: () => { locks--; } }) },
    SpreadsheetApp: { getActiveSpreadsheet: () => ({ getSheetByName: name => name === 'Active' ? sheet : null }) }
  });
  vm.runInContext(source, ctx);
  return {
    post: payload => JSON.parse(JSON.stringify(ctx.handlePost({ postData: { contents: JSON.stringify({ secret: 'synthetic-secret', ...payload }) } }))),
    writes: () => writes, locks: () => locks, grid
  };
}

test('actual script reads a shifted section, display dates, decisions and hyperlink without writes', () => {
  const f = fixture();
  const result = f.post({ action: 'read' });
  assert.equal(result.ok, true);
  assert.equal(result.protocol_version, 2);
  assert.equal(result.rows.length, 1);
  assert.equal(result.rows[0].sheet_row_number, 39);
  assert.equal(result.rows[0].due_date, '10/8/2026');
  assert.equal(result.rows[0].due_time, '4:00 PM');
  assert.equal(result.rows[0].submit_y_n, 'N');
  assert.equal(result.rows[0].notes, 'Keep decision');
  assert.equal(result.rows[0].go_bys, '');
  assert.equal(result.rows[0].submitted_y_n, 'Y');
  assert.equal(result.rows[0].link, 'https://example.test/rfq');
  assert.equal(f.writes(), 0);
  assert.equal(f.locks(), 0);
});
test('explicit 16-column header retains separate Go-bys, Notes, Submitted and Link', () => {
  const f = fixture({ withGoBys: true });
  const row = f.post({ action: 'read' }).rows[0];
  assert.equal(row.go_bys, 'Example reference');
  assert.equal(row.notes, 'Keep decision');
  assert.equal(row.submitted_y_n, 'Y');
  assert.equal(row.link, 'https://example.test/rfq');
  assert.equal(f.writes(), 0);
});
for (const column of [3, 7, 12, 13, 14, 15]) {
  test(`unexpected header at column ${column + 1} rejects the snapshot without writes`, () => {
    const f = fixture();
    f.grid[1][column] = 'Unexpected header';
    assert.equal(f.post({ action: 'read' }).error, 'structure_error');
    assert.equal(f.writes(), 0);
  });
}
test('missing Date Added does not truncate the snapshot', () => {
  const f = fixture({ missingDate: true });
  assert.equal(f.post({ action: 'read' }).rows.length, 1);
  assert.equal(f.writes(), 0);
});
for (const options of [{ extraHeader: true }, { boundary: true }]) {
  test(`ambiguous/unsafe structure fails closed ${JSON.stringify(options)}`, () => {
    const f = fixture(options);
    assert.equal(f.post({ action: 'read' }).error, 'structure_error');
    assert.equal(f.writes(), 0);
    assert.equal(f.locks(), 0);
  });
}
test('a verified empty section is a valid empty snapshot', () => {
  assert.deepEqual(fixture({ empty: true }).post({ action: 'read' }).rows, []);
});
test('unknown actions never fall through to a write', () => {
  const f = fixture({ header: 36 });
  assert.equal(f.post({ action: 'reed', fields: { rfq_title: 'No insertion' } }).error, 'bad_request');
  assert.equal(f.writes(), 0);
});
test('wrong secret cannot read or write', () => {
  const f = fixture();
  assert.equal(f.post({ action: 'read', secret: 'wrong' }).error, 'unauthorized');
  assert.equal(f.writes(), 0);
});
test('legacy write contract still inserts only at verified original layout', () => {
  const f = fixture({ header: 36, withGoBys: true });
  assert.equal(f.post({ fields: { date_added: '10/6/2026', rfq_title: 'New synthetic row' } }).status, 'inserted');
  assert.equal(f.writes(), 2);
});
test('shifted layout does not silently broaden write authorization', () => {
  const f = fixture();
  assert.equal(f.post({ fields: { rfq_title: 'No insertion' } }).error, 'structure_error');
  assert.equal(f.writes(), 0);
});
