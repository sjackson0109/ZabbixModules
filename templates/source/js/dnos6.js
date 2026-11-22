// Dell N-Series (DNOS 6) hardware health -> canonical "hardware" rows.
// CPU and memory: DNOS-SWITCHING-MIB agentSwitchCpuProcessGroup. Fans, supplies and temperature
// sensors: DNOS-BOXSERVICES-PRIVATE-MIB, indexed by stack unit. Overall status: Dell-Vendor-MIB.

var DNOS = {
    cpu: '1.3.6.1.4.1.674.10895.5000.2.6132.1.1.1.1.4',
    box: '1.3.6.1.4.1.674.10895.5000.2.6132.1.1.43.1',
    global: '1.3.6.1.4.1.674.10895.3000.1.2.110.1.0'
};

function dnosUnitRows(walk, kind, table, stateColumn, unitColumn, map, label) {
    var states = NE.table(walk, table + '.' + stateColumn), units = NE.table(walk, table + '.' + unitColumn);
    var rows = [], k;
    for (k in states) {
        if (!states.hasOwnProperty(k)) { continue; }
        var uid = HW.indexUid(kind, k), parts = k.split('.');
        if (uid === null || parts.length !== 2) { continue; }
        var unit = NE.int(units[k] || null);
        if (unit === null) { unit = parseInt(parts[0], 10); }
        rows.push(HW.row(kind, uid, unit, 'Unit ' + unit + ' ' + label + ' ' + parts[1], HW.state(map, states[k])));
    }
    return rows;
}

function normaliseDnosHardware(walk, env) {
    var rows = [], i;
    var free = NE.int(NE.scalar(walk, DNOS.cpu + '.1.0')), total = NE.int(NE.scalar(walk, DNOS.cpu + '.2.0'));
    var cpu = [NE.scalar(walk, DNOS.cpu + '.10.0'), NE.scalar(walk, DNOS.cpu + '.11.0'), NE.scalar(walk, DNOS.cpu + '.12.0')];
    var global = NE.scalar(walk, DNOS.global);
    var fans = dnosUnitRows(walk, 'fan', DNOS.box + '.6.1', 3, 6, HW.BOX_ITEM, 'fan');
    var psus = dnosUnitRows(walk, 'psu', DNOS.box + '.7.1', 3, 4, HW.BOX_ITEM, 'power supply');
    var temps = dnosUnitRows(walk, 'temperature', DNOS.box + '.8.1', 4, 1, HW.BOX_TEMP, 'sensor');
    if (!cpu[0] && !cpu[1] && !cpu[2] && total === null && !global && !fans.length && !psus.length && !temps.length) {
        throw {unsupported: 'The agent returned no DNOS switching, boxServices or Dell-Vendor status tables.'};
    }
    if (global) { rows.push(HW.row('global', 'global', null, 'Overall status', HW.state(HW.DELL_GLOBAL, global))); }
    if (cpu[0] || cpu[1] || cpu[2]) {
        rows.push(HW.cpuRow({util_5s_pct: HW.percent(cpu[0]), util_1m_pct: HW.percent(cpu[1]),
                             util_5m_pct: HW.percent(cpu[2])}));
    }
    if (total !== null && total > 0 && free !== null && free >= 0 && free <= total) {
        rows.push({kind: 'memory', uid: 'memory', unit: null, name: 'Memory', state: null, raw_state: null,
                   total_bytes: total * 1024, free_bytes: free * 1024,
                   util_pct: Math.round((total - free) * 1000 / total) / 10});
    }
    else if (total !== null || free !== null) {
        NE.warning(env, 'memory_unreadable', 'The memory counters are missing or inconsistent.');
    }
    var speeds = NE.table(walk, DNOS.box + '.6.1.4');
    for (i = 0; i < fans.length; i++) {
        var key = fans[i].uid.replace(/^fan-/, '').replace(/-/g, '.');
        fans[i].speed = HW.present(fans[i].state) ? NE.int(speeds[key] || null) : null;
    }
    for (i = 0; i < psus.length; i++) { psus[i].source = null; }
    var values = NE.table(walk, DNOS.box + '.8.1.5');
    for (i = 0; i < temps.length; i++) {
        var t = temps[i], index = t.uid.replace(/^temperature-/, '').replace(/-/g, '.');
        t.state_source = 'device';
        t.celsius = HW.present(t.state) && t.state !== 'not_functioning' ? NE.int(values[index] || null) : null;
        t.warning_c = null;
        t.critical_c = null;
    }
    return HW.sortRows(rows.concat(fans, psus, temps));
}
