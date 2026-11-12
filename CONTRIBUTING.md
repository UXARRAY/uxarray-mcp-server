# Contributing

```bash
git clone https://github.com/UXARRAY/uxarray-mcp-server.git && cd uxarray-mcp-server
uv sync --dev                       # add --extra hpc for the Globus layer
uv run pre-commit install
uv run pre-commit run --all-files
uv run pytest -m "not hpc and not live and not yac"
```

Read [docs/architecture.md](docs/architecture.md) first; it is one page and
states the three rules below in context.

## Rules

- **`core/` imports no server code** (`mcp`, `toolregistry`, pydantic,
  `uxarray_mcp.server`, `uxarray_mcp.remote`). `tests/test_core_isolation.py`
  enforces it. A worker imports `core/` with `--no-deps`; anything else there
  breaks every HPC endpoint.
- **New capability = new operation, not new tool.** Add the function to the
  right `core/` module, register it in `core/ops.py`, expose it as a new
  `statistic=` / `shape=` / `kind=` value in `server/tools.py`. Twelve tools
  is the surface; `tests/test_server.py` pins the list and the schema byte
  budget (~13 kB). If a change needs more bytes, say why in the test.
- **Refuse, don't warn, when the number would be wrong.** Use
  `contract.check(...)` for conditions under which the answer is not
  physical; core functions report coverage, the tool decides.
- **Every change has a test.** Core functions: a real number in
  `tests/test_core_<module>.py`. Tools: happy path + refusal in
  `tests/test_tools.py`. Remote: `tests/test_remote_executor.py` with the
  stub executor, or `tests/fake_endpoint.py` under the `hpc` marker.
- **Docs are three files.** A new operation gets a row in `docs/tools.md`;
  a new endpoint fact goes in `docs/hpc.md`. Nothing else.
- Comments say why, not what. Keep docstrings to a few lines — tool
  docstrings are the descriptions clients pay for on every request.

## Process

Branch from `main`, one logical change per PR, rebase rather than merge, CI
green. Runtime deps go in `[project] dependencies`, Globus-only ones in the
`hpc` extra; run `uv lock` and commit `uv.lock`.

HPC-dependent tests are marker-gated (`hpc`, `live`, `yac`); CI runs the
`hpc` lane with `fake_endpoint.py`, never a real cluster. `live` tests need
a configured endpoint and are run by hand.

Licensed under Apache-2.0 by contributing.
