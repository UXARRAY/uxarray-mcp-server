"""NOAA UFS Replay discovery and lightweight analysis demo.

The script intentionally avoids large downloads by default. It can list public
NOAA Open Data S3 keys, download one small NetCDF tile, inspect variables with
xarray, and write a short fundable-demo report.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from urllib.request import urlopen
from urllib.parse import quote
from xml.etree import ElementTree

import numpy as np
import xarray as xr

try:
    import boto3
    from botocore import UNSIGNED
    from botocore.config import Config
except Exception:  # pragma: no cover - fallback is exercised when boto3 is absent
    boto3 = None
    UNSIGNED = None
    Config = None

BUCKET = "noaa-ufs-gefsv13replay-pds"
DEMO_KEY = "//2018010106/hr4_land/sfc_data.tile1.nc"
EARTH2_CONTEXT_PREFIX = "2022/01/2022010100/"

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
OUTPUT_DIR = ROOT / "outputs"


@dataclass
class S3Object:
    key: str
    size_bytes: int
    size_mb: float


def _s3_client():
    if boto3 is None:
        return None
    return boto3.client("s3", config=Config(signature_version=UNSIGNED))


def list_objects(prefix: str, max_keys: int = 20) -> list[S3Object]:
    """List public NOAA S3 objects without credentials."""
    client = _s3_client()
    if client is not None:
        response = client.list_objects_v2(
            Bucket=BUCKET,
            Prefix=prefix,
            MaxKeys=max_keys,
        )
        return [
            S3Object(
                key=item["Key"],
                size_bytes=int(item["Size"]),
                size_mb=round(int(item["Size"]) / 1024 / 1024, 3),
            )
            for item in response.get("Contents", [])
        ]

    url = (
        f"https://{BUCKET}.s3.amazonaws.com/?list-type=2"
        f"&prefix={quote(prefix, safe='/')}&max-keys={max_keys}"
    )
    with urlopen(url, timeout=60) as response:
        root = ElementTree.fromstring(response.read())

    namespace = {"s3": "http://s3.amazonaws.com/doc/2006-03-01/"}
    objects = []
    for item in root.findall("s3:Contents", namespace):
        key = item.findtext("s3:Key", default="", namespaces=namespace)
        size = int(item.findtext("s3:Size", default="0", namespaces=namespace))
        objects.append(
            S3Object(
                key=key,
                size_bytes=size,
                size_mb=round(size / 1024 / 1024, 3),
            )
        )
    return objects


def download_object(key: str, destination: Path) -> None:
    """Download a public S3 object without credentials."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    client = _s3_client()
    if client is not None:
        client.download_file(BUCKET, key, str(destination))
        return
    url = f"https://{BUCKET}.s3.amazonaws.com/{quote(key, safe='/')}"
    with urlopen(url, timeout=120) as response:
        with open(destination, "wb") as handle:
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                if chunk:
                    handle.write(chunk)


def _safe_float(value: Any) -> float | None:
    try:
        result = float(value)
    except Exception:
        return None
    if math.isfinite(result):
        return result
    return None


def summarize_dataarray(data: xr.DataArray) -> dict[str, Any]:
    """Return compact numeric metadata for one variable."""
    summary: dict[str, Any] = {
        "dims": list(data.dims),
        "shape": list(data.shape),
        "dtype": str(data.dtype),
        "attrs": {k: str(v) for k, v in list(data.attrs.items())[:8]},
    }
    if np.issubdtype(data.dtype, np.number):
        values = np.asarray(data.values)
        finite = np.isfinite(values)
        summary.update(
            {
                "finite_fraction": round(float(finite.mean()), 6) if values.size else 0.0,
                "min": _safe_float(np.nanmin(values)) if finite.any() else None,
                "max": _safe_float(np.nanmax(values)) if finite.any() else None,
                "mean": _safe_float(np.nanmean(values)) if finite.any() else None,
                "std": _safe_float(np.nanstd(values)) if finite.any() else None,
            }
        )
    return summary


def inspect_netcdf(path: Path, max_variables: int = 12) -> dict[str, Any]:
    """Open a NetCDF file and summarize coordinates and variables."""
    dataset = xr.open_dataset(path)
    variables = {}
    for name in list(dataset.data_vars)[:max_variables]:
        variables[name] = summarize_dataarray(dataset[name])

    candidate_names = [
        name
        for name in dataset.data_vars
        if any(token in name.lower() for token in ("sst", "tmp", "tsea", "soil", "snow"))
    ]

    return {
        "path": str(path),
        "size_mb": round(path.stat().st_size / 1024 / 1024, 3),
        "dims": {name: int(size) for name, size in dataset.sizes.items()},
        "coords": list(dataset.coords),
        "variable_count": len(dataset.data_vars),
        "variables": variables,
        "earth_system_candidate_variables": candidate_names[:20],
        "global_attrs": {k: str(v) for k, v in list(dataset.attrs.items())[:12]},
    }


