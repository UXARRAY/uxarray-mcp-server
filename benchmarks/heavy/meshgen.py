"""Deterministic synthetic mesh builders for the heavy benchmark suite.

Self-contained by design: every function inlines its imports and touches no
``uxarray_mcp`` module, so the same source can be shipped to a Globus Compute
worker via ``AllCodeStrategies`` and executed there unchanged.  Module-level
helpers do *not* survive that serialization, so nothing here may depend on
another function in this file.
"""

from __future__ import annotations


def build_quad_mesh(
    outdir: str,
    nlon: int = 360,
    nlat: int = 180,
    ntime: int = 12,
) -> dict:
    """Write a lon/lat quad UGRID mesh plus a face-centered dataset.

    Field values are analytic (no RNG) so a mesh generated locally and one
    generated on a worker are bit-identical, which is what makes the
    local-vs-remote differential comparison meaningful.
    """
    import os

    import numpy as np
    import xarray as xr

    os.makedirs(outdir, exist_ok=True)
    lon_edges = np.linspace(-180.0, 180.0, nlon + 1)
    lat_edges = np.linspace(-90.0, 90.0, nlat + 1)
    mesh_x, mesh_y = np.meshgrid(lon_edges, lat_edges, indexing="ij")
    node_x, node_y = mesh_x.ravel(), mesh_y.ravel()

    faces = np.array(
        [
            [
                i * (nlat + 1) + j,
                (i + 1) * (nlat + 1) + j,
                (i + 1) * (nlat + 1) + j + 1,
                i * (nlat + 1) + j + 1,
            ]
            for i in range(nlon)
            for j in range(nlat)
        ],
        dtype=np.int32,
    )

    grid = xr.Dataset(
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
            "Mesh2_node_x": (
                ["nMesh2_node"],
                node_x,
                {"units": "degrees_east", "standard_name": "longitude"},
            ),
            "Mesh2_node_y": (
                ["nMesh2_node"],
                node_y,
                {"units": "degrees_north", "standard_name": "latitude"},
            ),
            "Mesh2_face_nodes": (
                ["nMesh2_face", "nMaxMesh2_face_nodes"],
                faces,
                {"cf_role": "face_node_connectivity", "start_index": 0},
            ),
        }
    )

    centre_lat = np.repeat(
        (0.5 * (lat_edges[:-1] + lat_edges[1:]))[None, :], nlon, axis=0
    ).ravel()
    centre_lon = np.repeat(
        (0.5 * (lon_edges[:-1] + lon_edges[1:]))[:, None], nlat, axis=1
    ).ravel()

    base = (
        288.0
        - 40.0 * np.sin(np.deg2rad(centre_lat)) ** 2
        + 3.0 * np.cos(np.deg2rad(2 * centre_lon))
    )
    temperature = np.stack(
        [base + 5.0 * np.sin(2 * np.pi * k / max(ntime, 1)) for k in range(ntime)]
    )
    u_wind = np.stack(
        [12.0 * np.cos(np.deg2rad(centre_lat)) + 0.1 * k for k in range(ntime)]
    )
    v_wind = np.stack(
        [4.0 * np.sin(np.deg2rad(2 * centre_lon)) + 0.1 * k for k in range(ntime)]
    )

    data = xr.Dataset(
        {
            "temperature": (["time", "nMesh2_face"], temperature, {"units": "K"}),
            "u_wind": (["time", "nMesh2_face"], u_wind, {"units": "m s-1"}),
            "v_wind": (["time", "nMesh2_face"], v_wind, {"units": "m s-1"}),
        },
        coords={"time": np.arange(ntime)},
    )

    grid_path = os.path.join(outdir, "grid.nc")
    data_path = os.path.join(outdir, "data.nc")
    grid.to_netcdf(grid_path)
    data.to_netcdf(data_path)
    return {
        "grid_path": grid_path,
        "data_path": data_path,
        "n_face": int(faces.shape[0]),
        "n_time": int(ntime),
        "grid_mb": round(os.path.getsize(grid_path) / 1e6, 2),
        "data_mb": round(os.path.getsize(data_path) / 1e6, 2),
    }


def build_healpix_data(outdir: str, zoom: int = 5, ntime: int = 8) -> dict:
    """Write a face-centered dataset sized to a HEALPix grid at ``zoom``.

    The grid itself is virtual — callers pass ``healpix:<zoom>`` as the grid
    path — so only the data file is materialized here.
    """
    import os

    import numpy as np
    import uxarray as ux
    import xarray as xr

    os.makedirs(outdir, exist_ok=True)
    grid = ux.Grid.from_healpix(zoom=zoom)
    n_face = int(grid.n_face)

    lat = np.asarray(grid.face_lat.values, dtype="float64")
    lon = np.asarray(grid.face_lon.values, dtype="float64")
    base = (
        288.0 - 40.0 * np.sin(np.deg2rad(lat)) ** 2 + 3.0 * np.cos(np.deg2rad(2 * lon))
    )
    temperature = np.stack(
        [base + 5.0 * np.sin(2 * np.pi * k / max(ntime, 1)) for k in range(ntime)]
    )
    u_wind = np.stack([12.0 * np.cos(np.deg2rad(lat)) + 0.1 * k for k in range(ntime)])
    v_wind = np.stack(
        [4.0 * np.sin(np.deg2rad(2 * lon)) + 0.1 * k for k in range(ntime)]
    )

    data = xr.Dataset(
        {
            "temperature": (["time", "n_face"], temperature, {"units": "K"}),
            "u_wind": (["time", "n_face"], u_wind, {"units": "m s-1"}),
            "v_wind": (["time", "n_face"], v_wind, {"units": "m s-1"}),
        },
        coords={"time": np.arange(ntime)},
    )

    data_path = os.path.join(outdir, f"healpix_z{zoom}_data.nc")
    data.to_netcdf(data_path)
    return {
        "grid_path": f"healpix:{zoom}",
        "data_path": data_path,
        "zoom": int(zoom),
        "n_face": n_face,
        "n_time": int(ntime),
        "data_mb": round(os.path.getsize(data_path) / 1e6, 2),
    }
