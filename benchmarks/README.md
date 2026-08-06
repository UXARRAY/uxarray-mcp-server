# Benchmarks

Heavy, compute-intensive checks that are deliberately **not** part of the
pytest suite.

The unit tests mock the UXarray layer, so they verify that a tool was
*called* correctly. They cannot catch the failure mode that matters most
here: a tool that returns a plausible-looking number that is wrong. These
benchmarks run real UXarray compute on real meshes and assert analytic
invariants, which is how three silent HEALPix bugs and a zonal-axis data
corruption bug were found.

They are kept local because they build meshes of up to ~200k faces, take
minutes, and write hundreds of MB.

## Layout

```
benchmarks/
  README.md
  heavy/
    runner.py          # entry point: builds meshes, runs suites, writes JSON
    meshgen.py         # deterministic mesh/data builders (worker-serializable)
    checks.py          # invariant assertions shared by all suites
    cases/
      pipeline_cases.py  # file-backed mesh, full tool pipeline
      healpix_cases.py   # HEALPix-specific analytic invariants
    meshes/            # generated inputs (gitignored)
    results/           # per-run JSON reports (gitignored)
```

## Running

```bash
uv run python benchmarks/heavy/runner.py --suite healpix
uv run python benchmarks/heavy/runner.py --suite pipeline --scale small
uv run python benchmarks/heavy/runner.py --suite all --scale large

# Same cases, executed on an HPC endpoint
uv run python benchmarks/heavy/runner.py --suite all --remote --endpoint chrysalis
```

Scales are `small` / `medium` / `large`. Meshes are cached in
`heavy/meshes/` and reused; delete a subdirectory to force a rebuild.
The runner exits non-zero if any case errors or fails a check, so it can
gate a release.

## Why HEALPix gets its own suite

HEALPix is the only grid family here whose correctness is checkable in
closed form:

- zoom `z` has exactly `12 * 4**z` faces,
- every face has identical area (that is the defining property),
- those areas sum to `4*pi` on the unit sphere.

Any deviation is a real bug, with no tolerance argument to hide behind.
`healpix_zoom_sweep` checks all three across zooms 0-7. `healpix_zonal_symmetry`
adds an end-to-end check: the synthetic field is an even function of latitude
once the longitude term averages over a band, so an asymmetric zonal profile
means faces are landing in the wrong bands.

`healpix_spec_parsing` is a regression guard for three bugs found by this
suite:

1. Prefix-only `startswith("healpix")` tests hijacked ordinary files named
   `healpix_z5_data.nc`, silently substituting a virtual grid of the wrong size.
2. Local loaders accepted `HEALPix:3` but remote routing did not, so the same
   spec ran locally and refused to run remotely.
3. A malformed zoom was coerced to a default instead of raising, producing a
   valid-looking grid at the wrong resolution.

## Local vs remote

Mesh generation is analytic and RNG-free, so a mesh built locally and one
built on a worker are bit-identical. That makes local-vs-remote result
comparison meaningful rather than approximate. Everything in `meshgen.py`
inlines its imports and depends on no other function in the module, because
module-level helpers do not survive `AllCodeStrategies` serialization.
