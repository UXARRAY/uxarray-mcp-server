# Release Process

This project follows the same broad release model as UXarray, with an added
scheduled release workflow:

1. GitHub CI must be green on `main`.
2. On the 5th of every month, GitHub Actions checks for commits since the
   latest `v*` tag.
3. If there are no new commits, the release is skipped.
4. If there are new commits, the workflow bumps the patch version, commits it,
   creates a `v<version>` tag, and publishes a GitHub Release.
5. The release workflow builds and publishes the Python package to PyPI.
6. Conda packages are handled through a conda-forge feedstock.

## Monthly Automation

`.github/workflows/monthly-release.yml` runs at 05:00 UTC on the 5th of every
month. It can also be run manually with `workflow_dispatch`.

Default behavior:

- no previous `v*` tag: release the current version from `pyproject.toml`
- previous `vX.Y.Z` tag exists and commits have landed since then: release
  `X.Y.(Z+1)`
- no commits since the latest tag: skip

Manual inputs:

- `version`: release an explicit version such as `0.1.0`
- `force`: release even if there are no commits since the latest tag

The workflow updates:

- `pyproject.toml`
- `src/uxarray_mcp/__init__.py`
- `conda/recipe/meta.yaml`

Then it runs the release checks, builds the package, commits the version bump,
tags it, pushes to `main`, and creates the GitHub Release.

## PyPI

The package name is `uxarray-mcp`. The release workflow is
`.github/workflows/release.yml` and runs when a GitHub Release is published.

Before the first release, configure PyPI trusted publishing:

- PyPI project: `uxarray-mcp`
- GitHub repository: `UXARRAY/uxarray-mcp-server`
- Workflow: `release.yml`
- Environment: `pypi`

The GitHub repository must also have an environment named `pypi` and Actions
workflow permissions set to read/write.

Release steps:

```bash
uv run pre-commit run --all-files
uv run pytest tests/ --ignore=tests/test_remote_agent.py -v
uv run --extra hpc pytest tests/test_remote_agent.py tests/test_hpc_safety.py -v
uv run --extra docs sphinx-build -b html docs docs/_build/html -W --keep-going
uv build
```

The release workflow (`.github/workflows/release.yml`) runs after a GitHub
Release is published. It will:

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

Fully automatic Conda releases require a feedstock repository and two GitHub
settings in this repository:

- variable `CONDA_FEEDSTOCK_REPOSITORY`, for example
  `conda-forge/uxarray-mcp-feedstock`
- secret `CONDA_FEEDSTOCK_TOKEN`, a token with permission to push branches and
  open pull requests on that feedstock

When those are configured, the PyPI release workflow will update the feedstock
recipe hash/version, open a pull request, and enable auto-merge. Conda-forge CI
then builds and uploads the package after the PR merges.

If those settings are not configured, the workflow still publishes PyPI and
skips the feedstock update with a clear log message.

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
