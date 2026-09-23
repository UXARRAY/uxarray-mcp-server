"""Shared grid loading with HEALPix and GIS support."""

import os
from typing import Any

#: Largest HEALPix zoom we accept. Zoom ``z`` has ``12 * 4**z`` faces, so
#: ``z=13`` is already ~805M faces -- far past what a worker can hold. Anything
#: beyond this is a typo, and failing fast beats an OOM kill on an HPC node.
MAX_HEALPIX_ZOOM = 13

#: URI schemes that denote data held somewhere other than the local
#: filesystem. ``uxarray`` hands these to ``xarray``/``fsspec``, which resolve
#: them natively, so a ``Path.exists()`` precheck on one is meaningless -- it
#: reports False for a perfectly readable remote store and blocks the read.
REMOTE_URI_SCHEMES = (
    "http://",
    "https://",
    "s3://",
    "gs://",
    "gcs://",
    "az://",
    "abfs://",
    "ftp://",
    "dap4://",
)


def is_remote_uri(file_path: Any) -> bool:
    """True when ``file_path`` points at a remote store rather than a file.

    Covers object storage and plain HTTP(S), plus OPeNDAP endpoints, which
    are ordinary https URLs distinguished only by a ``dodsC``/``thredds``
    path segment. Callers use this to skip filesystem existence checks:
    ``Path("https://host/f.nc").exists()`` is always False, and worse,
    ``Path`` collapses the ``//`` so the string is corrupted on the way
    through.
    """
    if not isinstance(file_path, str):
        return False
    lowered = file_path.strip().lower()
    return lowered.startswith(REMOTE_URI_SCHEMES)


def is_opendap_uri(file_path: Any) -> bool:
    """True for an OPeNDAP endpoint (THREDDS ``dodsC``, Hyrax, ``dap4://``).

    These look like ordinary https URLs but are served by a DAP protocol the
    netCDF library speaks directly, so they must be passed as a URL string
    rather than wrapped in an fsspec byte-range file object.
    """
    if not isinstance(file_path, str):
        return False
    lowered = file_path.strip().lower()
    return lowered.startswith("dap4://") or "/dodsc/" in lowered


def is_kerchunk_reference(file_path: Any) -> bool:
    """True when ``file_path`` is a kerchunk reference rather than a dataset.

    Kerchunk publishes chunk manifests as Parquet (``.parq``/``.parquet``)
    or JSON sidecars. These are not netCDF and the default engine cannot
    read them -- they need ``engine="kerchunk"``, which then fetches only
    the byte ranges actually requested.
    """
    if not isinstance(file_path, str):
        return False
    lowered = file_path.strip().lower().split("?", 1)[0]
    return lowered.endswith((".parq", ".parquet")) or (
        "kerchunk" in lowered and lowered.endswith(".json")
    )


def open_remote_store(file_path: str) -> Any:
    """Open a remote dataset, selecting the engine the transport requires.

    Three cases, because they need genuinely different handling:

    * **OPeNDAP** -- the netCDF library speaks DAP natively, so the URL is
      passed through as a string. Correct, but each variable read is a
      protocol round-trip, which makes whole-field reads slow.
    * **Kerchunk reference** -- needs ``engine="kerchunk"``, which then
      fetches only the byte ranges actually requested.
    * **Plain remote netCDF** -- ``xr.open_dataset(url)`` does *not* work:
      the netCDF4 engine cannot take an https URL that is not DAP. Opened
      instead as an fsspec file object, which serves reads as HTTP range
      requests. Engines are tried in order because the file may be HDF5
      (``h5netcdf``) or classic netCDF-3 (``scipy``), and neither reads the
      other's format from a file-like object.
    """
    import xarray as xr

    if is_kerchunk_reference(file_path):
        return xr.open_dataset(
            file_path,
            engine="kerchunk",
            storage_options={"remote_protocol": "https", "lazy": True},
        )
    if is_opendap_uri(file_path):
        return xr.open_dataset(file_path)

    import fsspec

    handle = fsspec.open(file_path, "rb").open()
    errors = []
    for engine in ("h5netcdf", "scipy"):
        try:
            return xr.open_dataset(handle, engine=engine)
        except Exception as exc:  # noqa: PERF203 - need each engine's reason
            errors.append(f"{engine}: {exc}")
            try:
                handle.seek(0)
            except Exception:
                handle = fsspec.open(file_path, "rb").open()
    raise ValueError(
        f"Could not open remote dataset {file_path}. Tried " + "; ".join(errors)
    )


