"""Pure inspection ops: one happy path and one error per operation."""

from __future__ import annotations

import numpy as np
import pytest
import xarray as xr

from uxarray_mcp.core import inspect as insp


class TestInspectMesh:
    def test_global_mesh_summary(self, structured_mesh_files):
        grid_file, _ = structured_mesh_files
        result = insp.inspect_mesh(grid_file)
        assert result["n_face"] == 162
        assert result["n_node"] == 146
        assert result["n_edge"] > 0
        assert "n_edge_skipped" not in result
        assert result["format"] is not None
        assert result["file_size_mb"] > 0
        coverage = result["mesh_coverage"]
        assert coverage["sphere_fraction"] == pytest.approx(1.0, abs=1e-3)
        assert coverage["closed"] is True
        assert coverage["euler_characteristic"] == 2
        assert "_provenance" not in result and "recommended_next_steps" not in result

    def test_healpix_spec(self):
        result = insp.inspect_mesh("healpix:2")
        assert result["format"] == "HEALPix"
        assert result["n_face"] == 192
        assert result["n_edge"] == 384
        assert result["file_size_mb"] == 0.0

    def test_huge_mesh_skips_and_says_so(self, monkeypatch):
        """Mirror of test_inspect_mesh_at_scale: n_edge and sphere_fraction abstain."""
        ux = pytest.importorskip("uxarray")
        real = ux.Grid.from_healpix(2)

        class Huge:
            n_face = 299_999_162

            @property
            def n_edge(self):
                raise AssertionError("n_edge computed on a 300M-face mesh")

            @property
            def face_areas(self):
                raise AssertionError("face_areas computed on a 300M-face mesh")

            def __getattr__(self, name):
                return getattr(real, name)

        monkeypatch.setattr(
            ux.Grid, "from_healpix", staticmethod(lambda *a, **k: Huge())
        )
        result = insp.inspect_mesh("healpix:2")
        assert result["n_edge"] is None
        assert "250000" in result["n_edge_skipped"]
        assert result["mesh_coverage"]["sphere_fraction"] is None
        assert "50000000" in result["mesh_coverage"]["sphere_fraction_skipped"]
        assert result["mesh_coverage"]["lat_extent"] is not None

    def test_errors(self, tmp_path):
        with pytest.raises(FileNotFoundError, match="Mesh file not found"):
            insp.inspect_mesh(str(tmp_path / "missing.nc"))
        with pytest.raises(ValueError, match="Invalid HEALPix format"):
            insp.inspect_mesh("healpix:xyz")


class TestGridFacts:
    def test_facts_with_data(self, structured_mesh_files):
        grid_file, data_file = structured_mesh_files
        result = insp.grid_facts(grid_file, data_file)
        assert (
            result["n_face"] == 162 and result["n_node"] == 146 and result["n_edge"] > 0
        )
        assert result["is_global"] is True
        assert result["variables"][0]["name"] == "temperature"
        assert result["variables"][0]["location"] == "faces"

    def test_missing_data(self, structured_mesh_files, tmp_path):
        grid_file, _ = structured_mesh_files
        with pytest.raises(FileNotFoundError, match="Data file not found"):
            insp.grid_facts(grid_file, str(tmp_path / "no.nc"))


class TestInspectVariable:
    def test_single_variable(self, structured_mesh_files):
        grid_file, data_file = structured_mesh_files
        result = insp.inspect_variable(grid_file, data_file, "temperature")
        assert len(result["variables"]) == 1
        var = result["variables"][0]
        assert var["name"] == "temperature"
        assert var["location"] == "faces"
        assert var["dtype"] == "float64"
        assert 250 <= var["statistics"]["min"] <= var["statistics"]["max"] <= 280
        assert result["grid_info"]["n_face"] == 162

    def test_unknown_variable(self, structured_mesh_files):
        grid_file, data_file = structured_mesh_files
        with pytest.raises(ValueError, match="Variable 'pressure' not found"):
            insp.inspect_variable(grid_file, data_file, "pressure")


