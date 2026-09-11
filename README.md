# UXarray MCP Server

An MCP server that lets an AI assistant (Claude Code, Claude Desktop, Codex,
opencode, Cursor, or any MCP client) analyze unstructured climate meshes with
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
5. **Just trying it out, or running an agent harness** — you don't want to
   install a scientific Python stack at all. → [Docker](#docker).

---

## Docker

The container is the fastest way to run the server without resolving
`uxarray`, `netcdf4`, `matplotlib`, and friends on your own machine. It ships
five small mesh fixtures so there is something to analyze immediately.

```bash
docker build -t uxarray-mcp:local .
docker run --rm -i uxarray-mcp:local          # stdio, what MCP clients spawn
```

Point Claude Code at it:

```bash
claude mcp add uxarray-docker --transport stdio -- \
  docker run --rm -i uxarray-mcp:local
```

To analyze your own meshes, mount them — `/work` is the working directory:

```bash
docker run --rm -i -v /path/to/my/data:/work uxarray-mcp:local
```

For an agent harness that wants HTTP instead of stdio:

```bash
docker run --rm -p 8001:8001 uxarray-mcp:local \
  serve --transport http --host 0.0.0.0
```

Verify an image end-to-end — handshake, tool surface, and one real
computation checked against an analytic result:

```bash
python3 scripts/container_smoke_test.py --image uxarray-mcp:local
```

**The image is local-only, on purpose.** The HPC extras
(`globus-compute-sdk`, `academy-py`) are not installed, and the baked config
pins `execution_mode: local`. A sealed container should not hold Globus
credentials or reach a Slurm endpoint — and an image that *could* submit
remote work is not one you should point an untrusted agent at. If you want
HPC, run the server on the host where your identity lives; see
[docs/remote-hpc.md](docs/remote-hpc.md).

**Baked fixtures** live at `/data/uxarray` and are generated at build time by
[`scripts/generate_container_fixtures.py`](scripts/generate_container_fixtures.py)
rather than committed as binaries, so what's in them is readable as code. Each
one targets a specific blind spot:

| Fixture | Why it exists |
|---|---|
| `global` | Coarse global mesh, unit sphere — the everyday case. |
| `earth_radius` | Declares R = 6371 km, so a missing radius scaling shows up in the numbers instead of hiding behind R = 1. |
| `multi_level` | Four levels 100 apart; a wrong level selection is unmistakable. |
| `time_level` | Three times × four levels, value `1000*t + 100*(k+1)` — the magnitude says which slice was taken. |
| `regional` | A sliver mesh, so remap-coverage failures have something to fail against. |

`MANIFEST.json` records a content hash per fixture — hashing decoded arrays
rather than file bytes, so it stays stable across NetCDF library versions. The
build verifies it, and you can re-check any image:

```bash
docker run --rm -i --entrypoint python uxarray-mcp:local - --verify \
  < scripts/generate_container_fixtures.py
```

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
cd uxarray-mcp-server && uv sync --python 3.12 --extra hpc --extra transfer
# or: bash SETUP.sh   (local-only sync + runs the local test suite in one step)
```

The `hpc` and `transfer` extras hold the Globus Compute and Globus Transfer
SDKs. Leave them off for a laptop-only install. Note that `uv sync` installs
*exactly* the requested set: running a plain `uv sync` later removes the
extras again, and `hpc/endpoint_status` will then report `unreachable` with
`No module named 'globus_compute_sdk'`.

> **Why `--python 3.12`?** Only the HPC path needs it. Globus Compute's
> serializer is fragile across Python minor versions — a 3.13 submitter
> against a 3.12 endpoint worker raises `WorkerLost` on non-trivial payloads,
> and HPC sites broadly ship 3.12 conda stacks today. Local-only use works on
> 3.11–3.13. Tracking removal of this constraint at
> [globus/globus-compute#2139](https://github.com/globus/globus-compute/issues/2139).
> `uv` downloads 3.12 automatically if your system doesn't have it.

### Step 2 — Write a starter config

```bash
uxarray-mcp setup
```

Creates `~/.config/uxarray-mcp/config.yaml` with sensible defaults. Local mode
needs nothing more.

Three environment variables adjust where the server looks and writes:
`UXARRAY_MCP_CONFIG` (path to a config file, checked before
`~/.config/uxarray-mcp/config.yaml`), `UXARRAY_MCP_STATE_DIR` (sessions,
result handles and rendered plots; default `~/.uxarray_mcp_server`), and
`UXARRAY_MCP_VERDICT_POLICY` (`full`, `reference_only` or `off` for the
postcondition block on every result).

### Step 3 — Connect your AI client

**Claude Desktop**

```bash
# merges the mcpServers block into the config file you name
uxarray-mcp install-claude --config-path ~/Library/Application\ Support/Claude/claude_desktop_config.json
# or
uxarray-mcp install-claude --print-only   # prints the JSON to paste manually
```

Without `--config-path` the command only prints the block; it never guesses
where your Claude Desktop config lives.

If you installed from a clone rather than `uv tool install`, the `uxarray-mcp`
binary lives in the project `.venv`. In every client config below, use
`uv --directory /path/to/uxarray-mcp-server run uxarray-mcp serve` as the
command instead of a bare `uxarray-mcp serve`.

Restart Claude Desktop. The `uxarray` server should appear in Settings →
Developer.

**Claude Code**

```bash
claude mcp add uxarray --transport stdio -- uxarray-mcp serve
```

Then `/mcp` in Claude Code; pick `uxarray`.

**Codex CLI**

```bash
codex mcp add uxarray -- uxarray-mcp serve
```

Or write `~/.codex/config.toml` directly:

```toml
[mcp_servers.uxarray]
command = "uxarray-mcp"
args = ["serve"]
```

Then `/mcp` in a Codex session.

**opencode**

Add to `~/.config/opencode/opencode.json`:

```json
{
  "mcp": {
    "uxarray": {
      "type": "local",
      "command": ["uxarray-mcp", "serve"],
      "enabled": true
    }
  }
}
```

The server registers 33 tools, which is a large tool schema to carry on every
request. `"enabled": false` turns it off for sessions that are not doing mesh
analysis.

**Cursor**

Add to `~/.cursor/mcp.json` (or a project-local `.cursor/mcp.json`):

```json
{
  "mcpServers": {
    "uxarray": {
      "command": "uxarray-mcp",
      "args": ["serve"]
    }
  }
}
```

**Any other MCP client**

The server speaks stdio, so every client wants the same two facts — the
command `uxarray-mcp` and the argument `serve`. `uxarray-mcp install-claude
--print-only` prints the `mcpServers` JSON block that most clients accept
verbatim.

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

Intent-shaped tools, not raw UXarray bindings — all local by default:

- `get_capabilities` — what can I do with this mesh?
- `analyze_dataset` — deterministic first-look: inspect, validate, area, zonal mean, plots.
- `run_analysis` — one operation at a time (gradient, curl, subset, remap, …).
  Remaps take `method`: `nearest_neighbor`, `inverse_distance_weighted` or
  `bilinear` on UXarray's own engine, or `conservative`, `nnn`, `dnn`,
  `average` on [YAC](https://dkrz-sw.gitlab-pages.dkrz.de/yac/) (equivalently
  `backend="yac"` with `yac_method`). Only `conservative` preserves the field
  integral, and it needs YAC importable where the remap runs — build it with
  `scripts/build_yac_local.sh` on a laptop or `scripts/hpc_build_yac.py` on a
  worker, and put its `site-packages` on `PYTHONPATH`.
- `plot_dataset` — `plot_type` of `mesh`, `mesh_geo`, `variable`, or `zonal_mean`.
- `run_workflow`, `resume_workflow`, `get_status`, `get_result`, `manage_session` —
  persisted sessions and multi-step workflows.

Helper namespaces also appear in `tools/list`: `session/*`, `hpc/*`,
`io/list_datasets`, `contract/*` and `prompt/*`.

Full schema and every `run_analysis` parameter: [docs/tools.md](docs/tools.md).

**Protocol version.** We do not implement MCP directly; servers are built
through `toolregistry-server`, which depends on the `mcp` Python SDK. As of
`toolregistry-server` 0.5.0 and `toolregistry` 0.16.0 the SDK cap is lifted, so
we resolve `mcp` 1.27 or 2.x (2.1.1 at the last lock) and negotiate spec
**`2026-07-28`** (stateless core,
cacheable list results, MRTR). 0.16.0 also widens the recognized content-block
set to audio, `resource_link`, and embedded resources.

**Once you've configured an HPC endpoint** (optional — see
[Going beyond your laptop](#going-beyond-your-laptop) below): most tools above
also take `use_remote: bool` and `endpoint: str`, falling back to local if the
endpoint is unhealthy. Two more tools exist purely for that case:
`diagnose_endpoint` and `probe_path_access` (endpoint health + file
readability). Ignore all of this until you actually have an endpoint to point
at.

---

## Transparency & correctness safeguards

Because agent-driven analysis needs to be *trustworthy*, every result is
auditable and the server actively flags common scientific pitfalls:

- **Provenance on everything.** Each result carries a `_provenance` block:
  the tool that ran, timestamp, input arguments, `execution_venue`
  (`local` or `hpc:<endpoint>`), and the UXarray/Python versions used.
- **Derivative unit convention is never hidden.** `gradient`, `curl`, and
  `divergence` echo `scale_by_radius` and a `radius_basis` block (the radius
  used and whether it came from the grid or the caller), so a unit-sphere
  result can never be mistaken for a physical (per-metre) one. Most grid files
  declare no `sphere_radius`; pass `sphere_radius=6371000` (metres) to attach
  Earth's. Without it, or with `scale_by_radius=False`, the call is refused
  with `outcome="input_required"` until you pass `acknowledge`. The same
  `sphere_radius` argument turns `calculate_area` from steradians into m².
- **Vector-calculus sanity guard.** `curl`/`divergence` warn (without blocking)
  when the two inputs are the same field, or when neither carries a
  velocity/flux-like `units` attribute — the classic "vorticity from two random
  scalars" mistake now surfaces a warning in `_provenance.warnings` and a
  machine-actionable `scientific_status` with stable warning codes.
- **Applicability is not suitability.** `get_capabilities` reports whether
  vector operations are structurally computable separately from whether
  metadata supports physical interpretation.
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
| `uxarray-mcp serve` | Run the MCP server (used by your AI client); `--profile core\|deferred-full`, `--transport stdio\|sse\|http` — see [docs/serving.md](docs/serving.md) |
| `uxarray-mcp openapi` | Print the OpenAPI document for the HTTP transport |
| `uxarray-mcp setup` | Write a starter config |
| `uxarray-mcp endpoints add NAME UUID` | Register a Globus Compute endpoint |
| `uxarray-mcp endpoints list` / `remove NAME` | Show or drop configured endpoints |
| `uxarray-mcp transfer setup` | Check and fix everything a Globus Transfer needs, including the browser login an MCP server cannot open |
| `uxarray-mcp doctor` | Validate local + (optionally) remote setup |
| `uxarray-mcp install-claude --config-path FILE` | Merge (or `--print-only`) the Claude Desktop config block |

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
uv sync --extra hpc --extra transfer --extra docs
uv run pre-commit run --all-files
uv run pytest tests/ --ignore=tests/test_remote_agent.py
uv run sphinx-build -b html docs docs/_build/html
```

Release process: [docs/release.md](docs/release.md).

## License

See [LICENSE](LICENSE).
