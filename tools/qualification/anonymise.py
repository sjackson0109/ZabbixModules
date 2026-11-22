#!/usr/bin/env python3
"""Anonymise capture_walk.py output before it is published as qualification evidence.

``capture_walk.py --sanitise`` replaces names, addresses, serial numbers and aliases in the standard columns it
knows. This repository is public, so evidence must also carry no real asset details and nothing that helps an
attack on the estate it came from. This second pass removes what the sanitiser leaves:

- MAC addresses, wherever the MIBs put one, are replaced with locally administered ``02:00:xx:xx:xx:xx``
  addresses. The same real MAC gets the same placeholder in every walk, so joins and neighbours still match.
- Host names in vendor tables, vendor and LLDP-MED serial numbers, asset tags and Dell service tags.
- VLAN names, PoE port labels, and everything a neighbour says about itself over LLDP: system and port
  descriptions, locally assigned chassis and port IDs, LLDP-MED inventory and organisation-defined TLV text.
- The end-device MAC table (``dot1qTpFdbTable``, ``dot1dTpFdbTable``), which no template reads.
- Uptime: ``sysUpTime`` becomes 7 days, and every TimeTicks value and LLDP/Q-BRIDGE time mark keeps its age up to
  7 days; anything older reads as "since start-up".
- The ``net_snmp_version`` of the capture host, from the manifest.

OID indexes keep their joins: a time mark rewritten in one LLDP table is rewritten identically in all of them.

Stdlib only (Python 3.10+). Never prints a real value.

  anonymise.py --map PRIVATE-MAP.json [--config PRIVATE-CONFIG.json] --out-dir DIR WALK.snmprec [WALK.snmprec ...]

Each ``WALK.snmprec`` needs the ``WALK.manifest.json`` that capture_walk.py wrote beside it. The output is
``DIR/<label>/capture.snmprec`` and ``DIR/<label>/manifest.json``, ready for an evidence directory. Anonymise every
walk of one estate with the same map, so the same real value always gets the same placeholder.

The map holds the real values. Keep it private beside the ``--sanitise-map`` and never commit it. The optional
config holds estate-specific rules, which are private too:

  {"name_patterns": ["(?i)\\\\bSITE-[A-Z0-9-]+"],
   "version_masks": {"1.0.8802.1.1.2.1.4.1.1.10.": ["1.2.3.4"]}}

``name_patterns`` are replaced with ``name-NNN`` in any text. ``version_masks`` lists version strings that a
reviewer has confirmed are not addresses but that sit outside the MIB revision columns; each is masked in place
(digits become ``x``) in the column it is listed under. ``qualify.py check-evidence`` then checks the result.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import qualify  # noqa: E402  (the column definitions are shared with check-evidence)

FORMAT_VERSION = 1
UPTIME = qualify.PUBLISHED_UPTIME
TOOL = "tools/qualification/anonymise.py"

SYS_UPTIME = "1.3.6.1.2.1.1.3.0"
IF_DESCR = "1.3.6.1.2.1.2.2.1.2."
IF_NAME = "1.3.6.1.2.1.31.1.1.1.1."
LOC_MAN_ADDR = "1.0.8802.1.1.2.1.3.8.1."
DROP = ("1.3.6.1.2.1.17.7.1.2.2.", "1.3.6.1.2.1.17.4.3.")   # dot1qTpFdbTable, dot1dTpFdbTable
URL_COLUMN = "1.3.6.1.4.1.674.10895.3000.1.2.100.6.0"      # Dell productIdentificationURL
NOT_SERIAL = {"", "none", "not available", "n/a", "na", "unknown"}
IDRAC_PORT = re.compile(r"^([0-9A-Z]{7}) Dedicated$")
PRINTABLE_RUN = re.compile(r"[\x20-\x7e]{4,}")
IPV4 = qualify.IPV4_TEXT
MAC_COLON = re.compile(r"(?i)\b[0-9a-f]{2}([:-])(?:[0-9a-f]{2}\1){4}[0-9a-f]{2}\b")
MAC_PAIRS = re.compile(r"(?i)\b[0-9a-f]{2}([. ])(?:[0-9a-f]{2}\1){4}[0-9a-f]{2}\b")
MAC_DOTTED = re.compile(r"(?i)\b[0-9a-f]{4}\.[0-9a-f]{4}\.[0-9a-f]{4}\b")
MAC_BARE = re.compile(r"(?i)(?<![0-9a-f])(?:SEP)?([0-9a-f]{12})(?![0-9a-f])")
MAC_NAME = re.compile(r"(?i)\bswitch([0-9a-f]{6})\b")       # Cisco SB default host name: switch + last 3 octets

TIMESTAMP_COLUMNS = (   # TimeTicks holding the sysUpTime of an event
    "1.3.6.1.2.1.2.2.1.9.", "1.3.6.1.2.1.31.1.1.1.19.", "1.3.6.1.2.1.17.7.1.4.2.1.7.", "1.3.6.1.2.1.1.8.0",
    "1.3.6.1.2.1.1.9.1.4.", "1.0.8802.1.1.2.1.2.1.0", "1.2.840.10006.300.43.1.3.0",
)


# --- records -----------------------------------------------------------------------------------------------------

def text_of(tag: str, value: str) -> str | None:
    if tag == "4x":
        try:
            return bytes.fromhex(value).decode("latin-1")
        except ValueError:
            return None
    return value if tag == "4" else None


def encode(tag: str, text: str) -> str:
    return text.encode("latin-1").hex() if tag == "4x" else text


def unicast(mac: str) -> bool:
    return len(mac) == 12 and mac not in ("000000000000", "ffffffffffff") and not int(mac[:2], 16) & 1


def write_private(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(content)


class Placeholders:
    """real value -> placeholder, kept in the private map so that every run and every walk agree."""

    FORMATS = {"serial": "SERIAL-9{:03d}", "chassis": "chassis-{:03d}", "port": "port-{:03d}",
               "portdesc": "portdesc-{:03d}", "sysdesc": "sysdesc-{:03d}", "inventory": "inventory-{:03d}",
               "orgdef": "orgdef-{:03d}", "label": "label-{:03d}", "name": "name-{:03d}", "mac": "0200{:08x}",
               "macname": "{:06x}"}

    def __init__(self, path: Path):
        self.path = path
        self.data = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}

    def get(self, kind: str, real: str) -> str:
        table = self.data.setdefault(kind, {})
        if real not in table:
            table[real] = self.FORMATS[kind].format(len(table) + 1)
        return table[real]

    def save(self) -> None:
        write_private(self.path, json.dumps(self.data, indent=1, sort_keys=True) + "\n")


# --- MAC addresses -----------------------------------------------------------------------------------------------

def subtype(records: dict, column: str, oid: str, prefix: str) -> str | None:
    return records.get(column + oid[len(prefix):], (None, None))[1]


def mac_values(records: list[tuple[str, str, str]]) -> set[str]:
    """Real MACs: 6-octet values in MAC-typed columns (LLDP IDs only of the MAC subtype), and the MAC half of
    STP bridge IDs. Other octet strings of six bytes (port bitmaps, protocol IDs) are never treated as MACs."""
    by = {oid: (tag, value) for oid, tag, value in records}
    found = set()
    for oid, tag, value in records:
        if tag != "4x":
            continue
        v = value.lower()
        if qualify.is_mac_column(oid, by) and unicast(v):
            found.add(v)
        elif oid.startswith(qualify.BRIDGE_ID_COLUMNS) and len(v) == 16 and unicast(v[4:]):
            found.add(v[4:])
    return found


class Macs:
    def __init__(self, placeholders: Placeholders, known: set[str]):
        if any(k.startswith("0200") for k in known):
            raise SystemExit("error: a real MAC already uses the 02:00 placeholder prefix")
        self.p, self.known = placeholders, known

    def fake(self, real: str) -> str:
        return self.p.get("mac", real)

    def in_octets(self, value: str) -> str:
        """Every known MAC at a byte boundary inside an octet string (TLV payloads)."""
        h, out, i, changed = value.lower(), [], 0, False
        while i < len(h):
            if h[i:i + 12] in self.known:
                out.append(self.fake(h[i:i + 12]))
                i, changed = i + 12, True
            else:
                out.append(h[i:i + 2])
                i += 2
        return "".join(out) if changed else value

    def in_text(self, text: str, own_chassis: str | None) -> str:
        def styled(real: str, sep: str, upper: bool) -> str:
            f = self.fake(real)
            s = sep.join(f[i:i + 2] for i in range(0, 12, 2))
            return s.upper() if upper else s

        def colon(m):   # unambiguous MAC syntax: replace even a MAC not seen in a MAC column
            raw = re.sub(r"[:-]", "", m.group(0)).lower()
            return styled(raw, m.group(1), m.group(0).isupper()) if unicast(raw) else m.group(0)

        def pairs(m):
            raw = re.sub(r"[. ]", "", m.group(0)).lower()
            return styled(raw, m.group(1), m.group(0).isupper()) if raw in self.known else m.group(0)

        def dotted(m):
            raw = m.group(0).replace(".", "").lower()
            if raw not in self.known:
                return m.group(0)
            f = self.fake(raw)
            return ".".join(f[i:i + 4] for i in range(0, 12, 4))

        def bare(m):
            raw = m.group(1).lower()
            if raw not in self.known:
                return m.group(0)
            f = self.fake(raw)
            return m.group(0)[:-12] + (f.upper() if m.group(1).isupper() else f)

        def name(m):
            tail = m.group(1).lower()
            real = own_chassis if own_chassis and own_chassis.endswith(tail) else \
                next((k for k in sorted(self.known) if k.endswith(tail)), None)
            return m.group(0)[:-6] + (self.fake(real)[-6:] if real else self.p.get("macname", tail))

        for rx, fn in ((MAC_COLON, colon), (MAC_PAIRS, pairs), (MAC_DOTTED, dotted), (MAC_BARE, bare), (MAC_NAME, name)):
            text = rx.sub(fn, text)
        return text

    def in_index(self, oid: str) -> str:
        arcs = oid.split(".")
        for i in range(7, len(arcs) - 5):
            window = arcs[i:i + 6]
            if all(a.isdigit() and int(a) < 256 for a in window):
                h = "".join(f"{int(a):02x}" for a in window)
                if h in self.known:
                    f = self.fake(h)
                    arcs[i:i + 6] = [str(int(f[j:j + 2], 16)) for j in range(0, 12, 2)]
        return ".".join(arcs)


# --- time --------------------------------------------------------------------------------------------------------

class Clock:
    """Keeps each timestamp's age (sysUpTime minus the value) up to UPTIME; older reads as start-up (0)."""

    def __init__(self, uptime: int | None):
        self.uptime = uptime

    def stamp(self, ticks: int) -> int:
        if ticks == 0 or self.uptime is None:
            return min(ticks, UPTIME)
        age = max(self.uptime - ticks, 0)
        return 0 if age >= UPTIME else UPTIME - age

    @staticmethod
    def duration(ticks: int) -> int:
        return min(ticks, UPTIME)

    def index(self, oid: str) -> str:
        arcs = oid.split(".")
        position = qualify.time_mark_position(arcs)
        if position is not None and arcs[position].isdigit():
            arcs[position] = str(self.stamp(int(arcs[position])))
        return ".".join(arcs)


