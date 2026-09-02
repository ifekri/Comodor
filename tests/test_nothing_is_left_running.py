"""What the suite must not do to the machine it runs on.

Both of these were found the hard way, on the developer's own desktop.

The pointer moved on its own, every run, mid-sentence: `test_real_desktop.py`
drives the real mouse and the only thing gating it was `sys.platform !=
"win32"` — true of every Windows developer who types `pytest`.

And browsers accumulated. Not because `stop` was broken, but because an
interrupted run never reaches it: Ctrl-C, a runner timeout, a killed session.
Chrome is a dozen processes that outlive the Python that started them, holding
their profile and their share of a gigabyte, and nothing in the next run knows
to clean up the last one's. They pile up for days.

Neither is the kind of bug a test suite normally catches, because the damage is
outside the process doing the testing.
"""

from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


# --------------------------------------------------------------------------- #
# the pointer
# --------------------------------------------------------------------------- #


def test_the_real_desktop_tests_do_not_run_unless_asked_for():
    """They take over the machine: the pointer jumps and clicks land where the
    test aims them. Fine on a machine set aside for it, unacceptable on the one
    somebody is working at."""
    source = (ROOT / "tests" / "test_real_desktop.py").read_text(
        encoding="utf-8")

    assert "COMODOR_REAL_DESKTOP" in source, \
        "nothing gates the tests that move the real mouse"
    assert "ASKED_FOR" in source and "skipif(not ASKED_FOR" in source, \
        "the variable is read but never used to skip"


def test_they_are_skipped_by_a_plain_pytest_run(monkeypatch):
    """The property that matters, checked by collecting them rather than by
    reading the file: with nothing set, none of them run."""
    monkeypatch.delenv("COMODOR_REAL_DESKTOP", raising=False)

    finished = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/test_real_desktop.py",
         "--collect-only", "-q", "-n", "0"],
        cwd=ROOT, capture_output=True, text=True, timeout=180)

    # Collection lists them; running is what must not happen. So run it.
    finished = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/test_real_desktop.py",
         "-q", "-n", "0"],
        cwd=ROOT, capture_output=True, text=True, timeout=300)
    output = finished.stdout + finished.stderr

    assert " passed" not in output or "0 passed" in output, \
        f"a real-desktop test ran without being asked for:\n{output[-600:]}"
    assert "skipped" in output


def test_the_environment_variable_is_documented_where_it_is_read():
    """A gate nobody knows about is a test nobody ever runs again."""
    source = (ROOT / "tests" / "test_real_desktop.py").read_text(
        encoding="utf-8")

    assert "COMODOR_REAL_DESKTOP=1 pytest" in source, \
        "it never says how to actually run them"


# --------------------------------------------------------------------------- #
# the browsers
# --------------------------------------------------------------------------- #


def _pids_naming(marker: str) -> set[int]:
    """Every process whose command line contains `marker`.

    Identified by the unique profile directory this test made, not by image
    name. Counting every `chrome.exe` would count the developer's own browser,
    and — since the suite runs in parallel — whatever another worker happened
    to have open at that moment, which made this fail for reasons that had
    nothing to do with what it checks.
    """
    # The marker is a hex uuid this test made, so interpolating it into the
    # command is safe — there is nothing in it to quote.
    #
    # `-not $_.Name.StartsWith('powershell')` because this query carries the
    # marker in its own command line and would otherwise find itself, forever,
    # and report a leak that is the measurement.
    finished = subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         "Get-CimInstance Win32_Process | "
         f"Where-Object {{ $_.CommandLine -like '*{marker}*' -and "
         "$_.Name -ne 'powershell.exe' -and $_.Name -ne 'pwsh.exe' -and "
         "$_.Name -ne 'conhost.exe' } | "
         "ForEach-Object { $_.ProcessId }"],
        capture_output=True, text=True, timeout=90)
    return {int(line.strip()) for line in finished.stdout.splitlines()
            if line.strip().isdigit()}


def test_an_abandoned_browser_is_still_cleaned_up(tmp_path):
    """A run that never reaches its cleanup — the case that actually leaked."""
    if sys.platform != "win32":
        pytest.skip("the process listing here is Windows-specific")
    try:
        from comodor.browser.launch import find

        find()
    except Exception:
        pytest.skip("no browser on this machine")

    import time
    import uuid

    # A marker no other process on the machine can be carrying.
    marker = f"comodor-leak-check-{uuid.uuid4().hex[:12]}"
    profile = tmp_path / marker / "profile"

    abandons_it = textwrap.dedent(f'''
        import sys
        from pathlib import Path
        sys.path.insert(0, "src")
        from comodor.browser import Browser
        Browser.start(Path({str(profile)!r}), headless=True)
        # No stop(), no finally: the process simply ends, the way an
        # interrupted run does.
    ''')

    subprocess.run([sys.executable, "-c", abandons_it],
                   cwd=ROOT, capture_output=True, timeout=180)

    # atexit runs during interpreter shutdown and the children go shortly
    # after, so this waits for the state rather than for a fixed delay.
    for _ in range(30):
        if not _pids_naming(marker):
            break
        time.sleep(0.5)
    left = _pids_naming(marker)

    assert not left, (
        f"{len(left)} browser processes outlived the run that started them — "
        f"this is how a machine fills up with browsers nobody opened")


def test_stopping_is_registered_for_a_run_that_never_gets_there():
    """The mechanism, asserted directly, so the test above failing points at
    the right thing rather than at whatever else could leave a process."""
    from comodor.browser import launch

    assert hasattr(launch, "_LIVE"), "nothing tracks the open browsers"
    assert hasattr(launch, "_stop_everything_still_open")

    text = Path(launch.__file__).read_text(encoding="utf-8")
    assert "atexit.register(_stop_everything_still_open)" in text, \
        "the cleanup is defined and never registered"
    assert "_remember(browser)" in text, \
        "a started browser is never added to the set that gets cleaned up"
