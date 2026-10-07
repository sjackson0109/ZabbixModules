"""Release packaging must exclude local runtime state and remain reproducible."""
import importlib.util
import io
import tarfile
from pathlib import Path

import pytest


SPEC = importlib.util.spec_from_file_location("ne_package", Path(__file__).resolve().parents[2] / "scripts/package.py")
PACKAGE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PACKAGE)


def test_package_reproducible_and_excludes_runtime_state(tmp_path, monkeypatch):
    source = tmp_path / "frontend"
    source.mkdir()
    (source / "manifest.json").write_text('{"id":"networkexplorer"}')
    (source / ".lab").mkdir()
    (source / ".lab" / "credentials.json").write_text('local runtime material')
    (source / "__pycache__").mkdir()
    (source / "__pycache__" / "cache.pyc").write_bytes(b"generated")
    (source / "build").mkdir()
    (source / "build" / "copied.py").write_text("generated build output")
    (source / "generated.egg-info").mkdir()
    (source / "generated.egg-info" / "PKG-INFO").write_text("generated metadata")
    monkeypatch.setattr(PACKAGE, "ROOT", tmp_path)
    first = PACKAGE.archive(tmp_path / "first.tar", [source])
    second = PACKAGE.archive(tmp_path / "second.tar", [source])
    assert first["sha256"] == second["sha256"]
    with tarfile.open(tmp_path / "first.tar") as tar:
        assert tar.getnames() == ["frontend/manifest.json"]
        assert tar.getmember("frontend/manifest.json").mode == 0o644


def test_package_rejects_secret_file_and_symlink(tmp_path, monkeypatch):
    source = tmp_path / "collector"
    source.mkdir()
    monkeypatch.setattr(PACKAGE, "ROOT", tmp_path)
    (source / ".env").write_text("private local configuration")
    with pytest.raises(ValueError, match="Local configuration"):
        list(PACKAGE.files_under(source))
    (source / ".env").unlink()
    (source / "escape").symlink_to(tmp_path)
    with pytest.raises(ValueError, match="Symlinks"):
        list(PACKAGE.files_under(source))


def test_package_rejects_empty_delivery(tmp_path, monkeypatch):
    source = tmp_path / "empty"
    source.mkdir()
    monkeypatch.setattr(PACKAGE, "ROOT", tmp_path)
    with pytest.raises(ValueError, match="empty archive"):
        PACKAGE.archive(tmp_path / "empty.tar", [source])


def test_external_check_launcher_is_executable_in_delivery(tmp_path, monkeypatch):
    source = tmp_path / "collector"
    source.mkdir()
    (source / "network-explorer-collect").write_text("#!/bin/sh\nexit 0\n")
    monkeypatch.setattr(PACKAGE, "ROOT", tmp_path)
    PACKAGE.archive(tmp_path / "collector.tar", [source])
    with tarfile.open(tmp_path / "collector.tar") as tar:
        assert tar.getmember("collector/network-explorer-collect").mode == 0o755
