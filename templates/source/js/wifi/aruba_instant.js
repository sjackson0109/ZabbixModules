// Aruba Instant (AI-AP-MIB, 1.3.6.1.4.1.14823.2.3.3) -> canonical Wi-Fi datasets.
//
// Evidence: the operator's Aruba Wireless template notes (live walks of five Instant APs in two clusters,
// firmware 8.13.2.0 and 6.5.4.11); see docs/wifi-explorer/ARUBA_TEMPLATE_REVIEW.md. aiAccessPointTable and
// aiRadioTable are populated only on the elected virtual controller (VC) and empty on members, and
// aiVirtualControllerIPAddress reads 0.0.0.0 on members. Every AP and radio dataset therefore requires the VC
// role, so a member host never reports an empty site.

var ARUBA = {};
ARUBA.ENTERPRISE = '1.3.6.1.4.1.14823';
ARUBA.VERSION = '1.3.6.1.4.1.14823.2.3.3.1.1.4.0';     // aiControllerVersion (populated on the VC)
ARUBA.VC_IP = '1.3.6.1.4.1.14823.2.3.3.1.1.5.0';       // aiVirtualControllerIPAddress
ARUBA.AP = '1.3.6.1.4.1.14823.2.3.3.1.2.1.1';          // aiAccessPointEntry, indexed by AP MAC
ARUBA.RADIO = '1.3.6.1.4.1.14823.2.3.3.1.2.2.1';       // aiRadioEntry, indexed by AP MAC and radio index
ARUBA.AP_COL = {mac: 1, name: 2, ip: 3, serial: 4, model: 6, cpu: 7, memFree: 8, uptime: 9, memTotal: 10, status: 11};
ARUBA.RADIO_COL = {apMac: 1, index: 2, bssid: 3, channel: 4, txPower: 5, noise: 6, util64: 8, status: 20};
ARUBA.STATUS = {1: 'up', 2: 'down'};

// The role gate. Throws unsupported unless this agent is the elected VC.
ARUBA.requireVc = function (walk) {
    var entry = NE.scalar(walk, ARUBA.VC_IP);
    if (!entry) {
        throw {unsupported: 'The agent does not expose AI-AP-MIB aiVirtualControllerIPAddress; this is not an Aruba Instant AP.',
               code: 'not_aruba_instant'};
    }
    if (WE.ipv4(entry) === null) {
        throw {unsupported: 'This AP is not the elected virtual controller. Only the VC (or the cluster\'s floating AVC address) lists the cluster\'s APs and radios; link this template to the AVC host.',
               code: 'not_virtual_controller'};
    }
};

// {suffix: {column: entry}} for one table, from the columns present in the walk.
ARUBA.rows = function (walk, base, columns) {
    var out = {}, name, col, cells, suffix;
    for (name in columns) {
        if (!columns.hasOwnProperty(name)) { continue; }
        col = columns[name];
        cells = NE.table(walk, base + '.' + col);
        for (suffix in cells) {
            if (!cells.hasOwnProperty(suffix)) { continue; }
            if (!out.hasOwnProperty(suffix)) { out[suffix] = {}; }
            out[suffix][name] = cells[suffix];
        }
    }
    return out;
};

// The AP MAC of an aiAccessPointTable row: the MAC column, else the six index arcs.
ARUBA.apMac = function (row, suffix) {
    return (row.mac ? NE.mac(row.mac) : null) || WE.macFromArcs(suffix.split('.'));
};

// The owning AP MAC and radio index of an aiRadioTable row (index: six MAC arcs, then the radio index).
ARUBA.radioId = function (row, suffix) {
    var arcs = suffix.split('.');
    var mac = (row.apMac ? NE.mac(row.apMac) : null) || WE.macFromArcs(arcs.slice(0, 6));
    var index = row.index ? NE.int(row.index) : (arcs.length === 7 ? parseInt(arcs[6], 10) : null);
    return {mac: mac, index: index !== null && index >= 0 && index <= 255 ? index : null};
};

// aiRadioChannel: the first byte is the primary channel; two bits of the second byte are the bonding indicator
// (0 = 20 MHz, 1 = secondary above, 2 = secondary below, 3 = every width above 40 MHz). 80, 80+80 and 160 MHz
// cannot be told apart, so the widest class is '80+'.
ARUBA.channel = function (entry) {
    var v = NE.int(entry);
    if (v === null || v < 0) { return {channel: null, width: null}; }
    var channel = v & 0xFF, bits = (v >> 8) & 3;
    if (channel === 0) { return {channel: null, width: null}; }
    return {channel: channel, width: bits === 0 ? '20' : bits === 3 ? '80+' : '40'};
};

