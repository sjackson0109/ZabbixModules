// Q-BRIDGE-MIB + BRIDGE-MIB walk -> canonical "vlan" rows.
// Port bitmaps are indexed by bridge port, mapped to interfaces through
// dot1dBasePortIfIndex. Bitmaps are MSB-first: bit 0 of octet 0 is port 1.

var QB = {
    staticName: '1.3.6.1.2.1.17.7.1.4.3.1.1',
    staticEgress: '1.3.6.1.2.1.17.7.1.4.3.1.2',
    staticForbidden: '1.3.6.1.2.1.17.7.1.4.3.1.3',
    staticUntagged: '1.3.6.1.2.1.17.7.1.4.3.1.4',
    currentEgress: '1.3.6.1.2.1.17.7.1.4.2.1.4',
    currentUntagged: '1.3.6.1.2.1.17.7.1.4.2.1.5',
    currentStatus: '1.3.6.1.2.1.17.7.1.4.2.1.6',
    pvid: '1.3.6.1.2.1.17.7.1.4.5.1.1',
    frameTypes: '1.3.6.1.2.1.17.7.1.4.5.1.2'
};
var VLAN_STATUS = {1: 'other', 2: 'permanent', 3: 'dynamic'};

// {vlanId: {bridgePort: true}} from a bitmap column; current-table rows are
// indexed by timeMark.vlanId, static rows by vlanId.
function vlanBitmaps(column, current) {
    var out = {}, k, vid, ports, i;
    for (k in column) {
        if (!column.hasOwnProperty(k)) { continue; }
        vid = current ? k.split('.')[1] : k;
        if (!/^[0-9]+$/.test(vid || '')) { continue; }
        ports = NE.bitsSet(NE.bytes(column[k]), 1);
        out[vid] = out[vid] || {};
        for (i = 0; i < ports.length; i++) { out[vid][ports[i]] = true; }
    }
    return out;
}

function vlanMembers(bitmaps, port) {
    var out = [], vid;
    for (vid in bitmaps) {
        if (bitmaps.hasOwnProperty(vid) && bitmaps[vid][port]) { out.push(parseInt(vid, 10)); }
    }
    return out;
}

function normaliseVlan(walk, env) {
    var t = {}, key;
    for (key in QB) {
        if (QB.hasOwnProperty(key)) { t[key] = NE.table(walk, QB[key]); }
    }
    var hasStatic = NE.has(walk, QB.staticEgress), hasCurrent = NE.has(walk, QB.currentEgress);
    if (!hasStatic && !hasCurrent) {
        throw {unsupported: 'The agent returned no Q-BRIDGE-MIB VLAN membership tables.'};
    }
    var uids = NE.interfaceIndex(walk, env, true);
    var bridgePorts = NE.table(walk, NE.BRIDGE_PORT_IFINDEX);
    var sEgress = vlanBitmaps(t.staticEgress, false), sUntagged = vlanBitmaps(t.staticUntagged, false);
    var sForbidden = vlanBitmaps(t.staticForbidden, false);
    var cEgress = vlanBitmaps(t.currentEgress, true), cUntagged = vlanBitmaps(t.currentUntagged, true);
    var rows = [], vids = {}, vid;

    for (key in t.staticName) { if (t.staticName.hasOwnProperty(key)) { vids[key] = true; } }
    for (key in sEgress) { if (sEgress.hasOwnProperty(key)) { vids[key] = true; } }
    for (key in cEgress) { if (cEgress.hasOwnProperty(key)) { vids[key] = true; } }
    var status = {};
    for (key in t.currentStatus) {
        if (t.currentStatus.hasOwnProperty(key)) { status[key.split('.')[1]] = NE.int(t.currentStatus[key]); }
    }
    var vidList = [];
    for (vid in vids) {
        if (vids.hasOwnProperty(vid) && parseInt(vid, 10) >= 1 && parseInt(vid, 10) <= 4094) { vidList.push(parseInt(vid, 10)); }
    }
    vidList.sort(function (a, b) { return a - b; });
    for (var v = 0; v < vidList.length; v++) {
        vid = String(vidList[v]);
        rows.push({kind: 'vlan', vlan_id: vidList[v], name: NE.text(t.staticName[vid] || null),
                   state: VLAN_STATUS[status[vid]] || (t.staticName[vid] || sEgress[vid] ? 'permanent' : 'unknown')});
    }

    // Every bridge port that appears in the base table, a bitmap or the PVID table.
    var ports = {}, p;
    for (key in bridgePorts) { if (bridgePorts.hasOwnProperty(key)) { ports[key] = true; } }
    for (key in t.pvid) { if (t.pvid.hasOwnProperty(key)) { ports[key] = true; } }
    var maps = [sEgress, cEgress];
    for (var m = 0; m < maps.length; m++) {
        for (vid in maps[m]) {
            if (!maps[m].hasOwnProperty(vid)) { continue; }
            for (p in maps[m][vid]) { if (maps[m][vid].hasOwnProperty(p)) { ports[p] = true; } }
        }
    }
    var portList = [];
    for (p in ports) { if (ports.hasOwnProperty(p) && /^[0-9]+$/.test(p)) { portList.push(parseInt(p, 10)); } }
    portList.sort(function (a, b) { return a - b; });

    for (var i = 0; i < portList.length; i++) {
        p = String(portList[i]);
        var ifIndex = bridgePorts[p] ? String(NE.int(bridgePorts[p])) : null;
        var uid = ifIndex !== null && uids.hasOwnProperty(ifIndex) ? uids[ifIndex] : null;
        if (uid === null) {
            NE.error(env, 'bridge_port_unresolved', 'A bridge port could not be mapped to an interface; its VLAN membership is unattributed.');
        }
        var egress = hasStatic ? vlanMembers(sEgress, p) : null;
        var untagged = hasStatic ? vlanMembers(sUntagged, p) : null;
        var forbidden = hasStatic ? vlanMembers(sForbidden, p) : null;
        var curEgress = hasCurrent ? vlanMembers(cEgress, p) : null;
        var curUntagged = hasCurrent ? vlanMembers(cUntagged, p) : null;
        var tagged = null;
        if (egress !== null) {
            tagged = egress.filter(function (x) { return untagged.indexOf(x) < 0; });
        }
        // Classify from configuration, or from operational state when only that exists.
        var cfgTagged = tagged !== null ? tagged : (curEgress !== null ? curEgress.filter(function (x) { return curUntagged.indexOf(x) < 0; }) : []);
        var cfgUntagged = untagged !== null ? untagged : (curUntagged || []);
        var frames = NE.int(t.frameTypes[p] || null), mode = 'unknown';
        if (cfgTagged.length > 0 || frames === 2) { mode = cfgUntagged.length > 1 ? 'hybrid' : 'trunk'; }
        else if (cfgUntagged.length === 1) { mode = 'access'; }
        else if (cfgUntagged.length > 1) { mode = 'hybrid'; }
        var row = {kind: 'port', interface_uid: uid, bridge_port: portList[i], mode: mode,
                   pvid: NE.int(t.pvid[p] || null),
                   tagged: NE.ranges(tagged), untagged: NE.ranges(untagged), forbidden: NE.ranges(forbidden),
                   current_egress: NE.ranges(curEgress), current_untagged: NE.ranges(curUntagged),
                   source: hasStatic ? 'q-bridge-static' : 'q-bridge-current'};
        if (row.pvid !== null && (row.pvid < 0 || row.pvid > 4094)) { row.pvid = null; }
        rows.push(row);
    }
    return rows;
}
