"""Tests for vector calculus and azimuthal mean tools."""

from __future__ import annotations

from unittest.mock import patch

import numpy as np
import pytest
import uxarray as ux

from uxarray_mcp.domain.vector_calc import (
    compute_azimuthal_mean,
    compute_curl,
    compute_divergence,
    compute_gradient,
)
from uxarray_mcp.tools.vector_calc import (
    calculate_azimuthal_mean,
    calculate_curl,
    calculate_divergence,
    calculate_gradient,
)

# ---------------------------------------------------------------------------
# Shared fixture — minimal HEALPix dataset with face-centred u and v fields
# ---------------------------------------------------------------------------


@pytest.fixture()
def healpix_wind_dataset():
    """Return a small HEALPix UxDataset with synthetic u and v wind fields."""
    grid = ux.Grid.from_healpix(zoom=2)
    n = grid.n_face
    rng = np.random.default_rng(42)
    import xarray as xr

    u_data = xr.DataArray(rng.standard_normal(n).astype(np.float64), dims=["n_face"])
    v_data = xr.DataArray(rng.standard_normal(n).astype(np.float64), dims=["n_face"])
    scalar = xr.DataArray(
        np.abs(rng.standard_normal(n).astype(np.float64)), dims=["n_face"]
    )

    ds = ux.UxDataset(
        {
            "u": ux.UxDataArray(u_data, uxgrid=grid),
            "v": ux.UxDataArray(v_data, uxgrid=grid),
            "temperature": ux.UxDataArray(scalar, uxgrid=grid),
        },
        uxgrid=grid,
    )
    return ds


# ---------------------------------------------------------------------------
# Domain: compute_gradient
# ---------------------------------------------------------------------------


class TestComputeGradient:
    def test_returns_components(self, healpix_wind_dataset):
        result = compute_gradient(healpix_wind_dataset, "temperature")
        assert "components" in result
        assert len(result["components"]) == 2
        assert "component_stats" in result
        assert result["n_face"] == healpix_wind_dataset.uxgrid.n_face

    def test_stats_have_required_keys(self, healpix_wind_dataset):
        result = compute_gradient(healpix_wind_dataset, "temperature")
        for comp in result["components"]:
            stats = result["component_stats"][comp]
            assert set(stats.keys()) >= {"min", "max", "mean"}

    def test_missing_variable_raises(self, healpix_wind_dataset):
        with pytest.raises(ValueError, match="not found"):
            compute_gradient(healpix_wind_dataset, "nonexistent")

    def test_non_face_centered_raises(self, healpix_wind_dataset):
        import xarray as xr

        node_var = ux.UxDataArray(
            xr.DataArray(np.ones(healpix_wind_dataset.uxgrid.n_node), dims=["n_node"]),
            uxgrid=healpix_wind_dataset.uxgrid,
        )
        ds = healpix_wind_dataset.assign({"node_var": node_var})
        with pytest.raises(ValueError, match="not face-centered"):
            compute_gradient(ds, "node_var")


# ---------------------------------------------------------------------------
# Domain: compute_curl
# ---------------------------------------------------------------------------


class TestComputeCurl:
    def test_returns_stats(self, healpix_wind_dataset):
        result = compute_curl(healpix_wind_dataset, "u", "v")
        assert "stats" in result
        assert set(result["stats"].keys()) >= {"min", "max", "mean", "std"}

    def test_interpretation_present(self, healpix_wind_dataset):
        result = compute_curl(healpix_wind_dataset, "u", "v")
        assert "vorticity" in result["interpretation"].lower()
        assert "∂v/∂x" in result["interpretation"]

    def test_n_face_correct(self, healpix_wind_dataset):
        result = compute_curl(healpix_wind_dataset, "u", "v")
        assert result["n_face"] == healpix_wind_dataset.uxgrid.n_face

    def test_missing_u_raises(self, healpix_wind_dataset):
        with pytest.raises(ValueError, match="not found"):
            compute_curl(healpix_wind_dataset, "bad_u", "v")

    def test_missing_v_raises(self, healpix_wind_dataset):
        with pytest.raises(ValueError, match="not found"):
            compute_curl(healpix_wind_dataset, "u", "bad_v")


# ---------------------------------------------------------------------------
# Domain: compute_divergence
# ---------------------------------------------------------------------------


