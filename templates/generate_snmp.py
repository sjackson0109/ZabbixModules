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
FAILED = "__NE_COLLECTION_FAILED__"
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
              discard: bool = False, history: str = "7d", **extra) -> dict:
    result = {"uuid": uid("item:" + key), "name": name, "type": "DEPENDENT", "key": key, "delay": "0",
              "history": history, "value_type": value_type}
    if value_type in ("TEXT", "CHAR"):
        result["trends"] = "0"
    result.update(extra)
    result["master_item"] = {"key": master}
    result["preprocessing"] = js(script, discard)
    result["tags"] = tags(dataset)
    return result


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
            "preprocessing": [{"type": "CHECK_NOT_SUPPORTED", "parameters": ["-1"],
                               "error_handler": "CUSTOM_VALUE", "error_handler_params": FAILED}],
            "tags": tags(entry["dataset"])}


def producer_items(entry: dict, template: str) -> list[dict]:
    dataset, name = entry["dataset"], producer(entry)
    attempt = entry["attempt_key"]
    items = [raw_item(entry),
             dependent(attempt, f"Collection attempt: {name}", dataset, entry["raw_key"], compose(entry),
                       description="Canonical envelope for every attempt, including partial, failed and unsupported.")]
    for key in entry["snapshot_keys"]:
        items.append(dependent(key, f"Last complete snapshot: {name}", dataset, attempt, gate(dataset), discard=True,
                               description="Updated only by complete, successful observations."))
    status = dependent(f"ne.collection.status[{name}]", f"Collection status: {name}", dataset, attempt,
                       COLLECTION_STATUS,
                       value_type="UNSIGNED", history="31d", trends="0", valuemap={"name": STATUS_MAP})
    success = dependent(f"ne.collection.success[{name}]", f"Last complete observation: {name}", dataset, attempt,
                        gate(dataset, "return Math.floor(Date.parse(e.observed_at)/1000);"),
                        value_type="UNSIGNED", discard=True, history="31d", trends="0", units="unixtime")
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
    prototypes = []
    for field, key, label, value_type, unknown, convert in (
        ("oper_status", "ne.if.oper", "operational status", "UNSIGNED", "4", IF_STATUS_CONVERT),
        ("admin_status", "ne.if.admin", "administrative status", "UNSIGNED", "4", IF_STATUS_CONVERT),
        ("speed_bps", "ne.if.speed", "negotiated speed (0 = unknown)", "UNSIGNED", "0", ""),
        ("duplex", "ne.if.duplex", "duplex", "CHAR", "'unknown'", ""),
    ):
        if field.endswith("status"):
            # Enumerations: trends of a status code are meaningless.
            extra = {"trends": "0", "valuemap": {"name": IF_STATUS_MAP}}
        elif field == "speed_bps":
            # Speed keeps the default trends on purpose: long-term min/max/avg of negotiated speed is useful history.
            extra = {"units": "bps"}
        else:
            extra = {}  # CHAR: dependent() already disables trends.
        prototype = dependent(key + "[{#IFUID}]", "{#IFNAME}: " + label, "interfaces", "ne.interfaces.state",
                              interface_scalar(field, unknown, convert), value_type=value_type, discard=True,
                              history="31d", **extra)
        prototype["tags"].append({"tag": "interface", "value": "{#IFNAME}"})
        prototypes.append(prototype)
    oper, admin, speed = (f"/{template}/{k}[{{#IFUID}}]" for k in ("ne.if.oper", "ne.if.admin", "ne.if.speed"))
    prototypes[0]["trigger_prototypes"] = [{
        "uuid": uid("trigger:if-down"),
        "expression": f'{{$NE.IF.MONITOR:"{{#IFNAME}}"}}=1 and last({oper})<>1 and last({admin})=1',
        "name": "Network Explorer: {#IFNAME} is down", "priority": "AVERAGE",
        "description": "Raised only for ports an operator marks with {$NE.IF.MONITOR:\"<ifName>\"}=1.",
        "tags": tags("interfaces")}]
    prototypes[2]["trigger_prototypes"] = [{
        "uuid": uid("trigger:if-speed"),
        "expression": f'{{$NE.IF.EXPECTED_SPEED:"{{#IFNAME}}"}}>0 and last({oper})=1 and '
                      f'min({speed},{{$NE.IF.SPEED.DEGRADED_FOR}})>0 and max({speed},{{$NE.IF.SPEED.DEGRADED_FOR}})<{{$NE.IF.EXPECTED_SPEED:"{{#IFNAME}}"}}',
        "name": "Network Explorer: {#IFNAME} below expected speed", "priority": "WARNING",
        "description": "Uses the explicit per-port override only. Derived expectations are shown by the frontend.",
        "tags": tags("interfaces")}]
    return {"uuid": uid("lld:interfaces"), "name": "Interface discovery", "type": "DEPENDENT",
            "key": "ne.interfaces.discovery", "delay": "0", "lifetime": "7d",
            "enabled_lifetime_type": "DISABLE_AFTER", "enabled_lifetime": "1d",
            "master_item": {"key": "ne.interfaces.inventory"},
            "description": "Fed from the complete inventory snapshot, so a partial walk never removes ports.",
            "preprocessing": js(gate("interfaces", "return JSON.stringify(e.data.map(function(r){return "
                                      "{uid:r.uid,name:r.name||r.description||r.uid,if_index:r.if_index,"
                                      "physical:r.physical===true?1:0};}));"), True),
            "lld_macro_paths": [{"lld_macro": "{#IFUID}", "path": "$.uid"},
                                {"lld_macro": "{#IFNAME}", "path": "$.name"},
                                {"lld_macro": "{#IFINDEX}", "path": "$.if_index"},
                                {"lld_macro": "{#IFPHYSICAL}", "path": "$.physical"}],
            "item_prototypes": prototypes}


