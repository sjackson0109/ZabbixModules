// Shared helpers for Network Explorer SNMP normalisers.
// Runs inside Zabbix JavaScript preprocessing (Duktape, ECMAScript 5.1):
// no let/const, arrow functions, template literals or ES2015+ library calls.
// The global sha256() is provided by Zabbix (and by the Node test harness).

var NE = {};
NE.SCHEMA = '1.1';
NE.VERSION = '1.2.0';  // The root VERSION file; tests/unit/test_native_templates.py checks it.
NE.FAILED = '__NE_COLLECTION_FAILED__';
NE.UPTIME = '1.3.6.1.2.1.1.3.0';

NE.IF = {
    number: '1.3.6.1.2.1.2.1.0',
    descr: '1.3.6.1.2.1.2.2.1.2',
    type: '1.3.6.1.2.1.2.2.1.3',
    mtu: '1.3.6.1.2.1.2.2.1.4',
    speed: '1.3.6.1.2.1.2.2.1.5',
    mac: '1.3.6.1.2.1.2.2.1.6',
    admin: '1.3.6.1.2.1.2.2.1.7',
    oper: '1.3.6.1.2.1.2.2.1.8',
    lastChange: '1.3.6.1.2.1.2.2.1.9',
    name: '1.3.6.1.2.1.31.1.1.1.1',
    highSpeed: '1.3.6.1.2.1.31.1.1.1.15',
    connector: '1.3.6.1.2.1.31.1.1.1.17',
    alias: '1.3.6.1.2.1.31.1.1.1.18',
    stack: '1.3.6.1.2.1.31.1.2.1.3',
    duplex: '1.3.6.1.2.1.10.7.2.1.19',
    // ENTITY-MIB: physical position of each port (stack member, slot, port).
    entContained: '1.3.6.1.2.1.47.1.1.1.1.4',
    entClass: '1.3.6.1.2.1.47.1.1.1.1.5',
    entRelPos: '1.3.6.1.2.1.47.1.1.1.1.6',
    entAlias: '1.3.6.1.2.1.47.1.3.2.1.2'
};
NE.BRIDGE_PORT_IFINDEX = '1.3.6.1.2.1.17.1.4.1.2';

// ---------------------------------------------------------------- parsing

// Parses Zabbix walk[] output: one "OID = TYPE: value" entry per line, numeric
// OIDs and enums, quoted STRING values (which may span lines), and unquoted
// Hex-STRING values (which net-snmp may wrap onto continuation lines).
NE.parseWalk = function (text) {
    var rows = {}, order = [], pos = 0, len = text.length;
    var head = /^\.?([0-9]+(?:\.[0-9]+)*) = (?:([A-Za-z0-9-]+): ?)?/;
    while (pos < len) {
        var eol = text.indexOf('\n', pos);
        if (eol < 0) { eol = len; }
        var line = text.substring(pos, eol);
        var m = head.exec(line);
        if (!m) { pos = eol + 1; continue; }
        var oid = m[1], type = m[2] || 'STRING', start = pos + m[0].length, value;
        if (text.charAt(start) === '"') {
            var i = start + 1, out = '';
            while (i < len && text.charAt(i) !== '"') {
                if (text.charAt(i) === '\\' && i + 1 < len) { i++; }
                out += text.charAt(i);
                i++;
            }
            value = out;
            eol = text.indexOf('\n', i);
            if (eol < 0) { eol = len; }
        }
        else {
            value = text.substring(start, eol);
            // Unquoted continuation lines (wrapped Hex-STRING) until the next OID line.
            while (eol < len) {
                var next = text.indexOf('\n', eol + 1);
                if (next < 0) { next = len; }
                var more = text.substring(eol + 1, next);
                if (more === '' || head.test(more)) { break; }
                value += ' ' + more;
                eol = next;
            }
            value = value.replace(/\s+$/, '');
        }
        if (/^No (Such|more) /.test(value)) { type = 'MISSING'; }
        if (!rows.hasOwnProperty(oid)) { order.push(oid); }
        rows[oid] = {type: type, value: value};
        pos = eol + 1;
    }
    return {rows: rows, order: order};
};

