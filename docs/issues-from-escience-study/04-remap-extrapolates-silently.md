# Remapping returns confident numbers outside source coverage

## Problem

`remap_to_rectilinear` will happily return a value at every requested target
point even when the target lies entirely outside the source mesh. There is no
coverage check anywhere in the remap path — grepping `src/uxarray_mcp/` for
`coverage` or `extrapolat` finds only unrelated matches in `plotting.py`.

This is the failure mode a scientific interface most needs to catch, because
nothing about the output looks wrong.

## Evidence

The study's remap fixture is deliberately adversarial. The source is a 195-cell
regional mesh spanning roughly 43-47 degrees E and plus/minus 2 degrees
latitude. The request asks for a global 5x5 lon/lat target.

**Zero of the 25 target points fall inside the source mesh bounding box.**
Nearest-neighbor remapping returned a value at all 25 anyway, with plausible
statistics: min 0.138, max 0.159, mean 0.146. Every MCP run reproduced these
numbers exactly and reported them as the answer.

The study scored this task on invocation only and stated in print that the
returned field is scientifically meaningless. That is a workaround for an
evaluation, not an acceptable property of a server.

A second issue compounds it: nearest-neighbor is **not conservative**, so even
with full coverage the result would be unsuitable for any flux quantity. Nothing
in the response says this.

## Suggested direction

At minimum, compute what fraction of target points fall within the source mesh
and return it. A result carrying `points_in_source: 0/25` is impossible to
misread, and it is cheap: a bounding-box test first, then a point-in-cell test
only for points that pass.

Beyond that:

- Emit a stable warning code when coverage is partial, and a distinct one when
  it is zero.
- State the remap method's conservation property in the result, so a model
  choosing between nearest-neighbor and a conservative scheme has the
  information in front of it.
- Consider returning masked or null values outside coverage rather than
  extrapolated ones, or at minimum make that an option that defaults to safe.

This connects to issue 05: coverage of zero is arguably a case where the server
should refuse rather than warn.
