// MAU-MIB walk -> canonical "port_capability" rows, used to derive expected
// speed. Rows are indexed by ifIndex.mauIndex; the first MAU of each
// interface is used. Column numbers follow RFC 4836.

var MAU = {
    type: '1.3.6.1.2.1.26.2.1.1.3',
    typeListBits: '1.3.6.1.2.1.26.2.1.1.13',
    autoNegAdmin: '1.3.6.1.2.1.26.5.1.1.1',
    capAdvertised: '1.3.6.1.2.1.26.5.1.1.10',
    capReceived: '1.3.6.1.2.1.26.5.1.1.11'
};

function firstMau(column) {
    var out = {}, k, p;
    for (k in column) {
        if (!column.hasOwnProperty(k)) { continue; }
        p = k.split('.');
        if (p.length === 2 && (!out.hasOwnProperty(p[0]) || parseInt(p[1], 10) < out[p[0]].mau)) {
            out[p[0]] = {mau: parseInt(p[1], 10), entry: column[k]};
        }
    }
    return out;
}

function normalisePortCapability(walk, env) {
    if (!NE.has(walk, '1.3.6.1.2.1.26.2.1.1') && !NE.has(walk, '1.3.6.1.2.1.26.5.1.1')) {
        throw {unsupported: 'The agent returned no MAU-MIB interface tables.'};
    }
    var uids = NE.interfaceIndex(walk, env, true), t = {}, key;
    for (key in MAU) {
        if (MAU.hasOwnProperty(key)) { t[key] = firstMau(NE.table(walk, MAU[key])); }
    }
    var indexes = {};
    for (key in t) {
        if (!t.hasOwnProperty(key)) { continue; }
        for (var k in t[key]) { if (t[key].hasOwnProperty(k)) { indexes[k] = true; } }
    }
    var list = Object.keys(indexes).map(function (x) { return parseInt(x, 10); }).sort(function (a, b) { return a - b; });
    var rows = [];
    for (var i = 0; i < list.length; i++) {
        var ix = String(list[i]), uid = uids[ix] || null;
        if (uid === null) { continue; }
        var get = function (col) { return t[col][ix] ? t[col][ix].entry : null; };
        var arc = NE.mauArc(get('type')), mau = arc !== null ? NE.MAU[arc] || null : null;
        var admin = NE.int(get('autoNegAdmin'));
        var typeBits = get('typeListBits'), adv = get('capAdvertised'), rec = get('capReceived');
        rows.push({
            uid: uid, if_index: list[i],
            autoneg_enabled: admin === 1 ? true : (admin === 2 ? false : null),
            oper_mau_type: get('type') ? get('type').value.replace(/^\./, '') : null,
            oper_speed_bps: mau ? mau[0] : null, oper_duplex: mau ? mau[1] : null,
            supported_speeds_bps: typeBits ? NE.speedsFromBits(NE.bitsSet(NE.bytes(typeBits)), 'mau') : null,
            advertised_speeds_bps: adv ? NE.speedsFromBits(NE.bitsSet(NE.bytes(adv)), 'autoneg') : null,
            partner_advertised_speeds_bps: rec ? NE.speedsFromBits(NE.bitsSet(NE.bytes(rec)), 'autoneg') : null
        });
    }
    return rows;
}
