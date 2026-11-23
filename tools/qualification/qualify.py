#!/usr/bin/env python3
"""Hardware qualification: classify walks, check evidence, and keep the qualification matrix honest.

Stdlib only (Python 3.10+); ``classify`` also needs Node.js, because it replays a walk through the same native
template normalisers Zabbix runs (``tests/js/run_normaliser.cjs``). Nothing here talks to a device or to Zabbix.

  qualify.py [--product P] classify [--template T] <file.snmprec>
                                                        per-dataset outcome of the native normalisers, as JSON;
                                                        T is the switch template whose producers are replayed
  qualify.py [--product P] check-evidence <evidence-dir> sanitisation and completeness of one evidence directory
  qualify.py [--product P] matrix [--check | --write]    validate the product's matrix.json against its evidence
                                                        and render (or check) its Markdown matrix

The product is ``network`` (Network Explorer switches, the default) or ``wifi`` (Wi-Fi Explorer sources). Each has
its own datasets, capabilities, matrix and evidence root; the states, evidence kinds and sanitisation rules are shared.

Exit codes: 0 ok, 1 a check failed, 2 usage error.
"""

from __future__ import annotations

import argparse
import ipaddress
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RUNNER = ROOT / "tests/js/run_normaliser.cjs"
MATRIX_JSON = ROOT / "docs/qualification/matrix.json"
MATRIX_MD = ROOT / "docs/qualification/MATRIX.md"
EVIDENCE_ROOT = ROOT / "tests/fixtures/qualification"

# A classification replays the producers of one switch template (templates/source/datasets.json), the generic one
# unless the evidence names another, so a vendor template's own producers (hardware, PoE) are judged on its walks.
SWITCH_MANIFEST = ROOT / "templates/source/datasets.json"
DEFAULT_TEMPLATE = "ne__generic_switch"
# Each producer's name in a classification (the dataset, or dataset_variant where a dataset has two producers).
PRODUCER_NAMES = {"interfaces": "interfaces_state", "interfaces.inventory": "interfaces_inventory"}
CAPABILITIES = ("interfaces", "entity", "mau", "lldp", "vlan", "stp", "lag", "hardware", "poe")
CAPABILITY_LABELS = {"interfaces": "Interfaces", "entity": "ENTITY", "mau": "MAU", "lldp": "LLDP",
                     "vlan": "VLAN", "stp": "STP", "lag": "LAG", "hardware": "Hardware", "poe": "PoE"}
SYSTEM_UPTIME = "1.3.6.1.2.1.1.3"

# Wi-Fi Explorer: the Aruba Instant producers (templates/source/wifi/datasets.json) and what each capability means.
WIFI_RAW_KEYS = {
    "device": "we.raw.aruba.system",
    "ap_inventory": "we.raw.aruba.ap.inventory",
    "ap_state": "we.raw.aruba.ap.state",
    "radio_inventory": "we.raw.aruba.radio.inventory",
    "radio_state": "we.raw.aruba.radio.state",
}
WIFI_CAPABILITIES = ("controller", "ap_inventory", "ap_state", "radio_inventory", "radio_state")
WIFI_CAPABILITY_LABELS = {"controller": "Controller", "ap_inventory": "AP inventory", "ap_state": "AP state",
                          "radio_inventory": "Radio inventory", "radio_state": "Radio state"}

# Qualification states, weakest first. Each names the evidence it needs (see docs/qualification/README.md).
STATES = ("Unqualified", "Lab simulated", "Captured-walk tested", "Partially qualified", "Real-device qualified",
          "Unsupported")
EVIDENCE_KINDS = ("synthetic", "captured", "field")

SYS_DESCR = "1.3.6.1.2.1.1.1.0"
SYS_OBJECT_ID = "1.3.6.1.2.1.1.2.0"
SYS_CONTACT = "1.3.6.1.2.1.1.4.0"
SYS_NAME = "1.3.6.1.2.1.1.5.0"
SYS_LOCATION = "1.3.6.1.2.1.1.6.0"
LLDP_LOC_SYS_NAME = "1.0.8802.1.1.2.1.3.3.0"
LLDP_REM_SYS_NAME = "1.0.8802.1.1.2.1.4.1.1.9"
ENT_SERIAL = "1.3.6.1.2.1.47.1.1.1.1.11"
IF_ALIAS = "1.3.6.1.2.1.31.1.1.1.18"
# LLDP management-address tables: (entry OID, index parts before the address subtype).
LLDP_MAN_ADDR_ENTRIES = (("1.0.8802.1.1.2.1.3.8.1", 0), ("1.0.8802.1.1.2.1.4.2.1", 3),
                         ("1.0.8802.1.1.2.1.1.7.1", 0))   # loc, rem and lldpConfigManAddrTable
ARUBA_AI = "1.3.6.1.4.1.14823.2.3.3.1"
AI_AP_NAME = ARUBA_AI + ".2.1.1.2"
AI_AP_SERIAL = ARUBA_AI + ".2.1.1.4"
DOCUMENTATION_NETS = tuple(ipaddress.IPv4Network(n) for n in ("192.0.2.0/24", "198.51.100.0/24", "203.0.113.0/24"))
MANIFEST_KEYS = {"format", "device_label", "captured_at", "snmp_version", "snmp_security_level", "walk_options",
                 "sanitised", "sanitisation_limits", "snmprec_file", "record_count", "subtrees", "anonymised"}