class TestValidateDataset:
    def test_clean_dataset(self, structured_mesh_files):
        grid_file, data_file = structured_mesh_files
        result = insp.validate_dataset(grid_file, data_file)
        assert result["passed"] is True and result["is_valid"] is True
        assert result["issues"] == []
        assert result["n_variables_checked"] == 1
        var = result["variables"][0]
        assert var["has_nan"] is False and var["nan_count"] == 0
        assert var["total_values"] == 162
        assert len(var["value_range"]) == 2

    def test_nan_and_fill_and_latitude(self, structured_mesh_files, tmp_path):
        grid_file, _ = structured_mesh_files
        n = 162
        temp = np.full(n, 280.0)
        temp[0] = np.nan
        temp[1] = 1e20
        lat = np.zeros(n)
        lat[2] = 95.0
        data_file = tmp_path / "bad.nc"
        xr.Dataset(
            {"temperature": (["n_face"], temp), "face_latitude": (["n_face"], lat)}
        ).to_netcdf(data_file)
        result = insp.validate_dataset(grid_file, str(data_file))
        assert result["passed"] is False
        assert result["n_variables_failed"] == 2
        by_name = {v["name"]: v for v in result["variables"]}
        assert by_name["temperature"]["nan_count"] == 1
        assert by_name["temperature"]["detected_fill_value"] == 1e20
        assert by_name["face_latitude"]["coordinate_issues"] == [
            "latitude out of valid range [-90, 90]"
        ]
        assert any("NaN" in issue for issue in result["issues"])

    def test_missing_grid(self, structured_mesh_files, tmp_path):
        _, data_file = structured_mesh_files
        with pytest.raises(FileNotFoundError, match="Grid file not found"):
            insp.validate_dataset(str(tmp_path / "no.nc"), data_file)


class TestCalculateArea:
    def test_unit_sphere_with_basis(self, structured_mesh_files):
        grid_file, _ = structured_mesh_files
        result = insp.calculate_area(grid_file)
        assert result["n_face"] == 162
        assert result["total_area"] == pytest.approx(4 * np.pi, rel=1e-3)
        assert result["min_area"] <= result["mean_area"] <= result["max_area"]
        assert result["area_units"] is None
        assert result["area_basis"] == {
            "sphere_radius": 1.0,
            "radius_source": "unit_sphere",
            "scaled": False,
        }

    def test_explicit_radius_scales_and_names_units(self, structured_mesh_files):
        grid_file, _ = structured_mesh_files
        result = insp.calculate_area(grid_file, sphere_radius=6371000.0)
        assert result["total_area"] == pytest.approx(5.1e14, rel=1e-2)
        assert result["area_units"] == "m^2"
        assert result["area_basis"]["radius_source"] == "argument"
        assert result["area_basis"]["scaled"] is True

    def test_errors(self, tmp_path):
        with pytest.raises(FileNotFoundError, match="Mesh file not found"):
            insp.calculate_area(str(tmp_path / "missing.nc"))
        with pytest.raises(ValueError, match="Invalid HEALPix format"):
            insp.calculate_area("healpix:bad")


class TestZonal:
    def test_zonal_mean_default_bands(self, structured_mesh_files):
        grid_file, data_file = structured_mesh_files
        result = insp.calculate_zonal_mean(grid_file, data_file, "temperature")
        assert result["variable_name"] == "temperature"
        assert result["conservative"] is False
        assert len(result["latitudes"]) == len(result["zonal_mean_values"]) == 19
        assert result["grid_info"]["n_face"] == 162

    def test_zonal_anomaly_stats(self, structured_mesh_files):
        grid_file, data_file = structured_mesh_files
        result = insp.zonal_anomaly(grid_file, data_file, "temperature")
        assert result["variable_name"] == "temperature"
        assert result["n_face"] == 162
        assert set(result["stats"]) >= {"min", "max", "mean", "std"}

    def test_errors(self, structured_mesh_files, tmp_path):
        grid_file, data_file = structured_mesh_files
        with pytest.raises(ValueError, match="Variable 'nope' not found"):
            insp.calculate_zonal_mean(grid_file, data_file, "nope")
        with pytest.raises(FileNotFoundError, match="Data file not found"):
            insp.calculate_zonal_mean(grid_file, str(tmp_path / "no.nc"), "temperature")
