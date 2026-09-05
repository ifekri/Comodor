"""Models that run on this machine: the catalogue, the download, the runtime."""

from __future__ import annotations

import hashlib
import json
import threading
import time
from pathlib import Path

import pytest

from comodor.local import catalogue as cat
from comodor.local import download as dl
from comodor.local import store as st

# --------------------------------------------------------------------------- #
# the catalogue, which is the part people will edit
# --------------------------------------------------------------------------- #


def an_entry(**over):
    base = {
        "id": "test-model",
        "name": "Test Model",
        "url": "https://example.invalid/model.gguf",
        "size": 1024,
        "sha256": "ab" * 32,
        "description": "For tests.",
        "context": 4096,
        "needs_ram_gb": 4,
    }
    base.update(over)
    return base


def a_document(*entries, **top):
    document = {"version": 1, "models": list(entries) or [an_entry()]}
    document.update(top)
    return document


def test_the_bundled_list_is_valid():
    """It is the fallback for a machine with no network, so it must parse."""
    parsed = cat.parse(cat.bundled_path().read_text(encoding="utf-8"), "bundled")
    assert len(parsed) >= 1
    for model in parsed:
        assert model.url.startswith("https://")
        assert model.size > 0
        assert len(model.sha256) == 64, f"{model.id} has no usable checksum"
        assert model.name and model.description


def test_every_bundled_id_is_a_safe_filename():
    """The id becomes a path. A slash in one writes outside the store."""
    for model in cat.parse(cat.bundled_path().read_text(encoding="utf-8"), "b"):
        assert "/" not in model.id and "\\" not in model.id
        assert ".." not in model.id
        assert model.filename == f"{model.id}.gguf"


def test_a_model_over_plain_http_is_refused():
    """A model file is an executable artefact in every way that matters."""
    parsed = cat.parse(a_document(an_entry(url="http://example.invalid/m.gguf"),
                                  an_entry(id="fine")), "test")
    assert [m.id for m in parsed] == ["fine"]


def test_one_bad_entry_does_not_cost_the_whole_list():
    parsed = cat.parse(a_document(
        {"id": "broken"},                       # no url, no size
        an_entry(id="good"),
    ), "test")
    assert [m.id for m in parsed] == ["good"]


def test_a_document_with_nothing_usable_is_refused():
    with pytest.raises(cat.BadCatalogue):
        cat.parse(a_document({"id": "broken"}), "test")


def test_a_document_that_is_not_json_is_refused():
    with pytest.raises(cat.BadCatalogue, match="JSON"):
        cat.parse("{not json", "test")


def test_duplicate_ids_keep_the_first():
    parsed = cat.parse(a_document(an_entry(name="First"),
                                  an_entry(name="Second")), "test")
    assert len(parsed) == 1 and parsed.models[0].name == "First"


def test_a_field_this_version_does_not_know_is_kept():
    """So a newer catalogue survives being read by an older Comodor."""
    [model] = cat.parse(a_document(an_entry(speaks_klingon=True)), "test")
    assert model.extra["speaks_klingon"] is True


def test_nothing_unstated_is_invented():
    [model] = cat.parse(a_document({
        "id": "bare", "name": "Bare", "url": "https://example.invalid/b.gguf",
        "size": 10,
    }), "test")
    assert model.context is None
    assert model.needs_ram_gb is None
    assert model.sha256 == ""
    assert model.fits(8) is None, "an unknown requirement is unknown, not met"


def test_a_size_that_is_not_a_positive_integer_is_refused():
    for bad in ("4683074336", 0, -1, 1.5):
        assert len(cat.parse(a_document(an_entry(size=bad), an_entry(id="ok")),
                             "t")) == 1


def test_fits_is_a_comparison_not_a_guess():
    [model] = cat.parse(a_document(an_entry(needs_ram_gb=8)), "test")
    assert model.fits(16) is True
    assert model.fits(4) is False
    assert model.fits(None) is None


# --------------------------------------------------------------------------- #
# where the list comes from
# --------------------------------------------------------------------------- #


def test_the_bundled_copy_is_used_when_there_is_no_network(tmp_path):
    parsed = cat.load(tmp_path, allow_network=False)
    assert parsed.source == "bundled"
    assert len(parsed) >= 1