#: Remap-*weights* files carry a complete description of both grids they map
#: between, so the source mesh is fully recoverable from one -- but under names
#: no grid reader recognises. Two conventions are in circulation and they share
#: no variable names at all, so both are handled:
#:
#: * SCRIP weights prefix the plain SCRIP names with ``src_``/``dst_``.
#: * ESMF weights (what ``ESMF_RegridWeightGen`` and NCO emit) use a terse
#:   ``_a``/``_b`` suffix scheme: ``xc``/``yc`` for centers, ``xv``/``yv`` for
#:   vertices, with dimensions ``n_a`` (cells) and ``nv_a`` (corners).
WEIGHTS_VAR_RENAME = {
    "scrip": {
        "src_grid_dims": "grid_dims",
        "src_grid_center_lat": "grid_center_lat",
        "src_grid_center_lon": "grid_center_lon",
        "src_grid_corner_lat": "grid_corner_lat",
        "src_grid_corner_lon": "grid_corner_lon",
        "src_grid_imask": "grid_imask",
        "src_grid_area": "grid_area",
    },
    "esmf": {
        "src_grid_dims": "grid_dims",
        "yc_a": "grid_center_lat",
        "xc_a": "grid_center_lon",
        "yv_a": "grid_corner_lat",
        "xv_a": "grid_corner_lon",
        "mask_a": "grid_imask",
        "area_a": "grid_area",
    },
}

WEIGHTS_DIM_RENAME = {
    "scrip": {
        "src_grid_size": "grid_size",
        "src_grid_corners": "grid_corners",
        "src_grid_rank": "grid_rank",
    },
    "esmf": {
        "n_a": "grid_size",
        "nv_a": "grid_corners",
        "num_vertices": "grid_corners",
        "src_grid_rank": "grid_rank",
    },
}

#: Corner coordinates are the discriminator. A weights file carrying only cell
#: centers describes no polygons and cannot be turned into a mesh by renaming.
WEIGHTS_REQUIRED = {
    "scrip": {"src_grid_corner_lat", "src_grid_corner_lon"},
    "esmf": {"xv_a", "yv_a"},
}


def weights_convention(dataset: Any) -> str | None:
    """Return ``"scrip"``, ``"esmf"``, or ``None`` if not a weights file."""
    names = set(getattr(dataset, "variables", {}))
    for convention, required in WEIGHTS_REQUIRED.items():
        if required <= names:
            return convention
    return None


def is_scrip_weights(dataset: Any) -> bool:
    """True when ``dataset`` is a remap-weights file rather than a grid file."""
    return weights_convention(dataset) is not None


def scrip_grid_from_weights(dataset: Any) -> Any:
    """Extract the source grid from a remap-weights dataset as SCRIP.

    Returns a new ``xarray.Dataset`` holding only the source-grid variables,
    renamed to the plain SCRIP names readers expect. The weight arrays
    (``S``, ``row``, ``col``) and the entire destination grid are dropped --
    they are the bulk of the file and irrelevant to mesh topology, so
    excluding them also keeps a remote read small.

    Raises
    ------
    ValueError
        If ``dataset`` is not a recognised weights file.
    """
    convention = weights_convention(dataset)
    if convention is None:
        raise ValueError("Dataset is not a recognised SCRIP or ESMF weights file.")

    rename = {
        k: v
        for k, v in WEIGHTS_VAR_RENAME[convention].items()
        if k in dataset.variables
    }
    subset = dataset[list(rename)].rename(rename)
    dims = {k: v for k, v in WEIGHTS_DIM_RENAME[convention].items() if k in subset.dims}
    if dims:
        subset = subset.rename_dims(dims)

    # SCRIP readers switch on the units attribute to decide whether to convert
    # from radians. ESMF weight files write degrees but do not always label
    # them, and an unlabelled radian-assumption would silently collapse the
    # whole mesh toward the origin -- so make the assumption explicit.
    for name in (
        "grid_center_lat",
        "grid_center_lon",
        "grid_corner_lat",
        "grid_corner_lon",
    ):
        if name in subset and "units" not in subset[name].attrs:
            subset[name].attrs["units"] = "degrees"

    subset.attrs = dict(dataset.attrs)
    subset.attrs["title"] = subset.attrs.get("source_grid", "remap source grid")
    subset.attrs["Conventions"] = "SCRIP"
    return subset


