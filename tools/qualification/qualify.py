#!/usr/bin/env python3
"""Hardware qualification: classify walks, check evidence, and keep the qualification matrix honest.

Stdlib only (Python 3.10+); ``classify`` also needs Node.js, because it replays a walk through the same native
template normalisers Zabbix runs (``tests/js/run_normaliser.cjs``). Nothing here talks to a device or to Zabbix.

  qualify.py [--product P] classify <file.snmprec>       per-dataset outcome of the native normalisers, as JSON
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

# Raw template keys replayed for a classification, and the canonical dataset each produces.
RAW_KEYS = {
    "device": "ne.raw.system",
    "interfaces_state": "ne.raw.if.state",
    "interfaces_inventory": "ne.raw.if.inventory",
    "port_capability": "ne.raw.if.capability",
    "lldp": "ne.raw.lldp",
    "vlan": "ne.raw.vlan",
    "stp": "ne.raw.stp",
    "lag": "ne.raw.lag",
}
CAPABILITIES = ("interfaces", "entity", "mau", "lldp", "vlan", "stp", "lag")
CAPABILITY_LABELS = {"interfaces": "Interfaces", "entity": "ENTITY", "mau": "MAU", "lldp": "LLDP",
                     "vlan": "VLAN", "stp": "STP", "lag": "LAG"}

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
LLDP_MAN_ADDR_ENTRIES = (("1.0.8802.1.1.2.1.3.8.1", 0), ("1.0.8802.1.1.2.1.4.2.1", 3))
ARUBA_AI = "1.3.6.1.4.1.14823.2.3.3.1"
AI_AP_NAME = ARUBA_AI + ".2.1.1.2"
AI_AP_SERIAL = ARUBA_AI + ".2.1.1.4"
DOCUMENTATION_NETS = tuple(ipaddress.IPv4Network(n) for n in ("192.0.2.0/24", "198.51.100.0/24", "203.0.113.0/24"))
MANIFEST_KEYS = {"format", "device_label", "captured_at", "net_snmp_version", "snmp_version", "snmp_security_level",
                 "walk_options", "sanitised", "sanitisation_limits", "snmprec_file", "record_count", "subtrees"}
IPV4_TEXT = re.compile(r"(?<![\d.])(\d{1,3}(?:\.\d{1,3}){3})(?![\d.])")
MAC_TEXT = re.compile(r"^(?:[0-9a-f]{12})$")


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
    """ok (rows present), empty (collected, nothing observed), partial, unsupported or failed."""
    status = outcome["status"]
    if status == "ok":
        return "ok" if outcome["rows"] or not need_rows else "empty"
    return status if status in ("partial", "unsupported", "failed") else "failed"


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


def classify(walk: Path) -> dict:
    """Replays a walk through every native normaliser and states, per matrix capability, what it shows."""
    envelopes = {name: run_normaliser(key, walk) for name, key in RAW_KEYS.items()}
    datasets = {name: dataset_outcome(envelope) for name, envelope in envelopes.items()}
    caps = {}
    state, inventory = datasets["interfaces_state"], datasets["interfaces_inventory"]
    worst = [capability_from(state), capability_from(inventory)]
    caps["interfaces"] = next((s for s in ("failed", "unsupported", "partial", "empty") if s in worst), "ok")
    placed = [row for row in envelopes["interfaces_inventory"].get("data") or []
              if row.get("member") is not None or row.get("slot") is not None]
    # ENTITY-MIB placement is only visible through the inventory rows it places.
    caps["entity"] = ("ok" if placed else "absent") if caps["interfaces"] in ("ok", "partial") else caps["interfaces"]
    caps["mau"] = capability_from(datasets["port_capability"])
    for name in ("lldp", "vlan", "stp", "lag"):
        caps[name] = capability_from(datasets[name])
    records = {oid: (tag, value) for oid, tag, value in read_snmprec(walk)}
    system = {"sys_object_id": records.get(SYS_OBJECT_ID, ("", ""))[1],
              "sys_descr": octets(*records.get(SYS_DESCR, ("4", "")))}
    return {"format": "network-explorer-classification-1", "system": system, "datasets": datasets,
            "capabilities": caps}


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


def check_walk(records: list[tuple[str, str, str]]) -> tuple[list[str], list[str]]:
    """Errors: anything identifying that the capture sanitiser should have replaced, or free-text IPv4 it cannot.
    Warnings: what the sanitiser deliberately keeps (MAC addresses), for the reviewer."""
    errors, warnings = [], []
    placeholders = [
        (lambda o: o in (SYS_NAME, LLDP_LOC_SYS_NAME) or o.startswith(LLDP_REM_SYS_NAME + "."), r"device-\d{3}", "system name"),
        (lambda o: o.startswith(AI_AP_NAME + "."), r"device-\d{3}", "AP name"),
        (lambda o: o.startswith(AI_AP_SERIAL + "."), r"SERIAL-\d{4}", "AP serial number"),
        (lambda o: o == SYS_LOCATION, r"location-\d{3}", "sysLocation"),
        (lambda o: o == SYS_CONTACT, r"contact-redacted", "sysContact"),
        (lambda o: o.startswith(ENT_SERIAL + "."), r"SERIAL-\d{4}", "serial number"),
        (lambda o: o.startswith(IF_ALIAS + "."), r"alias-\d{4}", "ifAlias"),
    ]
    macs = 0
    for oid, tag, value in records:
        address = _man_addr_index(oid)
        if address and not _ipv4_ok(address):
            errors.append(f"{oid}: LLDP management-address index holds {address}, not a documentation address")
        if tag == "64" and not _ipv4_ok(value):
            errors.append(f"{oid}: IpAddress {value} is not a documentation address")
        if tag not in ("4", "4x"):
            continue
        text = octets(tag, value)
        for matches, pattern, label in placeholders:
            if matches(oid) and text and not re.fullmatch(pattern, text):
                errors.append(f"{oid}: {label} is not a sanitised placeholder")
        for found in IPV4_TEXT.findall(text):
            if not _ipv4_ok(found):
                errors.append(f"{oid}: free text contains IPv4 address {found}; edit it by hand")
        if tag == "4x" and len(value) == 12 and MAC_TEXT.match(value.lower()):
            macs += 1
    if macs:
        warnings.append(f"{macs} six-octet values (MAC addresses) are kept as captured; confirm they may be shared")
    return errors, warnings


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
        walk_errors, walk_warnings = check_walk(read_snmprec(walk))
        errors += walk_errors
        warnings += walk_warnings
    if kind == "field":
        field = evidence.get("field", {})
        for key in ("observed_on", "zabbix_version", "verified"):
            if not field.get(key):
                errors.append(f"field.{key} is required for field evidence")
        if set(field.get("verified", [])) - set(capabilities):
            errors.append(f"field.verified may list only {', '.join(capabilities)}")
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
            print(json.dumps(PRODUCTS[args.product]["classify"](args.walk), indent=2, sort_keys=True))
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