def test_a_fresh_cached_copy_is_preferred(tmp_path):
    (tmp_path / "local-models.json").write_text(
        json.dumps(a_document(an_entry(id="from-cache"))), encoding="utf-8")
    parsed = cat.load(tmp_path, allow_network=False)
    assert parsed.source == "cached"
    assert parsed.get("from-cache") is not None


def test_a_corrupt_cache_falls_back_rather_than_failing(tmp_path):
    (tmp_path / "local-models.json").write_text("{ truncated", encoding="utf-8")
    parsed = cat.load(tmp_path, allow_network=False)
    assert parsed.source == "bundled"


# --------------------------------------------------------------------------- #
# the network path, which had never been tested and had never worked
# --------------------------------------------------------------------------- #
#
# `CATALOGUE_URL` pointed at a file on the `skills` branch that was never
# published there. Every install fell through to the bundled snapshot, and
# nothing said so, because the fallback chain is deliberately quiet: somebody
# with no network still gets a list, which is the case the whole feature exists
# for.
#
# The quietness is right and it is also why this went unnoticed for as long as
# it did. The tests below are the part that was missing: they exercise the live
# path and every way it can fail, and one of them pins the URL itself.


class _Answer:
    """What `http.get` returns, in the parts the loader touches."""

    def __init__(self, text: str, status: int = 200) -> None:
        self.text = text
        self.status_code = status

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise OSError(f"HTTP {self.status_code}")


def _serving(monkeypatch, answer, *, url_seen=None):
    """Point the loader's HTTP client at `answer` instead of the internet."""
    def get(url, **kwargs):
        if url_seen is not None:
            url_seen.append(url)
        if isinstance(answer, Exception):
            raise answer
        return answer

    from comodor.net import http

    monkeypatch.setattr(http, "get", get)


def _aged(path: Path, seconds: float) -> None:
    """Backdate a file, so a cache can be made stale without waiting a day."""
    import os

    when = time.time() - seconds
    os.utime(path, (when, when))


def test_the_catalogue_url_is_the_published_one():
    """The bug in one assertion.

    This is not a style check. The URL named a branch that has no such file,
    so the live catalogue never loaded once, anywhere, for anybody — and the
    fallback made that look like normal operation. If it ever points somewhere
    unpublished again, this is the test that says so.
    """
    assert cat.CATALOGUE_URL == (
        "https://raw.githubusercontent.com/ifekri/Comodor/"
        "catalogues/local-models.json")

    assert "skills/local-models.json" not in cat.CATALOGUE_URL, \
        "the local model catalogue is not on the skills branch"


def test_the_bundled_snapshot_parses_with_the_real_parser():
    """The floor everything else falls back to. If this file is ever malformed
    there is nothing underneath it."""
    parsed = cat.parse(cat.bundled_path().read_text(encoding="utf-8"), "bundled")

    assert len(parsed) >= 1
    ids = [model.id for model in parsed.models]
    assert len(ids) == len(set(ids)), "a duplicate id would silently vanish"
    assert all(model.url.startswith("https://") for model in parsed.models)
    assert all(isinstance(model.size, int) and model.size > 0
               for model in parsed.models)


def test_a_published_catalogue_is_used_when_it_can_be_reached(tmp_path,
                                                              monkeypatch):
    """The path that had never run. Everything below is a way for it to fail;
    this is the one where it works."""
    seen: list[str] = []
    _serving(monkeypatch, _Answer(json.dumps(a_document(an_entry(id="live-one")))),
             url_seen=seen)

    parsed = cat.load(tmp_path)

    assert parsed.source == "live"
    assert parsed.get("live-one") is not None
    assert seen == [cat.CATALOGUE_URL], "it must ask for the published location"


def test_a_fetched_catalogue_is_cached_for_next_time(tmp_path, monkeypatch):
    _serving(monkeypatch, _Answer(json.dumps(a_document(an_entry(id="live-one")))))

    cat.load(tmp_path)

    assert (tmp_path / "local-models.json").is_file(), \
        "a fetch that is not cached is a fetch repeated on every start"


