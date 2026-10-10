/* Network Explorer widget runtime. All network data arrives through the current-session PHP reader. */
(function (global) {
  'use strict';
  if (global.NEWidgetRuntime) return;
  const asRows = value => (Array.isArray(value) ? value : []);
  const text = value => (value === null || value === undefined || value === '' ? 'Unknown' : String(value));
  const id = value => String(value ?? '');
  const natural = (a, b) => text(a).localeCompare(text(b), undefined, { numeric: true });
  const enumValue = value => (typeof value === 'object' && value ? (value.state ?? value.value) : value);
  /** Topology geometry, in SVG units. */
  const LAYOUT = {
    maxNodes: 300,
    originX: 115,
    originY: 70,
    columnGap: 215,
    rowGap: 120,
    nodeWidth: 180,
    nodeHeight: 50,
    labelChars: 26,
    maxRowNodes: 8,
    componentGap: 110,
    stubRadius: 100,
    parallelSpacing: 10,
    blockMarkGap: 14
  };
  function speed(value) {
    const n = Number(value);
    if (!Number.isFinite(n) || n <= 0) return 'Unknown';
    for (const [unit, scale] of [
      ['Tb/s', 1e12],
      ['Gb/s', 1e9],
      ['Mb/s', 1e6],
      ['kb/s', 1e3]
    ]) {
      if (n >= scale) return `${Number((n / scale).toFixed(2))} ${unit}`;
    }
    return `${n} b/s`;
  }
  function portState(port) {
    if (typeof port.state === 'string') {
      const state = {
        normal: 'up',
        speed_observation: 'speed_observation',
        duplex_observation: 'duplex_observation',
        unknown: 'unknown',
        disabled: 'disabled',
        down: 'down',
        degraded: 'degraded'
      }[port.state];
      if (state) return state;
    }
    const admin = enumValue(port.admin_status),
      oper = enumValue(port.oper_status);
    if (admin === 'down' || admin === 'disabled' || Number(admin) === 2) return 'disabled';
    if (oper === 'down' || Number(oper) === 2 || oper === 'lower_layer_down') return 'down';
    if (oper === 'up' || Number(oper) === 1) {
      const expected = Number(port.expected_speed_bps),
        actual = Number(port.speed_bps);
      // One reading is only an observation; the server's PortPolicy decides sustained degradation.
      if (expected > 0 && actual > 0 && actual < expected) return 'speed_observation';
      return 'up';
    }
    return 'unknown';
  }
  const STATE_LABELS = {
    up: '● Up',
    down: '× Down',
    disabled: '○ Admin disabled',
    speed_observation: '△ Below intended speed (unconfirmed)',
    duplex_observation: '△ Half duplex observed',
    degraded: '⚠ Sustained speed degradation',
    unknown: '? Unknown'
  };
  function stateLabel(port) {
    return STATE_LABELS[portState(port)];
  }
  function isPhysical(port) {
    const value = port.physical;
    return value === true || value === 'physical' || value === 'true' || value?.state === 'physical';
  }
  // VLAN ranges arrive as canonical strings such as "1,10-12". The same few strings repeat across every port
  // and link, so expanded sets are cached; callers must treat the returned set as read-only.
  const vlanSets = new Map();
  function vlanSet(ranges) {
    const key = String(ranges ?? '');
    let cached = vlanSets.get(key);
    if (!cached) {
      if (vlanSets.size >= 4096) vlanSets.clear();
      cached = expandVlans(key);
      vlanSets.set(key, cached);
    }
    return cached;
  }
  function expandVlans(ranges) {
    const result = new Set();
    for (const part of ranges.split(',')) {
      const match = /^(\d{1,4})(?:-(\d{1,4}))?$/.exec(part);
      if (!match) continue;
      for (let v = Math.max(1, Number(match[1])); v <= Math.min(4094, Number(match[2] ?? match[1])); v++) result.add(v);
    }
    return result;
  }
  /** Role of one port in one VLAN: access, tagged, native, not_permitted, unrelated or unknown. */
  function vlanRole(port, vlan) {
    const v = port.vlan,
      n = Number(vlan);
    if (!v || !n) return 'unknown';
    const trunk = v.mode === 'trunk' || v.mode === 'hybrid';
    if (vlanSet(v.forbidden).has(n)) return 'not_permitted';
    if (!vlanSet(v.carried).has(n)) return trunk ? 'not_permitted' : 'unrelated';
    if (!trunk) return 'access';
    return vlanSet(v.untagged).has(n) ? 'native' : 'tagged';
  }
  const VLAN_LABELS = {
    access: '▣ Access (untagged)',
    tagged: '⇉ Trunk (tagged)',
    native: '◆ Trunk (native)',
    not_permitted: '⊘ Not permitted',
    unrelated: '· Unrelated',
    unknown: '? No VLAN data'
  };
  /** carried: both ends carry it; stopped: the link exists but one end does not; unrelated; unknown. */
  function edgeVlanState(edge, vlan) {
    const v = edge.vlan,
      n = Number(vlan);
    if (!v) return 'unknown';
    if (vlanSet(v.common).has(n)) return 'carried';
    if (vlanSet(v.source_only).has(n) || vlanSet(v.target_only).has(n)) return 'stopped';
    return 'unrelated';
  }
  /** Walks links that carry a VLAN from one switch, and reports each link where it stops. */
  function vlanTrace(payload, start, vlan) {
    const n = Number(vlan),
      reached = new Set([id(start)]),
      stops = [],
      queue = [id(start)];
    const edges = asRows(payload.edges);
    while (queue.length) {
      const current = queue.shift();
      for (const edge of edges) {
        const ends = [id(edge.source), id(edge.target)];
        if (!ends.includes(current) || edge.target === null || edge.source === null) continue;
        const other = ends[0] === current ? ends[1] : ends[0];
        const state = edgeVlanState(edge, n);
        if (state === 'carried' && !reached.has(other)) {
          reached.add(other);
          queue.push(other);
        } else if (state === 'stopped' && !reached.has(other)) {
          const missing = vlanSet(edge.vlan.source_only).has(n) ? 'target' : 'source';
          stops.push({ edge, hostid: id(edge[missing]), uid: edge[missing + '_uid'] });
        }
      }
    }
    return { reached: [...reached], stops };
  }
  function stpPort(port, instance = 0) {
    return asRows(port.stp).find(row => Number(row.instance) === Number(instance)) ?? null;
  }
  function stpClass(row) {
    const state = row?.state;
    if (state === 'forwarding') return 'forwarding';
    if (state === 'blocking' || state === 'discarding') return 'blocking';
    if (state === 'learning' || state === 'listening') return 'learning';
    if (state === 'disabled' || state === 'broken') return 'disabled';
    return 'unknown';
  }
  const STP_MARKS = { forwarding: '●', blocking: '⊘', learning: '◐', disabled: '○', unknown: '?' };
  function stpLabel(row) {
    if (!row) return '? No STP data';
    return `${STP_MARKS[stpClass(row)]} ${text(row.state)} · ${text(row.role)}${row.role_source === 'derived' ? '*' : ''}`;
  }
  /**
   * The observed instance-0 (CIST) root bridge, per matching domain. A switch is the root only when it reports itself
   * as root (bridge_id == root_bridge_id) and every visible switch in its domain reports that same root; never from
   * its place in the layout. `current` also needs current STP collection from the root switch. A domain whose
   * switches disagree has no root; `claimed` lists the switches that report themselves as root.
   */
  function stpRoots(payload) {
    const fresh = new Set(
      asRows(payload.quality)
        .filter(q => q.dataset === 'stp' && q.freshness === 'current' && q.status === 'ok')
        .map(q => id(q.hostid))
    );
    const groups = new Map();
    for (const host of asRows(payload.hosts)) {
      const bridge = asRows(host.stp).find(b => Number(b.instance) === 0);
      if (!bridge?.root_bridge_id) continue;
      // A switch without a matching domain shares no namespace with the others.
      const key = host.domain ? `domain:${host.domain}` : `host:${id(host.hostid)}`;
      if (!groups.has(key)) groups.set(key, []);
      groups.get(key).push({ host, bridge });
    }
    const result = { roots: new Set(), current: new Set(), claimed: new Set(), outside: [], disputed: [] };
    for (const rows of groups.values()) {
      for (const { host, bridge } of rows) if (bridge.is_root) result.claimed.add(id(host.hostid));
      const seen = [...new Set(rows.map(r => r.bridge.root_bridge_id))];
      if (seen.length > 1) {
        result.disputed.push({ domain: rows[0].host.domain ?? '', roots: seen });
        continue;
      }
      const root = rows.find(r => r.bridge.is_root && r.bridge.bridge_id === seen[0]);
      if (!root) {
        if (!result.outside.includes(seen[0])) result.outside.push(seen[0]);
        continue;
      }
      result.roots.add(id(root.host.hostid));
      if (fresh.has(id(root.host.hostid))) result.current.add(id(root.host.hostid));
    }
    return result;
  }
  const MEDIA_LABELS = { copper: 'Copper', sfp: 'SFP', sfp_plus: 'SFP+' };
  /** Groups ports by stack member and slot (ENTITY-MIB placement); unplaced ports form one group. */
  function groupPorts(ports, layout = 'auto') {
    const groups = new Map();
    for (const port of ports
      .slice()
      .sort(
        (a, b) =>
          natural(a.member ?? Infinity, b.member ?? Infinity) ||
          natural(a.slot, b.slot) ||
          natural(a.port ?? a.name, b.port ?? b.name)
      )) {
      const member = port.member ?? null,
        slot = port.slot ?? null;
      const place = member === null ? 'Unplaced ports' : `Member ${member}${slot === null ? '' : ` · slot ${slot}`}`;
      const key = layout === 'mixed' ? `${place} · ${MEDIA_LABELS[port.media] ?? 'Media unknown'}` : place;
      if (!groups.has(key)) groups.set(key, { key, member, ports: [] });
      groups.get(key).ports.push(port);
    }
    return [...groups.values()];
  }
  /** Applies configured state colours (six-digit hex from the widget form) as CSS custom properties. */
  function applyColours(root, colours) {
    for (const state of ['normal', 'down', 'degraded', 'disabled', 'unknown']) {
      const value = String(colours?.[state] ?? '');
      if (/^[0-9A-Fa-f]{6}$/.test(value)) root.style.setProperty(`--ne-colour-${state}`, `#${value}`);
    }
  }
  /**
   * Deterministic, topology-aware hierarchical placement. Pure: hosts and links in, coordinates out; no DOM.
   *
   * - Only links whose two ends are visible switches shape the layout; external and undisclosed peers are drawn
   *   afterwards as stubs and never move a switch.
   * - Each connected component is placed on its own and never overlaps another. Components holding an anchor come
   *   first, then larger before smaller, then by their first switch's natural name. Unlinked switches share a block
   *   at the end.
   * - Rows are levels below the component's anchors: observed root bridges from `options.anchors`, or, with none in
   *   the component, its best-connected switch (natural name, then host ID, breaks ties). Placement never decides
   *   which switch is a root; anchors come from canonical STP evidence (`stpRoots`).
   * - Layer 2 levels are shortest hop counts from the anchors. With `options.parents` (child → upstream switch from
   *   observed root ports, `stpParents`), a component that holds an anchor is a root-port hierarchy instead, and a
   *   switch whose root-port chain does not reach an anchor goes to an "unresolved" area below it rather than being
   *   given a parent. Links that are not part of the hierarchy are still drawn, as cross-links.
   * - Within a level, a fixed number of barycentre sweeps (down, then up) reduces crossings; the starting order is
   *   the previous x position from `options.previous` (hostid → {x}) when given, then natural name and host ID.
   *   Levels wider than LAYOUT.maxRowNodes wrap onto extra rows.
   *
   * Returns {nodes: [{...host, x, y, component, level, order, unresolved}], components: [{index, size, anchors}],
   * bounds: {x, y, width, height}}. The same input always gives the same output.
   */
  function layoutTopology(hosts, edges, options = {}) {
    const anchors = options.anchors ?? new Set(),
      parents = options.parents ?? null,
      previous = options.previous ?? new Map();
    const ordered = hosts
      .slice()
      .sort((a, b) => natural(a.name, b.name) || natural(a.hostid, b.hostid))
      .slice(0, LAYOUT.maxNodes);
    const rank = new Map(ordered.map((h, index) => [id(h.hostid), index]));
    const byRank = (a, b) => rank.get(a) - rank.get(b);
    const adjacency = new Map(ordered.map(h => [id(h.hostid), new Set()]));
    for (const edge of edges) {
      const a = id(edge.source),
        b = id(edge.target);
      if (a !== b && adjacency.has(a) && adjacency.has(b)) {
        adjacency.get(a).add(b);
        adjacency.get(b).add(a);
      }
    }
    const neighbours = hostid => [...adjacency.get(hostid)].sort(byRank);
    const seen = new Set(),
      groups = [],
      loose = [];
    for (const h of ordered) {
      const start = id(h.hostid);
      if (seen.has(start)) continue;
      seen.add(start);
      const members = [start];
      for (let i = 0; i < members.length; i++)
        for (const next of neighbours(members[i])) if (!seen.has(next) && seen.add(next)) members.push(next);
      (members.length > 1 ? groups : loose).push(members.sort(byRank));
    }
    const anchored = members => members.some(h => anchors.has(h));
    groups.sort((a, b) => anchored(b) - anchored(a) || b.length - a.length || byRank(a[0], b[0]));
    const blocks = groups.map(members =>
      componentLevels(members, { neighbours, anchors, parents, previous, byRank })
    );
    if (loose.length)
      blocks.push({ rows: chunk(loose.flat(), LAYOUT.maxRowNodes).map(row => ({ ids: row, level: 0 })), anchors: [] });
    // Blocks run left to right and wrap into bands, so a wide estate stays readable.
    const placed = new Map(),
      bandLimit = LAYOUT.maxRowNodes * LAYOUT.columnGap;
    let left = 0,
      top = 0,
      bandHeight = 0;
    blocks.forEach((block, component) => {
      const { rows } = block;
      const width = Math.max(...rows.map(r => r.ids.length)) * LAYOUT.columnGap,
        height = rows.reduce((sum, r) => sum + (r.gapBefore ? LAYOUT.rowGap : 0), rows.length * LAYOUT.rowGap);
      if (left > 0 && left + width > bandLimit) {
        left = 0;
        top += bandHeight + LAYOUT.componentGap;
        bandHeight = 0;
      }
      let y = LAYOUT.originY + top;
      for (const row of rows) {
        if (row.gapBefore) y += LAYOUT.rowGap;
        row.ids.forEach((hostid, c) =>
          placed.set(hostid, {
            x: LAYOUT.originX + left + (width - row.ids.length * LAYOUT.columnGap) / 2 + c * LAYOUT.columnGap,
            y,
            component,
            level: row.level,
            order: c,
            unresolved: !!row.unresolved
          })
        );
        y += LAYOUT.rowGap;
      }
      left += width + LAYOUT.componentGap;
      bandHeight = Math.max(bandHeight, height);
    });
    const byId = new Map(ordered.map(h => [id(h.hostid), h]));
    const nodes = blocks.flatMap(b => b.rows.flatMap(r => r.ids)).map(hostid => ({ ...byId.get(hostid), ...placed.get(hostid) }));
    const xs = nodes.map(n => n.x),
      ys = nodes.map(n => n.y);
    return {
      nodes,
      components: blocks.map((b, index) => ({
        index,
        size: b.rows.reduce((sum, r) => sum + r.ids.length, 0),
        anchors: b.anchors
      })),
      bounds: nodes.length
        ? {
            x: Math.min(...xs) - LAYOUT.nodeWidth / 2,
            y: Math.min(...ys) - LAYOUT.nodeHeight / 2,
            width: Math.max(...xs) - Math.min(...xs) + LAYOUT.nodeWidth,
            height: Math.max(...ys) - Math.min(...ys) + LAYOUT.nodeHeight
          }
        : { x: 0, y: 0, width: 0, height: 0 }
    };
  }
  /** Placed hosts only, for callers that need no component or bounds data. */
  function graphLayout(hosts, edges, options = {}) {
    return layoutTopology(hosts, edges, options).nodes;
  }
  function chunk(list, size) {
    const rows = [];
    for (let i = 0; i < list.length; i += size) rows.push(list.slice(i, i + size));
    return rows;
  }
  const CROSSING_SWEEPS = 4;
  /** One component's levels and rows (see layoutTopology). */
  function componentLevels(members, { neighbours, anchors, parents, previous, byRank }) {
    const inside = new Set(members);
    let tops = members.filter(h => anchors.has(h));
    const hierarchy = !!parents && tops.length > 0;
    if (!tops.length)
      tops = [members.slice().sort((a, b) => neighbours(b).length - neighbours(a).length || byRank(a, b))[0]];
    const depth = new Map(tops.map(h => [h, 0]));
    const unresolved = [];
    if (hierarchy) {
      // A switch's level is its root-port hop count to an anchor; without a complete chain it is unresolved.
      const treeDepth = (hostid, trail = new Set()) => {
        if (depth.has(hostid)) return depth.get(hostid);
        const parent = parents.get(hostid);
        if (!parent || !inside.has(parent) || trail.has(hostid)) return null;
        trail.add(hostid);
        const above = treeDepth(parent, trail);
        if (above === null) return null;
        depth.set(hostid, above + 1);
        return above + 1;
      };
      for (const hostid of members) if (treeDepth(hostid) === null) unresolved.push(hostid);
    } else {
      const queue = tops.slice();
      for (let i = 0; i < queue.length; i++)
        for (const next of neighbours(queue[i]))
          if (!depth.has(next)) {
            depth.set(next, depth.get(queue[i]) + 1);
            queue.push(next);
          }
    }
    const levels = [];
    for (const hostid of members) if (depth.has(hostid)) (levels[depth.get(hostid)] ??= []).push(hostid);
    const compact = levels.filter(Boolean);
    // Starting order: where the switch was before (when known), then natural name and host ID.
    const was = hostid => previous.get(hostid)?.x ?? Infinity;
    for (const level of compact) level.sort((a, b) => was(a) - was(b) || byRank(a, b));
    // Upward links follow root ports in a hierarchy, every physical link otherwise.
    const linksTo = (hostid, level) =>
      hierarchy && level === 'up'
        ? parents.has(hostid)
          ? [parents.get(hostid)]
          : []
        : hierarchy
          ? members.filter(m => parents.get(m) === hostid)
          : neighbours(hostid);
    const position = new Map();
    const index = level => level.forEach((h, i) => position.set(h, i - (level.length - 1) / 2));
    compact.forEach(index);
    const reorder = (level, towards, direction) => {
      const placedIn = new Set(towards);
      const weight = new Map(
        level.map(h => {
          const near = linksTo(h, direction).filter(n => placedIn.has(n));
          return [h, near.length ? near.reduce((s, n) => s + position.get(n), 0) / near.length : position.get(h)];
        })
      );
      // Array.prototype.sort is stable, so ties keep the current order and the result stays deterministic.
      level.sort((a, b) => weight.get(a) - weight.get(b));
      index(level);
    };
    for (let sweep = 0; sweep < CROSSING_SWEEPS; sweep++) {
      for (let i = 1; i < compact.length; i++) reorder(compact[i], compact[i - 1], 'up');
      for (let i = compact.length - 2; i >= 0; i--) reorder(compact[i], compact[i + 1], 'down');
    }
    const rows = [];
    compact.forEach((level, l) => {
      for (const ids of chunk(level, LAYOUT.maxRowNodes)) rows.push({ ids, level: l });
    });
    if (unresolved.length) {
      unresolved.sort((a, b) => was(a) - was(b) || byRank(a, b));
      chunk(unresolved, LAYOUT.maxRowNodes).forEach((ids, i) =>
        rows.push({ ids, level: null, unresolved: true, gapBefore: i === 0 })
      );
    }
    return { rows, anchors: hierarchy || tops.some(h => anchors.has(h)) ? tops : [] };
  }
  /** Child → parent hostid along observed STP root ports: a switch whose port on a link has the root role. */
  function stpParents(edges) {
    const parents = new Map();
    for (const edge of edges)
      for (const member of asRows(edge.members ?? [edge])) {
        if (!member.source || !member.target) continue;
        for (const [side, other] of [
          ['source', 'target'],
          ['target', 'source']
        ])
          if (member.stp?.[side]?.role === 'root' && !parents.has(id(member[side])))
            parents.set(id(member[side]), id(member[other]));
      }
    return parents;
  }
  const LAG_MODES = { lacp: 'LACP', static: 'Static', pagp: 'PAgP' };
  // The aggregation mode of a link, from the LAG rows its members belong to; both ends normally agree.
  function lagModeLabel(payload, edge) {
    const ids = new Set(
      asRows(edge.members ?? [edge])
        .flatMap(m => asRows(m.lag_ids).concat(m.lag_id ? [m.lag_id] : []))
        .map(id)
    );
    const labels = [
      ...new Set(
        asRows(payload.lags)
          .filter(lag => ids.has(id(lag.id)))
          .map(lag => LAG_MODES[lag.mode] ?? 'Unknown mode')
      )
    ];
    return labels.sort().join(' / ');
  }
  function groupedEdges(edges, collapse = true) {
    if (!collapse) return edges.map(edge => ({ ...edge, members: [edge] }));
    const groups = new Map();
    for (const edge of edges) {
      // The reader lists every LAG an edge belongs to, one per end; both ends name the same logical link.
      const lag =
        edge.lag_id ??
        edge.source_lag_id ??
        edge.lag?.uid ??
        (asRows(edge.lag_ids).length ? [...edge.lag_ids].sort().join('+') : null);
      const endpoints = [id(edge.source), id(edge.target)].sort();
      const key = lag
        ? JSON.stringify([endpoints, id(lag)])
        : id(edge.id) || JSON.stringify([endpoints, edge.source_uid, edge.target_uid]);
      if (!groups.has(key)) groups.set(key, { ...edge, members: [] });
      groups.get(key).members.push(edge);
    }
    return [...groups.values()];
  }
  function safeNavigation(url) {
    if (!url || typeof url !== 'string' || /[\r\n\x00]/.test(url)) return null;
    try {
      const parsed = new URL(url, 'https://zabbix.invalid/');
      // Links are exclusively supported Zabbix controller routes within this installation.
      if (parsed.origin !== 'https://zabbix.invalid' || !parsed.pathname.endsWith('/zabbix.php')) return null;
      if (!['host.dashboard.view', 'networkexplorer.view', 'ne.explorer'].includes(parsed.searchParams.get('action')))
        return null;
      return `${parsed.pathname.replace(/^\//, '')}${parsed.search}${parsed.hash}`;
    } catch (_) {
      return null;
    }
  }
  function fragmentContext(hash) {
    if (!hash?.startsWith('#ne=')) return null;
    try {
      const data = JSON.parse(decodeURIComponent(hash.substring(4)));
      if (
        !/^[1-9][0-9]*$/.test(id(data.hostid)) ||
        typeof data.uid !== 'string' ||
        data.uid.length < 1 ||
        data.uid.length > 128 ||
        /[\x00-\x1f]/.test(data.uid)
      )
        return null;
      return {
        hostid: id(data.hostid),
        uid: data.uid,
        origin: typeof data.origin === 'string' ? data.origin.slice(0, 128) : ''
      };
    } catch (_) {
      return null;
    }
  }
  function peerUrl(url, peer, origin) {
    const safe = safeNavigation(url);
    if (!safe) return null;
    if (!peer.uid) return safe;
    return (
      safe.split('#')[0] +
      '#ne=' +
      encodeURIComponent(JSON.stringify({ hostid: id(peer.hostid), uid: id(peer.uid), origin: id(origin) }))
    );
  }
  function el(tag, value, className) {
    const node = document.createElement(tag);
    if (value !== undefined) node.textContent = String(value);
    if (className) node.className = className;
    return node;
  }
  function button(label, action, className) {
    const node = el('button', label, className);
    node.type = 'button';
    node.addEventListener('click', action);
    return node;
  }
  function notice(root, value, kind = 'info') {
    root.appendChild(el('p', value, `ne-notice ne-${kind}`));
  }
  function table(root, columns, rows, caption) {
    const node = el('table', undefined, 'ne-table');
    if (caption) node.appendChild(el('caption', caption));
    const head = el('thead'),
      tr = el('tr');
    for (const column of columns) {
      const th = el('th', column.label);
      th.scope = 'col';
      tr.appendChild(th);
    }
    head.appendChild(tr);
    node.appendChild(head);
    const body = el('tbody');
    for (const row of rows) {
      const tr = el('tr');
      for (const column of columns) {
        const td = el('td'),
          value = column.value(row);
        td.append(value instanceof Node ? value : document.createTextNode(text(value)));
        tr.appendChild(td);
      }
      body.appendChild(tr);
    }
    node.appendChild(body);
    root.appendChild(node);
    return node;
  }
  // Host and interface lookups run per link and per finding, so each payload is indexed once.
  const indexes = new WeakMap();
  function indexOf(payload) {
    let index = indexes.get(payload);
    if (!index) {
      index = {
        hosts: new Map(asRows(payload.hosts).map(h => [id(h.hostid), h])),
        interfaces: new Map(asRows(payload.interfaces).map(p => [`${id(p.hostid)}|${id(p.uid)}`, p]))
      };
      indexes.set(payload, index);
    }
    return index;
  }
  function findHost(payload, hostid) {
    return indexOf(payload).hosts.get(id(hostid));
  }
  function findInterface(payload, hostid, uid) {
    return indexOf(payload).interfaces.get(`${id(hostid)}|${id(uid)}`);
  }
  function interfaceName(payload, hostid, uid) {
    return uid ? (findInterface(payload, hostid, uid)?.name ?? uid) : null;
  }
  function hostName(payload, hostid) {
    return findHost(payload, hostid)?.name ?? hostid;
  }
  function observations(root, payload, hostid) {
    const quality = asRows(payload.quality).filter(q => !hostid || id(q.hostid) === id(hostid));
    for (const host of asRows(payload.hosts).filter(
      h => (!hostid || id(h.hostid) === id(hostid)) && h.snmp_available === false
    )) {
      notice(
        root,
        `${text(host.name)}: the SNMP agent is unreachable. Values shown are the last successful observations.`,
        'warning'
      );
    }
    if (!quality.length) {
      notice(root, 'No collection timestamps or capability evidence are available.');
      return;
    }
    const summaries = quality.filter(q =>
      ['interfaces', 'interfaces.inventory', 'interfaces.state', 'lldp', 'lag'].includes(q.dataset)
    );
    if (!hostid && new Set(summaries.map(q => id(q.hostid))).size > 1) {
      for (const dataset of [...new Set(summaries.map(q => q.dataset))]) {
        const rows = summaries.filter(q => q.dataset === dataset);
        const current = rows.filter(q => q.freshness === 'current' && q.status === 'ok').length;
        notice(
          root,
          `${dataset}: ${current} current successful observations of ${rows.length} permitted hosts; ${rows.length - current} need quality review.`,
          current === rows.length ? 'info' : 'warning'
        );
      }
      return;
    }
    for (const row of summaries) {
      const state = row.freshness ?? 'unknown';
      notice(
        root,
        `${row.dataset}: ${text(row.status)}; ${state}; observed ${text(row.observed_at)}${row.complete === false ? '; partial collection' : ''}.`,
        state === 'current' && row.status === 'ok' ? 'info' : 'warning'
      );
    }
  }
  function capabilities(root, payload, hostid) {
    const rows = asRows(payload.quality).filter(
      q => (!hostid || id(q.hostid) === id(hostid)) && /^(vlan|stp)$/.test(q.dataset)
    );
    const state = dataset => {
      const counts = new Map();
      for (const q of rows.filter(q => q.dataset === dataset)) {
        const value = text(q.capability?.state ?? q.capability);
        counts.set(value, (counts.get(value) ?? 0) + 1);
      }
      return (
        [...counts]
          .map(([value, n]) => (counts.size > 1 || n > 1 ? `${value} on ${n} ${n === 1 ? 'host' : 'hosts'}` : value))
          .join(', ') || 'not collected'
      );
    };
    notice(root, `VLAN collection: ${state('vlan')}. STP collection: ${state('stp')}.`);
  }
  function endpoints(edge) {
    const source = edge.source_endpoint ?? { hostid: edge.source, uid: edge.source_uid };
    const target = edge.target_endpoint ?? { hostid: edge.target, uid: edge.target_uid };
    return {
      source: { ...source, uid: source.uid ?? source.interface_uid },
      target: { ...target, uid: target.uid ?? target.interface_uid }
    };
  }
  function peersFor(payload, port) {
    const peers = [];
    for (const edge of asRows(payload.edges)) {
      const { source, target } = endpoints(edge);
      if (id(source.hostid) === id(port.hostid) && id(source.uid) === id(port.uid)) peers.push({ edge, peer: target });
      else if (id(target.hostid) === id(port.hostid) && id(target.uid) === id(port.uid))
        peers.push({ edge, peer: source });
    }
    return peers;
  }
  function peerLink(payload, peer, origin, broadcast) {
    const host = findHost(payload, peer.hostid);
    if (!host) return el('span', 'External, ambiguous or undisclosed peer');
    const href = peerUrl(host.dashboard_url ?? host.url, peer, origin);
    if (href) {
      const link = el('a', host.name ?? host.hostid);
      link.href = href;
      return link;
    }
    return button(host.name ?? host.hostid, () => broadcast(host.hostid), 'ne-link-button');
  }
  /**
   * Interface detail. `ctx.linked === false` drops the linked-widget button (no dashboard to broadcast to);
   * `ctx.selectInterface` makes each resolved peer selectable in place; `ctx.showHost` names the switch.
   */
  function showDetail(root, payload, port, broadcast, ctx = {}) {
    root.replaceChildren();
    root.appendChild(el('h4', `${text(port.name)} · ${stateLabel(port)}`));
    const list = el('dl', undefined, 'ne-details');
    const details = {
      ...(ctx.showHost ? { Switch: hostName(payload, port.hostid) } : {}),
      Description: port.description,
      Alias: port.alias,
      'Interface UID': port.uid,
      'Current ifIndex': port.if_index,
      Classification: isPhysical(port) ? 'Physical' : port.physical === false ? 'Logical' : 'Unknown',
      'Member / slot / port': [port.member, port.slot, port.port].map(text).join(' / '),
      'Administrative state': enumValue(port.admin_status),
      'Operational state': enumValue(port.oper_status),
      'Observed speed': speed(port.speed_bps),
      'Intended speed': speed(port.expected_speed_bps),
      'Expected speed source': [port.expected_speed_source ?? port.policy?.source, port.expected_speed_basis]
        .filter(Boolean)
        .join(' · '),
      'Observed at': port.observed_at ?? port.quality?.observed_at,
      Freshness: port.freshness ?? port.quality?.freshness,
      Duplex: port.duplex,
      MTU: port.mtu,
      'MAC address': port.mac_address
    };
    for (const [label, value] of Object.entries(details)) {
      list.appendChild(el('dt', label));
      list.appendChild(el('dd', text(value)));
    }
    root.appendChild(list);
    const sections = [];
    if (port.capability) {
      const c = port.capability,
        speeds = list => (Array.isArray(list) ? (list.length ? list.map(speed).join(', ') : 'None') : 'Unknown');
      sections.push([
        'Port capability',
        {
          'Auto-negotiation': c.autoneg_enabled === true ? 'Enabled' : c.autoneg_enabled === false ? 'Disabled' : null,
          Supported: speeds(c.supported_speeds_bps),
          Advertised: speeds(c.advertised_speeds_bps),
          'Partner advertised': speeds(c.partner_advertised_speeds_bps),
          'Operating (MAU)': `${speed(c.oper_speed_bps)} ${text(c.oper_duplex)}`
        }
      ]);
    }
    if (port.vlan) {
      const v = port.vlan;
      sections.push([
        'VLAN membership',
        {
          ...(v.via_lag ? { 'Carried via': v.via_lag } : {}),
          Mode: v.mode,
          'Native VLAN (PVID)': v.pvid,
          Untagged: v.untagged || 'None',
          Tagged: v.tagged || 'None',
          Forbidden: v.forbidden || 'None'
        }
      ]);
    }
    for (const [title, values] of sections) {
      root.appendChild(el('h4', title));
      const dl = el('dl', undefined, 'ne-details');
      for (const [label, value] of Object.entries(values)) {
        dl.appendChild(el('dt', label));
        dl.appendChild(el('dd', text(value)));
      }
      root.appendChild(dl);
    }
    if (asRows(port.stp).length) {
      table(
        root,
        [
          { label: 'Instance', value: r => r.instance },
          { label: 'State', value: r => r.state },
          { label: 'Role', value: r => `${text(r.role)}${r.role_source === 'derived' ? ' (derived)' : ''}` },
          { label: 'Cost', value: r => r.cost },
          { label: 'Edge port', value: r => (r.edge === true ? 'Yes' : r.edge === false ? 'No' : null) }
        ],
        port.stp,
        'Spanning tree'
      );
    }
    const ownHost = findHost(payload, port.hostid);
    if (ownHost?.dashboard_url) {
      const href = peerUrl(ownHost.dashboard_url, { hostid: port.hostid, uid: port.uid }, 'Interface detail');
      if (href) {
        const link = el('a', 'Open host dashboard with this port highlighted');
        link.href = href;
        root.appendChild(link);
      }
    }
    if (port.itemid && ctx.linked !== false)
      root.appendChild(button('Select interface in linked widgets', () => broadcast(port.hostid, port.itemid)));
    const peers = peersFor(payload, port);
    root.appendChild(el('h4', 'LLDP peers'));
    if (!peers.length) notice(root, 'No permitted LLDP peer is resolved for this interface.');
    for (const { peer, edge } of peers) {
      const row = el('p');
      const remote = findInterface(payload, peer.hostid, peer.uid);
      row.append(
        peerLink(payload, peer, port.name, broadcast),
        document.createTextNode(
          ` · port ${text(remote?.name ?? peer.name ?? peer.uid)} · ${text(edge.confidence ?? edge.status)} · ${text(edge.freshness)}`
        )
      );
      if (remote && ctx.selectInterface) {
        row.appendChild(document.createTextNode(' '));
        row.appendChild(button(`Select ${text(remote.name)}`, () => ctx.selectInterface(remote), 'ne-link-button'));
      }
      root.appendChild(row);
    }
    const lagRows = asRows(payload.lags).filter(
      lag =>
        id(lag.hostid) === id(port.hostid) &&
        (id(lag.uid ?? lag.interface_uid ?? lag.logical_interface_uid) === id(port.uid) ||
          asRows(lag.members).some(m => id(typeof m === 'string' ? m : (m.interface_uid ?? m.uid)) === id(port.uid)))
    );
    for (const lag of lagRows)
      notice(
        root,
        `LAG ${text(lag.name ?? lag.uid ?? lag.aggregator_id)} · ${LAG_MODES[lag.mode] ?? 'Unknown mode'} · ${asRows(lag.members).length} observed members.`
      );
  }
  function renderPorts(root, payload, broadcast, state = {}) {
    const hostid = id(payload.scope?.hostid),
      ports = asRows(payload.interfaces).filter(p => id(p.hostid) === hostid);
    if (!ports.length) {
      notice(root, 'No validated interface observations are available for this host.');
      return;
    }
    observations(root, payload, hostid);
    const legends = {
      physical: Object.values(STATE_LABELS).join('  '),
      vlan: Object.values(VLAN_LABELS).join('  '),
      stp: `${Object.entries(STP_MARKS)
        .map(([state, mark]) => `${mark} ${state[0].toUpperCase()}${state.slice(1)}`)
        .join('  ')}  * derived role`,
      lldp: '⇄ LLDP neighbour  · No neighbour'
    };
    const legend = el('p', undefined, 'ne-legend');
    root.appendChild(legend);
    const physical = ports.filter(isPhysical),
      other = ports.filter(p => !isPhysical(p));
    const toolbar = el('div', undefined, 'ne-toolbar'),
      layout = el('select');
    layout.setAttribute('aria-label', 'Physical layout');
    for (const value of ['auto', '24', '48', 'mixed', 'stack', 'generic']) {
      const option = el(
        'option',
        {
          auto: 'Automatic',
          24: '24 port',
          48: '48 port',
          mixed: 'Mixed copper / fibre',
          stack: 'Stack',
          generic: 'Generic rows'
        }[value]
      );
      option.value = value;
      layout.appendChild(option);
    }
    layout.value = payload.scope?.layout ?? 'auto';
    toolbar.appendChild(layout);
    const host = findHost(payload, hostid) ?? {};
    const layer = el('select'),
      vlanPick = el('select'),
      instancePick = el('select');
    layer.setAttribute('aria-label', 'Layer');
    vlanPick.setAttribute('aria-label', 'VLAN');
    instancePick.setAttribute('aria-label', 'Spanning-tree instance');
    for (const [value, label] of [
      ['physical', 'Physical'],
      ['vlan', 'VLAN'],
      ['stp', 'STP'],
      ['lldp', 'LLDP']
    ]) {
      const option = el('option', label);
      option.value = value;
      layer.appendChild(option);
    }
    const vlanIds = new Set(asRows(host.vlans).map(v => Number(v.vlan_id)));
    for (const p of ports) for (const v of vlanSet(p.vlan?.carried)) vlanIds.add(v);
    for (const v of [...vlanIds].sort((a, b) => a - b)) {
      const named = asRows(host.vlans).find(x => Number(x.vlan_id) === v);
      const option = el('option', named?.name ? `${v} · ${named.name}` : String(v));
      option.value = String(v);
      vlanPick.appendChild(option);
    }
    const instances = new Set(asRows(host.stp).map(b => Number(b.instance)));
    for (const p of ports) for (const r of asRows(p.stp)) instances.add(Number(r.instance));
    for (const i of [...instances].sort((a, b) => a - b)) {
      const option = el('option', i === 0 ? 'CIST / instance 0' : `Instance ${i}`);
      option.value = String(i);
      instancePick.appendChild(option);
    }
    layer.value = state.layer ?? payload.scope?.layer ?? 'physical';
    if (state.vlan) vlanPick.value = state.vlan;
    if (state.instance) instancePick.value = state.instance;
    toolbar.append(layer, vlanPick, instancePick);
    root.appendChild(toolbar);
    const layerNote = el('p', undefined, 'ne-legend');
    root.appendChild(layerNote);
    applyColours(root, payload.scope?.colours);
    const tabs = el('div', undefined, 'ne-member-tabs');
    tabs.setAttribute('role', 'tablist');
    tabs.setAttribute('aria-label', 'Stack members');
    root.appendChild(tabs);
    const panel = el('div', undefined, 'ne-port-panel'),
      drawer = el('section', undefined, 'ne-drawer');
    drawer.setAttribute('aria-label', 'Selected interface details');
    drawer.setAttribute('aria-live', 'polite');
    const selection = fragmentContext(global.location?.hash);
    let selected =
      selection?.hostid === hostid
        ? ports.find(p => id(p.uid) === selection.uid)
        : ports.find(p => id(p.uid) === state.selected_uid && id(p.hostid) === state.selected_hostid);
    const isSelected = port =>
      !!selected && id(selected.uid) === id(port.uid) && id(selected.hostid) === id(port.hostid);
    function select(port) {
      selected = port;
      state.selected_uid = id(port.uid);
      state.selected_hostid = id(port.hostid);
      state.last_broadcast = `${port.hostid}:${port.uid}`;
      for (const node of panel.querySelectorAll('[aria-pressed]'))
        node.setAttribute('aria-pressed', node.dataset.uid === id(port.uid) ? 'true' : 'false');
      showDetail(drawer, payload, port, broadcast);
      broadcast(port.hostid, port.itemid);
    }
    function tileView(port) {
      if (layer.value === 'vlan') {
        const role = vlanRole(port, vlanPick.value);
        return {
          className: `ne-vlan-${role}`,
          status: VLAN_LABELS[role],
          extra: port.vlan?.pvid ? `PVID ${port.vlan.pvid}` : ''
        };
      }
      if (layer.value === 'stp') {
        const row = stpPort(port, instancePick.value || 0);
        return { className: `ne-stp-${stpClass(row)}`, status: stpLabel(row), extra: '' };
      }
      if (layer.value === 'lldp') {
        const peer = peersFor(payload, port)[0]?.peer;
        const name = peer ? (peer.hostid ? hostName(payload, peer.hostid) : 'External or undisclosed') : '';
        return {
          className: peer ? 'ne-lldp-peer' : 'ne-lldp-none',
          status: peer ? '⇄ Neighbour' : '· No neighbour',
          extra: name
        };
      }
      return { className: `ne-state-${portState(port)}`, status: stateLabel(port), extra: speed(port.speed_bps) };
    }
    let firstDraw = true;
    function draw() {
      panel.replaceChildren();
      state.layer = layer.value;
      state.vlan = vlanPick.value;
      state.instance = instancePick.value;
      vlanPick.hidden = layer.value !== 'vlan';
      instancePick.hidden = layer.value !== 'stp';
      legend.textContent = legends[layer.value];
      layerNote.textContent =
        layer.value === 'vlan' && !vlanIds.size
          ? 'No VLAN membership has been collected for this host.'
          : layer.value === 'stp' && !instances.size
            ? 'No spanning-tree data has been collected for this host.'
            : '';
      if (!physical.length)
        notice(
          panel,
          'No interfaces have confirmed physical-port classification. Use the interface table below; no chassis geometry has been inferred.'
        );
      // Stack members become tabs when the layout is Stack, or Automatic with more than one placed member.
      const groups = groupPorts(physical, layout.value),
        members = [...new Set(groups.map(g => g.member))];
      const tabbed = ['auto', 'stack'].includes(layout.value) && members.filter(m => m !== null).length > 1;
      tabs.replaceChildren();
      tabs.hidden = !tabbed;
      if (tabbed && firstDraw && selected && members.some(m => id(m) === id(selected.member ?? null)))
        state.member = id(selected.member ?? null);
      if (tabbed && !members.some(m => id(m) === state.member)) state.member = id(members[0]);
      firstDraw = false;
      if (tabbed)
        for (const member of members) {
          const tab = button(
            member === null ? 'Unplaced ports' : `Member ${member}`,
            () => {
              state.member = id(member);
              draw();
              tabs.querySelector('[aria-selected="true"]')?.focus();
            },
            'ne-member-tab'
          );
          tab.setAttribute('role', 'tab');
          tab.setAttribute('aria-selected', id(member) === state.member ? 'true' : 'false');
          tab.tabIndex = id(member) === state.member ? 0 : -1;
          tab.addEventListener('keydown', event => {
            if (!['ArrowLeft', 'ArrowRight'].includes(event.key)) return;
            event.preventDefault();
            const next =
              members[
                (members.indexOf(member) + (event.key === 'ArrowRight' ? 1 : members.length - 1)) % members.length
              ];
            state.member = id(next);
            draw();
            tabs.querySelector('[aria-selected="true"]')?.focus();
          });
          tabs.appendChild(tab);
        }
      for (const group of groups.filter(g => !tabbed || id(g.member) === state.member)) {
        const section = el('section', undefined, 'ne-port-member');
        section.appendChild(el('h4', group.key));
        const grid = el('div', undefined, `ne-port-grid ne-layout-${layout.value}`);
        grid.setAttribute('role', 'group');
        grid.setAttribute('aria-label', `Ports ${group.key}`);
        for (const port of group.ports) {
          const view = tileView(port);
          const tile = button('', () => select(port), `ne-port ${view.className}`);
          tile.dataset.uid = id(port.uid);
          tile.setAttribute('aria-pressed', isSelected(port) ? 'true' : 'false');
          tile.setAttribute(
            'aria-label',
            `${text(port.name)}: ${view.status}; ${view.extra}; ${text(port.description)}`
          );
          tile.append(
            el('span', text(port.name ?? port.port), 'ne-port-number'),
            el('span', view.status, 'ne-port-status'),
            el('span', view.extra, 'ne-port-speed')
          );
          tile.addEventListener('keydown', event => {
            if (!['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown'].includes(event.key)) return;
            event.preventDefault();
            // Up and Down move one rendered row, whatever the layout or screen width made the column count.
            const columns = getComputedStyle(grid).gridTemplateColumns.split(' ').filter(Boolean).length || 1;
            const buttons = [...grid.querySelectorAll('button')],
              index = buttons.indexOf(tile),
              step = { ArrowLeft: -1, ArrowRight: 1, ArrowUp: -columns, ArrowDown: columns }[event.key];
            buttons[Math.max(0, Math.min(buttons.length - 1, index + step))]?.focus();
          });
          grid.appendChild(tile);
        }
        section.appendChild(grid);
        panel.appendChild(section);
      }
    }
    for (const control of [layout, layer, vlanPick, instancePick]) control.addEventListener('change', draw);
    draw();
    root.append(panel, drawer);
    if (selected) {
      showDetail(drawer, payload, selected, broadcast);
      if (selection?.origin) notice(drawer, `Navigated from ${selection.origin}.`);
      if (state.last_broadcast !== `${selected.hostid}:${selected.uid}`) {
        broadcast(selected.hostid, selected.itemid);
        state.last_broadcast = `${selected.hostid}:${selected.uid}`;
      }
    }
    const details = el('details');
    details.appendChild(el('summary', `Interface table (${ports.length}; ${other.length} logical or unclassified)`));
    table(
      details,
      [
        { label: 'Interface', value: p => button(text(p.name), () => select(p), 'ne-link-button') },
        {
          label: 'Classification',
          value: p => (isPhysical(p) ? 'Physical' : p.physical === false ? 'Logical' : 'Unknown')
        },
        { label: 'State', value: stateLabel },
        { label: 'Speed', value: p => speed(p.speed_bps) },
        { label: 'Description', value: p => p.description }
      ],
      ports,
      'All observed interfaces'
    );
    root.appendChild(details);
    capabilities(root, payload, hostid);
  }
  function svgEl(tag, attributes = {}, value) {
    const node = document.createElementNS('http://www.w3.org/2000/svg', tag);
    for (const [key, val] of Object.entries(attributes)) node.setAttribute(key, String(val));
    if (value !== undefined) node.textContent = String(value);
    return node;
  }
  function vlanNotes(root, payload, vlan, collected, trace, from) {
    if (!collected) notice(root, 'No VLAN membership has been collected for the visible switches.');
    else
      notice(
        root,
        `Solid: both ends carry VLAN ${vlan}. Red: the physical link exists but one end does not permit VLAN ${vlan}. Grey: neither end carries it.`
      );
    if (!trace) return;
    if (!trace.stops.length)
      notice(
        root,
        `VLAN ${vlan} reaches ${trace.reached.length} switches from ${text(hostName(payload, from))} without stopping at a monitored link.`
      );
    for (const stop of trace.stops)
      notice(
        root,
        `VLAN ${vlan} stops at ${text(hostName(payload, stop.hostid))} port ${text(interfaceName(payload, stop.hostid, stop.uid))}: physical link yes, VLAN ${vlan} not permitted.`,
        'warning'
      );
  }
  /** Explains the root marker, in every mode: who the root is, or why none is marked. */
  function stpNotes(root, info, mode) {
    const marked = mode === 'stp' ? info.roots : info.current;
    const parts = [];
    if (marked.size) parts.push('★ marks the observed spanning-tree root bridge (instance 0).');
    if (info.outside.length)
      parts.push(
        `The spanning-tree root (bridge ${info.outside.join(', ')}) is not a visible switch, so it is not drawn.`
      );
    if (info.disputed.length)
      parts.push(
        mode === 'stp'
          ? 'Visible switches disagree about the spanning-tree root, so none is marked as the root; ☆ marks each switch that reports itself as root. See the stp_root_disagreement finding.'
          : 'Visible switches disagree about the spanning-tree root, so none is marked. See the stp_root_disagreement finding.'
      );
    if (mode !== 'stp' && info.roots.size > info.current.size)
      parts.push('A root whose spanning-tree observation is not current is marked only in the Spanning Tree view.');
    if (mode === 'stp') {
      if (!info.roots.size && !info.outside.length && !info.disputed.length)
        parts.push('No spanning-tree data has been collected for the visible switches.');
      else parts.push('Root-port links are highlighted; ⊘ marks a blocking port end.');
    }
    if (parts.length) notice(root, parts.join(' '), mode === 'stp' || !info.disputed.length ? 'info' : 'warning');
  }
  function onActivate(node, action) {
    node.addEventListener('click', action);
    node.addEventListener('keydown', event => {
      if (['Enter', ' '].includes(event.key)) {
        event.preventDefault();
        action();
      }
    });
  }
  function edgeOverlay(context, edge) {
    if (context.mode === 'vlan') {
      const stop = context.trace?.stops.some(s => edge.members.some(m => m.id === s.edge.id));
      return ` ne-edge-vlan-${edgeVlanState(edge, context.vlan)}${stop ? ' ne-edge-trace-stop' : ''}`;
    }
    if (context.mode === 'stp') {
      const ends = edge.members.map(m => m.stp).filter(Boolean);
      if (ends.some(s => s.blocked)) return ' ne-edge-stp-blocked';
      if (ends.some(s => s.source?.role === 'root' || s.target?.role === 'root')) return ' ne-edge-stp-rootpath';
    }
    return '';
  }
  /** The LAGs a member link belongs to, as "switch LAG (mode)". */
  function lagNames(payload, member) {
    return asRows(payload.lags)
      .filter(lag => asRows(lag.edge_ids).map(id).includes(id(member.id)))
      .map(
        lag =>
          `${text(hostName(payload, lag.hostid))} ${text(lag.name ?? lag.interface_uid)} (${LAG_MODES[lag.mode] ?? 'Unknown mode'})`
      )
      .join('; ');
  }
  /** A link end: a button selecting the interface when it is a visible one, else its plain identity. */
  function endpointCell(payload, hostid, uid, ctx) {
    const port = hostid === null || hostid === undefined ? null : findInterface(payload, hostid, uid);
    if (!port) return hostid === null || hostid === undefined ? 'Undisclosed' : text(uid);
    const node = button(text(port.name), () => ctx.selectInterface(port), 'ne-link-button ne-endpoint');
    node.setAttribute('aria-label', `Select interface ${text(hostName(payload, hostid))} ${text(port.name)}`);
    return node;
  }
  function showEdgeDetails(details, payload, edge, ctx) {
    details.replaceChildren();
    const aggregation = lagModeLabel(payload, edge);
    details.appendChild(
      el(
        'h4',
        `${edge.members.length > 1 ? 'LAG member links' : 'Observed physical link'}${aggregation ? ` (${aggregation})` : ''} · ${text(edge.status)}; confidence ${text(edge.confidence)}`
      )
    );
    const stpEnd = end => (end ? `${text(end.role)} ${text(end.state)}` : 'Unknown');
    table(
      details,
      [
        { label: 'Source switch', value: e => hostName(payload, e.source) },
        { label: 'Source interface', value: e => endpointCell(payload, e.source, e.source_uid, ctx) },
        {
          label: 'Destination switch',
          value: e => (e.target === null ? 'Undisclosed peer' : hostName(payload, e.target))
        },
        { label: 'Destination interface', value: e => endpointCell(payload, e.target, e.target_uid, ctx) },
        { label: 'LAG', value: e => lagNames(payload, e) || 'None observed' },
        { label: 'VLANs on both ends', value: e => (e.vlan ? e.vlan.common || 'None' : 'Unknown') },
        {
          label: 'Native VLAN',
          value: e => (e.vlan ? `${text(e.vlan.source_pvid)} / ${text(e.vlan.target_pvid)}` : 'Unknown')
        },
        {
          label: 'STP role and state (source / destination)',
          value: e => (e.stp ? `${stpEnd(e.stp.source)} / ${stpEnd(e.stp.target)}` : 'Unknown')
        },
        { label: 'Confidence', value: e => e.confidence },
        { label: 'Freshness', value: e => e.freshness }
      ],
      edge.members,
      'Individual observed members'
    );
  }
  /** Device identity and health, its visible interfaces, and the way to its host dashboard. */
  function showHost(details, payload, host, ctx) {
    details.replaceChildren();
    const hostid = id(host.hostid),
      bridge = asRows(host.stp).find(b => Number(b.instance) === 0);
    details.appendChild(el('h4', `${ctx.stp?.roots.has(hostid) ? '★ ' : ''}${text(host.name)}`));
    const addresses = asRows(host.addressing?.addresses).length
      ? host.addressing.addresses.map(a => `${a.address} (${a.state})`).join(', ')
      : asRows(host.management_addresses).join(', ');
    const facts = {
      'Vendor / model': [host.vendor, host.model].filter(Boolean).join(' / '),
      Firmware: host.firmware,
      Site: host.site,
      'Matching domain': host.domain,
      'Management addresses': addresses,
      'SNMP agent': host.snmp_available === false ? 'Unreachable' : host.snmp_available === true ? 'Available' : null,
      'Spanning tree (instance 0)': bridge
        ? bridge.is_root
          ? `Root bridge ${text(bridge.bridge_id)}`
          : `Bridge ${text(bridge.bridge_id)}; root ${text(bridge.root_bridge_id)}, cost ${text(bridge.root_cost)}`
        : null
    };
    const list = el('dl', undefined, 'ne-details');
    for (const [label, value] of Object.entries(facts)) {
      list.appendChild(el('dt', label));
      list.appendChild(el('dd', text(value)));
    }
    details.appendChild(list);
    if (host.out_of_subnet)
      notice(details, 'Advertised management addressing is outside the selected subnet.', 'warning');
    if (host.outside_site)
      notice(
        details,
        'This switch is outside the selected site. It is shown because it connects to a switch inside it.'
      );
    const href = safeNavigation(host.dashboard_url);
    if (href) {
      const link = el('a', 'Open host dashboard', 'ne-open-dashboard');
      link.href = href;
      details.appendChild(link);
    }
    observations(details, payload, hostid);
    const ports = asRows(payload.interfaces)
      .filter(p => id(p.hostid) === hostid)
      .sort((a, b) => natural(a.member ?? Infinity, b.member ?? Infinity) || natural(a.name, b.name));
    const section = el('details');
    section.open = true;
    section.appendChild(el('summary', `Interfaces (${ports.length})`));
    if (!ports.length) notice(section, 'No validated interface observations are available for this switch.');
    else
      table(
        section,
        [
          { label: 'Interface', value: p => button(text(p.name), () => ctx.selectInterface(p), 'ne-link-button') },
          { label: 'State', value: stateLabel },
          { label: 'Speed', value: p => speed(p.speed_bps) },
          {
            label: 'Peer',
            value: p =>
              peersFor(payload, p)
                .map(({ peer }) => (peer.hostid ? hostName(payload, peer.hostid) : 'Undisclosed'))
                .join(', ')
          },
          { label: 'Description', value: p => p.description }
        ],
        ports,
        `Visible interfaces of ${text(host.name)}`
      );
    details.appendChild(section);
  }
  /** Draws one (possibly grouped) link; returns the line, or null when neither end is a visible switch. */
  function drawEdge(context, edge, siblings) {
    const { payload, svg, byId } = context;
    const a = byId.get(id(edge.source)),
      b = byId.get(id(edge.target));
    if (!a && !b) return null;
    let start = a ?? b,
      end = a && b ? b : stubPoint(context, start);
    // Lines stop at the switch boxes rather than running underneath them.
    if (a && b) [start, end] = [boxEdgePoint(start, end, 0), boxEdgePoint(end, start, 0)];
    else start = boxEdgePoint(start, end, 0);
    // Parallel links between the same two switches (expanded LAG members) are drawn side by side.
    if (a && b && siblings.length > 1) {
      const dx = end.x - start.x,
        dy = end.y - start.y,
        len = Math.hypot(dx, dy) || 1,
        shift = (siblings.indexOf(edge) - (siblings.length - 1) / 2) * LAYOUT.parallelSpacing;
      start = { x: start.x - (dy / len) * shift, y: start.y + (dx / len) * shift };
      end = { x: end.x - (dy / len) * shift, y: end.y + (dx / len) * shift };
    }
    const uncertain =
      !a ||
      !b ||
      edge.freshness === 'stale' ||
      edge.confidence === 'ambiguous' ||
      !['confirmed', 'bidirectional', 'high'].includes(edge.confidence ?? edge.status);
    const visible = a ?? b;
    const label =
      a && b
        ? `Link ${text(a.name)} to ${text(b.name)}`
        : `Link from ${text(visible.name)} to an external or undisclosed peer`;
    const line = svgEl('line', {
      x1: start.x,
      y1: start.y,
      x2: end.x,
      y2: end.y,
      class: `ne-edge${uncertain ? ' ne-edge-uncertain' : ''}${edgeOverlay(context, edge)}`,
      tabindex: 0,
      role: 'button',
      'aria-pressed': 'false',
      'aria-label': `${label}; ${edge.members.length} members; ${text(edge.status)}; ${text(edge.freshness)}`
    });
    line.dataset.external = a && b ? 'false' : 'true';
    onActivate(line, () => context.select.edge(edge));
    svg.appendChild(line);
    if (!(a && b)) svg.appendChild(svgEl('circle', { cx: end.x, cy: end.y, r: 6, class: 'ne-external' }));
    if (edge.members.length > 1) {
      const aggregation = lagModeLabel(payload, edge);
      svg.appendChild(
        svgEl(
          'text',
          { x: (start.x + end.x) / 2, y: (start.y + end.y) / 2 - 5, class: 'ne-svg-label' },
          `LAG ×${edge.members.length}${aggregation ? ` · ${aggregation}` : ''}`
        )
      );
    }
    if (context.mode === 'stp' && a && b) drawBlockMarks(svg, byId, edge, a, b);
    return line;
  }
  /**
   * Where the next external or undisclosed peer of a switch is drawn: fanned around the switch in a fixed order
   * so several stubs never sit on top of each other. Stubs are placed after the switches and never move them.
   */
  const STUB_ANGLES = [35, 145, -35, -145, 70, 110, -70, -110];
  function stubPoint(context, host) {
    const slots = (context.stubs ??= new Map()),
      n = slots.get(id(host.hostid)) ?? 0;
    slots.set(id(host.hostid), n + 1);
    const angle = (STUB_ANGLES[n % STUB_ANGLES.length] * Math.PI) / 180,
      radius = LAYOUT.stubRadius + Math.floor(n / STUB_ANGLES.length) * 22;
    const point = { x: host.x + Math.cos(angle) * radius, y: host.y + Math.sin(angle) * radius };
    (context.stubPoints ??= []).push(point);
    return point;
  }
  /** The point `gap` units outside the switch box at `near`, on the straight line towards `far`. */
  function boxEdgePoint(near, far, gap) {
    const dx = far.x - near.x,
      dy = far.y - near.y,
      len = Math.hypot(dx, dy) || 1,
      t = Math.min(
        dx ? LAYOUT.nodeWidth / 2 / Math.abs(dx) : Infinity,
        dy ? LAYOUT.nodeHeight / 2 / Math.abs(dy) : Infinity,
        1
      );
    return { x: near.x + dx * t + (dx / len) * gap, y: near.y + dy * t + (dy / len) * gap };
  }
  /** Marks each blocking port end just outside its switch box, on the link towards the peer. */
  function drawBlockMarks(svg, byId, edge, a, b) {
    for (const member of edge.members)
      for (const side of ['source', 'target']) {
        if (!['blocking', 'discarding'].includes(member.stp?.[side]?.state)) continue;
        const near = byId.get(id(member[side])),
          far = near === a ? b : a;
        if (!near) continue;
        const point = boxEdgePoint(near, far, LAYOUT.blockMarkGap);
        svg.appendChild(svgEl('text', { x: point.x, y: point.y + 4, class: 'ne-svg-label ne-stp-block-mark' }, '⊘'));
      }
  }
  /**
   * Pan and zoom by changing the SVG viewBox, so the drawing never grows past its container. `views[key]` keeps
   * the view for each placement (Layer 2/VLAN, Spanning Tree) across redraws.
   */
  function topologyViewport(graph, svg, arranged, views, key, stubs = []) {
    const pad = 30;
    // Switch boxes plus the external stubs drawn around them.
    const boxes = [
      ...arranged.map(h => [h.x, h.y, LAYOUT.nodeWidth / 2, LAYOUT.nodeHeight / 2]),
      ...stubs.map(p => [p.x, p.y, 8, 8])
    ];
    const bounds = boxes.length
      ? (() => {
          const left = Math.min(...boxes.map(([x, , w]) => x - w)),
            right = Math.max(...boxes.map(([x, , w]) => x + w)),
            top = Math.min(...boxes.map(([, y, , h]) => y - h)),
            bottom = Math.max(...boxes.map(([, y, , h]) => y + h));
          return { x: left - pad, y: top - pad, w: right - left + 2 * pad, h: bottom - top + 2 * pad };
        })()
      : { x: 0, y: 0, w: 500, h: 180 };
    const framed = (box, minW, minH) => {
      const w = Math.max(box.w, minW),
        h = Math.max(box.h, minH);
      return { x: box.x - (w - box.w) / 2, y: box.y - (h - box.h) / 2, w, h };
    };
    // A small graph keeps its proportions instead of filling the canvas with two huge boxes.
    const home = framed(bounds, 640, 240);
    svg.style.aspectRatio = `${Math.round(home.w)} / ${Math.round(home.h)}`;
    const smallest = 160,
      largest = Math.max(home.w, home.h) * 4;
    let view = views[key] ? { ...views[key] } : { ...home };
    const viewport = {
      apply() {
        svg.setAttribute('viewBox', [view.x, view.y, view.w, view.h].map(v => Math.round(v * 10) / 10).join(' '));
        svg.dataset.zoom = (home.w / view.w).toFixed(2);
        views[key] = { ...view };
      },
      /** factor < 1 zooms in, around (cx, cy) in drawing units or the view centre. */
      zoom(factor, cx = view.x + view.w / 2, cy = view.y + view.h / 2) {
        const w = Math.min(largest, Math.max(smallest, view.w * factor)),
          ratio = w / view.w;
        view = { x: cx - (cx - view.x) * ratio, y: cy - (cy - view.y) * ratio, w, h: view.h * ratio };
        viewport.apply();
      },
      /** Moves by a fraction of the visible width and height. */
      pan(fx, fy) {
        view = { ...view, x: view.x + view.w * fx, y: view.y + view.h * fy };
        viewport.apply();
      },
      fit() {
        view = framed(bounds, 0, 0);
        viewport.apply();
      },
      reset() {
        view = { ...home };
        viewport.apply();
      }
    };
    const unitsPerPixel = () => Math.max(view.w / (svg.clientWidth || 1), view.h / (svg.clientHeight || 1));
    let drag = null;
    svg.addEventListener('pointerdown', event => {
      if (event.target !== svg || event.button !== 0) return; // switches and links keep their own clicks
      drag = { x: event.clientX, y: event.clientY };
      svg.setPointerCapture?.(event.pointerId);
      svg.classList.add('ne-panning');
    });
    svg.addEventListener('pointermove', event => {
      if (!drag) return;
      const scale = unitsPerPixel();
      view = { ...view, x: view.x - (event.clientX - drag.x) * scale, y: view.y - (event.clientY - drag.y) * scale };
      drag = { x: event.clientX, y: event.clientY };
      viewport.apply();
    });
    const stop = () => {
      drag = null;
      svg.classList.remove('ne-panning');
    };
    svg.addEventListener('pointerup', stop);
    svg.addEventListener('pointercancel', stop);
    // Plain wheel scrolls the page as usual; Ctrl or Cmd with the wheel zooms around the pointer.
    svg.addEventListener(
      'wheel',
      event => {
        if (!(event.ctrlKey || event.metaKey)) return;
        event.preventDefault();
        const matrix = svg.getScreenCTM?.();
        const point = matrix ? new DOMPoint(event.clientX, event.clientY).matrixTransform(matrix.inverse()) : null;
        viewport.zoom(event.deltaY < 0 ? 1 / 1.15 : 1.15, point?.x, point?.y);
      },
      { passive: false }
    );
    return viewport;
  }
  /** Heads each component's unresolved Spanning Tree area, so those switches never read as part of the tree. */
  function drawUnresolvedLabels(svg, arranged) {
    const areas = new Map();
    for (const h of arranged.filter(h => h.unresolved)) areas.set(h.component, [...(areas.get(h.component) ?? []), h]);
    for (const members of areas.values()) {
      const x = (Math.min(...members.map(h => h.x)) + Math.max(...members.map(h => h.x))) / 2,
        y = Math.min(...members.map(h => h.y)) - LAYOUT.nodeHeight / 2 - 14;
      svg.appendChild(
        svgEl('text', { x, y, class: 'ne-svg-label ne-unresolved-label' }, 'Unresolved STP placement: no root-port path to the root')
      );
    }
  }
  /** A legend of only what this drawing shows. */
  function drawLegend(legend, context, arranged, lines) {
    legend.replaceChildren();
    const { svg, mode, stp } = context,
      has = selector => !!svg.querySelector(selector);
    const rootSet = mode === 'stp' ? stp.roots : stp.current;
    const entries = [
      [arranged.some(h => rootSet.has(id(h.hostid))), '★', 'Spanning-tree root (observed; every visible switch agrees)'],
      [has('.ne-node-root-disputed'), '☆', 'Reports itself as root; the switches disagree'],
      [lines.some(([, l]) => !l.classList.contains('ne-edge-uncertain')), 'solid', 'Confirmed link'],
      [lines.some(([, l]) => l.classList.contains('ne-edge-uncertain')), 'dashed', 'One-sided, ambiguous, external or stale link'],
      [has('.ne-edge-stp-rootpath'), 'rootpath', 'Link to a root port'],
      [has('.ne-stp-block-mark'), '⊘', 'Blocking or discarding port'],
      [has('.ne-edge-vlan-carried'), 'carried', `VLAN ${context.vlan} carried at both ends`],
      [has('.ne-edge-vlan-stopped'), 'stopped', `Physical link; VLAN ${context.vlan} not permitted at one end`],
      [lines.some(([edge]) => edge.members.length > 1), 'LAG', 'Aggregated link; members kept'],
      [has('.ne-external'), '●', 'External or undisclosed peer'],
      [has('.ne-node-context'), 'outside site', 'Connected neighbour outside the selected site'],
      [has('.ne-node-warning'), 'off subnet', 'Outside the management subnet'],
      [has('.ne-node-unreachable'), 'unreachable', 'SNMP unreachable'],
      [has('.ne-node-unresolved'), 'unresolved', 'Placed outside the tree: no observed root-port path to the root']
    ];
    for (const [shown, key, label] of entries) {
      if (!shown) continue;
      const item = el('li');
      const swatch = ['solid', 'dashed', 'rootpath', 'carried', 'stopped'].includes(key);
      item.appendChild(el('span', swatch ? '' : key, swatch ? `ne-legend-key ne-swatch ne-swatch-${key}` : 'ne-legend-key'));
      item.appendChild(el('span', label));
      legend.appendChild(item);
    }
  }
  /** A label cut to `size` characters with an ellipsis; the full name stays in the title and accessible name. */
  const clip = (value, size) => (value.length > size ? `${value.slice(0, size - 1)}…` : value);
  function drawNode(context, host, matching) {
    const { svg } = context,
      hostid = id(host.hostid);
    const carries = context.mode === 'vlan' && asRows(host.vlans).some(v => Number(v.vlan_id) === context.vlan),
      // Layer 2 marks only a current, agreed root; Spanning Tree also marks one whose observation is not current.
      isRoot = (context.mode === 'stp' ? context.stp.roots : context.stp.current).has(hostid),
      claimsRoot =
        context.mode === 'stp' && !isRoot && context.stp.disputed.length > 0 && context.stp.claimed.has(hostid),
      unreachable = host.snmp_available === false;
    const classes = ['ne-node'];
    const notes = [];
    if (!matching) classes.push('ne-muted');
    if (host.out_of_subnet) (classes.push('ne-node-warning'), notes.push('outside management subnet'));
    if (host.outside_site) (classes.push('ne-node-context'), notes.push('outside selected site'));
    if (carries) (classes.push('ne-node-vlan'), notes.push(`has VLAN ${context.vlan}`));
    if (isRoot) (classes.push('ne-node-root'), notes.push('spanning-tree root'));
    if (claimsRoot)
      (classes.push('ne-node-root-disputed'), notes.push('reports itself as spanning-tree root; switches disagree'));
    if (unreachable) (classes.push('ne-node-unreachable'), notes.push('SNMP unreachable'));
    if (host.unresolved) (classes.push('ne-node-unresolved'), notes.push('STP placement unresolved'));
    const group = svgEl('g', {
      transform: `translate(${host.x},${host.y})`,
      tabindex: 0,
      role: 'button',
      'aria-pressed': 'false',
      'aria-label': [text(host.name), ...notes].join('; '),
      class: classes.join(' ')
    });
    group.dataset.hostid = hostid;
    // Shown only while selected: a second outline around the box, so selection does not rest on colour.
    group.appendChild(
      svgEl('rect', {
        x: -LAYOUT.nodeWidth / 2 - 6,
        y: -LAYOUT.nodeHeight / 2 - 6,
        width: LAYOUT.nodeWidth + 12,
        height: LAYOUT.nodeHeight + 12,
        rx: 9,
        class: 'ne-node-halo'
      })
    );
    group.appendChild(
      svgEl('rect', {
        x: -LAYOUT.nodeWidth / 2,
        y: -LAYOUT.nodeHeight / 2,
        width: LAYOUT.nodeWidth,
        height: LAYOUT.nodeHeight,
        rx: 6
      })
    );
    // Short words beside the colours, so no state depends on colour alone.
    const badges = [
      host.outside_site && 'outside site',
      host.out_of_subnet && 'off subnet',
      unreachable && 'unreachable',
      host.unresolved && 'unresolved'
    ].filter(Boolean);
    group.appendChild(
      svgEl(
        'text',
        { 'text-anchor': 'middle', y: badges.length ? -2 : 4 },
        clip(`${isRoot ? '★ ' : claimsRoot ? '☆ ' : ''}${text(host.name)}`, LAYOUT.labelChars)
      )
    );
    if (badges.length)
      group.appendChild(svgEl('text', { 'text-anchor': 'middle', y: 15, class: 'ne-node-badge' }, badges.join(' · ')));
    group.appendChild(svgEl('title', {}, text(host.name)));
    onActivate(group, () => context.select.host(host));
    svg.appendChild(group);
    return group;
  }
  const MODE_LABELS = [
    ['physical', 'Layer 2'],
    ['stp', 'Spanning Tree'],
    ['vlan', 'VLAN']
  ];
  /**
   * The topology, shared by the Topology widget and the Explorer page. Switches, links and link ends are all
   * selectable; the selection is kept in `state.selection` and shown in `options.details` (or the widget's own
   * drawer). Selecting a switch or interface also broadcasts its host or interface item to linked widgets.
   * `options.linked === false` (no dashboard) hides linked-widget actions; `options.onChange(state)` hears every
   * view or selection change. Returns { selectHost } for callers such as the findings table.
   */
  function renderTopology(root, payload, broadcast, state = {}, options = {}) {
    observations(root, payload, payload.scope?.hostid);
    const hosts = asRows(payload.hosts),
      edges = asRows(payload.edges);
    if (!hosts.length) {
      notice(root, 'No permitted hosts with network observations are available.');
      return { selectHost() {} };
    }
    const changed = () => options.onChange?.(state);
    const toolbar = el('div', undefined, 'ne-toolbar'),
      search = el('input');
    search.type = 'search';
    search.placeholder = 'Find visible host';
    search.setAttribute('aria-label', 'Find visible host');
    toolbar.appendChild(search);
    let collapse = state.collapse_lag ?? true;
    const lagToggle = button(collapse ? 'Expand LAG member links' : 'Collapse LAG member links', () => {
      collapse = !collapse;
      state.collapse_lag = collapse;
      lagToggle.textContent = collapse ? 'Expand LAG member links' : 'Collapse LAG member links';
      draw();
    });
    toolbar.appendChild(lagToggle);
    const mode = el('select'),
      vlanPick = el('select'),
      tracePick = el('select');
    mode.setAttribute('aria-label', 'View');
    vlanPick.setAttribute('aria-label', 'VLAN');
    tracePick.setAttribute('aria-label', 'Trace VLAN from');
    for (const [value, label] of MODE_LABELS) {
      const option = el('option', label);
      option.value = value;
      mode.appendChild(option);
    }
    const vlanNames = new Map();
    for (const h of hosts)
      for (const v of asRows(h.vlans))
        if (!vlanNames.has(Number(v.vlan_id)) || v.name) vlanNames.set(Number(v.vlan_id), v.name);
    for (const v of [...vlanNames.keys()].sort((a, b) => a - b)) {
      const option = el('option', vlanNames.get(v) ? `${v} · ${vlanNames.get(v)}` : String(v));
      option.value = String(v);
      vlanPick.appendChild(option);
    }
    const none = el('option', 'No trace');
    none.value = '';
    tracePick.appendChild(none);
    for (const h of hosts.filter(h => asRows(h.vlans).length)) {
      const option = el('option', `Trace from ${text(h.name)}`);
      option.value = id(h.hostid);
      tracePick.appendChild(option);
    }
    mode.value = state.mode ?? payload.scope?.mode ?? 'physical';
    if (!mode.value) mode.value = 'physical';
    if (state.vlan && vlanNames.has(Number(state.vlan))) vlanPick.value = state.vlan;
    if (state.trace) tracePick.value = state.trace;
    toolbar.append(mode, vlanPick, tracePick);
    root.appendChild(toolbar);
    const overlayNote = el('div');
    root.appendChild(overlayNote);
    const controls = el('div', undefined, 'ne-toolbar ne-view-controls'),
      graph = el('div', undefined, 'ne-graph'),
      legend = el('ul', undefined, 'ne-topology-legend');
    graph.tabIndex = 0;
    graph.setAttribute('role', 'region');
    graph.setAttribute(
      'aria-label',
      'Topology canvas. Plus and minus zoom, arrow keys pan, F fits the topology, 0 resets the view. Drag the background to pan; Ctrl and the mouse wheel zoom.'
    );
    legend.setAttribute('aria-label', 'Topology legend');
    let details = options.details;
    if (!details) {
      details = el('section', undefined, 'ne-drawer');
      details.setAttribute('aria-label', 'Topology selection details');
      details.setAttribute('aria-live', 'polite');
    }
    root.append(controls, graph, legend);
    if (!options.details) root.appendChild(details);
    const cidrs = payload.scope?.management_cidr || asRows(payload.scope?.management_cidrs).join(', ');
    if (cidrs)
      notice(
        root,
        `Management subnet ${cidrs} is an annotation; permitted connected neighbours outside it remain visible.`
      );
    const stp = stpRoots(payload),
      parents = stpParents(edges);
    const views = (state.views ??= {}),
      layouts = (state.layouts ??= {});
    /**
     * The placement for one view: reused while the visible switches, their internal links and (for Spanning
     * Tree) the root and root-port evidence are unchanged; otherwise laid out again with the old positions as an
     * ordering hint, and the view refitted. Selection, search, VLAN and findings are not part of the signature.
     */
    function placementFor(key) {
      const anchors = key === 'stp' ? stp.roots : stp.current,
        visible = new Set(hosts.map(h => id(h.hostid)));
      const pairs = edges
        .filter(e => visible.has(id(e.source)) && visible.has(id(e.target)))
        .map(e => [id(e.source), id(e.target)].sort().join('-'));
      const signature = JSON.stringify([
        key,
        [...visible].sort(),
        [...new Set(pairs)].sort(),
        [...anchors].sort(),
        key === 'stp' ? [...parents].sort() : []
      ]);
      const kept = layouts[key];
      if (kept?.signature === signature) return kept.placement;
      const placement = layoutTopology(hosts, edges, {
        anchors,
        parents: key === 'stp' ? parents : null,
        previous: new Map(asRows(kept?.placement.nodes).map(n => [id(n.hostid), n]))
      });
      if (kept) delete views[key];
      layouts[key] = { signature, placement };
      return placement;
    }
    let viewport = null;
    let nodes = [],
      lines = [];
    const matches = host => !search.value || text(host.name).toLowerCase().includes(search.value.toLowerCase());
    const isEnd = (member, hostid, uid) =>
      (id(member.source) === hostid && id(member.source_uid) === uid) ||
      (id(member.target) === hostid && id(member.target_uid) === uid);
    /** Reflects state.selection on the drawing: the selected switch, link, or interface's switch and links. */
    function mark() {
      const sel = state.selection;
      for (const [host, node] of nodes) {
        const on = !!sel && ['host', 'interface'].includes(sel.kind) && id(host.hostid) === sel.hostid;
        node.classList.toggle('ne-node-selected', on);
        node.setAttribute('aria-pressed', on ? 'true' : 'false');
      }
      for (const [edge, line] of lines) {
        const on =
          !!sel &&
          ((sel.kind === 'edge' && edge.members.some(m => asRows(sel.edge_ids).includes(id(m.id)))) ||
            (sel.kind === 'interface' && edge.members.some(m => isEnd(m, sel.hostid, sel.uid))));
        line.classList.toggle('ne-edge-selected', on);
        line.setAttribute('aria-pressed', on ? 'true' : 'false');
      }
      // End markers tell "this link" (a square at each end) from "this interface" (a ring at its own end only).
      for (const marker of graph.querySelectorAll('.ne-endpoint-selected, .ne-link-end-selected')) marker.remove();
      const svg = graph.querySelector('svg.ne-topology');
      if (!svg || !sel || !['edge', 'interface'].includes(sel.kind)) return;
      const endOf = (line, atSource) => {
        const [x1, y1, x2, y2] = ['x1', 'y1', 'x2', 'y2'].map(k => Number(line.getAttribute(k))),
          near = atSource ? { x: x1, y: y1 } : { x: x2, y: y2 },
          far = atSource ? { x: x2, y: y2 } : { x: x1, y: y1 },
          len = Math.hypot(far.x - near.x, far.y - near.y) || 1;
        return { x: near.x + ((far.x - near.x) / len) * 9, y: near.y + ((far.y - near.y) / len) * 9 };
      };
      for (const [edge, line] of lines) {
        if (line.getAttribute('aria-pressed') !== 'true') continue;
        if (sel.kind === 'edge') {
          for (const atSource of line.dataset.external === 'true' ? [true] : [true, false]) {
            const p = endOf(line, atSource);
            svg.appendChild(svgEl('rect', { x: p.x - 5, y: p.y - 5, width: 10, height: 10, class: 'ne-link-end-selected' }));
          }
          continue;
        }
        // x1/y1 is the source end, or the only visible end of a link to an external peer.
        const p = endOf(line, id(edge.source) === sel.hostid || line.dataset.external === 'true');
        const ring = svgEl('circle', { cx: p.x, cy: p.y, r: 7, class: 'ne-endpoint-selected' });
        ring.appendChild(svgEl('title', {}, `Selected interface ${interfaceName(payload, sel.hostid, sel.uid)}`));
        svg.appendChild(ring);
      }
    }
    const ctx = { stp, linked: options.linked, showHost: true, selectInterface: port => select.iface(port) };
    const select = {
      host(host, quiet) {
        state.selection = { kind: 'host', hostid: id(host.hostid) };
        mark();
        showHost(details, payload, host, ctx);
        if (!quiet) {
          broadcast(host.hostid);
          changed();
        }
      },
      edge(edge, quiet) {
        state.selection = { kind: 'edge', edge_ids: edge.members.map(m => id(m.id)) };
        mark();
        showEdgeDetails(details, payload, edge, ctx);
        if (!quiet) changed();
      },
      iface(port, quiet) {
        state.selection = { kind: 'interface', hostid: id(port.hostid), uid: id(port.uid) };
        mark();
        showDetail(details, payload, port, broadcast, ctx);
        if (!quiet) {
          if (port.itemid) broadcast(port.hostid, port.itemid);
          changed();
        }
      }
    };
    function draw() {
      graph.replaceChildren();
      overlayNote.replaceChildren();
      state.mode = mode.value;
      state.vlan = vlanPick.value;
      state.trace = tracePick.value;
      vlanPick.hidden = tracePick.hidden = mode.value !== 'vlan';
      const vlan = Number(vlanPick.value),
        trace = mode.value === 'vlan' && tracePick.value ? vlanTrace(payload, tracePick.value, vlan) : null;
      if (mode.value === 'vlan') vlanNotes(overlayNote, payload, vlan, vlanNames.size > 0, trace, tracePick.value);
      stpNotes(overlayNote, stp, mode.value);
      // Layer 2 and VLAN share one placement; Spanning Tree has its own root-port hierarchy. Each is kept while
      // its topology is unchanged, so selection, VLAN, trace, LAG and refresh never move a switch.
      const layoutKey = mode.value === 'stp' ? 'stp' : 'physical';
      const placement = placementFor(layoutKey);
      const arranged = placement.nodes,
        byId = new Map(arranged.map(h => [id(h.hostid), h]));
      const componentCount = placement.components.length;
      const svg = svgEl('svg', {
        role: 'group',
        class: 'ne-topology',
        'aria-label': `${MODE_LABELS.find(([value]) => value === mode.value)?.[1] ?? 'Layer 2'} topology, ${arranged.length} permitted devices, ${componentCount} ${componentCount === 1 ? 'group' : 'groups'} of connected devices`
      });
      const context = { payload, svg, byId, mode: mode.value, vlan, trace, stp, select };
      const drawn = groupedEdges(edges, collapse),
        parallel = new Map();
      for (const edge of drawn) {
        const key = [id(edge.source), id(edge.target)].sort().join('|');
        parallel.set(key, [...(parallel.get(key) ?? []), edge]);
      }
      lines = [];
      for (const edge of drawn) {
        const siblings = parallel.get([id(edge.source), id(edge.target)].sort().join('|'));
        const line = drawEdge(context, edge, siblings);
        if (line) lines.push([edge, line]);
      }
      const externalCount = lines.filter(([, line]) => line.dataset.external === 'true').length;
      nodes = arranged.map(host => [host, drawNode(context, host, matches(host))]);
      drawUnresolvedLabels(svg, arranged);
      graph.appendChild(svg);
      viewport = topologyViewport(graph, svg, arranged, views, layoutKey, context.stubPoints);
      viewport.apply();
      drawLegend(legend, context, arranged, lines);
      mark();
      if (hosts.length > arranged.length)
        notice(graph, `The visible topology is capped at ${LAYOUT.maxNodes} nodes. Narrow the scope.`, 'warning');
      if (externalCount)
        notice(
          graph,
          `${externalCount} unresolved endpoint observations. External, restricted and ambiguous peers use undisclosed placeholders.`
        );
    }
    for (const [label, action] of [
      ['Zoom in', () => viewport?.zoom(1 / 1.25)],
      ['Zoom out', () => viewport?.zoom(1.25)],
      ['Fit topology', () => viewport?.fit()],
      ['Reset view', () => viewport?.reset()]
    ])
      controls.appendChild(button(label, action));
    graph.addEventListener('keydown', event => {
      if (event.target !== graph || !viewport) return;
      const step = { ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1] }[event.key];
      if (step) viewport.pan(step[0] * 0.1, step[1] * 0.1);
      else if (event.key === '+' || event.key === '=') viewport.zoom(1 / 1.25);
      else if (event.key === '-' || event.key === '_') viewport.zoom(1.25);
      else if (event.key === 'f' || event.key === 'F') viewport.fit();
      else if (event.key === '0') viewport.reset();
      else return;
      event.preventDefault();
    });
    // Searching only dims non-matching nodes, so it never rebuilds the drawing.
    search.addEventListener('input', () => {
      for (const [host, node] of nodes) node.classList.toggle('ne-muted', !matches(host));
    });
    for (const control of [mode, vlanPick, tracePick])
      control.addEventListener('change', () => {
        draw();
        changed();
      });
    draw();
    // A kept selection (widget refresh, or the Explorer's URL) is shown again without broadcasting.
    const kept = state.selection;
    if (kept?.kind === 'host' && findHost(payload, kept.hostid)) select.host(findHost(payload, kept.hostid), true);
    else if (kept?.kind === 'edge') {
      const edge = groupedEdges(edges, collapse).find(e =>
        e.members.some(m => asRows(kept.edge_ids).includes(id(m.id)))
      );
      if (edge) select.edge(edge, true);
    } else if (kept?.kind === 'interface') {
      const port = findInterface(payload, kept.hostid, kept.uid);
      if (port) select.iface(port, true);
      else notice(details, 'The selected interface is not in the current scope or observation.', 'warning');
    }
    const tabular = el('details');
    tabular.appendChild(el('summary', `Accessible link table (${edges.length})`));
    table(
      tabular,
      [
        { label: 'Device', value: e => hostName(payload, e.source) },
        { label: 'Local port', value: e => interfaceName(payload, e.source, e.source_uid) },
        { label: 'Peer', value: e => (e.target ? hostName(payload, e.target) : 'Undisclosed peer') },
        { label: 'Peer port', value: e => (e.target ? interfaceName(payload, e.target, e.target_uid) : null) },
        { label: 'Resolution', value: e => e.status },
        { label: 'Confidence', value: e => e.confidence },
        { label: 'Freshness', value: e => e.freshness }
      ],
      edges,
      'Observed physical topology'
    );
    root.appendChild(tabular);
    capabilities(root, payload, payload.scope?.hostid);
    return {
      selectHost(hostid) {
        const host = findHost(payload, hostid);
        if (host) select.host(host);
      }
    };
  }
  function section(root, title, className) {
    const node = el('section', undefined, `ne-explorer-section ${className}`);
    node.appendChild(el('h3', title));
    root.appendChild(node);
    return node;
  }
  /**
   * The Explorer page: the shared topology, one selection panel for switches, links and interfaces, and the
   * findings and collection quality of the same scope. There is no dashboard, so nothing is broadcast.
   */
  function renderExplorer(root, payload, broadcast, state = {}) {
    const graph = section(root, 'Network topology', 'ne-explorer-graph'),
      selection = section(root, 'Selection', 'ne-explorer-selection'),
      lower = el('div', undefined, 'ne-explorer-columns');
    const details = el('div', undefined, 'ne-drawer ne-selection');
    details.setAttribute('aria-label', 'Selection details');
    details.setAttribute('aria-live', 'polite');
    notice(details, 'Select a switch, a link or a link end in the topology to see its details here.');
    selection.appendChild(details);
    const topology = renderTopology(graph, payload, () => {}, state, {
      details,
      linked: false,
      onChange: state.onChange
    });
    root.appendChild(lower);
    const findings = section(lower, 'Findings', 'ne-explorer-findings'),
      quality = section(lower, 'Collection quality', 'ne-explorer-quality');
    notice(
      findings,
      'Findings and collection quality cover the same scope as the topology. The view selector changes only the drawing.'
    );
    renderFindings(findings, payload, hostid => {
      topology.selectHost(hostid);
      details.scrollIntoView?.({ block: 'nearest' });
    });
    renderQuality(quality, payload);
  }
  const VIEW_MODES = { layer2: 'physical', stp: 'stp', vlan: 'vlan' };
  /**
   * Starts the Explorer page from the server's request, and keeps the view, VLAN and selected interface in the
   * address (for bookmarks and sharing; the server re-checks permissions on every load) and in the scope form.
   */
  function mountExplorer(root, payload, request = {}) {
    const state = {
      mode: VIEW_MODES[request.view] ?? 'physical',
      vlan: request.vlan ? String(request.vlan) : undefined,
      selection:
        request.interface_uid && request.interface_hostid
          ? { kind: 'interface', hostid: id(request.interface_hostid), uid: id(request.interface_uid) }
          : undefined
    };
    state.onChange = () => {
      const sel = state.selection?.kind === 'interface' ? state.selection : null;
      const values = {
        view: Object.keys(VIEW_MODES).find(key => VIEW_MODES[key] === state.mode) ?? 'layer2',
        vlan: state.mode === 'vlan' ? id(state.vlan) : '',
        interface_hostid: sel ? sel.hostid : '',
        interface_uid: sel ? sel.uid : ''
      };
      for (const input of document.querySelectorAll('form.ne-scope input[data-ne-state]')) {
        const value = values[input.dataset.neState] ?? '';
        input.value = value;
        input.disabled = value === '';
      }
      try {
        const url = new URL(global.location.href);
        for (const [key, value] of Object.entries(values)) {
          if (value) url.searchParams.set(key, value);
          else url.searchParams.delete(key);
        }
        global.history.replaceState(global.history.state, '', url.toString());
      } catch (_) {
        // A page without a usable address (a test fixture) still works; only bookmarking is lost.
      }
    };
    render(root, payload, 'explorer', () => {}, state);
    state.onChange();
    return state;
  }
  function renderDetail(root, payload, broadcast) {
    const hostid = id(payload.scope?.hostid),
      uid = payload.scope?.interface_uid,
      ports = asRows(payload.interfaces).filter(p => id(p.hostid) === hostid);
    observations(root, payload, hostid);
    if (!ports.length) {
      notice(root, 'No permitted interface observations are available.');
      return;
    }
    const selected =
      ports.find(p => id(p.uid) === id(uid)) ??
      ports.find(p => id(p.itemid) === id(payload.scope?.itemid) && id(p.itemid));
    const select = el('select');
    select.setAttribute('aria-label', 'Interface');
    const blank = el('option', 'Select an interface');
    blank.value = '';
    select.appendChild(blank);
    for (const p of ports) {
      const option = el('option', text(p.name));
      option.value = id(p.uid);
      select.appendChild(option);
    }
    if (selected) select.value = id(selected.uid);
    root.appendChild(select);
    const details = el('section', undefined, 'ne-drawer');
    details.setAttribute('aria-live', 'polite');
    root.appendChild(details);
    select.addEventListener('change', () => {
      const p = ports.find(p => id(p.uid) === select.value);
      if (p) {
        showDetail(details, payload, p, broadcast);
        broadcast(p.hostid, p.itemid);
      } else details.replaceChildren();
    });
    if (selected) showDetail(details, payload, selected, broadcast);
    else
      notice(
        details,
        uid
          ? 'The selected interface is unavailable in the current observation.'
          : 'Choose an interface here, or link this widget to the Port panel item broadcast.'
      );
  }
  function renderQuality(root, payload) {
    const rows = asRows(payload.quality);
    if (!rows.length) {
      notice(root, 'No dataset quality evidence is available.');
      return;
    }
    notice(
      root,
      'Collection outcome, freshness and capability are independent. An empty complete observation differs from failed collection.'
    );
    table(
      root,
      [
        { label: 'Host', value: q => hostName(payload, q.hostid) },
        { label: 'Dataset', value: q => q.dataset },
        { label: 'Outcome', value: q => q.status },
        { label: 'Freshness', value: q => q.freshness },
        { label: 'Capability', value: q => q.capability?.state ?? q.capability },
        { label: 'Observed', value: q => q.observed_at },
        { label: 'Attempted', value: q => q.attempted_at },
        {
          label: 'Completeness',
          value: q => (q.complete === true ? 'Complete' : q.complete === false ? 'Partial' : 'Unknown')
        },
        {
          label: 'Diagnostics',
          value: q =>
            [
              ...asRows(q.errors).map(e => (typeof e === 'string' ? e : (e.code ?? e.message))),
              ...asRows(q.warnings).map(code => `skipped rows: ${code}`)
            ].join('; ') ||
            q.reason ||
            (q.status === 'ok' ? 'None reported' : 'Unknown')
        }
      ],
      rows,
      'Dataset quality and coverage'
    );
  }
  function csvCell(value) {
    const raw = id(value);
    const safe = /^(?:\s*[=+\-@]|[\t\r\n])/.test(raw) ? "'" + raw : raw;
    return '"' + safe.replaceAll('"', '""') + '"';
  }
  function findingsCsv(rows, payload) {
    const header = ['Host', 'Severity', 'Rule', 'Finding', 'Interface', 'Evidence'];
    return (
      '\ufeff' +
      [
        header.map(csvCell).join(','),
        ...rows.map(f =>
          [
            hostName(payload, f.hostid),
            f.severity,
            f.rule,
            f.title,
            interfaceName(payload, f.hostid, f.interface_uid),
            f.reason ?? f.description
          ]
            .map(csvCell)
            .join(',')
        )
      ].join('\r\n')
    );
  }
  function download(filename, content, type) {
    const blob = new Blob([content], { type }),
      url = URL.createObjectURL(blob),
      link = el('a');
    link.href = url;
    link.download = filename;
    link.hidden = true;
    // Firefox and Safari need the link in the document, and the URL alive until the download has started.
    document.body.appendChild(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  function renderFindings(root, payload, broadcast) {
    const rows = asRows(payload.findings),
      toolbar = el('div', undefined, 'ne-toolbar'),
      search = el('input');
    search.type = 'search';
    search.placeholder = 'Filter findings';
    search.setAttribute('aria-label', 'Filter findings');
    toolbar.appendChild(search);
    root.appendChild(toolbar);
    const results = el('div');
    root.appendChild(results);
    let visible = rows;
    function draw() {
      visible = rows.filter(row =>
        [row.title, row.rule, row.reason ?? row.description, hostName(payload, row.hostid)]
          .join(' ')
          .toLowerCase()
          .includes(search.value.toLowerCase())
      );
      results.replaceChildren();
      if (!visible.length) {
        notice(
          results,
          rows.length
            ? 'No findings match the filter.'
            : 'No findings were produced for the available observations. Review dataset quality for missing coverage.'
        );
        return;
      }
      table(
        results,
        [
          {
            label: 'Host',
            value: f => button(text(hostName(payload, f.hostid)), () => broadcast(f.hostid), 'ne-link-button')
          },
          { label: 'Severity', value: f => f.severity },
          { label: 'Rule', value: f => f.rule },
          { label: 'Finding', value: f => f.title },
          { label: 'Interface', value: f => interfaceName(payload, f.hostid, f.interface_uid) },
          { label: 'Evidence / limitation', value: f => f.reason ?? f.description }
        ],
        visible,
        'Current-state findings'
      );
    }
    toolbar.appendChild(
      button('Export filtered CSV', () =>
        download('network-explorer-findings.csv', findingsCsv(visible, payload), 'text/csv;charset=utf-8')
      )
    );
    toolbar.appendChild(
      button('Export filtered JSON', () =>
        download(
          'network-explorer-findings.json',
          JSON.stringify({ generated_at: new Date().toISOString(), scope: payload.scope, findings: visible }, null, 2),
          'application/json'
        )
      )
    );
    search.addEventListener('input', draw);
    draw();
  }
  function render(root, payload, kind, broadcast = () => {}, state = {}) {
    root.replaceChildren();
    if (payload.message) {
      notice(root, payload.message, 'warning');
      if (!asRows(payload.hosts).length) return;
    }
    if (payload.truncated || payload.scope?.truncated)
      notice(root, 'Observation scope was truncated. Narrow the host selection to see complete coverage.', 'warning');
    const handlers = {
      ports: renderPorts,
      topology: renderTopology,
      detail: renderDetail,
      quality: renderQuality,
      findings: renderFindings,
      explorer: renderExplorer
    };
    if (handlers[kind]) handlers[kind](root, payload, broadcast, state);
  }
  const runtime = {
    render,
    mountExplorer,
    stpRoots,
    speed,
    portState,
    isPhysical,
    vlanSet,
    vlanRole,
    edgeVlanState,
    vlanTrace,
    stpClass,
    groupPorts,
    graphLayout,
    layoutTopology,
    stpParents,
    groupedEdges,
    safeNavigation,
    fragmentContext,
    peerUrl,
    findingsCsv
  };
  global.NEWidgetRuntime = runtime;
  if (typeof module !== 'undefined' && module.exports) module.exports = runtime;
})(typeof window !== 'undefined' ? window : globalThis);