def snapshot_field(match: str, field: str, convert: str = "") -> str:
    """One field of the first snapshot row that matches. A missing row or a null value throws, so the item keeps its
    last value instead of storing a guess."""
    return ("var a=JSON.parse(value).data; for(var i=0;i<a.length;i++){var r=a[i]; if(" + match + "){var v=r['" + field
            + "']; if(v===null||v===undefined){throw 'Not reported';}" + convert + " return v;}} "
            "throw 'Absent; retain last observed value';")


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
    snapshot = "ne.hardware.snapshot"
    if "global" in provides:
        item = dependent("ne.hw.global.state", "Hardware: overall status", "hardware", snapshot,
                         snapshot_field("r.kind==='global'", "state", HW_STATE_CONVERT), value_type="UNSIGNED",
                         discard=True, history="31d", trends="0", valuemap={"name": HW_STATE_MAP},
                         description="The device's own summary of its hardware health.")
        item["triggers"] = hardware_state_triggers(f"/{template}/ne.hw.global.state", "device", "overall status",
                                                   "global")[:2]
        items.append(item)
    if "cpu" in provides:
        for window in ("1m", "5m"):
            items.append(dependent(f"ne.hw.cpu.util[{window}]", f"Hardware: CPU utilisation, {window} average",
                                   "hardware", snapshot, snapshot_field("r.kind==='cpu'", f"util_{window}_pct"),
                                   value_type="FLOAT", discard=True, history="31d", units="%",
                                   description="As the device averages it. No value while measurement is off."))
        cpu = f"/{template}/ne.hw.cpu.util[5m]"
        items[-1]["triggers"] = [{
            "uuid": uid("trigger:hw:cpu"), "expression": f"min({cpu},{{$NE.HW.CPU.UTIL.FOR}})>{{$NE.HW.CPU.UTIL.MAX}}",
            "name": "Network Explorer: CPU utilisation above {$NE.HW.CPU.UTIL.MAX}% for {$NE.HW.CPU.UTIL.FOR}",
            "priority": "WARNING", "tags": tags("hardware")}]
    if "memory" in provides:
        memory = dependent("ne.hw.memory.util", "Hardware: memory utilisation", "hardware", snapshot,
                           snapshot_field("r.kind==='memory'", "util_pct"), value_type="FLOAT", discard=True,
                           history="31d", units="%")
        util = f"/{template}/ne.hw.memory.util"
        memory["triggers"] = [{
            "uuid": uid("trigger:hw:memory"),
            "expression": f"min({util},{{$NE.HW.MEMORY.UTIL.FOR}})>{{$NE.HW.MEMORY.UTIL.MAX}}",
            "name": "Network Explorer: memory utilisation above {$NE.HW.MEMORY.UTIL.MAX}% for {$NE.HW.MEMORY.UTIL.FOR}",
            "priority": "WARNING", "tags": tags("hardware")}]
        items.append(memory)
    return items


