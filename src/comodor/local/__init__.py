"""Models that run on this machine, with no network and no account.

Four pieces, each with one job:

``catalogue``  the JSON list of what can be downloaded — a file, so a model
               added later needs an edit rather than a release
``store``      where the files are, what is already here, and whether the disk
               and the memory can take another one
``download``   fetching four gigabytes over a home line: resumable, verified,
               and watchable
``runtime``    a llama.cpp server holding the model, so the agent is never the
               thing doing the arithmetic

The join between this and the rest of Comodor is deliberately tiny. A local
server speaks the OpenAI API, so :class:`OpenAICompatProvider` drives it with
no changes at all — this package's entire job is to put a model on the disk and
something listening on a port.
"""

from __future__ import annotations

from pathlib import Path

from .catalogue import (  # noqa: F401
    CATALOGUE_URL,
    BadCatalogue,
    Catalogue,
    Model,
    bundled_path,
    load,
    parse,
)
from .download import DownloadFailed, Progress, fetch, human_bytes, human_time  # noqa: F401
from .runtime import Runner, RuntimeFailed, RuntimeMissing, Server, find_binary  # noqa: F401
from .store import Installed, Store, memory_gb  # noqa: F401

__all__ = [
    "BadCatalogue", "CATALOGUE_URL", "Catalogue", "DownloadFailed",
    "Installed", "Model", "Progress", "Runner", "RuntimeFailed",
    "RuntimeMissing", "Server", "Store", "bundled_path", "fetch",
    "find_binary", "human_bytes", "human_time", "load", "memory_gb", "parse",
    "store_for", "PROVIDER",
]

#: The provider id this appears under. Chosen to read as a place rather than a
#: vendor, because that is what it is.
PROVIDER = "local"


def store_for(user_dir: Path) -> Store:
    """The one model directory, shared by every project on this machine.

    Not per project: the same four-gigabyte file in three checkouts is twelve
    gigabytes of the same bytes.
    """
    return Store(Path(user_dir) / "models")