// Returns {suffix: entry} for every row under base (suffix without the dot).
NE.table = function (walk, base) {
    var out = {}, prefix = base + '.', i, oid;
    for (i = 0; i < walk.order.length; i++) {
        oid = walk.order[i];
        if (oid.indexOf(prefix) === 0 && walk.rows[oid].type !== 'MISSING') {
            out[oid.substring(prefix.length)] = walk.rows[oid];
        }
    }
    return out;
};

NE.has = function (walk, base) {
    var prefix = base + '.', i;
    for (i = 0; i < walk.order.length; i++) {
        if (walk.order[i].indexOf(prefix) === 0 && walk.rows[walk.order[i]].type !== 'MISSING') { return true; }
    }
    return false;
};

NE.scalar = function (walk, oid) {
    var row = walk.rows[oid];
    return row && row.type !== 'MISSING' ? row : null;
};

// ---------------------------------------------------------------- values

NE.int = function (entry) {
    if (!entry) { return null; }
    var m = /-?[0-9]+/.exec(entry.value);
    if (!m) { return null; }
    var n = parseInt(m[0], 10);
    return isFinite(n) ? n : null;
};

NE.utf8Encode = function (s) {
    var out = [], i, c;
    for (i = 0; i < s.length; i++) {
        c = s.charCodeAt(i);
        if (c >= 0xd800 && c <= 0xdbff && i + 1 < s.length) {
            c = 0x10000 + ((c - 0xd800) << 10) + (s.charCodeAt(++i) - 0xdc00);
        }
        if (c < 0x80) { out.push(c); }
        else if (c < 0x800) { out.push(0xc0 | (c >> 6), 0x80 | (c & 63)); }
        else if (c < 0x10000) { out.push(0xe0 | (c >> 12), 0x80 | ((c >> 6) & 63), 0x80 | (c & 63)); }
        else { out.push(0xf0 | (c >> 18), 0x80 | ((c >> 12) & 63), 0x80 | ((c >> 6) & 63), 0x80 | (c & 63)); }
    }
    return out;
};

NE.utf8Decode = function (bytes) {
    var out = '', i = 0, c, n, cp;
    while (i < bytes.length) {
        c = bytes[i++];
        if (c < 0x80) { cp = c; n = 0; }
        else if (c >= 0xc2 && c < 0xe0) { cp = c & 31; n = 1; }
        else if (c >= 0xe0 && c < 0xf0) { cp = c & 15; n = 2; }
        else if (c >= 0xf0 && c < 0xf5) { cp = c & 7; n = 3; }
        else { return null; }
        while (n-- > 0) {
            if (i >= bytes.length || (bytes[i] & 0xc0) !== 0x80) { return null; }
            cp = (cp << 6) | (bytes[i++] & 63);
        }
        if (cp >= 0x10000) {
            cp -= 0x10000;
            out += String.fromCharCode(0xd800 + (cp >> 10), 0xdc00 + (cp & 1023));
        }
        else { out += String.fromCharCode(cp); }
    }
    return out;
};

// Raw octets of an OCTET STRING / BITS value, whichever form Zabbix printed.
NE.bytes = function (entry) {
    if (!entry) { return null; }
    var v = entry.value, out = [], parts, i;
    if (entry.type === 'Hex-STRING' || entry.type === 'BITS') {
        parts = v.split(/\s+/);
        for (i = 0; i < parts.length; i++) {
            if (!/^[0-9A-Fa-f]{2}$/.test(parts[i])) { break; }
            out.push(parseInt(parts[i], 16));
        }
        return out;
    }
    // A MacAddress display hint prints "0:1b:2c:..." as a STRING.
    if (/^[0-9A-Fa-f]{1,2}([:-][0-9A-Fa-f]{1,2}){5,}$/.test(v)) {
        parts = v.split(/[:-]/);
        for (i = 0; i < parts.length; i++) { out.push(parseInt(parts[i], 16)); }
        return out;
    }
    // Zabbix prints octets that are valid UTF-8 as a STRING.
    return NE.utf8Encode(v);
};

NE.hex = function (bytes) {
    var out = '', i;
    for (i = 0; i < bytes.length; i++) { out += (bytes[i] < 16 ? '0' : '') + bytes[i].toString(16); }
    return out;
};

NE.text = function (entry) {
    if (!entry) { return null; }
    if (entry.type === 'Hex-STRING') {
        var bytes = NE.bytes(entry), decoded = NE.utf8Decode(bytes);
        return decoded !== null ? decoded.replace(/\u0000+$/, '') : 'hex:' + NE.hex(bytes);
    }
    return entry.value;
};

