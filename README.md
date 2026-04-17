# MCP Server for Nexus Dashboard OpenAPI Schema

This repo contains an MCP server that provides lower-token
access to Cisco's OpenAPI Schema for Nexus Dashboard 4.2

Tested on macOS 26.4.1 (Tahoe)

## Installation

```bash
cd $HOME/repos # Or wherever you keep your repositories
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

## To use with Claude Code

### Global (for use with all Claude Code projects)

#### Claude Code mcp.json

Add the following (edited for your environment) to $HOME/.claude/mcp.json

Note that it requires that uv was installed per above.

```json
{
    "mcpServers": {
        "nd-openapi": {
            "type": "stdio"
            "command": "/Users/arobel/repos/nd-openapi-mcp/.venv/bin/uv",
            "args": ["run", "/Users/arobel/repos/nd-openapi-mcp/server.py"],
            "env": {
                "ND_SCHEMA_DIR": "/Users/arobel/repos/nd-openapi-mcp/schemas",
                "PYTHONPATH": ""
            }
        }
    }
}
```

#### Caveat

See the bit about warnings below. It applies to usage with
Claude Code as well.

## To use standalone

1. Follow the steps in Installation above
2. cd $HOME/repos/nd-openapi-mcp
3. source .venv/bin/activate
4. Edit env for your environment (see example below)
5. source env
6. python server.py

You'll see a lot of warnings about similar to below:

```bash
Warning: schemas/poolData redefined in onemanage.json (overwriting previous definition)
```

If you're developing for OneManage, you can ignore these.
If you're developing for the schema's that are overwritten,
you'll want to move the onemanage.json file.

The above would apply for Claude Code usage as well.

### Example env (located in root of this repository)

```bash
export ND_SCHEMA_DIR=$HOME/.claude/schemas
export PYTHONPATH=$HOME/repos/nd-openapi-mcp/.venv/lib/python3.14/site-packages
```
