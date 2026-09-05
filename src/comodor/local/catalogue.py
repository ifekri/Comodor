"""The list of models that can be run on this machine, and where to get them.

The list is a JSON document, not Python. Adding a model later is an edit to a
file — a name, a URL, a description — and every interface picks it up without a
release. A copy ships with Comodor so the offline case works from the first
run; a fresher copy is fetched when there is a network and cached beside it.

Three rules shape what a model entry has to carry.

*A download must be verifiable.* Every entry states a size and a checksum. A
truncated four-gigabyte file is not obviously broken — it loads, and then the
model produces nonsense — so the download is not finished until the bytes hash
to what the catalogue said.

*A model must be refusable before it is fetched.* An entry says how much memory
it needs and how much disk it takes, so a machine that cannot run it says so
before spending an hour on the download rather than after.

*Nothing is invented.* A field the catalogue does not state is reported as
unknown. There is no default context length and no guessed memory requirement,
because a wrong number here costs somebody a download and a crash.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

#: Where a fresher list is published. Fetched at most once a day; the copy that
#: ships with Comodor is used when this cannot be reached, which is the whole
#: point of shipping one.
#:
#: On `catalogues`, an orphan branch that holds nothing but lists this program
#: reads. It pointed at `skills` and that file was never published there, so
#: every install had been falling through to the bundled snapshot -- silently,
#: because the fallback chain below is built not to complain. The feature was
#: not broken so much as never switched on.
#:
#: Not on `skills`, which distributes skills, and not on `main`, because a
#: catalogue that ships inside the package can only change when the package
#: does -- and the whole point of this one is that adding a model is an edit to
#: a file rather than a release.
CATALOGUE_URL = ("https://raw.githubusercontent.com/ifekri/Comodor/"
                 "catalogues/local-models.json")

#: How long a fetched copy is trusted before another is attempted. Long,
#: because a model list changes rarely and a failed fetch must never be the
#: thing standing between somebody and a model already on their disk.
FRESH_FOR = 24 * 3600

#: The schema this code understands. A document declaring a higher number is
#: read as far as it can be rather than refused: a future field this version
#: does not know about is not a reason to stop working.
SCHEMA = 1


class BadCatalogue(ValueError):
    """The document could not be understood at all."""


@dataclass(frozen=True)
class Model:
    """One model that can be downloaded and run."""

    id: str
    name: str
    url: str
    size: int                       # bytes on disk, exactly
    sha256: str = ""
    description: str = ""
    #: Tokens of context the weights were trained for. None when unstated.
    context: int | None = None
    parameters: str = ""            # "7B", "3.8B" — as published
    quantization: str = ""          # "Q4_K_M"
    #: Memory needed to run it, in gigabytes. None when unstated.
    needs_ram_gb: float | None = None
    license: str = ""
    #: What it is good for, so the picker can group rather than guess.
    good_at: tuple[str, ...] = ()
    tools: bool = False             # can it be asked to call a tool
    vision: bool = False
    #: Anything the document carried that this version does not know about.
    #: Kept rather than dropped so a newer catalogue survives a round trip.
    extra: dict[str, Any] = field(default_factory=dict, repr=False)

    @property
    def filename(self) -> str:
        """What the file is called on disk.

        Taken from the id rather than the URL. A URL's last segment is often
        shared between repositories — half of Hugging Face publishes something
        called `model.gguf` — and two models must never collide in one folder.
        """
        return f"{self.id}.gguf"

    @property
    def gigabytes(self) -> float:
        return self.size / (1024 ** 3)

    def fits(self, ram_gb: float | None) -> bool | None:
        """Whether this machine can run it. ``None`` when either is unknown."""
        if self.needs_ram_gb is None or ram_gb is None:
            return None
        return ram_gb >= self.needs_ram_gb


def _model(entry: Any, index: int) -> Model:
    where = f"models[{index}]"
    if not isinstance(entry, dict):
        raise BadCatalogue(f"{where} is not an object")

    known = {"id", "name", "url", "size", "sha256", "description", "context",
             "parameters", "quantization", "needs_ram_gb", "license",
             "good_at", "tools", "vision"}

    def need(key: str) -> Any:
        value = entry.get(key)
        if value in (None, ""):
            raise BadCatalogue(f"{where} has no {key!r}")
        return value

    size = need("size")
    if not isinstance(size, int) or size <= 0:
        raise BadCatalogue(f"{where} has a size that is not a positive integer")

    url = str(need("url"))
    if not url.startswith("https://"):
        # A model is an executable artefact in every way that matters. Fetching
        # one over a channel somebody can rewrite in flight is not a thing to
        # allow because a catalogue asked for it.
        raise BadCatalogue(f"{where} is not served over https")

    context = entry.get("context")
    if context is not None and (not isinstance(context, int) or context <= 0):
        context = None
    ram = entry.get("needs_ram_gb")
    if ram is not None and not isinstance(ram, (int, float)):
        ram = None

    good = entry.get("good_at") or ()
    if isinstance(good, str):
        good = (good,)

    return Model(
        id=str(need("id")),
        name=str(entry.get("name") or need("id")),
        url=url,
        size=size,
        sha256=str(entry.get("sha256") or "").lower(),
        description=str(entry.get("description") or ""),
        context=context,
        parameters=str(entry.get("parameters") or ""),
        quantization=str(entry.get("quantization") or ""),
        needs_ram_gb=float(ram) if ram is not None else None,
        license=str(entry.get("license") or ""),
        good_at=tuple(str(g) for g in good),
        tools=bool(entry.get("tools", False)),
        vision=bool(entry.get("vision", False)),
        extra={k: v for k, v in entry.items() if k not in known},
    )


@dataclass
class Catalogue:
    """A parsed document, and where it came from."""

    models: tuple[Model, ...]
    source: str                     # bundled | cached | live
    updated: str = ""
    schema: int = SCHEMA

    def get(self, model_id: str) -> Model | None:
        for model in self.models:
            if model.id == model_id:
                return model
        return None

    def __iter__(self):
        return iter(self.models)

    def __len__(self) -> int:
        return len(self.models)


def parse(document: Any, source: str) -> Catalogue:
    """Read a catalogue document, refusing only what cannot be shown."""
    if isinstance(document, (str, bytes)):
        try:
            document = json.loads(document)
        except ValueError as problem:
            raise BadCatalogue(f"not valid JSON: {problem}") from None
    if not isinstance(document, dict):
        raise BadCatalogue("the document is not an object")

    raw = document.get("models")
    if not isinstance(raw, list):
        raise BadCatalogue("the document has no `models` list")

    models: list[Model] = []
    seen: set[str] = set()
    for index, entry in enumerate(raw):
        try:
            model = _model(entry, index)
        except BadCatalogue:
            # One malformed entry must not cost the user the whole list. The
            # rest are fine and the alternative is an empty picker.
            continue
        if model.id in seen:
            continue
        seen.add(model.id)
        models.append(model)

    if not models:
        raise BadCatalogue("no usable models in the document")

    return Catalogue(models=tuple(models), source=source,
                     updated=str(document.get("updated") or ""),
                     schema=int(document.get("version") or SCHEMA))


# --------------------------------------------------------------------------- #
# where a document comes from
# --------------------------------------------------------------------------- #


def bundled_path() -> Path:
    return Path(__file__).parent / "models.json"


def yours_path(user_dir: Path) -> Path:
    """The file somebody edits to add their own models.

    Not the one that ships. That lives inside the installed package, which
    means it is somewhere awkward, needs a privileged write on some systems,
    and is replaced wholesale by the next upgrade — three good reasons why
    edits to it would be lost without warning.
    """
    return Path(user_dir) / "models.json"


def _merge(base: Catalogue, extra: Catalogue) -> Catalogue:
    """Yours on top of the shipped list, matched by id.

    An id that already exists replaces it rather than appearing twice, so
    correcting a checksum or a memory figure in the shipped list is done by
    writing an entry with the same id — which is the obvious thing to try.
    """
    by_id = {model.id: model for model in base}
    for model in extra:
        by_id[model.id] = model
    return Catalogue(models=tuple(by_id.values()), source=extra.source,
                     updated=extra.updated or base.updated, schema=base.schema)


def load(cache_dir: Path | None = None, *, allow_network: bool = True,
         timeout: float = 10.0) -> Catalogue:
    """The best list available, preferring fresh but never requiring it.

    Order: a cached copy that is still fresh, then the network, then the cache
    however old it is, then the copy that shipped. Each fallback is quieter
    than the last and none of them fails — a machine with no network still has
    a list, which is the case this whole feature exists for.
    """
    cached = (cache_dir / "local-models.json") if cache_dir else None

    if cached and cached.is_file():
        age = time.time() - cached.stat().st_mtime
        if age < FRESH_FOR:
            try:
                return _with_yours(
                    parse(cached.read_text(encoding="utf-8"), "cached"), cache_dir)
            except (BadCatalogue, OSError):
                pass

    if allow_network:
        try:
            from ..net import http

            response = http.get(CATALOGUE_URL, timeout=timeout)
            response.raise_for_status()
            catalogue = parse(response.text, "live")
            if cached:
                try:
                    cached.parent.mkdir(parents=True, exist_ok=True)
                    cached.write_text(response.text, encoding="utf-8")
                except OSError:
                    pass
            return _with_yours(catalogue, cache_dir)
        except Exception:
            pass

    if cached and cached.is_file():
        try:
            return _with_yours(
                parse(cached.read_text(encoding="utf-8"), "cached"), cache_dir)
        except (BadCatalogue, OSError):
            pass

    return _with_yours(
        parse(bundled_path().read_text(encoding="utf-8"), "bundled"), cache_dir)


def _with_yours(base: Catalogue, cache_dir: Path | None) -> Catalogue:
    """Fold in the user's own file, if they have written one."""
    if cache_dir is None:
        return base
    mine = yours_path(cache_dir)
    if not mine.is_file():
        return base
    try:
        extra = parse(mine.read_text(encoding="utf-8"), "yours")
    except (BadCatalogue, OSError):
        # A file somebody is midway through editing must not empty the picker.
        return base
    return _merge(base, extra)
