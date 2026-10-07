// Synthetic browser verification against a local Next server. No live credentials
// or services. Install Playwright outside the repo and set POI_PLAYWRIGHT_PATH.
const { chromium } = require(process.env.POI_PLAYWRIGHT_PATH || 'playwright');
const assert = require('node:assert/strict');
const { randomUUID } = require('node:crypto');
const fs = require('node:fs'), path = require('node:path');
const base = process.env.POI_UI_BASE || 'http://127.0.0.1:3010';
const artifacts = process.env.POI_UI_ARTIFACTS || path.resolve('ui-artifacts');
fs.mkdirSync(artifacts, { recursive: true });

const kpis = Object.fromEntries(['total_active_opportunities','total_estimated_contract_value','total_estimated_fee','discovered_this_week','due_within_30_days','awaiting_go_no_go','active_proposals','interviews_pending','awards_pending','wins','losses','sdvosb_setaside_count','sole_source_or_limited_competition_count','recompete_count','early_stage_count'].map(k => [k, 4]));
const intel = Object.fromEntries(['live_opportunity_count','pre_solicitation_count','early_signal_count','award_intelligence_count','new_this_week','sources_checked_today','sources_with_errors','new_intelligence_since_last_view'].map(k => [k, 2]));
const dashboard = { kpis: { ...kpis, win_rate_pct: 50 }, intelligence: { ...intel, last_viewed_at: null }, include_samples: false,
  status_board: { on_status_board: 6, selected_to_submit: 2, due_soon: 3, submitted: 0, past_due: 1 },
  highest_priority_opportunities: [], high_priority_signals: [], upcoming_deadlines: [],
  attention_today_tasks: [{ id: randomUUID(), title: 'Review the water-system RFQ', due_date: '2026-10-06', status: 'not_started', priority: 'high', opportunity_title: 'Synthetic project' }] };
for (const key of ['pipeline_by_stage','pipeline_by_agency','pipeline_by_state','pipeline_by_source','pipeline_by_contract_type','pipeline_by_naics','pipeline_by_score_band','pipeline_value_over_time']) dashboard[key] = [];
const titles = ['Water System Engineering RFQ', 'Bridge Rehabilitation Services', 'Drainage Study and Design', 'Airport Planning Services', 'Wastewater Treatment Upgrade', 'Surveying and Mapping'];

