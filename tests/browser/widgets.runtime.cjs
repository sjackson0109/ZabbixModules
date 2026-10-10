/** Actual Chromium DOM and accessibility smoke checks for the self-hosted renderer.
 * Run with Playwright installed externally; no runtime library is added to the widgets.
 */
const { chromium } = require('playwright');
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
(async () => {
  const browser = await chromium.launch({
    headless: true,
    executablePath: process.env.NE_CHROMIUM || undefined,
    args: process.env.NE_CHROMIUM ? ['--no-sandbox', '--disable-dev-shm-usage'] : []
  });
  try {
    const page = await browser.newPage({ viewport: { width: 1500, height: 900 } });
    const errors = [];
    page.on('pageerror', e => errors.push(e.message));
    await page.setContent(
      '<!doctype html><html><head><title>Network Explorer browser fixture</title></head><body><div id="widget" class="ne-widget"></div></body></html>'
    );
    await page.addStyleTag({ path: path.join(__dirname, '../../src/widget/widget.css') });
    await page.addScriptTag({ path: path.join(__dirname, '../../src/widget/runtime.js') });
    // Synthetic schema fixtures only; this test makes no vendor qualification claim.
    const payload = {
      scope: { hostid: '101', layout: '24' },
      hosts: [
        { hostid: '101', name: 'Fixture switch A', dashboard_url: 'zabbix.php?action=host.dashboard.view&hostid=101' },
        { hostid: '102', name: 'Fixture switch B', dashboard_url: 'zabbix.php?action=host.dashboard.view&hostid=102' }
      ],
      interfaces: Array.from({ length: 48 }, (_, i) => ({
        hostid: '101',
        uid: `port:${i + 1}`,
        if_index: i + 1,
        name: `Eth${i + 1}`,
        description: i === 0 ? '<img src=x onerror="window.injected=1">' : 'Fixture interface',
        physical: true,
        member: i < 24 ? 1 : 2,
        slot: 0,
        port: (i % 24) + 1,
        admin_status: 'up',
        oper_status: i === 2 ? 'down' : 'up',
        speed_bps: 1e9,
        expected_speed_bps: i === 1 ? 1e10 : null,
        itemid: String(1000 + i)
      })),
      edges: [
        {
          id: 'one',
          source: '101',
          target: '102',
          source_uid: 'port:1',
          target_uid: 'peer:1',
          source_endpoint: { hostid: '101', uid: 'port:1' },
          target_endpoint: { hostid: '102', uid: 'peer:1' },
          confidence: 'high',
          freshness: 'current',
          lag_id: 'lag-one'
        },
        {
          id: 'two',
          source: '101',
          target: '102',
          source_uid: 'port:2',
          target_uid: 'peer:2',
          lag_id: 'lag-one',
          confidence: 'high',
          freshness: 'current'
        }
      ],
      lags: [
        {
          id: 'lag-one',
          hostid: '101',
          uid: 'lag:1',
          name: 'Fixture LAG',
          mode: 'static',
          members: [{ interface_uid: 'port:1' }, { interface_uid: 'port:2' }]
        }
      ],
      quality: [
        {
          hostid: '101',
          dataset: 'interfaces',
          status: 'ok',
          freshness: 'current',
          capability: { state: 'supported' },
          observed_at: '2026-10-06T00:00:00Z',
          attempted_at: '2026-10-06T00:00:00Z',
          complete: true
        },
        {
          hostid: '101',
          dataset: 'lldp',
          status: 'partial',
          freshness: 'stale',
          capability: { state: 'partial' },
          observed_at: '2026-10-05T00:00:00Z',
          complete: false
        }
      ],
      findings: [
        {
          hostid: '101',
          rule: 'speed',
          severity: 'info',
          title: '=Unsafe spreadsheet formula',
          interface_uid: 'port:2',
          reason: 'Intended speed observation.'
        },
        {
          hostid: '101',
          rule: 'csv-fixture',
          severity: 'info',
          title: ' =Unsafe spreadsheet formula after space',
          reason: 'Whitespace fixture.'
        }
      ]
    };
    await page.evaluate(p => {
      window.testPayload = p;
      window.testBroadcasts = [];
      window.NEWidgetRuntime.render(document.querySelector('#widget'), p, 'ports', (h, i) =>
        window.testBroadcasts.push([h, i])
      );
    }, payload);
    assert.equal(await page.locator('.ne-port').count(), 48);
    await page.locator('.ne-port').first().click();
    assert.ok((await page.locator('.ne-drawer').innerText()).includes('<img src=x onerror='));
    assert.equal(await page.locator('.ne-drawer img').count(), 0);
    assert.ok((await page.locator('#widget').innerText()).includes('LAG Fixture LAG · Static · 2 observed members.'));
    assert.equal(await page.evaluate(() => window.injected), undefined);
    assert.equal(await page.locator('.ne-port').first().getAttribute('aria-pressed'), 'true');
    const link = page.getByRole('link', { name: 'Fixture switch B' });
    assert.equal(await link.count(), 1);
    assert.ok((await link.getAttribute('href')).includes('#ne='));
    await page.locator('.ne-port').first().focus();
    await page.keyboard.press('ArrowRight');
    assert.equal(
      await page
        .locator('.ne-port')
        .nth(1)
        .evaluate(e => e === document.activeElement),
      true
    );
    for (const layout of ['48', 'mixed', 'stack', 'generic']) {
      await page.getByRole('combobox', { name: 'Physical layout' }).selectOption(layout);
      assert.equal(await page.locator('.ne-port').count(), layout === 'stack' ? 24 : 48);
      assert.equal(await page.getByRole('tab').count(), layout === 'stack' ? 2 : 0);
    }
    assert.ok((await page.locator('#widget').innerText()).includes('VLAN collection: not collected'));
    await page.evaluate(() => {
      const p = window.testPayload;
      p.hosts[0].vlans = [
        { vlan_id: 10, name: 'Users' },
        { vlan_id: 49, name: 'Wireless' }
      ];
      p.hosts[1].vlans = [{ vlan_id: 10, name: 'Users' }];
      p.interfaces[0].vlan = {
        mode: 'trunk',
        pvid: 1,
        carried: '1,10,49',
        tagged: '10,49',
        untagged: '1',
        forbidden: ''
      };
      p.interfaces[1].vlan = { mode: 'access', pvid: 10, carried: '10', tagged: '', untagged: '10', forbidden: '' };
      p.interfaces[0].stp = [{ instance: 0, role: 'alternate', role_source: 'derived', state: 'blocking' }];
      p.edges[0].vlan = { common: '10', source_only: '49', target_only: '', source_pvid: 1, target_pvid: 1 };
      p.edges[1].vlan = { common: '10', source_only: '', target_only: '', source_pvid: 10, target_pvid: 10 };
      p.edges[0].stp = {
        source: { role: 'alternate', state: 'blocking' },
        target: { role: 'designated', state: 'forwarding' },
        blocked: true
      };
      window.NEWidgetRuntime.render(document.querySelector('#widget'), p, 'ports', () => {});
    });
    await page.getByRole('combobox', { name: 'Layer' }).selectOption('vlan');
    await page.getByRole('combobox', { name: 'VLAN', exact: true }).selectOption('49');
    assert.ok((await page.locator('.ne-port').nth(0).innerText()).includes('Trunk (tagged)'));
    assert.ok((await page.locator('.ne-port').nth(1).innerText()).includes('Unrelated'));
    await page.getByRole('combobox', { name: 'Layer' }).selectOption('stp');
    assert.ok((await page.locator('.ne-port').nth(0).innerText()).includes('blocking'));
    await page.evaluate(() =>
      window.NEWidgetRuntime.render(document.querySelector('#widget'), window.testPayload, 'topology', (h, i) =>
        window.testBroadcasts.push([h, i])
      )
    );
    assert.equal(await page.locator('svg .ne-node').count(), 2);
    assert.equal(await page.locator('svg .ne-edge').count(), 1);
    await page.getByRole('combobox', { name: 'View' }).selectOption('vlan');
    await page.getByRole('combobox', { name: 'VLAN', exact: true }).selectOption('49');
    await page.getByRole('combobox', { name: 'Trace VLAN from' }).selectOption('101');
    assert.equal(await page.locator('svg .ne-edge-vlan-stopped').count(), 1);
    assert.ok((await page.locator('#widget').innerText()).includes('VLAN 49 stops at Fixture switch B'));
    await page.getByRole('combobox', { name: 'View' }).selectOption('physical');
    assert.ok((await page.locator('svg').textContent()).includes('LAG ×2 · Static'));
    await page.locator('svg .ne-edge').first().focus();
    await page.keyboard.press('Enter');
    assert.ok((await page.locator('#widget').innerText()).includes('LAG member links (Static)'));
    await page.getByRole('button', { name: 'Expand LAG member links' }).click();
    assert.equal(await page.locator('svg .ne-edge').count(), 2);
    await page.locator('svg .ne-node').first().focus();
    await page.keyboard.press('Enter');
    assert.ok((await page.locator('.ne-drawer').innerText()).includes('Fixture switch A'));
    assert.equal(await page.locator('svg .ne-node').first().getAttribute('aria-pressed'), 'true');
    assert.ok((await page.locator('.ne-drawer').innerText()).includes('Interfaces (48)'));
    // A link end selects that exact interface and broadcasts its item to linked widgets.
    await page.locator('svg .ne-edge').first().focus();
    await page.keyboard.press('Enter');
    await page.evaluate(() => (window.testBroadcasts.length = 0));
    await page.getByRole('button', { name: 'Select interface Fixture switch A Eth1' }).click();
    assert.ok((await page.locator('.ne-drawer').innerText()).includes('Eth1 ·'));
    assert.deepEqual(await page.evaluate(() => window.testBroadcasts), [['101', '1000']]);
    assert.equal(await page.locator('svg .ne-edge-selected').count(), 1);
    // The selected interface's own end of its link carries a ring, not only a colour change.
    assert.equal(await page.locator('svg .ne-endpoint-selected').count(), 1);
    // Fit, zoom, reset and keyboard alternatives work on the drawing's viewBox, never the page.
    const svgView = () => page.locator('svg.ne-topology').getAttribute('viewBox');
    const zoom = async () => Number(await page.locator('svg.ne-topology').getAttribute('data-zoom'));
    const home = await svgView();
    await page.getByRole('button', { name: 'Zoom in' }).click();
    assert.ok((await zoom()) > 1);
    await page.getByRole('button', { name: 'Zoom out' }).click();
    await page.getByRole('button', { name: 'Zoom out' }).click();
    assert.ok((await zoom()) < 1);
    await page.getByRole('button', { name: 'Reset view' }).click();
    assert.equal(await svgView(), home);
    await page.getByRole('button', { name: 'Fit topology' }).click();
    assert.notEqual(await svgView(), home);
    await page.getByRole('region', { name: /Topology canvas/ }).focus();
    await page.keyboard.press('0');
    assert.equal(await svgView(), home);
    await page.keyboard.press('+');
    assert.ok((await zoom()) > 1);
    const zoomed = await svgView();
    await page.keyboard.press('ArrowRight');
    assert.notEqual(await svgView(), zoomed);
    // The view survives a redraw such as a view change, and a switch never moves with it.
    const positionOf = () => page.locator('svg .ne-node').first().getAttribute('transform');
    const placedAt = await positionOf();
    const panned = await svgView();
    // Layer 2 and VLAN share a placement and a view; Spanning Tree has its own; returning restores both.
    for (const view of ['vlan', 'stp', 'physical']) {
      await page.getByRole('combobox', { name: 'View' }).selectOption(view);
      if (view === 'stp') continue;
      assert.equal(await svgView(), panned);
      assert.equal(await positionOf(), placedAt);
    }
    await page.keyboard.press('0');
    // Selection, search, LAG collapse and VLAN trace restyle the drawing but never re-place a switch.
    const allPositions = () => page.locator('svg .ne-node').evaluateAll(n => n.map(g => g.getAttribute('transform')).join('|'));
    const layoutBefore = await allPositions();
    await page.locator('svg .ne-node').nth(1).click();
    const halo = page.locator('svg .ne-node-selected .ne-node-halo');
    assert.notEqual(await halo.evaluate(e => getComputedStyle(e).display), 'none', 'selected switch has a second outline');
    await page.getByPlaceholder('Find visible host').fill('switch B');
    assert.equal(await page.locator('svg .ne-node.ne-muted').count(), 1);
    await page.getByPlaceholder('Find visible host').fill('');
    await page.getByRole('button', { name: 'Collapse LAG member links' }).click();
    await page.locator('svg .ne-edge').first().focus();
    await page.keyboard.press('Enter');
    assert.equal(await page.locator('svg .ne-link-end-selected').count(), 2, 'a selected link is marked at both ends');
    assert.equal(await page.locator('svg .ne-endpoint-selected').count(), 0);
    await page.getByRole('button', { name: 'Expand LAG member links' }).click();
    await page.getByRole('combobox', { name: 'View' }).selectOption('vlan');
    await page.getByRole('combobox', { name: 'Trace VLAN from' }).selectOption('101');
    await page.getByRole('combobox', { name: 'View' }).selectOption('physical');
    assert.equal(await allPositions(), layoutBefore);
    // The legend lists only what this drawing shows.
    const legendText = await page.getByRole('list', { name: 'Topology legend' }).innerText();
    assert.ok(legendText.includes('Confirmed link'), legendText);
    assert.ok(!legendText.includes('VLAN') && !legendText.includes('root'), legendText);
    // The default Layer 2 view marks a current, agreed root; disagreement marks none.
    await page.evaluate(() => {
      const p = window.testPayload;
      p.hosts[0].domain = p.hosts[1].domain = 'fixture';
      p.hosts[0].stp = [{ instance: 0, bridge_id: '8000.a', root_bridge_id: '8000.b', is_root: false }];
      p.hosts[1].stp = [{ instance: 0, bridge_id: '8000.b', root_bridge_id: '8000.b', is_root: true }];
      p.quality.push({ hostid: '102', dataset: 'stp', status: 'ok', freshness: 'current' });
      window.NEWidgetRuntime.render(document.querySelector('#widget'), p, 'topology', () => {});
    });
    assert.equal(await page.getByRole('combobox', { name: 'View' }).inputValue(), 'physical');
    assert.ok((await page.locator('svg .ne-node-root').getAttribute('aria-label')).startsWith('Fixture switch B'));
    // The observed root heads the layout although switch A is first by name.
    const nodeY = name =>
      page
        .locator('svg .ne-node', { hasText: name })
        .getAttribute('transform')
        .then(t => Number(/,([-\d.]+)\)/.exec(t)[1]));
    assert.ok((await nodeY('Fixture switch B')) < (await nodeY('Fixture switch A')));
    assert.ok((await page.getByRole('list', { name: 'Topology legend' }).innerText()).includes('Observed spanning-tree root (agreed within its domain)'));
    // Selecting the root keeps its root marking alongside the selection.
    await page.locator('svg .ne-node-root').click();
    assert.equal(await page.locator('svg .ne-node-root.ne-node-selected').count(), 1);
    assert.ok((await page.locator('svg .ne-node-root').textContent()).startsWith('★'));
    // Spanning Tree: A has no observed root port yet, so it is kept apart and labelled, never given a parent.
    await page.getByRole('combobox', { name: 'View' }).selectOption('stp');
    assert.equal(await page.locator('svg .ne-node-unresolved').count(), 1);
    assert.ok((await page.locator('svg').textContent()).includes('Unresolved STP placement'));
    assert.ok((await nodeY('Fixture switch A')) > (await nodeY('Fixture switch B')) + 120);
    assert.equal(await page.locator('svg .ne-stp-block-mark').count(), 1, 'the blocked link is still drawn');
    await page.evaluate(() => {
      const p = window.testPayload;
      p.edges[1].stp = { source: { role: 'root', state: 'forwarding' }, target: { role: 'designated', state: 'forwarding' } };
      window.NEWidgetRuntime.render(document.querySelector('#widget'), p, 'topology', () => {}, { mode: 'stp' });
    });
    await page.getByRole('combobox', { name: 'View' }).selectOption('stp');
    assert.equal(await page.locator('svg .ne-node-unresolved').count(), 0);
    assert.equal(await page.locator('svg .ne-stp-block-mark').count(), 1);
    // A root-port child sits directly below its parent.
    assert.equal((await nodeY('Fixture switch A')) - (await nodeY('Fixture switch B')), 120);
    await page.evaluate(() => {
      delete window.testPayload.edges[1].stp;
    });
    await page.getByRole('combobox', { name: 'View' }).selectOption('physical');
    await page.evaluate(() => {
      const p = window.testPayload;
      p.hosts[0].stp = [{ instance: 0, bridge_id: '8000.a', root_bridge_id: '8000.a', is_root: true }];
      window.NEWidgetRuntime.render(document.querySelector('#widget'), p, 'topology', () => {}, { mode: 'physical' });
    });
    assert.equal(await page.locator('svg .ne-node-root').count(), 0);
    assert.ok((await page.locator('#widget').innerText()).includes('disagree about the spanning-tree root'));
    await page.getByRole('combobox', { name: 'View' }).selectOption('stp');
    assert.equal(await page.locator('svg .ne-node-root').count(), 0);
    assert.equal(await page.locator('svg .ne-node-root-disputed').count(), 2);
    // A large estate on a narrow screen: separated components, a capped row width and no sideways page scroll.
    await page.setViewportSize({ width: 700, height: 900 });
    await page.evaluate(() => {
      const hosts = Array.from({ length: 60 }, (_, i) => ({ hostid: String(500 + i), name: `Scale ${i + 1}` }));
      const edges = hosts.slice(1, 40).map((h, i) => ({
        id: `s${i}`,
        source: hosts[Math.floor(i / 3)].hostid,
        target: h.hostid,
        source_uid: `u${i}`,
        target_uid: `v${i}`,
        confidence: 'high',
        freshness: 'current'
      }));
      window.NEWidgetRuntime.render(
        document.querySelector('#widget'),
        { scope: {}, hosts, interfaces: [], edges, lags: [], quality: [], findings: [] },
        'topology',
        () => {}
      );
    });
    assert.equal(await page.locator('svg .ne-node').count(), 60);
    // One linked network and 20 unlinked switches are 21 components, though the unlinked ones share a block.
    assert.ok((await page.locator('svg.ne-topology').getAttribute('aria-label')).endsWith('60 permitted devices, 21 groups of connected devices'));
    // No two switch boxes overlap, across separate components and the unlinked block.
    const centres = await page
      .locator('svg .ne-node')
      .evaluateAll(n => n.map(g => /translate\(([-\d.]+),([-\d.]+)\)/.exec(g.getAttribute('transform')).slice(1).map(Number)));
    for (let i = 0; i < centres.length; i++)
      for (let j = i + 1; j < centres.length; j++)
        assert.ok(
          Math.abs(centres[i][0] - centres[j][0]) >= 180 || Math.abs(centres[i][1] - centres[j][1]) >= 50,
          `switch boxes ${i} and ${j} overlap`
        );
    assert.ok(
      await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth),
      'the topology must not widen the page'
    );
    await page.setViewportSize({ width: 1500, height: 900 });
    // The Explorer page: one selection panel, findings and quality of the same payload, nothing broadcast.
    await page.evaluate(() => {
      const p = window.testPayload;
      p.hosts[0].stp = [{ instance: 0, bridge_id: '8000.a', root_bridge_id: '8000.b', is_root: false }];
      p.scope = { management_cidrs: ['192.0.2.0/24'] };
      window.testExplorer = window.NEWidgetRuntime.mountExplorer(document.querySelector('#widget'), p, {
        view: 'layer2',
        interface_hostid: '101',
        interface_uid: 'port:3'
      });
    });
    const selection = page.locator('.ne-explorer-selection');
    assert.ok((await selection.innerText()).includes('Eth3 ·'), 'A deep-linked interface opens selected');
    assert.equal(await selection.getByRole('button', { name: 'Select interface in linked widgets' }).count(), 0);
    assert.ok((await page.locator('svg .ne-node-root').getAttribute('aria-label')).startsWith('Fixture switch B'));
    await page.locator('svg .ne-node', { hasText: 'Fixture switch B' }).click();
    assert.ok((await selection.innerText()).includes('Root bridge 8000.b'));
    assert.equal(await page.evaluate(() => window.testExplorer.selection.kind), 'host');
    await page.locator('.ne-explorer-findings').getByRole('button', { name: 'Fixture switch A' }).first().click();
    assert.ok((await selection.locator('h4').first().innerText()).includes('Fixture switch A'));
    assert.equal(await page.locator('.ne-explorer-quality tbody tr').count(), 3);
    await page.evaluate(() =>
      window.NEWidgetRuntime.render(document.querySelector('#widget'), window.testPayload, 'quality')
    );
    assert.equal(await page.locator('tbody tr').count(), 3);
    assert.ok((await page.locator('#widget').innerText()).includes('partial'));
    await page.evaluate(() =>
      window.NEWidgetRuntime.render(document.querySelector('#widget'), window.testPayload, 'findings')
    );
    const downloadEvent = page.waitForEvent('download');
    await page.getByRole('button', { name: 'Export filtered CSV' }).click();
    const download = await downloadEvent;
    const stream = await download.createReadStream();
    let csv = '';
    for await (const chunk of stream) csv += chunk.toString('utf8');
    assert.ok(csv.includes("'=Unsafe spreadsheet formula"));
    assert.ok(csv.includes("' =Unsafe spreadsheet formula after space"));
    // Stack members as tabs, ENTITY-MIB placement headings and configured colours.
    await page.evaluate(() => {
      const ports = [];
      for (const member of [1, 2])
        for (let p = 1; p <= 4; p++)
          ports.push({
            hostid: '101',
            uid: `m${member}p${p}`,
            name: `Gi${member}/0/${p}`,
            physical: true,
            member,
            slot: 0,
            port: p,
            media: 'copper',
            admin_status: 'up',
            oper_status: p === 4 ? 'down' : 'up',
            speed_bps: 1e9
          });
      ports.push({
        hostid: '101',
        uid: 'loose',
        name: 'Te9',
        physical: true,
        admin_status: 'up',
        oper_status: 'up',
        speed_bps: 1e10
      });
      window.NEWidgetRuntime.render(
        document.querySelector('#widget'),
        {
          scope: { hostid: '101', layout: 'auto', colours: { normal: '123456', down: 'not-a-colour' } },
          hosts: [{ hostid: '101', name: 'Stack' }],
          interfaces: ports,
          edges: [],
          lags: [],
          quality: [],
          findings: []
        },
        'ports',
        () => {}
      );
    });
    const tabs = page.getByRole('tab');
    assert.deepEqual(await tabs.allInnerTexts(), ['Member 1', 'Member 2', 'Unplaced ports']);
    assert.equal(await page.locator('.ne-port').count(), 4);
    assert.ok((await page.locator('.ne-port-member h4').innerText()).includes('Member 1 · slot 0'));
    await page.getByRole('tab', { name: 'Member 2' }).click();
    assert.equal(await page.getByRole('tab', { name: 'Member 2' }).getAttribute('aria-selected'), 'true');
    assert.ok((await page.locator('.ne-port').first().innerText()).includes('Gi2/0/1'));
    await page.keyboard.press('ArrowRight');
    assert.ok((await page.locator('.ne-port').first().innerText()).includes('Te9'));
    assert.equal(
      await page
        .locator('.ne-widget')
        .first()
        .evaluate(e => e.style.getPropertyValue('--ne-colour-normal')),
      '#123456'
    );
    assert.equal(
      await page
        .locator('.ne-widget')
        .first()
        .evaluate(e => e.style.getPropertyValue('--ne-colour-down')),
      ''
    );
    await page.getByRole('combobox', { name: 'Physical layout' }).selectOption('mixed');
    assert.equal(await page.getByRole('tab').count(), 0);
    assert.ok((await page.locator('#widget').innerText()).includes('Member 2 · slot 0 · Copper'));
    assert.deepEqual(errors, []);
    console.log(
      'Chromium: Explorer page selection, Layer 2 root marker and root-first layout, topology fit/zoom/reset with keyboard, legend, endpoint ring, no page overflow, link-end selection, physical, VLAN and STP layers, stack member tabs, state colours, VLAN trace, physical layouts, safe detail rendering, keyboard navigation, peer context, LAG expansion, quality and CSV export passed.'
    );
  } finally {
    await browser.close();
  }
})().catch(e => {
  console.error(e.stack);
  process.exit(1);
});