class TestComputeDivergence:
    def test_returns_stats(self, healpix_wind_dataset):
        result = compute_divergence(healpix_wind_dataset, "u", "v")
        assert "stats" in result
        assert set(result["stats"].keys()) >= {"min", "max", "mean", "std"}

    def test_interpretation_present(self, healpix_wind_dataset):
        result = compute_divergence(healpix_wind_dataset, "u", "v")
        assert "divergence" in result["interpretation"].lower()
        assert "∂u/∂x" in result["interpretation"]

    def test_n_face_correct(self, healpix_wind_dataset):
        result = compute_divergence(healpix_wind_dataset, "u", "v")
        assert result["n_face"] == healpix_wind_dataset.uxgrid.n_face

    def test_missing_variable_raises(self, healpix_wind_dataset):
        with pytest.raises(ValueError, match="not found"):
            compute_divergence(healpix_wind_dataset, "u", "bad_v")


# ---------------------------------------------------------------------------
# Domain: compute_azimuthal_mean
# ---------------------------------------------------------------------------


class TestComputeAzimuthalMean:
    def test_returns_radial_profile(self, healpix_wind_dataset):
        result = compute_azimuthal_mean(
            healpix_wind_dataset,
            "temperature",
            center_lon=0.0,
            center_lat=0.0,
            outer_radius=30.0,
            radius_step=5.0,
        )
        assert "radii_deg" in result
        assert "azimuthal_mean_values" in result
        assert len(result["radii_deg"]) == len(result["azimuthal_mean_values"])

    def test_center_recorded(self, healpix_wind_dataset):
        result = compute_azimuthal_mean(
            healpix_wind_dataset,
            "temperature",
            center_lon=-90.0,
            center_lat=25.0,
            outer_radius=10.0,
            radius_step=2.0,
        )
        assert result["center"]["lon"] == -90.0
        assert result["center"]["lat"] == 25.0

    def test_missing_variable_raises(self, healpix_wind_dataset):
        with pytest.raises(ValueError, match="not found"):
            compute_azimuthal_mean(
                healpix_wind_dataset,
                "bad_var",
                center_lon=0.0,
                center_lat=0.0,
                outer_radius=10.0,
                radius_step=2.0,
            )


# ---------------------------------------------------------------------------
# Tool layer — provenance and file-loading (mocked)
# ---------------------------------------------------------------------------


def _make_mock_uxds(healpix_wind_dataset):
    """Patch uxarray.open_dataset globally to return the fixture dataset."""
    return patch("uxarray.open_dataset", return_value=healpix_wind_dataset)


class TestCalculateGradientTool:
    def test_provenance_attached(self, healpix_wind_dataset):
        with _make_mock_uxds(healpix_wind_dataset):
            result = calculate_gradient("grid.nc", "data.nc", "temperature")
        assert "_provenance" in result
        assert result["_provenance"]["tool"] == "calculate_gradient"

    def test_use_remote_false_stays_local(self, healpix_wind_dataset):
        with _make_mock_uxds(healpix_wind_dataset):
            result = calculate_gradient(
                "grid.nc", "data.nc", "temperature", use_remote=False
            )
        assert result["_provenance"]["execution_venue"] == "local"

    def test_missing_variable_propagates(self, healpix_wind_dataset):
        with _make_mock_uxds(healpix_wind_dataset):
            with pytest.raises(ValueError, match="not found"):
                calculate_gradient("grid.nc", "data.nc", "bad_var")

    def test_accepts_use_remote_endpoint_session_params(self, healpix_wind_dataset):
        import inspect

        sig = inspect.signature(calculate_gradient)
        assert "use_remote" in sig.parameters
        assert "endpoint" in sig.parameters
        assert "session_id" in sig.parameters


