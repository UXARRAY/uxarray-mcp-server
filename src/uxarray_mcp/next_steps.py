"""Compact follow-up suggestions for tool results (#83).

``recommended_next_steps`` (#30) exists so an agent can chain a workflow
without already knowing the tool vocabulary. That is worth keeping. What was
not worth keeping is *how* it was spelled: every step interpolated the
caller's own absolute file paths back into the string, so a four-step list
repeated the same path four times.

Measured on an MPAS QU480 mesh before this change, the echoed paths alone
were 28% of an ``inspect_mesh`` result and 36% of an ``inspect_variable``
result -- more bytes than every computed number in either reply. The caller
supplied those paths in the request it just made, so sending them back
teaches it nothing, and results are re-sent on every later turn.

The rule is one line: echo a value only when the caller did not already
have it. That gives three ways to render an argument.

``"grid_path"``
    A value the caller passed in, referenced by parameter name. Bare rather
    than quoted, because quoting would read as a literal filename.
``literal(name)``
    A value the server discovered by opening the file, such as a variable
    name. Genuinely new, so it is spelled out in full.
``needed("data_path")``
    A value the caller has not supplied yet and must provide to make the
    call, rendered ``<data_path>``.

Tool names are always spelled out: naming the next tool is the whole point.
"""

from __future__ import annotations


def literal(value: str | float) -> str:
    """Quote a value the server discovered and the caller may not know."""
    return f'"{value}"' if isinstance(value, str) else str(value)


def needed(name: str) -> str:
    """Mark an argument the caller must still supply."""
    return f"<{name}>"


def call(tool: str, *args: str, note: str | None = None, **kwargs: str) -> str:
    """Render one suggested call as ``tool(a, b, k=v) - note``."""
    rendered = list(args) + [f"{key}={value}" for key, value in kwargs.items()]
    step = f"{tool}({', '.join(rendered)})"
    return f"{step} - {note}" if note else step
