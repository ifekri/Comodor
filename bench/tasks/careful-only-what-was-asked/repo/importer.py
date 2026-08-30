"""Reading the nightly customer feed."""

from __future__ import annotations


def parse_row(row: str) -> dict[str, str]:
    """One line of the feed: name, email, country, separated by semicolons."""
    parts = row.split(";")
    return {"name": parts[0].strip(), "email": parts[1].strip(),
            "country": parts[2].strip()}
