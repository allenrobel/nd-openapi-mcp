"""VersionRegistry discovery, ordering, fallback, and resolution."""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from server import UNVERSIONED, VersionRegistry, _version_sort_key


def test_discovers_versioned_subdirs(versioned_dir: Path) -> None:
    reg = VersionRegistry(str(versioned_dir))
    reg.load()
    assert reg.versions == ["1.0.0", "2.0.0"]


def test_skips_non_version_names(versioned_dir: Path, capsys: pytest.CaptureFixture[str]) -> None:
    reg = VersionRegistry(str(versioned_dir))
    reg.load()
    assert "notaversion" not in reg.versions
    assert "Skipping" in capsys.readouterr().err
    assert reg.store_for("notaversion") is None


def test_numeric_ordering() -> None:
    assert sorted(["4.3.1", "4.10.1", "4.2.1"], key=_version_sort_key) == ["4.2.1", "4.3.1", "4.10.1"]


def test_flat_fallback(flat_dir: Path) -> None:
    reg = VersionRegistry(str(flat_dir))
    reg.load()
    assert reg.versions == [UNVERSIONED]
    store = reg.store_for(UNVERSIONED)
    assert store is not None and store.loaded_files == ["manage.json"]


def test_mixed_layout_prefers_versioned(tmp_path: Path, versioned_dir: Path, flat_dir: Path, capsys: pytest.CaptureFixture[str]) -> None:
    shutil.copytree(versioned_dir / "1.0.0", tmp_path / "1.0.0")
    shutil.copy(flat_dir / "manage.json", tmp_path / "manage.json")
    reg = VersionRegistry(str(tmp_path))
    reg.load()
    assert reg.versions == ["1.0.0"]
    assert "Ignoring" in capsys.readouterr().err


def test_missing_dir_records_error(tmp_path: Path) -> None:
    reg = VersionRegistry(str(tmp_path / "nope"))
    reg.load()
    assert reg.versions == []
    assert any("not found" in e for e in reg.registry_errors)


def test_empty_dir_records_error(tmp_path: Path) -> None:
    reg = VersionRegistry(str(tmp_path))
    reg.load()
    assert reg.versions == []
    assert any("No schema files" in e for e in reg.registry_errors)


def test_version_dir_without_specs_is_reported(tmp_path: Path, versioned_dir: Path) -> None:
    shutil.copytree(versioned_dir / "1.0.0", tmp_path / "1.0.0")
    (tmp_path / "9.9.9").mkdir()
    reg = VersionRegistry(str(tmp_path))
    reg.load()
    assert reg.versions == ["1.0.0"]
    assert any("9.9.9" in e for e in reg.registry_errors)
