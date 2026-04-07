# Try UXarray MCP

This project is an MCP server, not a hosted web app. The fastest way to
evaluate it today is to run the real tools locally against the built-in
`healpix` demo meshes.

## Fastest path: no MCP client required

If you just want proof that the service works, use the Python entry points
directly first.

### 1. Install the core dependencies

```bash
cd /path/to/uxarray-mcp-server
uv sync
```

### 2. Run a real tool against the built-in demo mesh

```bash
uv run python -c "from uxarray_mcp.tools.inspection import inspect_mesh; r=inspect_mesh('healpix:4'); print(r['format'], r['n_face'], r['n_node'])"
```

Expected output:

```text
HEALPix 3072 3074
```

### 3. Run the full scientific agent

```bash
uv run python -c "from uxarray_mcp.tools.scientific_agent import run_scientific_agent; r=run_scientific_agent('healpix:3'); print(r['execution_venue'], r['mesh_summary']['n_face'], r['area_results']['n_face'])"
```

Expected output:

```text
local 768 768
```

That confirms the server can:

- generate a demo mesh without external files
- inspect topology
- run the autonomous analysis flow
- calculate face-area statistics locally

## Full MCP experience

If you want to test the actual client-server workflow, follow
[Getting Started](getting-started.md) to connect Claude Desktop or another
MCP client.

After restart, try these prompts:

```text
Do you have access to an inspect_mesh tool?
Use inspect_mesh with healpix:4
Run a complete scientific analysis on healpix:4
What is the current execution mode?
```

You can evaluate the core experience without downloading a dataset because the
`healpix:<zoom>` shorthand is already built into the server.

## What the docs site can and cannot do

This docs site can reduce setup friction, but it is still not a true hosted
trial environment. A user still needs to:

- clone the repository
- install dependencies locally
- use Python directly or connect an MCP client

## What would make this truly tryable

To turn the docs site into a real product trial surface, the next step is a
hosted playground built around fixed sample meshes and datasets. The key pieces
are:

- a browser-based chat or tool runner wired to a real MCP client
- preloaded demo inputs so users never need their own files on first run
- ephemeral server instances per session
- saved example prompts with expected outputs
- a one-click handoff from the hosted demo to local Claude Desktop setup
