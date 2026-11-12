"""Export ops and NetCDF repairs in the pure core layer."""

from __future__ import annotations

import numpy as np
import pytest
import uxarray as ux
import xarray as xr

from uxarray_mcp.core.export import (
    drop_phantom_topology_attrs,
    export_dataarray,
    export_dataset,
    widen_narrow_fill_values,
    write_grid_artifact,
)


@pytest.fixture
def lossy_dataset():
    """Units, long_name, global attrs, one NaN and a CF grid_mapping container."""
    n_face = 9
    sst = np.arange(n_face, dtype="float64")
    sst[2] = np.nan
    return xr.Dataset(
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
            "crs": ((), np.int32(0), {"grid_mapping_name": "latitude_longitude"}),
        },
        attrs={"title": "demo", "Conventions": "CF-1.8"},
    )


def test_csv_export_counts_what_it_lost(lossy_dataset, tmp_path):
    output = tmp_path / "out.csv"
    result = export_dataset(lossy_dataset, str(output), "csv")
    fidelity = result["export_fidelity"]
    assert fidelity["attributes_dropped"] == 7
    assert fidelity["missing_values"] == 1
    assert fidelity["missing_written_as"] == "empty field"
    assert ",," in output.read_text()
    assert fidelity["rows_written"] == 9 == fidelity["rows_expected"]
    assert result["summary"]["rows_written"] == 9
    assert fidelity["bytes_written"] == output.stat().st_size
    assert sorted(result["warning_codes"]) == [
        "EXPORT_ATTRIBUTES_DROPPED",
        "EXPORT_MISSING_VALUES_UNMARKED",
    ]
    assert result["coverage"] is fidelity


def test_single_variable_netcdf_reports_siblings_and_dangling_crs(
    lossy_dataset, tmp_path
):
    output = tmp_path / "sst.nc"
    result = export_dataset(lossy_dataset, str(output), "netcdf", variable_name="sst")
    fidelity = result["export_fidelity"]
    assert fidelity["variables_dropped"] == ["crs", "salinity"]
    assert fidelity["dangling_grid_mapping"] == ["crs"]
    assert fidelity["n_variables_written"] == 1
    assert fidelity["attributes_dropped"] == 0
    assert result["warning_codes"] == [
        "EXPORT_VARIABLES_DROPPED",
        "EXPORT_DANGLING_GRID_MAPPING",
    ]
    with xr.open_dataset(output) as back:
        assert back["sst"].attrs["grid_mapping"] == "crs"
        assert "crs" not in back.variables
    with pytest.raises(ValueError, match="not found"):
        export_dataset(lossy_dataset, str(output), "netcdf", variable_name="nope")


def test_whole_dataset_netcdf_loses_nothing(lossy_dataset, tmp_path):
    result = export_dataset(lossy_dataset, str(tmp_path / "all.nc"))
    assert result["warning_codes"] == []
    assert result["export_fidelity"]["bytes_written"] > 0
    assert result["export_fidelity"]["n_variables_written"] == 3


def test_dataarray_export_both_formats(lossy_dataset, tmp_path):
    netcdf = export_dataarray(lossy_dataset["sst"], str(tmp_path / "a.nc"))
    assert netcdf["warning_codes"] == []
    assert netcdf["export_fidelity"]["format"] == "netcdf"
    csv = export_dataarray(lossy_dataset["sst"], str(tmp_path / "a.csv"), "csv")
    assert csv["export_fidelity"]["attributes_dropped"] == 3
    assert csv["export_fidelity"]["rows_written"] == 9
    with pytest.raises(ValueError, match="Unsupported format"):
        export_dataarray(lossy_dataset["sst"], str(tmp_path / "a.txt"), "txt")


def test_uxdataarray_payload_is_accepted(structured_mesh_files, tmp_path):
    grid_file, data_file = structured_mesh_files
    uxda = ux.open_dataset(grid_file, data_file)["temperature"]
    result = export_dataarray(uxda, str(tmp_path / "ux.nc"))
    assert result["export_fidelity"]["bytes_written"] > 0
    with xr.open_dataarray(tmp_path / "ux.nc") as back:
        assert back.shape == uxda.shape


def test_empty_file_is_its_own_code(tmp_path):
    empty = xr.Dataset({"x": (["n"], np.zeros(0))})
    result = export_dataset(empty, str(tmp_path / "empty.csv"), "csv")
    assert result["export_fidelity"]["rows_written"] == 0
    assert "EXPORT_ROW_COUNT_MISMATCH" not in result["warning_codes"]


def test_narrow_fill_values_are_widened():
    ds = xr.Dataset({"conn": (["n"], np.array([0, 1], dtype=np.int32))})
    ds["conn"].attrs["_FillValue"] = np.iinfo(np.int64).min
    widened = widen_narrow_fill_values(ds)
    assert widened["conn"].dtype == np.int64
    assert widened["conn"].attrs["_FillValue"] == np.iinfo(np.int64).min


def test_phantom_topology_attrs_are_dropped():
    ds = xr.Dataset({"grid_topology": ((), 0), "face_node_connectivity": (["f"], [0])})
    ds["grid_topology"].attrs = {
        "topology_dimension": 2,
        "face_node_connectivity": "face_node_connectivity",
        "face_edge_connectivity": "face_edge_connectivity",
        "node_coordinates": "node_lon node_lat",
        "face_dimension": "f",
    }
    kept = drop_phantom_topology_attrs(ds)["grid_topology"].attrs
    assert kept == {
        "topology_dimension": 2,
        "face_node_connectivity": "face_node_connectivity",
        "face_dimension": "f",
    }


def test_grid_artifact_round_trips(structured_mesh_files, tmp_path):
    grid = ux.open_grid(structured_mesh_files[0])
    path = write_grid_artifact(grid, tmp_path / "grid_out.nc")
    assert ux.open_grid(path).n_face == grid.n_face
