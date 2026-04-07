"""Tests for get_capabilities tool — tool discovery and filtering."""

from unittest.mock import patch

import pytest
import xarray as xr

from uxarray_mcp.tools import get_capabilities


class TestGetCapabilitiesGridOnly:
    """Tests for get_capabilities with grid file only (no data_path)."""

    def test_healpix_grid_summary_structure(self):
        """Grid summary has all required topology keys."""
        result = get_capabilities("healpix:2")

        grid = result["grid_summary"]
        assert "n_face" in grid
        assert "n_node" in grid
        assert "n_edge" in grid
        assert "format" in grid
        assert "has_faces" in grid
        assert "has_nodes" in grid
        assert "has_edges" in grid

    def test_healpix_grid_has_faces(self):
        """HEALPix grid correctly identifies faces."""
        result = get_capabilities("healpix:2")

        assert result["grid_summary"]["has_faces"] is True
        assert result["grid_summary"]["n_face"] == 192

    def test_healpix_format_label(self):
        """HEALPix format is labeled correctly."""
        result = get_capabilities("healpix:2")
        assert result["grid_summary"]["format"] == "HEALPix"

    def test_mcp_tools_list_present(self):
        """mcp_server_tools is a non-empty list."""
        result = get_capabilities("healpix:2")
        assert "mcp_server_tools" in result
        assert isinstance(result["mcp_server_tools"], list)
        assert len(result["mcp_server_tools"]) > 0

    def test_mcp_tools_have_required_fields(self):
        """Each tool entry has name, applicable, reason, and call_example."""
        result = get_capabilities("healpix:2")
        for tool in result["mcp_server_tools"]:
            assert "name" in tool, f"Missing 'name' in {tool}"
            assert "applicable" in tool, f"Missing 'applicable' in {tool}"
            assert "reason" in tool, f"Missing 'reason' in {tool}"
            assert "call_example" in tool, f"Missing 'call_example' in {tool}"
            assert isinstance(tool["applicable"], bool)

    def test_inspect_mesh_always_applicable(self):
        """inspect_mesh is always applicable regardless of data."""
        result = get_capabilities("healpix:2")
        tools = {t["name"]: t for t in result["mcp_server_tools"]}
        assert tools["inspect_mesh"]["applicable"] is True

    def test_calculate_area_applicable_with_faces(self):
        """calculate_area is applicable when mesh has faces."""
        result = get_capabilities("healpix:2")
        tools = {t["name"]: t for t in result["mcp_server_tools"]}
        assert tools["calculate_area"]["applicable"] is True

    def test_inspect_variable_not_applicable_without_data(self):
        """inspect_variable requires data_path."""
        result = get_capabilities("healpix:2")
        tools = {t["name"]: t for t in result["mcp_server_tools"]}
        assert tools["inspect_variable"]["applicable"] is False
        assert "data_path" in tools["inspect_variable"]["reason"].lower()

    def test_zonal_mean_not_applicable_without_data(self):
        """calculate_zonal_mean requires face-centered data."""
        result = get_capabilities("healpix:2")
        tools = {t["name"]: t for t in result["mcp_server_tools"]}
        assert tools["calculate_zonal_mean"]["applicable"] is False

    def test_validate_dataset_not_applicable_without_data(self):
        """validate_dataset requires data_path."""
        result = get_capabilities("healpix:2")
        tools = {t["name"]: t for t in result["mcp_server_tools"]}
        assert tools["validate_dataset"]["applicable"] is False

    def test_probe_path_access_is_always_available(self):
        """probe_path_access should be surfaced for bring-up on any dataset."""
        result = get_capabilities("healpix:2")
        tools = {t["name"]: t for t in result["mcp_server_tools"]}
        assert tools["probe_path_access"]["applicable"] is True

    def test_session_and_workflow_tools_are_surfaced(self):
        """Stateful orchestration tools should be discoverable without data."""
        result = get_capabilities("healpix:2")
        tools = {t["name"]: t for t in result["mcp_server_tools"]}
        assert tools["create_session"]["applicable"] is True
        assert tools["run_workflow"]["applicable"] is True

    def test_uxarray_capabilities_structure(self):
        """uxarray_capabilities has all required category keys."""
        result = get_capabilities("healpix:2")
        caps = result["uxarray_capabilities"]
        for key in [
            "spatial_analysis",
            "subsetting",
            "remapping",
            "vector_calculus",
            "topological_ops",
            "visualization",
        ]:
            assert key in caps, f"Missing capability category: {key}"
            assert isinstance(caps[key], list)

    def test_spatial_analysis_includes_face_methods(self):
        """Mesh with faces gets face-related spatial methods."""
        result = get_capabilities("healpix:2")
        spatial = result["uxarray_capabilities"]["spatial_analysis"]
        assert any("face_areas" in m for m in spatial)

    def test_subsetting_always_populated(self):
        """Subsetting methods are always available."""
        result = get_capabilities("healpix:2")
        subsetting = result["uxarray_capabilities"]["subsetting"]
        assert len(subsetting) > 0
        assert any("bounding_box" in m for m in subsetting)

    def test_visualization_always_populated(self):
        """Visualization methods are always available."""
        result = get_capabilities("healpix:2")
        viz = result["uxarray_capabilities"]["visualization"]
        assert len(viz) > 0
        assert any("grid.plot.mesh" in m for m in viz)

    def test_no_variables_key_without_data(self):
        """Variables section is absent when no data_path provided."""
        result = get_capabilities("healpix:2")
        assert "variables" not in result

    def test_recommendations_present(self):
        """Recommendations list is always returned."""
        result = get_capabilities("healpix:2")
        assert "recommendations" in result
        assert isinstance(result["recommendations"], list)

    def test_recommendation_suggests_data_path(self):
        """Without data_path, recommendations mention providing one."""
        result = get_capabilities("healpix:2")
        combined = " ".join(result["recommendations"]).lower()
        assert "data_path" in combined

    def test_grid_file(self, synthetic_mesh_file):
        """Works with a real grid NetCDF file."""
        result = get_capabilities(synthetic_mesh_file)
        assert result["grid_summary"]["has_faces"] is True
        tools = {t["name"]: t for t in result["mcp_server_tools"]}
        assert tools["inspect_mesh"]["applicable"] is True
        assert tools["calculate_area"]["applicable"] is True

    def test_hpc_tools_hidden_without_endpoint(self):
        """HPC tools are omitted when no endpoint is configured."""
        with patch("uxarray_mcp.tools.capabilities.load_config") as mock_load_config:
            mock_load_config.return_value.has_endpoint = False
            result = get_capabilities("healpix:2")

        tool_names = {t["name"] for t in result["mcp_server_tools"]}
        assert "inspect_mesh_hpc" not in tool_names
        assert "calculate_area_hpc" not in tool_names
        assert "inspect_variable_hpc" not in tool_names
        assert "calculate_zonal_mean_hpc" not in tool_names

    def test_hpc_tools_shown_with_endpoint(self):
        """HPC tools are surfaced when an endpoint is configured."""
        with patch("uxarray_mcp.tools.capabilities.load_config") as mock_load_config:
            mock_load_config.return_value.has_endpoint = True
            result = get_capabilities("healpix:2")

        tool_names = {t["name"] for t in result["mcp_server_tools"]}
        assert "inspect_mesh_hpc" in tool_names
        assert "calculate_area_hpc" in tool_names
        assert "inspect_variable_hpc" in tool_names
        assert "calculate_zonal_mean_hpc" in tool_names