def test_a_network_that_is_not_there_does_not_crash(tmp_path, monkeypatch):
    """A refused connection, a DNS failure, a captive portal. None of them is
    an error the caller should see: there is a list either way."""
    _serving(monkeypatch, OSError("no route to host"))

    parsed = cat.load(tmp_path)

    assert parsed.source == "bundled"
    assert len(parsed) >= 1


def test_a_404_falls_back_rather_than_failing(tmp_path, monkeypatch):
    """Exactly the state this fix repaired: the URL resolves, the file is not
    there. It must be survivable — it was survived for weeks — and it must not
    be indistinguishable from working, which is what the health check is for."""
    _serving(monkeypatch, _Answer("404: Not Found", status=404))

    parsed = cat.load(tmp_path)

    assert parsed.source == "bundled"
    assert len(parsed) >= 1


def test_malformed_json_from_the_network_falls_back(tmp_path, monkeypatch):
    """A half-written file, a proxy login page, a truncated response."""
    _serving(monkeypatch, _Answer("{ not json at all"))

    parsed = cat.load(tmp_path)

    assert parsed.source == "bundled"
    assert not (tmp_path / "local-models.json").is_file(), \
        "an unparseable answer must not be cached as a catalogue"


def test_valid_json_that_is_not_a_catalogue_falls_back(tmp_path, monkeypatch):
    """Parses, means nothing. A repository page, an error object, an empty
    list — each is valid JSON and none of them is a list of models."""
    for body in ('{"models": []}', '{"message": "Not Found"}', '[]', '"hello"'):
        _serving(monkeypatch, _Answer(body))

        parsed = cat.load(tmp_path)

        assert parsed.source == "bundled", body
        assert len(parsed) >= 1, body


def test_one_bad_published_entry_does_not_cost_the_whole_list(tmp_path,
                                                              monkeypatch):
    """A malformed entry is skipped on its own, and that holds for a document
    off the network as much as for one parsed directly. The alternative is that
    one typo in a published file empties the picker for everybody."""
    document = a_document(an_entry(id="good-one"))
    document["models"].append({"id": "broken", "url": "http://insecure",
                               "size": 1})
    _serving(monkeypatch, _Answer(json.dumps(document)))

    parsed = cat.load(tmp_path)

    assert parsed.source == "live"
    assert parsed.get("good-one") is not None
    assert parsed.get("broken") is None, "http:// is refused, and rightly"


def test_a_fresh_cache_is_used_before_the_network(tmp_path, monkeypatch):
    """The daily budget. A cached copy under a day old is the answer, and the
    network is not asked at all."""
    (tmp_path / "local-models.json").write_text(
        json.dumps(a_document(an_entry(id="from-cache"))), encoding="utf-8")

    seen: list[str] = []
    _serving(monkeypatch, _Answer(json.dumps(a_document(an_entry(id="live-one")))),
             url_seen=seen)

    parsed = cat.load(tmp_path)

    assert parsed.source == "cached"
    assert parsed.get("from-cache") is not None
    assert seen == [], "a fresh cache must not cost a request"


def test_a_stale_cache_is_used_when_the_network_fails(tmp_path, monkeypatch):
    """Order matters here, and this is the rung that is easy to lose: a cache
    from last week is a better answer than the snapshot from the last release,
    and it is only reached when the network has already failed."""
    cached = tmp_path / "local-models.json"
    cached.write_text(json.dumps(a_document(an_entry(id="from-cache"))),
                      encoding="utf-8")
    _aged(cached, cat.FRESH_FOR + 60)

    _serving(monkeypatch, OSError("still no network"))

    parsed = cat.load(tmp_path)

    assert parsed.source == "cached"
    assert parsed.get("from-cache") is not None


def test_a_stale_cache_loses_to_a_reachable_network(tmp_path, monkeypatch):
    """The other side of the same rung. Stale means stale: if the network
    answers, what it says wins."""
    cached = tmp_path / "local-models.json"
    cached.write_text(json.dumps(a_document(an_entry(id="from-cache"))),
                      encoding="utf-8")
    _aged(cached, cat.FRESH_FOR + 60)

    _serving(monkeypatch, _Answer(json.dumps(a_document(an_entry(id="live-one")))))

    parsed = cat.load(tmp_path)

    assert parsed.source == "live"
    assert parsed.get("live-one") is not None


