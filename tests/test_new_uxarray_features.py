"""Tests for UXarray features adopted in the 0.2.x follow-ups.

Covers:
- ``scale_by_radius`` opt-in on gradient/curl (default keeps the unit sphere).
- ``zonal_anomaly`` operation.
- ``remap_to_rectilinear`` operation.

The package pins ``uxarray>=2026.6.0``, which ships all of these, so the tests
exercise them directly. A negative test still confirms the capability guard
raises a clear error if the underlying method is ever absent.
"""

from __future__ import annotations

import warnings

import numpy as np
import pytest
import uxarray as ux
import xarray as xr

from uxarray_mcp.domain.vector_calc import compute_curl, compute_gradient
from uxarray_mcp.domain.zonal import compute_zonal_anomaly_stats
from uxarray_mcp.tools.frontdoor import run_analysis


@pytest.fixture()
def healpix_dataset():
    """Small HEALPix UxDataset with face-centered u, v, and a scalar field."""
    grid = ux.Grid.from_healpix(zoom=2)
    n = grid.n_face
    rng = np.random.default_rng(7)
    return ux.UxDataset(
        {
            "u": ux.UxDataArray(
                xr.DataArray(rng.standard_normal(n), dims=["n_face"]), uxgrid=grid
            ),
            "v": ux.UxDataArray(
                xr.DataArray(rng.standard_normal(n), dims=["n_face"]), uxgrid=grid
            ),
            "temperature": ux.UxDataArray(
                xr.DataArray(250 + 30 * rng.standard_normal(n), dims=["n_face"]),
                uxgrid=grid,
            ),
        },
        uxgrid=grid,
    )


@pytest.fixture()
def structured_mesh_files(tmp_path):
    """A coarse global UGRID grid + face-centered data, written to disk.

    ``Grid.from_structured`` produces proper node coordinates that survive a
    NetCDF round-trip, making it a reliable file-based fixture for remapping.
    """
    lon = np.arange(0, 360, 20.0)
    lat = np.arange(-80, 81, 20.0)
    grid = ux.Grid.from_structured(lon=lon, lat=lat)
    grid_file = tmp_path / "grid.nc"
    data_file = tmp_path / "data.nc"
    grid.to_xarray().to_netcdf(grid_file)

    rng = np.random.default_rng(11)
    xr.Dataset(
        {"temperature": (["n_face"], 250 + 30 * rng.random(grid.n_face))}
    ).to_netcdf(data_file)
    return str(grid_file), str(data_file)


# ---------------------------------------------------------------------------
# scale_by_radius opt-in
# ---------------------------------------------------------------------------


class TestScaleByRadius:
    def test_gradient_default_keeps_unit_sphere(self, healpix_dataset):
        result = compute_gradient(healpix_dataset, "temperature")
        assert result["scale_by_radius"] is False

    def test_curl_default_keeps_unit_sphere(self, healpix_dataset):
        result = compute_curl(healpix_dataset, "u", "v")
        assert result["scale_by_radius"] is False

    def test_gradient_records_scale_by_radius_flag(self, healpix_dataset):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")  # grid has no sphere_radius
            result = compute_gradient(
                healpix_dataset, "temperature", scale_by_radius=True
            )
        assert result["scale_by_radius"] is True

    def test_remote_gradient_threads_scale_by_radius(self):
        """The remote dispatch must forward scale_by_radius to the agent."""
        from unittest.mock import MagicMock, patch

        from uxarray_mcp.tools import vector_calc

        agent = MagicMock()
        agent.config.endpoint_id = "fake-endpoint"
        agent.config.endpoint_name = "fake"
        agent.config.timeout_seconds = 60
        agent.calculate_gradient_remote.return_value = {
            "components": [],
            "component_stats": {},
            "n_face": 1,
            "scale_by_radius": True,
            "_provenance": {"warnings": []},
        }

        with (
            patch("uxarray_mcp.remote.agent.get_agent", return_value=agent),
            patch.object(
                vector_calc, "_endpoint_manager_is_up", return_value=(True, "ok")
            ),
            patch.object(vector_calc, "_run_sync", side_effect=lambda f: f()),
        ):
            vector_calc.calculate_gradient(
                "/hpc/grid.nc",
                "/hpc/data.nc",
                "t",
                scale_by_radius=True,
                use_remote=True,
                endpoint="improv",
            )

        # The agent method must have been called with scale_by_radius=True.
        args, kwargs = agent.calculate_gradient_remote.call_args
        assert (True in args) or (kwargs.get("scale_by_radius") is True)


# ---------------------------------------------------------------------------
# zonal_anomaly
# ---------------------------------------------------------------------------


class TestZonalAnomaly:
    def test_domain_returns_stats(self, healpix_dataset):
        result = compute_zonal_anomaly_stats(healpix_dataset, "temperature")
        assert result["variable_name"] == "temperature"
        assert set(result["stats"]) == {"min", "max", "mean", "std"}
        assert result["n_face"] == int(healpix_dataset.uxgrid.n_face)

    def test_anomaly_mean_near_zero(self, healpix_dataset):
        result = compute_zonal_anomaly_stats(healpix_dataset, "temperature")
        assert abs(result["stats"]["mean"]) < 1.0

    def test_missing_variable_raises(self, healpix_dataset):
        with pytest.raises(ValueError):
            compute_zonal_anomaly_stats(healpix_dataset, "nope")

    def test_run_analysis_dispatch(self, structured_mesh_files):
        grid_file, data_file = structured_mesh_files
        result = run_analysis(
            operation="zonal_anomaly",
            grid_path=grid_file,
            data_path=data_file,
            variable_name="temperature",
        )
        assert "stats" in result
        assert "_provenance" in result

    def test_capability_guard_when_unsupported(self, healpix_dataset, monkeypatch):
        """The domain layer raises a clear error if zonal_anomaly is absent."""
        monkeypatch.delattr(
            type(healpix_dataset["temperature"]), "zonal_anomaly", raising=False
        )
        if hasattr(healpix_dataset["temperature"], "zonal_anomaly"):
            pytest.skip("could not remove zonal_anomaly for negative test")
        with pytest.raises(NotImplementedError):
            compute_zonal_anomaly_stats(healpix_dataset, "temperature")


# ---------------------------------------------------------------------------
# remap_to_rectilinear
# ---------------------------------------------------------------------------


class TestRemapToRectilinear:
    def test_run_analysis_dispatch(self, state_dir, structured_mesh_files):
        grid_file, data_file = structured_mesh_files
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            result = run_analysis(
                operation="remap_to_rectilinear",
                grid_path=grid_file,
                data_path=data_file,
                variable_name="temperature",
                target_lon=list(np.arange(0, 360, 30.0)),
                target_lat=list(np.arange(-60, 61, 30.0)),
            )
        assert result["target_shape"] == [5, 12]
        assert set(result["stats"]) == {"min", "max", "mean"}
        assert result["result_handle"]
        assert "_provenance" in result

    def test_missing_target_coords_raises(self, state_dir, structured_mesh_files):
        grid_file, data_file = structured_mesh_files
        with pytest.raises(ValueError):
            run_analysis(
                operation="remap_to_rectilinear",
                grid_path=grid_file,
                data_path=data_file,
                variable_name="temperature",
            )
