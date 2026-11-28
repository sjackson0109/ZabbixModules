#!/usr/bin/env python3
"""Build the deterministic native SNMP switch templates for Zabbix 7.0, 7.2 and 7.4, one file per template.

Each dataset producer in templates/source/datasets.json becomes one walk[] master item, a
JavaScript normaliser that emits the canonical envelope, and gated dependents that only
accept complete observations. The JavaScript is composed exactly as tests/js/run_normaliser.cjs
composes it, so the code tested in Node is the code Zabbix runs.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _common  # noqa: E402
from _common import (COLLECTION_STATUS, GROUPS, IF_STATUS, IF_STATUS_CONVERT, IF_STATUS_MAP, STATUS_MAP,  # noqa: E402
                     VERSION, interface_scalar, js, read_text, widget)

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "source"
MANIFEST = SOURCE / "datasets.json"
# One template per switch type, listed under "templates" in the manifest, each exported to its own file named after
# it (the naming rule is in _common.py): ne_<vendor>_<series>_switch for vendor switches and ne__generic_switch for the
# generic default. Each holds every item it needs; the dataset components are generator building blocks only and are
# never exported on their own. The per-AP Wi-Fi templates embed the LLDP component through embedded().
PROFILES = json.loads(read_text(MANIFEST))["templates"]
# Earlier releases exported every switch template in this one file.
LEGACY_EXPORTS = ("network_explorer_snmp.yaml",)
PROFILE = PROFILES[0]["template"]
FAILED = _common.FAILED
SCHEMA = "1.1"
# Datasets added in schema 1.2 (templates/source/js/lib.js NE.SCHEMAS); the others stay on 1.1.
SCHEMAS = {"hardware": "1.2", "poe": "1.2"}
NAMESPACE = _common.NAMESPACES["ne"]
# sysUpTime is a 32-bit TimeTicks counter (1/100 s), so the uptime in seconds wraps after 2**32 / 100 s (~497 days).
UPTIME_WRAP_S = 2**32 // 100
TEMPLATE_DESCRIPTION = {
    "Base": "Device identity, chassis and stack members (SNMPv2-MIB, ENTITY-MIB, LLDP local system).",
    "Interfaces": "Interface inventory and state (IF-MIB, ifXTable, EtherLike) with interface discovery.",
    "Port Capability": "Supported and advertised port speeds (MAU-MIB) used to derive expected speed.",
    "LLDP": "LLDP neighbours with dot1 and dot3 extensions. Set {$NE.LLDP.REDACT_REMOTE} to 1 to drop remote descriptions.",
    "VLAN": "VLAN table and per-port membership (Q-BRIDGE-MIB).",
    "STP": "Spanning tree bridge and port state (BRIDGE-MIB, RSTP-MIB), instance 0.",
    "LAG": "Link aggregation bundles and members (IEEE8023-LAG-MIB, ifStackTable).",
    "Hardware Health": "CPU, memory, fans, power supplies and temperature with the device's own verdicts and "
                       "thresholds (vendor MIBs).",
    "PoE": "Power over Ethernet: budget, consumption and status per PSE unit, and detection status per port "
           "(POWER-ETHERNET-MIB), with per-port power where the vendor MIB reports it.",
}


def state_convert(states: dict) -> str:
    """Preprocessing that turns a canonical state name into its value-map number (unknown for anything else)."""
    return "var m=" + json.dumps(states) + "; v=m[v]===undefined?" + str(states["unknown"]) + ":m[v];"


HW_STATE_MAP = "Network Explorer hardware state"
HW_STATE = {"ok": 0, "warning": 1, "critical": 2, "shutdown": 3, "not_present": 4, "not_functioning": 5,
            "unavailable": 6, "unknown": 7}
HW_STATE_CONVERT = state_convert(HW_STATE)
POE_PSE_STATE_MAP = "Network Explorer PoE PSE state"
POE_PSE_STATE = {"on": 0, "off": 1, "faulty": 2, "unknown": 3}
POE_PORT_STATE_MAP = "Network Explorer PoE port state"
POE_PORT_STATE = {"delivering": 0, "searching": 1, "disabled": 2, "fault": 3, "test": 4, "other_fault": 5,
                  "unknown": 6}
# Parts discovered one by one: (row kind, key stem, label). A part is discovered only while present and readable.
# Up to 2.2.0 every component emitted the shared collection-status value map and the template's last component won,
# so that map's UUID is the last component's. Components added since come last but never take it over.
LATER_COMPONENTS = ("PoE",)
HW_PARTS = (("psu", "ne.hw.psu", "power supply"), ("fan", "ne.hw.fan", "fan"),
            ("temperature", "ne.hw.temp", "temperature sensor"))

# Storage policy. Every walk's canonical envelope goes to one unstored item, ne.normalised[<producer>]; everything
# stored is derived from it. A value that reports a state, a stored snapshot or an attempt receipt is written only
# when it changes, and again every {$NE.HEARTBEAT} while it does not; Zabbix discards the repeats where it does the
# preprocessing (on the proxy, for a proxied host), so they never reach a buffer or the database. Readings (CPU,
# temperature, PoE watts) are stored every poll, since dropping repeats would skew their hourly trends. The time
# each value was sampled is Zabbix's own: stored JSON carries no timestamps (see storage()).
HEARTBEAT = "{$NE.HEARTBEAT}"
SNAPSHOT_HISTORY = "{$NE.SNAPSHOT.HISTORY}"
TRENDS = "{$NE.TRENDS}"
THROTTLE = {"type": "DISCARD_UNCHANGED_HEARTBEAT", "parameters": [HEARTBEAT]}
STORAGE_MACROS = [
    {"macro": HEARTBEAT, "value": "2h",
     "description": "An unchanged state, snapshot or attempt receipt is stored again at least this often; a change is "
                    "stored at once. Lengthen it to write less; triggers on these items are re-checked only when a "
                    "value is stored."},
    {"macro": SNAPSHOT_HISTORY, "value": "2d",
     "description": "How long JSON snapshots and attempt receipts are kept. The frontend reads the latest two; keep it "
                    "well above {$NE.HEARTBEAT}."},
    {"macro": TRENDS, "value": "180d", "description": "How long hourly trends of readings are kept."},
]
# Row fields that would change on every poll, made stable for storage. Times the device reports relative to its own
# uptime (a port's last change, the device's uptime, the last spanning-tree change) are stored as absolute times
# rounded to the minute, which the frontend turns back into the canonical fields; readings are left to numeric items.
STORAGE_ROWS = {
    "interfaces": "if(r.last_change){r.last_change=m(Date.parse(r.last_change));}",
    "device": "if(r.hasOwnProperty('uptime_s')){r.boot_at=r.uptime_s===null?null:m(t-r.uptime_s*1000);"
              "delete r.uptime_s;}",
    "stp": "if(r.hasOwnProperty('time_since_topology_change_s')){var s=r.time_since_topology_change_s;"
           "r.topology_changed_at=s===null?null:m(t-s*1000);delete r.time_since_topology_change_s;}",
    "lldp": "delete r.observed_at;",
    "hardware": "var g=['util_1s_pct','util_5s_pct','util_1m_pct','util_5m_pct','util_pct','speed','celsius'];"
                "for(var j=0;j<g.length;j++){if(r.hasOwnProperty(g[j])){r[g[j]]=null;}} delete r.free_bytes;",
}


def storage(dataset: str, rows: dict = STORAGE_ROWS) -> str:
    """JavaScript that turns the envelope `e` into its stored form: no attempted_at, observed_at or generation_id (the
    reader takes them from Zabbix's value timestamps), "timing":"zabbix" to say so, and stable rows."""
    body = rows.get(dataset, "")
    return ("var t=Date.parse(e.observed_at||e.attempted_at); "
            "var m=function(x){return new Date(Math.round(x/60000)*60000).toISOString().replace('.000Z','Z');}; "
            "delete e.generation_id; delete e.attempted_at; delete e.observed_at; e.timing='zabbix'; "
            + (f"for(var i=0;i<e.data.length;i++){{var r=e.data[i]; {body}}} " if body else ""))


# Zabbix keeps at most this many bytes of a text value and cuts the rest, which leaves invalid JSON in the database.
TEXT_LIMIT = 65535
# Stored rows are packed: each run of consecutive rows with the same fields is a block of the field names, once
# ("columns"), and an array of values per row ("rows"). About half the size, since the field names otherwise repeat
# on every row; row order is kept. The same rule as NE.pack in templates/source/js/lib.js, which NE.run uses to fail
# an observation too large to store; the frontend restores "data" (StoredEnvelope::rehydrate).
PACK = ("var d=e.data; if(Array.isArray(d)&&d.length){var q=[],g=null,u=true; for(var i=0;i<d.length;i++){var r=d[i]; "
        "if(!r||typeof r!=='object'||Array.isArray(r)){u=false;break;} var c=Object.keys(r),h=JSON.stringify(c); "
        "if(g===null||g.h!==h){g={h:h,columns:c,rows:[]}; q.push(g);} var v=[]; "
        "for(var j=0;j<c.length;j++){v.push(r[c[j]]);} g.rows.push(v);} "
        "if(u){for(var i=0;i<q.length;i++){delete q[i].h;} delete e.data; e.blocks=q;}} ")
# The UTF-8 length of a string, as Zabbix measures a stored value.
BYTES = ("var b=function(s){var n=0; for(var k=0;k<s.length;k++){var x=s.charCodeAt(k); if(x<128){n+=1;} "
         "else if(x<2048){n+=2;} else if(x>=55296&&x<56320&&k+1<s.length){n+=4;k++;} else{n+=3;}} return n;}; ")


def unpacked(envelope: dict) -> dict:
    """A stored envelope with its blocks turned back into "data", as the frontend does (StoredEnvelope::unpack)."""
    if "blocks" not in envelope:
        return envelope
    result = {k: v for k, v in envelope.items() if k != "blocks"}
    result["data"] = [dict(zip(block["columns"], row, strict=True)) for block in envelope["blocks"] for row in block["rows"]]
    return result


def stored(dataset: str, rows: dict = STORAGE_ROWS) -> str:
    """A complete observation `e` in its stored form, packed. One that would still exceed Zabbix's text limit is never
    stored cut short: the script throws, so the snapshot item keeps its last complete value."""
    return (storage(dataset, rows) + PACK + BYTES + "var s=JSON.stringify(e); "
            f"if(b(s)>{TEXT_LIMIT}){{throw 'Too large to store whole; retain last success';}} return s;")


def receipt(dataset: str, rows: dict = STORAGE_ROWS) -> str:
    """Every attempt in its stored form. A complete success keeps no rows (they are in the snapshot), only their count;
    partial, failed and unsupported attempts are kept whole, packed, unless that would exceed the text limit."""
    omit = "e.data_rows=n; e.data=[]; e.data_omitted=true;"
    return ("var e=JSON.parse(value); " + storage(dataset, rows) +
            "var n=Array.isArray(e.data)?e.data.length:0; "
            f"if(e.status==='ok'&&e.complete===true&&Array.isArray(e.data)){{{omit}}} " + PACK + BYTES +
            f"var s=JSON.stringify(e); if(b(s)>{TEXT_LIMIT}){{delete e.blocks; {omit} "
            "s=JSON.stringify(e);} return s;")


def normalised_key(entry: dict) -> str:
    return f"ne.normalised[{producer(entry)}]"


_scope = ""


def uid(name: str) -> str:
    """UUIDs are scoped to the template being built, so the same key in two templates never shares one."""
    return _common.uid(NAMESPACE, _scope + name)


def manifest() -> list[dict]:
    return json.loads(read_text(MANIFEST))["datasets"]


def producers(profile: dict, component: str, entries: list[dict]) -> list[dict]:
    """A component's producers in one template: those without a templates list, and those that list this one."""
    return [e for e in entries
            if e["template"] == component and profile["template"] in e.get("templates", [profile["template"]])]


def compose(entry: dict) -> str:
    """Same composition as tests/js/run_normaliser.cjs."""
    scripts = entry["scripts"] if "scripts" in entry else ["lib.js", entry["script"]]
    return "\n".join([read_text(SOURCE / "js" / name) for name in scripts] +
                     [f"return JSON.stringify(NE.run('{entry['dataset']}', '{entry['adapter']}', value, "
                      f"function (w, e) {{ return {entry['call']}; }}));"])


def producer(entry: dict) -> str:
    return entry["dataset"] + ("." + entry["variant"] if entry.get("variant") else "")


def stale_macro(entry: dict) -> str:
    return entry["interval_macro"].replace(".INTERVAL}", ".STALE}")


def tags(dataset: str) -> list[dict]:
    return _common.tags(dataset, "native-snmp")


def dependent(key: str, name: str, dataset: str, master: str, script: str, *, value_type: str = "TEXT",
              discard: bool = False, history: str = "7d", throttle: bool = False, **extra) -> dict:
    """A dependent item. throttle stores it only on change and every {$NE.HEARTBEAT}: for states, snapshots and
    receipts, never for readings."""
    result = {"uuid": uid("item:" + key), "name": name, "type": "DEPENDENT", "key": key, "delay": "0",
              "history": history, "value_type": value_type}
    if value_type in ("TEXT", "CHAR"):
        result["trends"] = "0"
    result.update(extra)
    result["master_item"] = {"key": master}
    result["preprocessing"] = js(script, discard) + ([dict(THROTTLE)] if throttle else [])
    result["tags"] = tags(dataset)
    return result


def row_field(dataset: str, match: str, field: str, convert: str = "") -> str:
    """One field of the first row of a complete observation that matches. A missing row or a null value throws, so
    the item keeps its last value instead of storing a guess."""
    return gate(dataset, "var a=e.data; for(var i=0;i<a.length;i++){var r=a[i]; if(" + match + "){var v=r['" + field
                + "']; if(v===null||v===undefined){throw 'Not reported';}" + convert + " return v;}} "
                "throw 'Absent; retain last observed value';")


def interface_field(field: str, unknown: str | None, convert: str = "") -> str:
    """One interface's field from a complete interface observation. A null fact returns `unknown` (so the item stays
    supported) or throws when `unknown` is None; an absent interface always throws so its last value is kept."""
    missing = "return " + unknown + ";" if unknown is not None else "throw 'Unknown scalar';"
    return gate("interfaces", "var a=e.data; for(var i=0;i<a.length;i++){if(a[i].uid==='{#IFUID}'){var v=a[i]['"
                + field + "']; if(v===null||v===undefined){" + missing + "}" + convert
                + " return v;}} throw 'Interface absent; retain last observed value';")


def gate(dataset: str, then: str = "return value;") -> str:
    """Throws (and the item discards the value) unless the envelope is a complete observation."""
    return _common.gate(SCHEMAS.get(dataset, SCHEMA), dataset, then)


def raw_item(entry: dict) -> dict:
    walk = "walk[" + ",".join(entry["walk"]) + "]"
    return {"uuid": uid("item:" + entry["raw_key"]), "name": f"Raw SNMP walk: {producer(entry)}",
            "type": "SNMP_AGENT", "snmp_oid": walk, "key": entry["raw_key"], "delay": entry["interval_macro"],
            "history": "0", "value_type": "TEXT", "trends": "0",
            "description": "Input for the canonical normaliser only; not stored. A timeout or SNMP error becomes "
                           "a failed attempt instead of making the dataset silently disappear.",
            "preprocessing": _common.collection_failure(entry["walk"]),
            "tags": tags(entry["dataset"])}


def producer_items(entry: dict, template: str) -> list[dict]:
    dataset, name = entry["dataset"], producer(entry)
    attempt, normalised = entry["attempt_key"], normalised_key(entry)
    items = [raw_item(entry),
             dependent(normalised, f"Normalised envelope: {name}", dataset, entry["raw_key"], compose(entry),
                       history="0", description="The canonical envelope of each attempt, passed to the items below; "
                                                "not stored."),
             dependent(attempt, f"Collection attempt: {name}", dataset, normalised, receipt(dataset),
                       history=SNAPSHOT_HISTORY, throttle=True,
                       description="Each attempt's outcome, including partial, failed and unsupported, stored when it "
                                   "changes. A complete success keeps only its row count; the rows are in the "
                                   "snapshot. Times are Zabbix's own.")]
    for key in entry["snapshot_keys"]:
        items.append(dependent(key, f"Last complete snapshot: {name}", dataset, normalised,
                               gate(dataset, stored(dataset)), discard=True,
                               history=SNAPSHOT_HISTORY, throttle=True,
                               description="Complete, successful observations only, stored when they change. Times "
                                           "are Zabbix's own: the frontend takes the observation time from the last "
                                           "complete observation item."))
    status = dependent(f"ne.collection.status[{name}]", f"Collection status: {name}", dataset, normalised,
                       COLLECTION_STATUS, value_type="UNSIGNED", history="31d", trends="0",
                       valuemap={"name": STATUS_MAP}, throttle=True)
    # Stored at every complete observation: the staleness trigger's nodata() needs it, and its Zabbix timestamp is
    # the observation time the frontend reports.
    success = dependent(f"ne.collection.success[{name}]", f"Last complete observation: {name}", dataset, normalised,
                        gate(dataset, "return Math.floor(Date.parse(e.observed_at)/1000);"),
                        value_type="UNSIGNED", discard=True, history="7d", trends="0", units="unixtime")
    stale = stale_macro(entry)
    success["triggers"] = [{
        "uuid": uid("trigger:stale:" + name),
        "expression": f"nodata(/{template}/ne.collection.success[{name}],{stale})=1 and "
                      f"last(/{template}/ne.collection.status[{name}])<>3",
        "name": f"Network Explorer: no complete {name} observation for {stale}",
        "priority": "WARNING",
        "description": "Partial and failed attempts never refresh this age. An unsupported dataset does not alert.",
        "tags": tags(dataset)}]
    return items + [status, success]


def interface_discovery(template: str) -> dict:
    # An unknown fact is a value (so the item stays supported); only an absent interface is discarded.
    # Status comes from the status walk, speed and duplex from the link walk; each is a state, stored on change.
    prototypes = []
    for field, key, label, value_type, unknown, convert, master in (
        ("oper_status", "ne.if.oper", "operational status", "UNSIGNED", "4", IF_STATUS_CONVERT, "interfaces"),
        ("admin_status", "ne.if.admin", "administrative status", "UNSIGNED", "4", IF_STATUS_CONVERT, "interfaces"),
        ("speed_bps", "ne.if.speed", "negotiated speed (0 = unknown)", "UNSIGNED", "0", "", "interfaces.link"),
        ("duplex", "ne.if.duplex", "duplex", "CHAR", "'unknown'", "", "interfaces.link"),
    ):
        if field.endswith("status"):
            # Enumerations: trends of a status code are meaningless.
            extra = {"trends": "0", "valuemap": {"name": IF_STATUS_MAP}}
        elif field == "speed_bps":
            # A negotiated speed is a state stored on change, not a reading: hourly trends of it would be gaps.
            extra = {"trends": "0", "units": "bps"}
        else:
            extra = {}  # CHAR: dependent() already disables trends.
        prototype = dependent(key + "[{#IFUID}]", "{#IFNAME}: " + label, "interfaces", f"ne.normalised[{master}]",
                              interface_field(field, unknown, convert), value_type=value_type, discard=True,
                              history="31d", throttle=True, **extra)
        prototype["tags"].append({"tag": "interface", "value": "{#IFNAME}"})
        prototypes.append(prototype)
    oper, admin, speed = (f"/{template}/{k}[{{#IFUID}}]" for k in ("ne.if.oper", "ne.if.admin", "ne.if.speed"))
    prototypes[0]["trigger_prototypes"] = [{
        "uuid": uid("trigger:if-down"),
        "expression": f'{{$NE.IF.MONITOR:"{{#IFNAME}}"}}=1 and last({oper})<>1 and last({admin})=1',
        "name": "Network Explorer: {#IFNAME} is down", "priority": "AVERAGE",
        "description": "Raised only for ports an operator marks with {$NE.IF.MONITOR:\"<ifName>\"}=1.",
        "tags": tags("interfaces")}]
    # Speed is stored only when it changes, so a time window would hold one value and fire at once; the link walk's
    # own interval ({$NE.IF.LINK.INTERVAL}) is the settling time instead.
    prototypes[2]["trigger_prototypes"] = [{
        "uuid": uid("trigger:if-speed"),
        "expression": f'{{$NE.IF.EXPECTED_SPEED:"{{#IFNAME}}"}}>0 and last({oper})=1 and '
                      f'last({speed})>0 and last({speed})<{{$NE.IF.EXPECTED_SPEED:"{{#IFNAME}}"}}',
        "name": "Network Explorer: {#IFNAME} below expected speed", "priority": "WARNING",
        "description": "Uses the explicit per-port override only. Derived expectations are shown by the frontend. "
                       "Speed is read every {$NE.IF.LINK.INTERVAL}.",
        "tags": tags("interfaces")}]
    return {"uuid": uid("lld:interfaces"), "name": "Interface discovery", "type": "DEPENDENT",
            "key": "ne.interfaces.discovery", "delay": "0", "lifetime": "7d",
            "enabled_lifetime_type": "DISABLE_AFTER", "enabled_lifetime": "1d",
            "master_item": {"key": "ne.normalised[interfaces.inventory]"},
            "description": "Fed from complete inventory observations, so a partial walk never removes ports. "
                           "Processed only when the port list changes, and every {$NE.HEARTBEAT}.",
            "preprocessing": js(gate("interfaces", "return JSON.stringify(e.data.map(function(r){return "
                                      "{uid:r.uid,name:r.name||r.description||r.uid,if_index:r.if_index,"
                                      "physical:r.physical===true?1:0};}));"), True) + [dict(THROTTLE)],
            "lld_macro_paths": [{"lld_macro": "{#IFUID}", "path": "$.uid"},
                                {"lld_macro": "{#IFNAME}", "path": "$.name"},
                                {"lld_macro": "{#IFINDEX}", "path": "$.if_index"},
                                {"lld_macro": "{#IFPHYSICAL}", "path": "$.physical"}],
            "item_prototypes": prototypes}


def hardware_state_triggers(item_key: str, label: str, name: str, scope: str) -> list[dict]:
    """The device's own verdict, never a threshold of ours: 1 warning; 2 critical, 3 shutdown or 5 not functioning;
    4 a part that was present is gone; 6 the device cannot read it."""
    key = f"last({item_key})"
    return [
        {"uuid": uid(f"trigger:hw:{scope}:critical"), "expression": f"{key}=2 or {key}=3 or {key}=5",
         "name": f"Network Explorer: {label} {name} reports a critical state", "priority": "HIGH",
         "description": "Critical, shut down or not functioning, as the device reports it.", "tags": tags("hardware")},
        {"uuid": uid(f"trigger:hw:{scope}:warning"), "expression": f"{key}=1",
         "name": f"Network Explorer: {label} {name} reports a warning", "priority": "WARNING",
         "tags": tags("hardware")},
        {"uuid": uid(f"trigger:hw:{scope}:gone"), "expression": f"{key}=4",
         "name": f"Network Explorer: {label} {name} is no longer present", "priority": "WARNING",
         "manual_close": "YES", "tags": tags("hardware")},
        {"uuid": uid(f"trigger:hw:{scope}:unreadable"), "expression": f"{key}=6",
         "name": f"Network Explorer: {label} {name} cannot be read", "priority": "WARNING", "tags": tags("hardware")},
    ]


def hardware_scalars(entry: dict, template: str) -> list[dict]:
    provides, items = entry["provides"], []
    source = normalised_key(entry)
    if "global" in provides:
        item = dependent("ne.hw.global.state", "Hardware: overall status", "hardware", source,
                         row_field("hardware", "r.kind==='global'", "state", HW_STATE_CONVERT), value_type="UNSIGNED",
                         discard=True, history="31d", trends="0", valuemap={"name": HW_STATE_MAP}, throttle=True,
                         description="The device's own summary of its hardware health, stored when it changes.")
        item["triggers"] = hardware_state_triggers(f"/{template}/ne.hw.global.state", "device", "overall status",
                                                   "global")[:2]
        items.append(item)
    if "cpu" in provides:
        for window in ("1m", "5m"):
            items.append(dependent(f"ne.hw.cpu.util[{window}]", f"Hardware: CPU utilisation, {window} average",
                                   "hardware", source, row_field("hardware", "r.kind==='cpu'", f"util_{window}_pct",
                                                                 "v=Math.round(v*10)/10;"),
                                   value_type="FLOAT", discard=True, history="31d", trends=TRENDS, units="%",
                                   description="As the device averages it, to 0.1%. No value while measurement is "
                                               "off."))
        cpu = f"/{template}/ne.hw.cpu.util[5m]"
        items[-1]["triggers"] = [{
            "uuid": uid("trigger:hw:cpu"), "expression": f"min({cpu},{{$NE.HW.CPU.UTIL.FOR}})>{{$NE.HW.CPU.UTIL.MAX}}",
            "name": "Network Explorer: CPU utilisation above {$NE.HW.CPU.UTIL.MAX}% for {$NE.HW.CPU.UTIL.FOR}",
            "priority": "WARNING", "tags": tags("hardware")}]
    if "memory" in provides:
        memory = dependent("ne.hw.memory.util", "Hardware: memory utilisation", "hardware", source,
                           row_field("hardware", "r.kind==='memory'", "util_pct", "v=Math.round(v*10)/10;"),
                           value_type="FLOAT", discard=True, history="31d", trends=TRENDS, units="%",
                           description="To 0.1%.")
        util = f"/{template}/ne.hw.memory.util"
        memory["triggers"] = [{
            "uuid": uid("trigger:hw:memory"),
            "expression": f"min({util},{{$NE.HW.MEMORY.UTIL.FOR}})>{{$NE.HW.MEMORY.UTIL.MAX}}",
            "name": "Network Explorer: memory utilisation above {$NE.HW.MEMORY.UTIL.MAX}% for {$NE.HW.MEMORY.UTIL.FOR}",
            "priority": "WARNING", "tags": tags("hardware")}]
        items.append(memory)
    return items


def hardware_discovery(entry: dict, template: str) -> list[dict]:
    rules, source = [], normalised_key(entry)
    for kind, stem, label in HW_PARTS:
        if kind not in entry["provides"]:
            continue
        match = f"r.kind==='{kind}'&&r.uid==='{{#HWUID}}'"
        state = dependent(f"{stem}.state[{{#HWUID}}]", f"{label.capitalize()} {{#HWNAME}}: state", "hardware",
                          source, row_field("hardware", match, "state", HW_STATE_CONVERT),
                          value_type="UNSIGNED", discard=True, history="31d", trends="0",
                          valuemap={"name": HW_STATE_MAP}, throttle=True,
                          description="The device's own verdict, stored when it changes.")
        state["trigger_prototypes"] = hardware_state_triggers(f"/{template}/{stem}.state[{{#HWUID}}]", label,
                                                              "{#HWNAME}", kind)
        prototypes = [state]
        if kind == "fan" and "fan_speed" in entry["provides"]:
            prototypes.append(dependent(f"{stem}.speed[{{#HWUID}}]", "Fan {#HWNAME}: speed", "hardware",
                                        source, row_field("hardware", match, "speed"), value_type="UNSIGNED",
                                        discard=True, history="31d", trends=TRENDS,
                                        description="As the device reports it; the MIB gives no unit."))
        if kind == "temperature":
            prototypes.append(dependent(f"{stem}.value[{{#HWUID}}]", "Temperature sensor {#HWNAME}: temperature",
                                        "hardware", source, row_field("hardware", match, "celsius"),
                                        value_type="FLOAT", discard=True, history="31d", trends=TRENDS, units="°C",
                                        description="The device judges it against its own thresholds; see the "
                                                    "state item."))
        for prototype in prototypes:
            prototype["tags"].append({"tag": "hardware", "value": "{#HWNAME}"})
        unreadable = "" if kind != "temperature" else "&&r.state!=='unavailable'"
        rows = (f"return JSON.stringify(e.data.filter(function(r){{return r.kind==='{kind}'&&r.state!=='not_present'"
                f"&&r.state!=='unknown'{unreadable};}}).map(function(r){{return {{uid:r.uid,name:r.name,"
                "unit:r.unit===null?'':String(r.unit)};}));")
        rules.append({"uuid": uid(f"lld:hardware:{kind}"), "name": f"Hardware discovery: {label}s", "type": "DEPENDENT",
                      "key": f"{stem}.discovery", "delay": "0", "lifetime": "7d",
                      "enabled_lifetime_type": "DISABLE_AFTER", "enabled_lifetime": "1d",
                      "master_item": {"key": source},
                      "description": "Fed from complete hardware observations. A part is discovered while the device "
                                     "reports it present and readable. Processed only when the list changes, and "
                                     "every {$NE.HEARTBEAT}.",
                      "preprocessing": js(gate("hardware", rows), True) + [dict(THROTTLE)],
                      "lld_macro_paths": [{"lld_macro": "{#HWUID}", "path": "$.uid"},
                                          {"lld_macro": "{#HWNAME}", "path": "$.name"},
                                          {"lld_macro": "{#HWUNIT}", "path": "$.unit"}],
                      "item_prototypes": prototypes})
    return rules


def poe_discovery(entries: list[dict], template: str) -> list[dict]:
    """PSE units and PoE ports, discovered from complete status observations. States, the budget and the threshold
    come from the status walk and are stored when they change; consumption, the share of the budget used and per-port
    power come from the power walk and are readings. Faults are the device's own verdict; the usage alert uses the
    device's own threshold (pethMainPseUsageThreshold), never one of ours."""
    (status_entry,) = [e for e in entries if not e.get("variant")]
    (power_entry,) = [e for e in entries if e.get("variant") == "power"]
    status, power = normalised_key(status_entry), normalised_key(power_entry)
    pse = "r.kind==='pse'&&r.uid==='{#PSEUID}'"
    state = dependent("ne.poe.pse.state[{#PSEUID}]", "PoE {#PSENAME}: PSE status", "poe", status,
                      row_field("poe", pse, "state", state_convert(POE_PSE_STATE)), value_type="UNSIGNED",
                      discard=True, history="31d", trends="0", valuemap={"name": POE_PSE_STATE_MAP}, throttle=True)
    state["trigger_prototypes"] = [{
        "uuid": uid("trigger:poe:pse:faulty"), "expression": f"last(/{template}/ne.poe.pse.state[{{#PSEUID}}])=2",
        "name": "Network Explorer: PoE {#PSENAME} reports a fault", "priority": "HIGH",
        "description": "pethMainPseOperStatus is faulty, as the device reports it.", "tags": tags("poe")}]
    readings = [dependent(f"ne.poe.pse.{key}[{{#PSEUID}}]", f"PoE {{#PSENAME}}: {label}", "poe", source,
                          row_field("poe", pse, field, "v=Math.round(v*10)/10;"), value_type="FLOAT", discard=True,
                          history="31d", units=units, description=description,
                          **({"trends": TRENDS} if reading else {"trends": "0", "throttle": True}))
                for key, label, field, units, source, reading, description in (
                    ("power", "power budget", "power_w", "W", status, False,
                     "Nominal power of the PSE (pethMainPsePower), stored when it changes."),
                    ("consumption", "power consumption", "consumption_w", "W", power, True,
                     "pethMainPseConsumptionPower as the device reports it, every {$NE.POE.POWER.INTERVAL}. Some "
                     "firmware reports the power allocated to its ports here rather than the power they draw (Cisco "
                     "350-class, for example)."),
                    ("util", "budget used", "util_pct", "%", power, True,
                     "Consumption as a share of the budget, the figure the device compares with its usage threshold."),
                    ("threshold", "usage threshold", "usage_threshold_pct", "%", status, False,
                     "The device's own usage alarm threshold (pethMainPseUsageThreshold), stored when it changes."))]
    util, threshold = (f"/{template}/ne.poe.pse.{k}[{{#PSEUID}}]" for k in ("util", "threshold"))
    readings[2]["trigger_prototypes"] = [{
        "uuid": uid("trigger:poe:pse:usage"), "expression": f"last({util})>=last({threshold})",
        "name": "Network Explorer: PoE {#PSENAME} uses its budget above the device's usage threshold",
        "priority": "WARNING", "description": "The threshold is the one configured on the device.",
        "tags": tags("poe")}]
    pse_prototypes = [state, *readings]

    port = "r.kind==='port'&&r.uid==='{#POEUID}'"
    port_state = dependent("ne.poe.port.state[{#POEUID}]", "PoE port {#POENAME}: status", "poe", status,
                           row_field("poe", port, "state", state_convert(POE_PORT_STATE)), value_type="UNSIGNED",
                           discard=True, history="31d", trends="0", valuemap={"name": POE_PORT_STATE_MAP},
                           throttle=True,
                           description="pethPsePortDetectionStatus, as the device reports it, stored when it changes.")
    port_state["trigger_prototypes"] = [{
        "uuid": uid("trigger:poe:port:fault"),
        "expression": f"last(/{template}/ne.poe.port.state[{{#POEUID}}])=3 or "
                      f"last(/{template}/ne.poe.port.state[{{#POEUID}}])=5",
        "name": "Network Explorer: PoE port {#POENAME} reports a fault", "priority": "WARNING",
        "description": "The port's detection status is fault or another fault, as the device reports it.",
        "tags": tags("poe")}]
    port_prototypes = [port_state]
    if "port_power" in power_entry["provides"]:
        port_prototypes.append(dependent("ne.poe.port.power[{#POEUID}]", "PoE port {#POENAME}: power", "poe", power,
                                         row_field("poe", port, "power_mw", "v=Math.round(v/100)/10;"),
                                         value_type="FLOAT", discard=True, history="31d", trends=TRENDS, units="W",
                                         description="Power the port delivers, from the vendor MIB, to 0.1 W, every "
                                                     "{$NE.POE.POWER.INTERVAL}."))
    for prototype in pse_prototypes:
        prototype["tags"].append({"tag": "poe", "value": "{#PSENAME}"})
    for prototype in port_prototypes:
        prototype["tags"].append({"tag": "poe", "value": "{#POENAME}"})
    rule = lambda key, name, rows, macros, prototypes, description: {
        "uuid": uid("lld:" + key), "name": name, "type": "DEPENDENT", "key": key, "delay": "0", "lifetime": "7d",
        "enabled_lifetime_type": "DISABLE_AFTER", "enabled_lifetime": "1d", "master_item": {"key": status},
        "description": description + " Processed only when the list changes, and every {$NE.HEARTBEAT}.",
        "preprocessing": js(gate("poe", rows), True) + [dict(THROTTLE)],
        "lld_macro_paths": [{"lld_macro": m, "path": p} for m, p in macros], "item_prototypes": prototypes}
    return [
        rule("ne.poe.pse.discovery", "PoE discovery: PSE units",
             "return JSON.stringify(e.data.filter(function(r){return r.kind==='pse'&&r.state!=='not_present';})"
             ".map(function(r){return {uid:r.uid,name:r.name,unit:r.unit===null?'':String(r.unit)};}));",
             (("{#PSEUID}", "$.uid"), ("{#PSENAME}", "$.name"), ("{#PSEUNIT}", "$.unit")), pse_prototypes,
             "Fed from complete PoE status observations. A stack slot without a unit is not discovered."),
        rule("ne.poe.port.discovery", "PoE discovery: ports",
             "return JSON.stringify(e.data.filter(function(r){return r.kind==='port';}).map(function(r){return "
             "{uid:r.uid,name:r.name,unit:r.unit===null?'':String(r.unit),ifuid:r.interface_uid||''};}));",
             (("{#POEUID}", "$.uid"), ("{#POENAME}", "$.name"), ("{#POEUNIT}", "$.unit"), ("{#IFUID}", "$.ifuid")),
             port_prototypes,
             "Fed from complete PoE status observations. {#IFUID} is the interface the port joins to, where the template "
             "can tell; otherwise it is empty and the port is named by unit and port."),
    ]


def extras(short: str, template: str, mine: list[dict]) -> list[dict]:
    """Scalars a native trigger needs, read from complete observations."""
    if short == "Hardware Health":
        return [item for entry in mine for item in hardware_scalars(entry, template)]
    if short == "Base":
        # Uptime changes at every poll, so it is stored every poll (hourly); the restart trigger needs consecutive values.
        item = dependent("ne.device.uptime", "Device uptime", "device", normalised_key(mine[0]),
                         gate("device", "var d=e.data[0]; if(!d||d.uptime_s===null) throw 'Unknown uptime'; "
                                        "return d.uptime_s;"),
                         value_type="UNSIGNED", discard=True, history="31d", trends="0", units="uptime")
        uptime = f"/{template}/ne.device.uptime"
        # A sysUpTime wrap also drops uptime below 600 s; only a previous value well below the wrap point (by more
        # than a day of hourly polls) shows a restart.
        item["triggers"] = [{"uuid": uid("trigger:rebooted"),
                             "expression": f"last({uptime})<600 and last({uptime},#2)<{UPTIME_WRAP_S - 86400}",
                             "name": "Network Explorer: device restarted", "priority": "INFO",
                             "description": "Not raised when the 32-bit sysUpTime counter wraps (about every 497 days).",
                             "manual_close": "YES", "tags": tags("device")}]
        return [item]
    if short == "STP":
        bridge = ("var a=e.data; for(var i=0;i<a.length;i++){if(a[i].kind==='bridge'&&a[i].instance===0){"
                  "var v=a[i]['%s']; if(v===null) throw 'Unknown'; return v;}} throw 'No instance 0';")
        source = normalised_key(mine[0])
        # Both are stored only when they change: a stored root bridge is a new root (change()=1), and the heartbeat
        # value that follows, being equal, resolves it.
        root = dependent("ne.stp.root_bridge", "STP root bridge (instance 0)", "stp", source,
                         gate("stp", bridge % "root_bridge_id"), value_type="CHAR", discard=True, history="31d",
                         throttle=True)
        root["triggers"] = [{"uuid": uid("trigger:stp-root"), "expression": f"change(/{template}/ne.stp.root_bridge)=1",
                             "name": "Network Explorer: STP root bridge changed", "priority": "WARNING",
                             "manual_close": "YES", "tags": tags("stp")}]
        changes = dependent("ne.stp.topology_changes", "STP topology changes (instance 0)", "stp", source,
                            gate("stp", bridge % "topology_changes"), value_type="UNSIGNED", discard=True,
                            history="31d", trends="0", throttle=True)
        return [root, changes]
    return []


def macros(entries: list[dict], short: str) -> list[dict]:
    result = []
    for entry in entries:
        result.append({"macro": entry["interval_macro"], "value": entry["interval"],
                       "description": f"Polling interval for {producer(entry)}."})
        result.append({"macro": stale_macro(entry), "value": entry["stale"],
                       "description": f"Maximum age of a complete {producer(entry)} observation."})
    if short == "Interfaces":
        result += [{"macro": "{$NE.IF.MONITOR}", "value": "0",
                    "description": "Set to 1 with an interface-name context to alert when that port goes down."},
                   {"macro": "{$NE.IF.EXPECTED_SPEED}", "value": "0",
                    "description": "Expected speed in bit/s, with an interface-name context. 0 derives it from capability."}]
    if short == "LLDP":
        result.append({"macro": "{$NE.LLDP.REDACT_REMOTE}", "value": "0",
                       "description": "1 drops remote system and port descriptions from stored neighbour data."})
    provides = {p for entry in entries for p in entry.get("provides", [])}
    for part, label in (("cpu", "CPU"), ("memory", "memory")):
        if part in provides:
            name = part.upper()
            result += [{"macro": f"{{$NE.HW.{name}.UTIL.MAX}}", "value": "90",
                        "description": f"Alert when {label} utilisation stays above this percentage."},
                       {"macro": f"{{$NE.HW.{name}.UTIL.FOR}}", "value": "15m",
                        "description": f"How long {label} utilisation must stay high before alerting."}]
    return sorted(result, key=lambda m: m["macro"])


def valuemaps(short: str) -> list[dict]:
    maps = [{"uuid": uid(f"valuemap:{short}:status"), "name": STATUS_MAP,
             "mappings": [{"value": str(i), "newvalue": s} for i, s in enumerate(("ok", "partial", "failed", "unsupported"))]}]
    if short == "Interfaces":
        maps.append({"uuid": uid("valuemap:interfaces:if-status"), "name": IF_STATUS_MAP,
                     "mappings": [{"value": str(v), "newvalue": k} for k, v in IF_STATUS.items()]})
    if short == "Hardware Health":
        maps.append({"uuid": uid("valuemap:hardware:state"), "name": HW_STATE_MAP,
                     "mappings": [{"value": str(v), "newvalue": k} for k, v in HW_STATE.items()]})
    if short == "PoE":
        for key, name, states in (("pse", POE_PSE_STATE_MAP, POE_PSE_STATE), ("port", POE_PORT_STATE_MAP, POE_PORT_STATE)):
            maps.append({"uuid": uid(f"valuemap:poe:{key}"), "name": name,
                         "mappings": [{"value": str(v), "newvalue": k} for k, v in states.items()]})
    return maps


def build(version: str) -> dict:
    global _scope
    entries = manifest()
    known = set(e["template"] for e in entries)
    templates = []
    for profile in PROFILES:
        name = profile["template"]
        assert set(profile["components"]) <= known, profile["components"]
        assert set(profile.get("disabled", [])) <= set(profile["components"]), profile["disabled"]
        _scope = profile.get("scope", name) + ":"
        items, discovery, macro_list, maps = [], [], [], {}
        status_owner = [c for c in profile["components"] if c not in LATER_COMPONENTS][-1]
        for short in profile["components"]:
            mine = producers(profile, short, entries)
            produced = {producer(e) for e in mine}
            assert mine and len(produced) == len(mine), (name, short, "needs exactly one producer per dataset")
            own = [i for e in mine for i in producer_items(e, name)] + extras(short, name, mine)
            rules = [interface_discovery(name)] if short == "Interfaces" else []
            if short == "Hardware Health":
                rules += [rule for e in mine for rule in hardware_discovery(e, name)]
            if short == "PoE":
                rules += poe_discovery(mine, name)
            if short in profile.get("disabled", []):
                # Shipped but switched off: the operator can enable it on a host whose firmware supports it.
                for obj in own + rules:
                    obj["status"] = "DISABLED"
            items += own
            discovery += rules
            macro_list += macros(mine, short)
            for m in valuemaps(short):
                # The collection-status map is shared by every component and keeps the UUID it had up to 2.2.0.
                if m["name"] != STATUS_MAP or m["name"] not in maps or short == status_owner:
                    maps[m["name"]] = m
        parts = "; ".join(f"{short}: {TEMPLATE_DESCRIPTION[short]}"
                          + (" Disabled; enable it where the device supports it." if short in profile.get("disabled", []) else "")
                          for short in profile["components"])
        template = {"uuid": uid("template:" + profile.get("scope", name)), "template": name, "name": profile["name"],
                    "description": profile["description"] + " Datasets - " + parts +
                                   " Generated by templates/generate_snmp.py; do not edit by hand.",
                    "vendor": {"name": "Network Explorer", "version": VERSION},
                    "groups": [{"name": GROUPS[_common.product(name)]}], "items": items}
        if discovery:
            template["discovery_rules"] = discovery
        template["tags"] = [{"tag": "component", "value": "network-explorer"}]
        template["macros"] = sorted(macro_list + [dict(m) for m in STORAGE_MACROS], key=lambda m: m["macro"])
        template["valuemaps"] = list(maps.values())
        if profile.get("dashboard"):
            template["dashboards"] = [host_dashboard()]
        templates.append(template)
    _scope = ""
    groups = [_common.group(prefix) for prefix in dict.fromkeys(_common.product(t["template"]) for t in templates)]
    return {"zabbix_export": {"version": version, "template_groups": groups, "templates": templates}}


def embedded(template: str, scope: str, components: list[str]) -> dict:
    """Network Explorer components for a template that another generator builds: generate_wifi.py adds LLDP to the
    per-AP templates, so an AP's own LLDP confirms its uplink. UUIDs are scoped by `scope`, the host template's own
    UUID name, so they never coincide with a switch template's. Components with discovery rules are not embedded."""
    global _scope
    entries = manifest()
    _scope = scope + ":"
    try:
        items, macro_list, maps = [], [], []
        for short in components:
            assert short not in ("Interfaces", "Hardware Health", "PoE"), (template, short, "has discovery rules")
            mine = producers({"template": template}, short, entries)
            assert mine, (template, short)
            items += [i for e in mine for i in producer_items(e, template)] + extras(short, template, mine)
            macro_list += macros(mine, short)
            maps += valuemaps(short)
        return {"items": items, "macros": macro_list + [dict(m) for m in STORAGE_MACROS], "valuemaps": maps}
    finally:
        _scope = ""


def render(version: str) -> dict[str, str]:
    """One self-contained export per template, in a file named after its technical name."""
    return _common.split_exports(build(version)["zabbix_export"])


def host_dashboard() -> dict:
    """The switch host dashboard, inherited from the device template. Zabbix imports it whether or not the widget
    modules are installed; a widget whose module is missing or disabled shows as inaccessible."""
    # The Interface detail widget beside the panel shows the selected port, so the panel draws no drawer of its own.
    port_panel = [{"type": "STRING", "name": "reference", "value": "NEPRT"},
                  {"type": "INTEGER", "name": "details", "value": "0"}]
    detail = [{"type": "STRING", "name": "itemid._reference", "value": "NEPRT._itemid"}]
    pages = [
        {"name": "Ports", "widgets": [widget("nedataquality", "Collection quality", 0, 0, 72, 4),
                                      widget("neportpanel", "Port panel", 0, 4, 48, 10, port_panel),
                                      widget("neinterfacedetail", "Interface detail", 48, 4, 24, 10, detail)]},
        {"name": "Topology", "widgets": [widget("netopology", "Physical topology, VLAN and STP", 0, 0, 72, 12)]},
        {"name": "Findings", "widgets": [widget("nefindings", "Findings", 0, 0, 72, 9),
                                         widget("nedataquality", "Dataset quality", 0, 9, 72, 6)]},
    ]
    return {"uuid": uid("dashboard:Network Explorer"), "name": "Network Explorer", "auto_start": "NO", "pages": pages}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Fail if generated files differ.")
    args = parser.parse_args()
    outputs = {}
    for version in ("7.0", "7.2", "7.4"):
        for name, text in render(version).items():
            outputs[ROOT / "native" / version / name] = text
    # This generator owns every ne_*.yaml beside them (generate_wifi.py owns the other we_*.yaml); one it no longer
    # writes is stale.
    _common.write_native(outputs, args.check, lambda path: path.suffix == ".yaml" and (
        path.name.startswith("ne_") or path.name in LEGACY_EXPORTS))


if __name__ == "__main__":
    main()
