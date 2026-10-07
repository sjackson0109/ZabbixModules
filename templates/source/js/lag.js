// IEEE8023-LAG-MIB + IF-MIB ifStackTable walk -> canonical "lag" rows.
// LACP aggregators come from dot3adAgg tables. An ifType 161 interface that
// has active ifStack members but no LACP rows is a static bundle; one with no
// members at all stays "unknown". An LACP aggregator with no attached ports
// falls back to its ifStack members, so an idle LACP bundle still lists them.

var LAG = {
    actor: '1.2.840.10006.300.43.1.1.1.1.4',
    individual: '1.2.840.10006.300.43.1.1.1.1.5',
    partner: '1.2.840.10006.300.43.1.1.1.1.8',
    selected: '1.2.840.10006.300.43.1.2.1.1.12',
    attached: '1.2.840.10006.300.43.1.2.1.1.13',
    partnerPort: '1.2.840.10006.300.43.1.2.1.1.17',
    actorState: '1.2.840.10006.300.43.1.2.1.1.21'
};
var IF_OPER_LAG = {1: 'up', 2: 'down', 3: 'testing', 4: 'unknown', 5: 'dormant', 6: 'not_present', 7: 'lower_layer_down'};

function lagMode(source, partner, memberCount) {
    if (source === 'lacp') { return partner !== null && partner !== '00:00:00:00:00:00' ? 'lacp' : 'unknown'; }
    return memberCount ? 'static' : 'unknown';
}

function normaliseLag(walk, env) {
    var t = {}, key;
    for (key in LAG) {
        if (LAG.hasOwnProperty(key)) { t[key] = NE.table(walk, LAG[key]); }
    }
    var uids = NE.interfaceIndex(walk, env, true);
    var types = NE.table(walk, NE.IF.type), names = NE.table(walk, NE.IF.name);
    var descrs = NE.table(walk, NE.IF.descr), opers = NE.table(walk, NE.IF.oper);
    var stack = NE.table(walk, NE.IF.stack);
    var hasLacp = NE.has(walk, '1.2.840.10006.300.43.1.1.1.1') || NE.has(walk, '1.2.840.10006.300.43.1.2.1.1');
    var aggs = {}, k;
    for (k in t.actor) { if (t.actor.hasOwnProperty(k)) { aggs[k] = 'lacp'; } }
    for (k in types) {
        if (types.hasOwnProperty(k) && NE.int(types[k]) === 161 && !aggs[k]) { aggs[k] = 'unknown'; }
    }
    // Members: LACP attachment first, otherwise active ifStack children.
    var members = {};
    for (k in t.attached) {
        if (!t.attached.hasOwnProperty(k)) { continue; }
        var agg = String(NE.int(t.attached[k]));
        if (agg === '0') { continue; }
        if (!aggs[agg]) {
            NE.error(env, 'lag_aggregator_unresolved', 'A LAG member references an aggregator that was not walked.');
            continue;
        }
        (members[agg] = members[agg] || []).push(k);
    }
    var stacked = {};
    for (k in stack) {
        if (!stack.hasOwnProperty(k)) { continue; }
        var pair = k.split('.');
        if (pair.length === 2 && aggs[pair[0]] && pair[1] !== '0' && NE.int(stack[k]) === 1) {
            (stacked[pair[0]] = stacked[pair[0]] || []).push(pair[1]);
        }
    }
    for (k in stacked) {
        if (stacked.hasOwnProperty(k) && !members[k]) { members[k] = stacked[k]; }
    }
    if (!hasLacp && !Object.keys(aggs).length) {
        if (!NE.has(walk, NE.IF.type)) { throw {unsupported: 'The agent returned neither LAG nor interface type tables.'}; }
        return [];
    }
    var list = Object.keys(aggs).map(function (x) { return parseInt(x, 10); }).sort(function (a, b) { return a - b; });
    var rows = [];
    for (var i = 0; i < list.length; i++) {
        var a = String(list[i]), uid = uids[a] || null;
        if (uid === null) {
            NE.error(env, 'lag_interface_unresolved', 'An aggregator does not resolve to an IF-MIB interface.');
            continue;
        }
        var detail = [], memberUids = [];
        var mem = (members[a] || []).slice().sort(function (x, y) { return parseInt(x, 10) - parseInt(y, 10); });
        for (var j = 0; j < mem.length; j++) {
            var m = mem[j], muid = uids[m] || null;
            if (muid === null) {
                NE.error(env, 'lag_member_unresolved', 'A LAG member does not resolve to an IF-MIB interface.');
                continue;
            }
            var bits = t.actorState[m] ? NE.bitsSet(NE.bytes(t.actorState[m])) : null;
            var selected = t.selected[m] ? NE.int(t.selected[m]) === list[i] : null;
            memberUids.push(muid);
            detail.push({uid: muid, selected: selected,
                         collecting: bits === null ? null : bits.indexOf(4) >= 0,
                         distributing: bits === null ? null : bits.indexOf(5) >= 0,
                         lacp_active: bits === null ? null : bits.indexOf(0) >= 0,
                         partner_port: NE.int(t.partnerPort[m] || null)});
        }
        var partner = NE.mac(t.partner[a] || null);
        rows.push({
            uid: uid, name: NE.text(names[a] || descrs[a] || null), if_index: list[i],
            member_interface_uids: memberUids, members: detail,
            mode: lagMode(aggs[a], partner, memberUids.length),
            oper_status: IF_OPER_LAG[NE.int(opers[a] || null)] || null,
            actor_system_id: NE.mac(t.actor[a] || null),
            partner_system_id: partner === '00:00:00:00:00:00' ? null : partner
        });
    }
    return rows;
}
