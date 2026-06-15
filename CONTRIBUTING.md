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

Full coding conventions and architecture notes are in [AGENTS.md](AGENTS.md).

## Making Changes

- Work on a feature branch (`git checkout -b your-name/short-description`).
- Keep changes focused — one logical change per PR.
- All new tools must call `attach_provenance()` and be registered in
  `server.py` and exported from `tools/__init__.py`.
- All new tool functions need tests (see `tests/` for patterns).
- Run the full check suite before pushing:

```bash
uv run pre-commit run --all-files
uv run pytest tests/ --ignore=tests/test_remote_agent.py -v
```

CI must be green before a PR is merged.

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
