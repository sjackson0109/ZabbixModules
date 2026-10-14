#!/usr/bin/env python3
"""Copy the shared runtime and stylesheets into each widget module and both Explorer page modules.

Zabbix serves a module's assets only from its own directory, so every widget, and each Explorer page, ships a copy:
one topology implementation and one set of design tokens, several presentation hosts. The copies are generated from
src/widget and src/design; edit the source and run this script, never the copies.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
WIDGETS = ("neportpanel", "netopology", "neinterfacedetail", "nedataquality", "nefindings", "networkexplorer")
# Source file -> (where each copy lives in a module, the modules that ship it).
ASSETS = {
    ROOT / "src" / "widget" / "runtime.js": (Path("assets/js/runtime.js"), WIDGETS),
    ROOT / "src" / "widget" / "widget.css": (Path("assets/css/widget.css"), WIDGETS),
    ROOT / "src" / "design" / "explorers.css": (Path("assets/css/explorers.css"), WIDGETS + ("wifiexplorer",)),
}


def targets():
    for source, (relative, modules) in ASSETS.items():
        for module in modules:
            yield source, ROOT / "frontend" / module / relative


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="fail if any copy differs from src/widget")
    args = parser.parse_args()
    stale = []
    for source, target in targets():
        content = source.read_bytes()
        if target.exists() and target.read_bytes() == content:
            continue
        if args.check:
            stale.append(target.relative_to(ROOT))
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
    if stale:
        print("Widget assets are out of date; run scripts/sync_widget_assets.py:", file=sys.stderr)
        for path in stale:
            print(f"  {path}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