// Band from the decoded channel. 6 GHz channel numbers (1 to 233) overlap 2.4 GHz (1 to 14) and 5 GHz (36 to
// 177), so only channels above 177 prove 6 GHz. On dual-radio APs the sampled fleet put 5 GHz on radio 0 and
// 2.4 GHz on radio 1; an AP with three or more radios may carry 6 GHz on a channel below 178, so its radios get a
// band only when the channel proves one.
ARUBA.band = function (channel, radiosOnAp) {
    if (channel === null) { return null; }
    if (channel >= 178 && channel <= 233) { return '6'; }
    if (radiosOnAp >= 3) { return null; }
    if (channel >= 1 && channel <= 14) { return '2.4'; }
    if (channel >= 32 && channel <= 177) { return '5'; }
    return null;
};

ARUBA.device = function (walk, env) {
    var vc = NE.scalar(walk, ARUBA.VC_IP);
    if (!vc) {
        throw {unsupported: 'The agent does not expose AI-AP-MIB aiVirtualControllerIPAddress; this is not an Aruba Instant AP.',
               code: 'not_aruba_instant'};
    }
    var address = WE.ipv4(vc);
    var oidEntry = NE.scalar(walk, '1.3.6.1.2.1.1.2.0');
    var objectId = oidEntry ? oidEntry.value.replace(/^\./, '') : null;
    if (objectId !== null && !/^[0-9]+(\.[0-9]+)*$/.test(objectId)) { objectId = null; }
    var descr = WE.blank(NE.text(NE.scalar(walk, '1.3.6.1.2.1.1.1.0')));
    var uptime = NE.int(NE.scalar(walk, NE.UPTIME));
    return [{
        hostname: WE.blank(NE.text(NE.scalar(walk, '1.3.6.1.2.1.1.5.0'))),
        description: descr === null ? null : descr.substring(0, 1024),
        sys_object_id: objectId,
        vendor: objectId !== null && objectId.indexOf(ARUBA.ENTERPRISE + '.') === 0 ? 'Aruba' : null,
        platform: 'aruba_instant',
        role: address !== null ? 'virtual_controller' : 'member',
        controller_address: address,
        // The cluster firmware: aiControllerVersion is populated only on the VC.
        firmware: address !== null ? WE.blank(NE.text(NE.scalar(walk, ARUBA.VERSION))) : null,
        uptime_s: uptime === null ? null : Math.floor(uptime / 100)
    }];
};

ARUBA.apInventory = function (walk, env) {
    ARUBA.requireVc(walk);
    var table = ARUBA.rows(walk, ARUBA.AP, {mac: 1, name: 2, ip: 3, serial: 4, model: 6});
    var out = [], seen = {}, suffix, row, mac;
    for (suffix in table) {
        if (!table.hasOwnProperty(suffix)) { continue; }
        row = table[suffix];
        mac = ARUBA.apMac(row, suffix);
        if (mac === null) {
            NE.warning(env, 'ap_identity_missing', 'An AP row had no readable MAC address and was dropped.');
            continue;
        }
        if (seen.hasOwnProperty(mac)) {
            NE.warning(env, 'ap_identity_duplicate', 'Two AP rows had the same MAC address; both were dropped.');
            seen[mac].drop = true;
            continue;
        }
        seen[mac] = {
            ap_uid: WE.apUid(mac), mac_address: mac,
            name: WE.blank(NE.text(row.name || null)),
            ip_address: row.ip ? WE.ipv4(row.ip) : null,
            serial: WE.blank(NE.text(row.serial || null)),
            model: WE.blank(NE.text(row.model || null)),
            // AI-AP-MIB has no per-AP firmware column in the walked table; the cluster firmware is on the device.
            firmware: null
        };
        out.push(seen[mac]);
    }
    out = out.filter(function (r) { return !r.drop; });
    return WE.sort(out, ['name', 'mac_address']);
};

