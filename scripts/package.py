#!/usr/bin/env python3
"""Build deterministic copy-out artefacts without local data or credentials."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import tarfile
import io

ROOT = Path(__file__).resolve().parents[1]
VERSION = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
EXCLUDED = {"__pycache__", ".pytest_cache", ".venv", ".lab", "node_modules", ".git", "build", "dist"}


def files_under(path: Path):
    if path.is_symlink():
        raise ValueError(f"Symlinks are not distributable: {path.relative_to(ROOT)}")
    if not path.exists():
        raise ValueError(f"Missing package path: {path.relative_to(ROOT)}")
    candidates = [path] if path.is_file() else sorted(path.rglob("*"))
    for file in candidates:
        if file.is_symlink():
            raise ValueError(f"Symlinks are not distributable: {file.relative_to(ROOT)}")
        if file.is_file() and not EXCLUDED.intersection(file.parts) and not any(
                part.endswith(".egg-info") for part in file.parts) and file.suffix not in {".pyc", ".pyo"}:
            if file.name == ".env" or file.name.endswith(".secret"):
                raise ValueError(f"Local configuration cannot be packaged: {file.relative_to(ROOT)}")
            yield file


def archive(output: Path, paths: list[Path]) -> dict:
    entries = [file for path in paths for file in files_under(path)]
    if not entries:
        raise ValueError("Refusing to create an empty archive")
    # Uncompressed tar keeps timestamps deterministic and supports manual-copy installation.
    with tarfile.open(output, "w", format=tarfile.PAX_FORMAT) as tar:
        for file in sorted(entries):
            data = file.read_bytes()
            info = tarfile.TarInfo(str(file.relative_to(ROOT)))
            info.size = len(data)
            info.mode = 0o755 if file.suffix == ".sh" or file.name == "network-explorer-collect" else 0o644
            info.mtime = 0
            info.uid = info.gid = 0
            info.uname = info.gname = ""
            tar.addfile(info, io.BytesIO(data))
    return {"file": output.name, "sha256": hashlib.sha256(output.read_bytes()).hexdigest(), "files": len(entries)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "dist")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    packages = {
        "frontend": [ROOT / "frontend"],
        "collector": [ROOT / "collector", ROOT / "schemas"],
        "templates": [ROOT / "templates/native", ROOT / "schemas", ROOT / "dashboards"],
        "template-specifications": [ROOT / "templates/specifications", ROOT / "templates/contract.json",
            ROOT / "templates/profiles", ROOT / "schemas", ROOT / "dashboards"],
    }
    records = [archive(args.output / f"network-explorer-{name}-{VERSION}.tar", paths) for name, paths in packages.items()]
    manifest = {"version": VERSION, "stage": "pre-release" if "-" in VERSION else "release", "packages": records,
                "note": "The standard-MIB templates are generic; vendor/model qualification is separate. "
                        "Lab replay templates are test-only and are not packaged."}
    (args.output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    (args.output / "SHA256SUMS").write_text("".join(f"{r['sha256']}  {r['file']}\n" for r in records))
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
