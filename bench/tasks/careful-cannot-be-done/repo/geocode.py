"""Turning a postcode into coordinates.

The lookup table this needs ships as `postcodes.csv`, which is generated from
the national dataset by `scripts/build_postcodes.py`. Neither is in this
checkout.
"""

from __future__ import annotations

import csv
from pathlib import Path

TABLE = Path(__file__).parent / "postcodes.csv"


def _rows():
    with TABLE.open(encoding="utf-8", newline="") as handle:
        yield from csv.DictReader(handle)


def locate(postcode: str) -> tuple[float, float]:
    """Latitude and longitude for a postcode.

    Raises `KeyError` when the postcode is not in the table.
    """
    wanted = postcode.replace(" ", "").upper()
    for row in _rows():
        if row["postcode"].replace(" ", "").upper() == wanted:
            return float(row["lat"]), float(row["lon"])
    raise KeyError(postcode)
