#!/bin/bash
set -e

echo "[SETUP] Checking prerequisites..."
if ! python3 -c "import sys; assert sys.version_info >= (3, 13)" &> /dev/null; then
  echo "[ERROR] Python 3.13+ is required."
  exit 1
fi

echo "[SETUP] Installing project dependencies with uv..."
if ! command -v uv &> /dev/null; then
    echo "[INFO] Installing uv..."
    pip install uv
fi

uv sync

echo "[SETUP] Running automated tests (no external data required)..."
uv run pytest

echo ""
echo "[SUCCESS] Review the 'GETTING_STARTED.md' for next steps."
