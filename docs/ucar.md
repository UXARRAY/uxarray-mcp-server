# UCAR/Casper Endpoint

Casper is an NCAR data analysis cluster on the GLADE filesystem.

Official system information: [Casper system page](https://arc.ucar.edu/knowledge_base/70549913).

## Key Points

- The **MCP server does not need to be cloned on Casper** — remote functions are
  sent as source code via `AllCodeStrategies`.
- YAC is available via a pre-built activate script and enables conservative
  remapping on the worker.
- The conda `uxarray_dev` env is the worker environment — `globus-compute-endpoint`
  lives in a separate venv layered on top.

## Worker Environment

| Item | Value |
|---|---|
| Conda env | `/glade/work/<user>/conda-envs/uxarray_dev` |
| YAC activate | `~/opt/yac-core-v3.14.0_p1/activate-yac.sh` |
| Endpoint name | `ucar-uxarray-yac` |
| Modules | `ncarenv/24.12`, `gcc/12.4.0`, `openmpi/5.0.6`, `conda` |

## First-Time Setup

```bash
# 1. Load modules (add to ~/.bashrc or run manually each login)
module purge
module load ncarenv/24.12 gcc/12.4.0 openmpi/5.0.6 conda

# 2. Configure the endpoint
scripts/ucar_endpoint.sh configure

# 3. Start
scripts/ucar_endpoint.sh start
```

## Starting the Endpoint

```bash
# In a tmux session on a Casper login node:
scripts/ucar_endpoint.sh start
```

The script loads modules, activates the conda env, checks YAC, and starts the
endpoint inside a tmux session named `uxarray-endpoint`.

To reattach: `tmux attach -t uxarray-endpoint`
To restart: `scripts/ucar_endpoint.sh restart`
To check: `scripts/ucar_endpoint.sh status`

Add the UUID to your local config:

```bash
uxarray-mcp endpoints add ucar <uuid>
```

## Validation

```bash
uv run python scripts/hpc_doctor.py --endpoint ucar --timeout-seconds 120
```

Or with a real GLADE path:

```bash
uv run python scripts/hpc_doctor.py \
    --endpoint ucar \
    --sample-path /glade/work/<user>/your_mesh_file.nc
```

## YAC Remapping

YAC is pre-built and activated by `activate-yac.sh`. To verify it works on the
worker:

```bash
uv run python scripts/yac_smoke_test.py --endpoint ucar
```

## Troubleshooting

**`endpoint not ready` immediately after start** — modules not loaded before
starting. The `ucar_endpoint.sh start` command loads them automatically; if
starting manually, ensure `module load ncarenv/24.12 gcc/12.4.0 openmpi/5.0.6 conda`
is run first.

**YAC import fails on worker** — the `activate-yac.sh` path may have changed.
Check `~/opt/` for the current YAC build and update `YAC_ACTIVATE` in
`ucar_endpoint.sh`.

**`validate_hpc_setup` passes but YAC tools fail** — run `yac_smoke_test.py`
to verify YAC is importable on the compute worker specifically.
