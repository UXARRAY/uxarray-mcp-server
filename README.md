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

> **Local by default; HPC is opt-in.** Everything runs on your machine unless
> you configure a [Globus Compute](https://www.globus.org/compute) endpoint.
> The remote option only becomes available once such an endpoint exists —
> running one requires an account and allocation on that HPC system, though a
> shared/service-account endpoint can let authorized users submit without their
> own login.

> **⚠️ What the AI can access.** Any file you (or your HPC account) can read.
> Any compute the configured endpoint can submit. Outputs are written to your
> disk. **See [SECURITY.md](SECURITY.md) before connecting any remote endpoint.**

---

## Pick your path

You are most likely one of:

1. **Local user** — laptop only, no HPC. → [Local install](#local-install).
2. **HPC user, endpoint already exists** — someone at your lab gave you a
   Globus Compute endpoint UUID. → [Local install](#local-install), then
   [docs/remote-hpc.md](docs/remote-hpc.md).
3. **HPC user, your own personal endpoint** — you have a Globus identity and
   shell access to an HPC machine, and want to stand up an endpoint just for
   yourself. → [Local install](#local-install), then
   [docs/operating-an-endpoint.md](docs/operating-an-endpoint.md#solo-personal-endpoint-quickstart).
4. **Group / shared endpoint operator** — you're standing one up for a team,
   project, or lab. → [Local install](#local-install), then the full
   [docs/operating-an-endpoint.md](docs/operating-an-endpoint.md) including
   service-account migration and the MEP allowlist.

---

## Local install

Five steps. Each is one command unless noted.

### Step 1 — Install the package

Pick one. `uv` is the easiest; `pip` works too.

```bash
# Recommended
uv tool install --python 3.12 uxarray-mcp

# Or from a fresh clone (developer path)
git clone https://github.com/UXARRAY/uxarray-mcp-server.git
cd uxarray-mcp-server && uv sync --python 3.12
# or: bash SETUP.sh   (does the sync + runs the local test suite in one step)
```

> **Why `--python 3.12`?** The server uses Globus Compute to submit work to
> HPC endpoints, and Globus Compute's serializer is fragile across Python
> minor versions — a 3.13 submitter against a 3.12 endpoint worker raises
> `WorkerLost` on non-trivial payloads. HPC sites broadly ship 3.12 conda
> stacks today, so we pin the install to match. Tracking removal of this pin
> at [globus/globus-compute#2139](https://github.com/globus/globus-compute/issues/2139).
> `uv` downloads 3.12 automatically if your system doesn't have it.

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

Prints a JSON diagnostic report. With no endpoints configured it reports a
passing local setup and skips the remote checks; the process exits `0` when
`passed` is true.

### Step 5 — Ask the AI to do something

In your client, try:

> "Open `<path to a UGRID/MPAS/SCRIP grid file>` and plot the mesh."

That's it for local use.

**A few more things to try:**

- `Use run_analysis with operation="inspect_mesh" and grid_path="healpix:4"` —
  no sample file needed; HEALPix meshes are generated on the fly.
- `Run a complete scientific analysis on healpix:4` — the autonomous
  Analyze → Plan → Execute → Verify agent (see
  [docs/scientific-agent.md](docs/scientific-agent.md)).
- `Create a session called baseline-analysis, register <grid> and <data> in
  it, then run the workflow for <variable>` — persisted, resumable
  multi-step runs (see [docs/workflows.md](docs/workflows.md)).
- `Diagnose my configured endpoint status` — once you've added an endpoint
  below, this is the fastest way to check it's healthy.

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
The dispatcher falls back to local if the endpoint is unhealthy. This now
includes `get_capabilities` and the remapping tools (`remap_variable`,
`regrid_dataset`, `remap_to_rectilinear`) — so discovery and remapping can run
directly against datasets that live only on an HPC filesystem.

Full schema: [docs/tools.md](docs/tools.md).

---

## Transparency & correctness safeguards

Because agent-driven analysis needs to be *trustworthy*, every result is
auditable and the server actively flags common scientific pitfalls:

- **Provenance on everything.** Each result carries a `_provenance` block:
  the tool that ran, timestamp, input arguments, `execution_venue`
  (`local` or `hpc:<endpoint>`), and the UXarray/Python versions used.
- **Derivative unit convention is never hidden.** `gradient`, `curl`, and
  `divergence` echo `scale_by_radius` in both the result and provenance, so a
  unit-sphere result can never be mistaken for a physical (per-metre) one.
- **Vector-calculus sanity guard.** `curl`/`divergence` warn (without blocking)
  when the two inputs are the same field, or when neither carries a
  velocity/flux-like `units` attribute — the classic "vorticity from two random
  scalars" mistake now surfaces a warning in `_provenance.warnings`.
- **Local/remote version drift is surfaced.** Remote results record the
  worker's *actual* UXarray version (`remote_uxarray_version`) and emit a
  warning when it differs from the local version, so silent numerical
  differences between venues can't slip through.
- **Validation gating.** `analyze_dataset` validates a dataset (NaN/Inf/fill
  checks) before computing statistics like the zonal mean.

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

## Upgrading

```bash
uv tool upgrade --python 3.12 uxarray-mcp        # or your original install method
```

> **⚠️ Restart your AI client after upgrading.** MCP servers are launched once
> when your client (Claude Desktop, Claude Code, Cursor, …) starts and are **not
> hot-reloaded**. After upgrading the package, **fully quit and reopen your AI
> client** so it relaunches `uxarray-mcp serve` with the new code. Until you do,
> the running server keeps executing the *old* version — new tools and fixes
> won't appear, and you may see confusing errors (for example, a `use_remote`
> call on an HPC-only path failing with "file not found" because the old,
> local-only tool is still loaded). If in doubt, run `uxarray-mcp doctor` and
> check the reported version.

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
