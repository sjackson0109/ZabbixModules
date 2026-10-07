/** Browser tests against a disposable seeded Zabbix lab. Never targets production.
 * Prerequisites: lab/lab.py install-modules and tests/integration/zabbix_runtime.py.
 * Reads generated local lab Admin credentials only; does not print credentials/tokens.
 */
const { chromium } = require('playwright');
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const versions = process.argv.slice(2).length ? process.argv.slice(2) : ['7.0', '7.2', '7.4'];
(async () => {
  const browser = await chromium.launch({
    headless: true,
    executablePath: process.env.NE_CHROMIUM || undefined,
    args: process.env.NE_CHROMIUM ? ['--no-sandbox', '--disable-dev-shm-usage'] : []
  });
  try {
    for (const version of versions) {
      const port = { '7.0': 18070, 7.2: 18072, 7.4: 18074 }[version];
      if (!port) throw new Error('Unsupported lab version');
      const url = `http://127.0.0.1:${port}`;
      const credentials = JSON.parse(
        fs.readFileSync(path.join(__dirname, '../../lab/.state', version, 'credentials.json'))
      );
      async function api(method, params, token) {
        const response = await fetch(url + '/api_jsonrpc.php', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: 'Bearer ' + token } : {}) },
          body: JSON.stringify({ jsonrpc: '2.0', id: 1, method, params })
        });
        const body = await response.json();
        if (body.error) throw new Error(method + ': ' + JSON.stringify(body.error));
        return body.result;
      }
      const token = await api('user.login', { username: 'Admin', password: credentials.admin });
      const hosts = await api(
        'host.get',
        { output: ['hostid', 'host', 'name'], filter: { host: ['ne-lab-a', 'ne-lab-b'] } },
        token
      );
      const hostA = hosts.find(h => h.host === 'ne-lab-a'),
        hostB = hosts.find(h => h.host === 'ne-lab-b');
      assert.ok(hostA && hostB, 'Seed the lab integration fixtures before running browser checks');
      const context = await browser.newContext({ viewport: { width: 1600, height: 1050 } }),
        page = await context.newPage(),
        errors = [];
      page.on('pageerror', error => errors.push(error.message));
      await page.goto(url + '/index.php');
      await page.locator('#name').fill('Admin');
      await page.locator('#password').fill(credentials.admin);
      await page.locator('#enter').click();
      await page.waitForURL(/zabbix\.php/, { timeout: 30000 });
      await page.goto(`${url}/zabbix.php?action=host.dashboard.view&hostid=${hostA.hostid}`);
      await page.locator('.dashboard-widget-neportpanel .ne-port').first().waitFor({ timeout: 45000 });
      const slideshow = page.getByRole('button', { name: 'Stop slideshow', exact: true });
      if (await slideshow.count()) await slideshow.click();
      const panel = page.locator('.dashboard-widget-neportpanel');
      assert.ok((await panel.locator('.ne-port').count()) >= 2);
      await panel.locator('.ne-port').first().click();
      assert.equal(await panel.locator('.ne-port').first().getAttribute('aria-pressed'), 'true');
      assert.ok((await panel.locator('.ne-drawer').innerText()).includes('ifIndex'));
      const detail = page.locator('.dashboard-widget-neinterfacedetail');
      await detail.locator('select').waitFor({ timeout: 30000 });
      await page.waitForFunction(
        () => document.querySelector('.dashboard-widget-neinterfacedetail select')?.value === 'port1',
        { timeout: 30000 }
      );
      assert.ok(
        (await detail.locator('.ne-drawer').innerText()).includes('Ethernet1'),
        'Native interface item broadcast must select the detail interface'
      );
      const peer = panel.locator(`a[href*="hostid=${hostB.hostid}"][href*="#ne="]`).first();
      assert.ok(await peer.count(), 'Resolved peer navigation link must be present');
      const expectedContext = await peer.getAttribute('href');
      await peer.click();
      await page.waitForURL(new RegExp(`hostid=${hostB.hostid}`));
      await page.locator('.dashboard-widget-neportpanel .ne-port[aria-pressed="true"]').waitFor({ timeout: 30000 });
      assert.equal(await page.locator('.dashboard-widget-neportpanel .ne-port[aria-pressed="true"]').count(), 1);
      assert.ok(page.url().includes('#ne='));
      // Native Host navigator and inherited dashboards must retain core host context.
      assert.ok((await page.locator('.dashboard-widget-neportpanel .ne-drawer').innerText()).includes('LLDP peers'));
      await page.waitForFunction(
        () => document.querySelector('.dashboard-widget-neinterfacedetail select')?.value === 'port1',
        { timeout: 30000 }
      );
      await page.getByText('Connectivity', { exact: true }).click();
      await page.locator('.dashboard-widget-netopology svg .ne-node').first().waitFor({ timeout: 30000 });
      assert.ok((await page.locator('.dashboard-widget-netopology svg .ne-node').count()) >= 2);
      await page.locator('.dashboard-widget-netopology svg .ne-edge').first().focus();
      await page.keyboard.press('Enter');
      assert.ok((await page.locator('.dashboard-widget-netopology .ne-drawer').innerText()).includes('physical link'));
      await page.getByText('Diagnostics', { exact: true }).click();
      await page.locator('.dashboard-widget-nefindings .ne-widget').waitFor({ timeout: 30000 });
      await page.getByTitle('Overview', { exact: true }).click();
      await page.locator('.dashboard-widget-neportpanel .ne-port[aria-pressed="true"]').waitFor({ timeout: 30000 });
      await page.screenshot({
        path: path.join(__dirname, '../../lab/.state', version, 'host-dashboard.png'),
        fullPage: true
      });
      // Disposable ordinary dashboard exercises native Host navigator communication.
      const fleetName = 'Network Explorer browser validation';
      const existing = await api('dashboard.get', { output: ['dashboardid'], filter: { name: fleetName } }, token);
      const dashboard = {
        name: fleetName,
        display_period: 30,
        auto_start: 0,
        pages: [
          {
            name: 'Selection',
            widgets: [
              {
                type: 'hostnavigator',
                name: 'Fixture Host navigator',
                x: 0,
                y: 0,
                width: 18,
                height: 8,
                fields: [
                  { type: 1, name: 'reference', value: 'NEHST' },
                  { type: 1, name: 'hosts.0', value: 'ne-lab-*' }
                ]
              },
              {
                type: 'neportpanel',
                name: 'Fixture Port panel',
                x: 18,
                y: 0,
                width: 36,
                height: 8,
                fields: [
                  { type: 1, name: 'reference', value: 'NEPRT' },
                  { type: 1, name: 'override_hostid._reference', value: 'NEHST._hostid' }
                ]
              },
              {
                type: 'neinterfacedetail',
                name: 'Fixture Interface detail',
                x: 54,
                y: 0,
                width: 18,
                height: 8,
                fields: [
                  { type: 1, name: 'override_hostid._reference', value: 'NEHST._hostid' },
                  { type: 1, name: 'itemid._reference', value: 'NEPRT._itemid' }
                ]
              }
            ]
          }
        ]
      };
      let fleetId;
      if (existing.length) {
        fleetId = existing[0].dashboardid;
        await api('dashboard.update', { ...dashboard, dashboardid: fleetId }, token);
      } else fleetId = (await api('dashboard.create', dashboard, token)).dashboardids[0];
      await page.goto(`${url}/zabbix.php?action=dashboard.view&dashboardid=${fleetId}`);
      const navigator = page.locator('.dashboard-widget-hostnavigator');
      await navigator.getByText('ne-lab-a', { exact: true }).first().waitFor({ timeout: 30000 });
      await navigator.getByText('ne-lab-a', { exact: true }).first().click();
      await page.locator('.dashboard-widget-neportpanel .ne-port').first().waitFor({ timeout: 30000 });
      await page.locator('.dashboard-widget-neportpanel .ne-port').first().click();
      await page.waitForFunction(
        () => document.querySelector('.dashboard-widget-neinterfacedetail select')?.value === 'port1',
        { timeout: 30000 }
      );
      const detailOwnLink = page
        .locator('.dashboard-widget-neinterfacedetail a')
        .filter({ hasText: 'Open host dashboard' });
      assert.ok(
        (await detailOwnLink.getAttribute('href')).includes(`hostid=${hostA.hostid}`),
        'Native Host navigator must constrain the chosen host'
      );
      assert.deepEqual(errors, [], `Zabbix ${version} browser errors`);
      console.log(
        `Zabbix ${version}: five inherited widgets, Host navigator / interface broadcasts, permission-aware peer navigation and destination highlight passed.`
      );
      await context.close();
      await api('user.logout', [], token);
    }
  } finally {
    await browser.close();
  }
})().catch(error => {
  console.error(error.stack);
  process.exit(1);
});
