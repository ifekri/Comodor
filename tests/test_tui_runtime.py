"""The packaged renderer's own plumbing: lookup, verification, Bun detection.

These run against the real artifact the build writes, because the point of
the module is that what it reports and what the build produced cannot drift.
"""

from __future__ import annotations

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
    """When both exist, the package wins: the checkout is the development
    fallback, and silently preferring it would mean a pipx install running
    whatever a stray clone happened to hold."""
    dist = tmp_path / "dist"
    dist.mkdir()
    entry = tmp_path / "checkout" / "main.tsx"
    entry.parent.mkdir(parents=True)
    entry.write_text("// checkout", encoding="utf-8")
    monkeypatch.setattr(runtime, "packaged_dist", lambda: dist)
    monkeypatch.setattr(runtime, "checkout_entry", lambda: entry)
    assert runtime.renderer() == (dist, "package")


def test_a_missing_renderer_is_a_clear_refusal(tmp_path, monkeypatch, capsys):
    """No artifact, no Bun — the launch refuses before any setup is asked."""
    from comodor.transport.commands import run_tui

    import argparse

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
    from comodor.transport.commands import run_tui

    import argparse

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

