"""Classification of non-spatial dimensions shared by the domain modules.

Every face-centered operator here -- polygon plotting, vector calculus, zonal
profiles -- needs the same thing from a real model file: collapse each
dimension that is not the face dimension down to a single index so the array
is 1-D.

Which index to use depends on what the dimension *is*. A time axis takes the
caller's ``time_index``; a vertical axis takes ``level_index``; anything else
takes 0, because neither selector says anything about it. Applying
``time_index`` to every extra dimension -- which the plotting path used to do
-- silently hands back level 3 of a multi-level field when the caller asked
for time step 3, and nothing in the output says so.

That second half matters as much as the first: a collapse that is not
reported is how a caller ends up believing one level is the whole answer. So
every selection made here is returned alongside the selection itself, for the
tool layer to put in its provenance.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping

FACE_DIMS = frozenset({"n_face", "nCells"})

# Matched case-insensitively. A dimension whose name merely *contains* "time"
# (``valid_time``, ``time_counter``) is also treated as time-like, matching
# what the zonal profile path has always done.
TIME_DIM_NAMES = frozenset({"time", "time_counter"})

# Exact matches only -- these are short enough that a substring rule would
# misfire (``z`` appears inside plenty of unrelated names).
LEVEL_DIM_NAMES = frozenset({"lev", "level", "levels", "plev", "z", "nvertlevels"})

# Substrings that make a dimension vertical. ``lev`` covers the long tail of
# real spellings -- ``n_level``, ``nlev``, ``num_levels``, ``nVertLevels`` --
# which an exact list kept missing; this project's own multi-level fixture
# uses ``n_level``, and it was classified "other" and pinned to index 0 with
# no way for a caller to reach the other three.
LEVEL_DIM_SUBSTRINGS = ("lev", "depth", "height", "altitude", "isobaric")


def classify_dim(dim: Any) -> str:
    """Return ``"time"``, ``"level"``, or ``"other"`` for a dimension name."""
    name = str(dim).lower()
    if name in TIME_DIM_NAMES or "time" in name:
        return "time"
    if name in LEVEL_DIM_NAMES or any(s in name for s in LEVEL_DIM_SUBSTRINGS):
        return "level"
    return "other"


def face_slice_selection(
    sizes: Mapping[Any, int],
    *,
    time_index: int = 0,
    level_index: int = 0,
    keep: Iterable[Any] = FACE_DIMS,
) -> tuple[dict[str, int], dict[str, dict[str, Any]]]:
    """Plan the collapse of every dimension in ``sizes`` outside ``keep``.

    Returns ``(selection, reduced)``. ``selection`` is ready to hand to
    ``.isel(**selection)``. ``reduced`` describes each dimension that was
    genuinely collapsed -- name, kind, index chosen, and original size --
    and omits size-1 dimensions, which carry no information to lose.
    """
    keep_set = {str(d) for d in keep}
    selection: dict[str, int] = {}
    reduced: dict[str, dict[str, Any]] = {}

    for dim, size in sizes.items():
        name = str(dim)
        if name in keep_set:
            continue
        size = int(size)
        if size == 1:
            selection[name] = 0
            continue
        kind = classify_dim(name)
        index = {"time": time_index, "level": level_index}.get(kind, 0)
        selection[name] = index
        reduced[name] = {"kind": kind, "index": index, "size": size}

    return selection, reduced
