# `run_analysis` is a single tool with 38 parameters and 32 operations

## Problem

`src/uxarray_mcp/tools/frontdoor.py` exposes essentially the whole library
through one function. As of `de21d322`:

- **38 parameters** on `run_analysis`
- **32 operations** named in a **1210-character** docstring
- `get_capabilities` adds a further 2923-character description

Serialized, the two tools come to about **9,100 characters** of tool
specification sent on every request. The comparison condition in the study,
a plain file inspector plus a Python interpreter, was **619 characters**.

That 15x difference is not inherent to MCP. It is a consequence of this
design choice, and the paper says so explicitly rather than attributing the
overhead to the protocol.

## Why it matters beyond size

A tool this general cannot say anything specific about a particular call. It
cannot express that `calculate_zonal_mean` needs face-centered data while
`calculate_area` needs no data at all, because it has one signature for all 32
operations. Most of the 38 parameters are irrelevant to any given call
(`center_lon` and `outer_radius` mean nothing to `calculate_area`), so the
model must infer applicability from prose.

This also appears to drive issue 02: because the tool cannot describe the
specific call, it compensates by attaching a catalog of everything else it
could do.

## Evidence

Measured directly from the archived schemas:

```
persistent_generic  tools=[inspect_dataset, run_python]        schema =   619 chars
operation_only_mcp  tools=[get_capabilities, run_analysis]     schema = 9,100 chars
```

On the two easy control tasks the named-operation interface cost about
**3.2k and 3.8k more median tokens** than plain Python, for identical
scientific outcomes (20/20 either way). That is pure overhead on decisions
that were easy to begin with.

Note the honest counterweight: on the remap task the named operation was worth
it, taking 10/20 to 20/20 (`p = 4e-4`) and cutting median tokens for three of
four deployments. The problem is not having named operations. It is having one
name for everything.

## Suggested direction

Split the front door into a small number of tools whose schemas can be
specific, for example grouped by what they consume: mesh-only operations
(`calculate_area`, `inspect_mesh`), single-field operations
(`calculate_zonal_mean`, `gradient`), two-field operations (`curl`,
`divergence`, `bias`), and subsetting or export. Each gets only the parameters
it can use.

If the single entry point has to stay for compatibility, consider generating
per-operation schemas and advertising only the subset applicable to the dataset
currently in play.

Worth measuring after any change: serialized schema size, and whether
first-turn prompt tokens fall from the observed median of 2,000.