# --- one walk ----------------------------------------------------------------------------------------------------

CONFIG_MAN_ADDR = "1.0.8802.1.1.2.1.1.7.1."   # lldpConfigManAddrTable: column . subtype . length . address


def config_man_addr(oid: str, own: list[str]) -> str:
    """Captures sanitised before capture_walk.py covered lldpConfigManAddrTable still carry the real management
    address in its index. Its rows are the local management addresses, so the sanitised lldpLocManAddr address is
    the right replacement when the device has exactly one."""
    if not oid.startswith(CONFIG_MAN_ADDR):
        return oid
    arcs = oid[len(CONFIG_MAN_ADDR):].split(".")
    if len(arcs) == 7 and arcs[1:3] == ["1", "4"] and not qualify._ipv4_ok(".".join(arcs[3:])):
        if len(own) != 1:
            raise SystemExit("error: lldpConfigManAddrTable holds a real address and the walk has "
                             f"{len(own)} local management addresses; edit it by hand")
        arcs[3:] = own[0].split(".")
    return CONFIG_MAN_ADDR + ".".join(arcs)


def interface_like(text: str, names: set[str]) -> bool:
    return text in names or bool(qualify.INTERFACE_NAME.match(text))


def anonymise_walk(records, placeholders: Placeholders, macs: Macs, config: dict, counts: Counter):
    by = {oid: (tag, value) for oid, tag, value in records}
    sysname = text_of(*by.get(qualify.SYS_NAME, ("4", ""))) or ""
    own_addresses = sorted({".".join(oid.split(".")[-4:]) for oid in by if oid.startswith(LOC_MAN_ADDR)
                            and oid.split(".")[-6:-4] == ["1", "4"]})
    own_address = own_addresses[0] if own_addresses else None
    own_chassis = by.get(qualify.LLDP_LOC_CHASSIS_ID, ("", ""))[1].lower() or None
    uptime = by.get(SYS_UPTIME, ("67", None))[1]
    clock = Clock(int(uptime) if uptime and uptime.isdigit() else None)
    names = {text_of(t, v) for o, (t, v) in by.items() if o.startswith((IF_DESCR, IF_NAME))} - {None}
    patterns = [re.compile(p) for p in config.get("name_patterns", [])]
    masks = config.get("version_masks", {})

    models = {(text_of(t, v) or "").strip("\x00 ") for o, (t, v) in by.items()
              if o.startswith(qualify.MODEL_COLUMNS) or o in qualify.MODEL_COLUMNS} - {""}
    secrets = {}   # every other occurrence of a serial or tag is replaced too (never a model name or a short value)
    for oid, tag, value in records:
        text = (text_of(tag, value) or "").strip("\x00 ")
        if oid.startswith(qualify.SERIAL_COLUMNS) and text.lower() not in NOT_SERIAL and text not in models \
                and len(text) >= 6:
            secrets[text] = placeholders.get("serial", text)
        if oid.startswith(qualify.LLDP_REM_PORT_ID) and IDRAC_PORT.match(text):
            tag7 = IDRAC_PORT.match(text).group(1)
            secrets[tag7] = placeholders.get("serial", tag7)

    out = []
    for oid, tag, value in records:
        if oid.startswith(DROP):
            counts["end-device MAC table dropped"] += 1
            continue
        new_value = value
        text = text_of(tag, value)
        if text is not None:
            new = rewrite_text(oid, text, by, sysname, own_address, names, models, secrets, placeholders, counts)
            for pattern in patterns:
                new = pattern.sub(lambda m: placeholders.get("name", m.group(0)), new)
            for prefix, values in masks.items():
                if oid.startswith(prefix):
                    new = IPV4.sub(lambda m: re.sub(r"\d", "x", m.group(0)) if m.group(0) in values else m.group(0), new)
            if new != text:
                counts["text"] += 1
                new_value = encode(tag, new)
        if tag == "4x":
            if qualify.is_mac_column(oid, by) and new_value.lower() in macs.known:
                new_value = macs.fake(new_value.lower())
            elif oid.startswith(qualify.BRIDGE_ID_COLUMNS) and len(new_value) == 16 and new_value[4:].lower() in macs.known:
                new_value = new_value[:4] + macs.fake(new_value[4:].lower())
            elif oid.startswith(qualify.TLV_COLUMNS):
                new_value = macs.in_octets(new_value)
            decoded = text_of(tag, new_value)
            if decoded is not None and decoded.isprintable():
                new_value = encode(tag, macs.in_text(decoded, own_chassis))
        elif tag == "4":
            new_value = macs.in_text(new_value, own_chassis)
        elif tag == "67" and value.isdigit():
            ticks = int(value)
            new_value = str(UPTIME if oid == SYS_UPTIME else clock.stamp(ticks)
                            if oid.startswith(TIMESTAMP_COLUMNS) else clock.duration(ticks))
        if new_value != value and tag in ("4", "4x"):
            counts["changed"] += 1
        new_oid = macs.in_index(clock.index(config_man_addr(oid, own_addresses)))
        out.append((new_oid, tag, new_value))
    if len({o for o, _, _ in out}) != len(out):
        raise SystemExit("error: rewriting time marks or MACs in OID indexes made two rows collide")
    return out