IPV4_TEXT = re.compile(r"(?<![\d.])(\d{1,3}(?:\.\d{1,3}){3})(?![\d.])")
PRIVATE_NETS = tuple(ipaddress.IPv4Network(n) for n in
                     ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "100.64.0.0/10", "169.254.0.0/16"))

# --- what public evidence may hold (docs/qualification/README.md); tools/qualification/anonymise.py enforces it ---
PUBLISHED_UPTIME = 60_480_000   # sysUpTime of anonymised evidence: 7 days in TimeTicks; no TimeTicks value is larger
LLDP_LOC_CHASSIS_SUBTYPE = "1.0.8802.1.1.2.1.3.1.0"
LLDP_LOC_CHASSIS_ID = "1.0.8802.1.1.2.1.3.2.0"
LLDP_LOC_PORT_SUBTYPE = "1.0.8802.1.1.2.1.3.7.1.2."
LLDP_LOC_PORT_ID = "1.0.8802.1.1.2.1.3.7.1.3."
LLDP_LOC_PORT_DESC = "1.0.8802.1.1.2.1.3.7.1.4."
LLDP_REM_CHASSIS_SUBTYPE = "1.0.8802.1.1.2.1.4.1.1.4."
LLDP_REM_CHASSIS_ID = "1.0.8802.1.1.2.1.4.1.1.5."
LLDP_REM_PORT_SUBTYPE = "1.0.8802.1.1.2.1.4.1.1.6."
LLDP_REM_PORT_ID = "1.0.8802.1.1.2.1.4.1.1.7."
LLDP_REM_PORT_DESC = "1.0.8802.1.1.2.1.4.1.1.8."
LLDP_REM_SYS_DESC = "1.0.8802.1.1.2.1.4.1.1.10."
# LLDP-EXT-MED-MIB sits under lldpExtensions.4795; Cisco SB and RADLAN firmware publishes it under lldpExtensions.1.
_LLDP_MED = ("1.0.8802.1.1.2.1.5.4795.1", "1.0.8802.1.1.2.1.5.1.1")
# Columns whose MIB defines a revision string: a dotted quad there is a version number, not an address.
VERSION_COLUMNS = tuple(f"{column}." for column in (
    "1.3.6.1.2.1.47.1.1.1.1.8", "1.3.6.1.2.1.47.1.1.1.1.9", "1.3.6.1.2.1.47.1.1.1.1.10",      # entPhysical*Rev
    *(f"{arc}.2.{c}" for arc in _LLDP_MED for c in (2, 3, 4)),                                 # lldpXMedLoc*Rev
    *(f"{arc}.3.3.1.{c}" for arc in _LLDP_MED for c in (1, 2, 3)),                             # lldpXMedRem*Rev
    *(f"{base}.53.14.1.{c}" for base in ("1.3.6.1.4.1.9.6.1.101", "1.3.6.1.4.1.89")
      for c in (2, 3, 4, 17, 18)),                                    # rlPhdUnitGenParam Software/Firmware/Hardware/Cpld/Mcu
    *(f"{base}.53.4.1.5" for base in ("1.3.6.1.4.1.9.6.1.101", "1.3.6.1.4.1.89")),  # rlPhdStackSofrwareVer
    "1.3.6.1.4.1.674.10895.3000.1.2.100.4", "1.3.6.1.4.1.674.10895.3000.1.2.100.5",  # Dell productIdentification Version, BuildNumber
))
SERIAL_COLUMNS = (   # serial numbers, asset tags and service tags (a value equal to the model name is allowed)
    *(f"1.3.6.1.4.1.9.6.1.101.53.14.1.{c}." for c in (5, 6, 7)), *(f"1.3.6.1.4.1.89.53.14.1.{c}." for c in (5, 6, 7)),
    *(f"1.3.6.1.4.1.674.10895.3000.1.2.100.8.1.{c}." for c in (2, 3, 4)),
    *(f"{arc}.2.{c}.0" for arc in _LLDP_MED for c in (5, 8)), *(f"{arc}.3.3.1.{c}." for arc in _LLDP_MED for c in (4, 7)),
)
MODEL_COLUMNS = ("1.3.6.1.2.1.47.1.1.1.1.13.", "1.3.6.1.4.1.9.6.1.101.53.14.1.11.", "1.3.6.1.4.1.89.53.14.1.11.",
                 *(f"{arc}.2.7.0" for arc in _LLDP_MED))   # Cisco SB fills its service-tag column with the model name
HOSTNAME_COLUMNS = ("1.3.6.1.4.1.9.6.1.101.1.19.1.3.", "1.3.6.1.4.1.674.10895.3000.1.2.100.7.0")
VLAN_NAME_COLUMNS = ("1.3.6.1.2.1.17.7.1.4.3.1.1.", "1.0.8802.1.1.2.1.5.32962.1.2.3.1.2.",
                     "1.0.8802.1.1.2.1.5.32962.1.3.3.1.2.")
POE_LABEL = "1.3.6.1.2.1.105.1.1.1.9."   # pethPsePortType: a free-text port label
NEIGHBOUR_TEXT_COLUMNS = (LLDP_REM_SYS_DESC, LLDP_REM_PORT_DESC,
                          *(f"{arc}.3.3.1.{c}." for arc in _LLDP_MED for c in (1, 2, 3, 5, 6)))
