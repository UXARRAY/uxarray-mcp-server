import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path
from uxarray_mcp.tools.inspection import inspect_mesh

class TestInspectMeshFormat:
    """Tests for different mesh formats (MPAS, UGRID, etc.)."""

    def test_inspect_mpas_mesh(self, mpas_grid):
        """Test inspection of an MPAS mesh."""
        with patch("uxarray_mcp.tools.inspection.Path") as MockPath, \
             patch("uxarray.open_grid", return_value=mpas_grid):
            
            MockPath.return_value.exists.return_value = True
            MockPath.return_value.stat.return_value.st_size = 1024 * 1024

            result = inspect_mesh("/path/to/mpas.nc")
            assert result["format"] == "MPAS"
            assert result["n_face"] == 100

    def test_inspect_ugrid_mesh(self, ugrid_grid):
        """Test inspection of a UGRID mesh."""
        with patch("uxarray_mcp.tools.inspection.Path") as MockPath, \
             patch("uxarray.open_grid", return_value=ugrid_grid):
            
            MockPath.return_value.exists.return_value = True
            MockPath.return_value.stat.return_value.st_size = 1024 * 1024

            result = inspect_mesh("/path/to/ugrid.nc")
            assert result["format"] == "UGRID"

    def test_inspect_scrip_mesh(self, scrip_grid):
        """Test inspection of a SCRIP mesh."""
        with patch("uxarray_mcp.tools.inspection.Path") as MockPath, \
             patch("uxarray.open_grid", return_value=scrip_grid):
            
            MockPath.return_value.exists.return_value = True
            MockPath.return_value.stat.return_value.st_size = 1024 * 1024

            result = inspect_mesh("/path/to/scrip.nc")
            assert result["format"] == "SCRIP"

    def test_inspect_healpix_mesh(self, base_grid):
        """Test inspection of a HEALPix mesh generation."""
        # Mock grid returned by from_healpix
        healpix_grid = base_grid
        healpix_grid.n_face = 12 * 4**2  # Zoom 2 (example)
        healpix_grid.n_node = 200 # Dummy
        healpix_grid.n_edge = 300 # Dummy
        
        with patch("uxarray.Grid.from_healpix", return_value=healpix_grid) as mock_from_healpix:
            # Test default zoom 1 if not specified (we handle this in logic)
            # or explicit zoom
            result = inspect_mesh("healpix:2")
            
            mock_from_healpix.assert_called_once_with(zoom=2)
            assert result["format"] == "HEALPix"
            assert result["n_face"] == 192 # 12 * 4^2
            assert result["file_size_mb"] == 0.0

    def test_inspect_healpix_invalid_format(self):
        """Test invalid healpix format."""
        with pytest.raises(ValueError, match="Invalid HEALPix format"):
            inspect_mesh("healpix:invalid")

class TestInspectMeshErrorHandling:
    """Tests for error handling and edge cases."""

    def test_file_not_found(self):
        """Test handling of non-existent files."""
        with patch("uxarray_mcp.tools.inspection.Path") as MockPath:
            MockPath.return_value.exists.return_value = False
            
            with pytest.raises(FileNotFoundError, match="Mesh file not found"):
                inspect_mesh("/nonexistent/file.nc")

    def test_path_is_directory(self):
        """Test proper error when path is a directory (should be caught by uxarray or exists check)."""
        # Note: In the current impl, if 'exists' is true, we call open_grid.
        # uxarray.open_grid would verify if it is a directory.
        
        with patch("uxarray_mcp.tools.inspection.Path") as MockPath:
            mock_path_obj = MockPath.return_value
            mock_path_obj.exists.return_value = True
            mock_path_obj.is_dir.return_value = True # Start mocking checks
            
            # We assume uxarray raises an error if passed a directory
            with patch("uxarray.open_grid", side_effect=IsADirectoryError("Is a directory")):
                with pytest.raises(RuntimeError) as excinfo:
                    inspect_mesh("/path/to/directory")
                assert "Failed to load mesh file" in str(excinfo.value)
                assert "Is a directory" in str(excinfo.value)

    def test_permission_denied(self):
        """Test handling of permission denied errors."""
        with patch("uxarray_mcp.tools.inspection.Path") as MockPath:
            MockPath.return_value.exists.return_value = True
            
            with patch("uxarray.open_grid", side_effect=PermissionError("Permission denied")):
                with pytest.raises(RuntimeError) as excinfo:
                    inspect_mesh("/protected/file.nc")
                assert "Permission denied" in str(excinfo.value)

    def test_corrupt_file(self):
        """Test handling of corrupt or invalid mesh files."""
        with patch("uxarray_mcp.tools.inspection.Path") as MockPath:
            MockPath.return_value.exists.return_value = True
            
            with patch("uxarray.open_grid", side_effect=Exception("NetCDF: Unknown file format")):
                with pytest.raises(RuntimeError) as excinfo:
                    inspect_mesh("/corrupt.txt")
                assert "Unknown file format" in str(excinfo.value)

    def test_empty_string_path(self):
        """Test calling with empty string."""
        with patch("uxarray_mcp.tools.inspection.Path") as MockPath:
            # Path("") usually resolves to current directory in real usage, 
            # so exists() is True. We rely on uxarray to fail opening a dir.
            MockPath.return_value.exists.return_value = True
            
            with patch("uxarray.open_grid", side_effect=IsADirectoryError("Is a directory")):
                 with pytest.raises(RuntimeError, match="Failed to load mesh file"):
                    inspect_mesh("")
