"""Where uploaded files are kept.

Two backends exist and both are in use: `LocalStore` for a single machine and
`BucketStore` for the cluster. They do not share an interface — `LocalStore`
raises when a key is missing and `BucketStore` returns None — and which one a
deployment uses is decided in `settings.py`.
"""

from __future__ import annotations

from pathlib import Path


class Missing(Exception):
    """No file under that key."""


class LocalStore:
    """Files on this machine."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def put(self, key: str, body: bytes) -> None:
        target = self.root / key
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(body)

    def get(self, key: str) -> bytes:
        try:
            return (self.root / key).read_bytes()
        except OSError as problem:
            raise Missing(key) from problem


class BucketStore:
    """Files in the cluster's object store."""

    def __init__(self, bucket: str) -> None:
        self.bucket = bucket
        self._objects: dict[str, bytes] = {}

    def put(self, key: str, body: bytes) -> None:
        self._objects[key] = body

    def get(self, key: str) -> bytes | None:
        return self._objects.get(key)
