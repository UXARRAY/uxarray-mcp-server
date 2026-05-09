#!/usr/bin/env python3
"""Submit a YAC smoke test to a configured Globus Compute endpoint.

Uses AllCodeStrategies so the function ships its source to the worker
(avoids local Python 3.13 / worker Python 3.11 dill mismatches).
"""

from __future__ import annotations

import argparse
import json
import sys

from globus_compute_sdk import Executor
from globus_compute_sdk.serialize import AllCodeStrategies, ComputeSerializer

from uxarray_mcp.remote.compute_functions import remote_yac_remap_smoke
from uxarray_mcp.remote.config import load_config


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--endpoint",
        default="ucar",
        help="Named endpoint profile (default: ucar).",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=180,
    )
    args = parser.parse_args()

    cfg = load_config().for_endpoint(endpoint=args.endpoint)
    if not cfg.endpoint_id:
        print(f"No endpoint_id resolved for {args.endpoint!r}", file=sys.stderr)
        return 2

    print(
        f"Submitting remote_yac_remap_smoke to endpoint {args.endpoint} "
        f"({cfg.endpoint_id}) ...",
        file=sys.stderr,
    )

    executor = Executor(
        endpoint_id=cfg.endpoint_id,
        serializer=ComputeSerializer(strategy_code=AllCodeStrategies()),
    )
    try:
        future = executor.submit(remote_yac_remap_smoke)
        result = future.result(timeout=args.timeout_seconds)
    finally:
        executor.shutdown(wait=False)

    print(json.dumps(result, indent=2, default=str))
    if result.get("yac_helper_ok") and result.get("remap_ok"):
        return 0
    if result.get("yac_helper_ok"):
        return 1
    return 3


if __name__ == "__main__":
    sys.exit(main())
