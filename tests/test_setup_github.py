"""The GitHub step of onboarding, without a browser, a worker or a network.

The plan's states are tested in `test_onboarding.py`; what is tested here is
the join: the wizard offering the connection, driving a host through it, and
turning what the host reports into what the person sees and what gets written.

The host is the seam. Setup's orchestration asks it to begin, open, present
and wait; the default reaches the real connector and the real link
presentation, and these tests substitute a fake so that "Connect" can be
chosen without anything leaving the process. No real browser, no real worker,
no real GitHub, and no sleeps — the fake is a script.
"""

from __future__ import annotations

import io
import json
from types import SimpleNamespace

import pytest
from rich.console import Console

from comodor.config import Config, GitHubInstallation, Paths
from comodor.github import connect as github_connect
from comodor.onboarding import GitHubStep, Step
from comodor.setup import SetupWizard

FAKE_KEY = "sk-test-DO-NOT-WRITE-THIS-ANYWHERE-0123456789"


@pytest.fixture
def blank(tmp_path):
    """A fresh configuration: nothing chosen, so nothing is skipped over."""
    from comodor.config import _build_providers

    config = Config(paths=Paths(user=tmp_path / "home",
                                project=tmp_path / "project"))
    (tmp_path / "home").mkdir(parents=True, exist_ok=True)
    (tmp_path / "project").mkdir(parents=True, exist_ok=True)
    config.providers = _build_providers()
    return config


class FakeFlow:
    """One browser connection, scripted.

    `waits` is a queue of outcomes for the wait: an exception to raise, or an
    installation to return. Each retry attempt consumes another, so a
    transient failure followed by a success is two entries and no timing.
    """

    def __init__(self, *, begin_error=None, opened=True, automatic=True,
                 waits=()):
        self.begin_error = begin_error
        self.opened = opened
        self.automatic = automatic
        self.waits = list(waits)
        self.begun = 0
        self.presented = []

    def begin(self):
        self.begun += 1
        if self.begin_error is not None:
            raise self.begin_error
        return SimpleNamespace(url="https://github.com/apps/comodor-agent/x",
                               automatic=self.automatic,
                               seconds_left=900.0)

    def open(self, pending) -> bool:
        return self.opened

    def present(self, url: str, opened: bool) -> None:
        self.presented.append((url, opened))

    def wait(self, pending):
        outcome = self.waits.pop(0) if self.waits else None
        # BaseException, not Exception: KeyboardInterrupt is the former, and a
        # fake that returned it would hand the wizard a KeyboardInterrupt
        # object where an installation belongs — which is exactly the kind of
        # nonsense a fake exists to catch before the real thing produces it.
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


def an_installation(login: str = "someone",
                    installation_id: int = 7) -> GitHubInstallation:
    return GitHubInstallation(installation_id=installation_id, account_id=1,
                              account_login=login, account_type="User",
                              repository_selection="all",
                              grant="g2.signed-statement")


def run(blank_config, flow=None, github=("",), minimal=True,
        provider="ollama"):
    """A whole run, answered by step rather than by position.

    The prompt answers from the plan's own step identity: ollama by default
    (it needs no key, so the credential question is never asked), the first
    model, and whatever the test scripted for the GitHub step. A test about
    connecting cannot be derailed by a reply drifting onto a different
    question, and a test about anything else cannot drift onto this one.

    `provider="openai"` swaps in a provider that does ask for a key, which
    the secret answers — for tests about where the credential does and does
    not end up.
    """
    console = Console(file=io.StringIO(), width=90, force_terminal=False)
    github_replies = iter(github)
    holder: dict = {}

    def prompt(message: str) -> str:
        plan = holder.get("plan")
        step = plan.step if plan is not None else None
        if step is Step.PROVIDER:
            at = [fact.id for fact in plan.facts].index(provider)
            return str(at + 1)
        if step is Step.MODEL:
            return "1"
        if step is Step.GITHUB:
            return next(github_replies, "")
        return ""

    made = SetupWizard(blank_config, console=console, prompt=prompt,
                       secret=lambda message: FAKE_KEY,
                       github=(lambda config, console: flow) if flow else None)
    holder["plan"] = made.plan
    made._discover_models = lambda spec, answers: ["qwen2.5-coder"]
    answers = made.run(minimal=minimal)
    return made, made.apply(answers), console


# --------------------------------------------------------------------------- #
# skipping is a complete setup
# --------------------------------------------------------------------------- #