def hardware_discovery(entry: dict, template: str) -> list[dict]:
    rules = []
    for kind, stem, label in HW_PARTS:
        if kind not in entry["provides"]:
            continue
        match = f"r.kind==='{kind}'&&r.uid==='{{#HWUID}}'"
        state = dependent(f"{stem}.state[{{#HWUID}}]", f"{label.capitalize()} {{#HWNAME}}: state", "hardware",
                          "ne.hardware.snapshot", snapshot_field(match, "state", HW_STATE_CONVERT),
                          value_type="UNSIGNED", discard=True, history="31d", trends="0",
                          valuemap={"name": HW_STATE_MAP})
        state["trigger_prototypes"] = hardware_state_triggers(f"/{template}/{stem}.state[{{#HWUID}}]", label,
                                                              "{#HWNAME}", kind)
        prototypes = [state]
        if kind == "fan" and "fan_speed" in entry["provides"]:
            prototypes.append(dependent(f"{stem}.speed[{{#HWUID}}]", "Fan {#HWNAME}: speed", "hardware",
                                        "ne.hardware.snapshot", snapshot_field(match, "speed"), value_type="UNSIGNED",
                                        discard=True, history="31d",
                                        description="As the device reports it; the MIB gives no unit."))
        if kind == "temperature":
            prototypes.append(dependent(f"{stem}.value[{{#HWUID}}]", "Temperature sensor {#HWNAME}: temperature",
                                        "hardware", "ne.hardware.snapshot", snapshot_field(match, "celsius"),
                                        value_type="FLOAT", discard=True, history="31d", units="°C",
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
                      "master_item": {"key": "ne.hardware.snapshot"},
                      "description": "Fed from the complete hardware snapshot. A part is discovered while the device "
                                     "reports it present and readable.",
                      "preprocessing": js(gate("hardware", rows), True),
                      "lld_macro_paths": [{"lld_macro": "{#HWUID}", "path": "$.uid"},
                                          {"lld_macro": "{#HWNAME}", "path": "$.name"},
                                          {"lld_macro": "{#HWUNIT}", "path": "$.unit"}],
                      "item_prototypes": prototypes})
    return rules


