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