def test_the_whole_order_holds(tmp_path, monkeypatch):
    """All four rungs, in one place, in order.

    Written as one test because the property is the *sequence*, and four
    separate assertions each passing does not say the order between them is
    the one documented.
    """
    cached = tmp_path / "local-models.json"

    # 4. nothing anywhere
    _serving(monkeypatch, OSError("offline"))
    assert cat.load(tmp_path).source == "bundled"

    # 3. a stale cache beats the bundled snapshot
    cached.write_text(json.dumps(a_document(an_entry(id="c"))), encoding="utf-8")
    _aged(cached, cat.FRESH_FOR + 60)
    assert cat.load(tmp_path).source == "cached"

    # 2. a reachable network beats a stale cache
    _serving(monkeypatch, _Answer(json.dumps(a_document(an_entry(id="l")))))
    assert cat.load(tmp_path).source == "live"

    # 1. a fresh cache beats the network — the fetch above wrote one
    seen: list[str] = []
    _serving(monkeypatch, _Answer(json.dumps(a_document(an_entry(id="l")))),
             url_seen=seen)
    assert cat.load(tmp_path).source == "cached"
    assert seen == []


# --------------------------------------------------------------------------- #
# the download
# --------------------------------------------------------------------------- #


class _Body:
    def __init__(self, data: bytes, status: int = 200, headers=None):
        self.data = data
        self.status_code = status
        self.headers = headers or {}

    def iter_content(self, size):
        for start in range(0, len(self.data), size):
            yield self.data[start:start + size]

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


@pytest.fixture
def served(monkeypatch):
    """Stands in for the network, recording what was asked for."""
    state = {"asked": [], "body": b"", "status": 200, "headers": {}}

    def get(url, headers=None, **kwargs):
        state["asked"].append(dict(headers or {}))
        wanted = (headers or {}).get("Range")
        if wanted and state["status"] == 206:
            start = int(wanted.split("=")[1].split("-")[0])
            return _Body(state["body"][start:], 206,
                         {"Content-Range": f"bytes {start}-/{len(state['body'])}"})
        return _Body(state["body"], state["status"], state["headers"])

    monkeypatch.setattr(dl.http, "get", get)
    return state


def test_a_download_is_verified_against_its_checksum(tmp_path, served):
    served["body"] = b"weights" * 1000
    good = hashlib.sha256(served["body"]).hexdigest()

    out = dl.fetch("https://x.invalid/m.gguf", tmp_path / "m.gguf",
                   expect_size=len(served["body"]), expect_sha256=good)
    assert out.read_bytes() == served["body"]


def test_a_file_that_fails_its_checksum_is_deleted(tmp_path, served):
    served["body"] = b"not what was promised"
    with pytest.raises(dl.DownloadFailed, match="checksum"):
        dl.fetch("https://x.invalid/m.gguf", tmp_path / "m.gguf",
                 expect_size=len(served["body"]), expect_sha256="cd" * 32)
    assert not (tmp_path / "m.gguf").exists()
    assert not (tmp_path / "m.gguf.part").exists(), "a half-file was left behind"


def test_a_short_file_is_refused_even_with_no_checksum(tmp_path, served):
    served["body"] = b"only some of it"
    with pytest.raises(dl.DownloadFailed, match="expected"):
        dl.fetch("https://x.invalid/m.gguf", tmp_path / "m.gguf",
                 expect_size=99999)
    assert not (tmp_path / "m.gguf").exists()


def test_a_download_resumes_from_what_is_already_there(tmp_path, served):
    whole = bytes(range(256)) * 40
    served["body"] = whole
    served["status"] = 206
    (tmp_path / "m.gguf.part").write_bytes(whole[:1000])

    out = dl.fetch("https://x.invalid/m.gguf", tmp_path / "m.gguf",
                   expect_size=len(whole),
                   expect_sha256=hashlib.sha256(whole).hexdigest())
    assert out.read_bytes() == whole
    assert served["asked"][0].get("Range") == "bytes=1000-"