class TestGetCapabilitiesWithData:
    """Tests for get_capabilities with both grid and data files."""

    def test_variables_key_present_with_data(self, synthetic_mesh_with_data):
        """Variables section is included when data_path is provided."""
        grid_file, data_file = synthetic_mesh_with_data
        result = get_capabilities(grid_file, data_file)
        assert "variables" in result

    def test_face_centered_variables_detected(self, synthetic_mesh_with_data):
        """Face-centered variables are correctly identified."""
        grid_file, data_file = synthetic_mesh_with_data
        result = get_capabilities(grid_file, data_file)

        var_names = [v["name"] for v in result["variables"]]
        assert "temperature" in var_names
        assert "pressure" in var_names

        for var in result["variables"]:
            assert var["location"] == "faces"

    def test_zonal_mean_applicable_with_face_data(self, synthetic_mesh_with_data):
        """calculate_zonal_mean is applicable when face-centered data exists."""
        grid_file, data_file = synthetic_mesh_with_data
        result = get_capabilities(grid_file, data_file)
        tools = {t["name"]: t for t in result["mcp_server_tools"]}
        assert tools["calculate_zonal_mean"]["applicable"] is True

    def test_inspect_variable_applicable_with_data(self, synthetic_mesh_with_data):
        """inspect_variable is applicable when data_path provided."""
        grid_file, data_file = synthetic_mesh_with_data
        result = get_capabilities(grid_file, data_file)
        tools = {t["name"]: t for t in result["mcp_server_tools"]}
        assert tools["inspect_variable"]["applicable"] is True

    def test_validate_dataset_applicable_with_data(self, synthetic_mesh_with_data):
        """validate_dataset is applicable when data_path provided."""
        grid_file, data_file = synthetic_mesh_with_data
        result = get_capabilities(grid_file, data_file)
        tools = {t["name"]: t for t in result["mcp_server_tools"]}
        assert tools["validate_dataset"]["applicable"] is True

    def test_subset_compare_and_remap_tools_surface_with_face_data(
        self, synthetic_mesh_with_data
    ):
        """Face-centered data should unlock the newer analysis tools."""
        grid_file, data_file = synthetic_mesh_with_data
        result = get_capabilities(grid_file, data_file)
        tools = {t["name"]: t for t in result["mcp_server_tools"]}
        assert tools["subset_bbox"]["applicable"] is True
        assert tools["compare_fields"]["applicable"] is True
        assert tools["remap_variable"]["applicable"] is True

    def test_face_var_applicable_tools(self, synthetic_mesh_with_data):
        """Face-centered variables list calculate_zonal_mean as applicable."""
        grid_file, data_file = synthetic_mesh_with_data
        result = get_capabilities(grid_file, data_file)

        for var in result["variables"]:
            assert "calculate_zonal_mean" in var["applicable_mcp_tools"]

    def test_face_var_uxarray_methods_include_zonal_mean(
        self, synthetic_mesh_with_data
    ):
        """Face-centered variables include zonal_mean in UXarray methods."""
        grid_file, data_file = synthetic_mesh_with_data
        result = get_capabilities(grid_file, data_file)

        for var in result["variables"]:
            methods = var["applicable_uxarray_methods"]
            assert any("zonal_mean" in m for m in methods)

    def test_face_var_uxarray_methods_include_remap(self, synthetic_mesh_with_data):
        """Face-centered variables include remapping methods."""
        grid_file, data_file = synthetic_mesh_with_data
        result = get_capabilities(grid_file, data_file)

        for var in result["variables"]:
            methods = var["applicable_uxarray_methods"]
            assert any("remap" in m for m in methods)

    def test_vector_calculus_available_with_face_data(self, synthetic_mesh_with_data):
        """Vector calculus methods appear when face-centered data exists."""
        grid_file, data_file = synthetic_mesh_with_data
        result = get_capabilities(grid_file, data_file)
        vc = result["uxarray_capabilities"]["vector_calculus"]
        assert len(vc) > 0
        assert any("gradient" in m for m in vc)
        assert any("zonal_mean" in m for m in vc)

    def test_curl_available_with_multiple_face_vars(self, synthetic_mesh_with_data):
        """curl and divergence appear when 2+ face-centered variables exist."""
        grid_file, data_file = synthetic_mesh_with_data
        result = get_capabilities(grid_file, data_file)
        vc = result["uxarray_capabilities"]["vector_calculus"]
        # synthetic_mesh_with_data has temperature + pressure (2 face vars)
        assert any("curl" in m for m in vc)
        assert any("divergence" in m for m in vc)

    def test_remapping_available_with_face_data(self, synthetic_mesh_with_data):
        """Remapping methods listed without [needs face-centered data] note."""
        grid_file, data_file = synthetic_mesh_with_data
        result = get_capabilities(grid_file, data_file)
        remapping = result["uxarray_capabilities"]["remapping"]
        assert len(remapping) > 0
        # Should not have the caveat note since we have face-centered data
        assert all("needs face-centered" not in m for m in remapping)

    def test_recommendation_mentions_face_vars(self, synthetic_mesh_with_data):
        """Recommendations mention the face-centered variables found."""
        grid_file, data_file = synthetic_mesh_with_data
        result = get_capabilities(grid_file, data_file)
        combined = " ".join(result["recommendations"]).lower()
        # Should mention the pipeline since face vars exist
        assert "temperature" in combined or "pressure" in combined

    def test_visualization_includes_polygon_plot_with_face_data(
        self, synthetic_mesh_with_data
    ):
        """Visualization includes polygon plotting when face data present."""
        grid_file, data_file = synthetic_mesh_with_data
        result = get_capabilities(grid_file, data_file)
        viz = result["uxarray_capabilities"]["visualization"]
        assert any("polygons" in m for m in viz)


