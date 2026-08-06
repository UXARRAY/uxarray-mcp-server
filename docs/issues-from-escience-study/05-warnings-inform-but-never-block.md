# Warnings inform but never block

## Problem

The server can detect that two arrays are unsuitable as physical vector
components and then compute the curl of them anyway. In the study's vector task
it returned `VECTOR_COMPONENTS_UNVERIFIED` and produced a number in the same
response.

A warning that does not stop the next step is advice. Stronger models took it;
weaker ones did not.

## Evidence

The fixture gives two pairs of arrays that are **byte-identical**.
`component_x` equals `vector_u` and `component_y` equals `vector_v`. Only the
second pair carries `eastward_sea_water_velocity` and
`northward_sea_water_velocity` standard names with `m s-1` units. A model
reasoning from the numbers alone cannot distinguish them; it has to read the
metadata and act on it.

Outcomes were flat across every interface: 9/20 writing code, 10/20 with the
named operation, 10/20 with the enriched result. Adding more warning text did
not change behavior (`p = 1.0`). GPT-5.4 Nano and Gemma repeatedly called curl
on the unlabeled pair, or omitted radius scaling, or both.

Two observations follow. Detection is not the gap — the server already knows.
And more description does not close it, which is consistent with issue 02.

## Suggested direction

Let the server declare preconditions that a client can enforce, and make
violation refusable rather than merely reported.

A workable shape:

- Operations declare preconditions as data, not prose. For `curl` computing
  physical vorticity: both components carry velocity-like units, direction
  identity is resolvable from `standard_name` or `long_name`, and radius scaling
  is enabled.
- When a precondition fails, the default is to **refuse and return the reason**,
  with an explicit override for a caller who genuinely wants the unphysical
  number.
- After a refusal, return only the repair actions that would make the call
  valid, so a model has a bounded set of next steps instead of free rein.

The same machinery covers the validation case. In the study, models correctly
stopped after a failed validation, but they stopped because the prompt told them
to, not because anything prevented them from continuing. All 80 runs did the
right thing here, so this is not urgent — but the safety came from the prompt,
which will not always be there.

Note that `not_evaluated` from issue 03 and precondition failure are different
states and should stay distinct: one is "we did not check," the other is "we
checked and it fails."
