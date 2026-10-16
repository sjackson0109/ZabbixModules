// Generic access point (standard MIBs only) -> canonical Wi-Fi datasets.
//
// The vendor-neutral Wi-Fi template, the counterpart of Network Explorer - Generic Switch. It is linked to one host
// per AP, at the AP's own address, and reads only standard MIBs:
//   SNMPv2-MIB system group     device identity
//   IF-MIB ifTable              the AP's identity (its lowest-numbered Ethernet MAC), radio and SSID interface state
//   IEEE802dot11-MIB            (1.2.840.10036) radios, channel, transmit power, BSSID and SSID
//   ENTITY-MIB chassis entity   model, serial number and firmware
//   HOST-RESOURCES-MIB          CPU load and memory use
//   IP-MIB ipAddrTable          the AP's address, when it has exactly one
// No standard MIB lists associated clients, measured channel utilisation, noise floor or RF neighbours, so this
// template has no client or rf_neighbour dataset and those radio fields stay null. A vendor template adds them.
//
// A radio is an interface with a dot11PHYType row. An agent without the IEEE 802.11 MIB is not treated as an AP:
// every dataset reports unsupported (not_wifi_ap) instead of inventing one.

var GAP = {};
GAP.PHY_TYPE = '1.2.840.10036.4.1.1.1';        // dot11PHYType, indexed by ifIndex
GAP.MAC = '1.2.840.10036.2.1.1.1';             // dot11MACAddress (the radio's BSSID)
GAP.SSID = '1.2.840.10036.1.1.1.9';            // dot11DesiredSSID
GAP.TX_POWER = '1.2.840.10036.4.3.1';          // dot11PhyTxPowerEntry: .2-.9 levels 1-8 in mW, .10 the current level
GAP.DSSS_CHANNEL = '1.2.840.10036.4.5.1.1';    // dot11CurrentChannel (2.4 GHz PHYs)
GAP.OFDM_CHANNEL = '1.2.840.10036.4.11.1.1';   // dot11CurrentFrequency: the OFDM channel number
GAP.IF_TYPE = '1.3.6.1.2.1.2.2.1.3';
GAP.IF_MAC = '1.3.6.1.2.1.2.2.1.6';
GAP.IF_ADMIN = '1.3.6.1.2.1.2.2.1.7';
GAP.IF_OPER = '1.3.6.1.2.1.2.2.1.8';
GAP.ENT_CLASS = '1.3.6.1.2.1.47.1.1.1.1.5';
GAP.ENT = {firmware: '1.3.6.1.2.1.47.1.1.1.1.10', serial: '1.3.6.1.2.1.47.1.1.1.1.11', model: '1.3.6.1.2.1.47.1.1.1.1.13'};
GAP.HR_UPTIME = '1.3.6.1.2.1.25.1.1.0';
GAP.HR_LOAD = '1.3.6.1.2.1.25.3.3.1.2';
GAP.HR_STORAGE = '1.3.6.1.2.1.25.2.3.1';      // .2 type, .5 size, .6 used
GAP.HR_RAM = '1.3.6.1.2.1.25.2.1.2';
GAP.IP_ADDR = '1.3.6.1.2.1.4.20.1.1';
GAP.STATUS = {1: 'up', 2: 'down'};
// PHYs that exist only at 2.4 GHz: dsss(2), hrdsss(5) and erp(6). Every other PHY type leaves the band to the channel.
GAP.PHY_24 = {2: true, 5: true, 6: true};

// The role gate: only an agent with the IEEE 802.11 MIB is an AP to this template.
GAP.requireAp = function (walk) {
    if (!NE.has(walk, GAP.PHY_TYPE)) {
        throw {unsupported: 'The agent does not expose the IEEE 802.11 MIB (dot11PHYType), so it is not read as an access point. Link a vendor Wi-Fi template instead.',
               code: 'not_wifi_ap'};
    }
};

