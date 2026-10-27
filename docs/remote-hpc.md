# Remote HPC — the long form

[globus-basics.md](globus-basics.md) explains Globus and the identity.
[connect-a-cluster.md](connect-a-cluster.md) gets you running in five
commands. **Come here when one of those did not work**, or when you want
the reasoning behind a step.

Assumes you already have: a working local install, an HPC account with
shell access, data that account can read, and either an endpoint UUID or
a plan to stand one up ([operating-an-endpoint.md](operating-an-endpoint.md)).
Also assumes you have read
[SECURITY.md](https://github.com/UXARRAY/uxarray-mcp-server/blob/main/SECURITY.md)
— connecting to an endpoint means its operator sees what you submit.

Getting a Globus identity and installing the HPC extra are covered in
those pages. This one picks up from the UUID.

---

## 1. Register the endpoint UUID locally

You need a name to refer to the endpoint by, plus the UUID and the
filesystem prefix where the data lives.

**If you do not have the UUID**, do not go hunting for it — a UUID is
printed once, when the endpoint first registers, and is easy to lose. Ask
the service instead:

```bash
uxarray-mcp endpoints discover
```

That lists every endpoint your Globus identity can see and prints a
ready-made `endpoints add` line for each one, with a suggested path prefix.
An empty list means nobody has started an endpoint for your account yet —
see [operating-an-endpoint.md](operating-an-endpoint.md).

```bash
uxarray-mcp endpoints add NAME UUID --path-prefix /glade/ --set-default
```

Examples:

```bash
# NCAR Casper / Derecho (glade filesystem)
uxarray-mcp endpoints add ucar 79bf66fc-0507-42d0-a6bc-81628e9f1d77 \
    --path-prefix /glade/ --set-default

# Argonne Improv
uxarray-mcp endpoints add improv caf37dc0-759f-4e48-9e0a-04f2cdbd23d2 \
    --path-prefix /gpfs/fs1/ --path-prefix /home/

# Argonne Chrysalis
uxarray-mcp endpoints add chrysalis 3cca8be6-55ec-4386-b7fd-f6c1e161d52b \
    --path-prefix /lcrc/
```

`--path-prefix` tells the dispatcher: "files starting with this prefix
should route to this endpoint." You can give multiple. The `--set-default`
makes this endpoint the fallback when no path matches.

Give every endpoint a prefix. Clusters share conventional mount names — both
Improv and Chrysalis expose `/home/` — so an endpoint registered without one
never wins a match, and paths it should have claimed go to the default
endpoint instead. When a run is routed that way the result carries an explicit
provenance warning rather than silently reporting success from the wrong
facility.

Verify:

```bash
uxarray-mcp endpoints list
```

The endpoint UUID is **not a secret** by itself, but you still shouldn't
post it publicly — see [SECURITY.md](https://github.com/UXARRAY/uxarray-mcp-server/blob/main/SECURITY.md). It lives in
`~/.config/uxarray-mcp/config.yaml` (which is in `.gitignore` if you're in
the repo).

---

## 2. Authenticate and probe the endpoint

```bash
uxarray-mcp doctor --endpoint NAME --timeout-seconds 180
```

Replace `NAME` with the name you registered above (`ucar`, `improv`, etc.).

The first run will open a browser to <https://auth.globus.org> for OAuth
consent. Approve it. The token is cached at `~/.globus_compute/`.

A healthy run prints something like:

```text
endpoint ucar:
  status: active
  node: crhtc43
  python: 3.11.12
  pbs_job_id: 4187507.casper-pbs
  pythonpath_set: true
```

If it says **`registered` but probe timed out** — the endpoint manager is
up but no worker responded. Either the scheduler is busy, the worker
environment is broken, or you'll need to wait for a queued job to land.
Ask the operator. See troubleshooting below.

---

## 3. Use it from your AI client

In Claude or your MCP client, prompt:

> "Open `/glade/u/home/yourname/path/to/grid.nc` on the ucar endpoint and
> plot the mesh."

Or with the explicit kwargs the agent will pass under the hood:

> "Use `analyze_dataset` with `grid_path=/glade/.../grid.nc`,
> `use_remote=true`, `endpoint='ucar'`."

The first remote call will take 10–30 seconds (worker warmup). Subsequent
calls in the same session reuse the worker and are much faster.

---

## Verifying it's actually running remotely

In any tool response, the `_provenance` field will say:

```json
"execution_venue": "hpc:ucar"
```

or

```json
"execution_venue": "local"
```

If you asked for `use_remote=true` and got `local`, the dispatcher fell
back. Reasons appear in the response's `warnings` and in
`~/.config/uxarray-mcp/logs/`.

Remote results also record the worker's UXarray version as
`remote_uxarray_version`; if it differs from the local `uxarray_version` a
version-drift warning is added so you know the numbers were produced by a
different build.

---

## Live HPC integration tests (developers)

The remapping tools (`remap_variable`, `regrid_dataset`, `remap_to_rectilinear`)
run the heavy compute on the worker and return compact summaries. An opt-in test
suite validates this end-to-end against a real endpoint. It is **skipped by
default** and only runs when the required environment variables are set:

```bash
UXMCP_LIVE_ENDPOINT=chrysalis \
UXMCP_LIVE_GRID=/home/<user>/uxarray/test/meshfiles/mpas/QU/480/grid.nc \
UXMCP_LIVE_DATA=/home/<user>/uxarray/test/meshfiles/mpas/QU/480/data.nc \
UXMCP_LIVE_TARGET_GRID=/home/<user>/uxarray/test/meshfiles/mpas/dyamond-30km/gradient_grid_subset.nc \
UXMCP_LIVE_VARIABLE=bottomDepth \
uv run pytest tests/test_remote_remap_live.py -v
```

Each test asserts `execution_venue == "hpc:<endpoint>"` and that the worker
version is recorded. When the same paths are also readable locally, the suite
cross-checks that remote and local summary statistics agree.

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `globus_compute_sdk not installed` | Missing HPC extras | `uv tool upgrade --extra hpc uxarray-mcp` |
| Browser doesn't open on first auth | Headless laptop / SSH session | The Globus login prints an auth URL to the terminal — copy it into a local browser and paste the code back. |
| `endpoint status: registered, probe timed out` | Worker isn't responding | Operator's problem. Ask them. May be scheduler backlog. |
| `endpoint status: not found` | Wrong UUID or you've been removed | Re-check UUID with operator. Globus Auth identity must match endpoint's allow-list. |
| Tool returns `execution_venue: local` when you asked for remote | Auto-fallback fired | Check `warnings` in response. Common: path didn't match `path_prefix`, or endpoint unhealthy. |
| `PermissionError` reading `/glade/...` from worker | Your HPC user can't read that path | Verify with `ls` over SSH first. The endpoint runs as **your** user (or the operator's service account — check with them). |
| Slow first call, fast later calls | Normal — worker warmup | Not a bug. |
| `qsub: command not found` (PBS sites) | The endpoint's worker environment doesn't have scheduler commands on `PATH` | Fix in the endpoint's `worker_init` / environment, not on your laptop. |
| A path is readable in an interactive shell but not from the worker | You typed a login-node shell alias or symlink, not the canonical shared path | Run `readlink -f /path/to/file` and use the resolved path (e.g. the real `/gpfs/...` target). |

For deeper diagnostics from the shell:

```bash
uxarray-mcp doctor --endpoint NAME
```

or, from an MCP client, `diagnose_endpoint(endpoint="NAME", action="validate")`.

---

## When to use remote vs. local

Use **remote** when:

- The data lives on the HPC filesystem and is large (GB+).
- You'd otherwise need to Globus Transfer files to your laptop first. (If you do
  need to move files, that is a separate service with a separate login — see
  [data-transfer.md](data-transfer.md).)
- The analysis benefits from cluster CPU/memory.

Use **local** when:

- The data is small (test grids, plots, anything you already have on your laptop).
- You're iterating fast and don't want round-trip latency.
- The endpoint is unhealthy and you don't want to wait.

The dispatcher picks automatically when you omit `use_remote`. Path-prefix
routing handles most cases; for everything else, set `use_remote=true`
explicitly.

---

## Site-specific quickstarts

These pages have working examples for specific clusters:

- [Argonne Improv](improv.md)
- [Argonne Chrysalis](chrysalis.md)
- [NCAR Casper / Derecho](ucar.md)

If you're setting up at a new site for the first time, also read
[operating-an-endpoint.md](operating-an-endpoint.md) — even if a colleague
will do the actual setup, you'll need to understand what to ask them for.