NE.mac = function (entry) {
    var b = NE.bytes(entry);
    if (!b || b.length !== 6) { return null; }
    var parts = [], i;
    for (i = 0; i < 6; i++) { parts.push((b[i] < 16 ? '0' : '') + b[i].toString(16)); }
    return parts.join(':');
};

// Bits set in an octet string, numbered MSB-first from 0 (SNMP BITS and PortList).
NE.bitsSet = function (bytes, offset) {
    var out = [], i, b;
    if (!bytes) { return out; }
    for (i = 0; i < bytes.length; i++) {
        for (b = 0; b < 8; b++) {
            if (bytes[i] & (0x80 >> b)) { out.push(i * 8 + b + (offset || 0)); }
        }
    }
    return out;
};

NE.ipFromOctets = function (octets) {
    var i, parts = [];
    if (octets.length === 4) { return octets.join('.'); }
    if (octets.length !== 16) { return null; }
    for (i = 0; i < 16; i += 2) { parts.push(((octets[i] << 8) | octets[i + 1]).toString(16)); }
    // RFC 5952: compress the longest run (two or more) of zero groups.
    var best = -1, bestLen = 1, run = 0;
    for (i = 0; i <= 8; i++) {
        if (i < 8 && parts[i] === '0') { run++; continue; }
        if (run > bestLen) { best = i - run; bestLen = run; }
        run = 0;
    }
    if (best < 0) { return parts.join(':'); }
    return parts.slice(0, best).join(':') + '::' + parts.slice(best + bestLen).join(':');
};

// "1,3-5,49"; empty list gives "", null gives null.
NE.ranges = function (ids) {
    if (ids === null) { return null; }
    var sorted = ids.slice().sort(function (a, b) { return a - b; }), out = [], i, start, prev;
    for (i = 0; i < sorted.length; i++) {
        if (i > 0 && sorted[i] === prev) { continue; }
        if (start === undefined) { start = prev = sorted[i]; continue; }
        if (sorted[i] === prev + 1) { prev = sorted[i]; continue; }
        out.push(start === prev ? String(start) : start + '-' + prev);
        start = prev = sorted[i];
    }
    if (start !== undefined) { out.push(start === prev ? String(start) : start + '-' + prev); }
    return out.join(',');
};

// ---------------------------------------------------------------- interfaces

NE.uid = function (name, descr) {
    var basis = null;
    if (name !== null && name !== undefined && name.replace(/^\s+|\s+$/g, '') !== '') {
        basis = 'name:' + name.replace(/^\s+|\s+$/g, '');
    }
    else if (descr !== null && descr !== undefined && descr.replace(/^\s+|\s+$/g, '') !== '') {
        basis = 'description:' + descr.replace(/^\s+|\s+$/g, '');
    }
    return basis === null ? null : 'if-' + sha256(basis).substring(0, 24);
};

// {ifIndex: uid} from the ifName/ifDescr join columns every dataset walks.
// Duplicate or missing identities map to null, so those rows are dropped.
// They are reported as a warning unless quiet is set, for datasets that only
// join to interfaces.
NE.interfaceIndex = function (walk, env, quiet) {
    var names = NE.table(walk, NE.IF.name), descrs = NE.table(walk, NE.IF.descr);
    var out = {}, seen = {}, k, uid;
    for (k in descrs) { if (descrs.hasOwnProperty(k)) { out[k] = null; } }
    for (k in names) { if (names.hasOwnProperty(k)) { out[k] = null; } }
    for (k in out) {
        if (!out.hasOwnProperty(k)) { continue; }
        uid = NE.uid(NE.text(names[k] || null), NE.text(descrs[k] || null));
        out[k] = uid;
        if (uid !== null) { seen[uid] = (seen[uid] || 0) + 1; }
    }
    for (k in out) {
        if (out.hasOwnProperty(k) && (out[k] === null || seen[out[k]] > 1)) {
            out[k] = null;
            if (!quiet) { NE.warning(env, 'identity_ambiguous', 'An interface name is missing or duplicated; that interface is skipped.'); }
        }
    }
    return out;
};

// ---------------------------------------------------------------- LLDP identifiers