// ifIndex => entry for one column, keeping only single-arc (ifIndex) suffixes.
GAP.column = function (walk, base) {
    var cells = NE.table(walk, base), out = {}, suffix;
    for (suffix in cells) {
        if (cells.hasOwnProperty(suffix) && /^[0-9]+$/.test(suffix)) { out[suffix] = cells[suffix]; }
    }
    return out;
};

GAP.indexes = function (cells) {
    var out = [], suffix;
    for (suffix in cells) {
        if (cells.hasOwnProperty(suffix)) { out.push(parseInt(suffix, 10)); }
    }
    return out.sort(function (a, b) { return a - b; });
};

// The AP's identity: the MAC of its lowest-numbered Ethernet interface (ifType 6), the base MAC on most APs and the
// chassis ID its switch sees over LLDP. Radio MACs are never used: they are BSSIDs, not the AP.
GAP.apMac = function (walk) {
    var types = GAP.column(walk, GAP.IF_TYPE), macs = GAP.column(walk, GAP.IF_MAC), list = GAP.indexes(types), i, mac;
    for (i = 0; i < list.length; i++) {
        if (NE.int(types[list[i]]) !== 6 || !macs.hasOwnProperty(list[i])) { continue; }
        mac = NE.mac(macs[list[i]]);
        if (mac !== null && mac !== '00:00:00:00:00:00' && mac !== 'ff:ff:ff:ff:ff:ff') { return mac; }
    }
    return null;
};

// The AP MAC or an error: with no identity there is no AP row, and the observation is incomplete, not empty.
GAP.identity = function (walk, env) {
    var mac = GAP.apMac(walk);
    if (mac === null) {
        NE.error(env, 'ap_identity_missing', 'No Ethernet interface with a readable MAC address; the AP cannot be identified.');
    }
    return mac;
};

// The first chassis entity (entPhysicalClass 3) by index, as {firmware, serial, model}; nulls when there is none.
GAP.chassis = function (walk) {
    var classes = GAP.column(walk, GAP.ENT_CLASS), list = GAP.indexes(classes), out = {}, i, name, entry;
    for (name in GAP.ENT) {
        if (GAP.ENT.hasOwnProperty(name)) { out[name] = null; }
    }
    for (i = 0; i < list.length; i++) {
        if (NE.int(classes[list[i]]) !== 3) { continue; }
        for (name in GAP.ENT) {
            if (!GAP.ENT.hasOwnProperty(name)) { continue; }
            entry = NE.scalar(walk, GAP.ENT[name] + '.' + list[i]);
            out[name] = WE.blank(NE.text(entry));
            if (out[name] !== null) { out[name] = out[name].substring(0, 128); }
        }
        break;
    }
    return out;
};

// The AP's IPv4 address when ipAddrTable holds exactly one usable one; several (or none) leave it unknown.
GAP.address = function (walk) {
    var cells = NE.table(walk, GAP.IP_ADDR), found = {}, list = [], suffix, ip;
    for (suffix in cells) {
        if (!cells.hasOwnProperty(suffix)) { continue; }
        ip = WE.ipv4(cells[suffix]);
        if (ip !== null && ip.indexOf('127.') !== 0 && !found.hasOwnProperty(ip)) {
            found[ip] = true;
            list.push(ip);
        }
    }
    return list.length === 1 ? list[0] : null;
};

GAP.device = function (walk, env) {
    GAP.requireAp(walk);
    var oidEntry = NE.scalar(walk, '1.3.6.1.2.1.1.2.0');
    var objectId = oidEntry ? oidEntry.value.replace(/^\./, '') : null;
    if (objectId !== null && !/^[0-9]+(\.[0-9]+)*$/.test(objectId)) { objectId = null; }
    var descr = WE.blank(NE.text(NE.scalar(walk, '1.3.6.1.2.1.1.1.0')));
    var uptime = NE.int(NE.scalar(walk, NE.UPTIME));
    return [{
        hostname: WE.blank(NE.text(NE.scalar(walk, '1.3.6.1.2.1.1.5.0'))),
        description: descr === null ? null : descr.substring(0, 1024),
        sys_object_id: objectId,
        // No standard object names the vendor; the enterprise number is in sys_object_id.
        vendor: null,
        platform: 'generic_ap',
        role: 'standalone',
        controller_address: null,
        firmware: GAP.chassis(walk).firmware,
        uptime_s: uptime === null ? null : Math.floor(uptime / 100)
    }];
};

