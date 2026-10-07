"""Every shipped component carries the release version from the root VERSION file."""
import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
VERSION = (ROOT / "VERSION").read_text(encoding="utf-8").strip()


def test_version_is_semantic():
    assert re.fullmatch(r"\d+\.\d+\.\d+(?:-[0-9A-Za-z.]+)?", VERSION)


@pytest.mark.parametrize("manifest", sorted(ROOT.glob("frontend/*/manifest.json")), ids=lambda path: path.parent.name)
def test_frontend_manifests_match(manifest):
    assert json.loads(manifest.read_text(encoding="utf-8"))["version"] == VERSION


def test_collector_matches():
    # tomllib needs Python 3.11; the project line is simple enough to match directly.
    project = (ROOT / "collector/pyproject.toml").read_text(encoding="utf-8")
    init = (ROOT / "collector/network_explorer/__init__.py").read_text(encoding="utf-8")
    assert re.search(r'^version = "([^"]+)"$', project, re.M).group(1) == VERSION
    assert re.search(r'^__version__ = "([^"]+)"$', init, re.M).group(1) == VERSION
