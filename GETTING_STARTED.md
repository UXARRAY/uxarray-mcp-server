# Getting Started with UXarray MCP Server

This is the short entry-point guide for repository users.

If you want the full docs version, use
[docs/getting-started.md](docs/getting-started.md).

## Local Setup

```bash
cd /path/to/uxarray-mcp-server
uv sync
uv run pytest tests/ --ignore=tests/test_remote_agent.py
```

If you want HPC support too:

```bash
uv sync --extra hpc
```

## Claude Desktop Example

Use absolute paths in your Claude Desktop MCP config:

```json
{
  "mcpServers": {
    "uxarray": {
      "command": "/absolute/path/to/uv",
      "args": [
        "--directory",
        "/absolute/path/to/uxarray-mcp-server",
        "run",
        "python",
        "-m",
        "uxarray_mcp.server"
      ]
    }
  }
}
```

Then fully quit and reopen Claude Desktop.

## If You Want HPC

Do not start with scheduler debugging.

Read these in order:

1. [docs/globus-compute.md](docs/globus-compute.md)
2. [docs/hpc.md](docs/hpc.md)
3. [docs/improv.md](docs/improv.md) if you are on Argonne Improv

The key idea is that there are three separate layers:

1. the local machine running this repository
2. the endpoint on the HPC machine
3. the remote worker environment that must also have `uxarray`

## First HPC Checks

Once an endpoint UUID is in `config.yaml`, run:

```text
Run validate_hpc_setup
Run validate_hpc_setup with probe_timeout_seconds=180 and sample_path="/path/to/file.nc"
Run probe_path_access on /path/to/file.nc with use_remote=True
```

Or use the CLI helper:

```bash
uv run python scripts/hpc_doctor.py --timeout-seconds 180 --sample-path /path/to/file.nc
```

## Useful Pointers

- [README.md](README.md) for the high-level project overview
- [docs/tools.md](docs/tools.md) for tool-by-tool behavior
- [docs/workflows.md](docs/workflows.md) for sequential remote workflows
- `scripts/improv_endpoint.sh` for Improv endpoint templates
- `scripts/agentic_hpc_loop.py` for a multi-step remote example
