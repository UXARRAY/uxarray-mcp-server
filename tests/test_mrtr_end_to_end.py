"""End-to-end MRTR refusal through the real run_analysis front door (#86)."""

from __future__ import annotations

import warnings

import numpy as np
import pytest
import uxarray as ux
import xarray as xr

from uxarray_mcp.preconditions import OVERRIDE_TOKEN, PreconditionRefusal
from uxarray_mcp.tools.frontdoor import run_analysis


def _write_wind_files(tmp_path, labeled: bool):
    lon = np.arange(0, 360, 20.0)
    lat = np.arange(-80, 81, 20.0)
    grid = ux.Grid.from_structured(lon=lon, lat=lat)
    grid_file = tmp_path / f"grid_{labeled}.nc"
    data_file = tmp_path / f"wind_{labeled}.nc"
    grid_ds = grid.to_xarray()
    # A real sphere radius, so scale_by_radius=True actually applies and the
    # unit-sphere fallback warning does not fire.
    grid_ds.attrs["sphere_radius"] = 6371000.0
    grid_ds.to_netcdf(grid_file)

    rng = np.random.default_rng(5)
    n = grid.n_face
    u_attrs = {"units": "m s-1", "standard_name": "eastward_wind"} if labeled else {}
    v_attrs = {"units": "m s-1", "standard_name": "northward_wind"} if labeled else {}
    xr.Dataset(
        {
            "u": (["n_face"], rng.standard_normal(n), u_attrs),
            "v": (["n_face"], rng.standard_normal(n), v_attrs),
        }
    ).to_netcdf(data_file)
    return str(grid_file), str(data_file)


@pytest.fixture
def unlabeled_wind_files(tmp_path):
    return _write_wind_files(tmp_path, labeled=False)


@pytest.fixture
def labeled_wind_files(tmp_path):
    return _write_wind_files(tmp_path, labeled=True)


def _call(files, **kwargs):
    grid_file, data_file = files
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return run_analysis(
            operation="curl",
            grid_path=grid_file,
            data_path=data_file,
            u_variable="u",
            v_variable="v",
            **kwargs,
        )


def test_unlabeled_components_refuse_end_to_end(state_dir, unlabeled_wind_files):
    result = _call(unlabeled_wind_files)

    assert result["outcome"] == "input_required"
    assert {c["id"] for c in result["refusal"]["failed_checks"]} == {
        "velocity_units",
        "component_identity",
    }
    # The number must not be present: refusing means not answering.
    assert "stats" not in result
    assert "curl" not in result


def test_override_returns_an_explicitly_unverified_number(
    state_dir, unlabeled_wind_files
):
    result = _call(unlabeled_wind_files, acknowledge=OVERRIDE_TOKEN)

    assert result["outcome"] == "complete"
    assert result["preconditions"]["status"] == "overridden"
    assert result["scientific_status"]["physically_interpretable"] is False
    assert result["scientific_status"]["status"] == "unverified"
    assert result["stats"]["mean"] is not None


def test_labeled_components_pass_every_precondition(state_dir, labeled_wind_files):
    result = _call(labeled_wind_files)

    assert result["outcome"] == "complete"
    assert result["preconditions"]["status"] == "satisfied"
    assert result["preconditions"]["failed_checks"] == []
    assert result["scientific_status"]["physically_interpretable"] is True


def test_unscaled_curl_refuses_even_with_good_metadata(state_dir, labeled_wind_files):
    result = _call(labeled_wind_files, scale_by_radius=False)

    assert result["outcome"] == "input_required"
    assert [c["id"] for c in result["refusal"]["failed_checks"]] == ["radius_scaling"]


@pytest.mark.parametrize("acknowledge", [None, OVERRIDE_TOKEN])
def test_no_result_reuses_the_protocols_field_name(
    state_dir, unlabeled_wind_files, acknowledge
):
    """`result_type` must not come back under either shape.

    The SDK puts its own `resultType` on the result object and always sets it
    to "complete", since the call did return. Our field says something else --
    which payload shape this is -- and a refusal carrying both would put two
    same-named fields with contradicting values on one wire.
    """
    kwargs = {"acknowledge": acknowledge} if acknowledge else {}
    result = _call(unlabeled_wind_files, **kwargs)

    assert "result_type" not in result
    assert result["outcome"] in {"complete", "input_required"}


def test_refusal_is_not_raised_through_the_tool_boundary(
    state_dir, unlabeled_wind_files
):
    """The front door returns the refusal as data, never as an exception."""
    try:
        result = _call(unlabeled_wind_files)
    except PreconditionRefusal:  # pragma: no cover - the bug this guards
        pytest.fail("PreconditionRefusal escaped run_analysis")
    assert "_provenance" in result
