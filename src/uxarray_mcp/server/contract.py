"""What every tool result promises.

Each result carries ``status`` (``complete`` | ``warning`` | ``unverified``),
``physically_interpretable``, ``warning_codes``, a ``preconditions`` block
and ``_provenance``. A result whose preconditions fail is **refused**: the
caller gets ``outcome: "input_required"`` with the failed checks and their
repairs instead of a number. Passing ``acknowledge=OVERRIDE_TOKEN`` runs it
anyway, marked ``unverified``. Everything is made JSON-safe on the way out
(no NaN/Infinity, no numpy types).
"""

from __future__ import annotations

import math
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from uxarray_mcp import __version__

OVERRIDE_TOKEN = "i-understand-this-result-may-not-be-physical"
OUTCOME_COMPLETE = "complete"
OUTCOME_INPUT_REQUIRED = "input_required"

# ---------------------------------------------------------------- JSON safety


def json_safe(value: Any) -> Any:
    """Rebuild ``value`` from JSON-representable types; non-finite -> None."""
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, (int, str)):
        return value
    if isinstance(value, bytes):
        return value  # content blocks handle bytes; never in structured output
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k): json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [json_safe(v) for v in value]
    try:
        import numpy as np

        if isinstance(value, np.generic):
            return json_safe(value.item())
        if isinstance(value, np.ndarray):
            return json_safe(value.tolist())
    except ImportError:  # pragma: no cover
        pass
    if hasattr(value, "item") and callable(value.item):
        try:
            return json_safe(value.item())
        except Exception:
            pass
    return str(value)


# -------------------------------------------------------------- preconditions


def check(check_id: str, passed: bool, detail: str, repair: str) -> dict[str, Any]:
    """One declared precondition and, if it failed, how to fix it."""
    return {"id": check_id, "passed": bool(passed), "detail": detail, "repair": repair}


class Refusal(Exception):
    """Raised when a precondition fails and no override was given."""

    def __init__(self, payload: dict[str, Any]):
        super().__init__(payload["refusal"]["summary"])
        self.payload = payload


def enforce(
    operation: str, checks: list[dict[str, Any]], acknowledge: str | None
) -> dict[str, Any]:
    """Return the ``preconditions`` block, or raise :class:`Refusal`."""
    failed = [c for c in checks if not c["passed"]]
    overridden = bool(failed) and acknowledge == OVERRIDE_TOKEN
    if failed and not overridden:
        hint = (
            f"acknowledge={acknowledge!r} is not the override token; the exact "
            f"value is {OVERRIDE_TOKEN!r}."
            if acknowledge is not None
            else "The operation did not run and no number was produced."
        )
        raise Refusal(
            {
                "outcome": OUTCOME_INPUT_REQUIRED,
                "operation": operation,
                "refusal": {
                    "summary": f"{operation} refused: {len(failed)} of "
                    f"{len(checks)} preconditions failed.",
                    "failed_checks": failed,
                    "repairs": [c["repair"] for c in failed],
                    "override": {
                        "parameter": "acknowledge",
                        "value": OVERRIDE_TOKEN,
                        "effect": "Runs anyway; result marked unverified and "
                        "physically_interpretable=false.",
                    },
                    "hint": hint,
                },
            }
        )
    return {
        "status": "overridden"
        if overridden
        else ("satisfied" if checks else "not_evaluated"),
        "checks": checks,
        "failed_checks": [c["id"] for c in failed],
        "override_used": overridden,
    }


# ------------------------------------------------------------------- finish


def _uxarray_version() -> str:
    try:
        import uxarray

        return str(getattr(uxarray, "__version__", "unknown"))
    except Exception:  # pragma: no cover
        return "unknown"


def _compact_inputs(inputs: dict[str, Any]) -> dict[str, Any]:
    """Inputs as given, minus Nones and defaults nobody needs echoed."""
    return {k: v for k, v in inputs.items() if v is not None and v is not False}


def finish(
    result: dict[str, Any],
    *,
    tool: str,
    inputs: dict[str, Any],
    checks: list[dict[str, Any]] | None = None,
    acknowledge: str | None = None,
    venue: str = "local",
    artifacts: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Attach the contract envelope to a core result and make it JSON-safe.

    ``warning_codes`` and ``warnings`` already present on ``result`` (from
    core coverage checks or remote drift) are kept and merged. Raises
    :class:`Refusal` when ``checks`` fail without an override; callers wrap
    with :func:`guard` so the refusal becomes a payload.
    """
    remote = result.pop("_remote", None)
    if remote:
        venue = f"hpc:{remote.get('endpoint')}"

    preconditions = enforce(tool, checks or [], acknowledge)
    warning_codes: list[str] = list(result.get("warning_codes") or [])
    coverage = result.get("coverage")
    if isinstance(coverage, dict):
        for code in coverage.get("warning_codes") or []:
            if code not in warning_codes:
                warning_codes.append(code)
    warnings_text: list[str] = list(result.get("warnings") or [])

    if preconditions["override_used"]:
        status = "unverified"
        interpretable: bool | None = False
        for failed in preconditions["failed_checks"]:
            warning_codes.append(f"PRECONDITION_FAILED_{failed.upper()}")
    elif warning_codes:
        status = "warning"
        interpretable = result.get("physically_interpretable", False)
    else:
        status = "complete"
        interpretable = result.get("physically_interpretable", True)

    result["outcome"] = OUTCOME_COMPLETE
    result["status"] = status
    result["physically_interpretable"] = interpretable
    result["warning_codes"] = warning_codes
    result["warnings"] = warnings_text
    result["preconditions"] = preconditions
    result["_provenance"] = {
        "tool": tool,
        "inputs": _compact_inputs(inputs),
        "venue": venue,
        "timestamp_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "uxarray_version": _uxarray_version(),
        "server_version": __version__,
        "python_version": ".".join(str(v) for v in sys.version_info[:3]),
    }
    if remote:
        result["_provenance"]["remote"] = {
            k: v for k, v in remote.items() if v is not None and k != "endpoint"
        }
    if artifacts:
        result["_provenance"]["artifacts"] = artifacts
    return json_safe(result)


def guard(fn: Any) -> Any:
    """Decorator: a :class:`Refusal` or :class:`RemoteError` becomes a payload."""
    from functools import wraps

    from uxarray_mcp.remote.executor import RemoteError

    @wraps(fn)
    def wrapped(*args: Any, **kwargs: Any) -> Any:
        try:
            return fn(*args, **kwargs)
        except Refusal as refusal:
            return json_safe(refusal.payload)
        except RemoteError as err:
            return err.to_dict()

    return wrapped
