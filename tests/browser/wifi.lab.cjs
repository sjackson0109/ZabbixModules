/** LAB ONLY: Wi-Fi Explorer in a real browser against a disposable lab, after tests/integration/zabbix_runtime.py has
 * loaded the Wi-Fi replay hosts and WIFI_LAB_CONFIG. Covers what the HTTP checks cannot: tab and range navigation,
 * the floor placement script (click to place, remove), the configuration editor's save-and-reload, and escaping of
 * operator text in the rendered page. The module configuration is put back as it was, whatever happens.
 * Usage: node tests/browser/wifi.lab.cjs 7.4   (NE_CHROMIUM may name a Chromium binary)
 * Reads generated lab credentials only and never prints them.
 */
const { chromium } = require('playwright');
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const version = process.argv[2] || '7.4';
const port = { '7.0': 18070, 7.2: 18072, 7.4: 18074 }[version];
if (!port) throw new Error('Unsupported lab version');
const url = `http://127.0.0.1:${port}`;
const admin = JSON.parse(
  fs.readFileSync(path.join(__dirname, '..', '..', 'lab', '.state', version, 'credentials.json'))
).admin;
const VIEWS = {
  overview: 'Findings',
  floors: 'Floors',
  rf: 'Observing APs',
  ssids: 'Lab-Expected',
  paths: 'VLAN',
  impact: 'fail',
  events: 'Expo',
  clients: 'Clients now',
  capacity: 'Last 30 days'
};
const MARKUP = '<b id="we-injected">Expo</b>';

async function api(method, params, token) {
  const r = await fetch(url + '/api_jsonrpc.php', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: 'Bearer ' + token } : {}) },
    body: JSON.stringify({ jsonrpc: '2.0', id: 1, method, params })
  });
  const b = await r.json();
  if (b.error) throw new Error(method + ': ' + JSON.stringify(b.error));
  return b.result;
}
const steps = [];
const step = name => {
  steps.push(name);
  console.log('ok', steps.length, name);
};
const view = params => `${url}/zabbix.php?${new URLSearchParams({ action: 'wifiexplorer.view', site: 'lab-west', ...params })}`;

(async () => {
  const token = await api('user.login', { username: 'Admin', password: admin });
  const module = async () => (await api('module.get', { output: 'extend', filter: { id: 'wifiexplorer' } }, token))[0];
  const original = await module();
  assert.ok(original.config.wifi, 'Run tests/integration/zabbix_runtime.py first: it loads the Wi-Fi lab configuration.');
  const browser = await chromium.launch({
    headless: true,
    executablePath: process.env.NE_CHROMIUM || undefined,
    args: ['--no-sandbox', '--disable-dev-shm-usage']
  });
  try {
    const page = await (await browser.newContext({ viewport: { width: 1440, height: 1000 } })).newPage();
    const errors = [];
    page.on('pageerror', e => errors.push(e.message));
    page.on('console', m => m.type() === 'error' && errors.push(m.text()));
    await page.goto(url + '/index.php');
    await page.locator('#name').fill('Admin');
    await page.locator('#password').fill(admin);
    await page.locator('#enter').click();
    await page.waitForURL(/zabbix\.php/, { timeout: 30000 });

    // Every tab is a link that opens its view and marks itself current.
    await page.goto(view({}));
    for (const [name, text] of Object.entries(VIEWS)) {
      const tab = page.locator('.we-tabs a').nth(Object.keys(VIEWS).indexOf(name));
      await tab.click();
      await page.waitForURL(u => (new URL(u).searchParams.get('view') || 'overview') === name);
      await page.waitForLoadState('load');
      assert.equal(new URL(page.url()).searchParams.get('view') || 'overview', name, `${name} tab opened another view`);
      const current = await page.locator('.we-tabs').first().locator('a[aria-current="page"]').count();
      assert.equal(current, 1, `${name}: one current view tab`);
      assert.ok((await page.textContent('body')).includes(text), `${name} view lacks "${text}"`);
    }
    step('Every view tab navigates, marks itself current and renders its content');
    for (const [range, label] of [['day', 'Last 24 hours'], ['year', 'Last 12 months']]) {
      await page.locator('a', { hasText: label }).click();
      await page.waitForURL(u => new URL(u).searchParams.get('range') === range);
      assert.equal(await page.locator('[aria-current="page"]', { hasText: label }).count(), 1, `${label} not current`);
    }
    step('Capacity range tabs switch between the day, month and year views');

    // Placement: pick an unplaced AP, click the middle of the plan, then remove it again.
    await page.goto(view({ view: 'floors', floor: 'west-ground' }));
    const apUid = await page.locator('#we-place-ap li[title^="lab-ap-03"]').getAttribute('value');
    const option = page.locator(`li[value="${apUid}"]`);
    assert.match(apUid || '', /^ap-[0-9a-f]{24}$/, 'lab-ap-03 is offered for placement by its AP ID');
    assert.equal(await page.locator(`svg.we-floor [data-ap="${apUid}"]`).count(), 0, 'lab-ap-03 starts unplaced');
    await page.locator('#we-place-ap-button').click();
    await option.click();
    const box = await page.locator('svg.we-floor').boundingBox();
    await Promise.all([
      page.waitForURL(u => new URL(u).searchParams.get('ap') === apUid),
      page.mouse.click(box.x + box.width / 2, box.y + box.height / 2)
    ]);
    await page.locator(`svg.we-floor [data-ap="${apUid}"]`).waitFor();
    const placed = (await module()).config.wifi;
    const stored = typeof placed === 'string' ? null : placed.placements[apUid];
    assert.ok(stored && Math.abs(stored.x - 0.5) < 0.02 && Math.abs(stored.y - 0.5) < 0.02,
      'The click is stored as the middle of the plan');
    assert.ok(!(await page.textContent('body')).includes('does not validate'), 'The saved configuration loads again');
    step('Clicking the plan places lab-ap-03 at that point, and the saved configuration loads again');
    await page.locator('#we-place-ap-button').click();
    await page.locator(`li[value="${apUid}"]`).click();
    await page.locator('#we-place-remove').click();
    await page.waitForFunction(id => !document.querySelector(`svg.we-floor [data-ap="${id}"]`), apUid);
    step('Remove placement takes lab-ap-03 off the plan');

    // The editor saves a document that loads again, and operator text is shown as text, never as markup.
    await page.goto(`${url}/zabbix.php?action=wifiexplorer.config.edit`);
    const editor = page.locator('textarea').first();
    const document = JSON.parse(await editor.inputValue());
    document.events[0].name = MARKUP;
    await editor.fill(JSON.stringify(document, null, 2));
    await page.locator('[name="save"]').click();
    await page.getByText('Wi-Fi configuration saved').waitFor({ timeout: 30000 });
    await page.goto(view({ view: 'events', event: 'expo' }));
    const body = await page.textContent('body');
    assert.ok(!body.includes('does not validate') && body.includes(MARKUP), 'The event name is shown literally');
    assert.equal(await page.locator('#we-injected').count(), 0, 'Operator text became markup');
    step('The editor saves a document that loads again, and an event name with markup is shown as text');

    assert.deepEqual(errors, [], 'Browser errors: ' + errors.join('; '));
    step('No script errors on any page');
  } finally {
    await api('module.update', [{ moduleid: original.moduleid, config: original.config }], token);
    await browser.close();
  }
  console.log(`Wi-Fi browser checks passed (${steps.length} steps).`);
})().catch(error => {
  console.error(error.message);
  process.exit(1);
});
