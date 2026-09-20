"""Where this case study reads and writes.

The scripts originally hardcoded ``/tmp/era5_raw``, which is where the
analysis actually ran. That directory does not survive a reboot, let alone
a different machine, so nothing reproduced from a fresh clone even though
every intermediate needed was committed under ``data/``.

Resolution order, first match wins:

1. ``ERA5_CASE_STUDY_DIR`` if set -- for rerunning against a scratch
   directory without touching the committed inputs.
2. ``data/`` next to this script -- the committed intermediates, so
   ``02``/``03``/``04``/``05`` run from a fresh clone with no download.

The two raw ERA5 files are ~500 MB each and are not committed. Only
``01_build_era5_conus_field.py`` needs them; get them with
``00_download_era5.py``, which writes into ``raw/`` under the same root.
"""

from __future__ import annotations

import os
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_DEFAULT_ROOT = _HERE.parent

ROOT = Path(os.environ.get("ERA5_CASE_STUDY_DIR", _DEFAULT_ROOT))

DATA = ROOT / "data"
IMAGES = ROOT / "images"
RAW = ROOT / "raw"

# Step 4 inputs: the two raw ERA5 accumulation files, as named on S3.
LSP_NC = RAW / "e5.oper.fc.sfc.accumu.128_142_lsp.ll025sc.2020010106_2020011606.nc"
CP_NC = RAW / "e5.oper.fc.sfc.accumu.128_143_cp.ll025sc.2020010106_2020011606.nc"

# Everything downstream, all committed.
SOURCE_NC = DATA / "era5_conus_mean_precip.nc"
TARGET_MESH_NC = DATA / "ne30pg3_conus.nc"
RESULTS_JSON = DATA / "remap_fidelity_results.json"


def ensure_dirs() -> None:
    """Create the output directories a script is about to write into."""
    for d in (DATA, IMAGES):
        d.mkdir(parents=True, exist_ok=True)


def require(path: Path, how: str) -> Path:
    """Fail with the command that produces ``path`` rather than a bare
    FileNotFoundError three frames deep in xarray."""
    if not path.exists():
        raise SystemExit(
            f"missing input: {path}\n"
            f"produce it with: {how}\n"
            f"(or point ERA5_CASE_STUDY_DIR at a directory that has it)"
        )
    return path
