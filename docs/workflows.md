# Agentic HPC Workflows

Once a remote endpoint is healthy, you can run more than one isolated tool call.
The repository now supports a straightforward sequential workflow:

1. Submit a remote probe.
2. Poll until it finishes.
3. Use that result to decide the next job.
4. Repeat.

## What Is Possible Today

This is already possible with the current Globus Compute integration because the
remote compute functions are serializable and the endpoint can execute them one
after another.

The repository includes an example:

```bash
uv run python scripts/agentic_hpc_loop.py \
  --grid-path /gpfs/fs1/home/<username>/path/to/grid.nc \
  --data-path /gpfs/fs1/home/<username>/path/to/data.nc \
  --poll-seconds 5 \
  --timeout-seconds 300
```

This script does the following:

1. Submit `remote_runtime_probe`
2. Poll until the worker responds
3. Submit `remote_probe_path` for the grid path
4. Submit `remote_probe_path` for the data path
5. Submit `remote_inspect_mesh`
6. Submit `remote_inspect_variable`
7. Select the first face-centered variable if none was provided
8. Submit `remote_calculate_area`
9. Submit `remote_calculate_zonal_mean` when applicable

## Why This Matters

This is the pattern you need for longer scientific workflows:

- probe the environment first
- submit the smallest safe job
- inspect the result
- branch to the next computation based on that result

That pattern is more robust than trying to jump directly to a large autonomous
run on a brand-new cluster.

## What Is Still Missing

The current MCP tools are synchronous wrappers around remote jobs. They work
well for one tool call at a time, but they do not yet expose a first-class
multi-step remote workflow engine with persisted state, retries, or background
job orchestration.

The next product step would be a higher-level workflow tool or agent that can:

- persist remote task state
- retry failed stages selectively
- branch on validation results
- collect structured artifacts across multiple remote jobs

The example script in `scripts/agentic_hpc_loop.py` is the first building block.
