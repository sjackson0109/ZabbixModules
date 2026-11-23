// Power over Ethernet -> canonical "poe" rows (schema 1.2), from POWER-ETHERNET-MIB (RFC 3621):
//   one "pse" row per PSE group (pethMainPseTable): budget, consumption and the device's own usage threshold;
//   one "port" row per PSE port (pethPsePortTable): detection status, class, priority and the RFC counters.
// A group is a stack unit or module (pethPsePortGroupIndex). RFC 3621 does not map a PSE port to an interface,
// so a port joins to one only where captures show how the vendor numbers its ports (portMap 'ifindex': the port
// index is the ifIndex). The Cisco Small Business vendor table adds the power each port delivers, in milliwatts.

var POE = {
    PORT: '1.3.6.1.2.1.105.1.1.1',
    MAIN: '1.3.6.1.2.1.105.1.3.1.1',
    // rlPethPsePortTable (CISCOSB-POE-MIB), indexed like pethPsePortTable. Columns 5 (rlPethPsePortOutputPower)
    // and 9 (rlPethPsePortOperPowerLimit) are in milliwatts and sit at the same place in the SG300 1.4 layout,
    // whose other columns differ, so only those two are read.
    CISCOSB_PORT: '1.3.6.1.4.1.9.6.1.101.108.1.1',
    DETECTION: {1: 'disabled', 2: 'searching', 3: 'delivering', 4: 'fault', 5: 'test', 6: 'other_fault'},
    OPER: {1: 'on', 2: 'off', 3: 'faulty'},
    PRIORITY: {1: 'critical', 2: 'high', 3: 'low'}
};

POE.count = function (entry) {
    var v = NE.int(entry || null);
    return v === null || v < 0 ? null : v;
};

POE.sort = function (rows) {
    return rows.sort(function (a, b) {
        if (a.kind !== b.kind) { return a.kind === 'pse' ? -1 : 1; }
        if (a.unit !== b.unit) { return (a.unit || 0) - (b.unit || 0); }
        return (a.port || 0) - (b.port || 0);
    });
};

// portMap: 'ifindex' or null. vendor: 'ciscosb' or null.
function normalisePoe(walk, env, portMap, vendor) {
    var admin = NE.table(walk, POE.PORT + '.3'), oper = NE.table(walk, POE.MAIN + '.3');
    if (!Object.keys(admin).length && !Object.keys(oper).length) {
        throw {unsupported: 'The agent returned no POWER-ETHERNET-MIB PSE or PSE port tables.'};
    }
    var port = function (n) { return NE.table(walk, POE.PORT + '.' + n); };
    var detection = port(6), priority = port(7), mps = port(8), klass = port(10), invalid = port(11);
    var denied = port(12), overload = port(13), shorted = port(14);
    var power = vendor === 'ciscosb' ? NE.table(walk, POE.CISCOSB_PORT + '.5') : null;
    var limit = vendor === 'ciscosb' ? NE.table(walk, POE.CISCOSB_PORT + '.9') : null;
    if (power !== null && Object.keys(admin).length && !Object.keys(power).length) {
        NE.warning(env, 'vendor_power_missing', 'The vendor PoE table is missing, so per-port power is not reported.');
    }
    var uids = portMap === 'ifindex' ? NE.interfaceIndex(walk, env, true) : {};
    var names = portMap === 'ifindex' ? NE.table(walk, NE.IF.name) : {};
    var rows = [], ports = {}, k, m;

    for (k in admin) {
        if (!admin.hasOwnProperty(k) || !(m = /^([0-9]+)\.([0-9]+)$/.exec(k))) { continue; }
        var group = parseInt(m[1], 10), index = parseInt(m[2], 10);
        if (!detection[k]) {
            NE.error(env, 'incomplete_row', 'A PSE port row has no detection status; the walk is incomplete.');
            continue;
        }
        ports[group] = (ports[group] || 0) + 1;
        var det = NE.int(detection[k]), on = NE.int(admin[k]), cls = NE.int(klass[k] || null);
        var row = {kind: 'port', uid: 'port-' + group + '-' + index, unit: group, name: 'Port ' + group + '/' + index,
                   state: POE.DETECTION[det] || 'unknown', raw_state: det, port: index,
                   if_index: null, interface_uid: null,
                   admin_enabled: on === 1 ? true : (on === 2 ? false : null),
                   // The class is valid only while the port delivers power (RFC 3621).
                   power_class: det === 3 && cls !== null && cls >= 1 && cls <= 5 ? cls - 1 : null,
                   priority: POE.PRIORITY[NE.int(priority[k] || null)] || null,
                   power_mw: null, power_limit_mw: null,
                   mps_absent: POE.count(mps[k]), invalid_signature: POE.count(invalid[k]),
                   power_denied: POE.count(denied[k]), overload: POE.count(overload[k]), short: POE.count(shorted[k])};
        if (portMap === 'ifindex') {
            if (uids[String(index)]) {
                row.if_index = index;
                row.interface_uid = uids[String(index)];
                row.name = NE.text(names[String(index)] || null) || row.name;
            }
            else {
                NE.warning(env, 'port_unmapped', 'A PoE port has no interface with its index; it is named by group and port.');
            }
        }
        if (power !== null) {
            row.power_mw = POE.count(power[k]);
            row.power_limit_mw = POE.count(limit[k]);
        }
        rows.push(row);
    }

    var any = Object.keys(ports).length > 0;
    if (!any && Object.keys(oper).length) {
        NE.error(env, 'port_table_missing', 'The PSE table has rows but the PSE port table has none.');
    }
    for (k in oper) {
        if (!oper.hasOwnProperty(k) || !/^[0-9]+$/.test(k)) { continue; }
        var unit = parseInt(k, 10), status = NE.int(oper[k]);
        var pse = {kind: 'pse', uid: 'pse-' + unit, unit: unit, name: (portMap === 'ifindex' ? 'Unit ' : 'Group ') + unit,
                   state: POE.OPER[status] || 'unknown', raw_state: status, power_w: null, consumption_w: null,
                   usage_threshold_pct: null, util_pct: null, port_count: ports[unit] || 0};
        if (any && !ports[unit]) {
            // A stack slot without a unit: the agent lists the group but no ports on it.
            pse.state = 'not_present';
        }
        else {
            var budget = NE.int(NE.scalar(walk, POE.MAIN + '.2.' + k)), used = NE.int(NE.scalar(walk, POE.MAIN + '.4.' + k));
            var threshold = NE.int(NE.scalar(walk, POE.MAIN + '.5.' + k));
            pse.power_w = budget !== null && budget >= 0 ? budget : null;
            pse.consumption_w = used !== null && used >= 0 ? used : null;
            pse.usage_threshold_pct = threshold !== null && threshold >= 1 && threshold <= 99 ? threshold : null;
            pse.util_pct = pse.power_w && pse.consumption_w !== null
                ? Math.round(pse.consumption_w * 1000 / pse.power_w) / 10 : null;
        }
        rows.push(pse);
    }
    return POE.sort(rows);
}
