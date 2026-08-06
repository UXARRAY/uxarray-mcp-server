# No result-size budget or regression test

## Problem

Nothing in the test suite constrains how large a result payload may be, or what
fraction of it is the actual answer. The bloat described in issue 02 accumulated
without anyone noticing, because every individual addition looked reasonable.

If issues 01 and 02 are fixed and nothing guards them, the payload will grow
back the same way.

## Why a budget is the right tool

Payload size is not a cosmetic concern here. Everything the server returns is
added to the conversation and re-sent on every later turn, so a verbose result
is paid for repeatedly. The study measured this directly: enriched results added
a paired median of **+2,078 tokens** per run over plain results, and increased
demand in **111 of 120** matched cells, with no scientific improvement to show
for it.

There is a useful contrast in the same data. The verification block that *did*
change an outcome was **257 bytes**. The description block that changed nothing
was roughly twenty times larger. Size is not the enemy; unfocused size is.

## Suggested direction

Add tests that treat the shape of a result as an interface contract:

- Assert an upper bound on serialized bytes for a representative result from
  each operation family.
- Assert a lower bound on the **signal fraction**: computed values plus status
  divided by total payload. The study's enriched results were at roughly 2%;
  something like 50% would be a defensible floor.
- Assert that discovery-only keys such as `mcp_server_tools` and
  `uxarray_capabilities` do not appear in analysis results at all.
- Assert that the serialized tool specification stays under a stated size, so
  regressions of issue 01 are caught too.

These should fail loudly with the measured number in the message, since the
useful part is knowing what it grew to.

## Related

A broader point from the evaluation-methodology literature, which the paper
cites: agent evaluations tend to report accuracy and ignore cost. The same
applies to servers. If the project ever adds a benchmark, recording tokens
alongside correctness would make regressions like this visible earlier.
