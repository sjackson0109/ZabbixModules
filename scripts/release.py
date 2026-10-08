#!/usr/bin/env python3
"""Prepare and verify tagged releases.

  bump X.Y.Z        Set every shipped version to X.Y.Z, regenerate the templates and
                    move the changelog's Unreleased section under X.Y.Z.
  check vX.Y.Z      Fail unless the tag, the VERSION file, every component version and
                    the changelog agree. The release workflow runs this on each tag.
  notes X.Y.Z       Print the changelog section for X.Y.Z (the GitHub release notes).
"""
from __future__ import annotations

import argparse
import datetime
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
SEMVER = r"\d+\.\d+\.\d+(?:-[0-9A-Za-z.]+)?"
# Files whose single version string is rewritten by `bump`: (path glob, pattern with one group around the version).
VERSIONED = [
    ("frontend/*/manifest.json", r'^(\s*"version": ")' + SEMVER + r'(",?)$'),
    ("collector/pyproject.toml", r'^(version = ")' + SEMVER + r'(")$'),
    ("collector/network_explorer/__init__.py", r'^(__version__ = ")' + SEMVER + r'(")$'),
    ("templates/source/js/lib.js", r"^(NE\.VERSION = ')" + SEMVER + r"(';.*)$"),
]
# Operator docs that name the release in commands and file names.
DOCS = ["docs/operations/INSTALL.md", "docs/operations/DEPLOYMENT_GUIDE.md"]
GENERATORS = [["templates/generate_snmp.py"], ["templates/generate_lab.py"]]


def current() -> str:
    return (ROOT / "VERSION").read_text(encoding="utf-8").strip()


def key(version: str) -> tuple:
    core, _, pre = version.partition("-")
    # A pre-release sorts before its release.
    return tuple(int(part) for part in core.split(".")) + ((0, pre) if pre else (1, ""))


def component_versions() -> dict[str, str]:
    found = {"VERSION": current()}
    for pattern, regex in VERSIONED:
        for path in sorted(ROOT.glob(pattern)):
            match = re.search(regex, path.read_text(encoding="utf-8"), re.M)
            found[str(path.relative_to(ROOT))] = re.search(SEMVER, match.group(0)).group(0) if match else "no version"
    return found


def changelog_section(version: str) -> str | None:
    text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    match = re.search(rf"^## \[{re.escape(version)}\][^\n]*\n(.*?)(?=^## |\Z)", text, re.M | re.S)
    return match.group(1).strip() if match else None


def bump(version: str) -> None:
    old = current()
    if not re.fullmatch(SEMVER, version):
        sys.exit(f"Not a semantic version: {version}")
    if key(version) <= key(old):
        sys.exit(f"{version} is not newer than the current version {old}")
    changelog = ROOT / "CHANGELOG.md"
    text = changelog.read_text(encoding="utf-8")
    unreleased = re.search(r"^## \[Unreleased\]\n(.*?)(?=^## |\Z)", text, re.M | re.S)
    if not unreleased or not unreleased.group(1).strip():
        sys.exit("CHANGELOG.md has no Unreleased entries to release")

    (ROOT / "VERSION").write_text(version + "\n", encoding="utf-8")
    for pattern, regex in VERSIONED:
        for path in sorted(ROOT.glob(pattern)):
            source = path.read_text(encoding="utf-8")
            updated, count = re.subn(regex, lambda m: m.group(1) + version + m.group(2), source, count=1, flags=re.M)
            if count != 1:
                sys.exit(f"No version found in {path.relative_to(ROOT)}")
            path.write_text(updated, encoding="utf-8")
    for doc in DOCS:
        path = ROOT / doc
        path.write_text(path.read_text(encoding="utf-8").replace(old, version), encoding="utf-8")
    today = datetime.date.today().isoformat()
    changelog.write_text(text.replace("## [Unreleased]\n", f"## [Unreleased]\n\n## [{version}] - {today}\n", 1),
                         encoding="utf-8")
    for generator in GENERATORS:
        subprocess.run([sys.executable, str(ROOT / generator[0]), *generator[1:]], check=True, cwd=ROOT)
    print(f"Bumped {old} -> {version}. Review the diff, run the checks, and merge before tagging v{version}.")


def check(tag: str) -> None:
    errors = []
    version = current()
    if tag != f"v{version}":
        errors.append(f"Tag {tag} does not match VERSION {version} (expected v{version})")
    for path, found in component_versions().items():
        if found != version:
            errors.append(f"{path} carries {found!r}, not {version}")
    if not changelog_section(version):
        errors.append(f"CHANGELOG.md has no '## [{version}]' section")
    if errors:
        sys.exit("\n".join(errors))
    print(f"{tag} is consistent")


def notes(version: str) -> None:
    section = changelog_section(version)
    if not section:
        sys.exit(f"CHANGELOG.md has no '## [{version}]' section")
    print(section)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("bump").add_argument("version")
    commands.add_parser("check").add_argument("tag")
    commands.add_parser("notes").add_argument("version")
    args = parser.parse_args()
    {"bump": lambda: bump(args.version), "check": lambda: check(args.tag), "notes": lambda: notes(args.version)}[
        args.command]()


if __name__ == "__main__":
    main()
