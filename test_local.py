"""Test the inspect_mesh tool locally before connecting to Claude Desktop."""

import uxarray as ux
from pathlib import Path

# Path to test mesh files
# Adjust this to point to your uxarray test files
TEST_MESHFILES = Path.home() / "Desktop" / "uxarray" / "test" / "meshfiles"


def test_mpas_mesh():
    """Test with an MPAS ocean mesh."""
    print("\n" + "="*60)
    print("Testing MPAS Ocean Mesh")
    print("="*60)

    mesh_file = TEST_MESHFILES / "mpas" / "QU" / "oQU480.231010.nc"

    if not mesh_file.exists():
        print(f"[ERROR] File not found: {mesh_file}")
        return

    try:
        # Load mesh directly with uxarray
        grid = ux.open_grid(str(mesh_file))
        file_size_mb = mesh_file.stat().st_size / (1024 * 1024)

        result = {
            "format": grid.source_grid_spec,
            "n_face": int(grid.n_face),
            "n_node": int(grid.n_node),
            "n_edge": int(grid.n_edge),
            "n_max_face_nodes": int(grid.n_max_face_nodes),
            "file_size_mb": round(file_size_mb, 2)
        }

        print(f"\n[SUCCESS] Mesh inspected successfully")
        print(f"\nFormat: {result['format']}")
        print(f"Faces: {result['n_face']:,}")
        print(f"Nodes: {result['n_node']:,}")
        print(f"Edges: {result['n_edge']:,}")
        print(f"Max nodes per face: {result['n_max_face_nodes']}")
        print(f"File size: {result['file_size_mb']} MB")
    except Exception as e:
        print(f"[ERROR] {e}")


def test_ugrid_mesh():
    """Test with a UGRID mesh."""
    print("\n" + "="*60)
    print("Testing UGRID Mesh")
    print("="*60)

    mesh_file = TEST_MESHFILES / "ugrid" / "outCSne30" / "outCSne30.ug"

    if not mesh_file.exists():
        print(f"[ERROR] File not found: {mesh_file}")
        return

    try:
        # Load mesh directly with uxarray
        grid = ux.open_grid(str(mesh_file))
        file_size_mb = mesh_file.stat().st_size / (1024 * 1024)

        result = {
            "format": grid.source_grid_spec,
            "n_face": int(grid.n_face),
            "n_node": int(grid.n_node),
            "n_edge": int(grid.n_edge),
            "n_max_face_nodes": int(grid.n_max_face_nodes),
            "file_size_mb": round(file_size_mb, 2)
        }

        print(f"\n[SUCCESS] Mesh inspected successfully")
        print(f"\nFormat: {result['format']}")
        print(f"Faces: {result['n_face']:,}")
        print(f"Nodes: {result['n_node']:,}")
        print(f"Edges: {result['n_edge']:,}")
        print(f"Max nodes per face: {result['n_max_face_nodes']}")
        print(f"File size: {result['file_size_mb']} MB")
    except Exception as e:
        print(f"[ERROR] {e}")


def test_scrip_mesh():
    """Test with a SCRIP mesh."""
    print("\n" + "="*60)
    print("Testing SCRIP Mesh")
    print("="*60)

    mesh_file = TEST_MESHFILES / "scrip" / "outCSne8" / "outCSne8.nc"

    if not mesh_file.exists():
        print(f"[ERROR] File not found: {mesh_file}")
        return

    try:
        # Load mesh directly with uxarray
        grid = ux.open_grid(str(mesh_file))
        file_size_mb = mesh_file.stat().st_size / (1024 * 1024)

        result = {
            "format": grid.source_grid_spec,
            "n_face": int(grid.n_face),
            "n_node": int(grid.n_node),
            "n_edge": int(grid.n_edge),
            "n_max_face_nodes": int(grid.n_max_face_nodes),
            "file_size_mb": round(file_size_mb, 2)
        }

        print(f"\n[SUCCESS] Mesh inspected successfully")
        print(f"\nFormat: {result['format']}")
        print(f"Faces: {result['n_face']:,}")
        print(f"Nodes: {result['n_node']:,}")
        print(f"Edges: {result['n_edge']:,}")
        print(f"Max nodes per face: {result['n_max_face_nodes']}")
        print(f"File size: {result['file_size_mb']} MB")
    except Exception as e:
        print(f"[ERROR] {e}")


if __name__ == "__main__":
    print("\nTesting UXarray MCP Server - inspect_mesh tool")

    # Test different mesh formats
    test_mpas_mesh()
    test_ugrid_mesh()
    test_scrip_mesh()

    print("\n" + "="*60)
    print("Testing complete!")
    print("="*60 + "\n")
