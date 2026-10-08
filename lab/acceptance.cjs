/** LAB ONLY: the spec's acceptance walkthrough (docs/design/07-test-plan.md) against the native SNMP lab.
 * The network-wide journey runs on Monitoring -> Network Explorer and needs no global dashboard; host dashboards
 * cover one switch. A separate, clearly named widget fixture checks the Topology widget on a user-made dashboard.
 * Prerequisites, per version: lab.py start, an SNMP simulator serving tests/fixtures/walks, then
 * native_snmp.py import, hosts, poll; lab.py install-modules; native_snmp.py dashboard and viewer.
 * Usage: node lab/acceptance.cjs 7.0 [--outage]   (--outage expects sw-access-17 broken via native_snmp.py break)
 * Reads generated lab credentials only and never prints them.
 */
const { chromium } = require('playwright');
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const version = process.argv[2] || '7.0',
  outage = process.argv.includes('--outage');
const port = { '7.0': 18070, 7.2: 18072, 7.4: 18074 }[version];
if (!port) throw new Error('Unsupported lab version');
const url = `http://127.0.0.1:${port}`,
  state = path.join(__dirname, '.state', version);
const admin = JSON.parse(fs.readFileSync(path.join(state, 'credentials.json'))).admin;
const viewer = JSON.parse(fs.readFileSync(path.join(state, 'viewer.json')));
const HIDDEN = ['sw-dist-01', '10.102.5.10', 'lab-west'];
// Earlier lab runs made this global dashboard the fleet view; it is deleted so nothing below can depend on it.
const RETIRED_FLEET = 'Network Explorer fleet (lab)';
const WIDGET_FIXTURE = 'Network Explorer widget fixture (lab test only)';
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
async function login(browser, username, password) {
  const page = await (await browser.newContext({ viewport: { width: 1700, height: 1200 } })).newPage(),
    errors = [];
  page.on('pageerror', e => errors.push(e.message));
  await page.goto(url + '/index.php');
  await page.locator('#name').fill(username);
  await page.locator('#password').fill(password);
  await page.locator('#enter').click();
  await page.waitForURL(/zabbix\.php/, { timeout: 30000 });
  return { page, errors };
}
/** Opens Monitoring -> Network Explorer with optional scope parameters and waits for the topology. */
async function explorer(page, params = {}) {
  const query = new URLSearchParams({ action: 'networkexplorer.view', ...params });
  await page.goto(`${url}/zabbix.php?${query}`);
  const app = page.locator('#ne-explorer-app');
  await app.locator('svg .ne-node').first().waitFor({ timeout: 60000 });
  return app;
}
const nodeNames = async app =>
  (await app.locator('svg .ne-node').evaluateAll(nodes => nodes.map(n => n.querySelector('title').textContent))).sort();
const tableHosts = async locator =>
  [...new Set(await locator.locator('tbody tr td:first-child').allInnerTexts())].sort();
