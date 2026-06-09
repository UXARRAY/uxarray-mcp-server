# UXarray MCP Server

An MCP server that lets an AI assistant (Claude Code, Claude Desktop, Cursor,
or any MCP client) analyze unstructured climate meshes with
[UXarray](https://uxarray.readthedocs.io/) — locally on your machine, or
remotely on an HPC system you have access to.

```text
┌─────────────┐  stdio  ┌──────────────┐                    ┌─────────────────┐
│  AI client  │ ◀─────▶ │ uxarray-mcp  │ ◀── Globus ──────▶ │  HPC endpoint   │
│  (Claude…)  │   pipe  │ (your laptop)│    Compute (opt)   │ (Slurm/PBS node)│
└─────────────┘         └──────────────┘                    └─────────────────┘
```

> **What the AI can do.** Open meshes and datasets, compute area / zonal mean
> / vorticity / divergence, subset, remap, plot, and run multi-step workflows.
> All as natural-language prompts.

> **⚠️ What the AI can access.** Any file you (or your HPC account) can read.
> Any compute the configured endpoint can submit. Outputs are written to your
> disk. **See [SECURITY.md](SECURITY.md) before connecting any remote endpoint.**

---

## Pick your path

You are most likely one of:

1. **Local user** — laptop only, no HPC. → [Local install](#local-install) (5 min).
2. **HPC user, endpoint already exists** — someone at your lab gave you a
   Globus Compute endpoint UUID. → [Local install](#local-install), then
   [docs/remote-hpc.md](docs/remote-hpc.md) (15 min).
3. **HPC user, your own personal endpoint** — you have a Globus identity and
   shell access to an HPC machine, and want to stand up an endpoint just for
   yourself. → [Local install](#local-install), then
   [docs/operating-an-endpoint.md](docs/operating-an-endpoint.md#solo-personal-endpoint-quickstart)
   (~30 min).
4. **Group / shared endpoint operator** — you're standing one up for a team,
   project, or lab. → [Local install](#local-install), then the full
   [docs/operating-an-endpoint.md](docs/operating-an-endpoint.md) including
   service-account migration and the MEP allowlist (~1 hr+, site-dependent).

---

## Local install

Five steps. Each is one command unless noted.

### Step 1 — Install the package

Pick one. `uv` is the easiest; `pip` works too.

```bash
# Recommended
uv tool install uxarray-mcp

# Or from a fresh clone (developer path)
git clone https://github.com/UXARRAY/uxarray-mcp-server.git
cd uxarray-mcp-server && uv sync
```

### Step 2 — Write a starter config

```bash
uxarray-mcp setup
```

Creates `~/.config/uxarray-mcp/config.yaml` with sensible defaults. Local mode
needs nothing more.

### Step 3 — Connect your AI client

**Claude Desktop**

```bash
uxarray-mcp install-claude        # merges the mcpServers block into your config
# or
uxarray-mcp install-claude --print-only   # prints the JSON to paste manually
```

Restart Claude Desktop. The `uxarray` server should appear in Settings →
Developer.

**Claude Code**

```bash
claude mcp add uxarray --transport stdio -- uxarray-mcp serve
```

Then `/mcp` in Claude Code; pick `uxarray`.

**Cursor / other MCP clients**

Add an MCP server entry pointing at `uxarray-mcp serve` over stdio. See your
client's MCP docs.

### Step 4 — Sanity check

```bash
uxarray-mcp doctor
```

Should print `local execution: ok` and (if no endpoints configured) skip the
remote checks.

### Step 5 — Ask the AI to do something

In your client, try:

> "Open `<path to a UGRID/MPAS/SCRIP grid file>` and plot the mesh."

That's it for local use.

---

## Going beyond your laptop

If you have an HPC account at a national lab or university cluster with
[Globus Compute](https://www.globus.org/compute) available:

| You want to … | Read this |
|---|---|
| Connect to an endpoint someone else set up | **[docs/remote-hpc.md](docs/remote-hpc.md)** |
| Stand up your own endpoint | **[docs/operating-an-endpoint.md](docs/operating-an-endpoint.md)** |
| Understand the security model first | **[SECURITY.md](SECURITY.md)** |

Both paths assume you've finished local install above.

---

## What the MCP exposes

Intent-shaped tools, not raw UXarray bindings:

- `get_capabilities` — what can I do with this mesh?
- `analyze_dataset` — deterministic first-look: inspect, validate, area, zonal mean, plots.
- `run_analysis` — one operation at a time (gradient, curl, subset, remap, …).
- `plot_dataset` — mesh, geographic, variable, or zonal-mean plots.
- `diagnose_endpoint`, `probe_path_access` — endpoint health + file readability.
- `run_workflow`, `resume_workflow`, `get_status`, `get_result`, `manage_session` —
  persisted sessions and multi-step workflows.

Tools that can run remotely take `use_remote: bool` and optional `endpoint: str`.
The dispatcher falls back to local if the endpoint is unhealthy.

Full schema: [docs/tools.md](docs/tools.md).

---

## CLI reference

| Command | Purpose |
|---|---|
| `uxarray-mcp serve` | Run the MCP server (used by your AI client) |
| `uxarray-mcp setup` | Write a starter config |
| `uxarray-mcp endpoints add NAME UUID` | Register a Globus Compute endpoint |
| `uxarray-mcp endpoints list` | Show configured endpoints |
| `uxarray-mcp doctor` | Validate local + (optionally) remote setup |
| `uxarray-mcp install-claude` | Merge or print the Claude Desktop config block |

---

## Risks (read before relying on output)

AI agents can misread prompts, pick the wrong file, get units wrong (e.g.,
sphere-radius scaling on derivatives), or run long jobs on your HPC
allocation. uxarray-mcp does **not** guarantee correctness of agent-driven
analysis. You are responsible for:

- Verifying numerical results before publishing.
- Reviewing what files the agent opens.
- Monitoring HPC job submissions against your allocation.

For the security model (what the agent and the endpoint operator can access),
see **[SECURITY.md](SECURITY.md)**.

---

## Development

```bash
uv sync --extra hpc --extra docs --dev
uv run pre-commit run --all-files
uv run pytest tests/ --ignore=tests/test_remote_agent.py
uv run sphinx-build -b html docs docs/_build/html
```

Release process: [docs/release.md](docs/release.md).

## License

See [LICENSE](LICENSE).
