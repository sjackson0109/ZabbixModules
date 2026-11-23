"""tools/mib/collect_mibs.py: which modules it copies into mib/, and from which folder."""
from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("collect_mibs", ROOT / "tools/mib/collect_mibs.py")
MIBS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MIBS)


def module(name: str, *imports: str) -> str:
    block = "".join(f"    x FROM {i}\n" for i in imports)
    return f"-- {name} test module\n{name} DEFINITIONS ::= BEGIN\nIMPORTS\n{block};\nEND\n"


def release(tmp_path: Path) -> Path:
    src = tmp_path / "mibs"
    files = {
        "rfc/SNMPv2-SMI": module("SNMPv2-SMI"),
        "rfc/IF-MIB": module("IF-MIB", "SNMPv2-SMI"),
        "rfc/UNUSED-MIB": module("UNUSED-MIB", "SNMPv2-SMI"),
        # A copy of a standard module in another vendor's folder must not be chosen over rfc/.
        "acme/IF-MIB": module("IF-MIB", "SNMPv2-SMI"),
        "ciscosb/CISCOSB-X-MIB": module("CISCOSB-X-MIB", "IF-MIB", "CISCOSB-Y-MIB", "GONE-MIB"),
        "ciscosb/CISCOSB-Y-MIB": module("CISCOSB-Y-MIB", "SNMPv2-SMI"),
        # The importer's own folder wins: Dell's copy of a RADLAN module, not radlan/'s.
        "dell/Dell-A-MIB": module("Dell-A-MIB", "RADLAN-MIB"),
        "dell/RADLAN-MIB": module("RADLAN-MIB"),
        "radlan/RADLAN-MIB": module("RADLAN-MIB"),
    }
    for rel, text in files.items():
        (src / rel).parent.mkdir(parents=True, exist_ok=True)
        (src / rel).write_text(text, encoding="latin-1")
    return src


def test_copies_vendor_folders_and_the_standard_modules_they_import(tmp_path):
    src, dest = release(tmp_path), tmp_path / "mib"
    result = MIBS.collect(src, dest)
    copied = sorted(p.relative_to(dest).as_posix() for p in dest.rglob("*") if p.is_file() and p.name != "SHA256SUMS")
    assert copied == ["ciscosb/CISCOSB-X-MIB", "ciscosb/CISCOSB-Y-MIB", "dell/Dell-A-MIB", "dell/RADLAN-MIB",
                      "radlan/RADLAN-MIB", "rfc/IF-MIB", "rfc/SNMPv2-SMI"]
    assert result["missing"] == [("GONE-MIB", "ciscosb/CISCOSB-X-MIB")]
    assert result["other_vendors"] == []


def test_checksums_list_every_copied_file(tmp_path):
    src, dest = release(tmp_path), tmp_path / "mib"
    MIBS.collect(src, dest)
    lines = (dest / "SHA256SUMS").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 7
    for line in lines:
        digest, rel = line.split("  ")
        assert hashlib.sha256((src / rel).read_bytes()).hexdigest() == digest
        assert (dest / rel).read_bytes() == (src / rel).read_bytes()


def test_single_modules_from_other_vendor_folders_come_with_their_imports(tmp_path):
    src, dest = release(tmp_path), tmp_path / "mib"
    for rel, text in {"cisco/CISCO-ENVMON-MIB": module("CISCO-ENVMON-MIB", "CISCO-SMI", "SNMPv2-SMI"),
                      "cisco/CISCO-SMI": module("CISCO-SMI", "SNMPv2-SMI"),
                      "cisco/CISCO-UNUSED-MIB": module("CISCO-UNUSED-MIB", "SNMPv2-SMI")}.items():
        (src / rel).parent.mkdir(parents=True, exist_ok=True)
        (src / rel).write_text(text, encoding="latin-1")
    result = MIBS.collect(src, dest)
    copied = {p.relative_to(dest).as_posix() for p in dest.rglob("*") if p.is_file()}
    # Only the named module and what it imports, never the rest of that vendor's folder.
    assert {"cisco/CISCO-ENVMON-MIB", "cisco/CISCO-SMI"} <= copied and "cisco/CISCO-UNUSED-MIB" not in copied
    assert result["other_vendors"] == ["cisco/CISCO-ENVMON-MIB", "cisco/CISCO-SMI"]
