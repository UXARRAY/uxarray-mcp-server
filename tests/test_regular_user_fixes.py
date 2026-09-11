"""Defects found by driving the server as a regular user, pinned so they stay fixed.

Each class names the behaviour a first-time caller hit:

* a gradient on any grid without a ``sphere_radius`` attribute could not be
  obtained -- both repairs pointed at each other -- and acknowledging the
  refusal then failed the published output schema;
* the azimuthal profile always reported partial coverage because the ring
  at radius zero is empty by construction;
* there was no JSON spelling for a regular latitude range;
* ``analyze_dataset`` embedded base64 that no client could render.
"""

from __future__ import annotations

import numpy as np
import pytest
import uxarray as ux
import xarray as xr

from uxarray_mcp.content_blocks import image_block
from uxarray_mcp.domain.vector_calc import (
    compute_azimuthal_mean,
    compute_curl,
    compute_divergence,
    compute_gradient,
)
from uxarray_mcp.preconditions import OVERRIDE_TOKEN, _radius_scaling_check
from uxarray_mcp.tools.frontdoor import _resolve_lat_spec, run_analysis
from uxarray_mcp.typed_results import output_schema_for


def _healpix_scalar_dataset(zoom: int = 2):
    grid = ux.Grid.from_healpix(zoom=zoom)
    rng = np.random.default_rng(3)
    field = xr.DataArray(
        rng.standard_normal(grid.n_face), dims=["n_face"], attrs={"units": "K"}
    )
    u = xr.DataArray(
        rng.standard_normal(grid.n_face),
        dims=["n_face"],
        attrs={"units": "m s-1", "standard_name": "eastward_wind"},
    )
    v = xr.DataArray(
        rng.standard_normal(grid.n_face),
        dims=["n_face"],
        attrs={"units": "m s-1", "standard_name": "northward_wind"},
    )
    return ux.UxDataset(
        {
            "t": ux.UxDataArray(field, uxgrid=grid),
            "u": ux.UxDataArray(u, uxgrid=grid),
            "v": ux.UxDataArray(v, uxgrid=grid),
        },
        uxgrid=grid,
    )


@pytest.fixture()
def healpix_files(tmp_path):
    """A HEALPix grid spec plus a data file the front door can open."""
    ds = _healpix_scalar_dataset()
    data_path = tmp_path / "field.nc"
    xr.Dataset(
        {
            name: (["n_face"], ds[name].values, ds[name].attrs)
            for name in ("t", "u", "v")
        }
    ).to_netcdf(data_path)
    return "healpix:2", str(data_path)


class TestRadiusRepairsAreNotCircular:
    def test_missing_attribute_repair_names_the_argument(self):
        check = _radius_scaling_check(True, False)
        assert not check["passed"]
        assert "sphere_radius=6371000" in check["repair"]
        assert "scale_by_radius=False" not in check["repair"]

    def test_unscaled_request_repair_also_names_the_argument(self):
        check = _radius_scaling_check(False, None)
        assert not check["passed"]
        assert "sphere_radius=6371000" in check["repair"]
        assert "acknowledge" in check["repair"]

    def test_applied_scaling_passes(self):
        assert _radius_scaling_check(True, True)["passed"]