def test_a_server_that_ignores_the_range_starts_over(tmp_path, served):
    """Appending a whole body to a partial makes a file of the right length
    and the wrong contents, which the checksum would then reject — but the
    download should not get that far."""
    whole = b"abcdefgh" * 500
    served["body"] = whole
    served["status"] = 200
    (tmp_path / "m.gguf.part").write_bytes(whole[:100])

    out = dl.fetch("https://x.invalid/m.gguf", tmp_path / "m.gguf",
                   expect_size=len(whole),
                   expect_sha256=hashlib.sha256(whole).hexdigest())
    assert out.read_bytes() == whole


def test_an_existing_correct_file_is_not_downloaded_again(tmp_path, served):
    whole = b"already here" * 100
    (tmp_path / "m.gguf").write_bytes(whole)
    served["body"] = b"should not be fetched"

    dl.fetch("https://x.invalid/m.gguf", tmp_path / "m.gguf",
             expect_size=len(whole),
             expect_sha256=hashlib.sha256(whole).hexdigest())
    assert not served["asked"], "it went to the network for a file it had"


def test_stopping_keeps_what_arrived(tmp_path, served):
    served["body"] = b"x" * (4 * dl.CHUNK)
    stop = {"now": False}

    def should_stop():
        stop["now"] = True          # stop after the first chunk
        return stop["now"] and (tmp_path / "m.gguf.part").exists()

    with pytest.raises(dl.DownloadFailed, match="stopped"):
        dl.fetch("https://x.invalid/m.gguf", tmp_path / "m.gguf",
                 expect_size=len(served["body"]), should_stop=should_stop)
    assert not (tmp_path / "m.gguf").exists()


def test_progress_is_reported_while_it_runs(tmp_path, served, monkeypatch):
    monkeypatch.setattr(dl, "EVERY", 0.0)
    served["body"] = b"y" * (3 * dl.CHUNK)
    seen: list[dl.Progress] = []

    dl.fetch("https://x.invalid/m.gguf", tmp_path / "m.gguf",
             expect_size=len(served["body"]), watch=seen.append)

    assert len(seen) >= 3
    assert seen[-1].done == len(served["body"])
    assert seen[-1].percent == pytest.approx(100.0)
    assert all(a.done <= b.done for a, b in zip(seen, seen[1:], strict=False)), "went backwards"


# --------------------------------------------------------------------------- #
# the shape the interfaces read
# --------------------------------------------------------------------------- #


def test_the_progress_dict_does_not_call_a_byte_count_done():
    """A field called `done` holding a number is truthy from the first chunk,
    and a reader testing it for completion treats 1 MB as the whole file."""
    shape = dl.Progress(done=5, total=100, started=time.monotonic()).as_dict()
    assert "done" not in shape
    assert shape["done_bytes"] == 5
    assert shape["percent"] == 5.0


def test_the_rate_ignores_bytes_from_a_previous_run():
    at = dl.Progress(done=1000, total=2000,
                     started=time.monotonic() - 1.0, resumed_from=900)
    # 100 bytes in a second, not 1000.
    assert at.bytes_per_second == pytest.approx(100, rel=0.2)


def test_no_estimate_is_offered_before_anything_has_moved():
    at = dl.Progress(done=0, total=1000, started=time.monotonic())
    assert at.seconds_left is None


@pytest.mark.parametrize("count,text", [
    (0, "0 B"), (512, "512 B"), (1536, "1.5 KB"), (1024 ** 3, "1.0 GB"),
])
def test_bytes_read_as_people_write_them(count, text):
    assert dl.human_bytes(count) == text


@pytest.mark.parametrize("seconds,text", [
    (None, "—"), (45, "45s"), (125, "2m 05s"), (3725, "1h 02m"),
])
def test_times_read_as_people_write_them(seconds, text):
    assert dl.human_time(seconds) == text


# --------------------------------------------------------------------------- #
# the store
# --------------------------------------------------------------------------- #


@pytest.fixture
def a_store(tmp_path):
    return st.Store(tmp_path / "models")


def test_a_truncated_file_is_reported_as_incomplete(a_store):
    [model] = cat.parse(a_document(an_entry(size=1000)), "test")
    a_store.root.mkdir(parents=True)
    a_store.path_for(model).write_bytes(b"x" * 400)

    held = a_store.have(model)
    assert held is not None
    assert held.complete is False, "a short file must not read as installed"


