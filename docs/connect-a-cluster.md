# Connect a Cluster — Start Here

Your data is on an HPC machine. You want to ask an AI about it without
downloading anything. This page gets you there.

> **Never used Globus?** Ten minutes on
> [globus-basics.md](globus-basics.md) first. It covers the identity, why it
> has to be your institutional one, and why Compute is not Transfer — the
> three things that account for most stuck setups.

It is machine-agnostic: the same five commands work for Chrysalis, Casper,
Perlmutter or a university cluster nobody has written a page about. Site
pages ([chrysalis](chrysalis.md), [ucar](ucar.md), [improv](improv.md))
exist only for what is genuinely site-specific.

---

## The idea in one picture

Nothing moves your data. Your laptop sends a *function* to the machine the
data already lives on, and that machine sends back a number, a summary, or a
small image.

```text
  YOUR LAPTOP                                  THE CLUSTER
  ┌───────────────────────┐                    ┌────────────────────────┐
  │ AI client             │                    │ endpoint  (a daemon    │
  │   │                   │   "run this        │   running as YOU)      │
  │ uxarray-mcp  ─────────┼───  function" ────▶│      │                 │
  │                       │                    │   worker  (uxarray,    │
  │            ◀──────────┼─── small result ───┼──    your files)       │
  └───────────────────────┘                    └────────────────────────┘
          you                 Globus Compute            your HPC account
```

Three things, in three places, each of which can be wrong independently:

| Piece | Lives | Fails as |
|---|---|---|
| **Identity** | your laptop | auth errors, browser login prompts |
| **Endpoint** | the cluster | `ENDPOINT_NOT_ONLINE`, probe timeouts |
| **Worker env** | the cluster | `ModuleNotFoundError`, version drift |

Diagnose in that order. Most "it doesn't work" is the first or the third,
and the error usually names the second.

### Two things people reasonably expect, which are not true

- **An endpoint is per-user, not per-machine.** It runs *as your HPC
  account* and can read exactly what you can read. There is no shared
  "Chrysalis endpoint" unless someone deliberately operates one for a group.
- **Compute is not Transfer.** Globus Compute runs code; Globus Transfer
  moves files. Separate services, separate consents. A working endpoint
  cannot copy a file. You usually do not need Transfer at all — see
  [data-transfer.md](data-transfer.md).

---

## Do you already have an endpoint?

This is the fork in the road, and the question most new users get stuck on.

```bash
uxarray-mcp endpoints discover
```

