# Architecture

The UXarray MCP Server is organized into three layers:

## Layer Overview

```
MCP Client (Claude, Cline, etc.)
        |
        v
   Tools Layer        — MCP-facing functions (tools/)
        |
        v
   Domain Layer       — Pure computation logic (domain/)
        |
        v
   UXarray / HPC      — UXarray library + optional Globus Compute
```

## Tools Layer (`tools/`)

MCP tool functions that are registered with the FastMCP server and exposed to AI agents. Each tool handles input validation, calls into the domain layer, attaches provenance, and returns structured results.

- **inspection.py** — Core local tools: mesh inspection, variable inspection, area calculation, zonal mean, dataset validation
- **remote_tools.py** — HPC-enabled wrappers with pre-flight health checks and automatic fallback to local
- **scientific_agent.py** — Autonomous four-stage agent (Analyze > Plan > Execute > Verify)
- **capabilities.py** — Tool discovery and filtering based on grid topology and data
- **execution_control.py** — Runtime mode switching (local / hpc / auto)

## Domain Layer (`domain/`)

Pure computation functions with no knowledge of MCP, I/O, or provenance. These are shared between local and HPC code paths.

- **mesh.py** — Grid loading with HEALPix support
- **area.py** — Face area statistics
- **variable.py** — Variable metadata and statistics extraction
- **zonal.py** — Zonal mean computation

## Remote Layer (`remote/`)

HPC infrastructure for offloading computations to remote clusters via Globus Compute.

- **config.py** — YAML configuration loader
- **agent.py** — Academy agent for Globus Compute orchestration
- **compute_functions.py** — Remote-serializable functions (sent to the cluster)
- **health.py** — Endpoint health checks

## Key Design Decisions

**Conditional tool registration** — HPC tools are only registered with the MCP server when an endpoint UUID is configured. This keeps the tool list clean for local-only users.

**Domain/tool separation** — Computation logic lives in `domain/` so the same code can run locally or be serialized and sent to a remote cluster without importing MCP dependencies.

**Provenance on everything** — Every tool result gets a `_provenance` block attached automatically via `provenance.py`.

**Validation gating** — The scientific agent runs dataset validation before zonal mean. If validation fails, zonal mean is skipped rather than producing unreliable results.

## Interactive Diagram

An interactive architecture diagram is available at `docs/architecture.html` in the repository.
