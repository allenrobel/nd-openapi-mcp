"""Sanity: every fixture directory is a loadable OpenAPI spec for the existing store."""
from __future__ import annotations

from pathlib import Path

import pytest

from server import OpenAPISchemaStore


@pytest.mark.parametrize("sub", ["1.0.0", "2.0.0", "notaversion"])
def test_versioned_fixture_loads(versioned_dir: Path, sub: str) -> None:
    store = OpenAPISchemaStore(str(versioned_dir / sub))
    store.load()
    assert store.loaded_files, f"{sub} loaded nothing"
    assert "No endpoints found" not in store.query_list_endpoints()


def test_flat_fixture_loads(flat_dir: Path) -> None:
    store = OpenAPISchemaStore(str(flat_dir))
    store.load()
    assert store.loaded_files == ["manage.json"]
