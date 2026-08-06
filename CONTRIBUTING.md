# Contributing to UXarray MCP Server

Thank you for your interest in contributing. This project is part of the
[UXarray](https://uxarray.readthedocs.io/) ecosystem.

## Filing Issues

- **Bug reports** — include the Python version, OS, relevant config (redact
  endpoint UUIDs), the exact tool call, and the full error or unexpected result.
- **Feature requests** — describe the scientific workflow or use case that
  motivates the request, not just the API change.
- **HPC / Globus Compute issues** — include the output of `validate_hpc_setup`
  and `probe_path_access` with `use_remote=True`.

Search open issues before filing a new one.

## Development Setup

```bash
git clone https://github.com/UXARRAY/uxarray-mcp-server.git
cd uxarray-mcp-server
uv sync --dev                   # core + dev tools
uv sync --extra hpc --dev       # add Globus Compute + Academy (optional)

uv run pre-commit install        # install git hooks
uv run pre-commit run --all-files
uv run pytest tests/ --ignore=tests/test_remote_agent.py -v
```

Architecture notes — layer boundaries, tool profiles, and the key design
decisions behind them — are in
[docs/architecture.md](docs/architecture.md).

## Making Changes

- Work on a feature branch (`git checkout -b your-name/short-description`).
  `main` must always be deployable; never commit to it directly.
- Keep changes focused — one logical change per PR. Rebase onto `main` (do not
  merge) to resolve conflicts before opening the PR.
- All new tools must call `attach_provenance()`, be assigned to a bucket in
  `registry.py` (`_CONTROL_TOOLS`, `_CORE_EXTRA_TOOLS`, or `_DEFERRED_TOOLS`),
  be exported from `tools/__init__.py`, and be documented in `docs/tools.md`.
  `test_namespace_plan_covers_every_public_tool` fails if a tool in `__all__`
  is not assigned to a bucket.
- Prefer a new *operation* behind an existing front door (`run_analysis`,
  `plot_dataset`, `diagnose_endpoint`, `manage_session`) over a new public
  tool. New operations start deferred and graduate to `core` once stable.
- Deferred tools need a `search_hint` in `_SEARCH_HINTS`; BM25 discovery works
  much better with domain synonyms.
- All new tool functions need tests (see `tests/` for patterns). Add a test for
  every new error path and every bug fix. Behavior-preserving refactors should
  not need existing tests changed.
- Run the full check suite before pushing:

```bash
uv run pre-commit run --all-files
uv run pytest tests/ --ignore=tests/test_remote_agent.py -v
```

HPC-dependent tests need the optional extra:

```bash
uv sync --extra hpc --dev
uv run pytest tests/test_remote_agent.py tests/test_hpc_safety.py -v
```

CI must be green before a PR is merged.

## Common Mistakes

- Importing `mcp` or `toolregistry` inside `domain/`. Domain functions must
  import without server dependencies — they run on remote workers that do not
  have `uxarray_mcp` installed.
- Calling a module-level helper from a function in `remote/compute_functions.py`.
  Only the submitted function body is serialized, so the helper is undefined on
  the worker; keep shared logic inlined.
- Returning a plain dict from a tool without `attach_provenance()`.
- Using a `/home/...` path on a cluster where the file actually lives under the
  canonical shared mount (for example `/gpfs/fs1/home/...`). Check
  `probe_path_access` first on a new cluster.
- Importing `io` inside a function when it is used for byte I/O that tests need
  to patch — import it at module level instead.

## Pull Request Process

1. Open a PR against `main` with a clear title and description of what changed
   and why.
2. Link any related issues.
3. A maintainer will review — expect feedback within a few business days.
4. Squash and merge is preferred for small changes; merge commits for large
   features with meaningful history.

## Code Style

- Formatter and linter: `ruff` (enforced by pre-commit).
- Type checker: `mypy` (enforced by pre-commit).
- Annotate all new public functions.
- Comments explain *why*, not *what*.
- No `domain/` imports of `mcp` or `toolregistry` — domain functions run on
  remote HPC workers that do not have `uxarray_mcp` installed.

## Adding Dependencies

- Runtime deps → `[project] dependencies` in `pyproject.toml`.
- HPC-only deps → `[project.optional-dependencies] hpc`.
- Dev-only tools → `[dependency-groups] dev`.
- Run `uv sync` after editing to regenerate `uv.lock`, and include the lock
  file in your PR.

## License

By contributing you agree that your contributions will be licensed under the
[Apache License 2.0](LICENSE).
