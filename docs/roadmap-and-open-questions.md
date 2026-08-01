# Roadmap and open questions

Working memory for this server: what we intend to do, why, and what is
already filed. Update this rather than re-deriving context from scratch.

Last updated 2026-07-31.

## Where the work comes from

Three sources feed this list.

1. **The eScience 2026 evaluation** — a 480-run study that held six tasks and
   their inputs fixed and varied only what the server returned. Notes and
   provenance in [`issues-from-escience-study/`](issues-from-escience-study/).
2. **Reviewer feedback on that paper** — methodological criticism, most of it
   fair, and much of it pointing at server work rather than paper work. Logged
   below.
3. **Protocol movement** — MCP spec releases we do not control. See
   [`mcp-2026-07-28-assessment.md`](mcp-2026-07-28-assessment.md).

## Filed and open

| Issue | Title | Origin |
|---|---|---|
| [#89](https://github.com/UXARRAY/uxarray-mcp-server/issues/89) | `run_analysis` is a single tool with 38 parameters and 32 operations | study; root cause of #83 |
| [#88](https://github.com/UXARRAY/uxarray-mcp-server/issues/88) | No result-size budget or regression test | study |
| [#87](https://github.com/UXARRAY/uxarray-mcp-server/issues/87) | `scale_by_radius` default disagrees with the UXarray Python API | study |
| [#86](https://github.com/UXARRAY/uxarray-mcp-server/issues/86) | Warnings inform but never block | study; MRTR noted |
| [#85](https://github.com/UXARRAY/uxarray-mcp-server/issues/85) | Remapping returns confident numbers outside source coverage | study |
| [#84](https://github.com/UXARRAY/uxarray-mcp-server/issues/84) | Results cannot say whether anything was checked | study; the one measured win |
| [#83](https://github.com/UXARRAY/uxarray-mcp-server/issues/83) | A tool catalog is 74% of what the server sends back | study |
| [#67](https://github.com/UXARRAY/uxarray-mcp-server/issues/67) | Academy dashboard (agent observability) — deferred | earlier |
| [#90](https://github.com/UXARRAY/uxarray-mcp-server/issues/90) | Check block should be able to supply a reference without the verdict | review |
| [#91](https://github.com/UXARRAY/uxarray-mcp-server/issues/91) | Results have no declared shape a caller can validate against | review |
| [#92](https://github.com/UXARRAY/uxarray-mcp-server/issues/92) | Test fixtures have no physical radius, vertical coordinate, or mask | review |
| [#93](https://github.com/UXARRAY/uxarray-mcp-server/issues/93) | No eval for multi-turn behavior: handles, chaining, and recovery | review |

Upstream, blocking us:

- [Oaklight/toolregistry-server#54](https://github.com/Oaklight/toolregistry-server/issues/54)
  — `mcp` 2.0.0 breaks the MCP adapter. Until this lands we cannot reach spec
  `2026-07-28`, so MRTR (#86) and cacheable list results are unavailable.

## Reviewer feedback, and what we do about it

Six criticisms were raised. They are recorded here in full because several are
correct and actionable, and because the ones that are *not* server work should
not be re-argued later.

### 1. The "copying" loophole in the check block

> The `+check` interface returned both the residual and the verdict, so the
> model parsed JSON and echoed an answer rather than verifying anything.

**Correct, and the paper already says so** — it bounds the claim to
"performing that arithmetic on the server removes an error models make
reliably," not "models learned to verify." But the reviewer is right that the
experiment cannot separate copying from checking, because we never ran the
condition that would.

**Server implication:** the check block should be able to supply the reference
and tolerance *without* the verdict, so a deployment can require the model to
do the comparison. That is a real product decision, not just an experimental
one: a server that always hands over the verdict trains callers to trust it
blindly. Filed as #90, against the #84 design.

### 2. Confounded baseline (Write-the-code vs Named operation)

> The comparison changed at least five variables at once: prompt length 619 →
> 9,100 characters, tool names, constrained action space. The gain cannot be
> attributed to MCP.

**Correct, and the paper states this explicitly** in both the results and the
limitations. No change of position needed.

**Server implication:** none directly. It is an experimental-design point, and
the honest answer is that a clean decomposition needs new runs, not new server
code. Noted so it is not mistaken for an open engineering task.

### 3. Self-inflicted payload overhead

> The 74% tool catalog is a consequence of exposing everything through one
> monolithic `run_analysis`. Atomic tools would eliminate it.

**Correct, and we agree so strongly it is already two issues** — #89 (the
monolith) and #83 (the catalog it forces). The paper also says the cause is
ours. This is the single highest-value piece of server work on the list.

### 4. Scoring sensitivity

> Significance depends on a reviewed scoring pass that forgave JSON formatting
> for 119 of 480 runs. Under strict scoring the area result is p=0.20.

**Correct, and disclosed** — the paper has a section on exactly where the two
scorings disagree, and ships both.

**Server implication, and this is the useful part:** most of those 119 runs
failed on *output format*, not on science. Five of the seven disputed area
runs were one model emitting bare JSON. A server that stated its expected
result shape in a machine-checkable way — and validated against it — would
have removed most of that ambiguity. Filed as #91.

### 5. Adversarial and synthetic fixtures

> A 195-cell regional mesh, a 4-cell toy mesh, and an idealized R=1 unit
> sphere do not reflect production Earth-system models: no vertical
> coordinates, no physical radii, no staggered masks.

**Correct, and listed in the paper's limitations.** But it is also a genuine
gap in the *server's* test coverage, not only the study's. We have
`scale_by_radius` problems (#87) precisely because the unit sphere hid them.

**Server implication:** we need fixtures with a physical Earth radius, at
least one vertical coordinate, and a mask. Filed as #92.

### 6. Single-turn execution

> The median run used one or two tool calls. This does not test multi-step
> planning, state persistence, cross-tool coordination, or error recovery.

**Correct.** We ship `create_session`, `dataset_handle`, `result_handle`,
`run_workflow`, and `resume_workflow`, and the study exercised almost none of
it. There are unit tests for the stateful tools, but no eval that measures
whether a model can actually carry a handle across several calls and recover
from a failure.

**Server implication:** a multi-turn eval belongs in `evals/`. Filed as #93.

## What we intend to build, in rough order

1. **Split `run_analysis`** (#89). Everything else about payload size follows
   from this.
2. **Check block with an optional verdict** (#90), so the server can supply
   reference and tolerance while leaving the comparison to the caller.
3. **Declared result shape** the caller can validate against (#91),
   addressing the format-versus-science confound in item 4.
4. **Realistic fixtures** — physical radius, vertical coordinate, mask (#92).
5. **Multi-turn eval** in `evals/` covering handles, chaining, and recovery (#93).
6. **Precondition enforcement** (#86), designed so it can surface as a refusal
   now and as MRTR `input_required` once the SDK allows.
7. **Result-size budget in CI** (#88) so payloads cannot grow back.

## Explicitly not doing

- Re-running the eScience study to decompose the confounded baseline. It would
  be a new experiment, and the paper already declines to attribute that
  comparison to MCP.
- Forking the `mcp` SDK to reach spec 2026-07-28 early.
- Rewriting session handling to be "stateless" — we already mint explicit
  handles, which is what the new spec recommends.
