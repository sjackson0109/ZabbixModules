// CISCO-ENVMON-MIB (1.3.6.1.4.1.9.9.13) -> canonical "hardware" rows: temperature sensors, fans and power
// supplies, each with the device's own CiscoEnvMonState verdict (the same 1-6 values as RlEnvMonState, so
// HW.ENV_MON maps them). Cisco's data sheet lists this MIB for the Business 220 series; templates/specifications/
// HARDWARE.md says what has been captured. The MIB has no CPU, memory or stack-unit objects.

var ENVMON = {
    TEMP: '1.3.6.1.4.1.9.9.13.1.3.1',     // ciscoEnvMonTemperatureStatusEntry
    FAN: '1.3.6.1.4.1.9.9.13.1.4.1',      // ciscoEnvMonFanStatusEntry
    SUPPLY: '1.3.6.1.4.1.9.9.13.1.5.1'    // ciscoEnvMonSupplyStatusEntry
};

function normaliseEnvmonHardware(walk, env) {
    var temps = NE.table(walk, ENVMON.TEMP + '.6'), fans = NE.table(walk, ENVMON.FAN + '.3');
    var supplies = NE.table(walk, ENVMON.SUPPLY + '.3'), rows = [], k;
    if (!Object.keys(temps).length && !Object.keys(fans).length && !Object.keys(supplies).length) {
        throw {unsupported: 'The agent returned no CISCO-ENVMON-MIB temperature, fan or supply tables.'};
    }
    var column = function (base, n) { return NE.table(walk, base + '.' + n); };

    var tempNames = column(ENVMON.TEMP, 2), legacy = column(ENVMON.TEMP, 3), shutdown = column(ENVMON.TEMP, 4);
    var current = column(ENVMON.TEMP, 7);
    for (k in temps) {
        if (!temps.hasOwnProperty(k) || HW.indexUid('temperature', k) === null) { continue; }
        var row = HW.row('temperature', HW.indexUid('temperature', k), null,
                         NE.text(tempNames[k] || null) || 'Temperature sensor ' + k, HW.state(HW.ENV_MON, temps[k]));
        row.state_source = 'device';
        // ciscoEnvMonTemperatureStatusValueRev1 (signed) replaces the deprecated unsigned column 3.
        row.celsius = HW.present(row.state) ? NE.int(current[k] || legacy[k] || null) : null;
        row.warning_c = null;
        row.critical_c = null;
        var limit = NE.int(shutdown[k] || null);
        row.shutdown_c = limit !== null && limit > 0 ? limit : null;
        rows.push(row);
    }

    var fanNames = column(ENVMON.FAN, 2);
    for (k in fans) {
        if (!fans.hasOwnProperty(k) || HW.indexUid('fan', k) === null) { continue; }
        var fan = HW.row('fan', HW.indexUid('fan', k), null, NE.text(fanNames[k] || null) || 'Fan ' + k,
                         HW.state(HW.ENV_MON, fans[k]));
        fan.speed = null;
        rows.push(fan);
    }

    var supplyNames = column(ENVMON.SUPPLY, 2), sources = column(ENVMON.SUPPLY, 4);
    for (k in supplies) {
        if (!supplies.hasOwnProperty(k) || HW.indexUid('psu', k) === null) { continue; }
        var psu = HW.row('psu', HW.indexUid('psu', k), null, NE.text(supplyNames[k] || null) || 'Power supply ' + k,
                         HW.state(HW.ENV_MON, supplies[k]));
        var source = NE.int(sources[k] || null);
        psu.source = HW.present(psu.state) && source !== null ? HW.SUPPLY_SOURCE[source] || null : null;
        rows.push(psu);
    }
    return HW.sortRows(rows);
}
