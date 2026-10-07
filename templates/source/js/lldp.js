// LLDP-MIB (+ 802.3 and 802.1 extensions) walk -> canonical "lldp" rows.
// Set REDACT_REMOTE to true to suppress remote identities at collection time.

var LLDP = {
    locPortSubtype: '1.0.8802.1.1.2.1.3.7.1.2',
    locPortId: '1.0.8802.1.1.2.1.3.7.1.3',
    locPortDesc: '1.0.8802.1.1.2.1.3.7.1.4',
    remChassisSubtype: '1.0.8802.1.1.2.1.4.1.1.4',
    remChassisId: '1.0.8802.1.1.2.1.4.1.1.5',
    remPortSubtype: '1.0.8802.1.1.2.1.4.1.1.6',
    remPortId: '1.0.8802.1.1.2.1.4.1.1.7',
    remPortDesc: '1.0.8802.1.1.2.1.4.1.1.8',
    remSysName: '1.0.8802.1.1.2.1.4.1.1.9',
    remSysDesc: '1.0.8802.1.1.2.1.4.1.1.10',
    remCapSupported: '1.0.8802.1.1.2.1.4.1.1.11',
    remCapEnabled: '1.0.8802.1.1.2.1.4.1.1.12',
    remManAddrIfSubtype: '1.0.8802.1.1.2.1.4.2.1.3',
    dot3RemAdvertised: '1.0.8802.1.1.2.1.5.4623.1.3.1.1.3',
    dot3RemOperMau: '1.0.8802.1.1.2.1.5.4623.1.3.1.1.4',
    dot3RemAggStatus: '1.0.8802.1.1.2.1.5.4623.1.3.3.1.1',
    dot3RemAggPortId: '1.0.8802.1.1.2.1.5.4623.1.3.3.1.2',
    dot1RemPvid: '1.0.8802.1.1.2.1.5.32962.1.3.1.1.1'
};
var LLDP_CAPS = ['other', 'repeater', 'bridge', 'wlan_access_point', 'router', 'telephone',
                 'docsis', 'station', 'c_vlan', 's_vlan', 'tpmr'];

function lldpCapabilities(entry) {
    if (!entry) { return null; }
    var bits = NE.bitsSet(NE.bytes(entry)), out = [], i;
    for (i = 0; i < bits.length; i++) {
        if (LLDP_CAPS[bits[i]]) { out.push(LLDP_CAPS[bits[i]]); }
    }
    return out;
}

// lldpLocPortNum is not ifIndex: map it by port ID subtype.
function lldpLocalInterface(walk, subtype, idEntry, descEntry, uids) {
    var names = NE.table(walk, NE.IF.name), aliases = NE.table(walk, NE.IF.alias);
    var descrs = NE.table(walk, NE.IF.descr), macs = NE.table(walk, NE.IF.mac);
    var wanted = subtype === 3 ? NE.mac(idEntry) : NE.text(idEntry), desc = NE.text(descEntry);
    var matches = [], k, source;
    source = subtype === 5 ? names : (subtype === 1 ? aliases : (subtype === 3 ? macs : null));
    if (source !== null && wanted) {
        for (k in source) {
            if (source.hasOwnProperty(k) && (subtype === 3 ? NE.mac(source[k]) : NE.text(source[k])) === wanted) { matches.push(k); }
        }
    }
    if (subtype === 7 && wanted) {
        for (k in uids) {
            if (uids.hasOwnProperty(k) && (NE.text(names[k] || null) === wanted || NE.text(descrs[k] || null) === wanted)) { matches.push(k); }
        }
        if (matches.length !== 1 && desc) {
            matches = [];
            for (k in descrs) {
                if (descrs.hasOwnProperty(k) && NE.text(descrs[k]) === desc) { matches.push(k); }
            }
        }
    }
    return matches.length === 1 ? {ifIndex: parseInt(matches[0], 10), uid: uids[matches[0]] || null} : null;
}

