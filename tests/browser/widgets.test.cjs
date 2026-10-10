const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { createHash } = require('node:crypto');
const hash = content => createHash('sha256').update(content).digest('hex');
const runtime = require('../../src/widget/runtime.js');
test('physical port state uses explicit intended speed, independent of maximum capability', () => {
  assert.equal(runtime.portState({ admin_status: 'up', oper_status: 'up', speed_bps: 1e9, max_speed_bps: 1e10 }), 'up');
  assert.equal(
    runtime.portState({ admin_status: 1, oper_status: 1, speed_bps: 1e9, expected_speed_bps: 1e10 }),
    'speed_observation',
    'Without a server-assigned state, one low reading is only an observation'
  );
  assert.equal(runtime.portState({ state: 'degraded', speed_bps: 1e9, expected_speed_bps: 1e10 }), 'degraded');
  assert.equal(runtime.portState({ admin_status: 2, oper_status: 2 }), 'disabled');
  assert.equal(runtime.portState({ admin_status: 'up', oper_status: 'down' }), 'down');
  assert.equal(runtime.portState({}), 'unknown');
  assert.equal(runtime.speed(1e9), '1 Gb/s');
});
test('ports retain stack member and slot geometry with natural port order', () => {
  const ports = [
    { name: 'Eth10', member: 1, slot: 0, port: 10 },
    { name: 'Eth2', member: 1, slot: 0, port: 2 },
    { name: 'Eth1', member: 2, slot: 0, port: 1 }
  ];
  const groups = runtime.groupPorts(ports, 'stack');
  assert.equal(groups.length, 2);
  assert.deepEqual(
    groups[0].ports.map(p => p.port),
    [2, 10]
  );
  assert.equal(groups[1].ports[0].member, 2);
  assert.equal(runtime.isPhysical({ type: 'ethernetCsmacd' }), false);
  assert.equal(runtime.isPhysical({ physical: true }), true);
});
const layoutHost = (n, name = 'Switch ' + n) => ({ hostid: String(n), name });
const link = (source, target, stp) => ({ source: String(source), target: String(target), ...(stp ? { stp } : {}) });
const rootPort = (side = 'source') => ({
  [side]: { role: 'root', state: 'forwarding' },
  [side === 'source' ? 'target' : 'source']: { role: 'designated', state: 'forwarding' }
});
const at = placed => Object.fromEntries(placed.map(h => [h.hostid, h]));
const box = (hosts, ids) => {
  const xs = hosts.filter(h => ids.includes(h.hostid));
  return {
    left: Math.min(...xs.map(h => h.x)) - 90,
    right: Math.max(...xs.map(h => h.x)) + 90,
    top: Math.min(...xs.map(h => h.y)) - 25,
    bottom: Math.max(...xs.map(h => h.y)) + 25
  };
};
const apart = (p, q) => p.right < q.left || q.right < p.left || p.bottom < q.top || q.bottom < p.top;
test('layout is deterministic, capped at 300 switches and never stacks two switches', () => {
  const hosts = Array.from({ length: 310 }, (_, i) => layoutHost(i + 1));
  const edges = Array.from({ length: 120 }, (_, i) => link(i + 1, ((i * 7) % 150) + 2));
  const first = runtime.graphLayout(hosts, edges);
  assert.equal(first.length, 300);
  assert.deepEqual(first, runtime.graphLayout(hosts.slice().reverse(), edges.slice().reverse()));
  assert.equal(new Set(first.map(h => `${h.x},${h.y}`)).size, 300);
  // The cap keeps the same switches whatever order they arrive in: natural name order keeps 1–300.
  assert.ok(!first.some(h => Number(h.hostid) > 300));
});
test('equal relationships are ordered by natural name, then host ID', () => {
  const hosts = [layoutHost(3, 'sw-10'), layoutHost(1, 'sw-2'), layoutHost(2, 'sw-2'), layoutHost(4, 'core')];
  const placed = at(runtime.graphLayout(hosts, [link(4, 3), link(4, 1), link(4, 2)]));
  assert.ok(placed['1'].x < placed['2'].x && placed['2'].x < placed['3'].x);
  assert.ok(placed['4'].y < placed['1'].y);
});
test('example A: a tree hangs below its best-connected switch without root evidence, inventing no root', () => {
  const [core, distA, distB, accA, accB] = [1, 2, 3, 4, 5];
  const hosts = [layoutHost(core, 'CORE'), layoutHost(distA, 'DIST-A'), layoutHost(distB, 'DIST-B'), layoutHost(accA, 'ACCESS-A'), layoutHost(accB, 'ACCESS-B')];
  const result = runtime.layoutTopology(hosts, [link(core, distA), link(distA, accA), link(core, distB), link(distB, accB)]);
  const p = at(result.nodes);
  assert.deepEqual([p[1].level, p[2].level, p[3].level, p[4].level, p[5].level], [0, 1, 1, 2, 2]);
  assert.ok(p[2].x < p[3].x && p[4].x < p[5].x, 'each access switch sits under its own distribution switch');
  assert.deepEqual(result.components[0].anchors, [], 'a layout anchor is not a root');
});
test('example B: a redundant link between two levels-one switches stays a cross-link', () => {
  const hosts = [layoutHost(1, 'CORE'), layoutHost(2, 'D1'), layoutHost(3, 'D2')];
  const edges = [link(1, 2), link(1, 3), link(2, 3)];
  const p = at(runtime.graphLayout(hosts, edges, { anchors: new Set(['1']) }));
  assert.ok(p[1].y < p[2].y && p[2].y === p[3].y);
});
test('a current agreed root anchors its component even when another switch is busier or named first', () => {
  // A ring 1–2–3–4–1 with a spur 4–5: 4 has the most links, 1 is first by name, 3 is the observed root.
  const hosts = [1, 2, 3, 4, 5].map(n => layoutHost(n));
  const edges = [link(1, 2), link(2, 3), link(3, 4), link(4, 1), link(4, 5)];
  const p = at(runtime.graphLayout(hosts, edges, { anchors: new Set(['3']) }));
  assert.equal(p[3].level, 0);
  assert.ok(Object.values(p).every(h => h.hostid === '3' || h.y > p[3].y));
  assert.equal(p[2].y, p[4].y);
  // Without root evidence the busiest switch anchors.
  assert.equal(at(runtime.graphLayout(hosts, edges))[4].level, 0);
});
test('example C: Spanning Tree follows root ports; the blocked alternate link stays but never makes a parent', () => {
  const hosts = [layoutHost(1, 'CORE'), layoutHost(2, 'D1'), layoutHost(3, 'D2'), layoutHost(4, 'A1')];
  const edges = [
    link(2, 1, rootPort('source')),
    link(3, 1, rootPort('source')),
    link(2, 3, { source: { role: 'designated', state: 'forwarding' }, target: { role: 'alternate', state: 'blocking' } }),
    link(4, 3, rootPort('source'))
  ];
  const parents = runtime.stpParents(edges);
  assert.deepEqual(Object.fromEntries(parents), { 2: '1', 3: '1', 4: '3' });
  const p = at(runtime.graphLayout(hosts, edges, { anchors: new Set(['1']), parents }));
  assert.deepEqual([p[1].level, p[2].level, p[3].level, p[4].level], [0, 1, 1, 2]);
  assert.ok(p[4].y > p[3].y);
});
test('a switch with no root-port path is kept visible in an unresolved area, never given a parent', () => {
  const hosts = [layoutHost(1, 'ROOT'), layoutHost(2, 'D1'), layoutHost(3, 'SW-X')];
  // SW-X is physically linked to D1, but no root role was observed on its side.
  const edges = [link(2, 1, rootPort('source')), link(3, 2)];
  const parents = runtime.stpParents(edges);
  const p = at(runtime.graphLayout(hosts, edges, { anchors: new Set(['1']), parents }));
  assert.equal(p[3].unresolved, true);
  assert.equal(p[3].level, null);
  assert.ok(p[3].y > p[2].y + 120, 'the unresolved area sits apart below the tree');
  assert.ok(!p[2].unresolved && !p[1].unresolved);
});
test('disputed or missing roots fall back to the Layer 2 placement instead of a fabricated hierarchy', () => {
  const hosts = [1, 2, 3].map(n => layoutHost(n));
  const edges = [link(1, 2, rootPort('source')), link(2, 3)];
  const parents = runtime.stpParents(edges);
  // stpRoots gives no roots when switches disagree, so there is no anchor and no hierarchy.
  const tree = runtime.graphLayout(hosts, edges, { anchors: new Set(), parents });
  assert.deepEqual(tree, runtime.graphLayout(hosts, edges));
  assert.ok(!tree.some(h => h.unresolved));
});
test('example D: components are laid out apart, rooted ones first, and never overlap', () => {
  const hosts = [
    layoutHost(1, 'CORE-A'),
    layoutHost(2, 'A1'),
    layoutHost(3, 'A2'),
    layoutHost(4, 'CORE-B'),
    layoutHost(5, 'B1'),
    layoutHost(6, 'LONE')
  ];
  const edges = [link(1, 2), link(2, 3), link(4, 5)];
  const plain = runtime.layoutTopology(hosts, edges);
  assert.equal(plain.components.length, 3);
  const a = box(plain.nodes, ['1', '2', '3']),
    b = box(plain.nodes, ['4', '5']),
    lone = box(plain.nodes, ['6']);
  assert.ok(apart(a, b) && apart(a, lone) && apart(b, lone));
  assert.equal(plain.nodes[0].component, 0);
  assert.ok(['1', '2', '3'].includes(plain.nodes[0].hostid), 'larger first without roots');
  // A component with an observed root comes first; each component has its own root, no super-root.
  const rooted = runtime.layoutTopology(hosts, edges, { anchors: new Set(['4', '1']) });
  assert.deepEqual(rooted.components.map(c => c.anchors), [['1'], ['4'], []]);
  const r = at(rooted.nodes);
  assert.equal(r[1].level, 0);
  assert.equal(r[4].level, 0);
  assert.ok(rooted.bounds.width > 0 && rooted.bounds.height > 0);
});
test('external peers do not change levels or positions of visible switches', () => {
  const hosts = [1, 2, 3].map(n => layoutHost(n));
  const internal = [link(1, 2), link(2, 3)];
  const withExternal = [...internal, link(3, 'hidden-9'), link('undisclosed', 1)];
  assert.deepEqual(runtime.graphLayout(hosts, withExternal), runtime.graphLayout(hosts, internal));
});
test('previous positions keep the order of unaffected switches when a leaf is added', () => {
  const hosts = [layoutHost(1, 'core'), layoutHost(2, 'd2'), layoutHost(3, 'd1'), layoutHost(4, 'a3'), layoutHost(5, 'a1'), layoutHost(6, 'a2')];
  const edges = [link(1, 2), link(1, 3), link(3, 5), link(3, 6), link(2, 4)];
  const before = runtime.graphLayout(hosts, edges);
  const previous = new Map(before.map(h => [h.hostid, h]));
  const after = runtime.graphLayout([...hosts, layoutHost(7, 'a0')], [...edges, link(2, 7)], { previous });
  const p = at(after),
    was = at(before);
  // Only the row that gained a switch re-centres; every other switch keeps its exact position.
  for (const hostid of ['1', '2', '3', '5', '6']) assert.deepEqual([p[hostid].x, p[hostid].y], [was[hostid].x, was[hostid].y]);
  assert.equal(p[7].y, p[4].y, 'the new leaf joins its parent’s other children');
  // The hint keeps the existing switch where it was relative to the newcomer, although "a0" sorts first by name.
  assert.ok(p[4].x < p[7].x);
  const unhinted = at(runtime.graphLayout([...hosts, layoutHost(7, 'a0')], [...edges, link(2, 7)]));
  assert.ok(unhinted[7].x < unhinted[4].x, 'without the hint, name order would put the newcomer first');
});
test('selection, VLAN and LAG collapse never move a switch: positions depend only on hosts and links', () => {
  const hosts = [1, 2, 3].map(n => layoutHost(n));
  const edges = [{ ...link(1, 2), members: [{ id: 'a' }, { id: 'b' }] }, link(2, 3)];
  const before = runtime.graphLayout(hosts, edges, { anchors: new Set(['1']) });
  const decorated = hosts.map(h => ({ ...h, selected: true, vlans: [{ vlan_id: 10 }] }));
  const after = runtime.graphLayout(decorated, [edges[1], edges[0]], { anchors: new Set(['1']) });
  assert.deepEqual(
    before.map(({ hostid, x, y }) => [hostid, x, y]),
    after.map(({ hostid, x, y }) => [hostid, x, y])
  );
});
test('LAG grouping retains parallel members and independent links', () => {
  const edges = [
    { id: 'a', source: '1', target: '2', lag_id: 'L1' },
    { id: 'b', source: '1', target: '2', lag_id: 'L1' },
    { id: 'c', source: '1', target: '2' },
    { id: 'd', source: '1', target: '3', lag_id: 'L1' }
  ];
  const grouped = runtime.groupedEdges(edges);
  assert.equal(grouped.length, 3);
  assert.equal(grouped[0].members.length, 2);
  assert.equal(runtime.groupedEdges(edges, false).length, 4);
});
test('peer navigation permits core relative routes and validates highlight context', () => {
  const url = runtime.peerUrl(
    'zabbix.php?action=host.dashboard.view&hostid=12',
    { hostid: '12', uid: 'name:Gi1/0/1' },
    'Switch 1'
  );
  assert.equal(runtime.fragmentContext('#' + url.split('#')[1]).uid, 'name:Gi1/0/1');
  for (const bad of [
    'javascript:alert(1)',
    'https://attacker.invalid/zabbix.php?action=host.dashboard.view',
    '//attacker.invalid/zabbix.php?action=host.dashboard.view',
    'zabbix.php?action=user.delete'
  ])
    assert.equal(runtime.safeNavigation(bad), null);
  assert.equal(
    runtime.fragmentContext('#ne=' + encodeURIComponent(JSON.stringify({ hostid: '12', uid: 'x\n' }))),
    null
  );
});
test('VLAN roles, link carry and trace follow the spec categories', () => {
  const trunk = { vlan: { mode: 'trunk', pvid: 1, carried: '1,10-12', untagged: '1', forbidden: '99' } };
  assert.equal(runtime.vlanRole(trunk, 11), 'tagged');
  assert.equal(runtime.vlanRole(trunk, 1), 'native');
  assert.equal(runtime.vlanRole(trunk, 99), 'not_permitted');
  assert.equal(runtime.vlanRole(trunk, 20), 'not_permitted');
  assert.equal(runtime.vlanRole({ vlan: { mode: 'access', carried: '49', untagged: '49' } }, 49), 'access');
  assert.equal(runtime.vlanRole({ vlan: { mode: 'access', carried: '49', untagged: '49' } }, 10), 'unrelated');
  assert.equal(runtime.vlanRole({}, 10), 'unknown');
  assert.deepEqual([...runtime.vlanSet('1,4093-4096,x')], [1, 4093, 4094]);
  const edges = [
    { id: 'ab', source: 'a', target: 'b', vlan: { common: '10', source_only: '', target_only: '' } },
    { id: 'bc', source: 'b', target: 'c', vlan: { common: '', source_only: '10', target_only: '' } },
    { id: 'cd', source: 'c', target: 'd', vlan: { common: '10' } }
  ];
  assert.equal(runtime.edgeVlanState(edges[0], 10), 'carried');
  assert.equal(runtime.edgeVlanState(edges[1], 10), 'stopped');
  assert.equal(runtime.edgeVlanState(edges[1], 20), 'unrelated');
  assert.equal(runtime.edgeVlanState({}, 10), 'unknown');
  const trace = runtime.vlanTrace({ edges }, 'a', 10);
  assert.deepEqual(trace.reached, ['a', 'b']);
  assert.equal(trace.stops.length, 1);
  assert.equal(trace.stops[0].hostid, 'c');
  assert.equal(runtime.stpClass({ state: 'discarding' }), 'blocking');
  assert.equal(runtime.stpClass(null), 'unknown');
});
test("LAG member links group by the reader's lag_ids into one logical link", () => {
  const edges = [
    { id: 'm1', source: '11', target: '13', lag_ids: ['lag-b', 'lag-a'] },
    { id: 'm2', source: '11', target: '13', lag_ids: ['lag-a', 'lag-b'] },
    { id: 'x', source: '11', target: '14', lag_ids: [] }
  ];
  const grouped = runtime.groupedEdges(edges);
  assert.equal(grouped.length, 2);
  assert.equal(grouped.find(g => g.id === 'm1').members.length, 2);
});
test('CSV exports escape quotes and spreadsheet formulas', () => {
  const csv = runtime.findingsCsv(
    [{ hostid: '1', title: '=HYPERLINK("bad")', rule: 'speed', severity: 'warning', reason: 'comma, "quoted"' }],
    { hosts: [{ hostid: '1', name: 'Switch' }] }
  );
  assert.ok(csv.includes('"\'=HYPERLINK(""bad"")"'));
  assert.ok(csv.includes('"comma, ""quoted"""'));
  assert.ok(csv.startsWith('\ufeff'));
  for (const prefix of [' ', '  ', '\t', '\r', '\n', ' \t', '\ufeff']) {
    const title = prefix + '=HYPERLINK("bad")';
    const output = runtime.findingsCsv([{ title }], {});
    assert.ok(
      output.includes('"\'' + prefix + '=HYPERLINK(""bad"")"'),
      'CSV formula escaped after whitespace ' + JSON.stringify(prefix)
    );
  }
});
test('widget manifests use only native host/item broadcasts and ship the shared runtime and stylesheet', () => {
  const ids = ['neportpanel', 'netopology', 'neinterfacedetail', 'nedataquality', 'nefindings'];
  const source = path.join(__dirname, '../../src/widget');
  for (const id of ids) {
    const directory = path.join(__dirname, '../../frontend', id);
    const manifest = JSON.parse(fs.readFileSync(path.join(directory, 'manifest.json')));
    assert.equal(manifest.id, id);
    assert.equal(manifest.widget.in.override_hostid.type, '_hostid');
    assert.ok(manifest.widget.out.every(o => ['_hostid', '_itemid'].includes(o.type)));
    for (const [name, copy] of [
      ['runtime.js', 'assets/js/runtime.js'],
      ['widget.css', 'assets/css/widget.css']
    ]) {
      assert.equal(
        hash(fs.readFileSync(path.join(directory, copy))),
        hash(fs.readFileSync(path.join(source, name))),
        `${id} ${copy} must match src/widget/${name}; run scripts/sync_widget_assets.py`
      );
    }
  }
});
test('the STP root comes from bridge evidence agreed within a domain, never from layout', () => {
  const bridge = (bridgeId, rootId) => [
    { instance: 0, bridge_id: bridgeId, root_bridge_id: rootId, is_root: bridgeId === rootId }
  ];
  const current = hostid => ({ hostid, dataset: 'stp', status: 'ok', freshness: 'current' });
  const payload = {
    hosts: [
      { hostid: '1', domain: 'd', stp: bridge('a', 'b') },
      { hostid: '2', domain: 'd', stp: bridge('b', 'b') },
      { hostid: '3', domain: 'e', stp: bridge('c', 'undisclosed-1234') }
    ],
    quality: [current('2')]
  };
  let roots = runtime.stpRoots(payload);
  assert.deepEqual([...roots.roots], ['2']);
  assert.deepEqual([...roots.current], ['2']);
  assert.deepEqual(roots.outside, ['undisclosed-1234']);
  payload.quality = [{ ...current('2'), freshness: 'stale' }];
  assert.deepEqual([...runtime.stpRoots(payload).current], [], 'A stale root is not marked in the Layer 2 view');
  payload.hosts[0].stp = bridge('a', 'a');
  roots = runtime.stpRoots(payload);
  assert.deepEqual([...roots.roots], [], 'Disagreeing switches choose no root');
  assert.deepEqual([...roots.claimed].sort(), ['1', '2']);
  assert.equal(roots.disputed.length, 1);
});
test('the Explorer page module ships the same shared runtime and stylesheet as the widgets', () => {
  const directory = path.join(__dirname, '../../frontend/networkexplorer');
  const manifest = JSON.parse(fs.readFileSync(path.join(directory, 'manifest.json')));
  assert.deepEqual(manifest.assets.js, ['runtime.js']);
  assert.ok(manifest.assets.css.includes('widget.css'));
  for (const [name, copy] of [
    ['runtime.js', 'assets/js/runtime.js'],
    ['widget.css', 'assets/css/widget.css']
  ])
    assert.equal(
      hash(fs.readFileSync(path.join(directory, copy))),
      hash(fs.readFileSync(path.join(__dirname, '../../src/widget', name)))
    );
});
