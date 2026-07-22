"""Tests for vector calculus and azimuthal mean tools."""

from __future__ import annotations

import warnings
from unittest.mock import MagicMock, patch

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


def _make_wind_dataset(with_units: bool = False):
    """Build a small HEALPix UxDataset with synthetic u, v, temperature fields."""
    import xarray as xr

    grid = ux.Grid.from_healpix(zoom=2)
    n = grid.n_face
    rng = np.random.default_rng(42)
    u_attrs = {"units": "m/s"} if with_units else {}
    v_attrs = {"units": "m/s"} if with_units else {}

    u_data = xr.DataArray(
        rng.standard_normal(n).astype(np.float64), dims=["n_face"], attrs=u_attrs
    )
    v_data = xr.DataArray(
        rng.standard_normal(n).astype(np.float64), dims=["n_face"], attrs=v_attrs
    )
    scalar = xr.DataArray(
        np.abs(rng.standard_normal(n).astype(np.float64)), dims=["n_face"]
    )

    return ux.UxDataset(
        {
            "u": ux.UxDataArray(u_data, uxgrid=grid),
            "v": ux.UxDataArray(v_data, uxgrid=grid),
            "temperature": ux.UxDataArray(scalar, uxgrid=grid),
        },
        uxgrid=grid,
    )


@pytest.fixture()
def healpix_wind_dataset():
    """Return a small HEALPix UxDataset with synthetic u and v wind fields."""
    return _make_wind_dataset(with_units=False)


def _make_multidim_wind_dataset():
    """Build a HEALPix UxDataset with (time, lev, n_face) u/v, like real model
    output (e.g. E3SM ``U``/``V`` with shape (time, lev, ncol))."""
    import xarray as xr

    grid = ux.Grid.from_healpix(zoom=2)
    n = grid.n_face
    n_time, n_lev = 2, 3
    rng = np.random.default_rng(7)

    u_data = xr.DataArray(
        rng.standard_normal((n_time, n_lev, n)).astype(np.float64),
        dims=["time", "lev", "n_face"],
        attrs={"units": "m/s"},
    )
    v_data = xr.DataArray(
        rng.standard_normal((n_time, n_lev, n)).astype(np.float64),
        dims=["time", "lev", "n_face"],
        attrs={"units": "m/s"},
    )

    return ux.UxDataset(
        {
            "u": ux.UxDataArray(u_data, uxgrid=grid),
            "v": ux.UxDataArray(v_data, uxgrid=grid),
        },
        uxgrid=grid,
    )


@pytest.fixture()
def healpix_multidim_wind_dataset():
    """Return a HEALPix UxDataset with (time, lev, n_face) u and v fields."""
    return _make_multidim_wind_dataset()


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
# Domain: time_index / level_index selection on real-shaped (time, lev,
# n_face) data — the shape genuine model output (e.g. E3SM U/V) actually has.
# ---------------------------------------------------------------------------


class TestMultiDimSelection:
    def test_curl_without_selection_raises(self, healpix_multidim_wind_dataset):
        with pytest.raises(Exception):
            healpix_multidim_wind_dataset["u"].curl(healpix_multidim_wind_dataset["v"])

    def test_curl_selects_time_and_level(self, healpix_multidim_wind_dataset):
        result = compute_curl(
            healpix_multidim_wind_dataset, "u", "v", time_index=1, level_index=2
        )
        assert result["n_face"] == healpix_multidim_wind_dataset.uxgrid.n_face
        assert result["stats"]["min"] is not None

    def test_curl_matches_manual_isel(self, healpix_multidim_wind_dataset):
        result = compute_curl(
            healpix_multidim_wind_dataset, "u", "v", time_index=0, level_index=1
        )
        u = healpix_multidim_wind_dataset["u"].isel(time=0, lev=1)
        v = healpix_multidim_wind_dataset["v"].isel(time=0, lev=1)
        expected = u.curl(v)
        finite = expected.values[np.isfinite(expected.values)]
        assert result["stats"]["mean"] == pytest.approx(float(finite.mean()))

    def test_divergence_selects_time_and_level(self, healpix_multidim_wind_dataset):
        result = compute_divergence(
            healpix_multidim_wind_dataset, "u", "v", time_index=1, level_index=0
        )
        assert result["stats"]["min"] is not None

    def test_gradient_selects_time_and_level(self, healpix_multidim_wind_dataset):
        result = compute_gradient(
            healpix_multidim_wind_dataset, "u", time_index=1, level_index=0
        )
        assert len(result["components"]) == 2

    def test_default_indices_select_first_slice(self, healpix_multidim_wind_dataset):
        result = compute_curl(healpix_multidim_wind_dataset, "u", "v")
        u = healpix_multidim_wind_dataset["u"].isel(time=0, lev=0)
        v = healpix_multidim_wind_dataset["v"].isel(time=0, lev=0)
        expected = u.curl(v)
        finite = expected.values[np.isfinite(expected.values)]
        assert result["stats"]["mean"] == pytest.approx(float(finite.mean()))

    def test_calculate_curl_tool_accepts_indices(self, healpix_multidim_wind_dataset):
        with _make_mock_uxds(healpix_multidim_wind_dataset):
            result = calculate_curl(
                "grid.nc", "data.nc", "u", "v", time_index=1, level_index=2
            )
        assert result["_provenance"]["inputs"]["time_index"] == 1
        assert result["_provenance"]["inputs"]["level_index"] == 2
        assert result["stats"]["min"] is not None


