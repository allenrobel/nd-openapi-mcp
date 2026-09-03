"""Smoke test against the real ND specs shipped in schemas/. Skipped when either release is missing."""
from __future__ import annotations

from pathlib import Path

import pytest

import server

SCHEMAS = Path(__file__).resolve().parent.parent / "schemas"
MODIFY = "/api/v1/manage/fabrics/{fabricName}/interfaceActions/modify"

pytestmark = pytest.mark.skipif(
    not (SCHEMAS / "4.2.1" / "manage.json").is_file() or not (SCHEMAS / "4.3.1" / "manage.json").is_file(),
    reason="requires schemas/4.2.1 and schemas/4.3.1",
)


@pytest.fixture(scope="module")
def real() -> None:
    server.build_server(str(SCHEMAS), default_version="4.2.1")


def test_modify_absent_in_421(real: None) -> None:
    assert MODIFY not in server.list_endpoints(path_contains="interfaceActions", version="4.2.1")


def test_modify_present_in_431(real: None) -> None:
    assert MODIFY in server.list_endpoints(path_contains="interfaceActions", version="4.3.1")


def test_modify_is_added_in_diff(real: None) -> None:
    out = server.diff_versions("4.2.1", "4.3.1", tag="Interfaces")
    assert f"+ POST    {MODIFY}" in out