TLV_COLUMNS = ("1.0.8802.1.1.2.1.4.4.1.4.", "1.0.8802.1.1.2.1.4.3.1.2.")   # lldpRemOrgDefInfo, lldpRemUnknownTLVInfo
MAC_COLUMNS = (   # always a MAC address
    "1.3.6.1.2.1.2.2.1.6.", "1.3.6.1.2.1.17.1.1.0",                                   # ifPhysAddress, dot1dBaseBridgeAddress
    *(f"1.2.840.10006.300.43.1.1.1.1.{c}." for c in (2, 4, 8)),                       # dot3adAgg MAC, actor and partner system
    *(f"1.2.840.10006.300.43.1.2.1.1.{c}." for c in (3, 8, 9)),                       # dot3adAggPort actor and partner system
    "1.3.6.1.4.1.9.6.1.101.53.4.1.7.", "1.3.6.1.4.1.89.53.4.1.7.",                    # rlPhdStackMacAddr
)
MAC_SUBTYPED = (   # (value column, subtype column, the subtype that means "MAC address")
    (LLDP_LOC_CHASSIS_ID, LLDP_LOC_CHASSIS_SUBTYPE, "4"), (LLDP_REM_CHASSIS_ID, LLDP_REM_CHASSIS_SUBTYPE, "4"),
    (LLDP_LOC_PORT_ID, LLDP_LOC_PORT_SUBTYPE, "3"), (LLDP_REM_PORT_ID, LLDP_REM_PORT_SUBTYPE, "3"),
)
BRIDGE_ID_COLUMNS = ("1.3.6.1.2.1.17.2.5.0", "1.3.6.1.2.1.17.2.15.1.6.", "1.3.6.1.2.1.17.2.15.1.8.")  # priority + MAC
END_DEVICE_TABLES = ("1.3.6.1.2.1.17.7.1.2.2.", "1.3.6.1.2.1.17.4.3.")   # dot1qTpFdbTable, dot1dTpFdbTable
INTERFACE_NAME = re.compile(
    r"(?i)^(?:(?:gi|te|fo|tw|hu|xg|fa|po|ch|ag|ge|xe|et|vl|lo|em|en|eth|ethernet|gigabitethernet|tengigabitethernet|"
    r"fortygigabitethernet|twentyfivegige|hundredgige|port-channel|lag|bond|eno|ens|enp|vmnic|mgmt|oob|vlan|loopback|"
    r"port|unit)\s*\d[\d/.:-]*|\d+(?:[/.]\d+)*)$")
TEXT_MAC = re.compile(r"(?i)\b[0-9a-f]{2}([:-])(?:[0-9a-f]{2}\1){4}[0-9a-f]{2}\b")
PLACEHOLDER_MAC = "0200"
NOT_SERIAL = re.compile(r"(?i)^(?:|none|not available|n/?a|unknown)$")


def is_mac_column(oid: str, records: dict) -> bool:
    if oid.startswith(MAC_COLUMNS) or oid in MAC_COLUMNS:
        return True
    for column, subtype_column, mac_subtype in MAC_SUBTYPED:
        if oid == column or (column.endswith(".") and oid.startswith(column)):
            index = "" if oid == column else oid[len(column):]
            return records.get(subtype_column + index, ("", ""))[1] == mac_subtype
    return False


def time_mark_position(arcs: list[str]) -> int | None:
    """Where a TimeFilter time mark sits in the index of an LLDP remote or Q-BRIDGE current-VLAN row, if any."""
    if arcs[:8] == ["1", "0", "8802", "1", "1", "2", "1", "4"] and len(arcs) > 11 and arcs[9] == "1":
        return 11                                     # lldpRem*Table: column . timeMark . port . index ...
    if (arcs[:8] == ["1", "0", "8802", "1", "1", "2", "1", "5"] and len(arcs) > 14
            and arcs[9] == "1" and arcs[10] == "3" and arcs[12] == "1"):
        return 14                                     # lldpX*Rem*Table of every extension
    if arcs[:12] == ["1", "3", "6", "1", "2", "1", "17", "7", "1", "4", "2", "1"] and len(arcs) > 13:
        return 13                                     # dot1qVlanCurrentTable
    return None


class UsageError(Exception):
    pass


# --- walks -------------------------------------------------------------------------------------------------------

def read_snmprec(path: Path) -> list[tuple[str, str, str]]:
    records = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        parts = line.split("|", 2)
        if len(parts) != 3:
            raise UsageError(f"{path.name}:{number}: not an OID|TAG|VALUE record")
        records.append((parts[0].lstrip("."), parts[1], parts[2]))
    return records


def octets(tag: str, value: str) -> str:
    """The text of an octet-string record (hex records decoded as Latin-1)."""
    if tag == "4x":
        try:
            return bytes.fromhex(value).decode("latin-1")
        except ValueError:
            return ""
    return value


def run_normaliser(raw_key: str, walk: Path) -> dict:
    if shutil.which("node") is None:
        raise UsageError("Node.js is required to replay a walk through the native normalisers.")
    out = subprocess.run(["node", str(RUNNER), raw_key, str(walk)], check=True, capture_output=True, text=True)
    return json.loads(out.stdout)


def dataset_outcome(envelope: dict) -> dict:
    """Only stable facts: status, row count and error/warning codes (never timestamps or row data)."""
    return {"status": envelope.get("status"), "rows": len(envelope.get("data") or []),
            "errors": sorted({e.get("code") for e in envelope.get("errors") or [] if isinstance(e, dict)}),
            "warnings": sorted({w.get("code") for w in envelope.get("warnings") or [] if isinstance(w, dict)})}


