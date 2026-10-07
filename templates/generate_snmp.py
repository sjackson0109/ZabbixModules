#!/usr/bin/env python3
"""Build the deterministic native SNMP templates (generic standard MIB) for Zabbix 7.0, 7.2 and 7.4.

Each dataset producer in templates/source/datasets.json becomes one walk[] master item, a
JavaScript normaliser that emits the canonical envelope, and gated dependents that only
accept complete observations. The JavaScript is composed exactly as tests/js/run_normaliser.cjs
composes it, so the code tested in Node is the code Zabbix runs.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import uuid

import yaml

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "source"
GROUP = "Templates/Network Explorer"
PREFIX = "Network Explorer - "
PROFILE = PREFIX + "Profile - Generic standard MIB"
DASHBOARD = PREFIX + "Host dashboard"
VERSION = "0.2.0"
FAILED = "__NE_COLLECTION_FAILED__"
DISCARD = "__NE_DISCARD__"
SCHEMA = "1.1"
NAMESPACE = uuid.UUID("5b0f8e0a-6f0e-4a55-9d0c-2a7f3c1e9b44")
STATUS_MAP = "Network Explorer collection status"
IF_STATUS_MAP = "Network Explorer interface status"
IF_STATUS = {"up": 1, "down": 2, "testing": 3, "unknown": 4, "dormant": 5, "not_present": 6, "lower_layer_down": 7}
TEMPLATE_DESCRIPTION = {
    "Base": "Device identity, chassis and stack members (SNMPv2-MIB, ENTITY-MIB, LLDP local system).",
    "Interfaces": "Interface inventory and state (IF-MIB, ifXTable, EtherLike) with interface discovery.",
    "Port Capability": "Supported and advertised port speeds (MAU-MIB) used to derive expected speed.",
    "LLDP": "LLDP neighbours with dot1 and dot3 extensions. Set {$NE.LLDP.REDACT_REMOTE} to 1 to drop remote descriptions.",
    "VLAN": "VLAN table and per-port membership (Q-BRIDGE-MIB).",
    "STP": "Spanning tree bridge and port state (BRIDGE-MIB, RSTP-MIB), instance 0.",
    "LAG": "Link aggregation bundles and members (IEEE8023-LAG-MIB, ifStackTable).",
}


def uid(name: str) -> str:
    # Zabbix imports require v4-shaped UUIDs. Hashing keeps ownership reproducible.
    digest = hashlib.sha256(NAMESPACE.bytes + name.encode("utf-8")).digest()[:16]
    return uuid.UUID(bytes=digest, version=4).hex


def manifest() -> list[dict]:
    return json.loads((SOURCE / "datasets.json").read_text())["datasets"]


def compose(entry: dict) -> str:
    """Same composition as tests/js/run_normaliser.cjs."""
    read = lambda name: (SOURCE / "js" / name).read_text()  # noqa: E731
    return "\n".join([read("lib.js"), read(entry["script"]),
                      f"return JSON.stringify(NE.run('{entry['dataset']}', '{entry['adapter']}', value, "
                      f"function (w, e) {{ return {entry['call']}; }}));"])


def producer(entry: dict) -> str:
    return entry["dataset"] + ("." + entry["variant"] if entry.get("variant") else "")


def stale_macro(entry: dict) -> str:
    return entry["interval_macro"].replace(".INTERVAL}", ".STALE}")


def js(script: str, discard: bool = False) -> list[dict]:
    """A JavaScript step. Zabbix offers no custom on-fail for JavaScript (an import silently drops it), so a
    discarding gate returns a sentinel that the following regular-expression step discards."""
    if not discard:
        return [{"type": "JAVASCRIPT", "parameters": [script]}]
    wrapped = ("try { return (function (value) {\n" + script + "\n})(value); } catch (error) { return '" + DISCARD + "'; }")
    return [{"type": "JAVASCRIPT", "parameters": [wrapped]},
            {"type": "NOT_MATCHES_REGEX", "parameters": ["^" + DISCARD + "$"], "error_handler": "DISCARD_VALUE"}]


def tags(dataset: str) -> list[dict]:
    return [{"tag": "component", "value": "network-explorer"}, {"tag": "dataset", "value": dataset},
            {"tag": "data_source", "value": "native-snmp"}]


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
    identity = ""
    if dataset == "interfaces":
        identity = ("var seen={}; for(var i=0;i<e.data.length;i++){var r=e.data[i];"
                    "if(!r||typeof r.uid!=='string'||!/^[a-z0-9][a-z0-9_-]{0,79}$/.test(r.uid)||"
                    "Object.prototype.hasOwnProperty.call(seen,r.uid)||typeof r.if_index!=='number'||"
                    "r.if_index<1||Math.floor(r.if_index)!==r.if_index) throw 'Unsafe or ambiguous interface identity';"
                    "seen[r.uid]=true;} ")
    return (f"var e=JSON.parse(value); if(e.schema_version!=='{SCHEMA}'||e.dataset!=='{dataset}'||e.status!=='ok'||"
            "e.complete!==true||!Array.isArray(e.data)) throw 'Incomplete or invalid snapshot; retain last success'; "
            "if(typeof e.observed_at!=='string'||!isFinite(Date.parse(e.observed_at))) throw 'Invalid observation timestamp'; "
            + identity + then)


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
                       "var s=JSON.parse(value).status; var m={ok:0,partial:1,failed:2,unsupported:3}; "
                       "if(m[s]===undefined) throw 'Unknown status'; return m[s];",
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
    def scalar(field: str, unknown: str, convert: str = "") -> str:
        # An unknown fact is a value (so the item stays supported); only an absent interface is discarded.
        return ("var a=JSON.parse(value).data; for(var i=0;i<a.length;i++){if(a[i].uid==='{#IFUID}'){var v=a[i]['"
                + field + "']; if(v===null||v===undefined) return " + unknown + ";" + convert
                + " return v;}} throw 'Interface absent; retain last observed value';")

    status = "var m=" + json.dumps(IF_STATUS) + "; v=m[v]===undefined?4:m[v];"
    prototypes = []
    for field, key, label, value_type, unknown, convert in (
        ("oper_status", "ne.if.oper", "operational status", "UNSIGNED", "4", status),
        ("admin_status", "ne.if.admin", "administrative status", "UNSIGNED", "4", status),
        ("speed_bps", "ne.if.speed", "negotiated speed (0 = unknown)", "UNSIGNED", "0", ""),
        ("duplex", "ne.if.duplex", "duplex", "CHAR", "'unknown'", ""),
    ):
        extra = {"trends": "0"} if value_type == "UNSIGNED" else {}
        if field.endswith("status"):
            extra["valuemap"] = {"name": IF_STATUS_MAP}
        if field == "speed_bps":
            extra = {"units": "bps"}
        prototype = dependent(key + "[{#IFUID}]", "{#IFNAME}: " + label, "interfaces", "ne.interfaces.state",
                              scalar(field, unknown, convert), value_type=value_type, discard=True, history="31d", **extra)
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


def extras(short: str, template: str) -> list[dict]:
    """Scalars a native trigger needs, read from the complete snapshot."""
    if short == "Base":
        item = dependent("ne.device.uptime", "Device uptime", "device", "ne.device.snapshot",
                         "var d=JSON.parse(value).data[0]; if(!d||d.uptime_s===null) throw 'Unknown uptime'; return d.uptime_s;",
                         value_type="UNSIGNED", discard=True, history="31d", trends="0", units="uptime")
        item["triggers"] = [{"uuid": uid("trigger:rebooted"), "expression": f"last(/{template}/ne.device.uptime)<600",
                             "name": "Network Explorer: device restarted", "priority": "INFO",
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
    return sorted(result, key=lambda m: m["macro"])


def valuemaps(short: str) -> list[dict]:
    maps = [{"uuid": uid(f"valuemap:{short}:status"), "name": STATUS_MAP,
             "mappings": [{"value": str(i), "newvalue": s} for i, s in enumerate(("ok", "partial", "failed", "unsupported"))]}]
    if short == "Interfaces":
        maps.append({"uuid": uid("valuemap:interfaces:if-status"), "name": IF_STATUS_MAP,
                     "mappings": [{"value": str(v), "newvalue": k} for k, v in IF_STATUS.items()]})
    return maps


def build(version: str) -> dict:
    entries = manifest()
    order = list(dict.fromkeys(e["template"] for e in entries))
    templates = []
    for short in order:
        name = PREFIX + short
        mine = [e for e in entries if e["template"] == short]
        items = [i for e in mine for i in producer_items(e, name)] + extras(short, name)
        template = {"uuid": uid("template:" + name), "template": name, "name": name,
                    "description": TEMPLATE_DESCRIPTION[short] + " Generated by templates/generate_snmp.py; do not edit by hand. "
                                   "Link through a Network Explorer profile so each dataset has exactly one producer.",
                    "vendor": {"name": "Network Explorer", "version": VERSION},
                    "groups": [{"name": GROUP}], "items": items}
        if short == "Interfaces":
            template["discovery_rules"] = [interface_discovery(name)]
        template["tags"] = [{"tag": "component", "value": "network-explorer"}]
        template["macros"] = macros(mine, short)
        template["valuemaps"] = valuemaps(short)
        templates.append(template)
    templates.append({"uuid": uid("template:" + PROFILE), "template": PROFILE, "name": PROFILE,
                      "description": "Link this one template to a switch that has an SNMP interface. It links every "
                                     "standard-MIB producer; datasets the device lacks report unsupported without "
                                     "affecting the others. Generated by templates/generate_snmp.py.",
                      "vendor": {"name": "Network Explorer", "version": VERSION},
                      "templates": [{"name": PREFIX + short} for short in order],
                      "groups": [{"name": GROUP}],
                      "tags": [{"tag": "component", "value": "network-explorer"}]})
    return {"zabbix_export": {"version": version, "template_groups": [{"uuid": uid("group:" + GROUP), "name": GROUP}],
                              "templates": templates}}


def render(version: str) -> str:
    return yaml.safe_dump(build(version), sort_keys=False, allow_unicode=True, width=110)


def widget(kind: str, name: str, x: int, y: int, width: int, height: int, fields: list[dict] | None = None) -> dict:
    result = {"type": kind, "name": name, "x": str(x), "y": str(y), "width": str(width), "height": str(height)}
    if fields:
        result["fields"] = fields
    return result


def build_dashboard(version: str) -> dict:
    """A template holding only the host dashboard, kept apart because importing it needs the widget modules."""
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
    template = {"uuid": uid("template:" + DASHBOARD), "template": DASHBOARD, "name": DASHBOARD,
                "description": "Optional. Link to a switch alongside a Network Explorer profile to give it the Network "
                               "Explorer host dashboard. Import it after the frontend modules are installed and enabled. "
                               "Generated by templates/generate_snmp.py.",
                "vendor": {"name": "Network Explorer", "version": VERSION},
                "groups": [{"name": GROUP}],
                "tags": [{"tag": "component", "value": "network-explorer"}],
                "dashboards": [{"uuid": uid("dashboard:" + DASHBOARD), "name": "Network Explorer",
                                "auto_start": "NO", "pages": pages}]}
    return {"zabbix_export": {"version": version, "template_groups": [{"uuid": uid("group:" + GROUP), "name": GROUP}],
                              "templates": [template]}}


def render_dashboard(version: str) -> str:
    return yaml.safe_dump(build_dashboard(version), sort_keys=False, allow_unicode=True, width=110)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Fail if generated files differ.")
    args = parser.parse_args()
    for version in ("7.0", "7.2", "7.4"):
        for name, output in (("network_explorer_snmp.yaml", render(version)),
                             ("network_explorer_dashboard.yaml", render_dashboard(version))):
            target = ROOT / "native" / version / name
            if args.check:
                if not target.exists() or target.read_text() != output:
                    raise SystemExit(f"Generated file differs: {target}")
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(output)


if __name__ == "__main__":
    main()
