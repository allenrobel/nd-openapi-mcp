"""Components are scoped per source file: $refs resolve within their own document and same-named schemas coexist."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from server import OpenAPISchemaStore, _fingerprint


@pytest.fixture
def store(versioned_dir: Path) -> OpenAPISchemaStore:
    st = OpenAPISchemaStore(str(versioned_dir / "1.0.0"))
    st.load()
    return st


def test_no_redefinition_warning(versioned_dir: Path, capsys: pytest.CaptureFixture[str]) -> None:
    st = OpenAPISchemaStore(str(versioned_dir / "1.0.0"))
    st.load()
    assert "redefined" not in capsys.readouterr().err


def test_both_definitions_are_kept(store: OpenAPISchemaStore) -> None:
    entries = store.schemas["Shared"]
    assert [(e.api, e.schema_type) for e in entries] == [("infra", "string"), ("manage", "object")]


def test_endpoint_ref_resolves_in_own_file(store: OpenAPISchemaStore) -> None:
    out = json.loads(store.query_get_endpoint("/api/v1/infra/health", "get"))
    schema = out["responses"]["200"]["content"]["application/json"]["schema"]
    assert schema == {"type": "string", "description": "infra flavour"}


def test_resolve_refs_scoped(store: OpenAPISchemaStore) -> None:
    ref = {"$ref": "#/components/schemas/Shared"}
    assert store.resolve_refs(ref, source_file="manage.json")["type"] == "object"
    assert store.resolve_refs(ref, source_file="infra.json")["type"] == "string"
    assert store.resolve_refs(ref)["type"] == "string"  # unscoped: first file in load order (infra.json < manage.json)


def test_resolve_refs_unknown_file_is_unresolved(store: OpenAPISchemaStore) -> None:
    out = store.resolve_refs({"$ref": "#/components/schemas/Shared"}, source_file="nope.json")
    assert out == {"$ref": "#/components/schemas/Shared", "_unresolved": True}


def test_get_schema_unique_name(store: OpenAPISchemaStore) -> None:
    out = json.loads(store.query_get_schema("Widget"))
    assert out["source_file"] == "manage.json" and out["api"] == "manage"


def test_get_schema_ambiguous_name_asks_for_api(store: OpenAPISchemaStore) -> None:
    out = store.query_get_schema("Shared")
    assert out.startswith('Schema "Shared" is defined differently in infra.json and manage.json.')
    assert 'api="infra"' in out and 'api="manage"' in out


def test_get_schema_with_api(store: OpenAPISchemaStore) -> None:
    out = json.loads(store.query_get_schema("Shared", api="manage"))
    assert out["api"] == "manage" and out["schema"]["type"] == "object"
    out = json.loads(store.query_get_schema("shared", api="INFRA"))  # case-insensitive on both
    assert out["schema"]["type"] == "string"


def test_get_schema_wrong_api(store: OpenAPISchemaStore) -> None:
    out = store.query_get_schema("Shared", api="analyze")
    assert out.startswith('Schema "Shared" is not defined in api "analyze". Defined in: infra, manage')


def test_get_schema_identical_duplicates_answer_directly(tmp_path: Path, versioned_dir: Path) -> None:
    import shutil

    shutil.copytree(versioned_dir / "1.0.0", tmp_path / "1.0.0")
    # Make infra's Shared identical to manage's so the name is duplicated but not conflicting.
    infra = json.loads((tmp_path / "1.0.0" / "infra.json").read_text())
    manage = json.loads((tmp_path / "1.0.0" / "manage.json").read_text())
    infra["components"]["schemas"]["Shared"] = manage["components"]["schemas"]["Shared"]
    (tmp_path / "1.0.0" / "infra.json").write_text(json.dumps(infra))
    st = OpenAPISchemaStore(str(tmp_path / "1.0.0"))
    st.load()
    out = json.loads(st.query_get_schema("Shared"))
    assert out["api"] == "infra" and out["also_defined_in"] == ["manage"]


def test_list_schemas_marks_multi_file_names(store: OpenAPISchemaStore) -> None:
    lines = store.query_list_schemas().splitlines()
    shared = next(l for l in lines if l.startswith("Shared"))
    assert shared.endswith("[infra, manage] (definitions differ)")
    widget = next(l for l in lines if l.startswith("Widget"))
    assert "[" not in widget
    assert lines[-1] == "(4 schemas)"  # 4 distinct names (Widget, Stable, LegacyThing, Shared), not 5 entries


def test_fingerprint_helper() -> None:
    assert _fingerprint({"a": 1, "b": 2}) == _fingerprint({"b": 2, "a": 1})
    assert _fingerprint({"a": 1}) != _fingerprint({"a": 2})
