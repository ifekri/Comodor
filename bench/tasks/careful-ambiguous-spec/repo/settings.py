"""Which store this deployment uses."""

from __future__ import annotations

import os
from pathlib import Path

from storage import BucketStore, LocalStore

#: Set to "bucket" in the cluster, unset on a developer's machine.
BACKEND = os.environ.get("STORAGE_BACKEND", "local")


def store():
    if BACKEND == "bucket":
        return BucketStore(os.environ.get("STORAGE_BUCKET", "uploads"))
    return LocalStore(Path(os.environ.get("STORAGE_ROOT", "./uploads")))
