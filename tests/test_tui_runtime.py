"""The packaged renderer's own plumbing: lookup, verification, Bun detection.

These run against the real artifact the build writes, because the point of
the module is that what it reports and what the build produced cannot drift.
"""

from __future__ import annotations

import hashlib
import json

from comodor.tui import runtime


def test_the_packaged_renderer_is_found_and_whole():
    """The artifact the wheel ships must verify against its own manifest."""
    path, origin = runtime.renderer()
    assert origin in ("package", "checkout")
    assert path is not None
    if origin == "package":
        assert runtime.verify(path) == [], (
            "the shipped artifact does not match its manifest")


def test_a_renderer_missing_its_entry_is_not_one(tmp_path):
    """An empty directory is not a renderer; the launcher must say so."""
    dist = tmp_path / "dist"
    dist.mkdir()
    assert runtime.verify(dist) != []


def test_a_corrupt_asset_is_named_not_silenced(tmp_path):
    """A file that is not what the manifest says is a different file."""
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "main.js").write_text("// the real one", encoding="utf-8")
    manifest = {"entry": "main.js", "native": "",
                "files": ["main.js"],
                "sha256": {"main.js": "0" * 64}}
    (dist / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    problems = runtime.verify(dist)
    assert any("does not match" in problem for problem in problems)


def test_bun_version_parses_a_real_answer():
    found = runtime.bun()
    if found is None:
        import pytest

        pytest.skip("no bun on this machine")
    version = runtime.bun_version(found)
    assert version is not None and version[0] >= 1


def test_bun_version_of_a_path_that_is_not_bun_is_none(tmp_path):
    fake = tmp_path / "not-bun"
    fake.write_text("@echo off\r\nexit /b 1\r\n", encoding="utf-8")
    assert runtime.bun_version(str(fake)) is None


def test_checkout_fallback_never_leaks_into_a_package(tmp_path, monkeypatch):
    """An installed package answers from itself, never from a nearby repo."""
    # Simulated by pointing the package resource lookup at nothing and
    # the checkout probe at a path that does not exist.
    monkeypatch.setattr(runtime, "packaged_dist", lambda: None)
    monkeypatch.setattr(runtime, "checkout_entry", lambda: None)
    assert runtime.renderer() == (None, "")


def test_a_package_is_preferred_over_a_checkout(monkeypatch, tmp_path):
    """A whole packaged artifact wins over the development tree.

    The checkout is the development fallback; a pipx install that could see a
    stray clone would otherwise run whatever that clone happened to hold. The
    preference is conditional on the artifact being whole for this platform —
    an artifact that cannot load is not an answer, and the checkout is what
    makes a foreign-platform source tree still work.
    """
    import hashlib

    dist = tmp_path / "dist"
    backend = dist / "node_modules" / "@opentui" / runtime.current_native_package().split("/")[-1]
    backend.mkdir(parents=True)
    (dist / "main.js").write_text("// the bundle", encoding="utf-8")
    native = runtime.current_native_package().split("/")[-1]
    (dist / "manifest.json").write_text(json.dumps({
        "entry": "main.js",
        "native": native,
        "natives": [native],
        "files": ["main.js"],
        "sha256": {"main.js": hashlib.sha256(b"// the bundle").hexdigest()},
    }), encoding="utf-8")
    entry = tmp_path / "checkout" / "main.tsx"
    entry.parent.mkdir(parents=True)
    entry.write_text("// checkout", encoding="utf-8")
    monkeypatch.setattr(runtime, "packaged_dist", lambda: dist)
    monkeypatch.setattr(runtime, "checkout_entry", lambda: entry)
    assert runtime.renderer() == (dist, "package")


def test_a_foreign_platform_artifact_falls_back_to_the_checkout(
        monkeypatch, tmp_path):
    """An artifact built for another OS is not this machine's renderer.

    The committed artifact carries the platform it was built on; a source
    checkout on another platform must use its own tree, or `comodor` would
    try to load a backend that does not exist here.
    """
    dist = tmp_path / "dist"
    (dist / "node_modules" / "@opentui" / "core-the-other-os").mkdir(
        parents=True)
    (dist / "main.js").write_text("// the bundle", encoding="utf-8")
    (dist / "manifest.json").write_text(json.dumps({
        "entry": "main.js",
        "native": "core-the-other-os",
        "natives": ["core-the-other-os"],
        "files": ["main.js"],
        "sha256": {"main.js": hashlib.sha256(b"// the bundle").hexdigest()},
    }), encoding="utf-8")

    entry = tmp_path / "checkout" / "main.tsx"
    entry.parent.mkdir(parents=True)
    entry.write_text("// checkout", encoding="utf-8")
    monkeypatch.setattr(runtime, "packaged_dist", lambda: dist)
    monkeypatch.setattr(runtime, "checkout_entry", lambda: entry)
    assert runtime.renderer() == (entry, "checkout")


def test_a_missing_renderer_is_a_clear_refusal(tmp_path, monkeypatch, capsys):
    """No artifact, no Bun — the launch refuses before any setup is asked."""
    import argparse

    from comodor.transport.commands import run_tui

    monkeypatch.setattr(runtime, "packaged_dist", lambda: None)
    monkeypatch.setattr(runtime, "checkout_entry", lambda: None)
    monkeypatch.setattr("comodor.tui.runtime.bun", lambda: "/fake/bun")

    from comodor.config import Config
    from comodor.paths import Paths

    (tmp_path / "project").mkdir()
    config = Config(paths=Paths(user=tmp_path / "home",
                                project=tmp_path / "project"))
    (tmp_path / "home").mkdir()
    config.providers = {}
    config.provider = ""

    code = run_tui(config, argparse.Namespace(demo=False))
    out = capsys.readouterr()
    assert code == 2
    assert "no TUI renderer" in out.err


def test_a_machine_without_bun_is_a_clear_refusal(tmp_path, monkeypatch,
                                                  capsys):
    """Bun is stated, not discovered by a broken screen."""
    import argparse

    from comodor.transport.commands import run_tui

    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "main.js").write_text("// the bundle", encoding="utf-8")
    monkeypatch.setattr(runtime, "packaged_dist", lambda: dist)
    monkeypatch.setattr(runtime, "bun", lambda: None)

    from comodor.config import Config
    from comodor.paths import Paths

    (tmp_path / "project").mkdir()
    config = Config(paths=Paths(user=tmp_path / "home",
                                project=tmp_path / "project"))
    (tmp_path / "home").mkdir()
    config.providers = {}
    config.provider = ""

    code = run_tui(config, argparse.Namespace(demo=False))
    out = capsys.readouterr()
    assert code == 2
    assert "Bun" in out.err
    assert "legacy" in out.err

