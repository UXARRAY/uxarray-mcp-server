"""Tool-retrieval eval — labeled prompts.

Each entry is a (prompt, expected_tool) pair. The expected_tool must be a
name that appears in `uxarray_mcp.tools.__all__`.

These are hand-written to span the visible tool surface: inspection,
calculation, plotting, regridding, ensemble stats, vector calculus,
state/session management. Add more as the catalog grows.
"""

from __future__ import annotations

PROMPTS: list[tuple[str, str]] = [
    # Inspection / discovery
    (
        "Tell me the topology of this mesh — how many faces, nodes, edges.",
        "inspect_mesh",
    ),
    (
        "What variables are in this dataset and what dimensions do they have?",
        "inspect_variable",
    ),
    ("Are there any NaN or fill values in this dataset?", "validate_dataset"),
    ("What can I do with this MPAS grid file?", "get_capabilities"),
    # Statistics on a single field
    ("Compute the area of each face on this mesh.", "calculate_area"),
    ("Give me the area-weighted zonal mean of temperature.", "calculate_zonal_mean"),
    ("Take the time average of the precipitation variable.", "calculate_temporal_mean"),
    ("Compute anomalies relative to the climatology.", "calculate_anomaly"),
    # Vector calculus
    ("Compute the curl of the wind field.", "calculate_curl"),
    ("Find the divergence of the velocity field.", "calculate_divergence"),
    ("Compute the gradient of surface pressure.", "calculate_gradient"),
    (
        "Take the azimuthal mean of precipitation around the hurricane center.",
        "calculate_azimuthal_mean",
    ),
    # Comparison / ensemble
    ("Compare these two runs for the same variable.", "compare_fields"),
    ("Compute the bias between simulation A and observations B.", "calculate_bias"),
    ("Average across the ensemble members.", "calculate_ensemble_mean"),
    ("How spread out are the ensemble members?", "calculate_ensemble_spread"),
    # Regridding / subsetting
    (
        "Remap this field from the source mesh to a coarser target grid.",
        "remap_variable",
    ),
    ("Subset the dataset to the North Atlantic bounding box.", "subset_bbox"),
    ("Clip the data to this irregular polygon.", "subset_polygon"),
    ("Pull out a cross section along 40 degrees north.", "extract_cross_section"),
    # Plotting
    ("Show me a wireframe plot of the mesh.", "plot_mesh"),
    ("Plot temperature as a colored map.", "plot_variable"),
    ("Plot the zonal mean as a line chart.", "plot_zonal_mean"),
    ("Make a map of the mesh with geographic coastlines.", "plot_mesh_geo"),
    # Export
    ("Save the result to a NetCDF file.", "export_to_netcdf"),
    ("Write the data out as CSV.", "export_to_csv"),
    # State / session / workflows
    ("Start a new analysis session.", "create_session"),
    ("Run the full first-look pipeline on this mesh.", "analyze_dataset"),
    ("Resume the workflow I started earlier.", "resume_workflow"),
    ("Check whether the HPC endpoint is healthy.", "diagnose_endpoint"),
]