async function exported(page, report, params) {
  const query = new URLSearchParams({ action: 'networkexplorer.export', report, format: 'json', ...params });
  return (await page.request.get(`${url}/zabbix.php?${query}`)).json();
}
const steps = [];
const step = name => {
  steps.push(name);
  console.log('ok', steps.length, name);
};
(async () => {
  const token = await api('user.login', { username: 'Admin', password: admin });
  const hosts = Object.fromEntries(
    (
      await api(
        'host.get',
        {
          output: ['hostid', 'host'],
          filter: { host: ['sw-core-01', 'sw-access-17', 'sw-dist-01', 'sw-dist-02', 'sw-stack-01'] }
        },
        token
      )
    ).map(h => [h.host, h.hostid])
  );
  assert.equal(Object.keys(hosts).length, 5, 'Create the five lab switches first');
  const ALL = ['sw-access-17', 'sw-core-01', 'sw-dist-01', 'sw-dist-02', 'sw-stack-01'];
  const retired = await api('dashboard.get', { output: ['dashboardid'], filter: { name: RETIRED_FLEET } }, token);
  if (retired.length)
    await api(
      'dashboard.delete',
      retired.map(d => d.dashboardid),
      token
    );
  const browser = await chromium.launch({
    headless: true,
    executablePath: process.env.NE_CHROMIUM || undefined,
    args: ['--no-sandbox', '--disable-dev-shm-usage']
  });
  try {
    const { page, errors } = await login(browser, 'Admin', admin);
    if (!outage) {
      // Host dashboards: one switch.
      await page.goto(`${url}/zabbix.php?action=host.dashboard.view&hostid=${hosts['sw-core-01']}`);
      const panel = page.locator('.dashboard-widget-neportpanel');
      await panel.locator('.ne-port').first().waitFor({ timeout: 60000 });
      const amber = panel.locator('.ne-port.ne-state-speed_observation', { hasText: 'Gi1/0/23' });
      assert.equal(await amber.count(), 1);
      step('Host dashboard: sw-core-01 Gi1/0/23 is amber (below expected speed)');
      await amber.click();
      const drawer = panel.locator('.ne-drawer');
      assert.ok((await drawer.innerText()).includes('negotiable') || (await drawer.innerText()).includes('policy'));
      await drawer.getByRole('link', { name: 'sw-access-17' }).click();
      const remote = page.locator('.dashboard-widget-neportpanel');
      await remote.locator('.ne-port[aria-pressed="true"]').waitFor({ timeout: 60000 });
      assert.ok((await remote.locator('.ne-port[aria-pressed="true"]').innerText()).includes('Gi1/0/48'));
      assert.ok((await remote.locator('.ne-drawer').innerText()).includes('Navigated from Gi1/0/23'));
      step('Host dashboard: peer navigation highlights sw-access-17 Gi1/0/48');
      await page.goto(`${url}/zabbix.php?action=host.dashboard.view&hostid=${hosts['sw-stack-01']}`);
      const stack = page.locator('.dashboard-widget-neportpanel');
      await stack.locator('.ne-port').first().waitFor({ timeout: 60000 });
      assert.deepEqual(await stack.getByRole('tab').allInnerTexts(), ['Member 1', 'Member 2']);
      assert.deepEqual(await stack.locator('.ne-port-member h4').allInnerTexts(), [
        'Member 1 · slot 0',
        'Member 1 · slot 1'
      ]);
      await stack.getByRole('tab', { name: 'Member 2' }).click();
      assert.ok((await stack.locator('.ne-port').first().innerText()).includes('Gi2/0/1'));
      await stack.getByRole('combobox', { name: 'Physical layout' }).selectOption('mixed');
      assert.ok((await stack.innerText()).includes('Member 2 · slot 1 · SFP+'));
      step('Host dashboard: sw-stack-01 shows two member tabs; SFP+ cages grouped apart');
      await stack.locator('.ne-port', { hasText: 'Te2/1/1' }).click();
      assert.ok((await stack.innerText()).includes('LAG Po1 · Static · 2 observed members.'));
      step('Host dashboard: sw-stack-01 Po1 is a static LAG over Te1/1/1 and Te2/1/1');

      // Monitoring -> Network Explorer: the network-wide view, with no global dashboard.
      await page.goto(`${url}/zabbix.php?action=problem.view`);
      await page.locator('a[href$="action=networkexplorer.view"]').first().click();
      await page.waitForURL(/action=networkexplorer\.view/);
      const app = page.locator('#ne-explorer-app');
      await app.locator('svg .ne-node').first().waitFor({ timeout: 60000 });
      assert.deepEqual(await nodeNames(app), ALL);
      assert.equal(
        (await api('dashboard.get', { output: ['name'] }, token)).filter(d => /Network Explorer/.test(d.name)).length,
        (await api('dashboard.get', { output: ['name'], filter: { name: WIDGET_FIXTURE } }, token)).length,
        'No Network Explorer global dashboard other than the widget fixture exists'
      );
      step('Monitoring -> Network Explorer, no parameters: all five switches, no global dashboard');
      const view = app.getByRole('combobox', { name: 'View' });
      assert.equal(await view.inputValue(), 'physical');
      assert.equal((await view.locator('option:checked').innerText()).trim(), 'Layer 2');
      assert.ok((await app.locator('svg .ne-node-root').getAttribute('aria-label')).startsWith('sw-dist-02'));
      assert.equal(await app.locator('svg .ne-node-root').count(), 1);
      assert.equal(await app.locator('svg .ne-edge-stp-blocked').count(), 0);
      step('Default view is Layer 2 and marks the observed STP root sw-dist-02 (★)');
      const labels = await app.locator('svg').textContent();
      assert.equal(await app.locator('svg .ne-edge').count(), 5);
      assert.ok(labels.includes('LAG ×2 · LACP') && labels.includes('LAG ×2 · Static'));
      await app.getByRole('button', { name: 'Expand LAG member links' }).click();
      assert.equal(await app.locator('svg .ne-edge').count(), 7);
      await app.getByRole('button', { name: 'Collapse LAG member links' }).click();
      step('LAGs are one logical link each (LACP and static), with two members when expanded');
      await view.selectOption('stp');
      assert.ok((await app.locator('svg .ne-node-root').getAttribute('aria-label')).startsWith('sw-dist-02'));
      assert.equal(await app.locator('svg .ne-edge-stp-blocked').count(), 1);
      assert.equal(await app.locator('svg .ne-stp-block-mark').count(), 1);
      assert.ok((await app.locator('svg .ne-edge-stp-rootpath').count()) >= 1);
      assert.ok(page.url().includes('view=stp'));
      step('Spanning Tree view: root, root-path links and one blocking port end');
      await view.selectOption('vlan');
      await app.getByRole('combobox', { name: 'VLAN', exact: true }).selectOption('49');
      await app.getByRole('combobox', { name: 'Trace VLAN from' }).selectOption(hosts['sw-access-17']);
      assert.ok((await app.innerText()).includes('VLAN 49 stops at sw-core-01 port Gi1/0/23'));
      assert.equal(await app.locator('svg .ne-edge-trace-stop').count(), 1);
      assert.ok(page.url().includes('view=vlan') && page.url().includes('vlan=49'));
      step('VLAN view: VLAN 49 traced from sw-access-17 stops at sw-core-01 Gi1/0/23');
      await view.selectOption('physical');
      const selection = page.locator('.ne-explorer-selection');
      await app.locator('svg .ne-node', { hasText: 'sw-core-01' }).click();
      assert.equal(await app.locator('svg .ne-node-selected').count(), 1);
      assert.ok((await selection.innerText()).includes('Interfaces ('));
      assert.equal(await selection.getByRole('link', { name: 'Open host dashboard' }).count(), 1);
      assert.ok(!page.url().includes('interface_uid'), 'Selecting a switch selects no interface');
      step('Selecting sw-core-01 shows its identity, health, interfaces and host dashboard link');
      const link = app.locator('svg line.ne-edge[aria-label*="sw-access-17"]');
      await link.focus();
      await page.keyboard.press('Enter');
      assert.equal(await link.getAttribute('aria-pressed'), 'true');
      const ends = selection.locator('button.ne-endpoint');
      assert.deepEqual((await ends.allInnerTexts()).sort(), ['Gi1/0/23', 'Gi1/0/48']);
      step('Selecting the sw-core-01 to sw-access-17 link shows both endpoint interfaces');
      await selection.getByRole('button', { name: 'Select interface sw-access-17 Gi1/0/48' }).click();
      const detail = await selection.innerText();
      assert.ok(detail.includes('Gi1/0/48') && detail.includes('sw-access-17') && detail.includes('Observed speed'));
      assert.ok(
        page.url().includes('interface_uid=') && page.url().includes(`interface_hostid=${hosts['sw-access-17']}`)
      );
      await page.reload();
      await app.locator('svg .ne-node').first().waitFor({ timeout: 60000 });
      assert.ok((await selection.innerText()).includes('Gi1/0/48'), 'The interface selection survives a reload');
      step('Selecting the endpoint shows sw-access-17 Gi1/0/48 in Interface Detail, bookmarkable');
      await selection.getByRole('link', { name: 'Open host dashboard with this port highlighted' }).click();
      const target = page.locator('.dashboard-widget-neportpanel');
      await target.locator('.ne-port[aria-pressed="true"]').waitFor({ timeout: 60000 });
      assert.ok(page.url().includes(`hostid=${hosts['sw-access-17']}`));
      assert.ok((await target.locator('.ne-port[aria-pressed="true"]').innerText()).includes('Gi1/0/48'));
      step('Open host dashboard reaches the inherited sw-access-17 dashboard with Gi1/0/48 selected');
      let scoped = await explorer(page, { management_cidr: '10.101.0.0/16' });
      assert.deepEqual(await nodeNames(scoped), ALL);
      assert.ok((await scoped.locator('svg .ne-node-warning').getAttribute('aria-label')).startsWith('sw-dist-01'));
      assert.equal(await scoped.locator('svg .ne-node-warning').count(), 1);
      step('Management subnet 10.101.0.0/16 flags sw-dist-01 and keeps it and its links visible');
      const siteOptions = await page.locator('z-select[name="site"] li').allInnerTexts();
      assert.deepEqual(siteOptions, ['All', 'lab-east', 'lab-west']);
      scoped = await explorer(page, { site: 'lab-west' });
      const west = ['sw-core-01', 'sw-dist-01', 'sw-dist-02'];
      assert.deepEqual(await nodeNames(scoped), west);
      assert.equal(await scoped.locator('svg .ne-node-context').count(), 2);
      const findingHosts = await tableHosts(page.locator('.ne-explorer-findings table'));
      const qualityHosts = await tableHosts(page.locator('.ne-explorer-quality table'));
      assert.ok(findingHosts.every(h => west.includes(h)) && findingHosts.length > 0, findingHosts.join());
      assert.deepEqual(qualityHosts, west);
      const inventory = await exported(page, 'inventory', { site: 'lab-west' });
      assert.deepEqual(inventory.rows.map(r => r.name).sort(), west);
      assert.equal(inventory.scope.site, 'lab-west');
      step('Site lab-west: sw-dist-01 plus its neighbours as context; findings, quality and export match');
      scoped = await explorer(page, { hostid: hosts['sw-access-17'] });
      assert.deepEqual(await nodeNames(scoped), ['sw-access-17', 'sw-core-01']);
      assert.deepEqual(await tableHosts(page.locator('.ne-explorer-quality table')), ['sw-access-17', 'sw-core-01']);
      step('Seed device sw-access-17: itself and its one-hop neighbour');
      // A user-made dashboard still hosts the Topology widget; it is a test fixture, not part of installation.
      let fixture = (
        await api('dashboard.get', { output: ['dashboardid'], filter: { name: WIDGET_FIXTURE } }, token)
      )[0]?.dashboardid;
      if (!fixture)
        fixture = (
          await api(
            'dashboard.create',
            {
              name: WIDGET_FIXTURE,
              private: 0,
              display_period: 30,
              auto_start: 0,
              userGroups: [],
              users: [],
              pages: [
                {
                  widgets: [
                    { type: 'netopology', name: 'Topology', x: 0, y: 0, width: 72, height: 12, fields: [] },
                    { type: 'nefindings', name: 'Findings', x: 0, y: 12, width: 72, height: 7, fields: [] }
                  ]
                }
              ]
            },
            token
          )
        ).dashboardids[0];
      await page.goto(`${url}/zabbix.php?action=dashboard.view&dashboardid=${fixture}`);
      const widget = page.locator('.dashboard-widget-netopology');
      await widget.locator('svg .ne-node').first().waitFor({ timeout: 60000 });
      assert.equal(await widget.locator('svg .ne-node').count(), 5);
      assert.ok((await widget.locator('svg .ne-node-root').getAttribute('aria-label')).startsWith('sw-dist-02'));
      const widgetLink = widget.locator('svg line.ne-edge[aria-label*="sw-access-17"]');
      await widgetLink.focus();
      await page.keyboard.press('Enter');
      await widget.getByRole('button', { name: 'Select interface sw-core-01 Gi1/0/23' }).click();
      assert.ok((await widget.locator('.ne-drawer').innerText()).includes('Select interface in linked widgets'));
      step('Widget fixture: the Topology widget shares the renderer, root marker and endpoint selection');
      assert.deepEqual(errors, []);
      // Permissions.
      const restricted = await login(browser, viewer.username, viewer.password);
      await restricted.page.goto(`${url}/zabbix.php?action=problem.view`);
      assert.equal(await restricted.page.locator('a[href$="action=networkexplorer.view"]').count(), 1);
      const rapp = await explorer(restricted.page);
      assert.deepEqual(await nodeNames(rapp), ['sw-access-17', 'sw-core-01', 'sw-dist-02', 'sw-stack-01']);
      assert.deepEqual(await restricted.page.locator('z-select[name="site"] li').allInnerTexts(), ['All', 'lab-east']);
      for (const params of [
        {},
        { site: 'lab-west' },
        { hostid: hosts['sw-dist-01'] },
        { management_cidr: '10.102.0.0/16' }
      ]) {
        await restricted.page.goto(
          `${url}/zabbix.php?${new URLSearchParams({ action: 'networkexplorer.view', ...params })}`
        );
        const html = await restricted.page.content();
        for (const secret of HIDDEN.slice(0, 2))
          assert.ok(!html.includes(secret), `page ${JSON.stringify(params)} leaks ${secret}`);
      }
      for (const format of ['json', 'csv'])
        for (const report of ['inventory', 'peers', 'findings', 'stp']) {
          const body = await (
            await restricted.page.request.get(
              `${url}/zabbix.php?action=networkexplorer.export&report=${report}&format=${format}`
            )
          ).text();
          for (const secret of HIDDEN) assert.ok(!body.includes(secret), `${report}.${format} leaks ${secret}`);
        }
      const viewerToken = await api('user.login', { username: viewer.username, password: viewer.password });
      assert.ok(!(await api('host.get', { output: ['host'] }, viewerToken)).some(h => h.host === 'sw-dist-01'));
      assert.deepEqual(restricted.errors, []);
      step('Restricted viewer: sw-dist-01 and its site absent from the Explorer page, selectors, API, JSON and CSV');
    } else {
      // A stopped agent.
      const app = await explorer(page);
      assert.ok(
        (await app.locator('svg .ne-node-unreachable').getAttribute('aria-label')).includes('SNMP unreachable')
      );
      assert.ok((await page.locator('.ne-explorer-findings').innerText()).includes('snmp_unreachable'));
      assert.deepEqual(errors, []);
      step('Stopped agent: sw-access-17 shown as SNMP unreachable on Network Explorer');
    }
    await explorer(page);
    await page.screenshot({
      path: path.join(state, outage ? 'acceptance-outage.png' : 'acceptance.png'),
      fullPage: true
    });
    console.log(`Zabbix ${version}: ${steps.length} acceptance steps passed.`);
  } finally {
    await browser.close();
  }
})().catch(e => {
  console.error(e.stack);
  process.exit(1);
});