def capability_from(outcome: dict, need_rows: bool = True) -> str:
    """ok (rows present), empty (collected, nothing observed), partial, unsupported, failed, or not_walked (the
    capture never walked what the producer reads, so it shows nothing either way)."""
    status = outcome["status"]
    if status == "ok":
        return "ok" if outcome["rows"] or not need_rows else "empty"
    return status if status in ("partial", "unsupported", "failed", "not_walked") else "failed"


def switch_templates() -> dict[str, dict]:
    manifest = json.loads(SWITCH_MANIFEST.read_text(encoding="utf-8"))
    return {p["template"]: p for p in manifest["templates"] if p["template"].startswith("ne_")}


def template_producers(template: str) -> dict[str, dict]:
    """The producers a switch template holds, by classification name (the generator's rule: a producer with a
    templates list belongs to those templates only)."""
    profile = switch_templates().get(template)
    if profile is None:
        raise UsageError(f"{template} is not a switch template in {SWITCH_MANIFEST.relative_to(ROOT).as_posix()}")
    producers = {}
    for entry in json.loads(SWITCH_MANIFEST.read_text(encoding="utf-8"))["datasets"]:
        if entry["template"] in profile["components"] and template in entry.get("templates", [template]):
            producer = entry["dataset"] + ("." + entry["variant"] if entry.get("variant") else "")
            producers[PRODUCER_NAMES.get(producer, entry["dataset"])] = entry
    return producers


def capture_manifest(walk: Path) -> dict | None:
    """The capture_walk.py manifest beside a captured walk; synthetic walks have none."""
    path = walk.parent / "manifest.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None


def walked(entry: dict, manifest: dict | None) -> bool:
    """Whether the capture walked anything the producer reads besides sysUpTime: a capture lists the subtrees it
    walked, and a subtree the agent did not implement is still walked (its outcome is no-such-object)."""
    if manifest is None:
        return True
    roots = [s["oid"] for s in manifest.get("subtrees", []) if s.get("outcome") in ("ok", "no-such-object")]
    return any(oid == root or oid.startswith(root + ".") for oid in entry["walk"] if oid != SYSTEM_UPTIME
               for root in roots)


def classify_wifi(walk: Path) -> dict:
    """Wi-Fi capabilities: controller says whether the walk is from a virtual controller (the only Aruba Instant
    source that lists the cluster); every other capability is its dataset's outcome."""
    envelopes = {name: run_normaliser(key, walk) for name, key in WIFI_RAW_KEYS.items()}
    datasets = {name: dataset_outcome(envelope) for name, envelope in envelopes.items()}
    device = capability_from(datasets["device"])
    role = ((envelopes["device"].get("data") or [{}])[0] or {}).get("role")
    caps = {"controller": ("ok" if role == "virtual_controller" else "absent") if device == "ok" else device}
    for name in WIFI_CAPABILITIES[1:]:
        caps[name] = capability_from(datasets[name])
    records = {oid: (tag, value) for oid, tag, value in read_snmprec(walk)}
    system = {"sys_object_id": records.get(SYS_OBJECT_ID, ("", ""))[1],
              "sys_descr": octets(*records.get(SYS_DESCR, ("4", "")))}
    return {"format": "wifi-explorer-classification-1", "system": system, "datasets": datasets, "capabilities": caps}


def classify(walk: Path, template: str = DEFAULT_TEMPLATE) -> dict:
    """Replays a walk through every producer of a switch template and states, per matrix capability, what it shows.
    A capability the template does not collect is not_collected."""
    manifest = capture_manifest(walk)
    envelopes, datasets = {}, {}
    for name, entry in template_producers(template).items():
        if walked(entry, manifest):
            envelopes[name] = run_normaliser(entry["raw_key"], walk)
            datasets[name] = dataset_outcome(envelopes[name])
        else:
            datasets[name] = {"status": "not_walked", "rows": 0, "errors": [], "warnings": []}
    caps = {}
    state, inventory = datasets["interfaces_state"], datasets["interfaces_inventory"]
    worst = [capability_from(state), capability_from(inventory)]
    caps["interfaces"] = next((s for s in ("failed", "unsupported", "partial", "empty") if s in worst), "ok")
    placed = [row for row in (envelopes.get("interfaces_inventory") or {}).get("data") or []
              if row.get("member") is not None or row.get("slot") is not None]
    # ENTITY-MIB placement is only visible through the inventory rows it places.
    caps["entity"] = ("ok" if placed else "absent") if caps["interfaces"] in ("ok", "partial") else caps["interfaces"]
    caps["mau"] = capability_from(datasets["port_capability"])
    for name in ("lldp", "vlan", "stp", "lag", "hardware", "poe"):
        caps[name] = capability_from(datasets[name]) if name in datasets else "not_collected"
    records = {oid: (tag, value) for oid, tag, value in read_snmprec(walk)}
    system = {"sys_object_id": records.get(SYS_OBJECT_ID, ("", ""))[1],
              "sys_descr": octets(*records.get(SYS_DESCR, ("4", "")))}
    return {"format": "network-explorer-classification-2", "template": template, "system": system,
            "datasets": datasets, "capabilities": caps}


