"""Read-only accessors added to OpenAPISchemaStore for the registry and diff."""
from __future__ import annotations

from pathlib import Path

from server import OpenAPISchemaStore


def _load(path: Path) -> OpenAPISchemaStore:
    store = OpenAPISchemaStore(str(path))
    store.load()
    return store


def test_file_versions_per_file(versioned_dir: Path) -> None:
    store = _load(versioned_dir / "1.0.0")
    assert store.file_versions == {"infra.json": "1.0.050", "manage.json": "1.0.100"}


def test_file_titles_per_file(versioned_dir: Path) -> None:
    store = _load(versioned_dir / "1.0.0")
    assert store.file_titles == {"infra.json": "Nexus Dashboard Infra v1", "manage.json": "Nexus Dashboard Manage v1"}


def test_endpoints_accessor(versioned_dir: Path) -> None:
    store = _load(versioned_dir / "2.0.0")
    keys = sorted((ep.method, ep.path) for ep in store.endpoints)
    assert keys == [
        ("GET", "/api/v1/manage/widgets"),
        ("POST", "/api/v1/manage/widgetActions/modify"),
        ("POST", "/api/v1/manage/widgets"),
    ]


def test_schemas_accessor(versioned_dir: Path) -> None:
    store = _load(versioned_dir / "2.0.0")
    assert sorted(store.schemas) == ["NewThing", "Shared", "Stable", "Widget"]
