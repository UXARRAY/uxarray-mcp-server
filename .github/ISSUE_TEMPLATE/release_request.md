---
name: Release Request
about: Request a release for this package
title: "[Release]: <version-number>"
labels: release
assignees: rajeeja

---

Date of intended release:

## Release progress checklist

- [ ] CI tests are passing on `main`
- [ ] endpoint UUID/privacy scans are clean
- [ ] local wheel install smoke passes
- [ ] GitHub release has been created from a `v<version>` tag
- [ ] PyPI publish workflow has completed successfully
- [ ] `uv tool install uxarray-mcp` works from PyPI
- [ ] conda-forge feedstock PR has been opened or merged
- [ ] `conda install -c conda-forge uxarray-mcp` works after feedstock merge