def classify_evidence(evidence: dict, product: str = "network") -> dict:
    """The classification an evidence directory should hold: its walk replayed through its template's producers."""
    if product == "network":
        return classify(walk_path(evidence), evidence.get("template", DEFAULT_TEMPLATE))
    return PRODUCTS[product]["classify"](walk_path(evidence))


# --- products ----------------------------------------------------------------------------------------------------

PRODUCTS = {
    "network": {"title": "Hardware qualification matrix", "capabilities": CAPABILITIES, "labels": CAPABILITY_LABELS,
                "classify": classify, "matrix_json": MATRIX_JSON, "matrix_md": MATRIX_MD,
                "evidence_root": EVIDENCE_ROOT},
    "wifi": {"title": "Wi-Fi qualification matrix", "capabilities": WIFI_CAPABILITIES, "labels": WIFI_CAPABILITY_LABELS,
             "classify": classify_wifi, "matrix_json": ROOT / "docs/qualification/wifi-matrix.json",
             "matrix_md": ROOT / "docs/qualification/WIFI_MATRIX.md",
             "evidence_root": ROOT / "tests/fixtures/wifi/qualification"},
}


# --- evidence ----------------------------------------------------------------------------------------------------

def load_evidence(directory: Path) -> dict:
    path = directory / "evidence.json"
    if not path.is_file():
        raise UsageError(f"{directory}: no evidence.json")
    evidence = json.loads(path.read_text(encoding="utf-8"))
    evidence["_dir"] = directory
    return evidence


def walk_path(evidence: dict) -> Path:
    walk = evidence.get("walk", "")
    # Synthetic evidence may cite a repository fixture; captured evidence carries its own walk.
    base = (ROOT if evidence.get("kind") == "synthetic" else Path(evidence["_dir"])).resolve()
    path = (base / walk).resolve()
    if base not in path.parents:
        raise UsageError(f"{evidence.get('id')}: walk path leaves {'the repository' if base == ROOT.resolve() else 'its evidence directory'}")
    return path


def _ipv4_ok(text: str) -> bool:
    """A documentation address, or one that identifies nothing (mask, loopback, multicast, 0.0.0.0)."""
    try:
        address = ipaddress.IPv4Address(text)
    except ValueError:
        return True
    value = int(address)
    inverted = ~value & 0xFFFFFFFF
    mask = value >> 24 == 0xFF and inverted & (inverted + 1) == 0
    return (address.is_unspecified or address.is_loopback or address.is_multicast or mask
            or any(address in net for net in DOCUMENTATION_NETS))


def _man_addr_index(oid: str) -> str | None:
    """The IPv4 address inside an LLDP management-address row index, if the row has one."""
    for entry, before in LLDP_MAN_ADDR_ENTRIES:
        if oid.startswith(entry + "."):
            arcs = oid[len(entry) + 1:].split(".")
            at = 1 + before   # skip the column and the index parts before the subtype
            if len(arcs) == at + 6 and arcs[at] == "1" and arcs[at + 1] == "4":
                return ".".join(arcs[at + 2:])
    return None


def _private(text: str) -> bool:
    try:
        return any(ipaddress.IPv4Address(text) in net for net in PRIVATE_NETS)
    except ValueError:
        return False


def _subtype(records: dict, column: str, oid: str, subtype_column: str) -> str:
    return records.get(subtype_column + oid[len(column):], ("", ""))[1]


