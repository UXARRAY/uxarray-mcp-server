#!/bin/bash
set -e

echo "[SETUP] Checking prerequisites..."
if ! command -v uv &> /dev/null; then
    echo "[INFO] Installing uv..."
    pip install uv
fi

# Deliberately *not* gated on the ambient `python3`. `.python-version` pins
# 3.12 and uv provisions that interpreter itself, so the python3 on PATH is
# not the one the project runs on. The old check aborted with "Python 3.11 or
# newer is required" on any machine whose system python3 was older -- a
# macOS box with 3.9 on PATH could not run this script at all, while
# `uv sync` on the very same box builds a working 3.12 environment. It
# refused the one interpreter that does not matter.
echo "[SETUP] Installing project dependencies with uv..."

# `--extra hpc --dev` matches the CI job that runs the hpc-marked tests.
# A bare `uv sync` leaves globus-compute-sdk uninstalled, and the 25
# hpc-marked tests then fail on `ModuleNotFoundError` rather than being
# deselected -- the first thing a new contributor saw was a red suite
# caused by the setup script itself. `--dev` brings in pytest, jsonschema
# and mypy, which the suite asserts on rather than importing optionally.
uv sync --extra hpc --dev

# Checked after the sync, against the interpreter uv actually chose, which
# is the one that would submit the Globus Compute task. Not fatal: local
# analysis works on any supported Python, and only submission is
# minor-version sensitive (globus/globus-compute#2139).
if ! uv run python -c "import sys; assert sys.version_info[:2] == (3, 12)" &> /dev/null; then
  echo "[WARN] Python 3.12 is the supported Globus Compute submitter;"
  echo "[WARN] this environment is $(uv run python -c 'import sys; print("%d.%d" % sys.version_info[:2])')."
  echo "[WARN] Local execution is unaffected; HPC submission may hit WorkerLost."
fi

# CI partitions the suite by marker in three jobs; this runs the two that
# need no special build. Markers, not `--ignore`: a filename ignore has to
# be repeated everywhere, says nothing about why, and hides the passing
# tests in that file. `--ignore=tests/test_remote_agent.py` was hiding 16
# tests that pass perfectly well.
#
# `yac` is left out because it needs a YAC build that no amount of pip can
# provide (scripts/build_yac_local.sh), and `live` because it submits real
# work to a configured Globus Compute endpoint.
echo "[SETUP] Running automated tests (no external data required)..."
uv run pytest tests/ -m "not hpc and not live and not yac"

# Separately, so that a missing or broken `hpc` extra is reported as the
# distinct failure it is rather than disappearing into the main run.
echo "[SETUP] Running HPC tests (mocked; no cluster required)..."
uv run pytest tests/ -m "hpc and not yac"

echo ""
echo "[INFO] Not run here: tests marked 'yac' need a YAC build"
echo "[INFO] (scripts/build_yac_local.sh); tests marked 'live' need a real"
echo "[INFO] Globus Compute endpoint and the UXMCP_LIVE_* variables."
echo ""
echo "[SUCCESS] Review 'README.md' for local setup and 'docs/remote-hpc.md' for HPC bring-up."
echo "[INFO] For HPC endpoints, run: uxarray-mcp setup && uxarray-mcp endpoints add <name> <uuid>"
