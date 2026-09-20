"""Fetch the two raw ERA5 files Step 4 needs, from the RODA-listed bucket.

RODA (AWS Registry of Open Data) is a catalog, not a data server: it told us
the bucket, region and layout, and the bytes then come from S3 directly. That
is the whole reason this script exists as a separate step from
``00_roda_exploration.py`` -- the registry answers *where*, S3 answers *what*.

``s3://nsf-ncar-era5`` is public, so no credentials are needed; the requests
are signed anonymously. Two files, ~500 MB each, so this is the slow step.
They are deliberately not committed -- everything downstream of them is,
under ``data/``, which is why steps 02-05 run without ever calling this.

    python scripts/00_download_era5.py

Requires ``s3fs`` (``uv pip install s3fs``).
"""

from __future__ import annotations

import sys

import paths

BUCKET = "nsf-ncar-era5"
PREFIX = "e5.oper.fc.sfc.accumu/202001"

# (remote object, local destination). The two ERA5 parameters that sum to
# total precipitation: 142 = large-scale precip, 143 = convective precip.
# There is no standalone `tp` file in this product.
OBJECTS = [
    (
        f"{PREFIX}/e5.oper.fc.sfc.accumu.128_142_lsp.ll025sc.2020010106_2020011606.nc",
        paths.LSP_NC,
    ),
    (
        f"{PREFIX}/e5.oper.fc.sfc.accumu.128_143_cp.ll025sc.2020010106_2020011606.nc",
        paths.CP_NC,
    ),
]


def main() -> int:
    try:
        import s3fs
    except ImportError:
        print("s3fs is required: uv pip install s3fs", file=sys.stderr)
        return 1

    # anon=True: the bucket is public and signing with absent credentials
    # fails rather than falling back.
    fs = s3fs.S3FileSystem(anon=True, client_kwargs={"region_name": "us-west-2"})

    paths.RAW.mkdir(parents=True, exist_ok=True)
    for key, dest in OBJECTS:
        if dest.exists():
            print(f"have  {dest.name} ({dest.stat().st_size / 1e6:.0f} MB)")
            continue
        remote = f"{BUCKET}/{key}"
        print(f"get   {remote}")
        # .tmp then rename, so an interrupted download is not mistaken for a
        # complete file by the `dest.exists()` check on the next run.
        tmp = dest.with_suffix(dest.suffix + ".tmp")
        fs.get(remote, str(tmp))
        tmp.rename(dest)
        print(f"wrote {dest} ({dest.stat().st_size / 1e6:.0f} MB)")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