def test_removing_takes_the_partial_too(a_store):
    [model] = cat.parse(a_document(), "test")
    a_store.root.mkdir(parents=True)
    a_store.path_for(model).write_bytes(b"whole")
    a_store.partial_for(model).write_bytes(b"half")

    assert a_store.remove(model) is True
    assert not a_store.path_for(model).exists()
    assert not a_store.partial_for(model).exists()


def test_the_store_reports_what_it_cannot_know(a_store, monkeypatch):
    monkeypatch.setattr(st.shutil, "disk_usage",
                        lambda _: (_ for _ in ()).throw(OSError("no")))
    assert a_store.free_bytes() is None
    [model] = cat.parse(a_document(), "test")
    assert a_store.room_for(model) is None


def test_room_leaves_headroom(a_store, monkeypatch):
    [model] = cat.parse(a_document(an_entry(size=1000)), "test")
    monkeypatch.setattr(a_store, "free_bytes", lambda: 1050)
    assert a_store.room_for(model) is False, "filling the last byte is not room"
    monkeypatch.setattr(a_store, "free_bytes", lambda: 2000)
    assert a_store.room_for(model) is True


def test_memory_is_a_number_or_nothing():
    ram = st.memory_gb()
    assert ram is None or ram > 0


# --------------------------------------------------------------------------- #
# the provider
# --------------------------------------------------------------------------- #


def test_the_provider_is_registered_and_needs_no_key():
    from comodor import catalogue as providers

    spec = providers.get("local")
    assert spec is not None
    assert spec.needs_key is False
    assert spec.kind == "local"


def test_it_refuses_clearly_when_nothing_is_downloaded(tmp_path):
    from comodor.local.provider import LocalProvider

    provider = LocalProvider(model="qwen2.5-coder-1.5b-q4", user_dir=tmp_path)
    with pytest.raises(Exception, match="not downloaded"):
        provider._ready()


def test_it_refuses_clearly_when_no_model_is_chosen(tmp_path):
    from comodor.local.provider import LocalProvider

    with pytest.raises(Exception, match="no local model"):
        LocalProvider(model="", user_dir=tmp_path)._ready()


def test_it_lists_only_what_is_on_the_disk(tmp_path, monkeypatch):
    """Unlike every other provider, where the list is what the vendor offers."""
    from comodor.local.provider import LocalProvider

    provider = LocalProvider(model="", user_dir=tmp_path)
    assert provider.list_models() == []


# --------------------------------------------------------------------------- #
# the runtime
# --------------------------------------------------------------------------- #


def test_a_missing_binary_says_how_to_get_one(tmp_path, monkeypatch):
    from comodor.local import runtime

    monkeypatch.setattr(runtime, "find_binary", lambda extra=None: None)
    [model] = cat.parse(a_document(), "test")
    with pytest.raises(runtime.RuntimeMissing, match="llama"):
        runtime.Runner().serve(model, tmp_path / "nothing.gguf")


def test_a_port_is_free_when_it_is_handed_out():
    from comodor.local import runtime

    first, second = runtime.free_port(), runtime.free_port()
    assert 1024 < first < 65536
    assert first != second


def test_the_runner_holds_one_server_at_a_time():
    """Two resident models is how a 16 GB machine starts swapping."""
    from comodor.local import runtime

    assert "current.stop()" in Path(runtime.__file__).read_text(encoding="utf-8")


def test_nothing_is_left_running_after_close(tmp_path):
    from comodor.local.provider import LocalProvider

    provider = LocalProvider(model="", user_dir=tmp_path)
    provider.close()
    assert provider._runner.running is None


# --------------------------------------------------------------------------- #
# the two threads
# --------------------------------------------------------------------------- #


def test_a_download_does_not_block_the_caller(tmp_path, served, monkeypatch):
    """The web session starts one and answers the request immediately."""
    monkeypatch.setattr(dl, "EVERY", 0.0)
    served["body"] = b"z" * (2 * dl.CHUNK)
    done = threading.Event()

    def work():
        dl.fetch("https://x.invalid/m.gguf", tmp_path / "m.gguf",
                 expect_size=len(served["body"]))
        done.set()

    started = time.monotonic()
    threading.Thread(target=work, daemon=True).start()
    handed_back = time.monotonic() - started
    assert handed_back < 0.5
    assert done.wait(30)
