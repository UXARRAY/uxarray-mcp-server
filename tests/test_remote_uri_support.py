"""Remote-URI handling and the remap-weights grid adapter.

Two gaps motivate this module, both found while reproducing the CONUS
precipitation case study against GDEX-hosted data:

1. Every tool guarded its inputs with ``Path(p).exists()``, which is False
   for any URL -- and ``Path`` additionally collapses ``https://`` to
   ``https:/``, so the string was corrupted on the way through. Remote data
   was unreachable regardless of whether the transport worked.
2. The only ne120-class mesh some archives publish is a remap *weights*
   file. It carries the full source mesh, but under names no grid reader
   recognises, so ``ux.open_grid`` fails with "Failed to parse uxgrid
   information" -- an error that names nothing the caller can act on.
"""

import numpy as np
import pytest
import xarray as xr

from uxarray_mcp.domain.mesh import (
    attach_grid,
    is_kerchunk_reference,
    is_opendap_uri,
    is_remote_uri,
    scrip_grid_from_weights,
    weights_convention,
)


class TestARemoteUriIsNotAFilesystemPath:
    @pytest.mark.parametrize(
        "uri",
        [
            "https://tds.gdex.ucar.edu/thredds/dodsC/files/d651007/grid.nc",
            "http://example.org/mesh.nc",
            "s3://bucket/key/mesh.nc",
            "gs://bucket/mesh.nc",
            "az://container/mesh.nc",
            "dap4://example.org/mesh",
        ],
        ids=lambda u: u.split("://", 1)[0],
    )
    def test_every_supported_scheme_is_recognised(self, uri):
        assert is_remote_uri(uri)

    @pytest.mark.parametrize(
        "path", ["/glade/p/mesh.nc", "mesh.nc", "./data/mesh.nc", "healpix:3"]
    )
    def test_a_local_path_is_not_remote(self, path):
        assert not is_remote_uri(path)

    def test_a_non_string_is_not_remote(self):
        """Callers pass whatever they were given; None must not raise here."""
        assert not is_remote_uri(None)
        assert not is_remote_uri(3)

    def test_scheme_matching_ignores_case_and_surrounding_space(self):
        assert is_remote_uri("  HTTPS://example.org/mesh.nc  ")

    def test_pathlib_would_corrupt_the_uri(self):
        """The reason the guard exists, asserted rather than described.

        If this ever stops being true the workaround can be dropped, so it
        is worth failing loudly rather than carrying the guard on faith.
        """
        from pathlib import Path

        url = "https://example.org/mesh.nc"
        assert str(Path(url)) != url
        assert not Path(url).exists()


class TestOpendapNeedsTheUrlNotAFileObject:
    @pytest.mark.parametrize(
        "uri",
        [
            "https://tds.gdex.ucar.edu/thredds/dodsC/files/d651007/grid.nc",
            "https://HOST/THREDDS/DODSC/x.nc",
            "dap4://example.org/mesh",
        ],
    )
    def test_dap_endpoints_are_detected(self, uri):
        assert is_opendap_uri(uri)

    def test_a_plain_http_netcdf_is_not_dap(self):
        """fileServer URLs differ from dodsC only by that path segment."""
        assert not is_opendap_uri(
            "https://tds.gdex.ucar.edu/thredds/fileServer/files/d651007/grid.nc"
        )


class TestKerchunkReferencesNeedTheirOwnEngine:
    @pytest.mark.parametrize(
        "uri",
        [
            "https://data.gdex.ucar.edu/d651007/kerchunk/PRECC.parq",
            "https://host/x.parquet",
            "https://host/kerchunk/PRECC.json",
        ],
    )
    def test_manifest_spellings_are_detected(self, uri):
        assert is_kerchunk_reference(uri)

    def test_a_query_string_does_not_hide_the_extension(self):
        assert is_kerchunk_reference("https://host/x.parq?versionId=9")

    def test_a_plain_netcdf_is_not_a_reference(self):
        assert not is_kerchunk_reference("https://host/PRECC.nc")

    def test_an_unrelated_json_is_not_a_reference(self):
        """Only kerchunk-named JSON counts; any other sidecar is not one."""
        assert not is_kerchunk_reference("https://host/attributes.json")


