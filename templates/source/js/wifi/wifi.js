// Shared helpers for Wi-Fi Explorer normalisers, composed after lib.js.
// Same engine rules as lib.js: Duktape, ECMAScript 5.1 only.
//
// Wi-Fi envelopes keep Network Explorer's envelope semantics (status, completeness, attempt and observation
// time, errors and warnings) and only change the schema version, so a Network Explorer reader rejects a Wi-Fi
// envelope as an unsupported schema and the reverse.

var WE = {};
WE.SCHEMA = 'wifi-1.0';

// Runs a Wi-Fi normaliser through NE.run. A normaliser may throw {unsupported: reason, code: 'stable_code'};
// the code replaces the generic 'unsupported' error code so the frontend can say what to change.
WE.run = function (dataset, adapter, value, normalise) {
    var code = null;
    var env = NE.run(dataset, adapter, value, function (w, e) {
        try {
            return normalise(w, e);
        }
        catch (x) {
            if (x && x.unsupported && typeof x.code === 'string') { code = x.code; }
            throw x;
        }
    });
    env.schema_version = WE.SCHEMA;
    if (env.status === 'unsupported' && code !== null) { env.errors[0].code = code; }
    return env;
};

// Opaque identities: stable across adapters for the same hardware, safe in URLs, never a raw MAC.
WE.apUid = function (mac) { return 'ap-' + sha256('ap:' + mac).substring(0, 24); };
WE.radioUid = function (mac, index) { return 'radio-' + sha256('radio:' + mac + ':' + index).substring(0, 24); };

WE.blank = function (s) { return s === null || s === undefined || String(s).replace(/\s+/g, '') === '' ? null : String(s); };

WE.ipv4 = function (entry) {
    var v = entry ? String(entry.value).replace(/^\s+|\s+$/g, '') : '';
    var m = /^([0-9]{1,3})\.([0-9]{1,3})\.([0-9]{1,3})\.([0-9]{1,3})$/.exec(v);
    if (!m) { return null; }
    for (var i = 1; i <= 4; i++) {
        if (parseInt(m[i], 10) > 255) { return null; }
    }
    return v === '0.0.0.0' ? null : v;
};

// A MAC from OID index arcs (six decimal octets).
WE.macFromArcs = function (arcs) {
    if (arcs.length !== 6) { return null; }
    var parts = [], i, n;
    for (i = 0; i < 6; i++) {
        n = parseInt(arcs[i], 10);
        if (!(n >= 0 && n <= 255)) { return null; }
        parts.push((n < 16 ? '0' : '') + n.toString(16));
    }
    return parts.join(':');
};

// Integer within [min, max], else null (an out-of-range value is unknown, not clamped).
WE.bounded = function (entry, min, max) {
    var n = NE.int(entry);
    return n !== null && n >= min && n <= max ? n : null;
};

// Rows sorted by a key list, for deterministic output.
WE.sort = function (rows, keys) {
    return rows.sort(function (a, b) {
        for (var i = 0; i < keys.length; i++) {
            var x = a[keys[i]], y = b[keys[i]];
            if (x === y) { continue; }
            if (x === null) { return 1; }
            if (y === null) { return -1; }
            return x < y ? -1 : 1;
        }
        return 0;
    });
};
