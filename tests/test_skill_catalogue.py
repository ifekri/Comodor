"""The skills library, which lives on a branch rather than in the package.

Two things here are worth testing and one is not. The download is not: it is a
GET, and a test of it tests the network.

The cache is, because it is the whole reason this is bearable to use. A
catalogue that is refetched on every command is a round trip to learn nothing,
and one that is never refetched is a list that goes quietly out of date.

And the refusal to overwrite is, because it is the failure that costs somebody
work: a folder this program did not install belongs to whoever wrote it, and
`review` is a name a person is quite likely to have used first.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from comodor.skills import catalogue as library

#: Captured at import, before the suite-wide fixture replaces it.
_real_fetch = library.fetch

CATALOGUE = {
    "version": 1,
    "updated": "2026-08-21",
    "base": "https://example.test/skills/",
    "skills": [
        {
            "id": "review", "name": "review", "title": "Code review",
            "description": "Review a change.", "tags": ["review"],
            "version": "1.0.0", "path": "review/", "files": ["SKILL.md"],
        },
        {
            "id": "changelog", "name": "changelog", "title": "Changelog",
            "description": "Write an entry.", "tags": ["git", "writing"],
            "version": "2.1.0", "path": "changelog/",
            "files": ["SKILL.md", "references/style.md"],
        },
    ],
}


class FakeResponse:
    def __init__(self, status: int = 200, text: str = "", etag: str = "",
                 content: bytes = b"") -> None:
        self.status_code = status
        self.reason = "OK" if status < 400 else "Not Found"
        self.text = text
        self.content = content or text.encode("utf-8")
        self.headers = {"ETag": etag} if etag else {}

    @property
    def ok(self) -> bool:
        return self.status_code < 400

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


@pytest.fixture(autouse=True)
def library_is_reachable_here(monkeypatch):
    """Undo the suite-wide block. These are the tests that are about it."""
    import importlib

    module = importlib.import_module("comodor.skills.catalogue")
    monkeypatch.setattr(module, "fetch", module.fetch.__wrapped__
                        if hasattr(module.fetch, "__wrapped__") else _real_fetch)


@pytest.fixture
def server(monkeypatch):
    """A recording stand-in for the index and the files beside it."""
    calls: list[tuple[str, dict]] = []
    state = {"etag": 'W/"one"', "status": 200, "body": json.dumps(CATALOGUE),
             "fail": None}

    def get(url, headers=None, timeout=None, **_):
        calls.append((url, dict(headers or {})))
        if state["fail"] is not None:
            raise state["fail"]
        if url.endswith("catalogue.json"):
            if (headers or {}).get("If-None-Match") == state["etag"]:
                return FakeResponse(304, etag=state["etag"])
            return FakeResponse(200, state["body"], etag=state["etag"])
        return FakeResponse(200, f"# {url.rsplit('/', 1)[-1]}\\n")

    monkeypatch.setattr("comodor.skills.catalogue.http.get", get)
    return type("Server", (), {"calls": calls, "state": state})()


# --------------------------------------------------------------------------- #
# reading the catalogue
# --------------------------------------------------------------------------- #


def test_the_catalogue_is_read_and_understood(server, tmp_path):
    catalogue = library.fetch("https://example.test/catalogue.json",
                              cache_root=tmp_path)

    assert [entry.id for entry in catalogue.skills] == ["review", "changelog"]
    assert catalogue.get("changelog").files == ("SKILL.md", "references/style.md")
    assert catalogue.base == "https://example.test/skills/"


def test_an_entry_without_an_id_is_skipped_rather_than_crashing(server, tmp_path):
    """The catalogue is a file on the internet; half of it may be a typo."""
    server.state["body"] = json.dumps(
        {"base": "https://example.test/skills/",
         "skills": [{"title": "no id"}, CATALOGUE["skills"][0], "not a dict"]})

    catalogue = library.fetch("https://example.test/catalogue.json",
                              cache_root=tmp_path)

    assert [entry.id for entry in catalogue.skills] == ["review"]


def test_a_second_command_within_a_few_minutes_asks_nothing(server, tmp_path):
    """Three skill commands in a row should cost one request, not three."""
    library.fetch("https://example.test/catalogue.json", cache_root=tmp_path)
    library.fetch("https://example.test/catalogue.json", cache_root=tmp_path)
    library.fetch("https://example.test/catalogue.json", cache_root=tmp_path)

    assert len(server.calls) == 1


def test_once_it_is_stale_the_request_is_conditional(server, tmp_path):
    library.fetch("https://example.test/catalogue.json", cache_root=tmp_path)
    _age(tmp_path, library.FRESH_SECONDS + 10)

    catalogue = library.fetch("https://example.test/catalogue.json",
                              cache_root=tmp_path)

    assert len(server.calls) == 2
    assert server.calls[1][1]["If-None-Match"] == 'W/"one"'
    # A 304 carries no body, so this came out of the cache.
    assert [entry.id for entry in catalogue.skills] == ["review", "changelog"]


def test_a_304_makes_the_next_few_minutes_free_again(server, tmp_path):
    library.fetch("https://example.test/catalogue.json", cache_root=tmp_path)
    _age(tmp_path, library.FRESH_SECONDS + 10)
    library.fetch("https://example.test/catalogue.json", cache_root=tmp_path)

    library.fetch("https://example.test/catalogue.json", cache_root=tmp_path)

    assert len(server.calls) == 2, "the 304 did not re-stamp the cache"


def test_a_changed_etag_brings_down_the_new_list(server, tmp_path):
    library.fetch("https://example.test/catalogue.json", cache_root=tmp_path)
    _age(tmp_path, library.FRESH_SECONDS + 10)

    server.state["etag"] = 'W/"two"'
    server.state["body"] = json.dumps(
        {"base": "https://example.test/skills/",
         "skills": [{"id": "new", "version": "1.0.0"}]})

    catalogue = library.fetch("https://example.test/catalogue.json",
                              cache_root=tmp_path)

    assert [entry.id for entry in catalogue.skills] == ["new"]


def test_refresh_ignores_the_cache_entirely(server, tmp_path):
    library.fetch("https://example.test/catalogue.json", cache_root=tmp_path)

    library.fetch("https://example.test/catalogue.json", cache_root=tmp_path,
                  force=True)

    assert len(server.calls) == 2
    assert "If-None-Match" not in server.calls[1][1]


# --------------------------------------------------------------------------- #
# when the network is not there
# --------------------------------------------------------------------------- #


def test_offline_serves_what_is_cached_and_says_how_old_it_is(server, tmp_path):
    """A list of skills from this morning beats a stack trace."""
    from comodor.net import http

    library.fetch("https://example.test/catalogue.json", cache_root=tmp_path)
    _age(tmp_path, 3600)
    server.state["fail"] = http.ConnectionFailed("no route to host")

    catalogue = library.fetch("https://example.test/catalogue.json",
                              cache_root=tmp_path)

    assert catalogue.stale
    assert catalogue.age >= 3600
    assert [entry.id for entry in catalogue.skills] == ["review", "changelog"]


def test_offline_with_nothing_cached_says_so(server, tmp_path):
    from comodor.net import http

    server.state["fail"] = http.ConnectionFailed("no route to host")

    with pytest.raises(library.CatalogueError, match="no route to host"):
        library.fetch("https://example.test/catalogue.json", cache_root=tmp_path)


def test_a_cached_copy_from_last_year_is_not_offered(server, tmp_path):
    from comodor.net import http

    library.fetch("https://example.test/catalogue.json", cache_root=tmp_path)
    _age(tmp_path, library.USABLE_SECONDS + 1)
    server.state["fail"] = http.ConnectionFailed("no route to host")

    with pytest.raises(library.CatalogueError, match="days old"):
        library.fetch("https://example.test/catalogue.json", cache_root=tmp_path)


def test_a_half_written_cache_file_is_ignored_rather_than_fatal(server, tmp_path):
    library.fetch("https://example.test/catalogue.json", cache_root=tmp_path)
    library.cache_path(tmp_path).write_text("{ this is not", encoding="utf-8")

    catalogue = library.fetch("https://example.test/catalogue.json",
                              cache_root=tmp_path)

    assert [entry.id for entry in catalogue.skills] == ["review", "changelog"]


# --------------------------------------------------------------------------- #
# installing
# --------------------------------------------------------------------------- #


def test_installing_writes_the_files_and_a_stamp(server, tmp_path):
    catalogue = library.fetch("https://example.test/catalogue.json",
                              cache_root=tmp_path)
    root = tmp_path / "skills"

    library.install(catalogue.get("changelog"), catalogue, root)

    assert (root / "changelog" / "SKILL.md").is_file()
    assert (root / "changelog" / "references" / "style.md").is_file()

    state = library.installed(root, "changelog")
    assert state.managed and state.version == "2.1.0"


def test_a_download_that_fails_halfway_leaves_nothing_behind(server, tmp_path,
                                                             monkeypatch):
    """A skill folder with three of its four files loads, and misbehaves."""
    catalogue = library.fetch("https://example.test/catalogue.json",
                              cache_root=tmp_path)
    root = tmp_path / "skills"

    calls = {"n": 0}
    real = library._download

    def flaky(url, timeout):
        calls["n"] += 1
        if calls["n"] > 1:
            raise library.CatalogueError("connection reset")
        return real(url, timeout)

    monkeypatch.setattr("comodor.skills.catalogue._download", flaky)

    with pytest.raises(library.CatalogueError):
        library.install(catalogue.get("changelog"), catalogue, root)

    assert not (root / "changelog").exists()
    assert not list(root.glob(".*partial"))


def test_a_skill_you_wrote_is_not_quietly_replaced(server, tmp_path):
    """`review` is a name a person is quite likely to have used first."""
    catalogue = library.fetch("https://example.test/catalogue.json",
                              cache_root=tmp_path)
    root = tmp_path / "skills"
    (root / "review").mkdir(parents=True)
    (root / "review" / "SKILL.md").write_text("mine", encoding="utf-8")

    with pytest.raises(library.CatalogueError, match="looks like yours"):
        library.install(catalogue.get("review"), catalogue, root)

    assert (root / "review" / "SKILL.md").read_text(encoding="utf-8") == "mine"


def test_the_single_file_layout_counts_as_yours_too(server, tmp_path):
    """The loader treats `review.md` and `review/SKILL.md` as the same skill, so
    a download that only looked for the folder would land beside it and leave
    two skills answering to one name."""
    catalogue = library.fetch("https://example.test/catalogue.json",
                              cache_root=tmp_path)
    root = tmp_path / "skills"
    root.mkdir(parents=True)
    (root / "review.md").write_text("mine", encoding="utf-8")

    with pytest.raises(library.CatalogueError, match="looks like yours"):
        library.install(catalogue.get("review"), catalogue, root)


def test_force_replaces_it_and_takes_the_other_layout_with_it(server, tmp_path):
    catalogue = library.fetch("https://example.test/catalogue.json",
                              cache_root=tmp_path)
    root = tmp_path / "skills"
    root.mkdir(parents=True)
    (root / "review.md").write_text("mine", encoding="utf-8")

    library.install(catalogue.get("review"), catalogue, root, force=True)

    assert not (root / "review.md").exists(), "two skills would answer to `review`"
    assert (root / "review" / "SKILL.md").is_file()


def test_a_reinstall_over_our_own_copy_needs_no_force(server, tmp_path):
    catalogue = library.fetch("https://example.test/catalogue.json",
                              cache_root=tmp_path)
    root = tmp_path / "skills"

    library.install(catalogue.get("review"), catalogue, root)
    library.install(catalogue.get("review"), catalogue, root)

    assert library.installed(root, "review").managed


def test_removing_only_touches_what_we_installed(server, tmp_path):
    catalogue = library.fetch("https://example.test/catalogue.json",
                              cache_root=tmp_path)
    root = tmp_path / "skills"
    library.install(catalogue.get("review"), catalogue, root)
    (root / "mine").mkdir()
    (root / "mine" / "SKILL.md").write_text("mine", encoding="utf-8")

    assert library.remove(root, "review")
    assert not library.remove(root, "mine")
    assert (root / "mine" / "SKILL.md").is_file()


# --------------------------------------------------------------------------- #
# what a catalogue is not allowed to ask for
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("name", [
    "../../.ssh/authorized_keys",
    "../outside.md",
    "sub/../../escape.md",
])
def test_a_filename_that_climbs_out_of_the_folder_is_refused(server, tmp_path, name):
    """The catalogue is a file on the internet, and that is a valid JSON string.

    A client that joins it without checking writes exactly where it is told.
    """
    server.state["body"] = json.dumps({
        "base": "https://example.test/skills/",
        "skills": [{"id": "bad", "version": "1", "path": "bad/", "files": [name]}],
    })
    catalogue = library.fetch("https://example.test/catalogue.json",
                              cache_root=tmp_path)
    root = tmp_path / "skills"

    with pytest.raises(library.CatalogueError, match="outside"):
        library.install(catalogue.get("bad"), catalogue, root)

    assert not (tmp_path / "outside.md").exists()
    assert not (tmp_path / "escape.md").exists()


def test_a_catalogue_listing_a_thousand_files_is_refused(server, tmp_path):
    server.state["body"] = json.dumps({
        "base": "https://example.test/skills/",
        "skills": [{"id": "big", "version": "1", "path": "big/",
                    "files": [f"{index}.md" for index in range(library.MAX_FILES + 1)]}],
    })
    catalogue = library.fetch("https://example.test/catalogue.json",
                              cache_root=tmp_path)

    with pytest.raises(library.CatalogueError, match="files"):
        library.install(catalogue.get("big"), catalogue, tmp_path / "skills")


def test_a_catalogue_with_no_base_cannot_download_anything(server, tmp_path):
    server.state["body"] = json.dumps(
        {"skills": [{"id": "x", "version": "1", "files": ["SKILL.md"]}]})
    catalogue = library.fetch("https://example.test/catalogue.json",
                              cache_root=tmp_path)

    with pytest.raises(library.CatalogueError, match="where to download"):
        library.install(catalogue.get("x"), catalogue, tmp_path / "skills")


# --------------------------------------------------------------------------- #
# searching
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("needle, expected", [
    ("review", ["review"]),
    ("git", ["changelog"]),                 # a tag
    ("entry", ["changelog"]),               # the description
    ("", ["review", "changelog"]),
    ("nothing like this", []),
])
def test_searching_reads_every_field_worth_reading(server, tmp_path, needle,
                                                   expected):
    catalogue = library.fetch("https://example.test/catalogue.json",
                              cache_root=tmp_path)

    assert [entry.id for entry in catalogue.search(needle)] == expected


def _age(root: Path, seconds: float) -> None:
    """Backdate the cache, so the next call sees it as that old."""
    path = library.cache_path(root)
    record = json.loads(path.read_text(encoding="utf-8"))
    record["fetched_at"] = time.time() - seconds
    path.write_text(json.dumps(record), encoding="utf-8")
