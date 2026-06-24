# Serving and Transports

The server is built on
[toolregistry](https://github.com/Oaklight/ToolRegistry) +
[toolregistry-server](https://github.com/Oaklight/toolregistry-server). The same
tool implementations are exposed over multiple protocols from a single process,
so the server is not tied to any one client. Claude Desktop is the default
target, but the tools are equally usable over REST or from plain Python.

For the Claude Desktop quickstart, see {doc}`getting-started`. This page covers
the additional surfaces the engine provides.

## The `serve` command

```bash
uxarray-mcp serve [--profile {core,deferred-full}]
                  [--transport {stdio,sse,http}]
                  [--host HOST] [--port PORT]
```

With no flags, `uxarray-mcp serve` starts MCP over stdio with the `core`
profile — the same behavior earlier releases had. Existing Claude Desktop
configurations work unchanged.

The server is assembled by `UXarrayApp`, an `App` subclass from
toolregistry-server that carries a single `ServerIdentity` (name, version,
description) shared by every transport. The same object also drives the
`openapi` command below.

## Profiles

The visible tool surface is selected by `--profile`:

| Profile | Visible tools | Use when |
|---|---|---|
| `core` (default) | ~31 | Most clients. Front-door gateway tools, session/HPC control, `list_datasets`, and prompts. Predictable, conservative. |
| `deferred-full` | ~31 visible (+32 deferred) | You want the full low-level surface. The raw implementation tools load with `defer=True`, so they do not appear in the initial list; agents find them with `discover_tools`. |

```bash
uxarray-mcp serve --profile deferred-full
```

In `core`, low-level operations are still reachable through the front-door
dispatchers (for example `run_analysis(operation="curl", ...)`).

## Transports

`--transport` selects the MCP transport:

| Transport | Description |
|---|---|
| `stdio` (default) | Subprocess transport used by Claude Desktop and Claude Code. |
| `sse` | Server-Sent Events over HTTP. Bind with `--host`/`--port`. |
| `http` | Streamable HTTP. Bind with `--host`/`--port`. |

```bash
uxarray-mcp serve --transport sse --host 127.0.0.1 --port 8001
uxarray-mcp serve --transport http --port 8000
```

## OpenAPI / REST

The same tools can be exposed as an OpenAPI/REST service for clients that speak
HTTP rather than MCP — curl, cloud assistants, chat UIs, or scripts. Install the
optional extra and start the `openapi` command:

```bash
pip install "uxarray-mcp[openapi]"

uxarray-mcp openapi [--profile {core,deferred-full}] [--host HOST] [--port PORT]
```

The tool implementations, provenance, and HPC dispatch are shared across MCP and
REST; only the protocol adapter differs. MCP and OpenAPI can run as separate
processes from the same install — for example `uxarray-mcp serve` for AI clients
and `uxarray-mcp openapi` for HTTP clients, behind a reverse proxy if needed.

## Tool discovery (`deferred-full`)

In the `deferred-full` profile, deferred tools are searchable via
`discover_tools`, which ranks tools by a BM25 match over names, docstrings, and
domain search hints. For example, a query like `"compute vorticity wind curl"`
surfaces `calculate_curl`. Operators can also promote deferred tools to the
visible set from the admin panel.

## Using the tools without an MCP client

Because the tools are ordinary Python functions, you can drive them directly —
no AI client, no transport:

```python
from uxarray_mcp.tools import inspect_mesh
result = inspect_mesh(file_path="grid.nc")  # dict with a _provenance block

# Or call by name through the same registry the server uses:
from uxarray_mcp.app import make_registry
reg = make_registry(profile="core")
run_analysis = reg.get_callable("run_analysis")
stats = run_analysis(operation="calculate_area", grid_path="grid.nc")
```

This is the basis for the REST surface and for pipeline/post-processing use.
