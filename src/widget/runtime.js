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
    externalOffset: { x: 85, y: 52 },
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
  function graphLayout(hosts, edges, positions = new Map()) {
    const ordered = hosts
      .slice()
      .sort((a, b) => natural(a.name, b.name) || natural(a.hostid, b.hostid))
      .slice(0, LAYOUT.maxNodes);
    const columns = Math.max(2, Math.ceil(Math.sqrt(ordered.length || 1)));
    const adjacency = new Map(ordered.map(h => [id(h.hostid), new Set()]));
    for (const edge of edges) {
      if (adjacency.has(id(edge.source)) && adjacency.has(id(edge.target))) {
        adjacency.get(id(edge.source)).add(id(edge.target));
        adjacency.get(id(edge.target)).add(id(edge.source));
      }
    }
    const pending = new Set(ordered.map(h => id(h.hostid))),
      sequence = [];
    while (pending.size) {
      const queue = [pending.values().next().value];
      pending.delete(queue[0]);
      for (let index = 0; index < queue.length; index++) {
        const current = queue[index];
        sequence.push(current);
        for (const neighbour of [...adjacency.get(current)].sort(natural)) {
          if (pending.delete(neighbour)) queue.push(neighbour);
        }
      }
    }
    const byId = new Map(ordered.map(h => [id(h.hostid), h]));
    const occupied = new Set(
      sequence
        .filter(hostid => positions.has(hostid))
        .map(hostid => `${positions.get(hostid).x},${positions.get(hostid).y}`)
    );
    let cursor = 0;
    return sequence.map(hostid => {
      let position = positions.get(hostid);
      if (!position) {
        do {
          position = {
            x: LAYOUT.originX + (cursor % columns) * LAYOUT.columnGap,
            y: LAYOUT.originY + Math.floor(cursor / columns) * LAYOUT.rowGap
          };
          cursor++;
        } while (occupied.has(`${position.x},${position.y}`));
        occupied.add(`${position.x},${position.y}`);
      }
      return { ...byId.get(hostid), ...position };
    });
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
  function showDetail(root, payload, port, broadcast) {
    root.replaceChildren();
    root.appendChild(el('h4', `${text(port.name)} · ${stateLabel(port)}`));
    const list = el('dl', undefined, 'ne-details');
    const details = {
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
    if (port.itemid)
      root.appendChild(button('Select interface in linked widgets', () => broadcast(port.hostid, port.itemid)));
    const peers = peersFor(payload, port);
    root.appendChild(el('h4', 'LLDP peers'));
    if (!peers.length) notice(root, 'No permitted LLDP peer is resolved for this interface.');
    for (const { peer, edge } of peers) {
      const row = el('p');
      row.append(
        peerLink(payload, peer, port.name, broadcast),
        document.createTextNode(
          ` · port ${text(peer.name ?? peer.uid)} · ${text(edge.confidence ?? edge.status)} · ${text(edge.freshness)}`
        )
      );
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
  function stpNotes(root, hosts, rootVisible) {
    const seen = [
      ...new Set(
        hosts.flatMap(h =>
          asRows(h.stp)
            .filter(b => Number(b.instance) === 0)
            .map(b => b.root_bridge_id)
        )
      )
    ].filter(Boolean);
    notice(
      root,
      rootVisible
        ? 'Root bridge marked ★. Root-port links are highlighted; ⊘ marks a blocking port end.'
        : seen.length
          ? `The spanning-tree root (bridge ${seen.join(', ')}) is not a visible switch. Root-port links are highlighted; ⊘ marks a blocking port end.`
          : 'No spanning-tree data has been collected for the visible switches.'
    );
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
  function showEdgeDetails(details, payload, edge) {
    details.replaceChildren();
    const aggregation = lagModeLabel(payload, edge);
    details.appendChild(
      el(
        'h4',
        `${edge.members.length > 1 ? 'LAG member links' : 'Observed physical link'}${aggregation ? ` (${aggregation})` : ''} · ${text(edge.status)}; confidence ${text(edge.confidence)}`
      )
    );
    table(
      details,
      [
        { label: 'Local host', value: e => hostName(payload, e.source) },
        { label: 'Local interface', value: e => e.source_uid },
        { label: 'Peer', value: e => hostName(payload, e.target) || 'Undisclosed' },
        { label: 'Peer interface', value: e => e.target_uid },
        { label: 'VLANs on both ends', value: e => (e.vlan ? e.vlan.common || 'None' : 'Unknown') },
        {
          label: 'Native VLAN',
          value: e => (e.vlan ? `${text(e.vlan.source_pvid)} / ${text(e.vlan.target_pvid)}` : 'Unknown')
        },
        {
          label: 'STP state',
          value: e => (e.stp ? `${text(e.stp.source?.state)} / ${text(e.stp.target?.state)}` : 'Unknown')
        },
        { label: 'Freshness', value: e => e.freshness }
      ],
      edge.members,
      'Individual observed members'
    );
  }
  /** Draws one (possibly grouped) link; returns 'external' when only one end is a visible switch. */
  function drawEdge(context, edge, siblings) {
    const { payload, svg, byId } = context;
    const a = byId.get(id(edge.source)),
      b = byId.get(id(edge.target));
    if (!a && !b) return 'hidden';
    let start = a ?? b,
      end = a && b ? b : { x: start.x + LAYOUT.externalOffset.x, y: start.y + LAYOUT.externalOffset.y };
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
      'aria-label': `${label}; ${edge.members.length} members; ${text(edge.status)}; ${text(edge.freshness)}`
    });
    onActivate(line, () => showEdgeDetails(context.details, payload, edge));
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
    return a && b ? 'drawn' : 'external';
  }
  /** Marks each blocking port end just outside its switch box, on the link towards the peer. */
  function drawBlockMarks(svg, byId, edge, a, b) {
    for (const member of edge.members)
      for (const side of ['source', 'target']) {
        if (!['blocking', 'discarding'].includes(member.stp?.[side]?.state)) continue;
        const near = byId.get(id(member[side])),
          far = near === a ? b : a;
        if (!near) continue;
        const dx = far.x - near.x,
          dy = far.y - near.y,
          len = Math.hypot(dx, dy) || 1,
          halfWidth = LAYOUT.nodeWidth / 2,
          halfHeight = LAYOUT.nodeHeight / 2,
          t = Math.min(dx ? halfWidth / Math.abs(dx) : Infinity, dy ? halfHeight / Math.abs(dy) : Infinity, 1);
        svg.appendChild(
          svgEl(
            'text',
            {
              x: near.x + dx * t + (dx / len) * LAYOUT.blockMarkGap,
              y: near.y + dy * t + (dy / len) * LAYOUT.blockMarkGap + 4,
              class: 'ne-svg-label ne-stp-block-mark'
            },
            '⊘'
          )
        );
      }
  }
  function drawNode(context, host, matching) {
    const { payload, svg, details, broadcast } = context;
    const carries = context.mode === 'vlan' && asRows(host.vlans).some(v => Number(v.vlan_id) === context.vlan),
      isRoot = context.mode === 'stp' && context.roots.has(id(host.hostid)),
      unreachable = host.snmp_available === false;
    const classes = ['ne-node'];
    const notes = [];
    if (!matching) classes.push('ne-muted');
    if (host.out_of_subnet) (classes.push('ne-node-warning'), notes.push('outside management subnet'));
    if (carries) (classes.push('ne-node-vlan'), notes.push(`has VLAN ${context.vlan}`));
    if (isRoot) (classes.push('ne-node-root'), notes.push('spanning-tree root'));
    if (unreachable) (classes.push('ne-node-unreachable'), notes.push('SNMP unreachable'));
    const group = svgEl('g', {
      transform: `translate(${host.x},${host.y})`,
      tabindex: 0,
      role: 'button',
      'aria-label': [text(host.name), ...notes].join('; '),
      class: classes.join(' ')
    });
    group.appendChild(
      svgEl('rect', {
        x: -LAYOUT.nodeWidth / 2,
        y: -LAYOUT.nodeHeight / 2,
        width: LAYOUT.nodeWidth,
        height: LAYOUT.nodeHeight,
        rx: 6
      })
    );
    group.appendChild(
      svgEl(
        'text',
        { 'text-anchor': 'middle', y: 4 },
        `${isRoot ? '★ ' : ''}${text(host.name)}`.slice(0, LAYOUT.labelChars)
      )
    );
    group.appendChild(svgEl('title', {}, text(host.name)));
    onActivate(group, () => {
      details.replaceChildren();
      details.appendChild(el('h4', text(host.name)));
      details.appendChild(peerLink(payload, { hostid: host.hostid }, 'Topology', broadcast));
      if (host.out_of_subnet)
        notice(details, 'Advertised management addressing is outside the selected subnet.', 'warning');
      if (host.addressing?.addresses)
        notice(details, host.addressing.addresses.map(a => `${a.address}: ${a.state}`).join('; '));
      broadcast(host.hostid);
    });
    svg.appendChild(group);
    return group;
  }
  function renderTopology(root, payload, broadcast, state = {}) {
    observations(root, payload, payload.scope?.hostid);
    const hosts = asRows(payload.hosts),
      edges = asRows(payload.edges);
    if (!hosts.length) {
      notice(root, 'No permitted hosts with network observations are available.');
      return;
    }
    const toolbar = el('div', undefined, 'ne-toolbar'),
      search = el('input');
    search.type = 'search';
    search.placeholder = 'Find visible host';
    search.setAttribute('aria-label', 'Find visible host');
    toolbar.appendChild(search);
    let collapse = state.collapse_lag ?? true;
    const lagToggle = button('Expand LAG member links', () => {
      collapse = !collapse;
      state.collapse_lag = collapse;
      lagToggle.textContent = collapse ? 'Expand LAG member links' : 'Collapse LAG member links';
      draw();
    });
    toolbar.appendChild(lagToggle);
    const mode = el('select'),
      vlanPick = el('select'),
      tracePick = el('select');
    mode.setAttribute('aria-label', 'Overlay');
    vlanPick.setAttribute('aria-label', 'VLAN');
    tracePick.setAttribute('aria-label', 'Trace VLAN from');
    for (const [value, label] of [
      ['physical', 'Physical'],
      ['vlan', 'VLAN'],
      ['stp', 'STP']
    ]) {
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
    if (state.vlan) vlanPick.value = state.vlan;
    if (state.trace) tracePick.value = state.trace;
    toolbar.append(mode, vlanPick, tracePick);
    root.appendChild(toolbar);
    const overlayNote = el('div');
    root.appendChild(overlayNote);
    const graph = el('div', undefined, 'ne-graph'),
      details = el('section', undefined, 'ne-drawer');
    details.setAttribute('aria-label', 'Topology selection details');
    root.append(graph, details);
    notice(
      root,
      'Solid: confirmed. Dashed: one-sided, ambiguous, external or stale. LAG grouping retains each member link.'
    );
    if (payload.scope?.management_cidr)
      notice(
        root,
        `Management subnet ${payload.scope.management_cidr} is an annotation; permitted connected neighbours outside it remain visible.`
      );
    const positions = (state.positions ??= new Map());
    let nodes = [];
    const matches = host => !search.value || text(host.name).toLowerCase().includes(search.value.toLowerCase());
    function draw() {
      graph.replaceChildren();
      overlayNote.replaceChildren();
      state.mode = mode.value;
      state.vlan = vlanPick.value;
      state.trace = tracePick.value;
      vlanPick.hidden = tracePick.hidden = mode.value !== 'vlan';
      const vlan = Number(vlanPick.value),
        trace = mode.value === 'vlan' && tracePick.value ? vlanTrace(payload, tracePick.value, vlan) : null;
      const roots = new Set();
      for (const h of hosts)
        if (asRows(h.stp).some(b => Number(b.instance) === 0 && b.is_root)) roots.add(id(h.hostid));
      if (mode.value === 'vlan') vlanNotes(overlayNote, payload, vlan, vlanNames.size > 0, trace, tracePick.value);
      if (mode.value === 'stp') stpNotes(overlayNote, hosts, roots.size > 0);
      const arranged = graphLayout(hosts, edges, positions),
        byId = new Map(arranged.map(h => [id(h.hostid), h]));
      for (const h of arranged) positions.set(id(h.hostid), { x: h.x, y: h.y });
      const width = Math.max(500, ...arranged.map(h => h.x + LAYOUT.nodeWidth / 2 + 30)),
        height = Math.max(180, ...arranged.map(h => h.y + LAYOUT.nodeHeight / 2 + 50));
      const svg = svgEl('svg', {
        viewBox: `0 0 ${width} ${height}`,
        role: 'img',
        'aria-label': `Physical topology, ${arranged.length} permitted devices`
      });
      svg.style.maxWidth = `${width * 1.25}px`; // a small graph keeps its proportions instead of filling the widget
      const context = { payload, svg, byId, mode: mode.value, vlan, trace, details, broadcast, roots };
      const drawn = groupedEdges(edges, collapse),
        parallel = new Map();
      for (const edge of drawn) {
        const key = [id(edge.source), id(edge.target)].sort().join('|');
        parallel.set(key, [...(parallel.get(key) ?? []), edge]);
      }
      let externalCount = 0;
      for (const edge of drawn) {
        const siblings = parallel.get([id(edge.source), id(edge.target)].sort().join('|'));
        if (drawEdge(context, edge, siblings) === 'external') externalCount++;
      }
      nodes = arranged.map(host => [host, drawNode(context, host, matches(host))]);
      graph.appendChild(svg);
      if (hosts.length > arranged.length)
        notice(graph, `The visible topology is capped at ${LAYOUT.maxNodes} nodes. Narrow the scope.`, 'warning');
      if (externalCount)
        notice(
          graph,
          `${externalCount} unresolved endpoint observations. External, restricted and ambiguous peers use undisclosed placeholders.`
        );
    }
    // Searching only dims non-matching nodes, so it never rebuilds the drawing.
    search.addEventListener('input', () => {
      for (const [host, node] of nodes) node.classList.toggle('ne-muted', !matches(host));
    });
    for (const control of [mode, vlanPick, tracePick]) control.addEventListener('change', draw);
    draw();
    const tabular = el('details');
    tabular.appendChild(el('summary', `Accessible link table (${edges.length})`));
    table(
      tabular,
      [
        { label: 'Device', value: e => hostName(payload, e.source) },
        { label: 'Local port', value: e => e.source_uid },
        { label: 'Peer', value: e => (e.target ? hostName(payload, e.target) : 'Undisclosed peer') },
        { label: 'Peer port', value: e => e.target_uid },
        { label: 'Resolution', value: e => e.status },
        { label: 'Confidence', value: e => e.confidence },
        { label: 'Freshness', value: e => e.freshness }
      ],
      edges,
      'Observed physical topology'
    );
    root.appendChild(tabular);
    capabilities(root, payload, payload.scope?.hostid);
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
            asRows(q.errors)
              .map(e => (typeof e === 'string' ? e : (e.code ?? e.message)))
              .join('; ') ||
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
      findings: renderFindings
    };
    if (handlers[kind]) handlers[kind](root, payload, broadcast, state);
  }
  const runtime = {
    render,
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
    groupedEdges,
    safeNavigation,
    fragmentContext,
    peerUrl,
    findingsCsv
  };
  global.NEWidgetRuntime = runtime;
  if (typeof module !== 'undefined' && module.exports) module.exports = runtime;
})(typeof window !== 'undefined' ? window : globalThis);
