#!/usr/bin/env python3
"""Copy the shared widget runtime and stylesheet into each widget module.

Zabbix serves a module's assets only from its own directory, so every widget ships a copy. The copies are
generated from src/widget; edit the source and run this script, never the copies.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src" / "widget"
WIDGETS = ("neportpanel", "netopology", "neinterfacedetail", "nedataquality", "nefindings")
ASSETS = {"runtime.js": Path("assets/js/runtime.js"), "widget.css": Path("assets/css/widget.css")}


def targets():
    for widget in WIDGETS:
        for name, relative in ASSETS.items():
            yield SOURCE / name, ROOT / "frontend" / widget / relative


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