def open_grid_object(obj: Any) -> Any:
    """Open a Grid from a path/URL/file-object, unwrapping SCRIP weights files.

    Tries the direct reader first so ordinary grid files take the normal
    path, and only falls back to the weights adapter when the direct attempt
    fails. On total failure the error names the variables actually present,
    because "failed to parse uxgrid information" alone gives the caller
    nothing to act on.
    """
    import uxarray as ux
    import xarray as xr

    try:
        return ux.open_grid(obj)
    except Exception as direct_error:
        try:
            ds = obj if isinstance(obj, xr.Dataset) else xr.open_dataset(obj)
        except Exception:
            raise direct_error from None
        if is_scrip_weights(ds):
            return ux.open_grid(scrip_grid_from_weights(ds))
        raise ValueError(
            f"{direct_error} Variables present: {sorted(ds.variables)[:40]}"
        ) from direct_error


def attach_grid(dataset: Any, grid: Any) -> Any:
    """Bind an ``xarray.Dataset`` to a Grid, mapping its spatial dim to UGRID.

    ``ux.open_dataset`` renames the model's spatial dimension (CAM writes
    ``ncol``, MPAS ``nCells``, ...) to the UGRID name before attaching. Building
    a ``UxDataset`` by hand skips that step, and the result looks fine until an
    operation asks whether a variable is face-centered and is told no. The
    mapping is by dimension *length* because the source name is model-specific
    and unknowable in advance.

    Ambiguity is refused rather than guessed: if the mesh has two element
    counts that happen to be equal, a length match cannot distinguish them, and
    silently picking one would mislocate the data onto the wrong mesh elements.
    """
    sizes = {name: getattr(grid, name, None) for name in ("n_face", "n_node", "n_edge")}
    sizes = {k: v for k, v in sizes.items() if v}
    ambiguous = len(set(sizes.values())) != len(sizes)

    rename = {}
    for dim, length in dataset.sizes.items():
        if dim in sizes:
            continue
        matches = [name for name, n in sizes.items() if n == length]
        if not matches:
            continue
        if ambiguous and len(matches) > 1:
            raise ValueError(
                f"Cannot map dimension {dim!r} (length {length}): the mesh has "
                f"equal counts for {matches}. Pass the data through "
                "ux.open_dataset instead."
            )
        rename[dim] = matches[0]

    if rename:
        dataset = dataset.rename_dims(rename)
    return dataset


def is_healpix_spec(file_path: Any) -> bool:
    """True when ``file_path`` is a virtual HEALPix spec, not a real file.

    The spec form is ``healpix:<zoom>`` (case-insensitive). The colon is
    required: a prefix-only test such as ``startswith("healpix")`` also
    matches an ordinary file named ``healpix_z5_data.nc``, which would be
    silently replaced by a virtual grid of the wrong size instead of being
    read from disk.
    """
    if not isinstance(file_path, str):
        return False
    prefix, sep, _ = file_path.partition(":")
    return bool(sep) and prefix.strip().lower() == "healpix"


def parse_healpix_zoom(file_path: str) -> int:
    """Extract and validate the zoom level from a ``healpix:<zoom>`` spec.

    Raises
    ------
    ValueError
        If the spec is malformed, the zoom is not an integer, is negative, or
        exceeds :data:`MAX_HEALPIX_ZOOM`. Silently coercing these (the old
        behaviour) produced a valid-looking grid at the wrong resolution.
    """
    _, _, raw = file_path.partition(":")
    raw = raw.strip()
    try:
        zoom = int(raw)
    except ValueError:
        raise ValueError(
            "Invalid HEALPix format. Use 'healpix:<zoom_level>' "
            f"(e.g. 'healpix:2'); got {file_path!r}."
        ) from None
    if zoom < 0 or zoom > MAX_HEALPIX_ZOOM:
        raise ValueError(
            "Invalid HEALPix format. Zoom must be between 0 and "
            f"{MAX_HEALPIX_ZOOM} inclusive; got {zoom}."
        )
    return zoom