def rewrite_text(oid, text, by, sysname, own_address, names, models, secrets, p: Placeholders, counts) -> str:
    clean = text.strip("\x00 ")
    if (oid.startswith(qualify.HOSTNAME_COLUMNS) or oid in qualify.HOSTNAME_COLUMNS) and clean and not clean.isdigit():
        counts["host names"] += 1
        return sysname
    if oid == URL_COLUMN and own_address:
        return IPV4.sub(own_address, text)
    if oid.startswith(qualify.SERIAL_COLUMNS) or oid in qualify.SERIAL_COLUMNS:
        if clean.lower() in NOT_SERIAL or clean in models:
            return text
        counts["serials"] += 1
        return p.get("serial", clean)
    if oid.startswith(qualify.LLDP_REM_CHASSIS_ID):
        kind = subtype(by, qualify.LLDP_REM_CHASSIS_SUBTYPE, oid, qualify.LLDP_REM_CHASSIS_ID)
        if kind in ("1", "2", "3", "6", "7") and clean and not (kind == "6" and interface_like(clean, set())):
            counts["neighbour IDs"] += 1
            return p.get("chassis", text)
        return text
    if oid.startswith(qualify.LLDP_REM_PORT_ID):
        kind = subtype(by, qualify.LLDP_REM_PORT_SUBTYPE, oid, qualify.LLDP_REM_PORT_ID)
        if kind in ("1", "2", "6") or (kind in ("5", "7") and clean and not interface_like(clean, set())):
            counts["neighbour IDs"] += 1
            return p.get("port", text)
        return text
    if oid.startswith(qualify.NEIGHBOUR_TEXT_COLUMNS):
        if not clean:
            return text
        counts["neighbour details"] += 1
        kind = "sysdesc" if oid.startswith(qualify.LLDP_REM_SYS_DESC) else \
            "portdesc" if oid.startswith(qualify.LLDP_REM_PORT_DESC) else "inventory"
        return p.get(kind, text)
    if oid.startswith(qualify.TLV_COLUMNS):
        if PRINTABLE_RUN.search(text):
            counts["neighbour details"] += 1
            return p.get("orgdef", text)
        return text
    if oid.startswith(qualify.LLDP_LOC_PORT_DESC):
        if clean and clean not in names and not interface_like(clean, names):
            counts["port descriptions"] += 1
            return p.get("portdesc", text)
        return text
    if oid.startswith(qualify.VLAN_NAME_COLUMNS):
        if clean.lower() in ("", "default"):
            return text
        counts["VLAN names"] += 1
        return f"VLAN{int(oid.rsplit('.', 1)[1]):04d}"
    if oid.startswith(qualify.POE_LABEL):
        if not clean:
            return text
        counts["PoE labels"] += 1
        return p.get("label", clean)
    new = text
    for real in sorted(secrets, key=len, reverse=True):
        if real and real in new:
            new = new.replace(real, secrets[real])
    return new


