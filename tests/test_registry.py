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


def test_default_is_highest_when_unset(versioned_dir: Path) -> None:
    reg = VersionRegistry(str(versioned_dir))
    reg.load()
    assert reg.default_version == "2.0.0"


def test_default_from_argument(versioned_dir: Path) -> None:
    reg = VersionRegistry(str(versioned_dir), default_version="1.0.0")
    reg.load()
    assert reg.default_version == "1.0.0"


def test_unknown_default_falls_back_and_reports(versioned_dir: Path) -> None:
    reg = VersionRegistry(str(versioned_dir), default_version="7.7.7")
    reg.load()
    assert reg.default_version == "2.0.0"
    assert any("7.7.7" in e and "falling back to 2.0.0" in e for e in reg.registry_errors)


def test_resolve_none_uses_default(versioned_dir: Path) -> None:
    reg = VersionRegistry(str(versioned_dir), default_version="1.0.0")
    reg.load()
    store, key = reg.resolve(None)
    assert key == "1.0.0"
    assert store is reg.store_for("1.0.0")


def test_resolve_empty_string_uses_default(versioned_dir: Path) -> None:
    reg = VersionRegistry(str(versioned_dir), default_version="1.0.0")
    reg.load()
    store, key = reg.resolve("")
    assert key == "1.0.0"
    assert store is reg.store_for("1.0.0")
    store, key = reg.resolve("  ")
    assert key == "1.0.0"
    assert store is reg.store_for("1.0.0")


def test_resolve_explicit(versioned_dir: Path) -> None:
    reg = VersionRegistry(str(versioned_dir), default_version="1.0.0")
    reg.load()
    store, key = reg.resolve("2.0.0")
    assert key == "2.0.0" and store is reg.store_for("2.0.0")


def test_resolve_unknown(versioned_dir: Path) -> None:
    reg = VersionRegistry(str(versioned_dir), default_version="1.0.0")
    reg.load()
    store, msg = reg.resolve("4.9.9")
    assert store is None
    assert msg == 'Unknown version "4.9.9". Available: 1.0.0, 2.0.0 (default: 1.0.0)'


def test_resolve_with_nothing_loaded(tmp_path: Path) -> None:
    reg = VersionRegistry(str(tmp_path))
    reg.load()
    store, msg = reg.resolve(None)
    assert store is None
    assert "No OpenAPI schemas loaded" in msg and str(tmp_path) in msg


def test_load_errors_groups_by_version(tmp_path: Path, versioned_dir: Path) -> None:
    shutil.copytree(versioned_dir / "1.0.0", tmp_path / "1.0.0")
    (tmp_path / "1.0.0" / "broken.json").write_text("{not json", encoding="utf-8")
    reg = VersionRegistry(str(tmp_path), default_version="0.0.1")
    reg.load()
    errors = reg.load_errors()
    assert any("broken.json" in e for e in errors["1.0.0"])
    assert any("0.0.1" in e for e in errors["__registry__"])
