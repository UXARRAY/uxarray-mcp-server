"""Regression coverage for HEALPix spec parsing and routing.

Three bugs motivated this module, all found by the heavy benchmark suite:

1. ``startswith("healpix")`` (no colon) treated an ordinary file named
   ``healpix_z5_data.nc`` as a virtual grid spec, silently substituting a
   grid of the wrong size for the user's data.
2. Local loaders used a case-insensitive test while remote routing used a
   case-sensitive one, so ``HEALPix:3`` ran locally but was refused remotely.
3. A malformed zoom fell back to a default instead of raising, producing a
   valid-looking grid at the wrong resolution.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from uxarray_mcp.domain.mesh import (
    MAX_HEALPIX_ZOOM,
    is_healpix_spec,
    parse_healpix_zoom,
)
from uxarray_mcp.tools.remote_tools import _path_is_locally_reachable


class TestIsHealpixSpec:
    @pytest.mark.parametrize(
        "spec", ["healpix:0", "healpix:3", "HEALPix:3", "HEALPIX:12", " healpix:2"]
    )
    def test_accepts_spec_forms(self, spec):
        assert is_healpix_spec(spec) is True

    @pytest.mark.parametrize(
        "path",
        [
            "healpix_z5_data.nc",
            "healpix.nc",
            "/scratch/run/healpix_out.nc",
            "healpix",
            "grid.nc",
            "",
        ],
    )
    def test_rejects_real_file_paths(self, path):
        """A filename that merely starts with 'healpix' is not a spec."""
        assert is_healpix_spec(path) is False

    def test_rejects_non_string(self):
        assert is_healpix_spec(None) is False
        assert is_healpix_spec(Path("healpix:2")) is False


class TestParseHealpixZoom:
    @pytest.mark.parametrize(
        ("spec", "zoom"),
        [("healpix:0", 0), ("healpix:3", 3), ("HEALPix:7", 7), ("healpix: 4", 4)],
    )
    def test_parses_valid_zoom(self, spec, zoom):
        assert parse_healpix_zoom(spec) == zoom

    @pytest.mark.parametrize(
        "spec", ["healpix:", "healpix:abc", "healpix:2.5", "healpix:notanumber"]
    )
    def test_rejects_non_integer(self, spec):
        with pytest.raises(ValueError, match="Invalid HEALPix format"):
            parse_healpix_zoom(spec)

    @pytest.mark.parametrize("spec", ["healpix:-1", "healpix:99"])
    def test_rejects_out_of_range(self, spec):
        """Silent coercion produced the wrong resolution; it must raise."""
        with pytest.raises(ValueError, match="Zoom must be between"):
            parse_healpix_zoom(spec)

    def test_upper_bound_is_inclusive(self):
        assert parse_healpix_zoom(f"healpix:{MAX_HEALPIX_ZOOM}") == MAX_HEALPIX_ZOOM


class TestRoutingAgreesWithLoader:
    """Remote routing and local loading must classify a spec identically."""

    @pytest.mark.parametrize("spec", ["healpix:3", "HEALPix:3", "HEALPIX:3"])
    def test_spec_is_locally_reachable_any_case(self, spec):
        assert is_healpix_spec(spec) is True
        assert _path_is_locally_reachable(spec) is True

    def test_missing_file_named_healpix_is_not_reachable(self):
        assert _path_is_locally_reachable("healpix_z9_data.nc") is False


class TestHealpixToolsAcceptSpecs:
    """Tools that guard on file existence must exempt virtual specs."""

    def test_inspect_mesh_reports_analytic_face_count(self):
        from uxarray_mcp.tools import inspect_mesh

        result = inspect_mesh("healpix:2")
        assert result["format"] == "HEALPix"
        assert result["n_face"] == 12 * 4**2

    def test_register_dataset_accepts_spec(self, tmp_path):
        import numpy as np
        import uxarray as ux
        import xarray as xr

        from uxarray_mcp.tools.stateful import create_session, register_dataset

        grid = ux.Grid.from_healpix(zoom=2)
        data_path = tmp_path / "data.nc"
        xr.Dataset({"temperature": (["n_face"], np.zeros(int(grid.n_face)))}).to_netcdf(
            data_path
        )

        session_id = create_session()["session_id"]
        result = register_dataset(session_id, "healpix:2", str(data_path))
        assert result is not None

    @pytest.mark.parametrize(
        "spec", ["healpix:invalid", "healpix:notanumber", "healpix:-1"]
    )
    def test_invalid_spec_still_raises(self, spec):
        from uxarray_mcp.tools import inspect_mesh

        with pytest.raises(ValueError, match="Invalid HEALPix format"):
            inspect_mesh(spec)
