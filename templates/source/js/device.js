// SNMPv2-MIB + ENTITY-MIB + LLDP local system walk -> canonical "device" row.

var DEV = {
    descr: '1.3.6.1.2.1.1.1.0',
    objectId: '1.3.6.1.2.1.1.2.0',
    name: '1.3.6.1.2.1.1.5.0',
    entClass: '1.3.6.1.2.1.47.1.1.1.1.5',
    entName: '1.3.6.1.2.1.47.1.1.1.1.7',
    entSoftware: '1.3.6.1.2.1.47.1.1.1.1.10',
    entSerial: '1.3.6.1.2.1.47.1.1.1.1.11',
    entModel: '1.3.6.1.2.1.47.1.1.1.1.13',
    chassisSubtype: '1.0.8802.1.1.2.1.3.1.0',
    chassisId: '1.0.8802.1.1.2.1.3.2.0',
    localManAddr: '1.0.8802.1.1.2.1.3.8.1.3'
};
var ENTERPRISES = {
    '9': 'Cisco', '11': 'HPE', '674': 'Dell', '890': 'Zyxel', '2636': 'Juniper', '4413': 'Ubiquiti',
    '4526': 'Netgear', '6027': 'Dell', '25506': 'HPE', '41112': 'Ubiquiti', '47196': 'HPE Aruba'
};

function blank(s) { return s === null || s.replace(/\s+/g, '') === '' ? null : s; }

function normaliseDevice(walk, env) {
    var oidEntry = NE.scalar(walk, DEV.objectId);
    var objectId = oidEntry ? oidEntry.value.replace(/^\./, '') : null;
    if (objectId !== null && !/^[0-9]+(\.[0-9]+)*$/.test(objectId)) { objectId = null; }
    var ent = /^1\.3\.6\.1\.4\.1\.([0-9]+)/.exec(objectId || '');
    var classes = NE.table(walk, DEV.entClass), chassis = [], k;
    for (k in classes) {
        if (classes.hasOwnProperty(k) && NE.int(classes[k]) === 3) { chassis.push(parseInt(k, 10)); }
    }
    chassis.sort(function (a, b) { return a - b; });
    var names = NE.table(walk, DEV.entName), soft = NE.table(walk, DEV.entSoftware);
    var serials = NE.table(walk, DEV.entSerial), models = NE.table(walk, DEV.entModel);
    var members = [];
    for (var i = 0; i < chassis.length; i++) {
        k = String(chassis[i]);
        members.push({member: blank(NE.text(names[k] || null)) || chassis[i],
                      model: blank(NE.text(models[k] || null)), serial: blank(NE.text(serials[k] || null)),
                      firmware: blank(NE.text(soft[k] || null)), role: 'unknown'});
    }
    var first = members.length ? members[0] : {model: null, serial: null, firmware: null};
    var chassisIds = [];
    if (NE.scalar(walk, DEV.chassisId)) {
        chassisIds.push(NE.lldpId(NE.scalar(walk, DEV.chassisSubtype), NE.scalar(walk, DEV.chassisId), 'chassis'));
    }
    var addresses = [], man = NE.table(walk, DEV.localManAddr);
    for (k in man) {
        if (!man.hasOwnProperty(k)) { continue; }
        var p = k.split('.'), octets = [];
        for (var j = 2; j < p.length; j++) { octets.push(parseInt(p[j], 10)); }
        var a = (p[0] === '1' || p[0] === '2') && octets.length === parseInt(p[1], 10) ? NE.ipFromOctets(octets) : null;
        if (a !== null && addresses.indexOf(a) < 0) { addresses.push(a); }
    }
    var uptime = NE.int(NE.scalar(walk, NE.UPTIME));
    var descr = NE.text(NE.scalar(walk, DEV.descr));
    return [{
        hostname: NE.text(NE.scalar(walk, DEV.name)), sys_name: NE.text(NE.scalar(walk, DEV.name)),
        description: descr === null ? null : descr.substring(0, 1024), sys_object_id: objectId,
        vendor: ent ? ENTERPRISES[ent[1]] || null : null,
        model: first.model, serial: first.serial, firmware: first.firmware,
        uptime_s: uptime === null ? null : Math.floor(uptime / 100),
        chassis_ids: chassisIds, management_addresses: addresses.sort(),
        stack_members: members.length > 1 ? members : []
    }];
}
