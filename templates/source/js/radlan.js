// RADLAN-derived hardware health -> canonical "hardware" rows. Cisco Small Business (CISCOSB, base
// 1.3.6.1.4.1.9.6.1.101) and Dell X-Series (RADLAN, base 1.3.6.1.4.1.89) carry the same tables under
// different bases: rndMng CPU (.1), rlPhdUnitEnvParamTable (.53.15.1) and the rlEnv fan and supply
// tables (.83.1.1, .83.1.2). Column positions follow mib/ (see mib/README.md).

var RADLAN = {
    CISCOSB: '1.3.6.1.4.1.9.6.1.101',
    RADLAN: '1.3.6.1.4.1.89',
    // rlPhdUnitEnvParamTable column numbers. The two layouts are told apart by where the TimeTicks column
    // rlPhdUnitEnvParamUpTime sits, so a device on the other layout is never read with the wrong columns.
    LAYOUTS: {
        // CISCOSB-Physicaldescription-MIB, 24 columns (SG350/X/XG, CBS350, C1200, C1300).
        '24': {temp: 10, sensor: 11, warning: 12, critical: 13, uptime: 14, verdict: 16, fanSpeed: 18},
        // Dell-Physicaldescription-MIB, 14 columns (SG300 1.4, Dell X-Series 3.0).
        '14': {temp: 9, sensor: 10, warning: null, critical: null, uptime: 11, verdict: 13, fanSpeed: null}
    },
    // rlEnv (and ENTITY) indexes carry the stack unit from bit 26 up; the low byte numbers the fan
    // (from 0x81) or supply (from 0x41) within the unit, matching their fanN_unitM / psN_unitM names.
    UNIT: 67108864,
    FAN_BASE: 128,
    SUPPLY_BASE: 64,
    DELL_GLOBAL: '1.3.6.1.4.1.674.10895.3000.1.2.110.1.0'
};

RADLAN.unitOf = function (index) {
    var n = parseInt(index, 10);
    return isFinite(n) && n >= RADLAN.UNIT ? Math.floor(n / RADLAN.UNIT) : null;
};

RADLAN.itemOf = function (index, base) {
    var n = parseInt(index, 10) % 256 - base;
    return n >= 1 && n <= 6 ? n : null;
};

function normaliseRadlanHardware(walk, env, base, layoutName, dellGlobal) {
    var L = RADLAN.LAYOUTS[layoutName], rows = [], k;
    var envBase = base + '.53.15.1', fanBase = base + '.83.1.1.1', psuBase = base + '.83.1.2.1';
    var cpu1m = NE.scalar(walk, base + '.1.8.0'), cpu5m = NE.scalar(walk, base + '.1.9.0');
    var units = NE.table(walk, envBase + '.1');
    var fanStates = NE.table(walk, fanBase + '.3'), psuStates = NE.table(walk, psuBase + '.3');
    var global = dellGlobal ? NE.scalar(walk, RADLAN.DELL_GLOBAL) : null;
    if (!cpu1m && !cpu5m && !Object.keys(units).length && !Object.keys(fanStates).length &&
            !Object.keys(psuStates).length && !global) {
        throw {unsupported: 'The agent returned no rndMng, rlPhdUnitEnvParam or rlEnv hardware tables.'};
    }

    if (global) { rows.push(HW.row('global', 'global', null, 'Overall status', HW.state(HW.DELL_GLOBAL, global))); }

    if (cpu1m || cpu5m) {
        var enabled = NE.int(NE.scalar(walk, base + '.1.6.0'));
        if (enabled === 2) {
            NE.warning(env, 'cpu_measurement_disabled', 'CPU utilisation measurement is disabled on the device.');
        }
        rows.push(HW.cpuRow({util_1s_pct: HW.percent(NE.scalar(walk, base + '.1.7.0')),
                             util_1m_pct: HW.percent(cpu1m), util_5m_pct: HW.percent(cpu5m)}));
    }

    // One temperature sensor per stack unit, with the unit's own verdict against its own thresholds.
    var column = function (n) { return n === null ? {} : NE.table(walk, envBase + '.' + n); };
    var temp = column(L.temp), sensor = column(L.sensor), warn = column(L.warning), crit = column(L.critical);
    var uptime = column(L.uptime), verdict = column(L.verdict);
    for (k in units) {
        if (!units.hasOwnProperty(k)) { continue; }
        var uid = HW.indexUid('temperature', k);
        if (uid === null) { continue; }
        if (!uptime[k] || uptime[k].type !== 'Timeticks') {
            NE.error(env, 'layout_mismatch', 'rlPhdUnitEnvParamTable does not have the expected column layout.');
            continue;
        }
        var unit = NE.int(units[k]), readable = HW.state(HW.SENSOR, sensor[k]);
        var row = HW.row('temperature', uid, unit, 'Unit ' + unit, readable);
        row.state_source = 'device';
        row.celsius = null;
        if (readable.state === 'ok') {
            row.celsius = NE.int(temp[k] || null);
            var own = HW.state(HW.TEMP_VERDICT, verdict[k]);
            row.state = own.state;
            row.raw_state = own.raw;
        }
        var w = NE.int(warn[k] || null), c = NE.int(crit[k] || null);
        row.warning_c = w !== null && w > 0 ? w : null;
        row.critical_c = c !== null && c > 0 ? c : null;
        rows.push(row);
    }

    var fanNames = NE.table(walk, fanBase + '.2');
    for (k in fanStates) {
        if (!fanStates.hasOwnProperty(k) || HW.indexUid('fan', k) === null) { continue; }
        var fan = HW.row('fan', HW.indexUid('fan', k), RADLAN.unitOf(k), NE.text(fanNames[k] || null) || 'Fan ' + k,
                         HW.state(HW.ENV_MON, fanStates[k]));
        fan.speed = null;
        var n = RADLAN.itemOf(k, RADLAN.FAN_BASE);
        if (L.fanSpeed !== null && n !== null && fan.unit !== null && HW.present(fan.state)) {
            fan.speed = NE.int(NE.scalar(walk, envBase + '.' + (L.fanSpeed + n - 1) + '.' + fan.unit));
        }
        rows.push(fan);
    }

    var psuNames = NE.table(walk, psuBase + '.2'), sources = NE.table(walk, psuBase + '.4');
    for (k in psuStates) {
        if (!psuStates.hasOwnProperty(k) || HW.indexUid('psu', k) === null) { continue; }
        var psu = HW.row('psu', HW.indexUid('psu', k), RADLAN.unitOf(k),
                         NE.text(psuNames[k] || null) || 'Power supply ' + k, HW.state(HW.ENV_MON, psuStates[k]));
        var source = NE.int(sources[k] || null);
        psu.source = HW.present(psu.state) && source !== null ? HW.SUPPLY_SOURCE[source] || null : null;
        rows.push(psu);
    }
    return HW.sortRows(rows);
}
