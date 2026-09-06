"""An export must say what it lost on the way to the file.

``export`` was the one operation returning ``status: "complete"`` with no
check of any kind behind it: the three functions in ``tools/advanced.py``
contained no ``stat``, ``getsize`` or ``nbytes`` call, so "complete" meant
``to_csv`` returned without raising.

Measured on a 9-face grid carrying ``sst`` (units K, a long_name, and a CF
``grid_mapping: crs``), ``salinity`` (units psu), a scalar ``crs``
container and global ``title``/``Conventions``:

- CSV of the whole dataset: 129 bytes, all 8 attributes gone, the single
  NaN written as ``2,,2.0,0``, and ``rows_written: 9`` read off the
  in-memory DataFrame rather than the file.
- NetCDF of ``sst`` alone: 8264 bytes, one variable, ``salinity`` and
  ``crs`` dropped, and ``sst`` still carrying ``grid_mapping: "crs"``
  into a file with no ``crs`` in it.

Both replies said ``complete`` with an empty ``warning_codes``.
"""

from __future__ import annotations

import numpy as np
import pytest
import xarray as xr

from uxarray_mcp.domain.export_fidelity import export_fidelity_warning_codes
from uxarray_mcp.state import create_session, register_dataset
from uxarray_mcp.tools.frontdoor import run_analysis

ux = pytest.importorskip("uxarray")


@pytest.fixture
def lossy_dataset(state_dir, tmp_path):
    """A dataset carrying everything CSV cannot represent.

    Units, a long_name, global attributes, one missing value and a CF
    grid-mapping container -- the five things an export can silently drop,
    on one small grid so the counts in the assertions are checkable by
    hand.
    """
    grid_file = tmp_path / "grid.nc"
    data_file = tmp_path / "data.nc"
    grid = ux.Grid.from_structured(
        lon=np.arange(0, 360, 120.0), lat=np.arange(-30, 31, 30.0)
    )
    grid.to_xarray().to_netcdf(grid_file)

    n_face = int(grid.n_face)
    sst = np.arange(n_face, dtype="float64")
    sst[2] = np.nan
    xr.Dataset(
        {
            "sst": (
                ["n_face"],
                sst,
                {"units": "K", "long_name": "sea surface temp", "grid_mapping": "crs"},
            ),
            "salinity": (
                ["n_face"],
                np.arange(n_face, dtype="float64"),
                {"units": "psu"},
            ),
            "crs": (
                (),
                np.int32(0),
                {
                    "grid_mapping_name": "latitude_longitude",
                    "earth_radius": 6371000.0,
                },
            ),
        },
        attrs={"title": "demo", "Conventions": "CF-1.8"},
    ).to_netcdf(data_file)

    session = create_session("export-fidelity")["session_id"]
    handle = register_dataset(
        session, grid_path=str(grid_file), data_path=str(data_file)
    )["dataset_handle"]
    return session, handle, n_face


def _export(session, handle, output_path, output_format, **kwargs):
    return run_analysis(
        operation="export",
        output_path=str(output_path),
        output_format=output_format,
        session_id=session,
        dataset_handle=handle,
        **kwargs,
    )


class TestTheCsvSaysWhatItCouldNotCarry:
    def test_the_dropped_attributes_are_counted(self, lossy_dataset, tmp_path):
        session, handle, _ = lossy_dataset
        result = _export(session, handle, tmp_path / "out.csv", "csv")
        fidelity = result["export_fidelity"]
        # 6 on the three variables, 2 global.
        assert fidelity["attributes_dropped"] == 8
        assert (
            "EXPORT_ATTRIBUTES_DROPPED" in result["scientific_status"]["warning_codes"]
        )

    def test_the_missing_value_is_named_and_so_is_its_spelling(
        self, lossy_dataset, tmp_path
    ):
        """An empty CSV field is indistinguishable from an unwritten one.

        Nothing in the file says which of the two it is, so the reply has
        to.
        """
        session, handle, _ = lossy_dataset
        output = tmp_path / "out.csv"
        result = _export(session, handle, output, "csv")
        fidelity = result["export_fidelity"]
        assert fidelity["missing_values"] == 1
        assert fidelity["missing_written_as"] == "empty field"
        assert ",," in output.read_text()

    def test_the_row_count_comes_off_the_file(self, lossy_dataset, tmp_path):
        session, handle, n_face = lossy_dataset
        output = tmp_path / "out.csv"
        result = _export(session, handle, output, "csv")
        fidelity = result["export_fidelity"]
        assert fidelity["rows_written"] == n_face
        assert fidelity["rows_expected"] == n_face
        assert result["summary"]["rows_written"] == n_face
        # The header is not a row, and the file is the only witness.
        assert len(output.read_text().strip().splitlines()) == n_face + 1
        assert fidelity["bytes_written"] == output.stat().st_size

    def test_an_export_of_one_variable_names_the_ones_left_behind(
        self, lossy_dataset, tmp_path
    ):
        session, handle, _ = lossy_dataset
        result = _export(
            session, handle, tmp_path / "one.csv", "csv", variable_name="sst"
        )
        fidelity = result["export_fidelity"]
        assert fidelity["variables_dropped"] == ["crs", "salinity"]
        assert (
            "EXPORT_VARIABLES_DROPPED" in result["scientific_status"]["warning_codes"]
        )