async function main() {
  const browser = await chromium.launch({ channel: 'msedge', headless: true });
  try {
    const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
    await page.clock.install();
    const errors = [], writes = []; let refreshes = 0, conflict = false, stale = false, fail = false, delayWrite = false;
    page.on('pageerror', e => errors.push(e.message));
    const rows = titles.map((title, i) => ({ id: randomUUID(), source_record_id: i === 5 ? null : randomUUID(), source_revision: 'a'.repeat(64), sheet_row_number: 39 + i,
      date_added: '10/6/2026', due_date: '10/30/2026', due_date_parsed: '2026-10-30', due_time: '4:00 PM', client_project_location: ['Synthetic Parish, LA','Synthetic City, MS'][i % 2],
      rfq_title: title, digital_option: 'Yes', standard_form: 'SF330', submit_y_n: i === 1 ? 'Y' : i === 2 ? null : i === 3 ? '?' : 'N', date_submitted: '', importance: '3', quality: '2', probability: '2', go_bys: '', notes: 'Owner notes stay intact.', submitted_y_n: '', link: `https://example.invalid/rfq/${i}`, is_submit_y: i === 1, is_submitted_y: false,
      opportunity_id: null, match_method: 'unmatched', is_manual_entry: true, last_synced_at: new Date().toISOString() }));
    await page.addInitScript(() => localStorage.setItem('poi_token', 'synthetic-test-token'));
    await page.route('**/api/**', async route => {
      const request = route.request(), url = new URL(request.url()); let body, status = 200;
      if (url.pathname === '/api/auth/me') body = { id: randomUUID(), email: 'owner@example.invalid', full_name: 'Synthetic Owner', role: 'executive', is_active: true };
      else if (url.pathname === '/api/dashboard/summary') body = dashboard;
      else if (url.pathname === '/api/status-board/submit') {
        const payload = request.postDataJSON(); writes.push(payload); if (delayWrite) await new Promise(resolve => setTimeout(resolve, 250));
        const row = rows.find(r => r.source_record_id === payload.source_record_id);
        if (fail) { status = 502; body = { detail: 'Save could not be confirmed. Inspect Google Sheets.' }; }
        else if (conflict) { status = 409; body = { detail: 'The sheet changed. Refresh and inspect Google Sheets.' }; }
        else { assert.equal(payload.expected_submit, row.submit_y_n); assert.equal(payload.expected_revision, row.source_revision); row.submit_y_n = payload.value; row.is_submit_y = payload.value === 'Y'; row.source_revision = 'b'.repeat(64); body = { status: 'confirmed', value: payload.value }; }
      } else if (url.pathname.startsWith('/api/status-board/')) {
        if (url.pathname.endsWith('/refresh')) refreshes++;
        const filter = url.searchParams.get('filter'); let filtered = rows;
        if (filter === 'submit_y') filtered = rows.filter(r => r.is_submit_y);
        if (filter === 'submit_n_blank') filtered = rows.filter(r => !r.submit_y_n || r.submit_y_n === 'N');
        const client = url.searchParams.get('client'); if (client) filtered = filtered.filter(r => r.client_project_location.toLowerCase().includes(client.toLowerCase()));
        const checked = new Date(Date.now() - (stale ? 20 * 60_000 : 0)).toISOString();
        body = { rows: filtered, submit_edits_enabled: true, last_sync_attempted_at: checked, last_sync_succeeded_at: checked, last_error: null, sheet_url: 'https://example.invalid/synthetic-sheet' };
      } else body = [];
      await route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) });
    });
    await page.goto(base);
    await page.getByRole('button', { name: `Change Submit for ${titles[0]}`, exact: true }).waitFor();
    assert.equal(await page.getByText('Executive Dashboard', { exact: true }).isVisible(), false);
    await page.screenshot({ path: path.join(artifacts, 'home-after-desktop.png'), fullPage: true });
    await page.getByRole('button', { name: 'All columns', exact: true }).click();
    await page.getByRole('columnheader', { name: 'Standard Form', exact: true }).waitFor();
    await page.getByRole('button', { name: 'Focused view', exact: true }).click();
    await page.getByRole('searchbox').count(); // Input is a textbox with a descriptive label.
    await page.getByRole('textbox', { name: 'Search RFQs, clients and notes' }).fill('Water System');
    assert.equal(await page.getByRole('button', { name: /Change Submit for/ }).count(), 1);
    await page.getByRole('textbox', { name: 'Search RFQs, clients and notes' }).fill('');
    await page.getByRole('combobox', { name: 'Filter Status Board' }).selectOption('submit_y');
    await page.getByText('1 RFQ', { exact: true }).waitFor();
    await page.getByRole('button', { name: 'Refresh', exact: true }).click();
    await page.waitForFunction(() => document.querySelector('select[aria-label="Filter Status Board"]').value === 'submit_y');
    assert.equal(await page.getByRole('button', { name: /Change Submit for/ }).count(), 1);
    await page.getByRole('combobox', { name: 'Filter Status Board' }).selectOption('all_active');
    await page.getByRole('button', { name: `Change Submit for ${titles[0]}`, exact: true }).waitFor();
    await page.getByRole('button', { name: `Change Submit for ${titles[0]}`, exact: true }).click();
    const form = page.getByRole('form', { name: 'Edit Submit decision' });
    assert.equal(await form.getByRole('textbox').count(), 0);
    assert.equal(await form.getByRole('radio').count(), 3);
    assert.equal(await page.getByRole('button', { name: 'Save to sheet' }).isEnabled(), false);
    await form.getByRole('radio', { name: 'N', exact: true }).check();
    assert.equal(await page.getByRole('button', { name: 'Save to sheet' }).isEnabled(), false);
    await form.getByRole('radio', { name: 'Y', exact: true }).check();
    await page.waitForFunction(() => [...document.querySelectorAll('button')].some(b => b.textContent === 'Save to sheet' && !b.disabled));
    await page.screenshot({ path: path.join(artifacts, 'submit-choices-desktop.png'), fullPage: true });
    await page.getByRole('button', { name: 'Cancel', exact: true }).click();
    assert.equal(writes.length, 0);
    await page.getByRole('button', { name: `Change Submit for ${titles[0]}`, exact: true }).click();
    assert.equal(await form.locator('input:checked').count(), 0);
    await form.getByRole('radio', { name: 'Y', exact: true }).check();
    delayWrite = true;
    await page.getByRole('button', { name: 'Save to sheet' }).evaluate(button => { button.click(); button.click(); });
    await page.getByText('Submit = Y confirmed in Google Sheets.', { exact: true }).waitFor();
    delayWrite = false;
    assert.equal(writes.length, 1); assert.equal(writes[0].value, 'Y');
    assert.deepEqual(Object.keys(writes[0]).sort(), ['expected_revision','expected_submit','request_id','source_record_id','value']);
    await page.getByRole('button', { name: `Change Submit for ${titles[0]}`, exact: true }).click();
    await form.getByRole('radio', { name: 'Blank', exact: true }).check();
    await page.getByRole('button', { name: 'Save to sheet' }).click();
    await page.getByText('Blank Submit confirmed in Google Sheets.', { exact: true }).waitFor();
    assert.equal(writes.length, 2); assert.equal(writes[1].value, ''); assert.equal(writes[1].expected_submit, 'Y');
    await page.getByRole('button', { name: `Choose Submit for ${titles[0]}`, exact: true }).click();
    assert.equal(await form.getByRole('radio').count(), 2);
    assert.equal(await form.getByRole('radio', { name: 'Blank' }).count(), 0);
    assert.equal(await page.getByRole('button', { name: 'Save to sheet' }).isEnabled(), false);
    await form.getByRole('radio', { name: 'N', exact: true }).check();
    await page.getByRole('button', { name: 'Save to sheet' }).click();
    await page.getByText('Submit = N confirmed in Google Sheets.', { exact: true }).waitFor();
    assert.equal(writes[2].expected_submit, ''); assert.equal(writes[2].value, 'N');
    await page.getByRole('button', { name: `Change Submit for ${titles[1]}`, exact: true }).click();
    await form.getByRole('radio', { name: 'N', exact: true }).check();
    await page.getByRole('button', { name: 'Save to sheet' }).click();
    await page.getByRole('button', { name: `Change Submit for ${titles[1]}`, exact: true }).waitFor();
    assert.equal(writes[3].expected_submit, 'Y'); assert.equal(writes[3].value, 'N');
    assert.equal(rows[0].notes, 'Owner notes stay intact.'); assert.equal(rows[0].link, 'https://example.invalid/rfq/0');
    // Advance the browser clock: active views poll; an edit draft or hidden view
    // pauses the poll so a user's in-progress decision is not replaced.
    const refreshBeforePoll = refreshes;
    await page.clock.fastForward(61_000);
    await new Promise(resolve => setTimeout(resolve, 250));
    assert.ok(refreshes > refreshBeforePoll);
    await page.getByRole('button', { name: `Change Submit for ${titles[0]}`, exact: true }).click();
    const refreshBeforeDraft = refreshes;
    await page.clock.fastForward(61_000);
    await new Promise(resolve => setTimeout(resolve, 100));
    assert.equal(refreshes, refreshBeforeDraft);
    await page.getByRole('button', { name: 'Cancel', exact: true }).click();
    await page.evaluate(() => Object.defineProperty(document, 'visibilityState', { configurable: true, get: () => 'hidden' }));
    await page.clock.fastForward(61_000);
    await new Promise(resolve => setTimeout(resolve, 100));
    assert.equal(refreshes, refreshBeforeDraft);
    await page.evaluate(() => { delete document.visibilityState; });
    await page.clock.setSystemTime(new Date());
    await page.getByRole('button', { name: 'Refresh', exact: true }).click();
    await new Promise(resolve => setTimeout(resolve, 200));
    await page.clock.resume();
    await page.locator('summary').filter({ hasText: 'Pipeline overview, intelligence and reports' }).click();
    assert.equal(await page.getByText('Executive Dashboard', { exact: true }).isVisible(), true);
    await page.locator('summary').filter({ hasText: 'Pipeline overview, intelligence and reports' }).click();
    // Capture the previous homepage from a temporary local-only route if provided.
    if (process.env.POI_UI_BEFORE_PATH) {
      await page.goto(base + process.env.POI_UI_BEFORE_PATH); await page.getByText('Executive Dashboard', { exact: true }).waitFor();
      await page.screenshot({ path: path.join(artifacts, 'home-before-desktop.png'), fullPage: true });
      await page.goto(base); await page.getByRole('button', { name: `Change Submit for ${titles[0]}`, exact: true }).waitFor();
    }
    await page.setViewportSize({ width: 390, height: 844 });
    await page.screenshot({ path: path.join(artifacts, 'home-after-mobile.png'), fullPage: true });
    await page.getByRole('button', { name: `Choose Submit for ${titles[2]}`, exact: true }).click();
    assert.equal(await form.getByRole('radio').count(), 2);
    assert.equal(await form.getByRole('radio', { name: 'Blank' }).count(), 0);
    await form.getByRole('radio', { name: 'Y', exact: true }).check();
    await page.screenshot({ path: path.join(artifacts, 'submit-choices-mobile.png'), fullPage: true });
    await page.getByRole('button', { name: 'Cancel', exact: true }).click();
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
    await page.setViewportSize({ width: 1440, height: 1000 });
    conflict = true;
    await page.getByRole('button', { name: `Change Submit for ${titles[0]}`, exact: true }).click();
    await form.getByRole('radio', { name: 'Y', exact: true }).check(); await page.getByRole('button', { name: 'Save to sheet' }).click();
    await page.getByRole('alert').filter({ hasText: 'The sheet changed' }).waitFor();
    assert.equal(writes.length, 5); assert.equal(rows[0].submit_y_n, 'N');
    await page.waitForTimeout(350); assert.equal(await page.getByRole('alert').filter({ hasText: 'The sheet changed' }).isVisible(), true);
    assert.equal(await page.getByRole('button', { name: /Change Submit for/ }).first().isEnabled(), false);
    conflict = false;
    await page.getByRole('button', { name: 'Refresh', exact: true }).click();
    await page.getByRole('button', { name: `Change Submit for ${titles[0]}`, exact: true }).click();
    await form.getByRole('radio', { name: 'Blank', exact: true }).check(); fail = true;
    await page.getByRole('button', { name: 'Save to sheet' }).click();
    await page.getByRole('alert').filter({ hasText: 'Save could not be confirmed' }).waitFor();
    assert.equal(writes.length, 6); assert.equal(rows[0].submit_y_n, 'N');
    fail = false; await page.getByRole('button', { name: 'Refresh', exact: true }).click();
    await page.getByRole('button', { name: `Change Submit for ${titles[0]}`, exact: true }).click();
    await form.getByRole('radio', { name: 'Y', exact: true }).check();
    await page.clock.pauseAt(new Date()); await page.clock.fastForward(121_000);
    assert.equal(await page.getByRole('button', { name: 'Save to sheet' }).isEnabled(), false);
    assert.equal(writes.length, 6); await page.getByRole('button', { name: 'Cancel', exact: true }).click();
    await page.clock.resume();
    stale = true; await page.getByRole('button', { name: 'Refresh', exact: true }).click();
    await page.getByRole('alert').filter({ hasText: 'older than two minutes' }).waitFor();
    assert.equal(await page.getByRole('button', { name: /Change Submit for/ }).first().isEnabled(), false);
    assert.equal(errors.length, 0, errors.join('\n'));
    console.log(JSON.stringify({ passed: ['home prominence','collapsed features accessible','all columns','search','filter preservation','N/Y/Blank fixed choices','blank row has N/Y only','cancel/reopen resets choice','repeated save sends once','real empty-string clear','Y-to-N and blank-to-N','failure preserves value','stale draft cannot save','narrow payload','conflict remains visible and no retry','stale disables editing','mobile overflow','no browser exceptions'], refreshes, syntheticWrites: writes.length, artifacts }, null, 2));
  } finally { await browser.close(); }
}
main().catch(e => { console.error(e); process.exitCode = 1; });
