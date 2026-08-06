# A tool catalog is 74% of what the server sends back

## Problem

This is the study's clearest finding about the server, and it was a surprise to
us. We added status, warnings, advice, and provenance to results expecting it to
help models make better scientific decisions. It did not help at all on the task
it was designed for. When we measured what we had actually been sending, the
reason was obvious.

Summing serialized bytes per top-level key across all 120 runs of the enriched
condition:

| What we actually sent | Share |
|---|---|
| `mcp_server_tools` | 25.9% |
| `variables` | 24.2% |
| `_provenance` | 16.2% |
| `recommended_next_steps` | 13.8% |
| `uxarray_capabilities` | 8.1% |
| `recommendations` | 3.5% |
| `scientific_status` | **1.9%** |
| `postconditions` | 1.8% |
| everything else, including the computed numbers | ~4.6% |

Grouped: **74.1% is a catalog of other tools and capabilities**, 16.2% is a
provenance record, 7.5% is status and warnings, and **2.2% is the actual
result**.

On the vector-suitability task the field that settles the scientific question,
`scientific_status`, was **100 bytes inside a 2,172-byte reply — 4.6%**.

## Effect

The enriched results roughly doubled that task's median token use, from about
14.0k to 28.6k, and changed the outcome not at all: 10/20 with and without,
Fisher exact `p = 1.0`. This is a real null, not an underpowered one.

The correct reading is not that scientific evidence is useless. It is that a
decisive signal at 2% of the payload, surrounded by a tool catalog, does not
change behavior.

## Where it comes from

`src/uxarray_mcp/tools/capabilities.py` builds `mcp_server_tools`,
`uxarray_capabilities`, `recommended_next_steps`, and `endpoint_profiles`. These
are useful once, during discovery. They are attached to results that a model has
already decided to request, and then re-sent on every subsequent turn because
the conversation carries them forward.

## Suggested direction

Separate discovery from results. A result should describe *that result*.

- Keep `get_capabilities` as the discovery call, and let it be as verbose as it
  needs to be, since it is called once.
- Remove `mcp_server_tools`, `uxarray_capabilities`, `recommended_next_steps`,
  and `endpoint_profiles` from analysis results entirely.
- Consider putting `_provenance` behind a handle. It is 16% and is rarely what
  the model needs for its next decision, though it does matter for the
  scientific record, so this needs thought rather than deletion.
- Keep `variables` only when the operation is an inspection.

A rough target: the computed numbers plus status should be the majority of a
result payload, not 4%.
