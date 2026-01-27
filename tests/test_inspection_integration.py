import pytest
from uxarray_mcp.tools.inspection import inspect_mesh

def test_inspect_synthetic_mesh(synthetic_mesh_file):
    """
    Integration test using a real (synthetic) temporary file and actual uxarray logic.
    Does NOT depend on external internet or cloned repos.
    """
    result = inspect_mesh(synthetic_mesh_file)
    
    # Check that it identified some basic properties correctly
    assert result["n_face"] == 1
    assert result["n_node"] == 3
    # Format might be UGRID or similar depending on how uxarray detects it
    assert "UGRID" in result["format"] or result["format"] == "Exodus" 