def test_skipping_github_finishes_setup(blank):
    _, saved, _ = run(blank, github=("2",))

    assert saved.github.installations == []
    assert saved.github.enabled is False
    assert saved.needs_setup is False, "skipping is success, not half-setup"


def test_pressing_enter_at_the_github_question_skips(blank):
    """The safe default: an empty answer must not open anything."""
    flow = FakeFlow()
    _, saved, _ = run(blank, flow, github=("",))

    assert flow.begun == 0, "an empty answer opened a connection"
    assert saved.github.installations == []


def test_no_host_is_built_when_the_answer_is_skip(blank):
    """The factory is not even called — nothing to reach."""
    def forbidden(_config, _console):
        raise AssertionError("a skip built a connection flow")

    console = Console(file=io.StringIO(), width=90, force_terminal=False)
    holder: dict = {}

    def prompt(message: str) -> str:
        plan = holder.get("plan")
        step = plan.step if plan is not None else None
        if step is Step.PROVIDER:
            return str([f.id for f in plan.facts].index("ollama") + 1)
        if step is Step.MODEL:
            return "1"
        return "2" if step is Step.GITHUB else ""

    made = SetupWizard(blank, console=console, prompt=prompt,
                       secret=lambda message: FAKE_KEY, github=forbidden)
    holder["plan"] = made.plan
    made._discover_models = lambda spec, answers: ["qwen2.5-coder"]
    made.apply(made.run(minimal=True))


# --------------------------------------------------------------------------- #
# an existing connection is kept, not remade
# --------------------------------------------------------------------------- #

def test_an_existing_connection_is_not_reconnected(blank):
    blank.github.remember(an_installation("ifekri", 42))
    flow = FakeFlow()

    made, saved, console = run(blank, flow, github=("2",))

    assert made.plan.github.step is GitHubStep.KEPT
    assert "ifekri" in console.file.getvalue()
    assert flow.begun == 0, "setup reconnected a working installation"
    assert saved.github.installations[0].installation_id == 42


# --------------------------------------------------------------------------- #
# the modern flow
# --------------------------------------------------------------------------- #

def test_the_browser_flow_connects_and_is_recorded(blank):
    flow = FakeFlow(waits=[an_installation("ifekri")])

    made, saved, _ = run(blank, flow, github=("1",))

    assert flow.begun == 1
    assert made.plan.github.step is GitHubStep.CONNECTED
    assert made.plan.github.account == "ifekri"
    assert saved.github.installations[0].account_login == "ifekri"
    assert saved.github.enabled is True


def test_the_link_is_presented_once_with_what_happened(blank):
    """The wizard hands the URL and the open outcome to the host.

    The presentation itself — OSC 8 label, clipboard fallback, raw URL as the
    last resort — is the same code `comodor github connect` uses and is
    tested in `test_github_connect_flow.py`; here it is only asserted that
    setup passes the right things to it, once, and only when a flow began.
    """
    flow = FakeFlow(waits=[an_installation()])
    run(blank, flow, github=("1",))

    assert flow.presented == [("https://github.com/apps/comodor-agent/x", True)]


def test_when_no_browser_can_open_the_flow_still_waits(blank):
    """No browser is a solved problem, not a dead end."""
    flow = FakeFlow(opened=False, waits=[an_installation()])
    run(blank, flow, github=("1",))

    assert flow.presented == [("https://github.com/apps/comodor-agent/x", False)]


def test_a_browser_that_finished_is_not_a_connection_until_committed(blank):
    """The plan holds the installation; the disk sees it at commit, once.

    Covered at the plan level in `test_onboarding.py`; this is the wizard
    half — nothing is written while the questions are still being asked.
    """
    flow = FakeFlow(waits=[an_installation()])
    made, _, _ = run(blank, flow, github=("1", "1"))

    assert made.plan.github.step is GitHubStep.CONNECTED
    assert blank.paths.config_file.exists()
    # And it appears exactly once.
    body = blank.paths.config_file.read_text(encoding="utf-8")
    assert body.count('"installation_id"') == 1


def test_cancel_during_the_wait_connects_nothing(blank):
    """Ctrl-C while waiting: nothing written, setup still finishes."""
    flow = FakeFlow(waits=[KeyboardInterrupt()])
    made, saved, _ = run(blank, flow, github=("1", "2"))

    assert "Nothing was connected." in made.console.file.getvalue()
    assert made.plan.github.step is not GitHubStep.CONNECTED
    assert saved.github.installations == []
    assert saved.github.enabled is False