ARUBA.apState = function (walk, env) {
    ARUBA.requireVc(walk);
    var table = ARUBA.rows(walk, ARUBA.AP, {mac: 1, cpu: 7, memFree: 8, uptime: 9, memTotal: 10, status: 11});
    var out = [], seen = {}, suffix, row, mac, free, total, ticks, used;
    for (suffix in table) {
        if (!table.hasOwnProperty(suffix)) { continue; }
        row = table[suffix];
        mac = ARUBA.apMac(row, suffix);
        if (mac === null || seen.hasOwnProperty(mac)) {
            NE.warning(env, mac === null ? 'ap_identity_missing' : 'ap_identity_duplicate',
                'An AP state row had no unique MAC address and was dropped.');
            if (mac !== null) { seen[mac].drop = true; }
            continue;
        }
        free = NE.int(row.memFree || null);
        total = NE.int(row.memTotal || null);
        // Memory units are not stated by the MIB description the evidence cites; only the ratio is reported.
        used = free !== null && total !== null && total > 0 && free >= 0 && free <= total
            ? Math.round((total - free) * 1000 / total) / 10 : null;
        ticks = NE.int(row.uptime || null);
        seen[mac] = {
            ap_uid: WE.apUid(mac),
            status: ARUBA.STATUS[NE.int(row.status || null)] || 'unknown',
            uptime_s: ticks === null || ticks < 0 ? null : Math.floor(ticks / 100),
            cpu_percent: WE.bounded(row.cpu || null, 0, 100),
            memory_used_percent: used
        };
        out.push(seen[mac]);
    }
    out = out.filter(function (r) { return !r.drop; });
    return WE.sort(out, ['ap_uid']);
};

ARUBA.radioRows = function (walk, env, columns) {
    var table = ARUBA.rows(walk, ARUBA.RADIO, columns);
    var out = [], seen = {}, perAp = {}, suffix, id, key;
    for (suffix in table) {
        if (!table.hasOwnProperty(suffix)) { continue; }
        id = ARUBA.radioId(table[suffix], suffix);
        if (id.mac === null || id.index === null) {
            NE.warning(env, 'radio_identity_missing', 'A radio row had no readable AP MAC address or radio index and was dropped.');
            continue;
        }
        key = id.mac + '/' + id.index;
        if (seen.hasOwnProperty(key)) {
            NE.warning(env, 'radio_identity_duplicate', 'Two radio rows had the same AP and radio index; both were dropped.');
            seen[key].drop = true;
            continue;
        }
        seen[key] = {mac: id.mac, index: id.index, row: table[suffix]};
        out.push(seen[key]);
        perAp[id.mac] = (perAp[id.mac] || 0) + 1;
    }
    out = out.filter(function (r) { return !r.drop; });
    return {rows: out, perAp: perAp};
};

ARUBA.radioInventory = function (walk, env) {
    ARUBA.requireVc(walk);
    var radios = ARUBA.radioRows(walk, env, {apMac: 1, index: 2, bssid: 3}).rows, out = [], i, r;
    for (i = 0; i < radios.length; i++) {
        r = radios[i];
        out.push({radio_uid: WE.radioUid(r.mac, r.index), ap_uid: WE.apUid(r.mac), radio_index: r.index,
                  bssid: r.row.bssid ? NE.mac(r.row.bssid) : null});
    }
    return WE.sort(out, ['ap_uid', 'radio_index']);
};

ARUBA.radioState = function (walk, env) {
    ARUBA.requireVc(walk);
    var found = ARUBA.radioRows(walk, env, {apMac: 1, index: 2, channel: 4, txPower: 5, noise: 6, util64: 8, status: 20});
    var out = [], i, r, ch, band, noise, power;
    for (i = 0; i < found.rows.length; i++) {
        r = found.rows[i];
        ch = ARUBA.channel(r.row.channel || null);
        band = ARUBA.band(ch.channel, found.perAp[r.mac]);
        if (ch.channel !== null && band === null) {
            NE.warning(env, 'radio_band_ambiguous',
                'A radio channel number does not prove its band (6 GHz channel numbers overlap 2.4 and 5 GHz); its band is unknown.');
        }
        noise = WE.bounded(r.row.noise || null, 1, 130);   // A positive magnitude: 94 means -94 dBm.
        power = WE.bounded(r.row.txPower || null, 0, 40);
        out.push({
            radio_uid: WE.radioUid(r.mac, r.index), ap_uid: WE.apUid(r.mac),
            status: ARUBA.STATUS[NE.int(r.row.status || null)] || 'unknown',
            band: band, channel: ch.channel, channel_width: ch.width,
            tx_power_dbm: power, noise_floor_dbm: noise === null ? null : -noise,
            utilisation_percent: WE.bounded(r.row.util64 || null, 0, 100), utilisation_window_s: 64
        });
    }
    return WE.sort(out, ['ap_uid', 'radio_uid']);
};