class TestTheNetcdfSaysWhatItLeftBehind:
    def test_a_single_variable_export_reports_the_dangling_crs(
        self, lossy_dataset, tmp_path
    ):
        """``sst`` keeps pointing at a container that is not in the file.

        Worse than declaring no CRS at all: the attribute tells a CF
        reader where to look and the place is empty.
        """
        session, handle, _ = lossy_dataset
        output = tmp_path / "one.nc"
        result = _export(session, handle, output, "netcdf", variable_name="sst")
        fidelity = result["export_fidelity"]
        assert fidelity["dangling_grid_mapping"] == ["crs"]
        assert fidelity["variables_dropped"] == ["crs", "salinity"]
        assert fidelity["n_variables_written"] == 1

        with xr.open_dataset(output) as back:
            assert back["sst"].attrs["grid_mapping"] == "crs"
            assert "crs" not in back.variables

    def test_netcdf_keeps_the_attributes_csv_cannot(self, lossy_dataset, tmp_path):
        """The two formats lose different things, and the block says which."""
        session, handle, _ = lossy_dataset
        result = _export(
            session, handle, tmp_path / "one.nc", "netcdf", variable_name="sst"
        )
        assert result["export_fidelity"]["attributes_dropped"] == 0
        assert result["export_fidelity"]["missing_values"] == 0

    def test_a_whole_dataset_copy_loses_nothing(self, lossy_dataset, tmp_path):
        """A byte copy is the one export with nothing to disclose."""
        session, handle, _ = lossy_dataset
        result = _export(session, handle, tmp_path / "all.nc", "netcdf")
        fidelity = result["export_fidelity"]
        assert export_fidelity_warning_codes(fidelity) == []
        assert fidelity["bytes_written"] > 0
        assert result["scientific_status"]["status"] == "complete"


class TestTheStatusFollowsTheMeasurement:
    def test_a_lossy_export_is_no_longer_reported_as_complete(
        self, lossy_dataset, tmp_path
    ):
        session, handle, _ = lossy_dataset
        result = _export(session, handle, tmp_path / "out.csv", "csv")
        status = result["scientific_status"]
        assert status["status"] == "warning"
        # Numbers in a file that no longer says what they measure are not
        # interpretable, and the export is the last place anyone can see it.
        assert status["physically_interpretable"] is False
        assert sorted(status["warning_codes"]) == [
            "EXPORT_ATTRIBUTES_DROPPED",
            "EXPORT_MISSING_VALUES_UNMARKED",
        ]

    def test_the_file_is_still_written(self, lossy_dataset, tmp_path):
        """Warned, not refused. A lossy export is still the export asked for."""
        session, handle, _ = lossy_dataset
        output = tmp_path / "out.csv"
        result = _export(session, handle, output, "csv")
        assert output.exists()
        assert result["output_path"] == str(output)
        assert result["outcome"] == "complete"


class TestAnAbsentBlockIsNotACleanBill:
    def test_no_measurement_raises_no_codes(self):
        assert export_fidelity_warning_codes({}) == []

    def test_an_empty_file_is_a_code_of_its_own(self):
        assert export_fidelity_warning_codes({"bytes_written": 0}) == [
            "EXPORT_EMPTY_FILE"
        ]

    def test_a_short_write_is_caught_by_comparing_the_two_counts(self):
        codes = export_fidelity_warning_codes(
            {"bytes_written": 42, "rows_written": 3, "rows_expected": 9}
        )
        assert codes == ["EXPORT_ROW_COUNT_MISMATCH"]
