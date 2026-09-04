# MCP Server for Nexus Dashboard OpenAPI Schema

This repo contains an MCP server that provides lower-token
access to Cisco's OpenAPI Schema for Nexus Dashboard. Several
ND releases can be loaded side by side and queried by version.

Tested on macOS 26.4.1 (Tahoe) with Python 3.14

## Installation

```bash
mkdir -p $HOME/repos/mcp && cd $HOME/repos/mcp # Or wherever you keep your repositories
git clone https://github.com/allenrobel/nd-openapi-mcp.git
cd nd-openapi-mcp
# python should be Python v3.14 or higher
# Might work with v3.11 or higher, but you'll need to modify
# uv.lock line 3 (requires-python = ">=3.14") and test for
# yourself.
python -m venv ./venv --prompt nd-openapi-mcp
source .venv/bin/activate
uv sync
# If uv is not available
#   pip install uv
#   uv sync
# uv installs the dependencies needed for the MCP server, including FastMCP
```

## Schema layout and versions

Place each ND release's spec files in a subdirectory of `ND_SCHEMA_DIR` named after the release:

```text
schemas/
  4.2.1/   analyze.json  infra.json  manage.json  onemanage.json
  4.3.1/   analyze.json  infra.json  manage.json  onemanage.json
```

- Directory names must look like `X.Y.Z`; anything else is skipped with a warning.
- `ND_DEFAULT_VERSION` selects the release used when a tool call omits `version`. When unset, the highest release wins.
- Every tool accepts an optional `version` argument and every result starts with `ND <version>`.
- `list_versions` shows what is loaded; `diff_versions` compares two releases (endpoints and schema names added, removed, changed).
- If `ND_SCHEMA_DIR` contains spec files directly and no version subdirectories, they load as the single version `unversioned`.
- Component schemas are scoped per file, so `manage.json` and `onemanage.json` can define the same name with different bodies; `list_schemas` flags such names and `get_schema` takes `api` to choose.

## Tests

```bash
uv run pytest -q
```

`tests/test_real_schemas.py` runs only when both `schemas/4.2.1` and `schemas/4.3.1` are present.

## To use with Claude Code

### Global (for use with all Claude Code projects)

#### Claude Code mcp.json

Add the following (edited for your environment) to $HOME/.claude/mcp.json

```json
{
    "mcpServers": {
        "nd-openapi": {
            "type": "http",
            "url": "http://<host>:8000/mcp"
        }
    }
}
```

The server itself is started separately (see "To use standalone" below): `ND_SCHEMA_DIR` and `ND_DEFAULT_VERSION`
are set in the environment of that running process (e.g. via the `env` file), not in `mcp.json`.

## To use standalone

1. Follow the steps in Installation above
2. cd $HOME/repos/mcp/nd-openapi-mcp
3. source .venv/bin/activate
4. Edit env for your environment (see example below)
5. source env
6. python server.py

### Example env (located in root of this repository)

```bash
export ND_SCHEMA_DIR=$HOME/repos/mcp/nd-openapi-mcp/schemas
export ND_DEFAULT_VERSION=4.2.1
export PYTHONPATH=$HOME/repos/mcp/nd-openapi-mcp/.venv/lib/python3.14/site-packages
```