# ---------------------------------------------------------------------------
# Domain: vector-component semantic guardrail (curl / divergence)
# ---------------------------------------------------------------------------


class TestVectorComponentGuardrail:
    """curl/divergence should warn (not block) on suspicious vector inputs."""

    def test_same_field_warns_curl(self, healpix_wind_dataset):
        result = compute_curl(healpix_wind_dataset, "u", "u")
        warns = result["component_warnings"]
        assert any("same field" in w for w in warns)
        # Result is still computed (math is valid), just flagged.
        assert result["stats"] is not None

    def test_same_field_warns_divergence(self, healpix_wind_dataset):
        result = compute_divergence(healpix_wind_dataset, "u", "u")
        assert any("same field" in w for w in result["component_warnings"])

    def test_missing_units_warns(self, healpix_wind_dataset):
        # Synthetic fields carry no 'units' attr → non-velocity warning.
        result = compute_curl(healpix_wind_dataset, "u", "v")
        assert any("velocity" in w for w in result["component_warnings"])

    def test_velocity_units_suppress_warning(self):
        # Fields with velocity units set at creation time → no warnings.
        ds = _make_wind_dataset(with_units=True)
        result = compute_curl(ds, "u", "v")
        assert result["component_warnings"] == []

    def test_curl_warning_reaches_provenance(self, monkeypatch):
        """The tool layer surfaces component warnings into _provenance.warnings."""
        from uxarray_mcp.tools import vector_calc as vc_tools

        # Avoid file I/O round-trips: feed the tool the in-memory dataset.
        ds = _make_wind_dataset(with_units=False)
        monkeypatch.setattr(vc_tools, "load_dataset", lambda *a, **k: ds)

        result = vc_tools.calculate_curl("grid.nc", "data.nc", "u", "u")
        assert any("same field" in w for w in result["_provenance"]["warnings"])


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
# scale_by_radius opt-in
# ---------------------------------------------------------------------------


class TestScaleByRadius:
    def test_gradient_default_keeps_unit_sphere(self, healpix_wind_dataset):
        result = compute_gradient(healpix_wind_dataset, "temperature")
        assert result["scale_by_radius"] is False

    def test_curl_default_keeps_unit_sphere(self, healpix_wind_dataset):
        result = compute_curl(healpix_wind_dataset, "u", "v")
        assert result["scale_by_radius"] is False

    def test_gradient_records_scale_by_radius_flag(self, healpix_wind_dataset):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")  # grid has no sphere_radius
            result = compute_gradient(
                healpix_wind_dataset, "temperature", scale_by_radius=True
            )
        assert result["scale_by_radius"] is True

    def test_remote_gradient_threads_scale_by_radius(self):
        """The remote dispatch must forward scale_by_radius to the agent."""
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

        args, kwargs = agent.calculate_gradient_remote.call_args
        assert (True in args) or (kwargs.get("scale_by_radius") is True)


# ---------------------------------------------------------------------------
# Server registration
# ---------------------------------------------------------------------------


def test_vector_calc_operations_available_through_run_analysis():
    """run_analysis must advertise vector calc operations in its description."""
    from uxarray_mcp.app import make_registry

    registry = make_registry(profile="core")
    tool = registry.get_tool("run_analysis")
    assert tool is not None
    for name in ("gradient", "curl", "divergence", "azimuthal_mean"):
        assert name in tool.description, (
            f"{name!r} not mentioned in run_analysis description"
        )


def test_prompts_registered_as_tools():
    """Former @mcp.prompt() decorators are now prompt/ namespace tools."""
    from uxarray_mcp.app import make_registry

    registry = make_registry(profile="core")
    tools = registry.list_tools()
    sep = registry._name_sep
    for name in ("first_look", "vorticity_analysis", "hpc_diagnose"):
        assert f"prompt{sep}{name}" in tools, f"prompt tool {name} missing"