def load_grid(file_path: str) -> Any:
    """Load a UXarray Grid from a file path, HEALPix spec, or shapefile/geojson.

    Parameters
    ----------
    file_path : str
        Path to mesh file, or "healpix:<zoom>" for virtual HEALPix meshes.

    Returns
    -------
    ux.Grid
        Loaded grid object.
    """
    import uxarray as ux

    if is_healpix_spec(file_path):
        return ux.Grid.from_healpix(zoom=parse_healpix_zoom(file_path))

    if is_remote_uri(file_path):
        # OPeNDAP endpoints are read by the netCDF library itself, so the URL
        # goes through untouched. Anything else is a byte-range read, which
        # needs an fsspec file object rather than a path string.
        if is_opendap_uri(file_path):
            return open_grid_object(file_path)
        import fsspec

        handle = fsspec.open(file_path, mode="rb").open()
        return open_grid_object(handle)

    ext = os.path.splitext(file_path.lower())[1]
    if ext in [".shp", ".geojson"]:
        return ux.Grid.from_file(file_path, backend="geopandas")

    return open_grid_object(file_path)


def load_dataset(grid_path: str, data_path: str) -> Any:
    """Load a UXarray Dataset from grid and data paths, supporting shapefiles/geojson.

    Parameters
    ----------
    grid_path : str
        Path to mesh grid file or "healpix:<zoom>".
    data_path : str
        Path to netCDF data file.

    Returns
    -------
    ux.UxDataset
        Loaded dataset object.
    """
    import uxarray as ux
    import xarray as xr

    # HEALPix and GIS grids don't round-trip through ux.open_dataset() as a
    # "grid file" the way a real UGRID/MPAS/SCRIP file does: grid.to_xarray()
    # returns a minimal representation (e.g. HEALPix has no node coordinates)
    # that the generic UGRID reader rejects. Attach the data directly to the
    # already-loaded Grid object instead.
    if is_healpix_spec(grid_path):
        grid = ux.Grid.from_healpix(zoom=parse_healpix_zoom(grid_path))
        ds = (
            open_remote_store(data_path)
            if is_remote_uri(data_path)
            else xr.open_dataset(data_path)
        )
        return ux.UxDataset(attach_grid(ds, grid), uxgrid=grid)

    ext = os.path.splitext(grid_path.lower())[1]
    if ext in [".shp", ".geojson"]:
        grid = ux.Grid.from_file(grid_path, backend="geopandas")
        return ux.UxDataset(xr.open_dataset(data_path), uxgrid=grid)

    # If either side is remote, load the grid on its own and attach the data
    # as an already-opened xarray Dataset. ux.open_dataset(grid, data) takes
    # two path strings and cannot express a kerchunk engine or fsspec
    # options, so the two-step form is the only way to reach remote stores.
    if is_remote_uri(grid_path) or is_remote_uri(data_path):
        grid = load_grid(grid_path)
        ds = (
            open_remote_store(data_path)
            if is_remote_uri(data_path)
            else xr.open_dataset(data_path)
        )
        return ux.UxDataset(attach_grid(ds, grid), uxgrid=grid)

    try:
        return ux.open_dataset(grid_path, data_path)
    except Exception as direct_error:
        # ux.open_dataset reads the grid itself and so never sees the
        # weights-file adapter in load_grid. Two local paths used to stop
        # here, which made a remap-weights "grid" work for the temporal-mean
        # map (whose worker copy has its own adapter) and fail for every
        # other tool. Retry through the two-step form; if the grid is not
        # the problem, the original error is the one worth reading.
        try:
            grid = load_grid(grid_path)
        except Exception:
            raise direct_error from None
        return ux.UxDataset(attach_grid(xr.open_dataset(data_path), grid), uxgrid=grid)