class TestGetCapabilitiesNodeOnlyData:
    """Tests for get_capabilities when data is on nodes, not faces."""

    @pytest.fixture
    def mesh_with_node_data(self, tmp_path):
        """Creates a mesh with node-centered data variables."""
        grid_ds = xr.Dataset(
            {
                "Mesh2": (
                    [],
                    0,
                    {
                        "cf_role": "mesh_topology",
                        "topology_dimension": 2,
                        "node_coordinates": "Mesh2_node_x Mesh2_node_y",
                        "face_node_connectivity": "Mesh2_face_nodes",
                    },
                ),
                "Mesh2_node_x": (["nMesh2_node"], [0.0, 1.0, 0.5]),
                "Mesh2_node_y": (["nMesh2_node"], [0.0, 0.0, 1.0]),
                "Mesh2_face_nodes": (
                    ["nMesh2_face", "nMaxMesh2_face_nodes"],
                    [[0, 1, 2]],
                    {"cf_role": "face_node_connectivity", "start_index": 0},
                ),
            }
        )
        data_ds = xr.Dataset(
            {
                "node_temperature": (
                    ["nMesh2_node"],
                    [1.0, 2.0, 3.0],
                    {"units": "K", "long_name": "Node Temperature"},
                ),
            }
        )
        grid_file = tmp_path / "grid.nc"
        data_file = tmp_path / "node_data.nc"
        grid_ds.to_netcdf(grid_file)
        data_ds.to_netcdf(data_file)
        return str(grid_file), str(data_file)

    def test_node_data_location_detected(self, mesh_with_node_data):
        """Node-centered variables are labeled as 'nodes'."""
        grid_file, data_file = mesh_with_node_data
        result = get_capabilities(grid_file, data_file)

        if result.get("variables"):
            for var in result["variables"]:
                assert var["location"] in ("nodes", "other")

    def test_zonal_mean_not_applicable_with_only_node_data(self, mesh_with_node_data):
        """calculate_zonal_mean is not applicable without face-centered data."""
        grid_file, data_file = mesh_with_node_data
        result = get_capabilities(grid_file, data_file)
        tools = {t["name"]: t for t in result["mcp_server_tools"]}
        assert tools["calculate_zonal_mean"]["applicable"] is False


class TestGetCapabilitiesErrors:
    """Tests for error handling in get_capabilities."""

    def test_grid_file_not_found(self):
        """Raises FileNotFoundError for missing grid file."""
        with pytest.raises(FileNotFoundError, match="Grid file not found"):
            get_capabilities("/nonexistent/path/grid.nc")

    def test_data_file_not_found(self, synthetic_mesh_file):
        """Raises FileNotFoundError for missing data file."""
        with pytest.raises(FileNotFoundError, match="Data file not found"):
            get_capabilities(synthetic_mesh_file, "/nonexistent/data.nc")

    def test_invalid_healpix_format(self):
        """Raises RuntimeError for invalid HEALPix specification."""
        with pytest.raises((RuntimeError, ValueError)):
            get_capabilities("healpix:notanumber")
