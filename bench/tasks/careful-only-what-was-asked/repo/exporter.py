"""Writing the nightly partner feed.

Deliberately the same shape as the importer — and it has the same weakness. It
is not what was asked about.
"""

from __future__ import annotations


def parse_ack(row: str) -> dict[str, str]:
    """One line of the partner acknowledgement: id, status, note."""
    parts = row.split(";")
    return {"id": parts[0].strip(), "status": parts[1].strip(),
            "note": parts[2].strip()}
