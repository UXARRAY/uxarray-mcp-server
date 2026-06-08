# Remote HPC Setup — Connecting to an Existing Endpoint

This page is for users who **already have an HPC account** (Argonne, NCAR,
NERSC, a university cluster, etc.) and want their AI agent to analyze data
that lives on that machine.

> **Prerequisites — check each one before starting:**
> 1. uxarray-mcp installed locally and working with your AI client. See the
>    [README](https://github.com/UXARRAY/uxarray-mcp-server/blob/main/README.md#local-install).
> 2. A user account on the HPC machine, with shell access.
> 3. The data you want to analyze is readable by your HPC account.
> 4. Either: someone has given you a **Globus Compute endpoint UUID** for
>    that machine, **or** you plan to stand up your own — in which case
>    stop and read [operating-an-endpoint.md](operating-an-endpoint.md) first,
>    then come back here.
> 5. You have read [SECURITY.md](https://github.com/UXARRAY/uxarray-mcp-server/blob/main/SECURITY.md). Connecting an endpoint
>    means the operator can see what you submit.

The total setup is **5 steps**, expect **15–30 minutes** the first time.

---

## The three pieces

Before the steps, the mental model. Remote analysis has three things that
have to all work, in three different places:

```text
┌────────────────────┐        ┌──────────────────────────┐
│  YOUR LAPTOP       │        │  HPC MACHINE             │
│                    │        │                          │
│  AI client         │        │  Globus Compute endpoint │
│    │ stdio         │        │    (runs as your HPC     │
│  uxarray-mcp ──────┼─Globus─┼──▶ user, executes        │
│    + globus-       │ Compute│    Python sent from      │
│    compute SDK     │  HTTPS │    your laptop)          │
│    + your Globus   │        │                          │
│    identity        │        │  uxarray + xarray in     │
│                    │        │  the worker environment  │
└────────────────────┘        └──────────────────────────┘
```

Most "it doesn't work" failures come from one of these three layers being
misconfigured. The steps below address each one in order.

---

## Step 1 — Get a Globus identity (one-time, 5 min)

If you've ever used Globus File Transfer for HPC, you already have this.
Skip to Step 2.

If not:

1. Go to <https://app.globus.org>.
2. Sign in with your **institutional identity** if your lab is listed
   (Argonne, NCAR/UCAR, LBL/NERSC, Oak Ridge, university SSO, etc.). This
   ensures your Globus identity is linked to the same account that has HPC
   access.
3. If your institution isn't listed, create a free Globus ID.
4. Verify you can reach <https://app.globus.org/account>. You're done.

> No fee. Globus is free for non-commercial research use.

---

## Step 2 — Install the HPC extras locally (1 min)

```bash
uv tool install "uxarray-mcp[hpc]"      # or `uv tool upgrade --extra hpc uxarray-mcp`
```

This adds the `globus-compute-sdk` to your local install. Verify:

```bash
uxarray-mcp doctor
```

You should see the SDK listed. (No endpoint health checks yet — that's
Step 4.)

---

## Step 3 — Register the endpoint UUID locally (1 min)

You need a name to refer to the endpoint by, plus the UUID someone gave you
and the filesystem prefix where the data lives.

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

Verify:

```bash
uxarray-mcp endpoints list
```

The endpoint UUID is **not a secret** by itself, but you still shouldn't
post it publicly — see [SECURITY.md](https://github.com/UXARRAY/uxarray-mcp-server/blob/main/SECURITY.md). It lives in
`~/.config/uxarray-mcp/config.yaml` (which is in `.gitignore` if you're in
the repo).

---

## Step 4 — Authenticate to Globus and probe the endpoint (2 min)

```bash
uxarray-mcp doctor --endpoint NAME --timeout-seconds 180
```

Replace `NAME` with what you used in Step 3 (`ucar`, `improv`, etc.).

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

## Step 5 — Use it from your AI client (2 min)

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

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `globus_compute_sdk not installed` | Missing HPC extras | `uv tool upgrade --extra hpc uxarray-mcp` |
| Browser doesn't open on first auth | Headless laptop / SSH session | Run `uxarray-mcp doctor` with `--no-browser`, paste the URL into a local browser |
| `endpoint status: registered, probe timed out` | Worker isn't responding | Operator's problem. Ask them. May be scheduler backlog. |
| `endpoint status: not found` | Wrong UUID or you've been removed | Re-check UUID with operator. Globus Auth identity must match endpoint's allow-list. |
| Tool returns `execution_venue: local` when you asked for remote | Auto-fallback fired | Check `warnings` in response. Common: path didn't match `path_prefix`, or endpoint unhealthy. |
| `PermissionError` reading `/glade/...` from worker | Your HPC user can't read that path | Verify with `ls` over SSH first. The endpoint runs as **your** user (or the operator's service account — check with them). |
| Slow first call, fast later calls | Normal — worker warmup | Not a bug. |

For deeper diagnostics:

```bash
uxarray-mcp diagnose-endpoint --endpoint NAME --action validate
```

---

## When to use remote vs. local

Use **remote** when:

- The data lives on the HPC filesystem and is large (GB+).
- You'd otherwise need to Globus Transfer files to your laptop first.
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
