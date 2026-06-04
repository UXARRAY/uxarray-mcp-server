# Workflows

The repository now includes a first-class persisted workflow surface for
multi-step scientific runs:

- `manage_session(action="create", ...)`
- `manage_session(action="register_dataset", ...)`
- `run_workflow(...)`
- `resume_workflow(...)`
- `get_status(kind="workflow", ...)`
- `get_status(kind="operation", ...)`

Internally, the default workflow template is a deterministic sequence that runs:

1. `validate_hpc_setup`
2. `probe_path_access`
3. `inspect_mesh`
4. `inspect_variable`
5. `validate_dataset`
6. `calculate_area`
7. `calculate_zonal_mean` when a valid face-centered variable is available

Each workflow stores:

- workflow status and per-step state
- progress events
- a final result handle with a JSON artifact
- session-visible result and operation references when a `session_id` is used

## Recommended Usage

For repeated work across multiple datasets, create a session first:

```python
from uxarray_mcp.tools import create_session, register_dataset, run_workflow

session = create_session("baseline-analysis")
dataset = register_dataset(
    session["session_id"],
    grid_path="/path/to/grid.nc",
    data_path="/path/to/data.nc",
    name="baseline",
)

workflow = run_workflow(
    session_id=session["session_id"],
    dataset_handle=dataset["dataset_handle"],
    variable_name="temperature",
)
```

Then inspect it later:

```python
from uxarray_mcp.tools import get_workflow_status, get_result_handle

status = get_workflow_status(workflow["workflow_id"])
summary = get_result_handle(status["result_handle"])
```

## Relationship to the Example Script

The repository still includes:

```bash
uv run python scripts/agentic_hpc_loop.py \
  --grid-path /gpfs/fs1/home/<username>/path/to/grid.nc \
  --data-path /gpfs/fs1/home/<username>/path/to/data.nc \
  --poll-seconds 5 \
  --timeout-seconds 300
```

That script remains useful as a lower-level example of explicit remote polling
and branching. The new workflow tools are the supported persisted runtime for
the common probe → inspect → validate → analyze sequence.

## Current Scope

The first workflow implementation is intentionally narrow:

- one canonical workflow template
- JSON-backed local state
- explicit resume support
- stage-based progress events instead of percentage completion

This keeps the workflow layer predictable and makes it compose well with the
new session, comparison, remapping, and export tools.
