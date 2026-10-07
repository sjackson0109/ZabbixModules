// IF-MIB / ifXTable / EtherLike-MIB walk -> canonical "interfaces" rows.
// Used by both the inventory walk (all columns) and the fast state walk
// (status and speed columns only); columns absent from a walk become null.

var IF_ADMIN = {1: 'up', 2: 'down', 3: 'testing'};
var IF_OPER = {1: 'up', 2: 'down', 3: 'testing', 4: 'unknown', 5: 'dormant', 6: 'not_present', 7: 'lower_layer_down'};
var IF_LOGICAL_TYPES = {24: true, 53: true, 131: true, 135: true, 136: true, 161: true};

function normaliseInterfaces(walk, env) {
    var t = {}, key;
    for (key in NE.IF) {
        if (NE.IF.hasOwnProperty(key)) { t[key] = NE.table(walk, NE.IF[key]); }
    }
    var uids = NE.interfaceIndex(walk, env);
    var uptime = NE.int(NE.scalar(walk, NE.UPTIME));
    var observed = Date.parse(env.attempted_at);
    var parents = {};
    for (key in t.stack) {
        if (!t.stack.hasOwnProperty(key)) { continue; }
        var pair = key.split('.');
        if (pair.length === 2 && pair[0] !== '0' && pair[1] !== '0' && NE.int(t.stack[key]) === 1) {
            parents[pair[1]] = parents.hasOwnProperty(pair[1]) ? null : pair[0];
        }
    }
    var rows = [], indexes = [];
    for (key in uids) {
        if (uids.hasOwnProperty(key) && /^[0-9]+$/.test(key)) { indexes.push(parseInt(key, 10)); }
    }
    indexes.sort(function (a, b) { return a - b; });
    for (var i = 0; i < indexes.length; i++) {
        var k = String(indexes[i]), uid = uids[k];
        if (uid === null) { continue; }
        var admin = NE.int(t.admin[k] || null), oper = NE.int(t.oper[k] || null);
        var type = NE.int(t.type[k] || null);
        if (!t.descr[k] || !IF_ADMIN[admin] || !IF_OPER[oper]) {
            NE.error(env, 'missing_interface_fields', 'An interface lacks ifDescr, ifAdminStatus or ifOperStatus.');
        }
        var high = NE.int(t.highSpeed[k] || null), speed = NE.int(t.speed[k] || null), bps = null;
        if (high !== null && high > 0) { bps = high * 1000000; }
        else if (speed !== null && speed > 0 && speed < 4294967295) { bps = speed; }
        var connector = NE.int(t.connector[k] || null), physical = null;
        if (connector === 1) { physical = true; }
        else if (connector === 2) { physical = false; }
        else if (type === 6) { physical = true; }
        else if (type !== null && IF_LOGICAL_TYPES[type]) { physical = false; }
        var duplex = NE.int(t.duplex[k] || null);
        var lastChange = null, ticks = NE.int(t.lastChange[k] || null);
        if (ticks !== null && ticks > 0 && uptime !== null && ticks <= uptime) {
            lastChange = new Date(observed - (uptime - ticks) * 10).toISOString();
        }
        var parent = parents[k] ? uids[parents[k]] || null : null;
        rows.push({
            uid: uid, if_index: indexes[i],
            name: NE.text(t.name[k] || null), description: NE.text(t.descr[k] || null),
            alias: NE.text(t.alias[k] || null), type: type, physical: physical,
            admin_status: IF_ADMIN[admin] || null, oper_status: IF_OPER[oper] || null,
            speed_bps: bps, duplex: duplex === 2 ? 'half' : (duplex === 3 ? 'full' : null),
            mtu: NE.int(t.mtu[k] || null), mac_address: NE.mac(t.mac[k] || null),
            last_change: lastChange, stack_parent_uid: parent
        });
    }
    var expected = NE.int(NE.scalar(walk, NE.IF.number));
    if (expected !== null && expected !== indexes.length) {
        NE.error(env, 'interface_count_mismatch', 'ifNumber does not match the number of interface rows walked.');
    }
    if (!indexes.length && expected === null) {
        throw {unsupported: 'The agent returned no IF-MIB interface table.'};
    }
    return rows;
}
