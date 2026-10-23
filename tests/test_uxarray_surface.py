"""The inventory in ``domain/uxarray_surface.py`` against the real library.

Three failure modes, each of which happened or nearly happened:

1. UXarray grows a method, nobody notices, and a user's notebook finds the
   gap before we do. ``subset.bounding_circle`` and ``topological_mean``
   were found exactly that way, in the uxarray-community notebooks.
2. UXarray renames or drops a method we advertise in ``get_capabilities``,
   and the server keeps recommending a call that no longer exists.
3. The inventory itself drifts -- it claims an operation reaches something
   when the operation was never wired up.

None of these are caught by a count. A test asserting "N of M exposed"
fails on every release for reasons nobody can act on. These assert that
every method has a *verdict*, which is a decision someone made.
"""

from __future__ import annotations

import uxarray as ux
import xarray as xr

from uxarray_mcp.domain.uxarray_surface import REACHABLE, SURFACE, gaps


def _uxarray_only(cls, base) -> set[str]:
    """Public names ``cls`` adds on top of its xarray base.

    The inherited xarray surface is deliberately excluded: ~150 methods
    that are not UXarray's to change and would drown the signal.
    """
    own = {n for n in dir(cls) if not n.startswith("_")}
    inherited = {n for n in dir(base) if not n.startswith("_")}
    return own - inherited


def _installed_surface() -> set[str]:
    from uxarray.subset import DataArraySubsetAccessor

    names = _uxarray_only(ux.UxDataArray, xr.DataArray)
    names |= _uxarray_only(ux.UxDataset, xr.Dataset)
    names |= {
        f"subset.{n}" for n in dir(DataArraySubsetAccessor) if not n.startswith("_")
    }
    return names


class TestEveryUpstreamMethodHasAVerdict:
    def test_nothing_upstream_is_unaccounted_for(self):
        """A new UXarray method must be given a verdict, not ignored.

        If this fails, UXarray added something. Decide what it is --
        `exposed`, `gap`, or `out-of-scope` with a reason -- and add it to
        SURFACE. Deciding "we are not doing this" is a fine answer; not
        noticing is not.
        """
        missing = sorted(_installed_surface() - set(SURFACE))
        assert not missing, (
            f"uxarray {ux.__version__} has methods with no verdict in "
            f"domain/uxarray_surface.py: {missing}"
        )

    def test_the_inventory_does_not_name_methods_that_vanished(self):
        """A verdict about a method that no longer exists is stale.

        Catches an upstream rename the day it lands rather than the next
        time a user follows our advice into a method that is gone.
        """
        installed = _installed_surface()
        stale = sorted(k for k in SURFACE if k not in installed)
        assert not stale, (
            f"domain/uxarray_surface.py names methods absent from uxarray "
            f"{ux.__version__}: {stale}. Renamed or removed upstream?"
        )


class TestTheInventoryIsInternallyHonest:
    def test_every_entry_carries_a_reason(self):
        for name, (verdict, reason) in SURFACE.items():
            assert reason.strip(), f"{name} has verdict {verdict} and no reason"

    def test_every_exposed_entry_names_how_to_reach_it(self):
        """ "exposed" with no route is the drift this file exists to stop."""
        for name, (verdict, reason) in SURFACE.items():
            if verdict in REACHABLE:
                assert "(" in reason or "alias" in reason, (
                    f"{name} is {verdict} but its note does not name a call: {reason!r}"
                )

    def test_the_operations_named_as_routes_actually_exist(self):
        """An inventory claiming a route that was never wired up is worse
        than an inventory with a gap in it: the gap is at least visible.
        """
        import re

        from uxarray_mcp.app import make_registry
        from uxarray_mcp.tools.frontdoor import SUPPORTED_OPERATIONS

        tools = set(make_registry(profile="deferred-full").list_tools())
        bare_tools = {t.split("-")[-1] for t in tools}
        ops = set(SUPPORTED_OPERATIONS)

        for name, (verdict, reason) in SURFACE.items():
            if verdict not in REACHABLE:
                continue
            for op in re.findall(r"operation='([a-z_]+)'", reason):
                assert op in ops, f"{name} names operation {op!r}, which does not exist"
            for tool in re.findall(r"\b([a-z_]+)\(", reason):
                if tool in {"operation", "run_analysis"}:
                    continue
                assert tool in bare_tools or tool in ops, (
                    f"{name} names {tool!r}, which is neither a tool nor an operation"
                )


class TestKnownGapsAreTrackedNotForgotten:
    def test_the_gap_list_is_the_backlog(self):
        """Gaps are allowed; silent gaps are not.

        This asserts the shape of the record, not its length -- closing a
        gap should not require editing a number somewhere else.
        """
        for name, reason in gaps().items():
            assert len(reason) > 20, (
                f"gap {name} needs a reason someone can act on, got {reason!r}"
            )
