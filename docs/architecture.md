# Architecture

The UXarray MCP Server is organized into three layers:

## Layer Overview

<div class="arch-flow">
  <div class="arch-box">
    <strong>MCP Client</strong><br>
    Claude, Cline, Continue, or another MCP-compatible client
  </div>
  <div class="arch-arrow">↓</div>
  <div class="arch-box">
    <strong>FastMCP Server</strong><br>
    Registers tools from <code>uxarray_mcp.server</code> and exposes them to the client
  </div>
  <div class="arch-arrow">↓</div>
  <div class="arch-box">
    <strong>Tools Layer</strong><br>
    Input handling, routing, provenance, diagnostics, and optional HPC wrappers
  </div>
  <div class="arch-arrow">↓</div>
  <div class="arch-box">
    <strong>Domain Layer</strong><br>
    Pure computation logic shared by local and remote execution paths
  </div>
  <div class="arch-arrow">↓</div>
  <div class="arch-grid">
    <div class="arch-box">
      <strong>Local Path</strong><br>
      UXarray runs directly on the machine hosting the MCP server
    </div>
    <div class="arch-box">
      <strong>Remote Path</strong><br>
      Globus Compute submits work to a configured endpoint on an HPC system
    </div>
  </div>
</div>

## Current High-Level Flow

### Local execution

1. The MCP client calls a tool such as `inspect_mesh`.
2. The tool implementation in `tools/` validates inputs and chooses the local path.
3. The shared computation in `domain/` runs through UXarray.
4. The result gets a `_provenance` block and is returned to the client.

### Remote execution

1. The MCP client calls a tool such as `inspect_mesh(..., use_remote=True)`.
2. The HPC wrapper checks endpoint readiness and configuration.
3. The remote agent submits a self-contained function from `remote/compute_functions.py` through Globus Compute.
4. The endpoint receives that function and runs it in the remote worker environment.
5. The result comes back to the local machine, where provenance is attached before returning it to the client.

## Important Terms

### Globus Compute

The remote function-execution system used by this repository. It moves Python
functions from the local machine to the remote endpoint and returns the result.

### Endpoint

A named Globus Compute service running on the remote machine or cluster. The
endpoint manager stays connected to Globus and starts the child endpoint and
worker processes that execute submitted functions.

### Academy

The lightweight agent abstraction used in `remote/agent.py` to organize local
and remote actions. It is a convenience layer inside this repo, not the
transport itself. Globus Compute is still the actual remote execution system.

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
