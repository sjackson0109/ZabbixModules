#!/usr/bin/env python3
"""Build deterministic LAB ONLY replay templates. Does not poll network devices."""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
import uuid

import yaml

ROOT = Path(__file__).resolve().parent
NAME = "Network Explorer LAB replay"
GROUP = "Templates/Network Explorer/Lab"
NAMESPACE = uuid.UUID("b1971d94-1b92-4ccb-b784-df4f76490ea0")


def uid(name: str) -> str:
    # Zabbix imports require v4-shaped UUIDs. Hashing keeps ownership reproducible.
    digest = hashlib.sha256(NAMESPACE.bytes + name.encode("utf-8")).digest()[:16]
    return uuid.UUID(bytes=digest, version=4).hex


def js(script: str, discard: bool = False) -> dict:
    step = {"type": "JAVASCRIPT", "parameters": [script]}
    if discard:
        step["error_handler"] = "DISCARD_VALUE"
    return step


def tags(dataset: str) -> list[dict]:
    return [{"tag": "component", "value": "network-explorer"},
            {"tag": "dataset", "value": dataset},
            {"tag": "data_source", "value": "lab-replay"}]


def item(key: str, name: str, dataset: str, *, master: str | None = None,
         script: str | None = None, value_type: str = "TEXT", discard: bool = False) -> dict:
    result = {"uuid": uid(key), "name": name,
              "type": "DEPENDENT" if master else "TRAP",
              "key": key, "delay": "0", "history": "7d", "value_type": value_type,
              "trends": "0", "tags": tags(dataset)}
    if master:
        result["master_item"] = {"key": master}
    if script:
        result["preprocessing"] = [js(script, discard)]
    return result


def gate(dataset: str) -> str:
    identity = ""
    if dataset == "interfaces":
        identity = ("var seen={}; for(var i=0;i<e.data.length;i++){var r=e.data[i];"
                    "if(!r||typeof r.uid!=='string'||!/^[a-z0-9][a-z0-9_-]{0,79}$/.test(r.uid)||"
                    "Object.prototype.hasOwnProperty.call(seen,r.uid)||typeof r.if_index!=='number'||"
                    "r.if_index<1||Math.floor(r.if_index)!==r.if_index) throw 'Unsafe or ambiguous interface identity';"
                    "seen[r.uid]=true;}")
    return ("var e=JSON.parse(value); if(e.schema_version!=='1.0'||e.dataset!==" +
            repr(dataset) + "||e.status!=='ok'||e.complete!==true||!Array.isArray(e.data)) "
            "throw 'Incomplete or invalid snapshot; retain last success'; "
            "if(typeof e.observed_at!=='string'||!/^\\d{4}-\\d{2}-\\d{2}T\\d{2}:\\d{2}:\\d{2}(?:\\.\\d+)?Z$/.test(e.observed_at)||!isFinite(Date.parse(e.observed_at))) "
            "throw 'Invalid observation timestamp'; " + identity + "return value;")


def scalar(field: str, *, unknown: int | None = None) -> str:
    missing = f"return {unknown};" if unknown is not None else "throw 'Unknown scalar';"
    convert = ""
    if field in ("admin_status", "oper_status"):
        enum = {"up": 1, "down": 2, "testing": 3, "unknown": 4,
                "dormant": 5, "not_present": 6, "lower_layer_down": 7}
        convert = "if(typeof v==='string'){var m=" + str(enum).replace("'", '"') + ";if(m[v]===undefined) throw 'Unknown status enum';v=m[v];}"
    return ("var e=JSON.parse(value),a=e.data; for(var i=0;i<a.length;i++){"
            "if(a[i].uid==='{#IFUID}'){var v=a[i][" + repr(field) + "];"
            "if(v===null||v===undefined){" + missing + "}" + convert + "return v;}} "
            "throw 'Interface absent; retain last observed value';")