def poe_discovery(entry: dict, template: str) -> list[dict]:
    """PSE units and PoE ports, each discovered from the complete snapshot. Faults are the device's own verdict; the
    usage alert uses the device's own threshold (pethMainPseUsageThreshold), never one of ours."""
    snapshot = "ne.poe.snapshot"
    pse = "r.kind==='pse'&&r.uid==='{#PSEUID}'"
    state = dependent("ne.poe.pse.state[{#PSEUID}]", "PoE {#PSENAME}: PSE status", "poe", snapshot,
                      snapshot_field(pse, "state", state_convert(POE_PSE_STATE)), value_type="UNSIGNED", discard=True,
                      history="31d", trends="0", valuemap={"name": POE_PSE_STATE_MAP})
    state["trigger_prototypes"] = [{
        "uuid": uid("trigger:poe:pse:faulty"), "expression": f"last(/{template}/ne.poe.pse.state[{{#PSEUID}}])=2",
        "name": "Network Explorer: PoE {#PSENAME} reports a fault", "priority": "HIGH",
        "description": "pethMainPseOperStatus is faulty, as the device reports it.", "tags": tags("poe")}]
    readings = [dependent(f"ne.poe.pse.{key}[{{#PSEUID}}]", f"PoE {{#PSENAME}}: {label}", "poe", snapshot,
                          snapshot_field(pse, field), value_type="FLOAT", discard=True, history="31d", units=units,
                          description=description)
                for key, label, field, units, description in (
                    ("power", "power budget", "power_w", "W", "Nominal power of the PSE (pethMainPsePower)."),
                    ("consumption", "power consumption", "consumption_w", "W",
                     "pethMainPseConsumptionPower as the device reports it. Some firmware reports the power "
                     "allocated to its ports here rather than the power they draw (Cisco 350-class, for example)."),
                    ("util", "budget used", "util_pct", "%", "Consumption as a share of the budget, the figure the "
                                                             "device compares with its usage threshold."),
                    ("threshold", "usage threshold", "usage_threshold_pct", "%",
                     "The device's own usage alarm threshold (pethMainPseUsageThreshold)."))]
    util, threshold = (f"/{template}/ne.poe.pse.{k}[{{#PSEUID}}]" for k in ("util", "threshold"))
    readings[2]["trigger_prototypes"] = [{
        "uuid": uid("trigger:poe:pse:usage"), "expression": f"last({util})>=last({threshold})",
        "name": "Network Explorer: PoE {#PSENAME} uses its budget above the device's usage threshold",
        "priority": "WARNING", "description": "The threshold is the one configured on the device.",
        "tags": tags("poe")}]
    pse_prototypes = [state, *readings]

    port = "r.kind==='port'&&r.uid==='{#POEUID}'"
    port_state = dependent("ne.poe.port.state[{#POEUID}]", "PoE port {#POENAME}: status", "poe", snapshot,
                           snapshot_field(port, "state", state_convert(POE_PORT_STATE)), value_type="UNSIGNED",
                           discard=True, history="31d", trends="0", valuemap={"name": POE_PORT_STATE_MAP},
                           description="pethPsePortDetectionStatus, as the device reports it.")
    port_state["trigger_prototypes"] = [{
        "uuid": uid("trigger:poe:port:fault"),
        "expression": f"last(/{template}/ne.poe.port.state[{{#POEUID}}])=3 or "
                      f"last(/{template}/ne.poe.port.state[{{#POEUID}}])=5",
        "name": "Network Explorer: PoE port {#POENAME} reports a fault", "priority": "WARNING",
        "description": "The port's detection status is fault or another fault, as the device reports it.",
        "tags": tags("poe")}]
    port_prototypes = [port_state]
    if "port_power" in entry["provides"]:
        port_prototypes.append(dependent("ne.poe.port.power[{#POEUID}]", "PoE port {#POENAME}: power", "poe", snapshot,
                                         snapshot_field(port, "power_mw", "v=v/1000;"), value_type="FLOAT",
                                         discard=True, history="31d", units="W",
                                         description="Power the port delivers, from the vendor MIB (milliwatts)."))
    for prototype in pse_prototypes:
        prototype["tags"].append({"tag": "poe", "value": "{#PSENAME}"})
    for prototype in port_prototypes:
        prototype["tags"].append({"tag": "poe", "value": "{#POENAME}"})
    rule = lambda key, name, rows, macros, prototypes, description: {
        "uuid": uid("lld:" + key), "name": name, "type": "DEPENDENT", "key": key, "delay": "0", "lifetime": "7d",
        "enabled_lifetime_type": "DISABLE_AFTER", "enabled_lifetime": "1d", "master_item": {"key": snapshot},
        "description": description, "preprocessing": js(gate("poe", rows), True),
        "lld_macro_paths": [{"lld_macro": m, "path": p} for m, p in macros], "item_prototypes": prototypes}
    return [
        rule("ne.poe.pse.discovery", "PoE discovery: PSE units",
             "return JSON.stringify(e.data.filter(function(r){return r.kind==='pse'&&r.state!=='not_present';})"
             ".map(function(r){return {uid:r.uid,name:r.name,unit:r.unit===null?'':String(r.unit)};}));",
             (("{#PSEUID}", "$.uid"), ("{#PSENAME}", "$.name"), ("{#PSEUNIT}", "$.unit")), pse_prototypes,
             "Fed from the complete PoE snapshot. A stack slot without a unit is not discovered."),
        rule("ne.poe.port.discovery", "PoE discovery: ports",
             "return JSON.stringify(e.data.filter(function(r){return r.kind==='port';}).map(function(r){return "
             "{uid:r.uid,name:r.name,unit:r.unit===null?'':String(r.unit),ifuid:r.interface_uid||''};}));",
             (("{#POEUID}", "$.uid"), ("{#POENAME}", "$.name"), ("{#POEUNIT}", "$.unit"), ("{#IFUID}", "$.ifuid")),
             port_prototypes,
             "Fed from the complete PoE snapshot. {#IFUID} is the interface the port joins to, where the template "
             "can tell; otherwise it is empty and the port is named by unit and port."),
    ]


