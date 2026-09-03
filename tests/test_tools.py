"""Tool functions: version passthrough, header line, and error paths."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import server


@pytest.fixture
def built(versioned_dir: Path):
    """Build the server against the versioned fixtures with 1.0.0 as default."""
    server.build_server(str(versioned_dir), default_version="1.0.0")
    return server


def test_header_line_on_default(built) -> None:
    out = built.list_endpoints()
    assert out.splitlines()[0] == "ND 1.0.0"


def test_header_line_on_explicit(built) -> None:
    out = built.list_endpoints(version="2.0.0")
    assert out.splitlines()[0] == "ND 2.0.0"


def test_list_endpoints_is_version_scoped(built) -> None:
    assert "widgetActions/modify" not in built.list_endpoints()
    assert "widgetActions/modify" in built.list_endpoints(version="2.0.0")


def test_unknown_version_error(built) -> None:
    out = built.list_endpoints(version="9.9.9")
    assert out.startswith('Unknown version "9.9.9". Available: 1.0.0, 2.0.0')


def test_get_endpoint_json_after_header(built) -> None:
    out = built.get_endpoint("/api/v1/manage/widgets", "post", version="2.0.0")
    header, body = out.split("\n", 1)
    assert header == "ND 2.0.0"
    assert "207" in json.loads(body)["responses"]


def test_search_endpoints_version(built) -> None:
    assert "No endpoints found" in built.search_endpoints("modify")
    assert "widgetActions/modify" in built.search_endpoints("modify", version="2.0.0")


def test_list_schemas_version(built) -> None:
    assert "LegacyThing" in built.list_schemas()
    assert "LegacyThing" not in built.list_schemas(version="2.0.0")


def test_get_schema_version(built) -> None:
    out = built.get_schema("Widget", version="2.0.0")
    body = json.loads(out.split("\n", 1)[1])
    assert "color" in body["schema"]["properties"]


def test_get_schema_api_passthrough(built) -> None:
    out = built.get_schema("Shared", api="infra")  # default version 1.0.0 has both flavours
    body = json.loads(out.split("\n", 1)[1])
    assert body["api"] == "infra" and body["schema"]["type"] == "string"


def test_list_tags_version(built) -> None:
    assert "Legacy" in built.list_tags()
    assert "Legacy" not in built.list_tags(version="2.0.0")


def test_get_api_info_has_header(built) -> None:
    assert built.get_api_info(version="2.0.0").splitlines()[0] == "ND 2.0.0"


def test_nothing_loaded_message(tmp_path: Path) -> None:
    server.build_server(str(tmp_path))
    assert "No OpenAPI schemas loaded" in server.list_endpoints()
    assert "No OpenAPI schemas loaded" in server.get_api_info()


def test_build_server_returns_fastmcp(versioned_dir: Path) -> None:
    mcp = server.build_server(str(versioned_dir))
    assert mcp.name == "nd-openapi"


def test_list_versions_rows(built) -> None:
    out = built.list_versions()
    lines = out.splitlines()
    assert lines[0] == "Loaded versions: 2 (default: 1.0.0)"
    assert any(l.startswith("* 1.0.0") and "manage.json=1.0.100" in l and "infra.json=1.0.050" in l for l in lines)
    assert any(l.startswith("  2.0.0") and "manage.json=1.2.200" in l and "3 endpoints" in l and "4 schema names" in l for l in lines)


def test_list_versions_reports_bad_default(versioned_dir: Path) -> None:
    server.build_server(str(versioned_dir), default_version="7.7.7")
    out = server.list_versions()
    assert "default: 2.0.0" in out
    assert "7.7.7" in out and "falling back" in out


def test_list_versions_nothing_loaded(tmp_path: Path) -> None:
    server.build_server(str(tmp_path))
    out = server.list_versions()
    assert out.startswith("Loaded versions: 0")
    assert "No schema files" in out