def build(version: str) -> dict:
    items = []
    for dataset in ("device", "interfaces", "lldp", "lag"):
        attempt = f"ne.{dataset}.attempt"
        items.append(item(attempt, f"LAB {dataset}: replay attempt", dataset,
                          script="var e=JSON.parse(value); if(e.schema_version!=='1.0'||e.dataset!==" +
                          repr(dataset) + "||!Array.isArray(e.data)||typeof e.complete!=='boolean'||"
                          "['ok','partial','failed','unsupported'].indexOf(e.status)<0||"
                          "typeof e.generation_id!=='string'||!e.generation_id||"
                          "typeof e.attempted_at!=='string'||!isFinite(Date.parse(e.attempted_at))||"
                          "!e.source||!e.capability||!Array.isArray(e.errors)||"
                          "(e.status==='ok'&&(e.complete!==true||typeof e.observed_at!=='string'||!isFinite(Date.parse(e.observed_at))))) "
                          "throw 'Invalid replay envelope'; return value;"))
        keys = ["ne.interfaces.inventory", "ne.interfaces.state"] if dataset == "interfaces" else [f"ne.{dataset}.snapshot"]
        for key in keys:
            items.append(item(key, f"LAB {dataset}: last complete successful snapshot", dataset,
                              master=attempt, script=gate(dataset), discard=True))
        items.append(item(f"ne.collection.status[{dataset}]", f"LAB {dataset}: last attempt status", dataset,
                          master=attempt, value_type="UNSIGNED",
                          script="var s=JSON.parse(value).status; return {ok:0,partial:1,failed:2,unsupported:3}[s];"))
        items[-1]["valuemap"] = {"name": "Network Explorer collection status"}
        items.append(item(f"ne.collection.success[{dataset}]", f"LAB {dataset}: last complete observation epoch", dataset,
                          master=attempt, value_type="UNSIGNED", discard=True,
                          script=gate(dataset).replace("return value;", "var t=Date.parse(e.observed_at); if(!isFinite(t)) throw 'Invalid observed_at'; return Math.floor(t/1000);")))
        items[-1]["units"] = "unixtime"
        stale = f"nodata(/{NAME}/ne.collection.success[{dataset}],{{$NE.{dataset.upper()}.STALE}})=1"
        items[-1]["triggers"] = [{"uuid": uid("stale:" + dataset), "name": f"LAB {dataset}: no complete observation within stale threshold",
                                  "expression": stale, "priority": "WARNING", "tags": tags(dataset),
                                  "description": "Replay lab diagnostic only. Partial or failed attempts do not refresh success age."}]
    prototypes = []
    for field, key, label, unknown in (
        ("oper_status", "ne.if.oper", "operational status", None),
        ("admin_status", "ne.if.admin", "administrative status", None),
        ("speed_bps", "ne.if.speed", "negotiated speed", None),
        ("expected_speed_bps", "ne.if.expected.speed", "explicit expected speed (0 means unknown)", 0),
    ):
        prototype = item(key + "[{#IFUID}]", "LAB {#IFNAME}: " + label, "interfaces",
                         master="ne.interfaces.state", script=scalar(field, unknown=unknown),
                         value_type="UNSIGNED", discard=True)
        prototype["tags"].append({"tag": "interface_uid", "value": "{#IFUID}"})
        if "speed" in field:
            prototype["units"] = "bps"
        prototypes.append(prototype)
    duplex = item("ne.if.duplex[{#IFUID}]", "LAB {#IFNAME}: observed duplex", "interfaces",
                  master="ne.interfaces.state", script=scalar("duplex"), value_type="CHAR", discard=True)
    prototypes.append(duplex)
    discovery = [{"uuid": uid("interfaces-discovery"), "name": "LAB complete interface inventory discovery",
                  "type": "DEPENDENT", "key": "ne.interfaces.discovery", "delay": "0",
                  "lifetime": "7d", "enabled_lifetime_type": "DISABLE_AFTER", "enabled_lifetime": "1d",
                  "master_item": {"key": "ne.interfaces.inventory"},
                  "preprocessing": [js(gate("interfaces").replace("return value;", "var rows=e.data.map(function(r){var x=JSON.parse(JSON.stringify(r));x.name=x.name||x.description||x.uid;return x;});return JSON.stringify(rows);"), True)],
                  "lld_macro_paths": [{"lld_macro": "{#IFUID}", "path": "$.uid"},
                                      {"lld_macro": "{#IFNAME}", "path": "$.name"},
                                      {"lld_macro": "{#IFINDEX}", "path": "$.if_index"}],
                  "item_prototypes": prototypes,
                  "graph_prototypes": [{"uuid": uid("lab-speed-graph"),
                                        "name": "LAB {#IFNAME}: negotiated speed",
                                        "graph_items": [{"color": "199C0D", "item": {"host": NAME, "key": "ne.if.speed[{#IFUID}]"}}]}]}]
    pages = [
        {"name": "Overview", "widgets": [widget("nedataquality", "Collection quality", 0, 0, 72, 4),
                                           widget("neportpanel", "Port panel", 0, 4, 48, 9) | {"fields": [{"type": "STRING", "name": "reference", "value": "NEPRT"}]},
                                           widget("neinterfacedetail", "Interface detail", 48, 4, 24, 9) | {"fields": [{"type": "STRING", "name": "itemid._reference", "value": "NEPRT._itemid"}]}]},
        {"name": "Connectivity", "widgets": [widget("netopology", "Physical topology and LAG", 0, 0, 48, 12),
                                               widget("neinterfacedetail", "Interface detail", 48, 0, 24, 12),
                                               widget("graphprototype", "Negotiated speed history (replayed lab values)", 0, 12, 72, 5) | {
                                                   "fields": [{"type": "INTEGER", "name": "columns", "value": "1"},
                                                              {"type": "GRAPH_PROTOTYPE", "name": "graphid.0",
                                                               "value": {"host": NAME, "name": "LAB {#IFNAME}: negotiated speed"}}]}]},
        {"name": "Diagnostics", "widgets": [widget("nedataquality", "Dataset quality", 0, 0, 72, 7),
                                              widget("nefindings", "Evidence and findings", 0, 7, 72, 10)]},
    ]
    template = {"uuid": uid(NAME), "template": NAME, "name": NAME,
                "description": "LAB ONLY. Zabbix sender/trapper fixture replay for Network Explorer contract testing. No SNMP polling; never link to production network hosts. Registered custom widgets are required for dashboards.",
                "vendor": {"name": "Network Explorer", "version": "0.1.0-lab"},
                "groups": [{"name": GROUP}], "items": items, "discovery_rules": discovery,
                "macros": [{"macro": "{$NE." + d.upper() + ".STALE}", "value": stale,
                            "description": "Maximum complete observation age; laboratory replay only."}
                           for d, stale in (("device", "2d"), ("interfaces", "5m"), ("lldp", "15m"), ("lag", "15m"))],
                "dashboards": [{"uuid": uid("lab-host-dashboard"), "name": "Network Explorer LAB", "pages": pages}],
                "valuemaps": [{"uuid": uid("collection-status"), "name": "Network Explorer collection status",
                               "mappings": [{"value": str(i), "newvalue": s} for i, s in enumerate(("ok", "partial", "failed", "unsupported"))]}]}
    return {"zabbix_export": {"version": version,
                             "template_groups": [{"uuid": uid(GROUP), "name": GROUP}],
                             "templates": [template]}}


def widget(kind: str, name: str, x: int, y: int, width: int, height: int) -> dict:
    return {"type": kind, "name": name, "x": str(x), "y": str(y),
            "width": str(width), "height": str(height)}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="Fail if generated files differ.")
    args = parser.parse_args()
    for version in ("7.0", "7.2", "7.4"):
        target = ROOT / "lab" / version / "network_explorer_lab.yaml"
        output = yaml.safe_dump(build(version), sort_keys=False, allow_unicode=True, width=110)
        if args.check:
            if not target.exists() or target.read_text() != output:
                raise SystemExit(f"Generated file differs: {target}")
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(output)


if __name__ == "__main__":
    main()
