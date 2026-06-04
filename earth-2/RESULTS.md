# Earth-2 Demo Results

This run used the public NOAA UFS Replay bucket:

```text
s3://noaa-ufs-gefsv13replay-pds/
```

## Discovery Highlights

The Earth-2/HealDA context prefix inspected by the demo is:

```text
2022/01/2022010100/
```

Representative objects listed from that cycle include:

| Object | Size |
|---|---:|
| `GFSFLX.GrbF00` | 35.299 MB |
| `GFSFLX.GrbF03` | 77.125 MB |
| `GFSPRS.GrbF00` | 710.353 MB |
| `GFSPRS.GrbF03` | 742.375 MB |
| `fv3_increment6.nc` | 2468.338 MB |

This demonstrates why an agent needs metadata-aware planning before moving
data: the bucket contains both small diagnostics and multi-GB state files.

## Lightweight NetCDF Tile Inspection

The runnable demo downloads one smaller public native NetCDF tile:

```text
s3://noaa-ufs-gefsv13replay-pds//2018010106/hr4_land/sfc_data.tile1.nc
```

Observed metadata from the run:

| Field | Value |
|---|---:|
| File size | 40.177 MB |
| Variables | 110 |
| Horizontal tile shape | 384 x 384 |
| Candidate Earth-system variables | `tsea`, `snowxy`, `qsnowxy` |

The `tsea` surface temperature-like field summary was:

| Statistic | Value |
|---|---:|
| Minimum | 262.866 K |
| Maximum | 303.759 K |
| Mean | 292.551 K |
| Standard deviation | 6.618 K |

## Funding Case

This is the connective tissue that scientific AI workflows need:

- public data discovery without credentials
- size-aware planning before expensive data movement
- metadata inspection before analysis
- direct bridge to UXarray, HEALPix, and unstructured-grid workflows
- a path to run the same workflow locally or on HPC via MCP endpoint tools

The result is not just a notebook. It is a reproducible, auditable workflow that
can become an MCP agent capability for Earth-system foundation model evaluation,
regridding, and mesh-aware diagnostics.
