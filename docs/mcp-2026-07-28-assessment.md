# MCP 2026-07-28: where we stand and what to do

Spec: <https://modelcontextprotocol.io/specification/2026-07-28>
Release notes: <https://blog.modelcontextprotocol.io/posts/2026-07-28/>
Anthropic rollout: <https://claude.com/blog/bringing-mcp-2026-07-28-to-claude>

Written 2026-07-31. Everything below was checked against the installed
dependency tree and the published 2.0.0 wheel, not inferred from documentation.

## Do we have access to this version?

No, and not by choice. We ship whatever protocol version our SDK implements.

```
uxarray-mcp
  └── toolregistry-server[mcp] >= 0.4.0
        └── mcp >= 1.20, < 2          (we cap it; see below)
              └── resolved to 1.27.1  (uv.lock)
```

At `mcp` 1.27.1, verified at runtime:

| Constant | Value |
|---|---|
| `LATEST_PROTOCOL_VERSION` | `2025-11-25` |
| `DEFAULT_NEGOTIATED_VERSION` | `2025-03-26` |
| `SUPPORTED_PROTOCOL_VERSIONS` | `2024-11-05`, `2025-03-26`, `2025-06-18`, `2025-11-25` |

So we speak **2025-11-25** at best. `2026-07-28` is not in that list. This is
expected rather than neglectful: 1.27.1 was published 2026-05-08, the spec
landed 2026-07-28.

## Who decides our version?

Three parties, and we are the least of them.

1. **The MCP maintainers** set the spec and the Tier 1 SDKs. `mcp` 2.0.0 was
   published 2026-07-28, the same day as the spec.
2. **`toolregistry-server` (Oaklight)** decides which `mcp` our stack can use.
   Its current release, 0.4.2 (2026-07-16), predates the spec and declares only
   `mcp>=1.8.0`, with no upper bound. **This is the real gate.**
3. **Us.** We never import `mcp` in library code — there are no `mcp.*` imports
   anywhere under `src/`; servers are built through `route_table_to_mcp_server`.
   Our only lever is the version range in `pyproject.toml`. There is no seam
   where we could set a protocol version even if we wanted to.

The practical answer: **upstream `toolregistry-server` decides, and it has not
moved yet.** We already pin `mcp>=1.20,<2` so this cannot change under us
without a deliberate edit.

## Why the cap has to stay for now

Because `toolregistry-server` leaves `mcp` unbounded, an unpinned refresh
resolves to 2.0.0. That was tested directly: removing the cap and re-locking
selects `mcp 2.0.0`. Inspecting that wheel shows why it breaks us.

- **`mcp/types.py` no longer exists.** Types moved to a separate distribution,
  `mcp-types==2.0.0`. `toolregistry_server/adapters/mcp/adapter.py` imports
  `from mcp.types import INTERNAL_ERROR, ErrorData, TextContent, Tool`, which
  fails outright.
- `McpError` was renamed `MCPError` (already noted in our `pyproject.toml`).
- `mcp/server/lowlevel`, `mcp/shared/exceptions`, `mcp/server/auth/provider`
  and `mcp/server/streamable_http_manager` do still exist, so this is a hard
  break but a narrow one, not a rewrite.
- 2.0.0 also swaps `httpx` for `httpx2` and adds an OpenTelemetry dependency.

Lifting the cap is blocked on upstream, not on us.

## What the new spec actually changes for a server like ours

Most headline items do not touch us. We run stdio by default; the CLI also
offers `sse` and `http`.

