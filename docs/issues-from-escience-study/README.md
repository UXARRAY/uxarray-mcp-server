# Server improvements suggested by the eScience 2026 evaluation

These notes come out of a 480-run study of this server, described in
*Beyond Tool Execution: Evaluating Scientific MCP Interfaces with UXarray*.
The study held six tasks and their input files fixed and varied only what the
server returned to the model. Two results are worth acting on:

- Adding one block that compared a computed area against the analytic value
  `4*pi` took that task from 11/20 correct to 20/20 (Fisher exact,
  `p = 1.2e-3`). Nothing else changed.
- Adding a roughly twenty-times-larger block of status text, warnings, advice,
  and provenance changed nothing on the task it was meant to help
  (10/20 both with and without, `p = 1.0`). Measuring what we had actually
  shipped explained why: **74% of those bytes were a catalog of other tools**,
  provenance was 16%, status and warnings 7.5%, and the computed numbers 2.2%.
  The single field that settled the scientific question was 4.6% of that reply.

The evaluation used the server at commit `de21d322` plus
`uxarray_mcp_frontdoor_v3.patch`, which added `scientific_status` and
`postconditions` to `run_analysis` results. **That patch was never merged.**
Several issues below are therefore about landing, in a better form, behavior
that only ever existed in the experiment.

Each file states the problem, the evidence, and a suggested direction. They are
written to be pasted into GitHub issues; nothing here is a committed design.

Filed upstream on 2026-07-31. The issue text is generic and does not cite the
paper; these local files keep the study provenance.

| Issue | Title | Why it matters |
|---|---|---|
| [#89](https://github.com/UXARRAY/uxarray-mcp-server/issues/89) | `run_analysis` is a single tool with 38 parameters and 32 operations | Root cause of the schema and catalog bloat below |
| [#83](https://github.com/UXARRAY/uxarray-mcp-server/issues/83) | A tool catalog is 74% of what the server sends back | 74% of the evidence payload, with no measured benefit |
| [#84](https://github.com/UXARRAY/uxarray-mcp-server/issues/84) | Results cannot say whether anything was checked | The one change that produced a measured improvement |
| [#85](https://github.com/UXARRAY/uxarray-mcp-server/issues/85) | Remapping returns confident numbers outside source coverage | Returns confident numbers with no scientific meaning |
| [#86](https://github.com/UXARRAY/uxarray-mcp-server/issues/86) | Warnings inform but never block | Weaker models ignored `VECTOR_COMPONENTS_UNVERIFIED` and computed anyway |
| [#87](https://github.com/UXARRAY/uxarray-mcp-server/issues/87) | `scale_by_radius` default disagrees with the UXarray Python API | Same call, two interfaces, two different physical answers |
| [#88](https://github.com/UXARRAY/uxarray-mcp-server/issues/88) | No result-size budget or regression test | Nothing stops payloads growing back |

## Reproducing the measurements

The evidence archive is a separate repository containing all 480 runs, both
scorings, and scripts that regenerate every number:
`https://github.com/rajeeja/artifacts_escience_2026_uxarray_mcp`

The payload-composition percentages come from summing serialized bytes per
top-level key across the 120 runs of the `semantic_mcp` condition. Every reply
in all 480 runs is text: no run returned an encoded image, a mesh, or a raw
array, so those percentages are shares of a JSON payload and would not carry
over to a server whose tools return binary artifacts.

All runs used MCP spec `2025-11-25`, via `mcp` 1.27.1. Spec `2026-07-28`
postdates the study and changes none of its conclusions, which are about what a
result body contains rather than how the protocol frames it. Two of its
features do bear on the issues above, and
[../mcp-2026-07-28-assessment.md](../mcp-2026-07-28-assessment.md) works
through them: cacheable `tools/list` results weaken the argument for repeating
catalog material inside results (#83), and Multi Round-Trip Requests give a
server a way to halt a call pending acknowledgment rather than warning and
computing anyway (#86).

```{toctree}
:hidden:
:maxdepth: 1

01-run-analysis-is-too-general
02-capability-catalog-dominates-every-reply
03-results-cannot-say-whether-anything-was-checked
04-remap-extrapolates-silently
05-warnings-inform-but-never-block
06-scale-by-radius-default-disagrees-with-uxarray
07-no-result-size-budget
```
