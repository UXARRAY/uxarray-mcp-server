# Results cannot say whether anything was checked

## Problem

Nothing in `src/uxarray_mcp/` currently distinguishes "this ran successfully"
from "this answer was compared against something known." Grep for
`postconditions`, `not_evaluated`, or `scientific_status` in `src/` and there
are no hits. Those fields existed only in the experiment patch
(`uxarray_mcp_frontdoor_v3.patch`) and were never merged.

This matters because it is the one change in the study that produced a
measurable improvement.

## Evidence

The area task asked models to compute a closed mesh's total area and say whether
it matched the analytic value. Every interface computed the identical number,
`12.566370614678554`, against `4*pi = 12.566370614359172`, a true error of
`3.19e-10` and well inside the `1e-9` tolerance. The task was to *say so*.

Without a check block, models got the arithmetic wrong in ways that are easy to
reproduce:

- All ten Gemma runs under both MCP variants reported an error of
  `3.19e-11` — exactly ten times too small, contradicting the two numbers they
  had just printed themselves.
- GPT-5.5 sometimes omitted the tolerance or the verdict.
- Four Gemma runs writing their own code summed flat triangles between mesh
  vertices instead of spherical areas, returning `12.5590730782`, wrong by
  `7.3e-3`.

Adding a block stating the reference, residual, tolerance, and verdict took the
task from **11/20 to 20/20**, Fisher exact `p = 1.2e-3`, surviving Bonferroni
correction across all eight contrasts tested. Every deployment went to 5/5;
Gemma went from 0/5 to 5/5.

## Two honest caveats

**The block is generous.** The prompt asked for five fields and the block
supplied four of them outright, including the pass/fail verdict. A model can
succeed by copying rather than by checking. So the demonstrated finding is that
*doing the comparison on the server removes a class of arithmetic error models
reliably make*, which is weaker than "models learned to verify" but is still a
good reason to build it.

**Under the strict scorer this result is not significant** (8/20 vs 13/20,
`p = 0.20`). The seven disputed runs all report the five requested numbers
correctly and are rejected only on JSON formatting, five of them Gemma, which
emitted bare JSON in 0 of 120 runs. We think the lenient reading is right, but
it should be known.

## Suggested direction

Two separable pieces.

**The cheap one, worth doing regardless.** Every analysis result should carry a
field that says whether a postcondition was evaluated, even when the answer is
"no." An explicit `not_evaluated` costs almost nothing and stops a model
implying more confidence than the computation supports. Four of the study's six
tasks had no independent answer available, and saying so plainly is the right
behavior.

**The valuable one.** Where a genuine invariant exists, evaluate it server-side
and return reference, residual, tolerance, and verdict. Candidates that already
have known answers:

- total area of a closed mesh equals `4*pi*R^2`
- `curl(grad(phi))` is zero to discretization error
- face areas sum to the global area
- conservative remap preserves the area-weighted integral

`scripts/analytic_validation.py` already computes residuals of this kind offline
for manufactured solutions. It is not reachable from the server. Wiring that
logic into the result path is most of the work.

Be careful not to reintroduce issue 02: the check block that worked was **257
bytes**. Keep it that size.
