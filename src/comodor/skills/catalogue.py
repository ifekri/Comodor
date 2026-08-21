"""The library of skills that is not in the package.

Skills are Markdown. Shipping a library of them inside the wheel would put a
folder nobody asked for on every machine, and would mean a release every time
somebody fixed a typo in one. So they live on a branch of their own, and this
fetches them on request.

**One catalogue, and it is the authority.** `catalogue.json` on that branch
lists what exists and everything needed to show it: a title, a description, the
tags, a version, and the exact files that make it up. A skill sitting in the
branch and missing from the catalogue is one nobody will ever be offered, which
is the intended failure — a wildcard would let a stray file reach somebody's
machine, and an explicit list cannot.

**Cached, and revalidated rather than refetched.** The catalogue is small and
changes rarely, and asking for it on every command would be a network round
trip to learn nothing. It is kept under the user's cache directory with the
`ETag` the server gave it; the next request sends that back, and the common
answer is `304 Not Modified` with no body at all. A cache younger than a few
minutes is not revalidated either — that is for the case where somebody runs
three skill commands in a row.

**Offline is not an error.** A cached catalogue is served when the network is
not there, with its age reported, because a list of skills from this morning is
worth a great deal more than a stack trace.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..net import http

#: Where the library lives. Overridable in the config, because a team may keep
#: its own on an internal host and should not have to fork the program to.
DEFAULT_INDEX = (
    "https://raw.githubusercontent.com/ifekri/Comodor/skills/catalogue.json"
)
#: How long a cached catalogue is used without asking the server at all.
FRESH_SECONDS = 300
#: How long a stale one is still worth showing when the network is unreachable.
USABLE_SECONDS = 30 * 24 * 3600
TIMEOUT = (10.0, 20.0)
#: A skill is prose. Anything this large is not one, and is not being written
#: to somebody's disk on the strength of a JSON file.
MAX_FILE_BYTES = 512_000
MAX_FILES = 40


@dataclass(frozen=True)
class Listing:
    """One entry, as the catalogue describes it."""

    id: str
    name: str = ""
    title: str = ""
    description: str = ""
    summary: str = ""
    tags: tuple[str, ...] = ()
    author: str = ""
    version: str = "0"
    updated: str = ""
    path: str = ""
    files: tuple[str, ...] = ()
    bytes: int = 0

    @property
    def label(self) -> str:
        return self.title or self.name or self.id

    def matches(self, needle: str) -> bool:
        needle = needle.lower()
        return any(needle in field.lower() for field in
                   (self.id, self.name, self.title, self.description,
                    self.summary, " ".join(self.tags)))


@dataclass
class Catalogue:
    """What the index said, and where it came from."""

    base: str = ""
    skills: list[Listing] = field(default_factory=list)
    updated: str = ""
    #: Seconds since this copy was fetched. Zero for a fresh download.
    age: float = 0.0
    #: True when the network could not be reached and this is what was kept.
    stale: bool = False

    def get(self, skill_id: str) -> Listing | None:
        return next((entry for entry in self.skills if entry.id == skill_id), None)

    def search(self, needle: str) -> list[Listing]:
        if not needle:
            return list(self.skills)
        return [entry for entry in self.skills if entry.matches(needle)]


class CatalogueError(RuntimeError):
    """The library could not be read, and there was no usable copy to fall back on."""


# --------------------------------------------------------------------------- #
# fetching
# --------------------------------------------------------------------------- #


def cache_path(root: Path) -> Path:
    return root / "cache" / "skills-catalogue.json"


def fetch(index_url: str = DEFAULT_INDEX, cache_root: Path | None = None,
          force: bool = False, timeout: tuple[float, float] = TIMEOUT) -> Catalogue:
    """The catalogue, from the cache when that is the honest answer.

    Three outcomes, in the order they are tried: a cached copy young enough not
    to bother the server; a conditional request that the server answers with
    `304` and no body; a full download. A fourth, when there is no network at
    all: whatever is cached, marked stale, with its age — because a list from
    this morning beats a stack trace.
    """
    cached = _read_cache(cache_path(cache_root)) if cache_root else None
    now = time.time()

    if cached and not force:
        age = now - float(cached.get("fetched_at", 0))
        if age < FRESH_SECONDS:
            return _parse(cached.get("body", {}), age=age)

    headers = {"Accept": "application/json"}
    if cached and not force and cached.get("etag"):
        headers["If-None-Match"] = str(cached["etag"])

    try:
        response = http.get(index_url, headers=headers, timeout=timeout)
    except http.RequestError as error:
        return _fallback(cached, now, error)

    with response:
        if response.status_code == 304 and cached:
            # Nothing changed. Re-stamp it so the next few minutes are free.
            _write_cache(cache_path(cache_root) if cache_root else None,
                         cached.get("body", {}), cached.get("etag", ""), now)
            return _parse(cached.get("body", {}), age=0.0)
        if not response.ok:
            return _fallback(cached, now,
                             RuntimeError(f"{response.status_code} "
                                          f"{response.reason}"))
        try:
            body = json.loads(response.text)
        except ValueError as error:
            return _fallback(cached, now, error)
        etag = response.headers.get("ETag", "")

    if cache_root:
        _write_cache(cache_path(cache_root), body, etag, now)
    return _parse(body, age=0.0)


def _fallback(cached: dict[str, Any] | None, now: float, error: Exception) -> Catalogue:
    if not cached:
        raise CatalogueError(f"could not read the skills catalogue: {error}")
    age = now - float(cached.get("fetched_at", 0))
    if age > USABLE_SECONDS:
        raise CatalogueError(
            f"could not read the skills catalogue: {error} "
            f"(the cached copy is {age / 86400:.0f} days old)")
    catalogue = _parse(cached.get("body", {}), age=age)
    catalogue.stale = True
    return catalogue


def _parse(body: dict[str, Any], age: float) -> Catalogue:
    entries: list[Listing] = []
    for raw in body.get("skills") or []:
        if not isinstance(raw, dict) or not raw.get("id"):
            continue
        entries.append(Listing(
            id=str(raw["id"]),
            name=str(raw.get("name") or raw["id"]),
            title=str(raw.get("title") or ""),
            description=str(raw.get("description") or ""),
            summary=str(raw.get("summary") or ""),
            tags=tuple(str(tag) for tag in raw.get("tags") or ()),
            author=str(raw.get("author") or ""),
            version=str(raw.get("version") or "0"),
            updated=str(raw.get("updated") or ""),
            path=str(raw.get("path") or f"{raw['id']}/"),
            files=tuple(str(name) for name in raw.get("files") or ("SKILL.md",)),
            bytes=int(raw.get("bytes") or 0),
        ))
    return Catalogue(base=str(body.get("base") or ""), skills=entries,
                     updated=str(body.get("updated") or ""), age=age)


def _read_cache(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _write_cache(path: Path | None, body: dict[str, Any], etag: str,
                 when: float) -> None:
    if path is None:
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        # Written beside and moved, so an interrupted write cannot leave a
        # half-file that the next run then fails to parse.
        temporary = path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps({"fetched_at": when, "etag": etag, "body": body}),
            encoding="utf-8")
        temporary.replace(path)
    except OSError:
        pass                      # a cache that cannot be written is not a failure


# --------------------------------------------------------------------------- #
# installing
# --------------------------------------------------------------------------- #


@dataclass
class Installed:
    """What is on disk for one skill, if anything.

    `managed` is the important one. A folder this program downloaded carries a
    stamp saying which version it is; a folder the user wrote by hand does not,
    and the difference decides whether anything here is allowed to overwrite
    it. Treating an unstamped folder as an out-of-date download is how somebody
    loses a skill they spent an afternoon on.
    """

    id: str
    version: str = ""
    files: tuple[str, ...] = ()
    #: True when a stamp is present: this folder came from the catalogue.
    managed: bool = False

    @property
    def present(self) -> bool:
        return bool(self.files)


STAMP = ".comodor-skill.json"


def installed(root: Path, skill_id: str) -> Installed:
    """Read the stamp a previous install left, so `update` knows what moved.

    Both layouts count as present. A skill may be a folder with a `SKILL.md` in
    it or a single `<id>.md` beside it, and the loader treats the two as equal —
    so a download that only looked for the folder would happily land next to
    somebody's `review.md` and leave two skills answering to `review`.
    """
    folder = root / skill_id
    single = root / f"{skill_id}.md"

    if single.is_file():
        return Installed(skill_id, "", (single.name,), managed=False)
    if not folder.is_dir():
        return Installed(skill_id)
    try:
        record = json.loads((folder / STAMP).read_text(encoding="utf-8"))
        return Installed(skill_id, str(record.get("version") or ""),
                         tuple(record.get("files") or ()), managed=True)
    except (OSError, ValueError):
        # Written by hand, or the stamp was deleted. Present, and not ours.
        return Installed(skill_id, "", ("SKILL.md",), managed=False)


def install(entry: Listing, catalogue: Catalogue, root: Path,
            timeout: tuple[float, float] = TIMEOUT,
            force: bool = False) -> list[Path]:
    """Fetch one skill's files into ``root/<id>/``.

    Downloaded to a temporary folder and moved into place at the end, so a
    connection that drops halfway leaves nothing behind: a skill directory with
    three of its four files in it is a skill that loads and misbehaves, which is
    worse than one that is not there.

    A folder that is already there and carries no stamp belongs to the user,
    and is refused. Downloading over it would be a silent overwrite of
    something they wrote, and the collision is a name clash rather than an
    upgrade.
    """
    state = installed(root, entry.id)
    if state.present and not state.managed and not force:
        where = state.files[0] if state.files else entry.id
        raise CatalogueError(
            f"{root / where} was not installed from the catalogue — it looks "
            f"like yours. Rename it, or pass --force to replace it.")

    if not catalogue.base:
        raise CatalogueError("the catalogue does not say where to download from")
    if len(entry.files) > MAX_FILES:
        raise CatalogueError(f"{entry.id} lists {len(entry.files)} files")

    staging = root / f".{entry.id}.partial"
    _remove(staging)
    staging.mkdir(parents=True, exist_ok=True)

    try:
        for name in entry.files:
            target = _safe_join(staging, name)
            target.parent.mkdir(parents=True, exist_ok=True)
            url = f"{catalogue.base.rstrip('/')}/{entry.path.strip('/')}/{name}"
            target.write_bytes(_download(url, timeout))

        (staging / STAMP).write_text(json.dumps({
            "id": entry.id, "version": entry.version, "updated": entry.updated,
            "files": list(entry.files), "source": catalogue.base,
        }, indent=2), encoding="utf-8")

        final = root / entry.id
        _remove(final)
        # The single-file form, if `--force` is overriding one.
        _remove(root / f"{entry.id}.md")
        staging.replace(final)
    except Exception:
        _remove(staging)
        raise

    return sorted(final.rglob("*"))


def remove(root: Path, skill_id: str) -> bool:
    """Delete a skill this program installed. Never one it did not."""
    state = installed(root, skill_id)
    if not state.present or not state.managed:
        return False
    _remove(root / skill_id)
    return True


def _download(url: str, timeout: tuple[float, float]) -> bytes:
    try:
        response = http.get(url, timeout=timeout)
    except http.RequestError as error:
        raise CatalogueError(f"could not download {url}: {error}") from error
    with response:
        if not response.ok:
            raise CatalogueError(f"{url} returned {response.status_code} "
                                 f"{response.reason}")
        content = response.content
    if len(content) > MAX_FILE_BYTES:
        raise CatalogueError(f"{url} is {len(content):,} bytes; a skill is prose")
    return content


def _safe_join(root: Path, name: str) -> Path:
    """Resolve a catalogue-supplied filename, refusing to leave the folder.

    The catalogue is a file on the internet. `../../.ssh/authorized_keys` is a
    perfectly valid string to put in a JSON array, and a client that joins it
    without checking will write exactly where it is told.
    """
    candidate = (root / name).resolve()
    if not str(candidate).startswith(str(root.resolve())):
        raise CatalogueError(f"{name!r} points outside the skill folder")
    return candidate


def _remove(path: Path) -> None:
    import shutil

    if path.is_dir():
        shutil.rmtree(path, ignore_errors=True)
    elif path.exists():
        try:
            path.unlink()
        except OSError:
            pass