// Chassis subtype 4 / port subtype 3 are MAC; chassis 5 / port 4 are network addresses.
NE.lldpId = function (subtypeEntry, valueEntry, kind) {
    var subtype = NE.int(subtypeEntry), macType = kind === 'chassis' ? 4 : 3;
    var netType = kind === 'chassis' ? 5 : 4, value = null, bytes;
    if (subtype === macType) { value = NE.mac(valueEntry); }
    else if (subtype === netType) {
        bytes = NE.bytes(valueEntry);
        if (bytes && bytes.length > 1 && (bytes[0] === 1 || bytes[0] === 2)) { value = NE.ipFromOctets(bytes.slice(1)); }
    }
    if (value === null && valueEntry) { value = NE.text(valueEntry); }
    return {subtype: subtype !== null && subtype >= 1 && subtype <= 7 ? subtype : null, value: value || ''};
};

// ---------------------------------------------------------------- MAU / speeds

// IANA-MAU-MIB dot3MauType arc -> [speed bit/s, duplex, media]. The same
// numbers are the IANAifMauTypeListBits positions.
// From 40G up (IANA-MAU-MIB revision 2017-04-10):
//   70 dot3MauType40GbaseKR4, 71 40GbaseCR4, 72 40GbaseSR4, 73 40GbaseFR,
//   74 40GbaseLR4, 75 100GbaseCR10, 76 100GbaseSR10, 77 100GbaseLR4,
//   78 100GbaseER4, 88 25GbaseCR, 89 25GbaseCRS, 90 25GbaseKR, 91 25GbaseKRS,
//   92 25GbaseR, 93 25GbaseSR, 94 25GbaseT, 95 40GbaseER4, 96 40GbaseR,
//   97 40GbaseT, 98 100GbaseCR4, 99 100GbaseKR4, 100 100GbaseKP4,
//   101 100GbaseR, 102 100GbaseSR4.
// That revision defines no 2.5G, 5G or 50G types. Media is null for 25G/40G/
// 100G MAUs other than BASE-T: the port_capability media enum has no SFP28 or
// QSFP value, and a backplane or undefined PMD names no cage.
NE.MAU = {
    5: [10e6, null, 'copper'], 10: [10e6, 'half', 'copper'], 11: [10e6, 'full', 'copper'],
    14: [100e6, 'half', 'copper'], 15: [100e6, 'half', 'copper'], 16: [100e6, 'full', 'copper'],
    17: [100e6, 'half', 'sfp'], 18: [100e6, 'full', 'sfp'], 19: [100e6, 'half', 'copper'], 20: [100e6, 'full', 'copper'],
    21: [1e9, 'half', 'sfp'], 22: [1e9, 'full', 'sfp'], 23: [1e9, 'half', 'sfp'], 24: [1e9, 'full', 'sfp'],
    25: [1e9, 'half', 'sfp'], 26: [1e9, 'full', 'sfp'], 27: [1e9, 'half', 'copper'], 28: [1e9, 'full', 'copper'],
    29: [1e9, 'half', 'copper'], 30: [1e9, 'full', 'copper'],
    31: [10e9, 'full', 'sfp_plus'], 32: [10e9, 'full', 'sfp_plus'], 33: [10e9, 'full', 'sfp_plus'],
    34: [10e9, 'full', 'sfp_plus'], 35: [10e9, 'full', 'sfp_plus'], 36: [10e9, 'full', 'sfp_plus'],
    41: [10e9, 'full', 'copper'], 44: [100e6, 'full', 'sfp'], 45: [100e6, 'full', 'sfp'], 46: [100e6, 'full', 'sfp'],
    47: [1e9, 'full', 'sfp'], 48: [1e9, 'full', 'sfp'], 49: [1e9, 'full', 'sfp'],
    54: [10e9, 'full', 'copper'], 55: [10e9, 'full', 'sfp_plus'],
    70: [40e9, 'full', null], 71: [40e9, 'full', null], 72: [40e9, 'full', null], 73: [40e9, 'full', null],
    74: [40e9, 'full', null], 75: [100e9, 'full', null], 76: [100e9, 'full', null], 77: [100e9, 'full', null],
    78: [100e9, 'full', null],
    88: [25e9, 'full', null], 89: [25e9, 'full', null], 90: [25e9, 'full', null], 91: [25e9, 'full', null],
    92: [25e9, 'full', null], 93: [25e9, 'full', null], 94: [25e9, 'full', 'copper'],
    95: [40e9, 'full', null], 96: [40e9, 'full', null], 97: [40e9, 'full', 'copper'],
    98: [100e9, 'full', null], 99: [100e9, 'full', null], 100: [100e9, 'full', null], 101: [100e9, 'full', null],
    102: [100e9, 'full', null]
};