def _esmf_weights(n_cells=4, n_corners=4):
    """A minimal ESMF_RegridWeightGen-style weights file.

    Deliberately includes the destination grid and the weight arrays, because
    the adapter's job is partly to *drop* them -- they are the bulk of a real
    file and irrelevant to source-mesh topology.
    """
    rng = np.arange(n_cells * n_corners, dtype="float64").reshape(n_cells, n_corners)
    return xr.Dataset(
        {
            "yc_a": ("n_a", np.linspace(-45.0, 45.0, n_cells)),
            "xc_a": ("n_a", np.linspace(0.0, 270.0, n_cells)),
            "yv_a": (("n_a", "nv_a"), rng),
            "xv_a": (("n_a", "nv_a"), rng + 100.0),
            "mask_a": ("n_a", np.ones(n_cells, dtype="int32")),
            "area_a": ("n_a", np.full(n_cells, 0.25)),
            # Destination grid + weights: must not survive the adapter.
            "yc_b": ("n_b", np.zeros(2)),
            "xc_b": ("n_b", np.zeros(2)),
            "S": ("n_s", np.ones(3)),
            "row": ("n_s", np.ones(3, dtype="int32")),
            "col": ("n_s", np.ones(3, dtype="int32")),
        },
        attrs={"source_grid": "ne120np4_pentagons"},
    )


def _scrip_weights(n_cells=4, n_corners=4):
    rng = np.arange(n_cells * n_corners, dtype="float64").reshape(n_cells, n_corners)
    return xr.Dataset(
        {
            "src_grid_center_lat": ("src_grid_size", np.linspace(-45.0, 45.0, n_cells)),
            "src_grid_center_lon": ("src_grid_size", np.linspace(0.0, 270.0, n_cells)),
            "src_grid_corner_lat": (("src_grid_size", "src_grid_corners"), rng),
            "src_grid_corner_lon": (("src_grid_size", "src_grid_corners"), rng + 100.0),
            "src_grid_imask": ("src_grid_size", np.ones(n_cells, dtype="int32")),
            "dst_grid_center_lat": ("dst_grid_size", np.zeros(2)),
            "S": ("n_s", np.ones(3)),
        }
    )


class TestBothWeightsConventionsAreRecognised:
    def test_esmf_is_detected_by_its_vertex_variables(self):
        assert weights_convention(_esmf_weights()) == "esmf"

    def test_scrip_is_detected_by_its_prefixed_corners(self):
        assert weights_convention(_scrip_weights()) == "scrip"

    def test_an_ordinary_grid_file_is_not_a_weights_file(self):
        grid = xr.Dataset(
            {
                "grid_corner_lat": (("grid_size", "grid_corners"), np.zeros((2, 4))),
                "grid_corner_lon": (("grid_size", "grid_corners"), np.zeros((2, 4))),
            }
        )
        assert weights_convention(grid) is None

    def test_centers_alone_are_not_enough(self):
        """A file with no corner coordinates describes no polygons.

        Renaming cannot invent a mesh from cell centers, so this must be
        refused rather than half-converted into something unusable.
        """
        centers_only = xr.Dataset(
            {
                "yc_a": ("n_a", np.zeros(4)),
                "xc_a": ("n_a", np.zeros(4)),
            }
        )
        assert weights_convention(centers_only) is None