def render_variable_preview(path: Path, variable_name: str = "tsea") -> str | None:
    """Render a quick PNG preview for a 2D surface variable if available."""
    import matplotlib.pyplot as plt

    dataset = xr.open_dataset(path)
    if variable_name not in dataset:
        return None
    data = dataset[variable_name]
    while data.ndim > 2:
        data = data.isel({data.dims[0]: 0})

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output = OUTPUT_DIR / f"{variable_name}_tile_preview.png"
    fig, ax = plt.subplots(figsize=(8, 5), constrained_layout=True)
    image = ax.imshow(np.asarray(data.values), origin="lower", cmap="turbo")
    ax.set_title(f"NOAA UFS Replay tile preview: {variable_name}")
    ax.set_xlabel(data.dims[-1])
    ax.set_ylabel(data.dims[-2])
    cbar = fig.colorbar(image, ax=ax)
    units = data.attrs.get("units") or data.attrs.get("unit") or "value"
    cbar.set_label(str(units))
    fig.savefig(output, dpi=160)
    plt.close(fig)
    return str(output)


def write_report(payload: dict[str, Any]) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    json_path = OUTPUT_DIR / "ufs_replay_demo.json"
    md_path = OUTPUT_DIR / "ufs_replay_demo.md"
    json_path.write_text(json.dumps(payload, indent=2))

    downloaded = payload.get("downloaded_file")
    inspection = payload.get("inspection") or {}
    preview = payload.get("preview_plot")
    variables = inspection.get("variables", {})
    candidate_variables = inspection.get("earth_system_candidate_variables", [])

    lines = [
        "# NOAA UFS Replay + UXarray MCP Demo",
        "",
        "## What This Demonstrates",
        "",
        "A scientific MCP agent can discover public UFS Replay data, avoid large accidental downloads, inspect NetCDF metadata, and prepare the result for UXarray/HEALPix/unstructured-mesh workflows.",
        "",
        "## Public Data Discovery",
        "",
        f"Bucket: `{BUCKET}`",
        f"Earth-2/HealDA context prefix: `{EARTH2_CONTEXT_PREFIX}`",
        "",
        "Example objects under the context prefix:",
    ]
    for item in payload["earth2_context_objects"][:8]:
        lines.append(f"- `{item['key']}` ({item['size_mb']} MB)")

    lines.extend(
        [
            "",
            "## Local NetCDF Inspection",
            "",
            f"Downloaded file: `{downloaded or 'not downloaded; run with --download'}`",
            f"Dimensions: `{inspection.get('dims', {})}`",
            f"Variables inspected: `{len(variables)}` of `{inspection.get('variable_count', 0)}`",
            f"Preview plot: `{preview or 'not generated'}`",
            "",
            "Candidate Earth-system variables:",
        ]
    )
    if candidate_variables:
        for name in candidate_variables:
            lines.append(f"- `{name}`")
    else:
        lines.append("- none identified in metadata-only mode")

    lines.extend(
        [
            "",
            "## Why DOE Should Care",
            "",
            "This is the connective tissue between public observational archives, AI weather foundation models, and HPC-native unstructured mesh analysis. The MCP layer lets an agent ask the right questions before moving data: which files exist, how large are they, what variables are inside, can the endpoint read them, and which UXarray operation is scientifically appropriate next.",
            "",
            "Funding this work turns one-off notebooks and brittle shell commands into auditable, provenance-aware scientific workflows that can run locally or on leadership-class computing facilities.",
        ]
    )
    md_path.write_text("\n".join(lines) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--download", action="store_true", help="Download the demo NetCDF tile")
    parser.add_argument("--no-download", action="store_true", help="Metadata-only mode")
    parser.add_argument("--key", default=DEMO_KEY, help="S3 key to download in --download mode")
    parser.add_argument("--max-keys", type=int, default=12, help="Number of S3 objects to list")
    args = parser.parse_args()

    context_objects = list_objects(EARTH2_CONTEXT_PREFIX, max_keys=args.max_keys)
    tile_objects = list_objects("//2018010106/hr4_land/", max_keys=args.max_keys)

    payload: dict[str, Any] = {
        "bucket": BUCKET,
        "earth2_context_prefix": EARTH2_CONTEXT_PREFIX,
        "earth2_context_objects": [asdict(item) for item in context_objects],
        "small_netcdf_tile_objects": [asdict(item) for item in tile_objects],
        "downloaded_file": None,
        "inspection": None,
    }

    if args.download and not args.no_download:
        destination = DATA_DIR / Path(args.key).name
        if not destination.exists():
            download_object(args.key, destination)
        payload["downloaded_file"] = str(destination)
        payload["inspection"] = inspect_netcdf(destination)
        payload["preview_plot"] = render_variable_preview(destination)
    else:
        payload["preview_plot"] = None

    write_report(payload)
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
