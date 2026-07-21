# Operating an Endpoint

This page covers two related cases:

- **You want a personal endpoint** that only you submit to. Skip to
  [Solo personal endpoint quickstart](#solo-personal-endpoint-quickstart) below
  (~30 min). The full 8-step section is overkill for this case.
- **You're standing up a shared endpoint** for a team, project, or lab. Use the
  full [eight-step setup](#the-eight-steps) including a service account and the
  function allowlist (~1 hr+).

**Read [SECURITY.md](https://github.com/UXARRAY/uxarray-mcp-server/blob/main/SECURITY.md) first** — even a personal endpoint is shell-equivalent access for
whoever can submit to it (which includes a stolen refresh token from your laptop),
so the hardening basics still apply.

> **Prerequisites:**
> 1. Shell access to the HPC machine.
> 2. A Globus identity ([app.globus.org](https://app.globus.org)).
> 3. Allocation / project ID at the site (Slurm account, PBS project).
> 4. Knowledge of the scheduler (Slurm vs. PBS) and the site's recommended
>    conda or module setup.
> 5. Permission from your site to run long-lived user processes on a login
>    node (most sites allow it; some don't — check first).

Total: **~1 hour first time**, including hardening.

---

## What you're about to do

```text
  YOUR HPC ACCOUNT                                       USERS' LAPTOPS
  ┌─────────────────────────────────┐                    ┌──────────────┐
  │  globus-compute-endpoint        │                    │ uxarray-mcp  │
  │   start <name>                  │ ◀── Globus ─────── │  (with your  │
  │                                 │     Compute        │   endpoint   │
  │   spawns workers (Slurm/PBS)    │     HTTPS          │   UUID)      │
  │   that import uxarray, run      │                    │              │
  │   functions, return results     │                    │              │
  └─────────────────────────────────┘                    └──────────────┘
```

You are giving **arbitrary Python execution as your HPC user** to anyone in
the endpoint's Globus Auth allow-list. Do this with eyes open.

---

## Solo personal endpoint quickstart

If only **you** will submit to this endpoint, you can skip the service-account
ticket, the multi-user setup, and the function allowlist. The minimum viable
personal endpoint is six commands and one config edit.

**Prereqs:** shell on the HPC machine, a Globus identity, your project's
Slurm account or PBS project ID, and the site's conda/module convention.

```bash
# 1. On the HPC machine, in your account
module load conda                       # or whatever your site provides
conda create -n gce python=3.12 -c conda-forge -y
conda activate gce
pip install globus-compute-endpoint uxarray xarray netCDF4 h5netcdf

# 2. Configure the endpoint
globus-compute-endpoint configure uxarray
```

> **Pick the worker Python version deliberately.** Globus Compute serialization
> tolerates same-minor skew (e.g. 3.12.10 ↔ 3.12.13) but breaks across minor
> versions (3.12 ↔ 3.13). The packaged MCP tools route through
> `AllCodeStrategies` and survive minor differences for simple payloads, but
> raw `Executor.submit()` calls and any user code dropping down to the SDK
> directly will hit pickle protocol errors and `WorkerLost`. **uxarray-mcp
> pins to Python 3.12 today** ([globus/globus-compute#2139](https://github.com/globus/globus-compute/issues/2139)
> tracks the upstream fix that will let us broaden this). Stand up your
> endpoint on 3.12 and your submitter install will already match;
> `uxarray-mcp doctor` will surface a warning at probe time if anything is
> off.

Edit `~/.globus_compute/uxarray/config.yaml` and set the scheduler block.
Minimum diff from the generated template (PBS example shown — see Step 3
below for Slurm):

```yaml
display_name: uxarray
engine:
  type: GlobusComputeEngine
  provider:
    type: PBSProProvider
    queue: casper                       # or your site's queue
    account: YOUR_PROJECT_ID            # critical — without this, jobs reject
    nodes_per_block: 1
    init_blocks: 1
    min_blocks: 0
    max_blocks: 1
    walltime: "01:00:00"
    worker_init: |
      unset PYTHONPATH                  # critical — see Step 3 for why
      module load conda
      conda activate gce
```

Lock down the auth so only **your** Globus identity can submit (find your
identity UUID at <https://app.globus.org/account/identities>):

```yaml
authentication_policy:
  high_assurance: true                  # recent MFA required
  allowed_identities:
    - your-globus-identity-uuid
```

Then:

```bash
# 3. Start the endpoint (opens a browser tab for OAuth on first run)
globus-compute-endpoint start uxarray
# → registers and prints your endpoint UUID. Save it.

# 4. Lock down credential storage
chmod 700 ~/.globus_compute ~/.globus
```

**Test from your laptop:**

```bash
uxarray-mcp endpoints add mine <UUID> --path-prefix /glade/   # or /lcrc/, /gpfs/...
uxarray-mcp doctor --endpoint mine
```

If `doctor` reports `active`, you're done. Total time: ~30 min the first time.

**You should still do the full hardening eventually:**

- If anyone else will ever submit (collaborator, student, agent on a shared
  laptop) → migrate to a service account ([Step 1](#step-1--pick-the-user-account)).
- For long-running endpoints → add the function allowlist
  ([MEP allowlist](#mep-allowlist)) and the audit cron
  ([Step 7](#step-7--harden)).
- Rotate credentials every 90 days ([Day-2 ops](#day-2-operations)).

---

## The eight steps

1. [Pick the user account](#step-1--pick-the-user-account) — service or personal
2. [Install the endpoint daemon](#step-2--install-the-endpoint-daemon)
3. [Configure the endpoint](#step-3--configure-the-endpoint) (scheduler, worker init)
4. [Install the worker environment](#step-4--install-the-worker-environment)
5. [Start the endpoint and capture its UUID](#step-5--start-the-endpoint)
6. [Add the Globus Auth policy](#step-6--auth-policy) (who can submit)
7. [Harden the install](#step-7--harden)
8. [Distribute the UUID and test](#step-8--distribute-the-uuid-and-test)

---

### Step 1 — Pick the user account

You have two choices.

**Personal account** (you, `jain@anl.gov`).
- Easy: nothing new to request.
- **High blast radius:** your SSH keys, your shell history, your group
  memberships, your refresh tokens are all reachable from any submitted
  function.
- OK for: solo use, you're the only submitter, short-lived bring-up.

**Service account** (e.g., `svc_uxarray`).
- Requires a ticket to your HPC site. See template below.
- **Much lower blast radius:** no SSH keys, no personal data, scoped ACLs.
- OK for: any multi-user endpoint, anything left running long-term, any
  endpoint exposed to people outside your immediate group.

We recommend service accounts for anything not strictly experimental.

#### Service-account request template

```
To: <site-support@…>  (cce-help@anl.gov, help@ucar.edu, help@nersc.gov, …)
Subject: Service account for Globus Compute endpoint

Hi,

I'd like to request a service account to host a Globus Compute endpoint for
the uxarray-mcp project (https://github.com/UXARRAY/uxarray-mcp-server).

Requested name: svc_uxarray (or site convention)
Project / allocation: <your project ID>
Purpose: Long-running Globus Compute endpoint that executes UXarray analyses
         submitted by AI agents on behalf of authenticated users.

Requirements:
- No interactive shell login.
- No SSH keys provisioned.
- Read-only ACL on shared project data (/path/to/data) via setfacl.
- Write access to a scoped scratch directory only.
- Member of project group <group-id> for allocation accounting.
- Allocation cap: <e.g., N node-hours/month> with hard MaxJobs / MaxNodes.

I will be the responsible PI / sysadmin for this account and will rotate
its Globus credentials per site policy.

Thanks,
<your name, affiliation>
```

---

### Step 2 — Install the endpoint daemon

On the HPC machine, in the chosen account's home (or a project space if
home is small):

```bash
# Use the site's recommended conda or module first
module load conda    # or whatever your site provides

conda create -n gce python=3.12 -c conda-forge -y
conda activate gce
pip install globus-compute-endpoint
```

Verify:

```bash
globus-compute-endpoint --version
```

---

### Step 3 — Configure the endpoint

```bash
globus-compute-endpoint configure uxarray
```

This creates `~/.globus_compute/uxarray/`. Edit
`~/.globus_compute/uxarray/config.yaml` for your scheduler.

**Slurm example (LCRC Chrysalis, NERSC, etc.):**

```yaml
display_name: uxarray
engine:
  type: GlobusComputeEngine
  provider:
    type: SlurmProvider
    partition: debug
    account: <YOUR_PROJECT>
    nodes_per_block: 1
    init_blocks: 1
    min_blocks: 0
    max_blocks: 1
    walltime: "01:00:00"
    worker_init: |
      unset PYTHONPATH
      module load conda
      conda activate gce
```

**PBS example (NCAR Casper, Argonne Polaris):**

```yaml
display_name: uxarray
engine:
  type: GlobusComputeEngine
  provider:
    type: PBSProProvider
    queue: casper
    account: <YOUR_PROJECT>
    select_options: "ngpus=0"
    nodes_per_block: 1
    init_blocks: 1
    min_blocks: 0
    max_blocks: 1
    walltime: "01:00:00"
    worker_init: |
      unset PYTHONPATH
      module load conda
      conda activate gce
```

Critical lines:

- **`unset PYTHONPATH`** — prevents pydantic/dill version conflicts when
  the inherited path includes incompatible modules. Without this, you'll
  see `ImportError`s that look unrelated.
- **`account:`** — your Slurm account or PBS project. Without it, jobs
  reject silently.
- **`max_blocks:`** — caps concurrent worker jobs. Start at 1.

See [chrysalis.md](chrysalis.md), [improv.md](improv.md), and
[ucar.md](ucar.md) for worked configurations.

---

### Step 4 — Install the worker environment

The endpoint manager and the worker can use different environments. The
**worker** is what actually runs UXarray. It needs:

```bash
conda activate gce
pip install uxarray xarray netCDF4 h5netcdf
# Plus anything else you want the agent to have access to:
pip install matplotlib cartopy
```

> If the worker env is different from the manager env, set
> `worker_init` (Step 3) to activate the worker env.

Verify it imports:

```bash
python -c "import uxarray; print(uxarray.__version__)"
```

---

### Step 5 — Start the endpoint

```bash
globus-compute-endpoint start uxarray
```

First start opens a browser-based OAuth flow. On a headless login node,
copy the URL into a local browser. After approval, the endpoint registers
and you get a UUID:

```text
> Starting endpoint; registered with id: 79bf66fc-0507-42d0-a6bc-81628e9f1d77
```

**Save this UUID.** Distribute it (Step 8) only to authenticated submitters.

Check status:

```bash
globus-compute-endpoint list
globus-compute-endpoint logs uxarray
```

---

### Step 6 — Auth policy

Edit `~/.globus_compute/uxarray/config.yaml` and add (at the top level):

```yaml
allowed_functions:
  # Empty list = no allowlist; any function from authorized identities runs.
  # See "MEP allowlist" section below for the hardened version.
  []

authentication_policy:
  # Require recent MFA at the configured identity provider.
  high_assurance: true
  # Restrict to specific Globus identities (UUIDs):
  allowed_identities:
    - <your-globus-identity-uuid>
    - <collaborator-1-uuid>
  # OR restrict by identity provider domain:
  # allowed_domains:
  #   - anl.gov
  #   - ucar.edu
```

Restart:

```bash
globus-compute-endpoint restart uxarray
```

### MEP allowlist

For the strongest protection, convert to a **Multi-User Endpoint** with a
function allowlist. Pre-register the ~20 functions uxarray-mcp uses; the
endpoint rejects any submission whose SHA-256 hash isn't on the list.

```bash
globus-compute-endpoint configure-multi-user uxarray-mep
# Then in config.yaml:
allowed_functions:
  - <sha256-of-remote_analyze_dataset>
  - <sha256-of-remote_calculate_area>
  - <sha256-of-remote_inspect_mesh>
  # … one per registered function
```

The hashes come from running each function through
`globus_compute_sdk.Client().register_function()` once and recording the
returned function ID + hash. We will publish a script for this once MEP
support lands in uxarray-mcp; track <https://github.com/UXARRAY/uxarray-mcp-server/issues>.

This is the single biggest security win after running as a service account.

---

### Step 7 — Harden

Do all of these, in order:

```bash
# Lock down credential storage
chmod 700 ~/.globus_compute ~/.globus
chmod 600 ~/.globus_compute/storage.db 2>/dev/null

# Disable shell history (if running as a personal account)
echo 'unset HISTFILE' >> ~/.bashrc

# Restrict data write permissions
setfacl -R -m u:svc_uxarray:r-x /path/to/shared/data   # read-only on shared
setfacl -R -m u:svc_uxarray:rwx /scratch/svc_uxarray   # write only in scratch
```

Scheduler caps (ask your site admin):

```text
sacctmgr modify user svc_uxarray set MaxJobs=4 MaxWall=04:00:00
# PBS equivalents vary by site
```

Outbound network: if your site supports egress filtering or proxy logging,
route worker HTTPS through it. Most don't, but ask.

Set up a weekly audit:

```bash
# In cron, owned by you (not the service account):
0 9 * * 1 globus-compute-endpoint logs uxarray --tail 1000 | \
  mail -s "uxarray endpoint weekly log" you@example.com
```

---

### Step 8 — Distribute the UUID and test

Send users:

1. The endpoint UUID.
2. The path prefix(es) where data lives (e.g., `/glade/`).
3. A pointer to [remote-hpc.md](remote-hpc.md) for their setup.
4. A pointer to [SECURITY.md](https://github.com/UXARRAY/uxarray-mcp-server/blob/main/SECURITY.md) so they know what they're
   trusting.

**Distribute out-of-band** — Slack DM, email, lab wiki behind SSO. Not in
a public GitHub README.

Have them run:

```bash
uxarray-mcp endpoints add ucar <UUID> --path-prefix /glade/
uxarray-mcp doctor --endpoint ucar
```

If `doctor` reports `active`, you're done.

---

## Day-2 operations

### Rotating credentials

Every 90 days, or immediately after suspected compromise:

1. Stop the endpoint: `globus-compute-endpoint stop uxarray`.
2. Log out at <https://app.globus.org/account/consents> and revoke the
   consent for "Globus Compute Endpoint."
3. Delete `~/.globus_compute/storage.db`.
4. Restart: `globus-compute-endpoint start uxarray` (re-auths). **New UUID.**
5. Notify users of the new UUID.

### Monitoring

```bash
globus-compute-endpoint list                  # status of all endpoints
globus-compute-endpoint logs uxarray          # tail the daemon log
sacct -u svc_uxarray --starttime $(date -d '7 days ago' +%F)  # Slurm history
```

### Incident response

See [SECURITY.md § Incident response](https://github.com/UXARRAY/uxarray-mcp-server/blob/main/SECURITY.md#incident-response).

---

## Reference: site-specific configs

- [chrysalis.md](chrysalis.md) — Argonne Chrysalis (LCRC, Slurm)
- [improv.md](improv.md) — Argonne Improv (LCRC, PBS)
- [ucar.md](ucar.md) — NCAR Casper / Derecho (PBS)
- [remote-hpc.md](remote-hpc.md) — connecting to an existing endpoint (also
  covers the Globus Compute mental model: local machine / endpoint / worker)
