"""`tools/check-wheel-contents.py` — the guard that keeps the retired interface
out of what gets installed.

It runs in CI on every wheel the workflow builds, on three operating
systems, and the first time it ran on Windows it crashed before reading a
single wheel: PowerShell hands `dist/*.whl` over as literal text where bash
had expanded it. A guard that depends on the shell it happens to be run from
is not a guard, so the expansion is the tool's own, and it is tested here on
the shell-free path — the function — rather than on whichever shell pytest
was started from.
"""

from __future__ import annotations

import importlib.util
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "check-wheel-contents.py"


@pytest.fixture(scope="module")
def guard():
    spec = importlib.util.spec_from_file_location("check_wheel_contents", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def a_wheel(path: Path, names: list[str]) -> Path:
    """A wheel is a zip; the guard reads names, so names are all it needs."""
    with zipfile.ZipFile(path, "w") as archive:
        for name in names:
            archive.writestr(name, "")
    return path


@pytest.fixture
def complete(tmp_path, guard) -> Path:
    return a_wheel(tmp_path / "comodor-1.0-py3-none-any.whl", list(guard.REQUIRED))


# --------------------------------------------------------------------------- #
# what it checks
# --------------------------------------------------------------------------- #


def test_a_wheel_with_only_what_it_needs_passes(guard, complete, capsys):
    assert guard.main([str(complete)]) == 0
    assert "ok" in capsys.readouterr().out


def test_the_retired_interface_fails_the_wheel(guard, tmp_path, capsys):
    wheel = a_wheel(tmp_path / "comodor-1.0-py3-none-any.whl",
                    [*guard.REQUIRED, "comodor/ui/__init__.py", "comodor/ui/app.py"])

    assert guard.main([str(wheel)]) == 1
    err = capsys.readouterr().err
    assert "comodor/ui/" in err and "2 file(s)" in err


def test_a_wheel_without_the_renderer_fails(guard, tmp_path, capsys):
    wheel = a_wheel(tmp_path / "comodor-1.0-py3-none-any.whl",
                    ["comodor/terminal/console.py"])

    assert guard.main([str(wheel)]) == 1
    assert "missing comodor/tui/dist/main.js" in capsys.readouterr().err


# --------------------------------------------------------------------------- #
# the shell it is run from
# --------------------------------------------------------------------------- #


def test_a_pattern_is_expanded_by_the_tool_itself(guard, complete, capsys):
    """PowerShell does not expand `dist/*.whl`; the tool must, or the
    Windows job crashes on `OSError: Invalid argument: 'dist\\*.whl'`."""
    pattern = str(complete.parent / "*.whl")

    assert guard.main([pattern]) == 0
    assert complete.name in capsys.readouterr().out


def test_a_pattern_that_matches_nothing_names_what_was_asked_for(guard, tmp_path, capsys):
    """Silently checking zero wheels would be a passing guard with no wheel
    behind it — the same lie the crash was, only quieter."""
    pattern = str(tmp_path / "empty" / "*.whl")

    assert guard.main([pattern]) == 2
    assert "no such wheel" in capsys.readouterr().err


def test_a_literal_path_is_taken_as_written(guard, complete):
    """A wheel name with no wildcard must not be handed to a globber that
    would treat `[` in a version string as a character class."""
    assert guard.wheels_named([str(complete)]) == [complete]


def test_no_arguments_is_a_usage_error(guard, capsys):
    assert guard.main([]) == 2
    assert "usage" in capsys.readouterr().err
