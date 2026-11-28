"""Helpers shared by the native (generate_snmp.py, generate_wifi.py) and LAB replay (generate_lab.py) template generators.

Both generators must produce preprocessing that survives a Zabbix import unchanged, so the JavaScript
gates, discard mechanics and YAML dumping live here once.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import uuid

import yaml

ROOT = Path(__file__).resolve().parent
# Native templates are named <product>_<words> in lowercase with single underscores, and their visible name is the
# product's name, " - ", then the same words in Title Case. Each product's generic template has a double underscore
# (ne__generic_switch, we__generic_access_point), which sorts it and its file first. The prefix also sets the template
# group, so a template for access points (we_) sits with Wi-Fi Explorer whichever generator builds it.
TECHNICAL_NAME = re.compile(r"(ne|we)__?[a-z0-9]+(_[a-z0-9]+)+")
PRODUCTS = {"ne": "Network Explorer", "we": "Wi-Fi Explorer"}
GROUPS = {"ne": "Templates/Network Explorer", "we": "Templates/Wi-Fi Explorer"}
# Each product's UUID namespace (generate_snmp.py and generate_wifi.py); never change one, or every UUID moves.
NAMESPACES = {"ne": uuid.UUID("5b0f8e0a-6f0e-4a55-9d0c-2a7f3c1e9b44"), "we": uuid.UUID("0f6c55d2-3b4e-4f51-a0de-6f2b0f1c7e3a")}
# The release version shipped in template vendor metadata (and asserted against NE.VERSION in lib.js).
VERSION = (ROOT.parent / "VERSION").read_text(encoding="utf-8").strip()
DISCARD = "__NE_DISCARD__"
STATUS_MAP = "Network Explorer collection status"
IF_STATUS_MAP = "Network Explorer interface status"
IF_STATUS = {"up": 1, "down": 2, "testing": 3, "unknown": 4, "dormant": 5, "not_present": 6, "lower_layer_down": 7}
IF_STATUS_UNKNOWN = IF_STATUS["unknown"]
# Unrecognised status strings map to "unknown" so the item stays supported, as for a null status.
IF_STATUS_CONVERT = "var m=" + json.dumps(IF_STATUS) + "; v=m[v]===undefined?" + str(IF_STATUS_UNKNOWN) + ":m[v];"
COLLECTION_STATUS = ("var s=JSON.parse(value).status; var m={ok:0,partial:1,failed:2,unsupported:3}; "
                     "if(m[s]===undefined) throw 'Unknown status'; return m[s];")
FAILED = "__NE_COLLECTION_FAILED__"
# Zabbix's own error texts for a failed walk[] (src/libs/zbxpoller/checks_snmp.c), each matched to a fixed failure
# class that NE.run in lib.js turns into an error code. When a request still times out after its retries once the walk
# has data (every walk starts with sysUpTime), the item is not supported with "only partial data received, cannot
# retrieve OID: '<oid>' from [[<address>]:<port>]: timed out", and Zabbix discards the whole walk (ZBX-27224).
# A timeout before any data is a network error instead: the interface goes unreachable and no value is processed.
WALK_FAILURES = (("Timeout while retrieving data|partial data received", "walk_partial"),
                 ("OID not changing|OID loop detected", "walk_oid_loop"),
                 ("^SNMP error", "snmp_error"))
PARTIAL_AT_OID = "partial data received.*OID[^0-9]*{oid}([^0-9]|$)"


def collection_failure(walk: list[str]) -> list[dict]:
    """The raw walk item's "Check for not supported value" steps, first match wins. Each turns Zabbix's error into a
    fixed value: the failure marker, a class and, for a walk that stopped part-way, which of the walk's own OIDs it
    stopped in. No capture group copies Zabbix's text, which names the device's address, so nothing the device or
    Zabbix wrote reaches the receipt. Any other error leaves the bare marker (collection_failed)."""
    def step(pattern: str | None, value: str) -> dict:
        return {"type": "CHECK_NOT_SUPPORTED", "parameters": ["-1"] if pattern is None else ["0", pattern],
                "error_handler": "CUSTOM_VALUE", "error_handler_params": value}
    # Longest first, so an OID inside another of the walk's subtrees is named rather than its parent.
    oids = sorted(dict.fromkeys(walk), key=lambda oid: (-len(oid.split(".")), oid))
    return ([step(PARTIAL_AT_OID.format(oid=re.escape(oid)), f"{FAILED} walk_partial {oid}") for oid in oids]
            + [step(pattern, f"{FAILED} {failure}") for pattern, failure in WALK_FAILURES]
            + [step(None, FAILED)])


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def uid(namespace: uuid.UUID, name: str) -> str:
    # Zabbix imports require v4-shaped UUIDs. Hashing keeps ownership reproducible.
    digest = hashlib.sha256(namespace.bytes + name.encode("utf-8")).digest()[:16]
    return uuid.UUID(bytes=digest, version=4).hex


def product(technical: str) -> str:
    """The product prefix of a native template's technical name, after checking the name and its visible name."""
    assert TECHNICAL_NAME.fullmatch(technical), technical
    return technical.split("_", 1)[0]


def group(prefix: str) -> dict:
    return {"uuid": uid(NAMESPACES[prefix], "group:" + GROUPS[prefix]), "name": GROUPS[prefix]}


def split_exports(export: dict) -> dict[str, str]:
    """One self-contained export per template, in a file named after its technical name, carrying only its own
    template group. Nothing in an export refers to another template, so each file imports on its own."""
    assert set(export) == {"version", "template_groups", "templates"}, sorted(export)
    files = {}
    for template in export["templates"]:
        prefix = product(template["template"])
        assert template["name"].startswith(PRODUCTS[prefix] + " - "), template["name"]
        assert template["groups"] == [{"name": GROUPS[prefix]}], template["groups"]
        files[template["template"] + ".yaml"] = dump({"zabbix_export": {
            "version": export["version"], "template_groups": [group(prefix)], "templates": [template]}})
    return files


