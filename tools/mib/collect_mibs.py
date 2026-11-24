#!/usr/bin/env python3
"""Rebuild mib/ from the Observium Community Edition MIB folder.

The MIB modules are not published in this repository: copyright stays with the vendors and the IETF. This copies the
vendor folders the templates were designed against, plus the standard modules they import, and writes SHA256SUMS.
See mib/README.md for the archive and its checksum.

usage: python -I tools/mib/collect_mibs.py <observium/mibs> <mib>

Extract the archive into an empty folder of its own and pass its observium/mibs folder. The files are only read as
text; nothing in the archive is run.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
import re
import shutil
import sys

VENDOR_DIRS = ("ciscosb", "radlan", "dell", "force10", "broadcom", "net-snmp")
# Standard MIBs the Network Explorer templates read directly (copied with their imports).
STANDARD_ROOTS = (
    "SNMPv2-MIB", "IF-MIB", "ENTITY-MIB", "ENTITY-SENSOR-MIB", "ENTITY-STATE-MIB", "POWER-ETHERNET-MIB",
    "MAU-MIB", "IANA-MAU-MIB", "LLDP-MIB", "LLDP-EXT-MED-MIB", "LLDP-EXT-DOT1-MIB", "LLDP-EXT-DOT3-MIB",
    "BRIDGE-MIB", "Q-BRIDGE-MIB", "P-BRIDGE-MIB", "RSTP-MIB", "IEEE8023-LAG-MIB", "HOST-RESOURCES-MIB",
    "EtherLike-MIB",
)
# Single modules from other vendor folders that a template reads directly (copied with their imports):
# CISCO-ENVMON-MIB for the Cisco Business 220 hardware producer.
VENDOR_MODULES = {"cisco": ("CISCO-ENVMON-MIB",)}
# Where an imported module is looked for when several folders define it: the importer's own folder first, then these.
PREFERRED = ("rfc", "net-snmp")
# Modules every SMI tool provides itself; copied when present but never reported missing.
BUILTIN = {"SNMPv2-SMI", "SNMPv2-TC", "SNMPv2-CONF", "RFC1155-SMI", "RFC-1212", "RFC-1215", "RFC1213-MIB",
           "SNMPv2-SMI-v1"}
IMPORTS = re.compile(r"\bIMPORTS\b(.*?);", re.S)
FROM = re.compile(r"\bFROM\s+([A-Za-z][A-Za-z0-9-]*)")
DEFINITIONS = re.compile(r"^\s*([A-Za-z][A-Za-z0-9-]*)\s+DEFINITIONS\s*::=\s*BEGIN", re.M)


def strip_comments(text: str) -> str:
    return re.sub(r"--.*?(--|$)", "", text, flags=re.M)


def read(path: Path) -> str:
    return strip_comments(path.read_text(encoding="latin-1"))


def index(src: Path) -> dict[str, list[Path]]:
    """Every module name defined anywhere in the release, with the files that define it."""
    modules: dict[str, list[Path]] = {}
    for path in sorted(src.rglob("*")):
        if path.is_file():
            for name in DEFINITIONS.findall(read(path)):
                modules.setdefault(name, []).append(path)
    return modules


def resolve(modules: dict[str, list[Path]], module: str, home: str, src: Path) -> Path | None:
    paths = modules.get(module)
    if not paths:
        return None
    for folder in (home, *PREFERRED, *VENDOR_DIRS):
        for path in paths:
            if path.relative_to(src).parts[0] == folder:
                return path
    return paths[0]


def imports_of(path: Path) -> set[str]:
    found: set[str] = set()
    for block in IMPORTS.findall(read(path)):
        found.update(FROM.findall(block))
    return found


def collect(src: Path, dest: Path) -> dict:
    modules = index(src)
    wanted: dict[Path, Path] = {}
    for vendor in VENDOR_DIRS:
        folder = src / vendor
        for path in sorted(folder.iterdir()) if folder.is_dir() else ():
            if path.is_file():
                wanted[path] = path.relative_to(src)
    queue = [resolve(modules, m, "rfc", src) for m in STANDARD_ROOTS if m in modules] + list(wanted)
    queue += [resolve(modules, m, folder, src) for folder, names in VENDOR_MODULES.items() for m in names
              if m in modules]
    missing: set[tuple[str, str]] = set()
    seen: set[Path] = set()
    while queue:
        path = queue.pop()
        if path in seen:
            continue
        seen.add(path)
        rel = path.relative_to(src)
        wanted.setdefault(path, rel)
        for module in imports_of(path):
            found = resolve(modules, module, rel.parts[0], src)
            if found:
                queue.append(found)
            elif module not in BUILTIN:
                missing.add((module, rel.as_posix()))
    for name in sorted(BUILTIN):
        found = resolve(modules, name, "rfc", src)
        if found:
            wanted.setdefault(found, found.relative_to(src))
    dest.mkdir(parents=True, exist_ok=True)
    sums = []
    for path, rel in sorted(wanted.items(), key=lambda item: item[1].as_posix().lower()):
        target = dest / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
        sums.append(f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {rel.as_posix()}")
    (dest / "SHA256SUMS").write_text("\n".join(sums) + "\n", encoding="utf-8", newline="\n")
    counts: dict[str, int] = {}
    for rel in wanted.values():
        counts[rel.parts[0]] = counts.get(rel.parts[0], 0) + 1
    return {"copied": len(wanted), "folders": counts, "missing": sorted(missing),
            "other_vendors": sorted(r.as_posix() for r in wanted.values() if r.parts[0] not in VENDOR_DIRS + PREFERRED)}


def main(argv: list[str]) -> None:
    if len(argv) != 2:
        raise SystemExit(__doc__)
    result = collect(Path(argv[0]).resolve(), Path(argv[1]).resolve())
    print("copied", result["copied"], result["folders"])
    print("imports not found anywhere in the release:", result["missing"] or "none")
    print("pulled in from other vendor folders:", result["other_vendors"] or "none")


if __name__ == "__main__":
    main(sys.argv[1:])