# --- manifest and command line -----------------------------------------------------------------------------------

def anonymise_manifest(manifest: dict, records: list[tuple[str, str, str]], rules: list[str]) -> dict:
    manifest = dict(manifest)
    manifest.pop("net_snmp_version", None)
    manifest["record_count"] = len(records)
    oids = [oid for oid, _, _ in records]
    for subtree in manifest.get("subtrees", []):
        if subtree.get("oid") and "records" in subtree:   # counts after anonymisation (the FDB is gone)
            root = subtree["oid"]
            subtree["records"] = sum(1 for o in oids if o == root or o.startswith(root + "."))
    manifest["anonymised"] = {"tool": TOOL, "version": FORMAT_VERSION, "uptime_ticks": UPTIME, "rules": rules}
    return manifest


RULES = ["mac-addresses", "vendor-host-names", "serial-numbers-and-service-tags", "vlan-names", "poe-labels",
         "neighbour-lldp-details", "end-device-mac-tables-dropped", "time-ticks", "manifest-net-snmp-version-dropped"]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--map", required=True, type=Path, help="private real-to-placeholder map (created if absent)")
    parser.add_argument("--config", type=Path, help="private estate-specific rules (JSON)")
    parser.add_argument("--out-dir", required=True, type=Path)
    parser.add_argument("walks", nargs="+", type=Path)
    args = parser.parse_args(argv)
    config = json.loads(args.config.read_text(encoding="utf-8")) if args.config else {}
    walks = {}
    for walk in sorted(args.walks):
        manifest = walk.with_name(walk.name[:-len(".snmprec")] + ".manifest.json")
        if not walk.name.endswith(".snmprec") or not manifest.is_file():
            print(f"error: {walk}: needs a .snmprec walk with its capture_walk.py manifest beside it", file=sys.stderr)
            return 2
        walks[walk] = (qualify.read_snmprec(walk), json.loads(manifest.read_text(encoding="utf-8")))
    placeholders = Placeholders(args.map)
    known = set(placeholders.data.get("mac", {}))
    for records, _ in walks.values():
        known |= mac_values(records)
    macs = Macs(placeholders, known)
    for walk, (records, manifest) in walks.items():
        label = manifest.get("device_label") or walk.name[:-len(".snmprec")]
        counts = Counter()
        clean = anonymise_walk(records, placeholders, macs, config, counts)
        target = args.out_dir / label
        target.mkdir(parents=True, exist_ok=True)
        (target / "capture.snmprec").write_text("".join(f"{o}|{t}|{v}\n" for o, t, v in clean), encoding="utf-8",
                                                newline="\n")
        (target / "manifest.json").write_text(json.dumps(anonymise_manifest(manifest, clean, RULES), indent=2) + "\n",
                                              encoding="utf-8", newline="\n")
        print(f"{label}: {len(records)} -> {len(clean)} records; "
              + ", ".join(f"{k} {v}" for k, v in sorted(counts.items()) if k not in ("text", "changed")), file=sys.stderr)
    placeholders.save()
    return 0


if __name__ == "__main__":
    sys.exit(main())
