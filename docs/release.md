# Release Process

This project follows the same broad release model as UXarray:

1. GitHub CI must be green on `main`.
2. A GitHub Release is published from a `v<version>` tag.
3. The release workflow builds and publishes the Python package to PyPI.
4. Conda packages are handled through a conda-forge feedstock.

## PyPI

The package name is `uxarray-mcp`. The release workflow is
`.github/workflows/release.yml` and runs when a GitHub Release is published.

Before the first release, configure PyPI trusted publishing:

- PyPI project: `uxarray-mcp`
- GitHub repository: `UXARRAY/uxarray-mcp-server`
- Workflow: `release.yml`
- Environment: `pypi`

Release steps:

```bash
uv run pre-commit run --all-files
uv run pytest tests/ --ignore=tests/test_remote_agent.py -v
uv run --extra hpc pytest tests/test_remote_agent.py tests/test_hpc_safety.py -v
uv run --extra docs sphinx-build -b html docs docs/_build/html -W --keep-going
uv build
```

Then create and publish a GitHub Release for a tag such as `v0.1.0`. The
workflow will:

- build the source distribution and wheel
- run `twine check`
- install the wheel in a clean environment
- publish to PyPI with trusted publishing

After publishing:

```bash
uv tool install uxarray-mcp
uxarray-mcp --help
```

For HPC users:

```bash
uv tool install "uxarray-mcp[hpc]"
uxarray-mcp setup
```

## Conda

Conda packages should be published through conda-forge, not from this repository
directly. A seed recipe lives at `conda/recipe/meta.yaml` to bootstrap a future
`uxarray-mcp-feedstock`.

Feedstock steps:

1. Publish the PyPI release first.
2. Create or update `conda-forge/uxarray-mcp-feedstock` from the seed recipe.
3. Update `version`, `sha256`, and `build/number` in `recipe/meta.yaml`.
4. Let conda-forge CI build and upload the package.
5. Verify:

```bash
conda install -c conda-forge uxarray-mcp
uxarray-mcp --help
```

The conda package should install the core MCP server and CLI. HPC-specific
Globus Compute dependencies can be added to the feedstock later if conda-forge
availability and solver behavior are acceptable.

## Privacy Check

Before every release, verify endpoint UUIDs and local config did not re-enter
tracked history:

```bash
git grep -n -E 'endpoint_id: [0-9a-f-]{36}' -- .
git log --all --oneline -- config.yaml
```
