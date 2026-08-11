"""Remote execution support for UXarray MCP server via Globus Compute and Academy.

Python version support
----------------------
The package as a whole installs on any Python >= 3.11, but *this subpackage*
is narrower. Globus Compute's default serializer is fragile across Python minor
versions -- a submitter on one minor against a worker on another raises
``WorkerLost`` on non-trivial payloads (globus/globus-compute#2139). HPC sites
broadly ship 3.12 conda stacks today, so 3.12 is the supported submitter.

That used to be expressed as a hard ``requires-python = ">=3.12,<3.13"`` on the
whole project, which made every local-only user pay for a constraint that only
binds when submitting remote work. The check now lives here instead, so the
cost lands on the code path that actually has the problem.

This module only *warns*; it does not raise. Import-time failure would be
wrong: ``uxarray_mcp.tools`` imports remote helpers unconditionally to build
the tool surface, so raising here would break a purely local server on 3.11 or
3.13. The tools that genuinely need an endpoint validate before submitting, and
``remote.health`` reports submitter/worker skew at probe time.
"""

from __future__ import annotations

import sys
import warnings

#: Submitter interpreters known to interoperate with current HPC worker stacks.
SUPPORTED_SUBMITTER_PYTHON = ((3, 12),)


def submitter_python_supported() -> bool:
    """Return True if this interpreter is a supported Globus Compute submitter."""
    return sys.version_info[:2] in SUPPORTED_SUBMITTER_PYTHON


def warn_if_unsupported_submitter() -> None:
    """Warn when the running interpreter is an unsupported submitter.

    Called by the tools that are about to submit remote work, not at import
    time -- a local-only session must stay silent.
    """
    if submitter_python_supported():
        return
    current = f"{sys.version_info.major}.{sys.version_info.minor}"
    supported = ", ".join(
        f"{major}.{minor}" for major, minor in SUPPORTED_SUBMITTER_PYTHON
    )
    warnings.warn(
        f"Python {current} is not a supported Globus Compute submitter "
        f"(supported: {supported}). Local execution is unaffected, but "
        f"submitting to an HPC endpoint may raise WorkerLost on non-trivial "
        f"payloads due to serializer skew (globus/globus-compute#2139). "
        f"To submit remote work, reinstall on {supported}: "
        f"`uv tool install --python {supported.split(',')[0].strip()} uxarray-mcp`.",
        RuntimeWarning,
        stacklevel=3,
    )


from .agent import UXarrayComputeAgent  # noqa: E402
from .config import load_config  # noqa: E402

__all__ = [
    "load_config",
    "UXarrayComputeAgent",
    "SUPPORTED_SUBMITTER_PYTHON",
    "submitter_python_supported",
    "warn_if_unsupported_submitter",
]