class TestSphereRadiusArgument:
    def test_gradient_uses_a_supplied_radius(self):
        ds = _healpix_scalar_dataset()
        result = compute_gradient(ds, "t", sphere_radius=6371000.0)
        assert result["radius_basis"] == {
            "sphere_radius": 6371000.0,
            "radius_source": "argument",
        }
        assert result["scientific_status"]["physical_scaling_applied"] is True
        assert result["component_warnings"] == []

    def test_gradient_without_a_radius_reports_none(self):
        ds = _healpix_scalar_dataset()
        result = compute_gradient(ds, "t")
        assert result["radius_basis"]["radius_source"] == "none"
        assert result["scientific_status"]["physical_scaling_applied"] is False

    def test_declared_grid_radius_is_reported_as_the_grid(self):
        ds = _healpix_scalar_dataset()
        ds.uxgrid.sphere_radius = 1000.0
        result = compute_gradient(ds, "t")
        assert result["radius_basis"] == {
            "sphere_radius": 1000.0,
            "radius_source": "grid",
        }

    def test_argument_overrides_a_declared_radius(self):
        ds = _healpix_scalar_dataset()
        ds.uxgrid.sphere_radius = 1000.0
        result = compute_gradient(ds, "t", sphere_radius=2000.0)
        assert result["radius_basis"]["radius_source"] == "argument"
        assert result["radius_basis"]["sphere_radius"] == 2000.0

    def test_scaled_gradient_is_the_unit_sphere_one_divided_by_radius(self):
        unit = compute_gradient(_healpix_scalar_dataset(), "t", scale_by_radius=False)
        scaled = compute_gradient(_healpix_scalar_dataset(), "t", sphere_radius=1000.0)
        for component in unit["components"]:
            assert scaled["component_stats"][component]["max"] == pytest.approx(
                unit["component_stats"][component]["max"] / 1000.0
            )

    @pytest.mark.parametrize("compute", [compute_curl, compute_divergence])
    def test_curl_and_divergence_take_the_radius_too(self, compute):
        ds = _healpix_scalar_dataset()
        result = compute(ds, "u", "v", sphere_radius=6371000.0)
        assert result["radius_basis"]["radius_source"] == "argument"
        assert result["scientific_status"]["physical_scaling_applied"] is True

    def test_non_positive_radius_is_rejected(self):
        with pytest.raises(ValueError, match="positive"):
            compute_gradient(_healpix_scalar_dataset(), "t", sphere_radius=0.0)

    def test_front_door_gradient_with_radius_is_satisfied(
        self, state_dir, healpix_files
    ):
        grid, data = healpix_files
        result = run_analysis(
            "gradient",
            grid_path=grid,
            data_path=data,
            variable_name="t",
            sphere_radius=6371000,
        )
        assert result["outcome"] == "complete"
        assert result["preconditions"]["status"] == "satisfied"
        assert result["scientific_status"]["physically_interpretable"] is True

    def test_front_door_gradient_without_radius_is_refused_with_the_repair(
        self, state_dir, healpix_files
    ):
        grid, data = healpix_files
        result = run_analysis(
            "gradient", grid_path=grid, data_path=data, variable_name="t"
        )
        assert result["outcome"] == "input_required"
        (repair,) = result["refusal"]["repairs"]
        assert "sphere_radius=6371000" in repair


class TestOverriddenResultValidates:
    """An acknowledged refusal must still fit the published output schema."""

    @pytest.fixture(autouse=True)
    def _needs_jsonschema(self):
        pytest.importorskip("jsonschema")

    def test_schema_admits_overridden(self):
        schema = output_schema_for("run_analysis")
        status = schema["properties"]["preconditions"]["properties"]["status"]
        assert "overridden" in status["enum"]

    def test_acknowledged_gradient_validates(self, state_dir, healpix_files):
        import jsonschema

        grid, data = healpix_files
        result = run_analysis(
            "gradient",
            grid_path=grid,
            data_path=data,
            variable_name="t",
            scale_by_radius=False,
            acknowledge=OVERRIDE_TOKEN,
        )
        assert result["outcome"] == "complete"
        assert result["preconditions"]["status"] == "overridden"
        assert result["scientific_status"]["physically_interpretable"] is False
        jsonschema.validate(result, output_schema_for("run_analysis"))