def check_walk(records: list[tuple[str, str, str]], reviewed: list[dict] | None = None) -> tuple[list[str], list[str]]:
    """Errors: anything identifying that capture_walk.py --sanitise or tools/qualification/anonymise.py should have
    replaced, and free-text IPv4 that neither can (edit it by hand, or acknowledge a reviewed version string)."""
    errors, warnings = [], []
    by = {oid: (tag, value) for oid, tag, value in records}
    models = {octets(*by[o]).strip("\x00 ") for o in by if o.startswith(MODEL_COLUMNS) or o in MODEL_COLUMNS} - {""}
    names = {octets(*by[o]) for o in by if o.startswith(("1.3.6.1.2.1.2.2.1.2.", "1.3.6.1.2.1.31.1.1.1.1."))}
    acknowledged = {}
    for item in reviewed or []:
        oid, address = str(item.get("oid", "")).lstrip("."), str(item.get("value", ""))
        if not item.get("reason") or not oid or not IPV4_TEXT.fullmatch(address):
            errors.append(f"reviewed_versions entry {item!r} needs an oid, a dotted-quad value and a reason")
        elif _private(address):
            errors.append(f"reviewed_versions cannot acknowledge {address} at {oid}: it is in a private address range")
        else:
            acknowledged[(oid, address)] = False
    placeholders = [
        (lambda o: o in (SYS_NAME, LLDP_LOC_SYS_NAME) or o.startswith(LLDP_REM_SYS_NAME + "."), r"device-\d{3}", "system name"),
        (lambda o: o.startswith(AI_AP_NAME + "."), r"device-\d{3}", "AP name"),
        (lambda o: o.startswith(AI_AP_SERIAL + "."), r"SERIAL-\d{4}", "AP serial number"),
        (lambda o: o == SYS_LOCATION, r"location-\d{3}", "sysLocation"),
        (lambda o: o == SYS_CONTACT, r"contact-redacted", "sysContact"),
        (lambda o: o.startswith(ENT_SERIAL + "."), r"SERIAL-\d{4}", "serial number"),
        (lambda o: o.startswith(IF_ALIAS + "."), r"alias-\d{4}", "ifAlias"),
        (lambda o: o.startswith(HOSTNAME_COLUMNS) or o in HOSTNAME_COLUMNS, r"device-\d{3}|\d+", "vendor host name"),
        (lambda o: o.startswith(VLAN_NAME_COLUMNS), r"VLAN\d{4}|(?i:default)", "VLAN name"),
        (lambda o: o.startswith(POE_LABEL), r"label-\d{3}", "PoE port label"),
        (lambda o: o.startswith(LLDP_REM_SYS_DESC), r"sysdesc-\d{3}", "neighbour system description"),
        (lambda o: o.startswith(LLDP_REM_PORT_DESC), r"portdesc-\d{3}", "neighbour port description"),
        (lambda o: o.startswith(NEIGHBOUR_TEXT_COLUMNS[2:]), r"inventory-\d{3}", "neighbour LLDP-MED inventory"),
    ]
    end_device_rows = 0
    for oid, tag, value in records:
        if oid.startswith(END_DEVICE_TABLES):
            end_device_rows += 1
        address = _man_addr_index(oid)
        if address and not _ipv4_ok(address):
            errors.append(f"{oid}: LLDP management-address index holds {address}, not a documentation address")
        if tag == "64" and not _ipv4_ok(value):
            errors.append(f"{oid}: IpAddress {value} is not a documentation address")
        if tag == "67" and value.isdigit():
            if oid == "1.3.6.1.2.1.1.3.0" and int(value) != PUBLISHED_UPTIME:
                errors.append(f"{oid}: sysUpTime is not the anonymised {PUBLISHED_UPTIME}")
            elif int(value) > PUBLISHED_UPTIME:
                errors.append(f"{oid}: TimeTicks value is older than the anonymised uptime")
        if tag == "4x" and is_mac_column(oid, by) and _real_mac(value.lower()):
            errors.append(f"{oid}: MAC address is not anonymised")
        if tag == "4x" and oid.startswith(BRIDGE_ID_COLUMNS) and len(value) == 16 and _real_mac(value[4:].lower()):
            errors.append(f"{oid}: bridge ID holds a MAC address that is not anonymised")
        if tag not in ("4", "4x"):
            continue
        text = octets(tag, value)
        clean = text.strip("\x00 ")
        for matches, pattern, label in placeholders:
            if matches(oid) and clean and not re.fullmatch(pattern, clean):
                errors.append(f"{oid}: {label} is not a sanitised placeholder")
        if oid.startswith(SERIAL_COLUMNS) and not (NOT_SERIAL.match(clean) or re.fullmatch(r"SERIAL-\d{4}", clean)
                                                   or clean in models):
            errors.append(f"{oid}: serial number, asset tag or service tag is not a placeholder")
        if oid.startswith(LLDP_REM_CHASSIS_ID) and clean:
            kind = _subtype(by, LLDP_REM_CHASSIS_ID, oid, LLDP_REM_CHASSIS_SUBTYPE)
            if kind in ("1", "2", "3", "6", "7") and not re.fullmatch(r"chassis-\d{3}", clean) \
                    and not (kind == "6" and INTERFACE_NAME.match(clean)):
                errors.append(f"{oid}: neighbour chassis ID is not a placeholder")
        if oid.startswith(LLDP_REM_PORT_ID) and clean:
            kind = _subtype(by, LLDP_REM_PORT_ID, oid, LLDP_REM_PORT_SUBTYPE)
            if (kind in ("1", "2", "6") or (kind in ("5", "7") and not INTERFACE_NAME.match(clean))) \
                    and not re.fullmatch(r"port-\d{3}", clean):
                errors.append(f"{oid}: neighbour port ID is not an interface name or placeholder")
        if oid.startswith(TLV_COLUMNS) and re.search(r"[\x20-\x7e]{4,}", text) and not re.fullmatch(r"orgdef-\d{3}", clean):
            errors.append(f"{oid}: neighbour TLV text is not a placeholder")
        if oid.startswith(LLDP_LOC_PORT_DESC) and clean and clean not in names and not INTERFACE_NAME.match(clean) \
                and not re.fullmatch(r"portdesc-\d{3}", clean):
            errors.append(f"{oid}: local port description is not an interface name or placeholder")
        for found in TEXT_MAC.finditer(text):
            raw = re.sub(r"[:-]", "", found.group(0)).lower()
            if _real_mac(raw):
                errors.append(f"{oid}: free text contains a MAC address that is not anonymised")
        for found in IPV4_TEXT.findall(text):
            if _ipv4_ok(found):
                continue
            if _private(found):
                errors.append(f"{oid}: free text contains IPv4 address {found}; edit it by hand")
            elif oid.startswith(VERSION_COLUMNS):
                continue   # a revision column: a version number, not an address
            elif (oid, found) in acknowledged:
                acknowledged[(oid, found)] = True
            else:
                errors.append(f"{oid}: free text contains IPv4 address {found}; edit it by hand, or list it in"
                              " reviewed_versions if a reviewer confirmed it is a version string")
    if end_device_rows:
        errors.append(f"{end_device_rows} rows of an end-device MAC table (dot1qTpFdbTable/dot1dTpFdbTable) are present")
    for (oid, address), used in acknowledged.items():
        if not used:
            errors.append(f"reviewed_versions acknowledges {address} at {oid}, but the walk has no such value there")
    return errors, warnings


