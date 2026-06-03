#!/bin/bash
set -e

echo "[SETUP] Checking prerequisites..."
if ! python3 -c "import sys; assert sys.version_info >= (3, 11)" &> /dev/null; then
  echo "[ERROR] Python 3.11+ is required."
  exit 1
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
echo "[SUCCESS] Review 'GETTING_STARTED.md' for local setup and 'docs/hpc.md' for HPC bring-up."
echo "[INFO] For HPC endpoints, run: uxarray-mcp setup && uxarray-mcp endpoints add <name> <uuid>"
