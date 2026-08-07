# DYAMOND resolution-ladder benchmark

Measures one fixed request pipeline across the DYAMOND-1 MPAS resolution
ladder (30 / 15 / 7.5 / 3.75 km), a 64x range in cell count from 655,362 to
41,943,042 faces.

This ladder is the same one UXarray's own ASV performance suite tracks, so
the axis is comparable with prior work rather than particular to this repo.
Unlike a bare-mesh benchmark it uses real model output: each diagnostic file
carries face-centred fields (for example `t2m`) and node-centred fields (for
example `vorticity_200hPa`), so one request exercises two mesh locations.

## Running

The data live on NSF NCAR GLADE and the largest grid is 19.8 GB, so this runs
at the endpoint rather than locally:

```bash
uv run python benchmarks/dyamond/run_data_ladder.py            # all four rungs
uv run python benchmarks/dyamond/run_data_ladder.py 30km 15km  # a subset
```

Results append to `data_ladder_results.json` after every rung, so an
interrupted run keeps the rungs it already finished.

## Reading the numbers

Three costs are deliberately separated, because collapsing them is misleading:

- **JIT compilation** — first call only, per worker deployment. UXarray's
  spherical-geometry kernels are `numba`-jitted with `cache=True`, so the
  first zonal reduction on a fresh worker can pay tens of seconds that no
  later call pays.
- **Bounds construction** — once per grid, scales with cell count. The first
  zonal reduction triggers it.
- **The reduction itself** — once per request.

Our first 30 km run reported 59.5 s for the 1-degree zonal mean; the same call
afterwards took 1.4 s. Reporting the cold number as "the cost of a zonal mean"
would misinform every downstream scheduling decision.

Timings are single-worker on one Casper node with numba resolving to two
threads, so they describe an unoptimized serial path and are upper bounds.

## Reproducibility

`data_ladder_results.json` is the run the paper table cites. A later repeat of
the 30 km rung on the same endpoint gave 7.98 s bounds and 1.33 s warm
1-degree zonal against 7.46 s and 1.40 s, so the run-to-run spread on a shared
node is a few percent — well inside the order-of-magnitude effects the table
is about.