def _real_mac(mac: str) -> bool:
    """A unicast MAC that is not an anonymised 02:00 placeholder (zero and broadcast identify nothing)."""
    return (len(mac) == 12 and mac not in ("000000000000", "ffffffffffff") and not int(mac[:2], 16) & 1
            and not mac.startswith(PLACEHOLDER_MAC))


def check_evidence(directory: Path, product: str = "network") -> tuple[list[str], list[str]]:
    capabilities = PRODUCTS[product]["capabilities"]
    evidence = load_evidence(directory)
    errors, warnings = [], []
    ident = evidence.get("id", "")
    if ident != directory.name or not re.fullmatch(r"[a-z0-9][a-z0-9.-]{0,63}", ident):
        errors.append("id must match the directory name (lower-case letters, digits, dots and hyphens)")
    kind = evidence.get("kind")
    if kind not in EVIDENCE_KINDS:
        return errors + [f"kind must be one of {', '.join(EVIDENCE_KINDS)}"], warnings
    walk = walk_path(evidence)
    if not walk.is_file():
        return errors + [f"walk {evidence.get('walk')} not found"], warnings
    if kind in ("captured", "field"):
        for key in ("vendor", "family", "model", "firmware"):
            if not str(evidence.get("device", {}).get(key, "")).strip():
                errors.append(f"device.{key} is required for {kind} evidence")
        manifest_file = directory / "manifest.json"
        if not manifest_file.is_file():
            errors.append("manifest.json from capture_walk.py is required")
        else:
            manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
            if manifest.get("format") != "network-explorer-walk-manifest-1":
                errors.append("manifest.json is not a capture_walk.py manifest")
            extra = set(manifest) - MANIFEST_KEYS
            if extra:
                errors.append(f"manifest.json has unexpected keys {sorted(extra)}; it must not carry targets or credentials")
            sanitised = manifest.get("sanitised", {})
            for flag in ("enabled", "serials", "aliases"):
                if sanitised.get(flag) is not True:
                    errors.append(f"capture was not taken with sanitisation '{flag}' (capture_walk.py --sanitise"
                                  " --sanitise-serials --sanitise-aliases)")
            if not isinstance(manifest.get("anonymised"), dict) or manifest["anonymised"].get("version", 0) < 1:
                errors.append("capture was not anonymised (tools/qualification/anonymise.py)")
        walk_errors, walk_warnings = check_walk(read_snmprec(walk), evidence.get("reviewed_versions"))
        errors += walk_errors
        warnings += walk_warnings
    if kind == "field":
        field = evidence.get("field", {})
        for key in ("observed_on", "zabbix_version", "verified"):
            if not field.get(key):
                errors.append(f"field.{key} is required for field evidence")
        if set(field.get("verified", [])) - set(capabilities):
            errors.append(f"field.verified may list only {', '.join(capabilities)}")
    if product == "network":
        template = evidence.get("template", DEFAULT_TEMPLATE)
        if template not in switch_templates():
            errors.append(f"template {template} is not a switch template")
        elif isinstance(evidence.get("classification"), dict) and evidence["classification"].get("template") != template:
            errors.append(f"classification was not replayed through {template}; run qualify.py classify --template"
                          f" {template} on the walk and store its output")
    if not isinstance(evidence.get("classification"), dict):
        errors.append("classification is missing; run qualify.py classify on the walk and store its output")
    return errors, warnings


# --- matrix ------------------------------------------------------------------------------------------------------

def evidence_index(product: str = "network") -> dict[str, dict]:
    index = {}
    root = PRODUCTS[product]["evidence_root"]
    if root.is_dir():
        for directory in sorted(p for p in root.iterdir() if p.is_dir()):
            evidence = load_evidence(directory)
            index[evidence["id"]] = evidence
    return index