GAP.apInventory = function (walk, env) {
    GAP.requireAp(walk);
    var mac = GAP.identity(walk, env);
    if (mac === null) { return []; }
    var chassis = GAP.chassis(walk);
    return [{
        ap_uid: WE.apUid(mac), mac_address: mac,
        name: WE.blank(NE.text(NE.scalar(walk, '1.3.6.1.2.1.1.5.0'))),
        ip_address: GAP.address(walk),
        serial: chassis.serial, model: chassis.model, firmware: chassis.firmware
    }];
};

GAP.apState = function (walk, env) {
    GAP.requireAp(walk);
    var mac = GAP.identity(walk, env);
    if (mac === null) { return []; }
    // The host uptime when HOST-RESOURCES-MIB has it, else the agent's.
    var ticks = NE.int(NE.scalar(walk, GAP.HR_UPTIME));
    if (ticks === null) { ticks = NE.int(NE.scalar(walk, NE.UPTIME)); }
    var loads = NE.table(walk, GAP.HR_LOAD), total = 0, count = 0, suffix, n;
    for (suffix in loads) {
        if (!loads.hasOwnProperty(suffix)) { continue; }
        n = WE.bounded(loads[suffix], 0, 100);
        if (n !== null) { total += n; count++; }
    }
    // Memory: the hrStorageRam entries. A size of zero or a used figure above the size is unknown.
    var types = NE.table(walk, GAP.HR_STORAGE + '.2'), size = 0, used = 0, ram = 0, s, u;
    for (suffix in types) {
        if (!types.hasOwnProperty(suffix) || String(types[suffix].value).replace(/^[^0-9]*/, '') !== GAP.HR_RAM) { continue; }
        s = NE.int(NE.scalar(walk, GAP.HR_STORAGE + '.5.' + suffix));
        u = NE.int(NE.scalar(walk, GAP.HR_STORAGE + '.6.' + suffix));
        if (s === null || u === null || s <= 0 || u < 0 || u > s) { ram = -1; break; }
        size += s;
        used += u;
        ram++;
    }
    // The agent answered this walk, so the AP is up. An AP cannot report itself down: a silent AP is a failed attempt,
    // which leaves it unknown once its state is stale.
    return [{
        ap_uid: WE.apUid(mac), status: 'up',
        uptime_s: ticks === null || ticks < 0 ? null : Math.floor(ticks / 100),
        cpu_percent: count ? Math.round(total / count) : null,
        memory_used_percent: ram > 0 ? Math.round(used * 1000 / size) / 10 : null
    }];
};

// Radios: interfaces with a dot11PHYType row, by ifIndex.
GAP.radios = function (walk) {
    var phys = GAP.column(walk, GAP.PHY_TYPE), list = GAP.indexes(phys), out = [], i;
    for (i = 0; i < list.length; i++) {
        if (list[i] >= 0 && list[i] <= 255) { out.push({index: list[i], phy: NE.int(phys[list[i]])}); }
    }
    return out;
};

GAP.radioInventory = function (walk, env) {
    GAP.requireAp(walk);
    var mac = GAP.identity(walk, env);
    if (mac === null) { return []; }
    var radios = GAP.radios(walk), out = [], i, bssid;
    if (GAP.indexes(GAP.column(walk, GAP.PHY_TYPE)).length !== radios.length) {
        NE.warning(env, 'radio_identity_missing', 'A radio with an interface index above 255 was dropped.');
    }
    for (i = 0; i < radios.length; i++) {
        bssid = NE.scalar(walk, GAP.MAC + '.' + radios[i].index);
        out.push({radio_uid: WE.radioUid(mac, radios[i].index), ap_uid: WE.apUid(mac), radio_index: radios[i].index,
                  bssid: bssid ? NE.mac(bssid) : null});
    }
    return out;
};

