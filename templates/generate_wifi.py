#!/usr/bin/env python3
"""Build the deterministic Wi-Fi Explorer native SNMP templates for Zabbix 7.0, 7.2 and 7.4.

Each producer in templates/source/wifi/datasets.json becomes one walk[] master item, a JavaScript normaliser that
emits the canonical Wi-Fi envelope, and gated dependents that only accept complete observations: the same item
pattern as the Network Explorer templates (templates/generate_snmp.py). The JavaScript is composed exactly as
tests/js/run_normaliser.cjs composes it, so the code tested in Node is the code Zabbix runs.

The templates carry no credentials, no API token and no per-AP or per-client items: Wi-Fi Explorer reads the
owner's snapshots in the frontend, under the viewing user's permissions.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _common  # noqa: E402
from _common import COLLECTION_STATUS, STATUS_MAP, VERSION, dump, js, read_text, write_outputs  # noqa: E402

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


def producer_items(entry: dict, template: str) -> list[dict]:
    dataset, history = entry["dataset"], entry["history"]
    attempt = entry["attempt_key"]
    items = [raw_item(entry),
             dependent(attempt, f"Collection attempt: {dataset}", dataset, entry["raw_key"], compose(entry),
                       history=history,
                       description="Canonical envelope for every attempt, including partial, failed and unsupported.")]
    for key in entry["snapshot_keys"]:
        items.append(dependent(key, f"Last complete snapshot: {dataset}", dataset, attempt, gate(dataset),
                               discard=True, history=history,
                               description="Updated only by complete, successful observations."))
    status = dependent(f"we.collection.status[{dataset}]", f"Collection status: {dataset}", dataset, attempt,
                       COLLECTION_STATUS, value_type="UNSIGNED", history="31d", trends="0",
                       valuemap={"name": STATUS_MAP})
    success = dependent(f"we.collection.success[{dataset}]", f"Last complete observation: {dataset}", dataset,
                        attempt, gate(dataset, "return Math.floor(Date.parse(e.observed_at)/1000);"),
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
    return items + [status, success]


def macros(entries: list[dict]) -> list[dict]:
    result = []
    for entry in entries:
        result.append({"macro": entry["interval_macro"], "value": entry["interval"],
                       "description": f"Polling interval for {entry['dataset']}."})
        result.append({"macro": stale_macro(entry), "value": entry["stale"],
                       "description": f"Maximum age of a complete {entry['dataset']} observation."})
    return sorted(result, key=lambda m: m["macro"])


def build(version: str) -> dict:
    source = manifest()
    templates = []
    for short, meta in source["templates"].items():
        name = PREFIX + short + SUFFIX
        mine = [e for e in source["datasets"] if e["template"] == short]
        templates.append({
            "uuid": uid("template:" + name), "template": name, "name": name,
            "description": meta["description"] + " Generated by templates/generate_wifi.py; do not edit by hand. "
                           "It reads only the host's SNMP interface and carries no credentials.",
            "vendor": {"name": "Network Explorer", "version": VERSION},
            "groups": [{"name": GROUP}],
            "items": [i for e in mine for i in producer_items(e, name)],
            "tags": [{"tag": "component", "value": "wifi-explorer"}],
            "macros": macros(mine),
            "valuemaps": [{"uuid": uid(f"valuemap:{short}:status"), "name": STATUS_MAP,
                           "mappings": [{"value": str(i), "newvalue": s}
                                        for i, s in enumerate(("ok", "partial", "failed", "unsupported"))]}]})
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