def required(state: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """(evidence kinds that can support the state, classification values that support it)."""
    return {
        "Lab simulated": (("synthetic",), ("ok",)),
        "Captured-walk tested": (("captured", "field"), ("ok",)),
        "Partially qualified": (("captured", "field"), ("partial", "absent", "ok")),
        "Real-device qualified": (("field",), ("ok",)),
        "Unsupported": (("captured", "field"), ("unsupported", "absent")),
    }[state]


def validate_matrix(matrix: dict, index: dict[str, dict], product: str = "network") -> list[str]:
    """Every state other than Unqualified must be backed by cited evidence that shows it."""
    capabilities = PRODUCTS[product]["capabilities"]
    root = PRODUCTS[product]["evidence_root"].relative_to(ROOT).as_posix()
    errors = []
    seen = set()
    for row in matrix.get("rows", []):
        name = f"{row.get('vendor', '?')} {row.get('family', '?')} {row.get('model') or ''}".strip()
        key = (row.get("vendor"), row.get("family"), row.get("model"), row.get("firmware"))
        if key in seen:
            errors.append(f"{name}: duplicate row")
        seen.add(key)
        cited = []
        for ident in row.get("evidence", []):
            if ident not in index:
                errors.append(f"{name}: evidence {ident} does not exist under {root}")
            else:
                cited.append(index[ident])
        states = row.get("states", {})
        if set(states) != set(capabilities):
            errors.append(f"{name}: states must name exactly {', '.join(capabilities)}")
        for capability in capabilities:
            state = states.get(capability, "Unqualified")
            if state not in STATES:
                errors.append(f"{name}: {capability} state '{state}' is not one of {', '.join(STATES)}")
                continue
            if state == "Unqualified":
                continue
            kinds, values = required(state)
            support = [e for e in cited if e.get("kind") in kinds
                       and e.get("classification", {}).get("capabilities", {}).get(capability) in values
                       and (state != "Real-device qualified" or capability in e.get("field", {}).get("verified", []))]
            if not support:
                errors.append(f"{name}: {capability} is '{state}' but no cited {'/'.join(kinds)} evidence shows it")
            if state == "Partially qualified" and not row.get("limitations"):
                errors.append(f"{name}: {capability} is 'Partially qualified' without stated limitations")
        if any(states.get(c) not in (None, "Unqualified", "Lab simulated") for c in capabilities):
            for key in ("model", "firmware"):
                if not row.get(key):
                    errors.append(f"{name}: a real-device state needs an exact {key}")
    return errors


def render_matrix(matrix: dict, index: dict[str, dict], product: str = "network") -> str:
    meta = PRODUCTS[product]
    capabilities, labels = meta["capabilities"], meta["labels"]
    flag = "" if product == "network" else f" --product {product}"
    lines = [
        f"# {meta['title']}",
        "",
        f"<!-- Generated by tools/qualification/qualify.py{flag} matrix --write from"
        f" {meta['matrix_json'].relative_to(ROOT).as_posix()}. Do not edit by hand. -->",
        "",
        "What each state means and what evidence it needs is in [README.md](README.md). A state other than"
        f" Unqualified is accepted only when cited evidence under `{meta['evidence_root'].relative_to(ROOT).as_posix()}/`"
        f" shows it; `qualify.py{flag} matrix --check` enforces that in CI. No row says PASS: a state names the"
        " evidence behind it.",
        "",
        "| Vendor / family | Model | Firmware | " + " | ".join(labels[c] for c in capabilities)
        + " | Known limitations | Evidence | Qualified on |",
        "|---|---|---|" + "---|" * len(capabilities) + "---|---|---|",
    ]
    cell = lambda text: str(text).replace("|", "\\|").replace("\n", " ") if text else "—"
    for row in matrix.get("rows", []):
        evidence = ", ".join(f"`{e}`" for e in row.get("evidence", [])) or "None"
        lines.append("| " + " | ".join([
            cell(f"{row['vendor']} {row['family']}"), cell(row.get("model")), cell(row.get("firmware")),
            *(row["states"][c] for c in capabilities),
            cell(row.get("limitations")), evidence, cell(row.get("qualified_on"))]) + " |")
    lines += ["", "## Evidence", ""]
    if not index:
        lines.append("None yet.")
    for ident, evidence in index.items():
        caps = evidence.get("classification", {}).get("capabilities", {})
        summary = ", ".join(f"{labels[c]} {caps.get(c, '?')}" for c in capabilities)
        lines.append(f"- `{ident}` ({evidence.get('kind')}): {evidence.get('description', '').strip()} "
                     f"Classification: {summary}.")
    return "\n".join(lines) + "\n"


# --- command line ------------------------------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--product", choices=sorted(PRODUCTS), default="network",
                        help="network (switches, the default) or wifi (Wi-Fi Explorer sources)")
    commands = parser.add_subparsers(dest="command", required=True)
    one = commands.add_parser("classify", help="replay a walk through the native normalisers")
    one.add_argument("--template", default=DEFAULT_TEMPLATE,
                     help=f"switch template whose producers to replay (network only; default {DEFAULT_TEMPLATE})")
    one.add_argument("walk", type=Path)
    two = commands.add_parser("check-evidence", help="check one evidence directory")
    two.add_argument("directory", type=Path)
    three = commands.add_parser("matrix", help="validate the matrix and render MATRIX.md")
    mode = three.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="fail if MATRIX.md is stale or a claim lacks evidence")
    mode.add_argument("--write", action="store_true", help="rewrite MATRIX.md")
    args = parser.parse_args(argv)
    try:
        if args.command == "classify":
            result = (classify(args.walk, args.template) if args.product == "network"
                      else PRODUCTS[args.product]["classify"](args.walk))
            print(json.dumps(result, indent=2, sort_keys=True))
            return 0
        if args.command == "check-evidence":
            errors, warnings = check_evidence(args.directory, args.product)
            for warning in warnings:
                print(f"warning: {warning}", file=sys.stderr)
            for error in errors:
                print(f"error: {error}", file=sys.stderr)
            return 1 if errors else 0
        meta = PRODUCTS[args.product]
        matrix = json.loads(meta["matrix_json"].read_text(encoding="utf-8"))
        index = evidence_index(args.product)
        errors = validate_matrix(matrix, index, args.product)
        for ident, evidence in index.items():
            errors += [f"{ident}: {e}" for e in check_evidence(evidence["_dir"], args.product)[0]]
        rendered = render_matrix(matrix, index, args.product)
        if args.write:
            meta["matrix_md"].write_text(rendered, encoding="utf-8")
        elif meta["matrix_md"].read_text(encoding="utf-8") != rendered:
            flag = "" if args.product == "network" else f" --product {args.product}"
            errors.append(f"{meta['matrix_md'].relative_to(ROOT).as_posix()} is stale; run"
                          f" tools/qualification/qualify.py{flag} matrix --write")
        for error in errors:
            print(f"error: {error}", file=sys.stderr)
        return 1 if errors else 0
    except (UsageError, json.JSONDecodeError, FileNotFoundError, subprocess.CalledProcessError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