def write_native(outputs: dict[Path, str], check: bool, owns) -> None:
    """Writes (or with check, compares) a generator's native exports, then deals with the files it owns, by
    owns(path), but no longer writes: --check fails on them, a normal run removes them."""
    write_outputs(outputs, check)
    stale = sorted(path for folder in sorted({p.parent for p in outputs}) for path in folder.iterdir()
                   if path not in outputs and owns(path))
    if stale and check:
        raise SystemExit("Stale generated files: " + ", ".join(str(p) for p in stale))
    for path in stale:
        path.unlink()
        print(f"Removed stale {path}")


def tags(dataset: str, data_source: str) -> list[dict]:
    return [{"tag": "component", "value": "network-explorer"}, {"tag": "dataset", "value": dataset},
            {"tag": "data_source", "value": data_source}]


def widget(kind: str, name: str, x: int, y: int, width: int, height: int, fields: list[dict] | None = None) -> dict:
    result = {"type": kind, "name": name, "x": str(x), "y": str(y), "width": str(width), "height": str(height)}
    if fields:
        result["fields"] = fields
    return result


def js(script: str, discard: bool = False) -> list[dict]:
    """A JavaScript step. Zabbix offers no custom on-fail for JavaScript (an import silently drops it), so a
    discarding gate returns a sentinel that the following regular-expression step discards."""
    if not discard:
        return [{"type": "JAVASCRIPT", "parameters": [script]}]
    wrapped = ("try { return (function (value) {\n" + script + "\n})(value); } catch (error) { return '" + DISCARD + "'; }")
    return [{"type": "JAVASCRIPT", "parameters": [wrapped]},
            {"type": "NOT_MATCHES_REGEX", "parameters": ["^" + DISCARD + "$"], "error_handler": "DISCARD_VALUE"}]


# Every interface row must carry a safe, unique uid (it is substituted into scalar scripts as {#IFUID})
# and a positive integer ifIndex before the snapshot may reach discovery or scalars.
INTERFACE_IDENTITY = ("var seen={}; for(var i=0;i<e.data.length;i++){var r=e.data[i];"
                      "if(!r||typeof r.uid!=='string'||!/^[a-z0-9][a-z0-9_-]{0,79}$/.test(r.uid)||"
                      "Object.prototype.hasOwnProperty.call(seen,r.uid)||typeof r.if_index!=='number'||"
                      "r.if_index<1||Math.floor(r.if_index)!==r.if_index) throw 'Unsafe or ambiguous interface identity';"
                      "seen[r.uid]=true;} ")


# Hardware rows reach discovery as {#HWUID}, so the same rule applies to their uids.
HARDWARE_IDENTITY = ("var seen={}; for(var i=0;i<e.data.length;i++){var r=e.data[i];"
                     "if(!r||typeof r.uid!=='string'||!/^[a-z0-9][a-z0-9_-]{0,79}$/.test(r.uid)||"
                     "Object.prototype.hasOwnProperty.call(seen,r.uid)) throw 'Unsafe or ambiguous hardware identity';"
                     "seen[r.uid]=true;} ")


def gate(schema: str, dataset: str, then: str = "return value;") -> str:
    """Throws (and the item discards the value) unless the envelope is a complete observation."""
    identity = {"interfaces": INTERFACE_IDENTITY, "hardware": HARDWARE_IDENTITY}.get(dataset, "")
    return (f"var e=JSON.parse(value); if(e.schema_version!=='{schema}'||e.dataset!=='{dataset}'||e.status!=='ok'||"
            "e.complete!==true||!Array.isArray(e.data)) throw 'Incomplete or invalid snapshot; retain last success'; "
            "if(typeof e.observed_at!=='string'||!/^\\d{4}-\\d{2}-\\d{2}T\\d{2}:\\d{2}:\\d{2}(?:\\.\\d+)?Z$/.test(e.observed_at)||"
            "!isFinite(Date.parse(e.observed_at))) throw 'Invalid observation timestamp'; " + identity + then)


def interface_scalar(field: str, unknown: str | None, convert: str = "") -> str:
    """One interface's field from the complete state snapshot. A null fact returns `unknown` (so the item stays
    supported) or throws when `unknown` is None; an absent interface always throws so its last value is kept."""
    missing = "return " + unknown + ";" if unknown is not None else "throw 'Unknown scalar';"
    return ("var a=JSON.parse(value).data; for(var i=0;i<a.length;i++){if(a[i].uid==='{#IFUID}'){var v=a[i]['"
            + field + "']; if(v===null||v===undefined){" + missing + "}" + convert
            + " return v;}} throw 'Interface absent; retain last observed value';")


class _Dumper(yaml.SafeDumper):
    """Never folds a scalar. Zabbix's YAML import adds a space at every escaped line fold, which corrupted any script
    line folded inside a string or regex literal. Multi-line text (scripts) is written as literal blocks instead."""


def _represent_str(dumper: yaml.SafeDumper, data: str) -> yaml.ScalarNode:
    return dumper.represent_scalar("tag:yaml.org,2002:str", data, style="|" if "\n" in data else None)


_Dumper.add_representer(str, _represent_str)


def dump(document: dict) -> str:
    return yaml.dump(document, Dumper=_Dumper, sort_keys=False, allow_unicode=True, width=1_000_000)


def write_outputs(outputs: dict[Path, str], check: bool) -> None:
    for target, output in outputs.items():
        if check:
            if not target.exists() or read_text(target) != output:
                raise SystemExit(f"Generated file differs: {target}")
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(output, encoding="utf-8")