function normaliseLldp(walk, env, redact) {
    var uids = NE.interfaceIndex(walk, env, true), t = {}, key;
    for (key in LLDP) {
        if (LLDP.hasOwnProperty(key)) { t[key] = NE.table(walk, LLDP[key]); }
    }
    if (!NE.has(walk, '1.0.8802.1.1.2.1.3.7.1') && !NE.has(walk, '1.0.8802.1.1.2.1.4.1.1')) {
        throw {unsupported: 'The agent returned no LLDP-MIB local port or remote tables.'};
    }
    var addresses = {};
    for (key in t.remManAddrIfSubtype) {
        if (!t.remManAddrIfSubtype.hasOwnProperty(key)) { continue; }
        var p = key.split('.');
        if (p.length < 6) { continue; }
        var family = parseInt(p[3], 10), length = parseInt(p[4], 10), octets = [];
        for (var j = 5; j < p.length; j++) { octets.push(parseInt(p[j], 10)); }
        var address = octets.length === length && (family === 1 || family === 2) ? NE.ipFromOctets(octets) : null;
        if (address === null) { continue; }
        var triple = p[0] + '.' + p[1] + '.' + p[2];
        (addresses[triple] = addresses[triple] || []).push(address);
    }
    var indexes = [];
    for (key in t.remChassisId) {
        if (t.remChassisId.hasOwnProperty(key)) { indexes.push(key); }
    }
    indexes.sort(function (a, b) {
        var x = a.split('.'), y = b.split('.'), i;
        for (i = 0; i < 3; i++) { if (x[i] !== y[i]) { return parseInt(x[i], 10) - parseInt(y[i], 10); } }
        return 0;
    });
    var rows = [];
    for (var i = 0; i < indexes.length; i++) {
        var idx = indexes[i], parts = idx.split('.');
        if (parts.length !== 3) {
            NE.error(env, 'malformed_lldp_index', 'An LLDP row does not have a timeMark.localPort.remIndex index.');
            continue;
        }
        if (!t.remChassisSubtype[idx] || !t.remPortSubtype[idx] || !t.remPortId[idx]) {
            NE.error(env, 'missing_lldp_identity', 'An LLDP neighbour lacks a chassis or port identity.');
            continue;
        }
        var local = parts[1], localSubtype = NE.int(t.locPortSubtype[local] || null);
        var mapped = lldpLocalInterface(walk, localSubtype, t.locPortId[local] || null, t.locPortDesc[local] || null, uids);
        // An unmapped local port stays visible as local_interface_uid = null.
        var operMau = NE.MAU[NE.int(t.dot3RemOperMau[idx] || null)] || null;
        var advertised = t.dot3RemAdvertised[idx] ? NE.speedsFromBits(NE.bitsSet(NE.bytes(t.dot3RemAdvertised[idx])), 'autoneg') : null;
        var agg = t.dot3RemAggStatus[idx] ? NE.bitsSet(NE.bytes(t.dot3RemAggStatus[idx])) : null;
        var addr = addresses[idx] || [];
        var row = {
            protocol: 'lldp', source_index: idx,
            local_interface_uid: mapped ? mapped.uid : null,
            local_if_index: mapped ? mapped.ifIndex : null,
            local_port_id: NE.lldpId(t.locPortSubtype[local] || null, t.locPortId[local] || null, 'port'),
            remote_chassis_id: NE.lldpId(t.remChassisSubtype[idx], t.remChassisId[idx], 'chassis'),
            remote_port_id: NE.lldpId(t.remPortSubtype[idx], t.remPortId[idx], 'port'),
            remote_system_name: NE.text(t.remSysName[idx] || null),
            remote_system_description: t.remSysDesc[idx] ? NE.text(t.remSysDesc[idx]).substring(0, 255) : null,
            remote_port_description: NE.text(t.remPortDesc[idx] || null),
            remote_management_addresses: addr.sort().filter(function (v, n, a) { return n === 0 || a[n - 1] !== v; }),
            capabilities: {supported: lldpCapabilities(t.remCapSupported[idx] || null),
                           enabled: lldpCapabilities(t.remCapEnabled[idx] || null)},
            remote_advertised_speeds_bps: advertised,
            remote_oper_speed_bps: operMau ? operMau[0] : null,
            remote_duplex: operMau ? operMau[1] : null,
            remote_lag: agg === null ? null : {aggregated: agg.indexOf(1) >= 0,
                                               port_id: NE.int(t.dot3RemAggPortId[idx] || null)},
            remote_pvid: NE.int(t.dot1RemPvid[idx] || null),
            observed_at: env.attempted_at
        };
        if (redact) {
            row.remote_chassis_id = {subtype: null, value: ''};
            row.remote_port_id = {subtype: null, value: ''};
            row.remote_system_name = null;
            row.remote_system_description = null;
            row.remote_port_description = null;
            row.remote_management_addresses = [];
        }
        rows.push(row);
    }
    return rows;
}
