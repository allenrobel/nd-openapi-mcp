# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "fastmcp>=2.0",
#     "pyyaml>=6.0",
# ]
# ///
"""
# ND OpenAPI Schema MCP Server

Provides efficient, low-token-usage access to Cisco Nexus Dashboard OpenAPI specifications for one or more releases.
Loads schema files from a configurable directory and exposes tools to browse, search, and inspect endpoints and schemas.

## Usage

    ND_SCHEMA_DIR=.claude/schemas uv run server.py

## Environment Variables

- `ND_SCHEMA_DIR` - Directory containing OpenAPI JSON/YAML files
  (default: `.claude/schemas` relative to cwd)
- `ND_DEFAULT_VERSION` - Release used when a tool call omits `version` (default: highest loaded)
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import yaml
from fastmcp import FastMCP


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class EndpointInfo:
    """Compact representation of a single API endpoint operation."""

    path: str
    method: str
    operation_id: str | None
    summary: str | None
    description: str | None
    tags: list[str]
    parameters: list[dict[str, Any]]
    request_body: dict[str, Any] | None
    responses: dict[str, Any]
    source_file: str

    def one_line(self) -> str:
        """Return a compact single-line representation."""
        tag_str = ",".join(self.tags) if self.tags else "-"
        summary_str = self.summary or ""
        if len(summary_str) > 80:
            summary_str = summary_str[:77] + "..."
        return f"{self.method:<7} {self.path:<65} [{tag_str}] {summary_str}"


@dataclass
class SchemaInfo:
    """Compact representation of a component schema."""

    name: str
    schema_type: str | None
    description: str | None
    properties: list[str]
    required: list[str]
    enum_values: list[str]
    full_schema: dict[str, Any]
    source_file: str

    def one_line(self) -> str:
        """Return a compact single-line representation."""
        type_str = self.schema_type or "unknown"
        if self.enum_values:
            vals = ", ".join(str(v) for v in self.enum_values[:5])
            if len(self.enum_values) > 5:
                vals += ", ..."
            return f"{self.name:<45} {type_str:<10} enum: [{vals}]"
        if self.properties:
            props = ", ".join(self.properties[:5])
            if len(self.properties) > 5:
                props += ", ..."
            return f"{self.name:<45} {type_str:<10} ({len(self.properties)} props: {props})"
        return f"{self.name:<45} {type_str:<10}"

    @property
    def api(self) -> str:
        """Short API name derived from the source file stem, e.g. `manage.json` -> `manage`."""
        return Path(self.source_file).stem


def _fingerprint(obj: Any) -> str:
    """
    # Summary

    SHA-256 of the canonical JSON form of `obj` (sorted keys), so two structurally equal objects hash the same.

    ## Raises

    None
    """
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str).encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Schema store
# ---------------------------------------------------------------------------

HTTP_METHODS = {"get", "post", "put", "delete", "patch", "head", "options", "trace"}


class OpenAPISchemaStore:
    """
    # Summary

    Load, merge, and index OpenAPI 3.x schema files for efficient querying.

    ## Raises

    None (errors are logged to stderr and stored for reporting)
    """

    def __init__(self, schema_dir: str) -> None:
        self._schema_dir = schema_dir
        self._endpoints: list[EndpointInfo] = []
        self._endpoints_by_path: dict[str, dict[str, EndpointInfo]] = {}
        self._schemas: dict[str, list[SchemaInfo]] = {}
        self._tags: dict[str, str] = {}
        self._api_info: dict[str, Any] = {}
        self._components_by_file: dict[str, dict[str, dict[str, Any]]] = {}
        self.loaded_files: list[str] = []
        self._file_stats: dict[str, dict[str, int]] = {}
        self._file_info: dict[str, dict[str, str]] = {}
        self._load_errors: list[str] = []

    def load(self) -> None:
        """
        # Summary

        Load all OpenAPI schema files from the schema directory.

        ## Raises

        None (errors logged to stderr)
        """
        schema_path = Path(self._schema_dir)
        if not schema_path.is_dir():
            msg = f"Schema directory not found: {self._schema_dir}"
            print(msg, file=sys.stderr)
            self._load_errors.append(msg)
            return

        files = sorted(
            f
            for f in schema_path.iterdir()
            if f.suffix.lower() in {".json", ".yaml", ".yml"} and f.is_file()
        )

        if not files:
            msg = f"No schema files found in {self._schema_dir}"
            print(msg, file=sys.stderr)
            self._load_errors.append(msg)
            return

        for filepath in files:
            try:
                self._load_file(filepath)
            except Exception as exc:
                msg = f"Error loading {filepath.name}: {exc}"
                print(msg, file=sys.stderr)
                self._load_errors.append(msg)

        print(
            f"Loaded {len(self.loaded_files)} file(s): "
            f"{len(self._endpoints)} endpoints, "
            f"{len(self._schemas)} schemas",
            file=sys.stderr,
        )

    def _load_file(self, filepath: Path) -> None:
        """
        # Summary

        Parse a single OpenAPI file and merge it into the store.

        ## Raises

        - `yaml.YAMLError` if the file is invalid YAML/JSON
        - `ValueError` if the file does not appear to be an OpenAPI spec
        """
        content = filepath.read_text(encoding="utf-8")

        if filepath.suffix.lower() == ".json":
            spec = json.loads(content)
        else:
            spec = yaml.safe_load(content)

        if not isinstance(spec, dict):
            raise ValueError(f"Expected a dict, got {type(spec).__name__}")

        if "openapi" not in spec and "swagger" not in spec:
            raise ValueError("File does not appear to be an OpenAPI spec (missing 'openapi' or 'swagger' key)")

        filename = filepath.name
        endpoint_count = 0
        schema_count = 0

        # Merge API info (first file wins for title/version)
        if not self._api_info and "info" in spec:
            self._api_info = dict(spec["info"])
        if "servers" in spec and "servers" not in self._api_info:
            self._api_info["servers"] = spec["servers"]

        # Merge tags
        for tag in spec.get("tags", []):
            tag_name = tag.get("name", "")
            if tag_name and tag_name not in self._tags:
                self._tags[tag_name] = tag.get("description", "")

        # Components are document-local (OpenAPI `#/...` refs never cross files), so keep them per file.
        components = spec.get("components", {})
        file_components: dict[str, dict[str, Any]] = {}
        for comp_type, comp_items in components.items():
            if not isinstance(comp_items, dict):
                continue
            file_components[comp_type] = dict(comp_items)
            if comp_type == "schemas":
                for name, definition in comp_items.items():
                    schema_count += 1
                    self._schemas.setdefault(name, []).append(
                        SchemaInfo(
                            name=name,
                            schema_type=definition.get("type") if isinstance(definition, dict) else None,
                            description=definition.get("description") if isinstance(definition, dict) else None,
                            properties=list(definition.get("properties", {}).keys()) if isinstance(definition, dict) else [],
                            required=definition.get("required", []) if isinstance(definition, dict) else [],
                            enum_values=definition.get("enum", []) if isinstance(definition, dict) else [],
                            full_schema=definition,
                            source_file=filename,
                        )
                    )
        self._components_by_file[filename] = file_components

        # Extract base path from servers[0].url (e.g. "https://{cluster}/api/v1/manage" -> "/api/v1/manage")
        base_path = ""
        servers = spec.get("servers", [])
        if servers and isinstance(servers, list):
            server_url = servers[0].get("url", "") if isinstance(servers[0], dict) else ""
            if server_url:
                parsed_path = urlparse(server_url).path
                # Strip trailing slash to avoid double slashes
                base_path = parsed_path.rstrip("/")

        # Merge paths
        shared_params = []
        for path_str, path_item in spec.get("paths", {}).items():
            if not isinstance(path_item, dict):
                continue

            # Path-level parameters apply to all operations
            shared_params = path_item.get("parameters", [])

            for method in HTTP_METHODS:
                if method not in path_item:
                    continue

                operation = path_item[method]
                if not isinstance(operation, dict):
                    continue

                # Merge path-level and operation-level parameters
                op_params = list(shared_params) + operation.get("parameters", [])

                full_path = base_path + path_str

                ep = EndpointInfo(
                    path=full_path,
                    method=method.upper(),
                    operation_id=operation.get("operationId"),
                    summary=operation.get("summary"),
                    description=operation.get("description"),
                    tags=operation.get("tags", []),
                    parameters=op_params,
                    request_body=operation.get("requestBody"),
                    responses=operation.get("responses", {}),
                    source_file=filename,
                )

                self._endpoints.append(ep)

                if full_path not in self._endpoints_by_path:
                    self._endpoints_by_path[full_path] = {}

                if method.upper() in self._endpoints_by_path[full_path]:
                    print(
                        f"Warning: {method.upper()} {full_path} redefined in "
                        f"{filename} (overwriting previous definition)",
                        file=sys.stderr,
                    )

                self._endpoints_by_path[full_path][method.upper()] = ep
                endpoint_count += 1

                # Collect tags discovered in operations
                for tag in operation.get("tags", []):
                    if tag not in self._tags:
                        self._tags[tag] = ""

        self.loaded_files.append(filename)
        self._file_stats[filename] = {
            "endpoints": endpoint_count,
            "schemas": schema_count,
        }

        info = spec.get("info", {}) if isinstance(spec.get("info"), dict) else {}
        self._file_info[filename] = {
            "title": str(info.get("title", "Unknown API")),
            "version": str(info.get("version", "unknown")),
        }

    # ------------------------------------------------------------------
    # Read-only accessors (used by VersionRegistry and diff)
    # ------------------------------------------------------------------

    @property
    def file_versions(self) -> dict[str, str]:
        """
        # Summary

        Map each loaded filename to that file's own `info.version` string.

        ## Raises

        None
        """
        return {name: meta["version"] for name, meta in self._file_info.items()}

    @property
    def file_titles(self) -> dict[str, str]:
        """
        # Summary

        Map each loaded filename to that file's `info.title` string.

        ## Raises

        None
        """
        return {name: meta["title"] for name, meta in self._file_info.items()}

    @property
    def endpoints(self) -> list[EndpointInfo]:
        """
        # Summary

        All loaded endpoint operations, in load order.

        ## Raises

        None
        """
        return self._endpoints

    @property
    def schemas(self) -> dict[str, list[SchemaInfo]]:
        """
        # Summary

        All loaded component schemas keyed by name; one entry per file that defines the name, in load order.

        ## Raises

        None
        """
        return self._schemas

    # ------------------------------------------------------------------
    # $ref resolution
    # ------------------------------------------------------------------

    def resolve_refs(
        self,
        obj: Any,
        max_depth: int = 3,
        _current_depth: int = 0,
        _seen: frozenset[str] | None = None,
        source_file: str | None = None,
    ) -> Any:
        """
        # Summary

        Recursively resolve `$ref` pointers in an OpenAPI object.

        Replaces `{"$ref": "#/components/schemas/Foo"}` with the actual
        definition, up to `max_depth` levels deep. Detects cycles and
        marks them with `_circular: true`. Refs are resolved in the scope of `source_file`; when it is None the
        first loaded file defining the name wins.

        ## Raises

        None
        """
        if _seen is None:
            _seen = frozenset()

        if isinstance(obj, dict):
            if "$ref" in obj and len(obj) == 1:
                ref_str = obj["$ref"]

                if not ref_str.startswith("#/"):
                    return obj

                if ref_str in _seen:
                    return {"$ref": ref_str, "_circular": True}

                if _current_depth >= max_depth:
                    return {"$ref": ref_str, "_truncated": True}

                resolved = self._lookup_ref(ref_str, source_file)
                if resolved is None:
                    return {"$ref": ref_str, "_unresolved": True}

                new_seen = _seen | frozenset([ref_str])
                return self.resolve_refs(
                    deepcopy(resolved),
                    max_depth=max_depth,
                    _current_depth=_current_depth + 1,
                    _seen=new_seen,
                    source_file=source_file,
                )

            return {
                k: self.resolve_refs(v, max_depth, _current_depth, _seen, source_file=source_file)
                for k, v in obj.items()
            }

        if isinstance(obj, list):
            return [
                self.resolve_refs(item, max_depth, _current_depth, _seen, source_file=source_file)
                for item in obj
            ]

        return obj

    def _lookup_ref(self, ref_str: str, source_file: str | None = None) -> dict[str, Any] | None:
        """
        # Summary

        Resolve a JSON Pointer like `#/components/schemas/User` inside one file's components. With `source_file` None, search files in
        load order and return the first hit.

        ## Raises

        None (returns None if not found)
        """
        parts = ref_str.lstrip("#/").split("/")
        if len(parts) < 2 or parts[0] != "components":
            return None

        files = [source_file] if source_file is not None else list(self.loaded_files)
        for fname in files:
            current: Any = self._components_by_file.get(fname)
            if current is None:
                continue
            for part in parts[1:]:
                if isinstance(current, dict) and part in current:
                    current = current[part]
                else:
                    current = None
                    break
            if isinstance(current, dict):
                return current
        return None

    # ------------------------------------------------------------------
    # Query methods
    # ------------------------------------------------------------------

    def query_list_endpoints(
        self,
        tag: str | None = None,
        path_contains: str | None = None,
        method: str | None = None,
    ) -> str:
        """
        # Summary

        List endpoints with optional filters, returning compact text.

        ## Raises

        None
        """
        results = self._endpoints

        if tag:
            tag_lower = tag.lower()
            results = [ep for ep in results if any(t.lower() == tag_lower for t in ep.tags)]

        if path_contains:
            pc_lower = path_contains.lower()
            results = [ep for ep in results if pc_lower in ep.path.lower()]

        if method:
            method_upper = method.upper()
            results = [ep for ep in results if ep.method == method_upper]

        if not results:
            return "No endpoints found matching the given filters."

        lines = [ep.one_line() for ep in sorted(results, key=lambda e: (e.path, e.method))]
        lines.append(f"\n({len(results)} endpoint{'s' if len(results) != 1 else ''})")
        return "\n".join(lines)

    def query_get_endpoint(self, path: str, method: str, ref_depth: int = 3) -> str:
        """
        # Summary

        Get full details of a specific endpoint with $refs resolved.

        ## Raises

        None
        """
        method_upper = method.upper()
        path_methods = self._endpoints_by_path.get(path)

        if not path_methods or method_upper not in path_methods:
            # Try case-insensitive path match
            for stored_path, methods in self._endpoints_by_path.items():
                if stored_path.lower() == path.lower() and method_upper in methods:
                    path_methods = methods
                    break

        if not path_methods or method_upper not in path_methods:
            return (
                f"Endpoint not found: {method_upper} {path}\n"
                f"Use list_endpoints or search_endpoints to find available paths."
            )

        ep = path_methods[method_upper]

        result = {
            "path": ep.path,
            "method": ep.method,
            "operation_id": ep.operation_id,
            "summary": ep.summary,
            "description": ep.description,
            "tags": ep.tags,
            "parameters": self.resolve_refs(ep.parameters, max_depth=ref_depth, source_file=ep.source_file),
            "request_body": self.resolve_refs(ep.request_body, max_depth=ref_depth, source_file=ep.source_file) if ep.request_body else None,
            "responses": self.resolve_refs(ep.responses, max_depth=ref_depth, source_file=ep.source_file),
            "source_file": ep.source_file,
        }

        return json.dumps(result, indent=2, default=str)

    def query_search_endpoints(self, query: str, max_results: int = 20) -> str:
        """
        # Summary

        Search endpoints by keyword across paths, summaries, descriptions,
        operation IDs, and parameter names.

        ## Raises

        None
        """
        q = query.lower()
        matches: list[EndpointInfo] = []

        for ep in self._endpoints:
            searchable = " ".join(
                filter(
                    None,
                    [
                        ep.path,
                        ep.summary,
                        ep.description,
                        ep.operation_id,
                    ]
                    + [p.get("name", "") for p in ep.parameters],
                )
            ).lower()

            if q in searchable:
                matches.append(ep)

        if not matches:
            return f'No endpoints found matching "{query}".'

        matches.sort(key=lambda e: (e.path, e.method))
        total = len(matches)
        truncated = matches[:max_results]

        lines = [f'Search: "{query}" (showing {len(truncated)} of {total} match{"es" if total != 1 else ""})\n']
        lines.extend(ep.one_line() for ep in truncated)

        if total > max_results:
            lines.append(f"\n... {total - max_results} more results not shown. Narrow your search or increase max_results.")

        return "\n".join(lines)

    def query_list_schemas(self, name_filter: str | None = None) -> str:
        """
        # Summary

        List component schema names with type and property preview. Names defined in more than one file are suffixed with the
        defining APIs, plus `(definitions differ)` when the definitions are not identical.

        ## Raises

        None
        """
        names = sorted(self._schemas, key=str.lower)
        if name_filter:
            nf_lower = name_filter.lower()
            names = [n for n in names if nf_lower in n.lower()]
        if not names:
            return "No schemas found matching the given filter."

        lines = []
        for name in names:
            entries = self._schemas[name]
            line = entries[0].one_line()
            if len(entries) > 1:
                apis = ", ".join(e.api for e in entries)
                differ = len({_fingerprint(e.full_schema) for e in entries}) > 1
                line += f" [{apis}]" + (" (definitions differ)" if differ else "")
            lines.append(line)
        lines.append(f"\n({len(names)} schema{'s' if len(names) != 1 else ''})")
        return "\n".join(lines)

    def query_get_schema(self, name: str, ref_depth: int = 3, api: str | None = None) -> str:
        """
        # Summary

        Get one schema definition with `$refs` resolved in its own file's scope. `api` (file stem such as `manage`) picks the definition
        when the same name exists in several files; it is required only when those definitions differ.

        ## Raises

        None
        """
        entries = self._schemas.get(name)
        if not entries:
            for schema_name, candidates in self._schemas.items():
                if schema_name.lower() == name.lower():
                    entries = candidates
                    break
        if not entries:
            return f'Schema "{name}" not found.\nUse list_schemas to see available schema names.'

        canonical = entries[0].name
        if api is not None:
            chosen = [e for e in entries if e.api.lower() == api.lower()]
            if not chosen:
                return f'Schema "{canonical}" is not defined in api "{api}". Defined in: {", ".join(e.api for e in entries)}'
            entries = chosen

        if len(entries) > 1 and len({_fingerprint(e.full_schema) for e in entries}) > 1:
            files = " and ".join(e.source_file for e in entries)
            choices = " or ".join(f'api="{e.api}"' for e in entries)
            return f'Schema "{canonical}" is defined differently in {files}. Call get_schema again with {choices}.'

        info = entries[0]
        result: dict[str, Any] = {
            "name": info.name,
            "source_file": info.source_file,
            "api": info.api,
            "schema": self.resolve_refs(info.full_schema, max_depth=ref_depth, source_file=info.source_file),
        }
        if len(entries) > 1:
            result["also_defined_in"] = [e.api for e in entries[1:]]
        return json.dumps(result, indent=2, default=str)

    def query_list_tags(self) -> str:
        """
        # Summary

        List all API tags with descriptions.

        ## Raises

        None
        """
        if not self._tags:
            return "No tags found in loaded schemas."

        lines = []
        for tag_name in sorted(self._tags.keys(), key=str.lower):
            desc = self._tags[tag_name]
            if desc:
                lines.append(f"{tag_name:<35} {desc}")
            else:
                lines.append(tag_name)

        lines.append(f"\n({len(self._tags)} tag{'s' if len(self._tags) != 1 else ''})")
        return "\n".join(lines)

    def query_get_api_info(self) -> str:
        """
        # Summary

        Return API metadata, loaded files, and counts.

        ## Raises

        None
        """
        lines = []

        title = self._api_info.get("title", "Unknown API")
        version = self._api_info.get("version", "unknown")
        lines.append(f"API: {title} v{version}")

        if "servers" in self._api_info:
            servers = self._api_info["servers"]
            if isinstance(servers, list):
                urls = [s.get("url", "") for s in servers if isinstance(s, dict)]
                if urls:
                    lines.append(f"Servers: {', '.join(urls)}")

        desc = self._api_info.get("description")
        if desc:
            short_desc = desc[:200] + "..." if len(desc) > 200 else desc
            lines.append(f"Description: {short_desc}")

        lines.append("")

        if self.loaded_files:
            lines.append(f"Loaded files: {len(self.loaded_files)}")
            for fname in self.loaded_files:
                stats = self._file_stats.get(fname, {})
                ep_count = stats.get("endpoints", 0)
                sc_count = stats.get("schemas", 0)
                lines.append(f"  {fname} ({ep_count} endpoints, {sc_count} schemas)")
        else:
            lines.append("No files loaded.")

        if self._load_errors:
            lines.append("")
            lines.append("Load errors:")
            for err in self._load_errors:
                lines.append(f"  - {err}")

        lines.append("")
        lines.append(f"Total: {len(self._endpoints)} endpoints, {len(self._schemas)} schemas")
        lines.append(f"Tags: {len(self._tags)}")

        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Version registry
# ---------------------------------------------------------------------------

VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")
UNVERSIONED = "unversioned"
SPEC_SUFFIXES = {".json", ".yaml", ".yml"}


def _version_sort_key(version: str) -> tuple[int, ...]:
    """
    # Summary

    Sort key for ND release strings: numeric on each dotted component, so `4.10.1` sorts after `4.3.1`. Non-matching names sort first.

    ## Raises

    None
    """
    if VERSION_RE.match(version):
        return tuple(int(part) for part in version.split("."))
    return (-1,)


def _warn(message: str) -> None:
    """Print a warning to stderr (the MCP stdio transport owns stdout)."""
    print(f"Warning: {message}", file=sys.stderr)


class VersionRegistry:
    """
    # Summary

    Discover `<schema_dir>/<X.Y.Z>/` directories and own one `OpenAPISchemaStore` per version. Falls back to loading spec files
    directly under `schema_dir` as the single version `unversioned` when no version directories exist.

    ## Raises

    None (problems are recorded in `registry_errors` and printed to stderr)
    """

    def __init__(self, schema_dir: str, default_version: str | None = None) -> None:
        self._schema_dir = schema_dir
        self._requested_default = default_version
        self._stores: dict[str, OpenAPISchemaStore] = {}
        self._registry_errors: list[str] = []
        self._default: str | None = None

    def load(self) -> None:
        """
        # Summary

        Scan the schema directory, build a store per version directory (or one `unversioned` store for a flat layout), and pick the default.

        ## Raises

        None
        """
        root = Path(self._schema_dir)
        if not root.is_dir():
            self._record(f"Schema directory not found: {self._schema_dir}")
            return

        entries = sorted(root.iterdir(), key=lambda p: p.name)
        subdirs = [p for p in entries if p.is_dir()]
        flat_files = [p for p in entries if p.is_file() and p.suffix.lower() in SPEC_SUFFIXES]
        versioned = [p for p in subdirs if VERSION_RE.match(p.name)]

        for sub in subdirs:
            if sub not in versioned:
                _warn(f"Skipping {sub}: directory name is not an X.Y.Z release")

        if versioned:
            if flat_files:
                _warn(f"Ignoring {len(flat_files)} spec file(s) directly under {self._schema_dir}; versioned subdirectories take precedence")
            for sub in versioned:
                store = OpenAPISchemaStore(str(sub))
                store.load()
                if store.loaded_files:
                    self._stores[sub.name] = store
                else:
                    self._record(f"{sub.name}: no schema files loaded from {sub}")
        elif flat_files:
            store = OpenAPISchemaStore(str(root))
            store.load()
            if store.loaded_files:
                self._stores[UNVERSIONED] = store
            else:
                self._record(f"No schema files loaded from {self._schema_dir}")
        else:
            self._record(f"No schema files or X.Y.Z version directories found in {self._schema_dir}")

        self._default = self._pick_default()

    def _record(self, message: str) -> None:
        """Log and remember a registry-level problem."""
        print(message, file=sys.stderr)
        self._registry_errors.append(message)

    def _pick_default(self) -> str | None:
        """Return the requested default if loaded, else the highest loaded version, else None."""
        if not self._stores:
            return None
        highest = self.versions[-1]
        if self._requested_default is None:
            return highest
        if self._requested_default in self._stores:
            return self._requested_default
        self._record(f'ND_DEFAULT_VERSION="{self._requested_default}" is not loaded; falling back to {highest}')
        return highest

    @property
    def versions(self) -> list[str]:
        """
        # Summary

        Loaded version names in ascending release order.

        ## Raises

        None
        """
        return sorted(self._stores, key=_version_sort_key)

    @property
    def registry_errors(self) -> list[str]:
        """
        # Summary

        Layout-level problems found during `load()` (missing directory, empty version directory, bad default).

        ## Raises

        None
        """
        return list(self._registry_errors)

    @property
    def default_version(self) -> str | None:
        """
        # Summary

        Version used when a tool call omits `version`; None when nothing is loaded.

        ## Raises

        None
        """
        return self._default

    def resolve(self, version: str | None) -> tuple[OpenAPISchemaStore | None, str]:
        """
        # Summary

        Map an optional version name to a store. Returns `(store, version_key)` on success, or `(None, error_message)` when nothing is
        loaded or the name is unknown.

        ## Raises

        None
        """
        if not self._stores or self._default is None:
            return None, f"No OpenAPI schemas loaded. Place X.Y.Z version directories (or spec files) in: {self._schema_dir}"
        key = version if version is not None else self._default
        store = self._stores.get(key)
        if store is None:
            return None, f'Unknown version "{version}". Available: {", ".join(self.versions)} (default: {self._default})'
        return store, key

    def load_errors(self) -> dict[str, list[str]]:
        """
        # Summary

        Problems recorded during load, keyed by version name plus `__registry__` for layout-level problems. Only non-empty lists are included.

        ## Raises

        None
        """
        errors: dict[str, list[str]] = {}
        if self._registry_errors:
            errors["__registry__"] = list(self._registry_errors)
        for name, store in self._stores.items():
            if store._load_errors:  # pylint: disable=protected-access
                errors[name] = list(store._load_errors)  # pylint: disable=protected-access
        return errors

    def store_for(self, version: str) -> OpenAPISchemaStore | None:
        """
        # Summary

        Return the store for an exact version name, or None.

        ## Raises

        None
        """
        return self._stores.get(version)


# ---------------------------------------------------------------------------
# MCP server
# ---------------------------------------------------------------------------

INSTRUCTIONS = (
    "ND OpenAPI schema reference for Cisco Nexus Dashboard. Several ND releases may be loaded; every tool accepts an optional "
    "`version` (e.g. '4.2.1') and answers from the configured default when it is omitted. Every result starts with a line "
    "'ND <version>' naming the release that answered. Call list_versions to see what is loaded and which is the default, and "
    "diff_versions to see what changed between two releases. Use list_endpoints or search_endpoints to discover endpoints, then "
    "get_endpoint for full details. Use list_schemas and get_schema for data model definitions. All results have $refs resolved inline."
)

# Replaced by build_server(); a placeholder so the tool functions can be imported and called in tests.
registry = VersionRegistry(".", None)


def _header(version_key: str) -> str:
    """Return the first line of every tool result."""
    return f"ND {version_key}"


def list_endpoints(
    tag: str | None = None,
    path_contains: str | None = None,
    method: str | None = None,
    version: str | None = None,
) -> str:
    """List API endpoints. Returns compact one-line-per-endpoint format.

    Filters are optional and can be combined:
    - tag: exact tag name match
    - path_contains: substring match in the URL path
    - method: HTTP method (GET, POST, PUT, DELETE, PATCH)
    - version: ND release to query (e.g. '4.2.1'); default when omitted
    """
    store, key = registry.resolve(version)
    if store is None:
        return key
    return f"{_header(key)}\n{store.query_list_endpoints(tag=tag, path_contains=path_contains, method=method)}"


def get_endpoint(
    path: str,
    method: str,
    ref_depth: int = 3,
    version: str | None = None,
) -> str:
    """Get full details of a specific API endpoint.

    Returns parameters, request body, and response schemas with $ref
    references resolved inline. Use list_endpoints first to find paths.

    - path: API path (e.g. /api/v1/infra/aaa/localUsers/{loginId})
    - method: HTTP method (GET, POST, PUT, DELETE, PATCH)
    - ref_depth: max $ref resolution depth (0-10, default 3)
    - version: ND release to query (e.g. '4.2.1'); default when omitted
    """
    store, key = registry.resolve(version)
    if store is None:
        return key
    return f"{_header(key)}\n{store.query_get_endpoint(path=path, method=method, ref_depth=ref_depth)}"


def search_endpoints(
    query: str,
    max_results: int = 20,
    version: str | None = None,
) -> str:
    """Search endpoints by keyword.

    Case-insensitive search across paths, summaries, descriptions,
    operation IDs, and parameter names.

    - query: search term
    - max_results: maximum results to return (1-100, default 20)
    - version: ND release to query (e.g. '4.2.1'); default when omitted
    """
    store, key = registry.resolve(version)
    if store is None:
        return key
    return f"{_header(key)}\n{store.query_search_endpoints(query=query, max_results=max_results)}"


def list_schemas(
    name_filter: str | None = None,
    version: str | None = None,
) -> str:
    """List component/model schema names.

    Returns schema name, type, and property preview in compact format.

    - name_filter: optional substring filter on schema names
    - version: ND release to query (e.g. '4.2.1'); default when omitted
    """
    store, key = registry.resolve(version)
    if store is None:
        return key
    return f"{_header(key)}\n{store.query_list_schemas(name_filter=name_filter)}"


def get_schema(
    name: str,
    ref_depth: int = 3,
    api: str | None = None,
    version: str | None = None,
) -> str:
    """Get a component/model schema definition by name.

    Returns the full schema with $ref references resolved inline, scoped to the
    file that defines it. Use list_schemas to find available names; names listed
    with "(definitions differ)" need `api` to pick one.

    - name: schema name (e.g. 'LocalUser')
    - ref_depth: max $ref resolution depth (0-10, default 3)
    - api: which API file's definition to return when a name exists in several
      ('analyze', 'infra', 'manage', 'onemanage'); optional otherwise
    - version: ND release to query (e.g. '4.2.1'); default when omitted
    """
    store, key = registry.resolve(version)
    if store is None:
        return key
    return f"{_header(key)}\n{store.query_get_schema(name=name, ref_depth=ref_depth, api=api)}"


def list_tags(version: str | None = None) -> str:
    """List all API tags with descriptions. Tags group related endpoints.

    - version: ND release to query (e.g. '4.2.1'); default when omitted
    """
    store, key = registry.resolve(version)
    if store is None:
        return key
    return f"{_header(key)}\n{store.query_list_tags()}"


def get_api_info(version: str | None = None) -> str:
    """Get API metadata for one loaded release: per-file titles and spec versions, servers, counts, and the list of loaded releases.

    - version: ND release to describe (e.g. '4.2.1'); default when omitted
    """
    store, key = registry.resolve(version)
    if store is None:
        return key
    return f"{_header(key)}\n{store.query_get_api_info()}"


TOOL_FUNCTIONS = (
    list_endpoints,
    get_endpoint,
    search_endpoints,
    list_schemas,
    get_schema,
    list_tags,
    get_api_info,
)


def build_server(schema_dir: str, default_version: str | None = None) -> FastMCP:
    """
    # Summary

    Load the registry from `schema_dir`, install it as the module-level `registry`, and return a FastMCP instance with every tool registered.

    ## Raises

    None
    """
    global registry  # pylint: disable=global-statement
    registry = VersionRegistry(schema_dir, default_version)
    registry.load()
    mcp = FastMCP(name="nd-openapi", instructions=INSTRUCTIONS)
    for fn in TOOL_FUNCTIONS:
        mcp.tool(fn)
    return mcp


def main() -> None:
    """
    # Summary

    Entry point: read `ND_SCHEMA_DIR` / `ND_DEFAULT_VERSION`, build the server, and run it.

    ## Raises

    None
    """
    schema_dir = os.environ.get("ND_SCHEMA_DIR", ".claude/schemas")
    if not os.path.isabs(schema_dir):
        schema_dir = os.path.join(os.getcwd(), schema_dir)
    build_server(schema_dir, os.environ.get("ND_DEFAULT_VERSION") or None).run(transport="streamable-http", host="0.0.0.0", port=8000)


if __name__ == "__main__":
    main()
