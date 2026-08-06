# `scale_by_radius` default disagrees with the UXarray Python API

## Problem

The same conceptual call gives two different physical answers depending on which
interface a user goes through.

In `src/uxarray_mcp/tools/frontdoor.py:67` and
`src/uxarray_mcp/domain/vector_calc.py:158,247`:

```python
scale_by_radius: bool = False,
```

and the docstring states this plainly:

> ``gradient`` and ``curl`` accept ``scale_by_radius`` (default False keeps the
> historical unit-sphere result).

The UXarray Python accessor documents the opposite default. So a caller writing
`uxds["u"].curl(uxds["v"])` gets a radius-scaled result, while a caller asking
this server for `curl` gets a unit-sphere derivative unless they know to pass
the flag.

For anything meant to be physical relative vorticity, that is a difference of
roughly a factor of the Earth's radius.

## Evidence

This surfaced as a genuine confound in the study and had to be disclosed in the
paper. Every MCP run that was scored correct set the flag explicitly; every
Nano and Gemma failure either omitted it or called the unsupported pair. Because
the two interfaces default differently, part of what the vector row measured was
our own inconsistency rather than model behavior.

The comment at `vector_calc.py:15` shows the risk was already understood:

> know about to trust a result -- e.g. ``scale_by_radius=True`` silently ...

## Suggested direction

Options, roughly in order of preference:

1. **Match the library default.** Least surprising for anyone who knows
   UXarray, and makes the physical answer the default rather than the
   opt-in. Requires a changelog entry and a version note, since it changes
   results for existing callers.
2. **Require it explicitly** for `curl` and `gradient` with no default, so the
   caller must state intent. Safe, slightly more friction.
3. **Keep the default but return it prominently**, alongside a statement of
   what the result means physically. Weakest option: the study suggests
   descriptive text alone does not change behavior.

Whichever is chosen, the returned result should state the effective value and
its physical consequence, and the parameter description should mention that it
differs from, or matches, the Python API.

Worth checking whether any other parameter defaults diverge from the library in
the same way.
