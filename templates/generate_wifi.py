#!/usr/bin/env python3
"""Build the deterministic Wi-Fi Explorer native SNMP templates for Zabbix 7.0, 7.2 and 7.4, one file per template.

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

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _common  # noqa: E402
import generate_snmp  # noqa: E402
from _common import COLLECTION_STATUS, GROUPS, STATUS_MAP, VERSION, js, read_text, widget  # noqa: E402

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "source"
MANIFEST = SOURCE / "wifi" / "datasets.json"
# Each template in the manifest has a technical name (we__generic_access_point for the generic template, which sorts
# first, then we_<vendor>_<words>; the rule is in _common.py), a visible name, and uuid_name: the name its UUIDs were
# derived from, which is its name up to 2.2.0, so importing over that release renames it in place.
GROUP = GROUPS["we"]
# Earlier releases exported every Wi-Fi template in this one file.
LEGACY_EXPORTS = ("wifi_explorer_snmp.yaml",)
# The switch generator's manifest; its components also supply the LLDP that per-AP templates embed.
SWITCH_MANIFEST = SOURCE / "datasets.json"
FAILED = "__NE_COLLECTION_FAILED__"
SCHEMA = "wifi-1.0"
NAMESPACE = _common.NAMESPACES["we"]
# The same storage policy as the switch templates (generate_snmp.py): snapshots, attempt receipts and collection
# statuses are stored when they change and every {$WE.HEARTBEAT}; capacity values are readings, stored every poll for
# their trends. Stored JSON carries no timestamps: the frontend takes them from Zabbix (StoredEnvelope.php).
HEARTBEAT = "{$WE.HEARTBEAT}"
THROTTLE = {"type": "DISCARD_UNCHANGED_HEARTBEAT", "parameters": [HEARTBEAT]}
HEARTBEAT_MACRO = {"macro": HEARTBEAT, "value": "2h",
                   "description": "An unchanged snapshot, attempt receipt or collection status is stored again at least "
                                  "this often; a change is stored at once. Lengthen it to write less."}
# An AP's and the controller's uptime is stored as the minute it started, so the stored JSON stays the same.
UPTIME = generate_snmp.STORAGE_ROWS["device"]
STORAGE_ROWS = {"device": UPTIME, "ap_state": UPTIME}


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


def item_uid(scope: str | None, key: str) -> str:
    """The Aruba Instant templates keep their original item UUIDs; a template added later scopes its item UUIDs by
    its uuid_scope (its name when it was added), since templates of different vendors share the canonical keys."""
    return uid("item:" + key) if scope is None else uid(scope + ":item:" + key)


def dependent(key: str, name: str, dataset: str, master: str, script: str, *, value_type: str = "TEXT",
              discard: bool = False, history: str = "7d", scope: str | None = None, throttle: bool = False,
              **extra) -> dict:
    result = {"uuid": item_uid(scope, key), "name": name, "type": "DEPENDENT", "key": key, "delay": "0",
              "history": history, "value_type": value_type}
    if value_type in ("TEXT", "CHAR"):
        result["trends"] = "0"
    result.update(extra)
    result["master_item"] = {"key": master}
    result["preprocessing"] = js(script, discard) + ([dict(THROTTLE)] if throttle else [])
    result["tags"] = tags(dataset)
    return result


def gate(dataset: str, then: str = "return value;") -> str:
    return _common.gate(SCHEMA, dataset, then)


def raw_item(entry: dict, scope: str | None) -> dict:
    return {"uuid": item_uid(scope, entry["raw_key"]), "name": f"Raw SNMP walk: {entry['dataset']}",
            "type": "SNMP_AGENT", "snmp_oid": "walk[" + ",".join(entry["walk"]) + "]", "key": entry["raw_key"],
            "delay": entry["interval_macro"], "history": "0", "value_type": "TEXT", "trends": "0",
            "description": "Input for the canonical normaliser only; not stored. A timeout or SNMP error becomes "
                           "a failed attempt instead of making the dataset silently disappear.",
            "preprocessing": [{"type": "CHECK_NOT_SUPPORTED", "parameters": ["-1"],
                               "error_handler": "CUSTOM_VALUE", "error_handler_params": FAILED}],
            "tags": tags(entry["dataset"])}


# A complete, successful attempt is stored as a receipt: its rows are already in the snapshot item, so storing
# them twice would double the dataset's history. Partial, failed and unsupported attempts are kept whole.
def receipt(dataset: str) -> str:
    return generate_snmp.receipt(dataset, STORAGE_ROWS)


def stored(dataset: str) -> str:
    """A complete observation in its stored form (no timestamps, stable rows)."""
    return gate(dataset, generate_snmp.stored(dataset, STORAGE_ROWS))


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


def capacity_items(entry: dict, scope: str | None, wanted: list[str] | None) -> list[dict]:
    """The capacity items of one dataset. `wanted` lists key prefixes for a template whose sources cannot give every
    value (the generic AP template has no utilisation or clients); None means all of them."""
    dataset = entry["dataset"]
    return [dependent(key, name, dataset, normalised_key(dataset), gate(dataset, script), value_type=value_type,
                      discard=True, history="{$WE.CAPACITY.HISTORY}", trends="{$WE.CAPACITY.TRENDS}", units=units,
                      scope=scope,
                      description="From each complete observation only, for the long-term capacity views; "
                                  "no value when the observation cannot give one.")
            for key, name, script, value_type, units in CAPACITY.get(dataset, [])
            if wanted is None or any(key == w or key.startswith(w + "[") for w in wanted)]


def history_macro(entry: dict) -> str:
    return entry["interval_macro"].replace(".INTERVAL}", ".HISTORY}")


def normalised_key(dataset: str) -> str:
    return f"we.normalised[{dataset}]"


def producer_items(entry: dict, template: str, meta: dict) -> list[dict]:
    dataset, history = entry["dataset"], history_macro(entry)
    attempt, normalised = entry["attempt_key"], normalised_key(dataset)
    scope, owner = meta.get("uuid_scope"), meta.get("uuid_name", template)
    items = [raw_item(entry, scope),
             dependent(normalised, f"Normalised envelope: {dataset}", dataset, entry["raw_key"], compose(entry),
                       history="0", scope=scope,
                       description="The canonical envelope of each attempt, passed to the items below; not stored."),
             dependent(attempt, f"Collection attempt: {dataset}", dataset, normalised, receipt(dataset),
                       history=history, scope=scope, throttle=True,
                       description="Each attempt's outcome, including partial, failed and unsupported, stored when it "
                                   "changes. A complete success is stored as a receipt without its rows, which are in "
                                   "the snapshot. Times are Zabbix's own.")]
    for key in entry["snapshot_keys"]:
        items.append(dependent(key, f"Last complete snapshot: {dataset}", dataset, normalised, stored(dataset),
                               discard=True, history=history, scope=scope, throttle=True,
                               description="Complete, successful observations only, stored when they change. Times "
                                           "are Zabbix's own: the frontend takes the observation time from the last "
                                           "complete observation item."))
    status = dependent(f"we.collection.status[{dataset}]", f"Collection status: {dataset}", dataset, normalised,
                       COLLECTION_STATUS, value_type="UNSIGNED", history="31d", trends="0", scope=scope,
                       valuemap={"name": STATUS_MAP}, throttle=True)
    # Stored at every complete observation: the staleness trigger's nodata() needs it, and its Zabbix timestamp is
    # the observation time the frontend reports.
    success = dependent(f"we.collection.success[{dataset}]", f"Last complete observation: {dataset}", dataset,
                        normalised, gate(dataset, "return Math.floor(Date.parse(e.observed_at)/1000);"),
                        value_type="UNSIGNED", discard=True, history="7d", trends="0", units="unixtime",
                        scope=scope)
    stale = stale_macro(entry)
    success["triggers"] = [{
        "uuid": uid("trigger:stale:" + owner + ":" + dataset),
        "expression": f"nodata(/{template}/we.collection.success[{dataset}],{stale})=1 and "
                      f"last(/{template}/we.collection.status[{dataset}])<>3",
        "name": f"Wi-Fi Explorer: no complete {dataset} observation for {stale}",
        "priority": "WARNING",
        "description": "Partial and failed attempts never refresh this age. An unsupported dataset (for example on "
                       "a member AP) does not alert.",
        "tags": tags(dataset)}]
    return items + [status, success] + capacity_items(entry, scope, meta.get("capacity"))


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


def cluster_dashboard(template: str, owner: str) -> dict:
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
    return {"uuid": uid("dashboard:" + owner), "name": "Wi-Fi Explorer", "auto_start": "NO",
            "pages": [{"name": "Capacity", "widgets": widgets}]}


def ap_dashboard(template: str, owner: str) -> dict:
    """The generic AP's host dashboard: its radios by band, from Zabbix's own widgets only."""
    widgets = [widget("item", f"Radios up, {band} GHz", 24 * i, 0, 24, 3,
                      [item_field("itemid.0", template, f"we.capacity.radios.up[{band}]")])
               for i, band in enumerate(BANDS)]
    widgets.append(graph("Radios up by band", template, [f"we.capacity.radios.up[{band}]" for band in BANDS], 0, 3))
    return {"uuid": uid("dashboard:" + owner), "name": "Wi-Fi Explorer", "auto_start": "NO",
            "pages": [{"name": "Radios", "widgets": widgets}]}


# Templates that carry a host dashboard: the owner of the capacity items (the generic AP itself, or the cluster's
# virtual controller).
DASHBOARDS = {"Generic AP": ap_dashboard, "Aruba Instant VC": cluster_dashboard}


def build(version: str) -> dict:
    source = manifest()
    templates = []
    for short, meta in source["templates"].items():
        name, owner = meta["template"], meta.get("uuid_name", meta["template"])
        mine = [e for e in source["datasets"] if e["template"] == short]
        template = {
            "uuid": uid("template:" + owner), "template": name, "name": meta["name"],
            "description": meta["description"] + " Generated by templates/generate_wifi.py; do not edit by hand. "
                           "It reads only the host's SNMP interface and carries no credentials.",
            "vendor": {"name": "Network Explorer", "version": VERSION},
            "groups": [{"name": GROUP}],
            "items": [i for e in mine for i in producer_items(e, name, meta)],
            "tags": [{"tag": "component", "value": "wifi-explorer"}],
            "macros": macros(mine, meta.get("macros", []) + [HEARTBEAT_MACRO]),
            "valuemaps": [{"uuid": uid(f"valuemap:{short}:status"), "name": STATUS_MAP,
                           "mappings": [{"value": str(i), "newvalue": s}
                                        for i, s in enumerate(("ok", "partial", "failed", "unsupported"))]}]}
        if meta.get("network_explorer"):
            # Network Explorer's own items (ne.* keys, as on a switch, so the frontend reads them the same way),
            # sharing this template's value map of the same name.
            parts = generate_snmp.embedded(name, owner, meta["network_explorer"])
            template["items"] += parts["items"]
            template["macros"] = sorted(template["macros"] + parts["macros"], key=lambda m: m["macro"])
            maps = {m["name"]: m for m in template["valuemaps"]}
            for m in parts["valuemaps"]:
                if m["name"] in maps:
                    assert m["mappings"] == maps[m["name"]]["mappings"], m["name"]
                else:
                    template["valuemaps"].append(m)
        if short in DASHBOARDS:
            template["dashboards"] = [DASHBOARDS[short](name, owner)]
        templates.append(template)
    return {"zabbix_export": {"version": version, "template_groups": [_common.group("we")], "templates": templates}}


def render(version: str) -> dict[str, str]:
    """One self-contained export per template, in a file named after its technical name."""
    return _common.split_exports(build(version)["zabbix_export"])


def switch_files() -> set[str]:
    return {p["template"] + ".yaml" for p in json.loads(read_text(SWITCH_MANIFEST))["templates"]}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Fail if generated files differ.")
    args = parser.parse_args()
    outputs = {ROOT / "native" / version / name: text
               for version in ("7.0", "7.2", "7.4") for name, text in render(version).items()}
    # This generator owns the we_*.yaml files that the switch generator does not write; one it no longer writes is
    # stale.
    theirs = switch_files()
    _common.write_native(outputs, args.check, lambda path: path.suffix == ".yaml" and (
        path.name.startswith("we_") and path.name not in theirs or path.name in LEGACY_EXPORTS))


if __name__ == "__main__":
    main()