class TestCalculateCurlTool:
    def test_provenance_attached(self, healpix_wind_dataset):
        with _make_mock_uxds(healpix_wind_dataset):
            result = calculate_curl("grid.nc", "data.nc", "u", "v")
        assert "_provenance" in result
        assert result["_provenance"]["tool"] == "calculate_curl"

    def test_inputs_recorded(self, healpix_wind_dataset):
        with _make_mock_uxds(healpix_wind_dataset):
            result = calculate_curl("grid.nc", "data.nc", "u", "v")
        assert result["_provenance"]["inputs"]["u_variable"] == "u"
        assert result["_provenance"]["inputs"]["v_variable"] == "v"

    def test_use_remote_false_stays_local(self, healpix_wind_dataset):
        with _make_mock_uxds(healpix_wind_dataset):
            result = calculate_curl("grid.nc", "data.nc", "u", "v", use_remote=False)
        assert result["_provenance"]["execution_venue"] == "local"

    def test_accepts_use_remote_endpoint_session_params(self):
        import inspect

        sig = inspect.signature(calculate_curl)
        assert "use_remote" in sig.parameters
        assert "endpoint" in sig.parameters
        assert "session_id" in sig.parameters


class TestCalculateDivergenceTool:
    def test_provenance_attached(self, healpix_wind_dataset):
        with _make_mock_uxds(healpix_wind_dataset):
            result = calculate_divergence("grid.nc", "data.nc", "u", "v")
        assert "_provenance" in result
        assert result["_provenance"]["tool"] == "calculate_divergence"

    def test_use_remote_false_stays_local(self, healpix_wind_dataset):
        with _make_mock_uxds(healpix_wind_dataset):
            result = calculate_divergence(
                "grid.nc", "data.nc", "u", "v", use_remote=False
            )
        assert result["_provenance"]["execution_venue"] == "local"

    def test_accepts_use_remote_endpoint_session_params(self):
        import inspect

        sig = inspect.signature(calculate_divergence)
        assert "use_remote" in sig.parameters
        assert "endpoint" in sig.parameters
        assert "session_id" in sig.parameters


class TestCalculateAzimuthalMeanTool:
    def test_provenance_attached(self, healpix_wind_dataset):
        with _make_mock_uxds(healpix_wind_dataset):
            result = calculate_azimuthal_mean(
                "grid.nc",
                "data.nc",
                "temperature",
                center_lon=0.0,
                center_lat=0.0,
                outer_radius=30.0,
                radius_step=5.0,
            )
        assert "_provenance" in result
        assert result["_provenance"]["tool"] == "calculate_azimuthal_mean"

    def test_center_in_inputs(self, healpix_wind_dataset):
        with _make_mock_uxds(healpix_wind_dataset):
            result = calculate_azimuthal_mean(
                "grid.nc",
                "data.nc",
                "temperature",
                center_lon=-45.0,
                center_lat=15.0,
                outer_radius=20.0,
                radius_step=2.0,
            )
        assert result["_provenance"]["inputs"]["center_lon"] == -45.0
        assert result["_provenance"]["inputs"]["center_lat"] == 15.0

    def test_use_remote_false_stays_local(self, healpix_wind_dataset):
        with _make_mock_uxds(healpix_wind_dataset):
            result = calculate_azimuthal_mean(
                "grid.nc",
                "data.nc",
                "temperature",
                center_lon=0.0,
                center_lat=0.0,
                outer_radius=30.0,
                radius_step=5.0,
                use_remote=False,
            )
        assert result["_provenance"]["execution_venue"] == "local"

    def test_accepts_use_remote_endpoint_session_params(self):
        import inspect

        sig = inspect.signature(calculate_azimuthal_mean)
        assert "use_remote" in sig.parameters
        assert "endpoint" in sig.parameters
        assert "session_id" in sig.parameters


# ---------------------------------------------------------------------------
# Server registration
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_vector_calc_operations_available_through_run_analysis():
    from uxarray_mcp.server import mcp

    if hasattr(mcp, "get_tools"):
        tools = await mcp.get_tools()
    else:
        tools_list = await mcp.list_tools()
        tools = {t.name: t for t in tools_list}

    assert "run_analysis" in tools
    for name in ("gradient", "curl", "divergence", "azimuthal_mean"):
        assert name in tools["run_analysis"].description


@pytest.mark.asyncio
async def test_prompts_registered():
    from uxarray_mcp.server import mcp

    if hasattr(mcp, "get_prompts"):
        prompts = await mcp.get_prompts()
    else:
        try:
            prompts_list = await mcp.list_prompts()
            prompts = {p.name: p for p in prompts_list}
        except Exception:
            pytest.skip("MCP client does not support prompt listing")
            return

    for name in ("first_look", "vorticity_analysis", "hpc_diagnose"):
        assert name in prompts, f"Prompt '{name}' not registered"