NE.mauArc = function (entry) {
    if (!entry) { return null; }
    var m = /([0-9]+)$/.exec(entry.value);
    return m ? parseInt(m[1], 10) : null;
};

// Autonegotiation capability bits (ifMauAutoNegCapAdvertisedBits and the
// LLDP 802.3 extension) -> distinct speeds in bit/s.
NE.AUTONEG_SPEED = {1: 10e6, 2: 10e6, 3: 100e6, 4: 100e6, 5: 100e6, 6: 100e6, 7: 100e6,
                    12: 1e9, 13: 1e9, 14: 1e9, 15: 1e9};

NE.speedsFromBits = function (bits, table) {
    var seen = {}, out = [], i, s;
    for (i = 0; i < bits.length; i++) {
        s = table === 'mau' ? (NE.MAU[bits[i]] ? NE.MAU[bits[i]][0] : null) : NE.AUTONEG_SPEED[bits[i]];
        if (s && !seen[s]) { seen[s] = true; out.push(s); }
    }
    return out.sort(function (a, b) { return a - b; });
};

// ---------------------------------------------------------------- envelope

NE.error = function (env, code, message) { NE.note(env.errors, code, message); };

// A problem confined to one row: the row is dropped or kept with unknown
// fields, and the rest of the dataset stays a complete observation.
NE.warning = function (env, code, message) { NE.note(env.warnings, code, message); };

NE.note = function (list, code, message) {
    for (var i = 0; i < list.length; i++) {
        if (list[i].code === code) { return; }
    }
    if (list.length < 256) { list.push({code: code, message: message}); }
};

NE.envelope = function (dataset, adapter) {
    var now = new Date().toISOString();
    return {
        schema_version: NE.SCHEMA, dataset: dataset,
        generation_id: dataset + '-' + now.replace(/[^0-9]/g, '') + '-' + Math.floor(Math.random() * 1e9),
        attempted_at: now, observed_at: null, status: 'failed', complete: false,
        source: {method: 'native_snmp', adapter: adapter, version: NE.VERSION},
        capability: {state: 'unknown', reason: null}, errors: [], warnings: [], data: []
    };
};

// Runs a dataset normaliser and sets status/completeness consistently.
//   normalise(walk, env) returns rows, or throws {unsupported: reason}.
//   Any error recorded on env makes the result partial.
NE.run = function (dataset, adapter, value, normalise) {
    var env = NE.envelope(dataset, adapter);
    if (value === NE.FAILED || value === '' || value === null || value === undefined) {
        NE.error(env, 'collection_failed', 'The SNMP walk returned no data or the item is not supported.');
        return env;
    }
    var walk, rows;
    try {
        walk = NE.parseWalk(String(value));
        if (!NE.scalar(walk, NE.UPTIME)) {
            NE.error(env, 'agent_unreachable', 'The walk did not include sysUpTime; the agent did not answer.');
            return env;
        }
        rows = normalise(walk, env);
    }
    catch (e) {
        if (e && e.unsupported) {
            env.status = 'unsupported';
            env.capability = {state: 'unsupported', reason: e.unsupported};
            env.errors = [{code: 'unsupported', message: e.unsupported}];
            env.warnings = [];
            return env;
        }
        // A normaliser bug still records a failed attempt rather than no
        // envelope at all. The message is fixed: an exception can quote
        // device data.
        env.errors = [{code: 'normaliser_error', message: 'The normaliser failed on this walk; nothing was observed.'}];
        env.warnings = [];
        return env;
    }
    env.observed_at = env.attempted_at;
    env.data = rows;
    if (env.errors.length) {
        env.status = 'partial';
        env.capability = {state: 'partial', reason: env.errors[0].message};
    }
    else {
        env.status = 'ok';
        env.complete = true;
        env.capability = {state: 'supported', reason: null};
    }
    return env;
};