def extras(short: str, template: str, mine: list[dict]) -> list[dict]:
    """Scalars a native trigger needs, read from the complete snapshot."""
    if short == "Hardware Health":
        return [item for entry in mine for item in hardware_scalars(entry, template)]
    if short == "Base":
        item = dependent("ne.device.uptime", "Device uptime", "device", "ne.device.snapshot",
                         "var d=JSON.parse(value).data[0]; if(!d||d.uptime_s===null) throw 'Unknown uptime'; return d.uptime_s;",
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
        bridge = "var a=JSON.parse(value).data; for(var i=0;i<a.length;i++){if(a[i].kind==='bridge'&&a[i].instance===0){var v=a[i]['%s']; if(v===null) throw 'Unknown'; return v;}} throw 'No instance 0';"
        root = dependent("ne.stp.root_bridge", "STP root bridge (instance 0)", "stp", "ne.stp.snapshot",
                         bridge % "root_bridge_id", value_type="CHAR", discard=True, history="31d")
        root["triggers"] = [{"uuid": uid("trigger:stp-root"), "expression": f"change(/{template}/ne.stp.root_bridge)=1",
                             "name": "Network Explorer: STP root bridge changed", "priority": "WARNING",
                             "manual_close": "YES", "tags": tags("stp")}]
        changes = dependent("ne.stp.topology_changes", "STP topology changes (instance 0)", "stp", "ne.stp.snapshot",
                            bridge % "topology_changes", value_type="UNSIGNED", discard=True, history="31d")
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
                    "description": "Expected speed in bit/s, with an interface-name context. 0 derives it from capability."},
                   {"macro": "{$NE.IF.SPEED.DEGRADED_FOR}", "value": "10m",
                    "description": "How long a port must run below its expected speed before alerting."}]
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
                rules += [rule for e in mine for rule in poe_discovery(e, name)]
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
        template["macros"] = sorted(macro_list, key=lambda m: m["macro"])
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
        return {"items": items, "macros": macro_list, "valuemaps": maps}
    finally:
        _scope = ""


def render(version: str) -> dict[str, str]:
    """One self-contained export per template, in a file named after its technical name."""
    return _common.split_exports(build(version)["zabbix_export"])


def host_dashboard() -> dict:
    """The switch host dashboard, inherited from the device template. Zabbix imports it whether or not the widget
    modules are installed; a widget whose module is missing or disabled shows as inaccessible."""
    port_panel = [{"type": "STRING", "name": "reference", "value": "NEPRT"}]
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
