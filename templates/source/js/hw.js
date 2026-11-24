// Shared hardware-health helpers -> canonical "hardware" rows (schema 1.2).
// Every row has kind, uid, unit (stack unit number or null), name, state and raw_state;
// the other fields depend on the kind. A state is the device's own verdict, never a
// threshold this template invents: canonical states are ok, warning, critical, shutdown,
// not_present, not_functioning, unavailable and unknown.

var HW = {};

// RlEnvMonState (CISCOSB-, RADLAN- and Dell-HWENVIROMENT) and EnvMonState (Dell-Vendor-MIB) share 1-6.
// backingUp(8) means the redundant supply is carrying the load, so the main one is not.
HW.ENV_MON = {1: 'ok', 2: 'warning', 3: 'critical', 4: 'shutdown', 5: 'not_present', 6: 'not_functioning',
              7: 'unavailable', 8: 'warning', 9: 'unknown'};
// boxServicesFanItemState / boxServicesPowSupplyItemState (DNOS-BOXSERVICES-PRIVATE-MIB).
// nopower(5) is a present unit without input power; incompatible(7) a pluggable part the board cannot use.
HW.BOX_ITEM = {1: 'not_present', 2: 'ok', 3: 'critical', 4: 'warning', 5: 'warning', 6: 'critical', 7: 'not_functioning'};
// BoxsTemperatureStatus (DNOS-BOXSERVICES-PRIVATE-MIB); low(0) is below the normal range.
HW.BOX_TEMP = {0: 'warning', 1: 'ok', 2: 'warning', 3: 'critical', 4: 'shutdown', 5: 'not_present', 6: 'not_functioning'};
// EntitySensorStatus (ENTITY-SENSOR-MIB): whether the sensor value can be read at all.
HW.SENSOR = {1: 'ok', 2: 'unavailable', 3: 'not_functioning'};
// rlPhdUnitEnvParamMonitorTemperatureStatus: the unit's own verdict against its own thresholds.
HW.TEMP_VERDICT = {1: 'ok', 2: 'warning', 3: 'critical'};
// productStatusGlobalStatus (Dell-Vendor-MIB).
HW.DELL_GLOBAL = {3: 'ok', 4: 'warning', 5: 'critical'};
HW.SUPPLY_SOURCE = {1: 'unknown', 2: 'ac', 3: 'dc', 4: 'external', 5: 'internal_redundant'};

HW.state = function (map, entry) {
    var v = NE.int(entry || null);
    return {state: v === null ? 'unknown' : (map[v] || 'unknown'), raw: v};
};

// A part the device lists but does not report as fitted (or cannot say) has no readings.
HW.present = function (state) {
    return state !== 'not_present' && state !== 'unknown';
};

HW.row = function (kind, uid, unit, name, state) {
    return {kind: kind, uid: uid, unit: unit, name: name, state: state.state, raw_state: state.raw};
};

// A utilisation the device reports as a percentage; anything outside 0-100 is "not measured"
// (rlCpuUtil* returns 101 when measurement is disabled).
HW.percent = function (entry) {
    var v = NE.int(entry || null);
    return v === null || v < 0 || v > 100 ? null : v;
};

HW.cpuRow = function (fields) {
    var row = {kind: 'cpu', uid: 'cpu', unit: null, name: 'CPU', state: null, raw_state: null};
    for (var k in fields) {
        if (fields.hasOwnProperty(k)) { row[k] = fields[k]; }
    }
    return row;
};

// Kind, then stack unit, then the numeric index parts of the UID.
HW.sortRows = function (rows) {
    var order = {global: 0, cpu: 1, memory: 2, psu: 3, fan: 4, temperature: 5};
    var parts = function (uid) { return uid.split('-').slice(1).map(function (x) { return parseInt(x, 10); }); };
    return rows.sort(function (a, b) {
        if (order[a.kind] !== order[b.kind]) { return order[a.kind] - order[b.kind]; }
        if ((a.unit || 0) !== (b.unit || 0)) { return (a.unit || 0) - (b.unit || 0); }
        var x = parts(a.uid), y = parts(b.uid);
        for (var i = 0; i < Math.min(x.length, y.length); i++) {
            if (x[i] !== y[i]) { return x[i] - y[i]; }
        }
        return x.length - y.length;
    });
};

// Indexes are numeric strings; a UID is built from them only, so it is always safe for LLD.
HW.indexUid = function (kind, index) {
    return /^[0-9]+(\.[0-9]+)*$/.test(index) ? kind + '-' + index.replace(/\./g, '-') : null;
};