class TestTheSourceMeshIsRecoveredFromWeights:
    def test_esmf_names_are_mapped_to_plain_scrip(self):
        out = scrip_grid_from_weights(_esmf_weights())
        assert set(out.data_vars) == {
            "grid_center_lat",
            "grid_center_lon",
            "grid_corner_lat",
            "grid_corner_lon",
            "grid_imask",
            "grid_area",
        }
        assert out.sizes["grid_size"] == 4
        assert out.sizes["grid_corners"] == 4

    def test_scrip_names_are_mapped_too(self):
        out = scrip_grid_from_weights(_scrip_weights())
        assert "grid_corner_lat" in out
        assert out.sizes["grid_size"] == 4

    def test_the_destination_grid_and_weights_are_dropped(self):
        """These are the bulk of a real file; keeping them defeats the point."""
        out = scrip_grid_from_weights(_esmf_weights())
        for dropped in ("S", "row", "col", "yc_b", "xc_b"):
            assert dropped not in out.variables

    def test_values_survive_the_rename_unchanged(self):
        source = _esmf_weights()
        out = scrip_grid_from_weights(source)
        np.testing.assert_array_equal(
            out["grid_corner_lat"].values, source["yv_a"].values
        )
        np.testing.assert_array_equal(
            out["grid_center_lon"].values, source["xc_a"].values
        )

    def test_unlabelled_coordinates_are_declared_as_degrees(self):
        """SCRIP readers switch on the units attribute to decide whether to
        convert from radians. ESMF writes degrees but does not always say so,
        and an unlabelled radian assumption collapses the mesh toward the
        origin -- a wrong mesh that still parses, which is the worst outcome.
        """
        out = scrip_grid_from_weights(_esmf_weights())
        for name in ("grid_center_lat", "grid_corner_lon"):
            assert out[name].attrs["units"] == "degrees"

    def test_an_existing_units_attribute_is_left_alone(self):
        source = _esmf_weights()
        source["yc_a"].attrs["units"] = "radians"
        out = scrip_grid_from_weights(source)
        assert out["grid_center_lat"].attrs["units"] == "radians"

    def test_the_result_announces_the_scrip_convention(self):
        assert scrip_grid_from_weights(_esmf_weights()).attrs["Conventions"] == "SCRIP"

    def test_a_non_weights_file_is_refused(self):
        with pytest.raises(ValueError, match="not a recognised"):
            scrip_grid_from_weights(xr.Dataset({"foo": ("x", np.zeros(3))}))


class _FakeGrid:
    def __init__(self, n_face, n_node, n_edge):
        self.n_face = n_face
        self.n_node = n_node
        self.n_edge = n_edge


class TestDataDimsAreMappedOntoTheMesh:
    """``ux.open_dataset`` renames the model's spatial dim to the UGRID name.

    Building a ``UxDataset`` by hand skips that, and the result looks fine
    until an operation asks whether a variable is face-centered and is told
    no -- which is exactly how this surfaced, as a spurious "PRECC is not
    face-centered".
    """

    def test_a_model_specific_dim_is_renamed_by_length(self):
        grid = _FakeGrid(n_face=777602, n_node=780456, n_edge=2329471)
        ds = xr.Dataset({"PRECC": (("time", "ncol"), np.zeros((2, 777602)))})
        assert attach_grid(ds, grid).sizes["n_face"] == 777602

    def test_unrelated_dims_are_left_alone(self):
        grid = _FakeGrid(n_face=6, n_node=8, n_edge=12)
        ds = xr.Dataset({"v": (("time", "ncol"), np.zeros((3, 6)))})
        out = attach_grid(ds, grid)
        assert "time" in out.dims
        assert out.sizes["time"] == 3

    def test_an_already_ugrid_dataset_is_unchanged(self):
        grid = _FakeGrid(n_face=6, n_node=8, n_edge=12)
        ds = xr.Dataset({"v": ("n_face", np.zeros(6))})
        assert attach_grid(ds, grid).sizes["n_face"] == 6

    def test_equal_element_counts_are_refused_not_guessed(self):
        """A length match cannot tell two equal counts apart, and picking one
        would silently mislocate the data onto the wrong mesh elements.
        """
        grid = _FakeGrid(n_face=6, n_node=6, n_edge=12)
        ds = xr.Dataset({"v": ("ncol", np.zeros(6))})
        with pytest.raises(ValueError, match="equal counts"):
            attach_grid(ds, grid)

    def test_a_dim_matching_nothing_is_left_alone(self):
        grid = _FakeGrid(n_face=6, n_node=8, n_edge=12)
        ds = xr.Dataset({"v": ("station", np.zeros(99))})
        assert attach_grid(ds, grid).sizes["station"] == 99
