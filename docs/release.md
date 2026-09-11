# Release Process

This project follows the same broad release model as UXarray, and releases
when UXarray does:

1. GitHub CI must be green on `main`.
2. Every day, GitHub Actions reads the newest `uxarray` release from PyPI and
   checks for commits since the latest `v*` tag.
3. If upstream has not moved and no commits have landed, nothing happens.
4. Otherwise the workflow computes the version, rewrites the version files and
   the uxarray pin, runs the full checks against that upstream release, and
   opens a release pull request.
5. A human merges that pull request and tags `v<version>` on `main`. Tagging
   is what publishes; nothing reaches PyPI unattended.
6. Conda packages are handled through a conda-forge feedstock.

## Versioning

Versions are CalVer: `<year>.<month>.<patch>`, mirroring the `year.month` of
the `uxarray` release they were built against, with the patch counting our own
releases within that month. `2026.9.2` is our third release against upstream's
September 2026 line, not upstream's third patch.

Components are never zero-padded. Upstream tags `v2026.09.0`, but PEP 440
strips the leading zero, so a dist built from a padded version publishes as
`2026.9.0` and disagrees with the tag it came from. `prepare_release.py`
rejects a padded version rather than normalizing it silently.

Upstream is read from PyPI rather than from upstream's git tags, which mix
`v2026.09.0` and `v2026.4.0`; PyPI normalizes both.

## Daily Automation

`.github/workflows/release-on-upstream.yml` runs at 05:17 UTC daily. It can
also be run manually with `workflow_dispatch`.

Default behavior:

- a `uxarray` release with a `year.month` we have not shipped against: release
  `<that year>.<that month>.0`
- the same `year.month` we already shipped against, with commits since the
  latest tag: bump our patch
- neither: skip

The release commit moves both ends of the uxarray pin, to
`uxarray>=<upstream>,<next month>`. Raising only the floor would leave a
ceiling written for the previous month, which makes the package uninstallable
beside the upstream release it was just tested against.

If PyPI cannot be reached, the version falls back to a patch bump and the pin
is left exactly as it was; a ceiling is never guessed from a version that
could not be read.

Manual inputs:

- `version`: release an explicit version such as `2026.9.0`
- `upstream`: mirror a specific `uxarray` version instead of reading PyPI
- `force`: prepare a release with no commits and no new upstream

The workflow updates:

- `pyproject.toml` — the version and both ends of the uxarray pin
- `src/uxarray_mcp/__init__.py`
- `conda/recipe/meta.yaml`
- `CHANGELOG.md` — the `## Unreleased` section is closed under a heading for
  the new version and an empty `## Unreleased` is left for the next cycle
- `uv.lock` — the lockfile records the project's own version, so it is
  relocked. Nothing in CI passes `--locked`, which means a stale lock is
  invisible here and only fails for someone checking out the tag

Then it installs the upstream release being mirrored, runs the release checks
against it with `uv run --no-sync` (a bare `uv run` re-syncs to `uv.lock` and
would silently put the locked uxarray back), builds the package, and opens the
release pull request. On failure it opens an issue naming the upstream version
and stops. It never tags, never publishes, and never pushes to `main`.

The cutover from `0.3.1` to CalVer is a one-time manual `workflow_dispatch`
with `version=2026.9.0`, run after reading the diff. It is irreversible: PEP
440 makes `2026.9.0 > 0.3.1`, so anyone pinned `>=0.3` moves to CalVer on
their next resolve.

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

The seed recipe intentionally targets the **core** package only. Keep
`globus-compute-sdk` and `academy-py` out of the initial conda-forge recipe
until those dependencies and their transitive solver behavior are validated on
conda-forge. If conda-native HPC support becomes necessary, prefer a second
output such as `uxarray-mcp-hpc` or a feedstock variant rather than making every
local-only user solve the remote-execution stack.

## Privacy Check

Before every release, verify endpoint UUIDs and local config did not re-enter
tracked history:

```bash
git grep -n -E 'endpoint_id: [0-9a-f-]{36}' -- .
git log --all --oneline -- config.yaml
```
