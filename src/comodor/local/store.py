"""Where downloaded models live, and what is already here.

One directory, shared across every project. A four-gigabyte file per project
would be absurd, and the same model in two checkouts is the same bytes.

The store is authoritative about what is *usable*, not about what has been
downloaded: a file whose size does not match the catalogue is reported as
damaged rather than present, because the alternative is a model that loads and
talks nonsense.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

from .catalogue import Catalogue, Model


@dataclass(frozen=True)
class Installed:
    """A model file on this disk."""

    model: Model
    path: Path
    size: int

    @property
    def complete(self) -> bool:
        """Whether it is the whole file the catalogue describes.

        Size only. Hashing four gigabytes to answer "is it there" would make
        listing the models take a minute, and the hash was already checked when
        it arrived — this catches truncation and interrupted copies, which is
        what actually happens afterwards.
        """
        return self.size == self.model.size


class Store:
    """The model directory."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    def path_for(self, model: Model) -> Path:
        return self.root / model.filename

    def partial_for(self, model: Model) -> Path:
        return self.root / (model.filename + ".part")

    def have(self, model: Model) -> Installed | None:
        path = self.path_for(model)
        if not path.is_file():
            return None
        return Installed(model=model, path=path, size=path.stat().st_size)

    def partial_bytes(self, model: Model) -> int:
        """How much of an unfinished download is already here."""
        partial = self.partial_for(model)
        return partial.stat().st_size if partial.is_file() else 0

    def everything(self, catalogue: Catalogue) -> list[Installed]:
        return [held for model in catalogue
                if (held := self.have(model)) is not None]

    def remove(self, model: Model) -> bool:
        """Delete a model and anything half-downloaded of it."""
        gone = False
        for path in (self.path_for(model), self.partial_for(model)):
            if path.is_file():
                path.unlink()
                gone = True
        return gone

    def bytes_used(self) -> int:
        if not self.root.is_dir():
            return 0
        return sum(f.stat().st_size for f in self.root.iterdir() if f.is_file())

    def free_bytes(self) -> int | None:
        """Room left on the disk the store is on, or None if it cannot be read."""
        try:
            self.root.mkdir(parents=True, exist_ok=True)
            return shutil.disk_usage(self.root).free
        except OSError:
            return None

    def room_for(self, model: Model) -> bool | None:
        """Whether this model would fit. ``None`` when the disk cannot be read.

        A tenth is left spare on top of the file. A download that fills the
        last byte of a disk does not just fail — it takes the rest of the
        machine down with it.
        """
        free = self.free_bytes()
        if free is None:
            return None
        needed = model.size - self.partial_bytes(model)
        return free > needed * 1.1


def memory_gb() -> float | None:
    """How much memory this machine has, or None where it cannot be read.

    None is returned rather than a guess. The number is used to warn somebody
    off a model too big for their machine, and a wrong warning is worse than
    none: it either blocks a download that would have worked or waves through
    one that will not.
    """
    try:
        import os

        if hasattr(os, "sysconf"):
            names = os.sysconf_names
            if "SC_PAGE_SIZE" in names and "SC_PHYS_PAGES" in names:
                return (os.sysconf("SC_PAGE_SIZE")
                        * os.sysconf("SC_PHYS_PAGES")) / (1024 ** 3)
    except (ValueError, OSError, AttributeError):
        pass

    # Windows, and macOS where sysconf does not carry those names.
    try:
        import ctypes

        class Status(ctypes.Structure):
            _fields_ = [("dwLength", ctypes.c_ulong),
                        ("dwMemoryLoad", ctypes.c_ulong),
                        ("ullTotalPhys", ctypes.c_ulonglong),
                        ("ullAvailPhys", ctypes.c_ulonglong),
                        ("ullTotalPageFile", ctypes.c_ulonglong),
                        ("ullAvailPageFile", ctypes.c_ulonglong),
                        ("ullTotalVirtual", ctypes.c_ulonglong),
                        ("ullAvailVirtual", ctypes.c_ulonglong),
                        ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]

        status = Status()
        status.dwLength = ctypes.sizeof(Status)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            return status.ullTotalPhys / (1024 ** 3)
    except (AttributeError, OSError):
        pass

    try:
        import subprocess

        out = subprocess.run(["sysctl", "-n", "hw.memsize"],
                             capture_output=True, text=True, timeout=5)
        if out.returncode == 0 and out.stdout.strip().isdigit():
            return int(out.stdout.strip()) / (1024 ** 3)
    except (OSError, subprocess.SubprocessError):
        pass

    return None
