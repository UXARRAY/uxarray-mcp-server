"""What reached the file, measured on the file rather than on the plan.

``export`` was the one operation that claimed success without checking
anything. The front door stamped ``scientific_status: {"status":
"complete", "physically_interpretable": null, "warning_codes": []}`` on
every export, and ``advanced.py`` had no ``st_size``, ``getsize``,
``stat`` or ``nbytes`` call anywhere in the three export functions -- so
"complete" meant "``to_csv`` returned", not "the data is in the file".

Measured on a 9-face grid carrying ``sst`` (units K, long_name, and a CF
``grid_mapping: crs``), ``salinity`` (units psu), a scalar ``crs``
container, and global ``title``/``Conventions``:

CSV export of the whole dataset produced 129 bytes and reported
``{"rows_written": 9}``, a number read off the in-memory DataFrame and
never off the file. All 8 attributes were gone -- 6 on the variables, 2
global -- so the ``sst`` column is bare numbers with no unit anywhere in
the artifact. The one NaN was written as ``2,,2.0,0``: an empty field,
with no sentinel and nothing in the reply mentioning it. The scalar
``crs`` container became a column of nine zeros, which reads as data.

NetCDF export of ``sst`` alone produced 8264 bytes containing exactly one
variable. Its ``grid_mapping: "crs"`` attribute survived and ``crs`` did
not, so the file references a coordinate reference system it does not
contain -- a CF reader following that attribute finds nothing.

None of that makes an export useless. A CSV of unlabelled numbers is
still the numbers. What it cannot be is silent: the caller is the one who
decides whether the loss matters, and they can only decide it if the
reply says what was lost.
"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any


def measure_written_csv(destination: Path) -> tuple[int, int | None]:
    """Bytes on disk and data rows read back out of the file.

    The row count comes from parsing the file rather than from
    ``len(frame)``, which is what the summary used to report. The two
    agree right up until the write is the thing that failed, which is the
    only moment the number was worth having. ``csv.reader`` rather than a
    newline count, because a quoted field may legally contain one.
    """
    size = destination.stat().st_size
    if size == 0:
        return 0, 0
    try:
        with destination.open("r", newline="") as handle:
            rows = sum(1 for _ in csv.reader(handle))
    except (OSError, UnicodeDecodeError):  # pragma: no cover - defensive
        return size, None
    return size, max(rows - 1, 0)


def count_dropped_attributes(dataset: Any) -> int:
    """Every attribute the CSV writer had no column for.

    Variable attributes and global attributes are summed rather than
    reported separately: the caller's question is whether the artifact
    still says what the numbers mean, and either kind going missing
    answers it the same way.
    """
    total = len(getattr(dataset, "attrs", {}) or {})
    for name in getattr(dataset, "variables", {}):
        total += len(dataset[name].attrs or {})
    return total


def dangling_grid_mappings(dataset: Any, written: set[str]) -> list[str]:
    """CF ``grid_mapping`` targets that a written variable names and the file lacks.

    A variable that keeps ``grid_mapping: "crs"`` into a file with no
    ``crs`` is worse than one that never declared a CRS: it tells a
    reader where to look and the place is empty.
    """
    dangling: list[str] = []
    for name in written:
        try:
            target = dataset[name].attrs.get("grid_mapping")
        except (KeyError, AttributeError):  # pragma: no cover - defensive
            continue
        if isinstance(target, str):
            # CF allows an extended form ("crs: lat lon"); the container
            # name is the first token either way.
            container = target.split(":")[0].strip()
            if container and container not in written and container not in dangling:
                dangling.append(container)
    return dangling


def export_fidelity(
    *,
    format: str,
    destination: Path,
    rows_expected: int | None = None,
    rows_written: int | None = None,
    n_variables_written: int | None = None,
    variables_dropped: list[str] | None = None,
    attributes_dropped: int = 0,
    missing_values: int = 0,
    missing_written_as: str | None = None,
    dangling_grid_mapping: list[str] | None = None,
) -> dict[str, Any]:
    """Assemble the block, filling in the file measurements that are free."""
    block: dict[str, Any] = {
        "format": format,
        "bytes_written": destination.stat().st_size if destination.exists() else 0,
        "variables_dropped": variables_dropped or [],
        "attributes_dropped": int(attributes_dropped),
        "missing_values": int(missing_values),
        "dangling_grid_mapping": dangling_grid_mapping or [],
    }
    if n_variables_written is not None:
        block["n_variables_written"] = int(n_variables_written)
    if rows_written is not None:
        block["rows_written"] = int(rows_written)
    if rows_expected is not None:
        block["rows_expected"] = int(rows_expected)
    if missing_values and missing_written_as is not None:
        block["missing_written_as"] = missing_written_as
    return block


def export_fidelity_warning_codes(fidelity: dict[str, Any]) -> list[str]:
    """Codes for the ways an export can be lossy or wrong.

    An empty block yields nothing. An export written by an older build
    sends no measurement, and absent measurement is not a clean bill.
    """
    if not fidelity:
        return []

    codes: list[str] = []
    if fidelity.get("bytes_written") == 0:
        codes.append("EXPORT_EMPTY_FILE")

    written = fidelity.get("rows_written")
    expected = fidelity.get("rows_expected")
    if written is not None and expected is not None and written != expected:
        codes.append("EXPORT_ROW_COUNT_MISMATCH")

    if fidelity.get("variables_dropped"):
        codes.append("EXPORT_VARIABLES_DROPPED")
    if fidelity.get("attributes_dropped"):
        # Units are attributes. A column of numbers whose unit was dropped
        # is not interpretable, however faithfully the numbers were copied.
        codes.append("EXPORT_ATTRIBUTES_DROPPED")
    if fidelity.get("missing_values"):
        codes.append("EXPORT_MISSING_VALUES_UNMARKED")
    if fidelity.get("dangling_grid_mapping"):
        codes.append("EXPORT_DANGLING_GRID_MAPPING")
    return codes
