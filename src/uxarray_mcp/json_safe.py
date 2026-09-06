"""Make tool payloads representable in JSON before they reach the wire.

JSON has no NaN and no Infinity. Python's ``json`` module papers over that
with ``allow_nan=True`` by default, emitting the bare tokens ``NaN``,
``Infinity`` and ``-Infinity`` -- valid Python, invalid JSON (RFC 8259
:rfc:`8259#section-6`). A strict client decoder rejects the whole message,
so one undefined zonal band can lose the caller every other number in the
response.

Two paths carry our results out and neither one closes this:

* ``structuredContent`` never passes through ``json.dumps`` inside the MCP
  adapter at all -- the live dict goes to pydantic and is serialized by the
  transport, so a float NaN travels as far as the encoder that finally
  refuses it.
* The text blocks we build ourselves call ``json.dumps`` with the default
  ``allow_nan=True``, which writes the invalid tokens rather than raising.

So the fix has to live here, in first-party code, ahead of the return.
Non-finite floats become ``null``: JSON's own way of saying "no value",
and the right reading of a NaN zonal band or an all-masked variable's
mean. It is lossy about *why* -- NaN and +Inf arrive as the same ``null``
-- and that is accepted, because a result that cannot be parsed carries
less information than one that says "undefined here".

This also absorbs the numpy and ``pathlib`` types that ``json`` does not
know, so a single pass covers everything between a tool's return statement
and the transport.
"""

from __future__ import annotations

import json
import math
from datetime import datetime
from pathlib import Path
from typing import Any

__all__ = ["json_safe", "json_text"]


def _finite_or_none(value: float) -> float | None:
    return value if math.isfinite(value) else None


def json_safe(value: Any) -> Any:
    """Return ``value`` rebuilt from types the JSON encoder can represent.

    Non-finite floats become ``None``; numpy scalars and arrays become
    Python scalars and lists; ``Path`` and ``datetime`` become strings.
    Containers are rebuilt rather than mutated, so the caller's dict is
    left alone.
    """
    if isinstance(value, bool) or value is None:
        # bool before int: ``isinstance(True, int)`` is True and a bool
        # must stay a bool on the wire.
        return value
    if isinstance(value, float):
        return _finite_or_none(value)
    if isinstance(value, int) or isinstance(value, str):
        return value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [json_safe(item) for item in value]

    numpy_value = _from_numpy(value)
    if numpy_value is not _UNHANDLED:
        return json_safe(numpy_value)
    return value


_UNHANDLED = object()


def _from_numpy(value: Any) -> Any:
    """Unwrap a numpy scalar or array, or return ``_UNHANDLED``.

    Imported lazily and guarded because this module sits on the return
    path of every tool, including ones that never touch numpy, and a
    missing or broken numpy must not be the reason a result fails to
    serialize.
    """
    try:
        import numpy as np
    except Exception:  # pragma: no cover - numpy is a hard dependency
        return _UNHANDLED
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, np.ndarray):
        return value.tolist()
    return _UNHANDLED


def json_text(value: Any, *, indent: int | None = 2) -> str:
    """Serialize ``value`` to JSON text that a strict decoder will accept.

    ``allow_nan=False`` is belt and braces: ``json_safe`` has already
    removed every non-finite float, so the encoder should never have the
    chance to raise. If it ever does, a loud ``ValueError`` here beats
    shipping a payload that only fails once it reaches the client.
    """
    return json.dumps(json_safe(value), indent=indent, allow_nan=False)
