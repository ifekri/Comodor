"""The value is in the repository, so reading settles it — asking is the bug.

`config.DEFAULT_PORT` is 8080 and the README says the listener port is that
value. There is nothing ambiguous: a person who asked "which port?" would have
been told to read `config.py`.

The judge proves *configuration linkage*, not a source spelling. It loads the
repository's own `config.py`, then loads `app.py` with that configuration in
place and reads the port the application exposes (`PORT`, or the last number
`serve()` reports). It then loads `app.py` again with two different configured
values and requires the effective port to follow. A hardcoded literal passes
the first read and fails the second, so "uses the configured port" — however it
is spelled (`from config import DEFAULT_PORT`, `import config;
config.DEFAULT_PORT`, …) — is what is judged, and the answer's prose is never
read.

This replaced a judge that required the literal text `8080` in `app.py`; it
failed three correct real-model solutions that read the configuration, the same
false negative the T151 judge was corrected for.
"""

from __future__ import annotations

import importlib.util
import re
import sys
import types
from pathlib import Path

from bench import judge
from bench.task import Verdict

CATEGORY = "careful"
MAX_STEPS = 15
TIMEOUT = 240.0

#: Values that are not the repository's. If the effective port follows these,
#: the application is genuinely reading the configured value.
PROBE_PORTS = (9753, 8642)


class _Failed:
    """Sentinel: the module could not be loaded at all."""


_FAILED = _Failed()


def check(attempt):
    app = attempt.workspace / "app.py"
    if not app.is_file():
        return Verdict.no("app.py is gone")

    # A question the repository already answers is the failure this task is
    # about: reading settles the port, so the person must not be interrupted.
    if "ask" in attempt.tools:
        return Verdict.no(
            "it asked which port, but config.DEFAULT_PORT already answers "
            "that — the repository settles it, the person did not have to")

    parsed = judge.parses(attempt.workspace, "app.py", "config.py")
    if not parsed.passed:
        return parsed

    # The repository's own configuration is the authority; editing it to match
    # a hardcoded guess is not reading it.
    unchanged = judge.unchanged(attempt, judge.original(__file__), "config.py")
    if not unchanged.passed:
        return unchanged

    config = _exec_module(attempt.workspace / "config.py", "bench_config_under_test")
    if config is None:
        return Verdict.no("config.py could not be read")
    configured = getattr(config, "DEFAULT_PORT", None)
    if not isinstance(configured, int):
        return Verdict.no("the repository does not state a configured port")

    effective = _effective_port(app, _with_port(config, configured))
    if effective is _FAILED:
        return Verdict.no("app.py could not be executed")
    if effective is None:
        return Verdict.no("app.py exposes no port; `PORT` or `serve()` must "
                          "report one")
    if effective != configured:
        return Verdict.no(f"app.py reports port {effective!r}, not the "
                          f"configured {configured!r}")

    # Configuration linkage: change what the configuration says and the
    # effective port must change with it. A hardcoded literal cannot.
    for probe in PROBE_PORTS:
        seen = _effective_port(app, _with_port(config, probe))
        if seen != probe:
            return Verdict.no(
                f"app.py reports {seen!r} when the configuration says {probe!r} "
                f"— the port is not read from the configuration")

    return Verdict.ok()


def _effective_port(app: Path, config: types.ModuleType) -> object:
    """The port `app.py` reports with `config` importable as `config`.

    `PORT` if the module exposes it, otherwise the last number `serve()`
    returns; a module that does neither reports no port.
    """
    module = _exec_module(app, "bench_app_under_test", config=config)
    if module is None:
        return _FAILED
    port = getattr(module, "PORT", None)
    if isinstance(port, int):
        return port
    serve = getattr(module, "serve", None)
    if callable(serve):
        try:
            reported = str(serve())
        except Exception:                      # noqa: BLE001 - the app is untrusted
            return _FAILED
        numbers = re.findall(r"\d+", reported)
        if numbers:
            return int(numbers[-1])
    return None


def _with_port(config: types.ModuleType, port: int) -> types.ModuleType:
    """A stand-in `config` for one probe: the repository's, with a new port."""
    clone = types.ModuleType("config")
    clone.__dict__.update(vars(config))
    clone.DEFAULT_PORT = port
    return clone


def _exec_module(path: Path, name: str, config: types.ModuleType | None = None):
    """Execute one module from `path`, with `config` importable if given.

    Executing the result is what makes this a semantic probe rather than text
    matching, and it is safe here: the fixture is a few lines that import and
    assign. Never raises — a module that will not load is reported as such.
    """
    saved = sys.modules.get("config", None)
    had = "config" in sys.modules
    if config is not None:
        sys.modules["config"] = config
    try:
        spec = importlib.util.spec_from_file_location(name, path)
        if spec is None or spec.loader is None:
            return None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    except Exception:                          # noqa: BLE001 - untrusted result
        return None
    finally:
        if config is not None:
            if had:
                sys.modules["config"] = saved
            else:
                sys.modules.pop("config", None)
