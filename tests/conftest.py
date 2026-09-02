"""Shared fixtures.

Every test runs against a temporary workspace and a temporary brain, so nothing
touches the developer's real project or their accumulated memory, and tests can
run in any order.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from comodor.config import Config, ProviderConfig  # noqa: E402
from comodor.events import EventBus  # noqa: E402
from comodor.paths import Paths  # noqa: E402
from comodor.safety import CheckpointStore, PermissionEngine, Redactor  # noqa: E402
from comodor.tools import ToolContext, ToolRegistry  # noqa: E402


@pytest.fixture(autouse=True)
def a_home_of_our_own(monkeypatch, tmp_path: Path):
    """No test may reach the real data directory, whatever it does.

    Most fixtures build a `Config` with explicit `Paths`, which is safe. But
    `load()` resolves its own paths and ignores the ones it was handed, so a
    test that saves a config it loaded writes to the developer's real
    `config.json` — and passes, because everything it asserts is true of that
    file too. One that deletes it also passes.

    `COMODOR_HOME` is the single lever `resolve_paths` honours, so it is set
    here for every test rather than left to each one to remember. The tests
    that care about the home directory set their own and still win, because a
    later `setenv` replaces this one.
    """
    home = tmp_path / "comodor-home"
    home.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("COMODOR_HOME", str(home))
    # And the profile, which moves the same directory again. A test that sets
    # it through `os.environ` rather than `monkeypatch` leaks it into every
    # test that runs after: `user_root` then answers `home/profiles/work`, the
    # file just saved is not the file loaded back, and the failure lands on
    # whichever test happened to be next rather than on the one at fault.
    monkeypatch.delenv("COMODOR_PROFILE", raising=False)


@pytest.fixture(autouse=True)
def no_skill_library(monkeypatch):
    """Nothing in this suite downloads the skills catalogue.

    The first-run wizard offers the library, which means an unpatched test of
    the wizard reaches out to raw.githubusercontent.com — a suite that needs a
    network, and one whose results depend on what happens to be published. The
    tests that are about the catalogue supply their own stand-in server.
    """
    def offline(*args, **kwargs):
        from comodor.skills.catalogue import CatalogueError

        raise CatalogueError("no network in the test suite")

    monkeypatch.setattr("comodor.skills.catalogue.fetch", offline)


@pytest.fixture(autouse=True)
def a_terminal_of_known_shape(monkeypatch):
    """The suite decides what the terminal can do, not the shell that ran it.

    `NO_COLOR` is a widely honoured convention and plenty of people set it
    globally. `prepare_theme` respects it, so with it set the tests that assert
    the banner is painted, or that the background reaches the empty rows, fail
    on a working build — and the failure looks like a bug in the banner rather
    than a preference in the environment. The colour-detection tests set these
    for themselves.
    """
    for name in ("NO_COLOR", "TERM_PROGRAM", "COLORTERM", "WT_SESSION"):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture(autouse=True)
def no_importing_from_the_real_home(monkeypatch):
    """Nothing in this suite reads another agent's real configuration.

    The wizard's first screen offers to import from OpenClaw or Hermes, and
    `discover` looks in `Path.home()`. On a machine that has either installed —
    which is the machine this was written on — an unguarded test of the wizard
    would copy a real API key into a temporary config and real skills into a
    temporary directory, and still pass. The tests that are about the import
    pass their own directory to look in.
    """
    monkeypatch.setenv("COMODOR_NO_IMPORT", "1")


@pytest.fixture(autouse=True)
def no_package_index(monkeypatch):
    """Nothing in this suite asks PyPI what the newest release is.

    `doctor` does, which is useful in a report and useless in a test: it makes
    the suite depend on a network, and in CI - where the checkout is shallow
    and the version reads as `0.1.dev1` - it reports being out of date on every
    single run. The tests that are about that check patch this themselves.
    """
    monkeypatch.setattr("comodor.update.latest", lambda *args, **kwargs: None)


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    """A project root that is a *subdirectory* of tmp_path.

    Nesting it matters: tests for the workspace guard need somewhere that is
    genuinely outside the project but still inside the temporary tree.
    """
    root = tmp_path / "project"
    (root / "src").mkdir(parents=True)
    (root / "pyproject.toml").write_text("[project]\nname='sample'\n", encoding="utf-8")
    return root


@pytest.fixture
def config(workspace: Path, tmp_path: Path) -> Config:
    """A config pointed entirely at temporary directories, using the fake provider."""
    cfg = Config(paths=Paths(user=tmp_path / "home", project=workspace))
    (tmp_path / "home").mkdir(parents=True, exist_ok=True)
    cfg.providers = {
        "fake": ProviderConfig(name="fake", kind="fake", base_url="offline",
                               api_key="test", model="fake-1", label="Fake"),
    }
    cfg.provider = "fake"
    cfg.model = "fake-1"
    cfg.agent.context_limit = 100_000
    cfg.safety.auto_approve_writes = True
    cfg.safety.auto_approve_shell = True
    return cfg


@pytest.fixture
def bus() -> EventBus:
    return EventBus()


@pytest.fixture
def tool_context(config: Config, bus: EventBus) -> ToolContext:
    from comodor.events import Cancellation

    return ToolContext(
        config=config,
        permissions=PermissionEngine(config, bus),
        checkpoints=CheckpointStore(config.paths.checkpoints),
        bus=bus,
        redact=Redactor([]),
        cancel=Cancellation(),
        cwd=config.paths.project,
    )


@pytest.fixture
def tools() -> ToolRegistry:
    return ToolRegistry()