def test_an_older_worker_is_not_driven_from_setup(blank):
    """A receipt flow belongs to the command built for it, not to first-run.

    Setup does not ask anybody to copy anything, so a pending that cannot
    finish by itself is named and skipped, and onboarding still completes.
    """
    flow = FakeFlow(automatic=False)
    made, saved, console = run(blank, flow, github=("1",))

    assert made.plan.github.step is GitHubStep.SKIPPED
    assert saved.github.installations == []


# --------------------------------------------------------------------------- #
# failure, told apart
# --------------------------------------------------------------------------- #

def test_a_refused_begin_can_be_skipped(blank):
    problem = github_connect.ConnectError(
        "GitHub would not confirm that installation.",
        status=403, kind=github_connect.REFUSED)
    flow = FakeFlow(begin_error=problem)

    made, saved, console = run(blank, flow, github=("1", "2"))

    assert made.plan.github.step is GitHubStep.SKIPPED
    assert "would not confirm" in console.file.getvalue()
    assert saved.github.installations == []


def test_a_transient_failure_can_be_retried_to_success(blank):
    trouble = github_connect.ConnectError(
        "gave up waiting: the endpoint said 502", status=502,
        kind=github_connect.UNREACHABLE)
    flow = FakeFlow(waits=[trouble, an_installation("ifekri")])

    made, saved, _ = run(blank, flow, github=("1", "1"))

    assert flow.begun == 2, "the retry never ran"
    assert made.plan.github.step is GitHubStep.CONNECTED
    assert saved.github.installations[0].account_login == "ifekri"


def test_an_expired_link_is_offered_a_fresh_one_not_the_old_one(blank):
    expired = github_connect.ConnectError(
        "that connection link expired before it was used.",
        kind=github_connect.EXPIRED)
    flow = FakeFlow(waits=[expired, an_installation("ifekri")])

    made, saved, _ = run(blank, flow, github=("1", "1"))

    assert flow.begun == 2
    # The expired attempt's URL is not carried into the second.
    urls = [url for url, _ in flow.presented]
    assert len(urls) == 2 and urls[0] == urls[1]
    assert made.plan.github.url == "", "an expired link stayed on the plan"
    assert saved.github.installations[0].account_login == "ifekri"


def test_three_failed_attempts_skip_rather_than_loop(blank):
    trouble = github_connect.ConnectError(
        "gave up waiting: no answer", kind=github_connect.UNREACHABLE)
    flow = FakeFlow(waits=[trouble, trouble, trouble, trouble])

    made, saved, console = run(blank, flow, github=("1", "1", "1", "1"))

    assert flow.begun == 3, "it retried more than three times"
    assert made.plan.github.step is GitHubStep.SKIPPED
    assert saved.github.installations == []


def test_the_cancel_race_has_one_winner(blank):
    """The person gives up, and then the browser finishes.

    Deterministic here because the fake returns the installation only on a
    later attempt that is never made: the cancel retires the attempt, and a
    late result is dropped by the plan (covered for real in
    `test_onboarding.py`). What this pins at the wizard level is that cancel
    does not leave the flow half-alive to answer a stale result into.
    """
    flow = FakeFlow(waits=[KeyboardInterrupt(), an_installation()])
    made, saved, _ = run(blank, flow, github=("1", "2"))

    assert flow.begun == 1, "a cancelled flow was retried without asking"
    assert made.plan.github.step is GitHubStep.SKIPPED
    assert saved.github.installations == []


# --------------------------------------------------------------------------- #
# secrets
# --------------------------------------------------------------------------- #

def test_a_typed_key_stays_out_of_the_github_section(blank):
    """A provider key that was typed during setup never lands in the github
    config, where copying the file would publish it.
    """
    flow = FakeFlow(waits=[an_installation()])
    made, saved, _ = run(blank, flow, github=("1",), provider="openai")

    body = blank.paths.config_file.read_text(encoding="utf-8")
    config = json.loads(body)
    github_part = json.dumps(config["github"])
    assert FAKE_KEY not in github_part, "the provider key leaked into the github config"
    assert "api_key" not in github_part, "no credential material in github"
    assert FAKE_KEY in json.dumps(config.get("providers", {}))
    inst = saved.github.installations[0]
    assert inst.installation_id == 7, "a verified installation was recorded"
