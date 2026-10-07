"""Helpers shared by the native (generate_snmp.py) and LAB replay (generate_lab.py) template generators.

Both generators must produce preprocessing that survives a Zabbix import unchanged, so the JavaScript
gates, discard mechanics and YAML dumping live here once.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import uuid

import yaml

ROOT = Path(__file__).resolve().parent
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


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def uid(namespace: uuid.UUID, name: str) -> str:
    # Zabbix imports require v4-shaped UUIDs. Hashing keeps ownership reproducible.
    digest = hashlib.sha256(namespace.bytes + name.encode("utf-8")).digest()[:16]
    return uuid.UUID(bytes=digest, version=4).hex


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


def gate(schema: str, dataset: str, then: str = "return value;") -> str:
    """Throws (and the item discards the value) unless the envelope is a complete observation."""
    identity = INTERFACE_IDENTITY if dataset == "interfaces" else ""
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
