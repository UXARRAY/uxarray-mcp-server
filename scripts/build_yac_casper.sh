#!/usr/bin/env bash
# Build YAC 3.20.2 for the Casper Python 3.12 worker env, via the endpoint.
# Run from the laptop (needs the endpoint config); the worker compiles.
set -euo pipefail
cd "$(dirname "$0")/.."
exec uv run --with globus-compute-sdk python scripts/hpc_build_yac.py \
    --endpoint "${ENDPOINT:-ucar-uxarray-yac}" \
    --prefix "${PREFIX:-~/opt/yac-3.20.2-py312}" \
    --build-root "${BUILD_ROOT:-~/build/yac-py312}" \
    --venv-python "${WORKER_PYTHON:-/glade/work/rajeevj/conda-envs/uxarray_312/bin/python}" \
    --module-loads "${MODULE_LOADS:-ncarenv/24.12 gcc/12.4.0 openmpi/5.0.6}" \
    --yac-version v3.20.2 --make-jobs 8 --timeout-seconds 3600
