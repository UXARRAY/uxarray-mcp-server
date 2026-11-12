# Releasing

## Versioning

CalVer `<year>.<month>.<patch>`, mirroring the `year.month` of the `uxarray`
release the server was built against; the patch counts our own releases in
that month (`2026.11.1` is our second release against upstream's November
line). Components are never zero-padded: PEP 440 turns `2026.09.0` into
`2026.9.0`, and `scripts/prepare_release.py` rejects a padded version rather
than letting a tag disagree with the published dist.

## Steps

```bash
git checkout main && git pull --ff-only
uv run pre-commit run --all-files
uv run pytest -m "not hpc and not live and not yac"
uv sync --extra hpc --dev && uv run pytest -m hpc

# Moves pyproject.toml, __init__.py, server.json, conda/recipe/meta.yaml,
# the uxarray pin and CHANGELOG's Unreleased heading in one go.
uv run python scripts/prepare_release.py --version 2026.11.0   # or --upstream / --no-upstream
uv lock && git diff --stat

git commit -am "Release 2026.11.0" && git push
gh release create v2026.11.0 --generate-notes
```

Publishing the GitHub Release triggers `.github/workflows/release.yml`,
which builds, `twine check`s, installs the wheel in a clean environment,
publishes to PyPI by trusted publishing (environment `pypi`), and — when
`CONDA_FEEDSTOCK_REPOSITORY` / `CONDA_FEEDSTOCK_TOKEN` are configured — opens
a version-bump PR on the conda-forge feedstock from `conda/recipe/meta.yaml`.
Without those settings it publishes PyPI and logs that the feedstock step was
skipped.

After publishing:

```bash
uv tool install uxarray-mcp && uxarray-mcp doctor
```

Then update each HPC worker env (`pip install --no-deps --upgrade uxarray-mcp`
and restart the endpoint; see [hpc.md](hpc.md)) — a released fix is absent on
the cluster until that happens, and every remote result will say so.

## Privacy check

Endpoint UUIDs and personal config must never enter tracked history:

```bash
git grep -n -E 'endpoint_id: [0-9a-f-]{36}' -- .
git log --all --oneline -- config.yaml
```

Both should print nothing.
