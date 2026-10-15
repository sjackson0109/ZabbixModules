#!/usr/bin/env python3
"""Build the deterministic Wi-Fi Explorer native SNMP templates for Zabbix 7.0, 7.2 and 7.4.

Each producer in templates/source/wifi/datasets.json becomes one walk[] master item, a JavaScript normaliser that
emits the canonical Wi-Fi envelope, and gated dependents that only accept complete observations: the same item
pattern as the Network Explorer templates (templates/generate_snmp.py). The JavaScript is composed exactly as
tests/js/run_normaliser.cjs composes it, so the code tested in Node is the code Zabbix runs.

The templates carry no credentials, no API token and no per-AP or per-client items: clients are one bounded
snapshot per owner, masked by {$WE.CLIENT.IDENTIFIERS} before it is stored. Wi-Fi Explorer reads the owner's
snapshots in the frontend, under the viewing user's permissions.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _common  # noqa: E402
from _common import COLLECTION_STATUS, STATUS_MAP, VERSION, dump, js, read_text, widget, write_outputs  # noqa: E402

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "source"
MANIFEST = SOURCE / "wifi" / "datasets.json"
GROUP = "Templates/Wi-Fi Explorer"
PREFIX = "Wi-Fi Explorer - "
SUFFIX = " by SNMP"
FAILED = "__NE_COLLECTION_FAILED__"
SCHEMA = "wifi-1.0"
NAMESPACE = uuid.UUID("0f6c55d2-3b4e-4f51-a0de-6f2b0f1c7e3a")


def uid(name: str) -> str:
    return _common.uid(NAMESPACE, name)


def manifest() -> dict:
    return json.loads(read_text(MANIFEST))


def compose(entry: dict) -> str:
    """Same composition as tests/js/run_normaliser.cjs for an entry that lists its scripts."""
    parts = [read_text(SOURCE / "js" / name) for name in entry["scripts"]]
    parts.append(f"return JSON.stringify(WE.run('{entry['dataset']}', '{entry['adapter']}', value, "
                 f"function (w, e) {{ return {entry['call']}; }}));")
    return "\n".join(parts)


def tags(dataset: str) -> list[dict]:
    return [{"tag": "component", "value": "wifi-explorer"}, {"tag": "dataset", "value": dataset},
            {"tag": "data_source", "value": "native-snmp"}]


def stale_macro(entry: dict) -> str:
    return entry["interval_macro"].replace(".INTERVAL}", ".STALE}")


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
    return _common.gate(SCHEMA, dataset, then)


def raw_item(entry: dict) -> dict:
    return {"uuid": uid("item:" + entry["raw_key"]), "name": f"Raw SNMP walk: {entry['dataset']}",
            "type": "SNMP_AGENT", "snmp_oid": "walk[" + ",".join(entry["walk"]) + "]", "key": entry["raw_key"],
            "delay": entry["interval_macro"], "history": "0", "value_type": "TEXT", "trends": "0",
            "description": "Input for the canonical normaliser only; not stored. A timeout or SNMP error becomes "
                           "a failed attempt instead of making the dataset silently disappear.",
            "preprocessing": [{"type": "CHECK_NOT_SUPPORTED", "parameters": ["-1"],
                               "error_handler": "CUSTOM_VALUE", "error_handler_params": FAILED}],
            "tags": tags(entry["dataset"])}


# A complete, successful attempt is stored as a receipt: its rows are already in the snapshot item, so storing
# them twice would double the dataset's history. Partial, failed and unsupported attempts are kept whole.
RECEIPT = ("var e=JSON.parse(value); if(e.status==='ok'&&e.complete===true&&Array.isArray(e.data)){"
           "e.data_rows=e.data.length; e.data=[]; e.data_omitted=true;} return JSON.stringify(e);")


# Cluster-level numbers from each complete observation, stored as numeric items so that Zabbix keeps trends for
# them: the long-term capacity views read those trends. An observation that cannot give a number (no radio in a
# band reports utilisation, no client is matched to an AP) stores nothing rather than a zero.
BANDS = ("2.4", "5", "6")
COUNT = "var n=0; for(var i=0;i<e.data.length;i++){if(%s){n++;}} return n;"
UTILISATION = ("var v=[]; for(var i=0;i<e.data.length;i++){var r=e.data[i]; if(r.status==='up'&&r.band==='%s'&&"
               "typeof r.utilisation_percent==='number'){v.push(r.utilisation_percent);}} "
               "if(!v.length){throw 'No utilisation in this band';} %s")
CAPACITY = {
    "ap_state": [("we.capacity.aps.up", "Capacity: APs up", COUNT % "e.data[i].status==='up'", "UNSIGNED", ""),
                 ("we.capacity.aps.down", "Capacity: APs down", COUNT % "e.data[i].status==='down'", "UNSIGNED", "")],
    "radio_state": [item for band in BANDS for item in [
        (f"we.capacity.radios.up[{band}]", f"Capacity: radios up, {band} GHz",
         COUNT % f"e.data[i].status==='up'&&e.data[i].band==='{band}'", "UNSIGNED", ""),
        (f"we.capacity.utilisation.avg[{band}]", f"Capacity: average channel utilisation, {band} GHz",
         UTILISATION % (band, "var t=0; for(var j=0;j<v.length;j++){t+=v[j];} return t/v.length;"), "FLOAT", "%"),
        (f"we.capacity.utilisation.max[{band}]", f"Capacity: highest channel utilisation, {band} GHz",
         UTILISATION % (band, "return Math.max.apply(null, v);"), "FLOAT", "%")]],
    "client": [("we.capacity.clients", "Capacity: clients associated", "return e.data.length;", "UNSIGNED", ""),
               ("we.capacity.clients.ap_max", "Capacity: most clients on one AP",
                "var c={}, m=-1; for(var i=0;i<e.data.length;i++){var a=e.data[i].ap_uid; if(a){c[a]=(c[a]||0)+1; "
                "if(c[a]>m){m=c[a];}}} if(m<0){throw 'No client is matched to an AP';} return m;", "UNSIGNED", "")],
}


def capacity_items(entry: dict) -> list[dict]:
    dataset = entry["dataset"]
    return [dependent(key, name, dataset, normalised_key(dataset), gate(dataset, script), value_type=value_type,
                      discard=True, history="{$WE.CAPACITY.HISTORY}", trends="{$WE.CAPACITY.TRENDS}", units=units,
                      description="From each complete observation only, for the long-term capacity views; "
                                  "no value when the observation cannot give one.")
            for key, name, script, value_type, units in CAPACITY.get(dataset, [])]


def history_macro(entry: dict) -> str:
    return entry["interval_macro"].replace(".INTERVAL}", ".HISTORY}")


def normalised_key(dataset: str) -> str:
    return f"we.normalised[{dataset}]"


def producer_items(entry: dict, template: str) -> list[dict]:
    dataset, history = entry["dataset"], history_macro(entry)
    attempt, normalised = entry["attempt_key"], normalised_key(dataset)
    items = [raw_item(entry),
             dependent(normalised, f"Normalised envelope: {dataset}", dataset, entry["raw_key"], compose(entry),
                       history="0",
                       description="The canonical envelope of each attempt, passed to the items below; not stored."),
             dependent(attempt, f"Collection attempt: {dataset}", dataset, normalised, RECEIPT,
                       history=history,
                       description="Every attempt, including partial, failed and unsupported. A complete success is "
                                   "stored as a receipt without its rows, which are in the snapshot.")]
    for key in entry["snapshot_keys"]:
        items.append(dependent(key, f"Last complete snapshot: {dataset}", dataset, normalised, gate(dataset),
                               discard=True, history=history,
                               description="Updated only by complete, successful observations."))
    status = dependent(f"we.collection.status[{dataset}]", f"Collection status: {dataset}", dataset, normalised,
                       COLLECTION_STATUS, value_type="UNSIGNED", history="31d", trends="0",
                       valuemap={"name": STATUS_MAP})
    success = dependent(f"we.collection.success[{dataset}]", f"Last complete observation: {dataset}", dataset,
                        normalised, gate(dataset, "return Math.floor(Date.parse(e.observed_at)/1000);"),
                        value_type="UNSIGNED", discard=True, history="31d", trends="0", units="unixtime")
    stale = stale_macro(entry)
    success["triggers"] = [{
        "uuid": uid("trigger:stale:" + template + ":" + dataset),
        "expression": f"nodata(/{template}/we.collection.success[{dataset}],{stale})=1 and "
                      f"last(/{template}/we.collection.status[{dataset}])<>3",
        "name": f"Wi-Fi Explorer: no complete {dataset} observation for {stale}",
        "priority": "WARNING",
        "description": "Partial and failed attempts never refresh this age. An unsupported dataset (for example on "
                       "a member AP) does not alert.",
        "tags": tags(dataset)}]
    return items + [status, success] + capacity_items(entry)


def macros(entries: list[dict], extra: list[dict]) -> list[dict]:
    result = [dict(m) for m in extra]
    for entry in entries:
        result.append({"macro": entry["interval_macro"], "value": entry["interval"],
                       "description": f"Polling interval for {entry['dataset']}."})
        result.append({"macro": stale_macro(entry), "value": entry["stale"],
                       "description": f"Maximum age of a complete {entry['dataset']} observation."})
        result.append({"macro": history_macro(entry), "value": entry["history"],
                       "description": f"How long {entry['dataset']} snapshots and attempts are kept."})
    return sorted(result, key=lambda m: m["macro"])


def item_field(name: str, template: str, key: str) -> dict:
    return {"type": "ITEM", "name": name, "value": {"host": template, "key": key}}


def graph(name: str, template: str, keys: list[str], x: int, y: int) -> dict:
    fields = [{"type": "INTEGER", "name": "ds.0.dataset_type", "value": "0"}]  # a list of items, not a pattern
    fields += [item_field(f"ds.0.itemids.{i}", template, key) for i, key in enumerate(keys)]
    return widget("svggraph", name, x, y, 36, 5, fields)


def cluster_dashboard(template: str) -> dict:
    """The cluster host dashboard, built only from Zabbix's own widgets and the capacity items, so it works without
    any widget module. Floors, paths, findings and clients stay on the Wi-Fi Explorer page."""
    tiles = [("APs up", "we.capacity.aps.up"), ("APs down", "we.capacity.aps.down"),
             ("Clients associated", "we.capacity.clients"), ("Most clients on one AP", "we.capacity.clients.ap_max")]
    widgets = [widget("item", name, 18 * i, 0, 18, 3, [item_field("itemid.0", template, key)])
               for i, (name, key) in enumerate(tiles)]
    widgets += [graph("Clients", template, ["we.capacity.clients", "we.capacity.clients.ap_max"], 0, 3),
                graph("APs up and down", template, ["we.capacity.aps.up", "we.capacity.aps.down"], 36, 3),
                graph("Average channel utilisation by band", template,
                      [f"we.capacity.utilisation.avg[{band}]" for band in BANDS], 0, 8),
                graph("Radios up by band", template, [f"we.capacity.radios.up[{band}]" for band in BANDS], 36, 8)]
    return {"uuid": uid("dashboard:" + template), "name": "Wi-Fi Explorer", "auto_start": "NO",
            "pages": [{"name": "Capacity", "widgets": widgets}]}


# Templates that carry a host dashboard: the cluster's virtual controller owns the capacity items.
DASHBOARDS = {"Aruba Instant VC": cluster_dashboard}


def build(version: str) -> dict:
    source = manifest()
    templates = []
    for short, meta in source["templates"].items():
        name = PREFIX + short + SUFFIX
        mine = [e for e in source["datasets"] if e["template"] == short]
        template = {
            "uuid": uid("template:" + name), "template": name, "name": name,
            "description": meta["description"] + " Generated by templates/generate_wifi.py; do not edit by hand. "
                           "It reads only the host's SNMP interface and carries no credentials.",
            "vendor": {"name": "Network Explorer", "version": VERSION},
            "groups": [{"name": GROUP}],
            "items": [i for e in mine for i in producer_items(e, name)],
            "tags": [{"tag": "component", "value": "wifi-explorer"}],
            "macros": macros(mine, meta.get("macros", [])),
            "valuemaps": [{"uuid": uid(f"valuemap:{short}:status"), "name": STATUS_MAP,
                           "mappings": [{"value": str(i), "newvalue": s}
                                        for i, s in enumerate(("ok", "partial", "failed", "unsupported"))]}]}
        if short in DASHBOARDS:
            template["dashboards"] = [DASHBOARDS[short](name)]
        templates.append(template)
    return {"zabbix_export": {"version": version, "template_groups": [{"uuid": uid("group:" + GROUP), "name": GROUP}],
                              "templates": templates}}


def render(version: str) -> str:
    return dump(build(version))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Fail if generated files differ.")
    args = parser.parse_args()
    write_outputs({ROOT / "native" / version / "wifi_explorer_snmp.yaml": render(version)
                   for version in ("7.0", "7.2", "7.4")}, args.check)


if __name__ == "__main__":
    main()