class TestAzimuthalZeroRing:
    def test_zero_radius_ring_is_not_counted_as_a_miss(self):
        ds = _healpix_scalar_dataset(zoom=3)
        result = compute_azimuthal_mean(
            ds, "t", center_lon=0.0, center_lat=0.0, outer_radius=30.0, radius_step=10.0
        )
        assert result["radii_deg"][0] == 0.0
        assert np.isnan(result["azimuthal_mean_values"][0])
        coverage = result["profile_coverage"]
        assert coverage["degenerate_bins_excluded"] == 1
        assert coverage["n_bins"] == len(result["radii_deg"]) - 1
        assert coverage["n_bins_filled"] == coverage["n_bins"]
        assert coverage["cause"] == "none"

    def test_front_door_profile_is_interpretable(self, state_dir, healpix_files):
        grid, data = healpix_files
        result = run_analysis(
            "azimuthal_mean",
            grid_path=grid,
            data_path=data,
            variable_name="t",
            center_lon=0.0,
            center_lat=0.0,
            outer_radius=40.0,
            radius_step=20.0,
        )
        assert result["scientific_status"]["warning_codes"] == []
        assert result["scientific_status"]["physically_interpretable"] is True


class TestLatStep:
    def test_no_step_leaves_the_spec_alone(self):
        assert _resolve_lat_spec([-90, 90, 30], None) == [-90, 90, 30]
        assert _resolve_lat_spec(None, None) is None

    def test_step_alone_spans_the_globe(self):
        assert _resolve_lat_spec(None, 30) == (-90.0, 90.0, 30.0)

    def test_step_with_bounds_builds_the_tuple(self):
        assert _resolve_lat_spec([-60, 60], 15) == (-60.0, 60.0, 15.0)

    @pytest.mark.parametrize(
        "spec,step,match",
        [
            ([-90, 0, 90], 30, r"\[start, stop\]"),
            (30.0, 10, "needs a range"),
            ([60, -60], 10, "must increase"),
            (None, 0, "positive"),
        ],
    )
    def test_bad_combinations_are_refused_clearly(self, spec, step, match):
        with pytest.raises(ValueError, match=match):
            _resolve_lat_spec(spec, step)

    def test_front_door_zonal_mean_honours_lat_step(self, state_dir, healpix_files):
        grid, data = healpix_files
        result = run_analysis(
            "calculate_zonal_mean",
            grid_path=grid,
            data_path=data,
            variable_name="t",
            lat_step=45,
        )
        assert result["latitudes"] == [-90.0, -45.0, 0.0, 45.0, 90.0]


class TestRemapResultNamesItsMethod:
    def test_result_reports_backend_and_names_its_method_in_the_warning(
        self, state_dir, healpix_files
    ):
        grid, data = healpix_files
        result = run_analysis(
            "remap_variable",
            grid_path=grid,
            data_path=data,
            variable_name="t",
            target_grid_path="healpix:1",
            method="nearest_neighbor",
        )
        assert result["outcome"] == "complete", result
        assert result["method"] == "nearest_neighbor"
        assert result["backend"] == "uxarray"
        assert result["yac_method"] is None
        assert result["source_coverage"]["method"] == "nearest_neighbor"
        warnings = result["_provenance"]["warnings"]
        assert any("nearest_neighbor remapping" in w for w in warnings)
        assert not any("nearest-neighbor" in w for w in warnings)


class TestAnalyzeDatasetDoesNotInlineStoredFigures:
    def test_png_meta_prefers_the_uri(self):
        import base64
        import json

        from uxarray_mcp.tools.orchestration import _png_meta

        b64 = base64.b64encode(b"\x89PNG_fake").decode()
        meta = json.dumps({"image_uri": "file:///tmp/x.png", "image_size_bytes": 9})
        out = _png_meta([image_block(b64), {"type": "text", "text": meta}])
        assert out["png_b64"] is None
        assert out["image_uri"] == "file:///tmp/x.png"
        assert out["image_delivery"] == "resource_link"

    def test_png_meta_keeps_bytes_when_nothing_was_stored(self):
        import base64
        import json

        from uxarray_mcp.tools.orchestration import _png_meta

        b64 = base64.b64encode(b"\x89PNG_fake").decode()
        out = _png_meta([image_block(b64), {"type": "text", "text": json.dumps({})}])
        assert out["png_b64"] == b64
        assert "image_uri" not in out
