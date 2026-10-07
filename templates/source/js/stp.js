// BRIDGE-MIB + RSTP-MIB walk -> canonical "stp" rows for the common
// spanning tree (instance 0). Port roles are not in these MIBs, so they are
// derived from root port and designated bridge evidence and marked "derived".

var STP = {
    protocol: '1.3.6.1.2.1.17.2.1.0',
    priority: '1.3.6.1.2.1.17.2.2.0',
    sinceChange: '1.3.6.1.2.1.17.2.3.0',
    changes: '1.3.6.1.2.1.17.2.4.0',
    root: '1.3.6.1.2.1.17.2.5.0',
    rootCost: '1.3.6.1.2.1.17.2.6.0',
    rootPort: '1.3.6.1.2.1.17.2.7.0',
    version: '1.3.6.1.2.1.17.2.16.0',
    bridgeAddress: '1.3.6.1.2.1.17.1.1.0',
    portPriority: '1.3.6.1.2.1.17.2.15.1.2',
    portState: '1.3.6.1.2.1.17.2.15.1.3',
    portEnable: '1.3.6.1.2.1.17.2.15.1.4',
    portCost: '1.3.6.1.2.1.17.2.15.1.5',
    portDesigRoot: '1.3.6.1.2.1.17.2.15.1.6',
    portDesigBridge: '1.3.6.1.2.1.17.2.15.1.8',
    portDesigPort: '1.3.6.1.2.1.17.2.15.1.9',
    portCost32: '1.3.6.1.2.1.17.2.15.1.11',
    operEdge: '1.3.6.1.2.1.17.2.19.1.3',
    operP2p: '1.3.6.1.2.1.17.2.19.1.5'
};
var STP_STATE = {1: 'disabled', 2: 'blocking', 3: 'listening', 4: 'learning', 5: 'forwarding', 6: 'broken'};

function stpBridgeId(entry) {
    var b = NE.bytes(entry);
    return b && b.length === 8 ? NE.hex(b) : null;
}

function stpTruth(entry) {
    var v = NE.int(entry);
    return v === 1 ? true : (v === 2 ? false : null);
}

function normaliseStp(walk, env) {
    var t = {}, key;
    if (!NE.scalar(walk, STP.root) && !NE.has(walk, '1.3.6.1.2.1.17.2.15.1')) {
        throw {unsupported: 'The agent returned no BRIDGE-MIB spanning tree objects.'};
    }
    for (key in STP) {
        if (STP.hasOwnProperty(key)) { t[key] = /\.0$/.test(STP[key]) ? NE.scalar(walk, STP[key]) : NE.table(walk, STP[key]); }
    }
    var uids = NE.interfaceIndex(walk, env, true), bridgePorts = NE.table(walk, NE.BRIDGE_PORT_IFINDEX);
    var priority = NE.int(t.priority), mac = NE.bytes(t.bridgeAddress), own = null;
    if (priority !== null && mac && mac.length === 6) {
        own = NE.hex([(priority >> 8) & 255, priority & 255].concat(mac));
    }
    var version = NE.int(t.version), protocol = 'unknown';
    if (version === 0) { protocol = 'stp'; }
    else if (version === 2) { protocol = 'rstp'; }
    else if (version === 3) { protocol = 'mstp'; }
    else if (NE.int(t.protocol) === 3) { protocol = 'stp'; }
    var rootPort = NE.int(t.rootPort);
    function uidOf(port) {
        var ifIndex = bridgePorts[port] ? String(NE.int(bridgePorts[port])) : null;
        return ifIndex !== null && uids.hasOwnProperty(ifIndex) ? uids[ifIndex] : null;
    }
    var ticks = NE.int(t.sinceChange);
    var rows = [{
        kind: 'bridge', instance: 0, protocol: protocol, bridge_id: own,
        root_bridge_id: stpBridgeId(t.root), root_cost: NE.int(t.rootCost),
        root_port_uid: rootPort ? uidOf(String(rootPort)) : null, priority: priority,
        vlans: null, topology_changes: NE.int(t.changes),
        time_since_topology_change_s: ticks === null ? null : Math.floor(ticks / 100)
    }];
    var ports = [];
    for (key in t.portState) {
        if (t.portState.hasOwnProperty(key) && /^[0-9]+$/.test(key)) { ports.push(parseInt(key, 10)); }
    }
    ports.sort(function (a, b) { return a - b; });
    for (var i = 0; i < ports.length; i++) {
        var p = String(ports[i]), state = STP_STATE[NE.int(t.portState[p])] || 'unknown';
        var desBridge = stpBridgeId(t.portDesigBridge[p] || null);
        var desPortBytes = NE.bytes(t.portDesigPort[p] || null);
        var desPort = desPortBytes && desPortBytes.length === 2 ? NE.hex(desPortBytes) : null;
        var enabled = NE.int(t.portEnable[p] || null);
        var role = 'unknown';
        if (state === 'disabled' || enabled === 2) { role = 'disabled'; }
        else if (rootPort !== null && ports[i] === rootPort) { role = 'root'; }
        else if (own !== null && desBridge !== null && desBridge.substring(4) === own.substring(4)) {
            // This bridge is designated for the segment; a second own port on it is a backup.
            role = desPort === null || (parseInt(desPort, 16) & 0x0fff) === ports[i] ? 'designated' : 'backup';
        }
        else if (desBridge !== null && (state === 'blocking' || state === 'listening')) { role = 'alternate'; }
        var cost32 = NE.int(t.portCost32[p] || null);
        var uid = uidOf(p);
        if (uid === null) {
            NE.error(env, 'bridge_port_unresolved', 'A spanning tree port could not be mapped to an interface.');
        }
        rows.push({
            kind: 'port', instance: 0, interface_uid: uid, bridge_port: ports[i],
            role: role, role_source: role === 'unknown' ? 'unknown' : 'derived', state: state,
            cost: cost32 !== null && cost32 > 0 ? cost32 : NE.int(t.portCost[p] || null),
            priority: NE.int(t.portPriority[p] || null), designated_bridge: desBridge, designated_port: desPort,
            edge: stpTruth(t.operEdge[p] || null), point_to_point: stpTruth(t.operP2p[p] || null)
        });
    }
    return rows;
}
