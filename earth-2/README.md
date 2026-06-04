# Earth-2 / HealDA UFS Replay Demo

This folder contains a small reproducible experiment for demonstrating why an
MCP server around UXarray is useful for DOE-style climate and Earth-system AI
workflows.

The target story is:

- NVIDIA Earth-2 / HealDA-style models need carefully curated Earth-system
  analysis data.
- NOAA UFS Replay provides public, cloud-hosted atmospheric and surface states.
- A scientific MCP agent should be able to discover the data, inspect metadata,
  decide what is safe to download, summarize variables, and connect the result
  to unstructured or HEALPix analysis workflows.

The demo is deliberately conservative. By default it lists public S3 objects and
does not download large files. Use `--download` to pull one small native NetCDF
surface tile from the public NOAA Open Data bucket.

## Data Source

Public S3 bucket:

```bash
aws s3 ls s3://noaa-ufs-gefsv13replay-pds/ --no-sign-request
```

Example UFS Replay cycle used in Earth-2/HealDA-style training data discovery:

```text
s3://noaa-ufs-gefsv13replay-pds/2022/01/2022010100/
```

Small native NetCDF tile used by this local demo:

```text
s3://noaa-ufs-gefsv13replay-pds//2018010106/hr4_land/sfc_data.tile1.nc
```

## Quick Start

Metadata-only run:

```bash
python earth-2/ufs_replay_demo.py --no-download
```

Download and inspect one NetCDF tile:

```bash
python earth-2/ufs_replay_demo.py --download
```

Outputs are written to `earth-2/outputs/`:

- `ufs_replay_demo.json`
- `ufs_replay_demo.md`
- `tsea_tile_preview.png`

Generated outputs and downloaded NetCDF files are gitignored. A portable summary
from a successful run is tracked in `RESULTS.md`.

## Why This Matters

The point is not just to download a file. The point is to show that a model- and
data-aware MCP tool can:

- discover public climate/forecast datasets without hard-coded local paths
- avoid accidentally pulling multi-GB files
- inspect scientific metadata before analysis
- summarize candidate variables for downstream UXarray/HEALPix workflows
- produce provenance that a DOE reviewer can audit

That is exactly the kind of glue needed between foundation-model weather systems,
observational reanalysis data, unstructured meshes, HPC endpoints, and scientific
agents.
