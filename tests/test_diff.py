"""VersionRegistry.diff and the diff_versions tool."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

import server
from server import VersionRegistry


@pytest.fixture
def reg(versioned_dir: Path) -> VersionRegistry:
    r = VersionRegistry(str(versioned_dir), default_version="1.0.0")
    r.load()
    return r


def test_summary_counts(reg: VersionRegistry) -> None:
    out = reg.diff("1.0.0", "2.0.0")
    assert out.splitlines()[0] == "ND 1.0.0 → 2.0.0"
    assert "Endpoints: 1 added, 2 removed, 1 changed" in out
    assert "Schemas: 1 added, 2 removed, 1 changed" in out


def test_endpoint_lines(reg: VersionRegistry) -> None:
    out = reg.diff("1.0.0", "2.0.0")
    assert "    + POST    /api/v1/manage/widgetActions/modify — Update widgets" in out
    assert "    - GET     /api/v1/manage/legacy — Get legacy thing" in out
    assert "    - GET     /api/v1/infra/health — Cluster health" in out
    assert "    ~ POST    /api/v1/manage/widgets — Create widgets" in out
    assert "/api/v1/manage/widgets — List widgets" not in out  # unchanged


def test_endpoint_lines_grouped_by_tag(reg: VersionRegistry) -> None:
    lines = reg.diff("1.0.0", "2.0.0").splitlines()
    widgets = lines.index("  [Widgets]")
    assert lines[widgets + 1].startswith("    + POST")
    assert lines[widgets + 2].startswith("    ~ POST")


def test_schema_lines(reg: VersionRegistry) -> None:
    out = reg.diff("1.0.0", "2.0.0")
    assert "    + NewThing [manage]" in out
    assert "    - LegacyThing [manage]" in out
    assert "    - Shared [infra]" in out
    assert "    ~ Widget [manage]" in out
    assert "Stable" not in out
    assert "Shared [manage]" not in out  # manage's Shared is unchanged


def test_reverse_direction(reg: VersionRegistry) -> None:
    out = reg.diff("2.0.0", "1.0.0")
    assert out.splitlines()[0] == "ND 2.0.0 → 1.0.0"
    assert "Endpoints: 2 added, 1 removed, 1 changed" in out
    assert "    + GET     /api/v1/manage/legacy — Get legacy thing" in out


def test_tag_filter(reg: VersionRegistry) -> None:
    out = reg.diff("1.0.0", "2.0.0", tag="widgets")
    assert "Endpoints: 1 added, 0 removed, 1 changed" in out
    assert "[Legacy]" not in out and "[Infra]" not in out
    assert "Schemas: 1 added, 2 removed, 1 changed" in out  # schema diff is not tag-scoped


def test_same_version(reg: VersionRegistry) -> None:
    assert reg.diff("1.0.0", "1.0.0") == "ND 1.0.0: nothing to compare (same version on both sides)."


def test_same_unknown_version_is_rejected(reg: VersionRegistry) -> None:
    out = reg.diff("9.9.9", "9.9.9")
    assert out.startswith('Unknown version "9.9.9"')


def test_unknown_version(reg: VersionRegistry) -> None:
    out = reg.diff("1.0.0", "3.0.0")
    assert out.startswith('Unknown version "3.0.0". Available: 1.0.0, 2.0.0')


def test_item_cap(reg: VersionRegistry) -> None:
    out = reg.diff("1.0.0", "2.0.0", item_cap=1)
    assert "Endpoints: 1 added, 2 removed, 1 changed" in out  # counts unaffected
    assert "Schemas: 1 added, 2 removed, 1 changed" in out
    assert out.count("    ... 1 more removed") == 2  # once for endpoints, once for schemas
    assert out.count("    - ") == 2  # one capped removed line in each section


def test_diff_versions_tool(versioned_dir: Path) -> None:
    server.build_server(str(versioned_dir), default_version="1.0.0")
    out = server.diff_versions("1.0.0", "2.0.0", tag="Widgets")
    assert out.splitlines()[0] == "ND 1.0.0 → 2.0.0"
    assert "widgetActions/modify" in out


def test_tag_group_case_insensitive(versioned_dir: Path, tmp_path: Path) -> None:
    """Mixed-case tags ('Widgets' vs 'widgets') that sort adjacent must produce exactly one group header."""
    root = tmp_path / "versioned"
    root.mkdir()
    shutil.copytree(versioned_dir / "1.0.0", root / "1.0.0")
    shutil.copytree(versioned_dir / "2.0.0", root / "2.0.0")

    manage_path = root / "2.0.0" / "manage.json"
    spec = json.loads(manage_path.read_text())
    spec["paths"]["/widgetActions/modify"]["post"]["tags"] = ["widgets"]
    manage_path.write_text(json.dumps(spec))

    r = VersionRegistry(str(root), default_version="1.0.0")
    r.load()
    out = r.diff("1.0.0", "2.0.0")
    lines = out.splitlines()

    widgets_headers = [line for line in lines if line.strip().lower() == "[widgets]"]
    assert len(widgets_headers) == 1

    header_index = lines.index(widgets_headers[0])
    group = []
    for line in lines[header_index + 1 :]:
        if line.startswith("  [") or line == "":
            break
        group.append(line)
    assert any(line.startswith("    + POST") and "widgetActions/modify" in line for line in group)
    assert any(line.startswith("    ~ POST") and line.rstrip().endswith("widgets — Create widgets") for line in group)