// dot11CurrentTxPowerLevel picks one of up to eight levels given in mW; the radio's power is that level in dBm.
GAP.power = function (walk, index) {
    var level = NE.int(NE.scalar(walk, GAP.TX_POWER + '.10.' + index));
    if (level === null || level < 1 || level > 8) { return null; }
    var mw = NE.int(NE.scalar(walk, GAP.TX_POWER + '.' + (level + 1) + '.' + index));
    if (mw === null || mw <= 0) { return null; }
    var dbm = Math.round(Math.log(mw) / Math.LN10 * 100) / 10;
    return dbm >= -10 && dbm <= 40 ? dbm : null;
};

GAP.band = function (phy, channel, radios) {
    if (GAP.PHY_24[phy] && channel !== null && channel >= 1 && channel <= 14) { return '2.4'; }
    return WE.channelBand(channel, radios);
};

GAP.radioState = function (walk, env) {
    GAP.requireAp(walk);
    var mac = GAP.identity(walk, env);
    if (mac === null) { return []; }
    var radios = GAP.radios(walk), out = [], i, r, channel, band;
    for (i = 0; i < radios.length; i++) {
        r = radios[i];
        channel = WE.bounded(NE.scalar(walk, GAP.DSSS_CHANNEL + '.' + r.index), 1, 233);
        if (channel === null) { channel = WE.bounded(NE.scalar(walk, GAP.OFDM_CHANNEL + '.' + r.index), 1, 233); }
        band = GAP.band(r.phy, channel, radios.length);
        if (channel !== null && band === null) {
            NE.warning(env, 'radio_band_ambiguous',
                'A radio channel number does not prove its band (6 GHz channel numbers overlap 2.4 and 5 GHz); its band is unknown.');
        }
        out.push({
            radio_uid: WE.radioUid(mac, r.index), ap_uid: WE.apUid(mac),
            status: GAP.STATUS[NE.int(NE.scalar(walk, GAP.IF_OPER + '.' + r.index))] || 'unknown',
            band: band, channel: channel,
            // The IEEE 802.11 MIB has no channel width, noise floor or measured utilisation that agents publish widely.
            channel_width: null,
            tx_power_dbm: GAP.power(walk, r.index), noise_floor_dbm: null,
            utilisation_percent: null, utilisation_window_s: null
        });
    }
    return WE.sort(out, ['radio_uid']);
};

// SSIDs: dot11DesiredSSID per interface. An interface with an empty desired SSID (often the radio itself, whose
// virtual interfaces carry the SSIDs) broadcasts none and is skipped. One name on several interfaces is one SSID,
// enabled when any of them is administratively up.
GAP.ssids = function (walk, env) {
    GAP.requireAp(walk);
    var cells = GAP.column(walk, GAP.SSID), list = GAP.indexes(cells), seen = {}, out = [], i, name, admin, enabled;
    for (i = 0; i < list.length; i++) {
        name = WE.blank(NE.text(cells[list[i]]));
        if (name === null) { continue; }
        if (name.length > 128) {
            NE.warning(env, 'ssid_name_missing', 'An SSID name was unreadable and was dropped.');
            continue;
        }
        admin = NE.int(NE.scalar(walk, GAP.IF_ADMIN + '.' + list[i]));
        enabled = admin === 1 ? true : admin === 2 ? false : null;
        if (seen.hasOwnProperty(name)) {
            seen[name].enabled = seen[name].enabled === true || enabled === true ? true
                : seen[name].enabled === false && enabled === false ? false : null;
            seen[name].profiles++;
            continue;
        }
        // No standard object says whether an SSID is hidden, how many clients it has, its VLAN or its security mode.
        seen[name] = {ssid_uid: WE.ssidUid(name), name: name, enabled: enabled, hidden: null, client_count: null,
                      vlan_id: null, security: null, profiles: 1};
        out.push(seen[name]);
    }
    return WE.sort(out, ['name']);
};