| Change | Relevance to this server |
|---|---|
| Stateless core, no `initialize` handshake or `Mcp-Session-Id` | Low for stdio. Matters only if we deploy the HTTP transport for real. Note `scripts/check_mcp_handshake.py` calls `session.initialize()`, which the new spec retires; that script needs revisiting at upgrade time. |
| Explicit handles instead of transport session state | **Already how we work.** `create_session` mints `session_id`; tools take `dataset_handle` / `result_handle`. The spec now recommends exactly this. Nothing to change. |
| `Mcp-Method` / `Mcp-Name` routing headers | SDK-level. Free when the SDK updates. |
| **Cacheable list results (`ttlMs`, `cacheScope`)** | **Directly relevant.** See below. |
| MRTR (`resultType: "input_required"`) | Relevant to issue #86. See below. |
| Auth hardening (RFC 9207, CIMD over DCR) | Not applicable; no OAuth deployment. |
| Tasks extension | Plausible future fit for long HPC submissions; not now. |
| Roots, Sampling, Logging deprecated; HTTP+SSE deprecated | We should stop advertising `--transport sse` eventually. Twelve-month window. |

### Two items intersect the eScience findings

**Cacheable list results vs. issue #83 (catalog is 74% of the payload).**

This needs care, because it is easy to overclaim. `ttlMs` and `cacheScope`
apply to `tools/list` responses — the *catalog listing*. The 74% measured in the
study was a capability catalog embedded in **`tools/call` result bodies**, which
we put there ourselves. Caching `tools/list` does not remove one byte of that.

So the spec does not fix #83. What it does is remove any remaining excuse for
repeating catalog material inside results "so the model does not forget what
else exists": the client can now cache the real catalog with a server-supplied
TTL. That strengthens the case for #83 without doing the work.

**MRTR vs. issue #86 (warnings inform but never block).**

Issue #86 wants a precondition that stops the call rather than warning and
computing anyway. Today the options are return-a-warning or raise. MRTR adds a
third: return `resultType: "input_required"`, state what is unverified, and
require the caller to return an explicit acknowledgment. That is much closer to
what #86 asks for than anything in 2025-11-25.

Worth recording on #86 now and building later; it is unreachable until the SDK
path exists.

## Plan

### Now, in this repository

1. ~~Cap the transitive `mcp` dependency.~~ **Already done** in `90c4380`
   (`mcp>=1.20,<2`). Keep it, and keep the comment explaining why.
2. **Record the protocol version we actually speak.** Nothing in the repo said
   `2025-11-25`. Reviewers of the eScience artifact will ask which spec the 480
   runs used. Added to the README alongside this document.
3. ~~Note on issue #86 that MRTR is the intended mechanism.~~ **Added**, with
   the caveat that the precondition data model should be designed to surface
   either as a refusal now or as `input_required` later.

### Upstream, not ours to merge

4. ~~Open a tracking issue on `Oaklight/toolregistry-server`.~~ **Filed** as
   [Oaklight/toolregistry-server#54](https://github.com/Oaklight/toolregistry-server/issues/54):
   `adapters/mcp/adapter.py` imports `mcp.types`, which 2.0.0 removes, and the
   unbounded `mcp>=1.8.0` means downstreams hit it on a routine lock refresh.
   Suggests an upper bound as the interim fix.

### When upstream lands support

5. Re-lock; run `tests/` and `scripts/check_mcp_handshake.py`; confirm the
   negotiated version is `2026-07-28`.
6. Rework `check_mcp_handshake.py`, which asserts an `initialize` exchange the
   new spec removes.
7. Reconsider `--transport sse` given the deprecation.
8. Evaluate the Tasks extension for long-running HPC submissions.
9. Revisit #86 with MRTR available.

### Explicitly not doing

- Vendoring or forking `mcp` to reach 2.0.0 early. The gain is protocol
  cosmetics; the cost is owning an SDK fork.
- Rewriting session handling to be "stateless." We already mint explicit
  handles, which is what the spec now recommends.

## Effect on the eScience paper

None on the results. The study varied *what the server returned*, not how the
protocol framed it, and every condition ran on the same protocol version. The
claim is about payload design and is version-independent.

One factual addition is worth making: the paper and artifact should state which
spec version the runs used, so a reader in 2027 is not left guessing. The
evaluated server negotiated `2025-11-25` via `mcp` 1.27.1.
