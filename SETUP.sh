#!/bin/bash
set -e

echo "[SETUP] Checking prerequisites..."
if ! python3 -c "import sys; assert sys.version_info >= (3, 11)" &> /dev/null; then
  echo "[ERROR] Python 3.11 or newer is required."
  exit 1
fi

# Not fatal. Local analysis works on any supported Python; only Globus Compute
# submission is minor-version sensitive (globus/globus-compute#2139), so an
# unsupported submitter is a warning for HPC users, not a blocked install.
if ! python3 -c "import sys; assert sys.version_info[:2] == (3, 12)" &> /dev/null; then
  echo "[WARN] Python 3.12 is the supported Globus Compute submitter."
  echo "[WARN] Local execution is unaffected; HPC submission may hit WorkerLost."
fi

echo "[SETUP] Installing project dependencies with uv..."
if ! command -v uv &> /dev/null; then
    echo "[INFO] Installing uv..."
    pip install uv
fi

uv sync

echo "[SETUP] Running automated tests (no external data required)..."
uv run pytest tests/ --ignore=tests/test_remote_agent.py

echo ""
echo "[SUCCESS] Review 'README.md' for local setup and 'docs/remote-hpc.md' for HPC bring-up."
echo "[INFO] For HPC endpoints, run: uxarray-mcp setup && uxarray-mcp endpoints add <name> <uuid>"