- **Lists something** → you have one. Go to [Connect](#connect-5-minutes).
- **Lists nothing** → nobody has started one for your account. Go to
  [Create](#create-20-minutes).
- **Auth error** → the first Globus command opens a browser. Finish the
  login and re-run.

> **Where does a UUID come from?** It is printed *once*, when an endpoint
> first registers, and it is easy to lose. `endpoints discover` asks the
> Globus service instead of relying on you having saved it.

---

## Connect (5 minutes)

You have a UUID, either from `discover` or from a colleague.

### 1. Install the HPC extra

```bash
uv tool install --python 3.12 "uxarray-mcp[hpc]"
```

`--python 3.12` is not cosmetic. Globus Compute serializes your function
with `dill`, which is fragile across Python minor versions; a mismatch
surfaces as `WorkerLost` on real payloads but *works* on toy ones, so it
passes a smoke test and fails on your actual job.

### 2. Register the endpoint

```bash
uxarray-mcp endpoints discover      # prints a ready-made `add` line
uxarray-mcp endpoints add chrysalis <UUID> --path-prefix /lcrc/ --set-default
```

`--path-prefix` is routing: *"paths starting with this belong to this
machine."* Give one to every endpoint. Clusters share mount names — both
Improv and Chrysalis expose `/home/` — so an endpoint with no prefix never
wins a match and its work silently goes to the default instead.

Common prefixes: `/lcrc/` (Chrysalis) · `/glade/` (NCAR) ·
`/gpfs/fs1/` (Improv) · `/pscratch/`, `/global/` (NERSC).

Not sure? Run `pwd` in your data directory on the cluster and use the first
one or two components.

### 3. Check it

```bash
uxarray-mcp doctor --summary --endpoint chrysalis
```

```
PASS  overall
      mode: auto
  ok    config: Configured endpoint chrysalis in ~/.config/uxarray-mcp/config.yaml.
  ok    endpoint_status: Endpoint manager reports status='registered'.
```

This submits a real task, which is the only honest test — see
[Why `registered` is not `working`](#why-registered-is-not-working).

### 4. Point it at your data

```bash
uxarray-mcp doctor --summary --endpoint chrysalis \
  --sample-path /lcrc/group/e3sm/$USER/mydata/grid.nc
```

Reading the actual file is the check that matters. The endpoint can be
perfectly healthy and still not see your path.

### 5. Ask the AI

> "Inspect the mesh at /lcrc/group/e3sm/me/run/grid.nc"

Results carry `execution_venue: hpc:<name>` in their provenance. If it says
`local`, it ran on your laptop — which is a correctness question, not a
performance one.

---

## Create (20 minutes)

Nobody has started an endpoint for your account. You will run a small daemon
on the cluster under your own user.

> Worth knowing before you start: the daemon must stay running. On a login
> node it survives until the node reboots or an admin kills it; under Slurm
> or PBS it lives inside an allocation and **ends when that allocation
> does**. That is normal and recoverable — see
> [the endpoint went away](#the-endpoint-went-away).

```bash
# on a login node of the cluster
python -m pip install --user globus-compute-endpoint

globus-compute-endpoint configure my-uxarray
# edit ~/.globus_compute/my-uxarray/config.yaml for your scheduler
globus-compute-endpoint start my-uxarray      # browser login on first run
#  >>> prints your endpoint UUID — this is the moment it appears <<<
```

Then, back on your laptop, follow [Connect](#connect-5-minutes) with that
UUID. If you lose it, `uxarray-mcp endpoints discover` will find it again.

The worker also needs `uxarray` and `xarray` importable in whatever
environment the endpoint launches. `doctor` reports what the worker actually
imported, which is how you check.

Scheduler templates, provider choices and multi-user setups:
[operating-an-endpoint.md](operating-an-endpoint.md).

---

## When it does not work

### Why `registered` is not `working`

`registered` means the manager process has checked in with Globus. It does
**not** mean a worker exists, that your Python environment is intact, or
that the scheduler has nodes free.

Globus itself only reports registration — its status call returns no worker
counts — so no status command can tell you more. **Submitting a task is the
only real test**, which is what `doctor` does by default.

### The endpoint went away

```
ENDPOINT_NOT_ONLINE / did not signal readiness
```

Usually a cold allocation: the Slurm or PBS job ended while the endpoint sat
idle, and the next submit has to wait for a new one. **Retry in a minute.**
The first call after an idle period can take ~60 s to land.

The raw Globus message blames `user_endpoint_config`; on a single-user
endpoint that is a red herring, which is why this server rewrites it.

If retrying keeps failing, the daemon is genuinely gone — restart it on the
cluster.

### Version drift warnings

```
UXarray version drift: local=2026.9.1, remote(worker)=2026.9.0
```

The worker's environment is updated separately from your laptop and is
routinely behind. Worth acting on: a fix you merged and released can be
absent on the cluster, so the bug looks unfixed.

Check where the worker actually imports from before updating anything — an
editable install or a `PYTHONPATH` entry will beat the conda environment,
and updating conda then changes nothing:

```bash
uxarray-mcp doctor --endpoint NAME | python -c "import json,sys; print(json.load(sys.stdin)['remote_probe']['modules'])"
```

### Everything looks right and nothing runs

Work through the layers in order rather than guessing:

```bash
uxarray-mcp endpoints list                       # 1. is it registered here?
uxarray-mcp doctor --summary --endpoint NAME     # 2. does a task run at all?
uxarray-mcp doctor --endpoint NAME --sample-path /your/file.nc   # 3. is the file readable?
```

The first failure is the real one; later checks fail as a consequence.

---

## Where next

| You want | Page |
|---|---|
| Argonne Chrysalis specifics | [chrysalis.md](chrysalis.md) |
| NCAR Casper/Derecho specifics | [ucar.md](ucar.md) |
| Argonne Improv specifics | [improv.md](improv.md) |
| Run your own endpoint properly | [operating-an-endpoint.md](operating-an-endpoint.md) |
| Move files (rarely needed) | [data-transfer.md](data-transfer.md) |
| What the operator can see | [SECURITY.md](https://github.com/UXARRAY/uxarray-mcp-server/blob/main/SECURITY.md) |
