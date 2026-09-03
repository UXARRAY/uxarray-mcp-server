"""Ensemble statistics are arithmetic across files, and the files have to agree.

Before this gate, `ensemble_mean` of a member in K and a member in degC returned
145.0 with `outcome: "complete"`, `preconditions.status: "not_evaluated"` and no
warning codes -- a number in neither scale, presented as an answer.
"""

from __future__ import annotations

import numpy as np
import pytest
import xarray as xr

from uxarray_mcp.preconditions import (
    OVERRIDE_TOKEN,
    evaluate_ensemble_preconditions,
)
from uxarray_mcp.tools.advanced import _member_grid_fingerprint
from uxarray_mcp.tools.frontdoor import run_analysis


def _write_member(path, *, units="K", offset=0.0, coords=None):
    data = {"temperature": (["n_face"], offset + np.arange(4.0), {"units": units})}
    if units is None:
        data["temperature"] = (["n_face"], offset + np.arange(4.0), {})
    ds = xr.Dataset(data, coords=coords or {})
    ds.to_netcdf(path)
    return str(path)


@pytest.fixture
def face_coords():
    return {
        "face_lon": ("n_face", np.array([0.0, 10.0, 20.0, 30.0])),
        "face_lat": ("n_face", np.array([0.0, 1.0, 2.0, 3.0])),
    }


class TestMemberGridFingerprint:
    """What a member file says about the mesh its values sit on."""

    def test_no_recognisable_coordinates_is_unknown_not_equal(self):
        """Matching dims are not evidence of a matching mesh."""
        ds = xr.Dataset({"temperature": (["n_face"], np.arange(4.0))})
        assert _member_grid_fingerprint(ds, ds["temperature"]) is None

    def test_same_coordinates_hash_the_same(self, face_coords):
        first = xr.Dataset({"t": (["n_face"], np.arange(4.0))}, coords=face_coords)
        second = xr.Dataset({"t": (["n_face"], np.ones(4))}, coords=face_coords)

        assert _member_grid_fingerprint(first, first["t"]) == _member_grid_fingerprint(
            second, second["t"]
        )

    def test_different_coordinates_hash_differently(self, face_coords):
        first = xr.Dataset({"t": (["n_face"], np.arange(4.0))}, coords=face_coords)
        moved = dict(face_coords)
        moved["face_lon"] = ("n_face", np.array([0.0, 10.0, 20.0, 31.0]))
        second = xr.Dataset({"t": (["n_face"], np.arange(4.0))}, coords=moved)

        assert _member_grid_fingerprint(first, first["t"]) != _member_grid_fingerprint(
            second, second["t"]
        )


class TestEvaluateEnsemblePreconditions:
    def test_declared_disagreement_fails(self):
        checks = evaluate_ensemble_preconditions(
            "ensemble_mean",
            "temperature",
            {"member_units": ["K", "degC"], "units_consistent": False},
        )

        assert [c["id"] for c in checks if not c["passed"]] == [
            "ensemble_units_consistent"
        ]

    def test_undeclared_units_do_not_fail(self):
        """A gap in metadata is not a contradiction, so it must not refuse."""
        checks = evaluate_ensemble_preconditions(
            "ensemble_mean",
            "temperature",
            {"member_units": ["K", None], "units_consistent": None},
        )

        assert all(c["passed"] for c in checks)

    def test_unverified_mesh_does_not_add_a_failing_check(self):
        checks = evaluate_ensemble_preconditions(
            "ensemble_mean",
            "temperature",
            {"member_units": ["K", "K"], "units_consistent": True},
        )

        assert all(c["passed"] for c in checks)
        assert "ensemble_grids_consistent" not in {c["id"] for c in checks}

    def test_contradicting_meshes_fail(self):
        checks = evaluate_ensemble_preconditions(
            "ensemble_mean",
            "temperature",
            {
                "member_units": ["K", "K"],
                "units_consistent": True,
                "grids_consistent": False,
            },
        )

        assert [c["id"] for c in checks if not c["passed"]] == [
            "ensemble_grids_consistent"
        ]


@pytest.mark.parametrize("operation", ["ensemble_mean", "ensemble_spread"])
class TestEnsembleFrontDoor:
    def test_mismatched_units_refuse_without_a_number(
        self, state_dir, tmp_path, operation, face_coords
    ):
        paths = [
            _write_member(
                tmp_path / "k.nc", units="K", offset=280.0, coords=face_coords
            ),
            _write_member(
                tmp_path / "c.nc", units="degC", offset=7.0, coords=face_coords
            ),
        ]

        result = run_analysis(
            operation=operation, variable_name="temperature", data_paths=paths
        )

        assert result["outcome"] == "input_required"
        assert [c["id"] for c in result["refusal"]["failed_checks"]] == [
            "ensemble_units_consistent"
        ]
        assert "summary" not in result

    def test_override_returns_the_number_marked_unverified(
        self, state_dir, tmp_path, operation, face_coords
    ):
        paths = [
            _write_member(
                tmp_path / "k.nc", units="K", offset=280.0, coords=face_coords
            ),
            _write_member(
                tmp_path / "c.nc", units="degC", offset=7.0, coords=face_coords
            ),
        ]

        result = run_analysis(
            operation=operation,
            variable_name="temperature",
            data_paths=paths,
            acknowledge=OVERRIDE_TOKEN,
        )

        assert result["outcome"] == "complete"
        assert result["preconditions"]["status"] == "overridden"
        assert result["scientific_status"]["physically_interpretable"] is False

    def test_matching_units_and_meshes_complete_clean(
        self, state_dir, tmp_path, operation, face_coords
    ):
        paths = [
            _write_member(tmp_path / "a.nc", offset=280.0, coords=face_coords),
            _write_member(tmp_path / "b.nc", offset=284.0, coords=face_coords),
        ]

        result = run_analysis(
            operation=operation, variable_name="temperature", data_paths=paths
        )

        assert result["outcome"] == "complete"
        assert result["scientific_status"]["warning_codes"] == []
        assert result["member_evidence"]["grid_evidence"] == "coordinates"

    def test_undeclared_units_warn_rather_than_refuse(
        self, state_dir, tmp_path, operation, face_coords
    ):
        paths = [
            _write_member(tmp_path / "a.nc", offset=280.0, coords=face_coords),
            _write_member(
                tmp_path / "b.nc", units=None, offset=284.0, coords=face_coords
            ),
        ]

        result = run_analysis(
            operation=operation, variable_name="temperature", data_paths=paths
        )

        assert result["outcome"] == "complete"
        assert (
            "ENSEMBLE_UNITS_UNDECLARED" in result["scientific_status"]["warning_codes"]
        )

    def test_members_without_coordinates_report_the_mesh_unverified(
        self, state_dir, tmp_path, operation
    ):
        """Same shape is not the same mesh, and the result must not imply it is."""
        paths = [
            _write_member(tmp_path / "a.nc", offset=280.0),
            _write_member(tmp_path / "b.nc", offset=284.0),
        ]

        result = run_analysis(
            operation=operation, variable_name="temperature", data_paths=paths
        )

        assert result["outcome"] == "complete"
        assert (
            "ENSEMBLE_GRID_UNVERIFIED" in result["scientific_status"]["warning_codes"]
        )
        assert result["member_evidence"]["grid_evidence"] == "dims_and_shape_only"
