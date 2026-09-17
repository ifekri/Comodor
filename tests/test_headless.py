"""`comodor run` — the path scripts, CI and the benchmark all go through.

Nobody is watching a headless run, which is exactly why the two things checked
here matter. A question with no one to answer it used to hold the process for
half an hour and then carry on regardless, and the JSON result said what the
agent spent but not what it reached for — so a caller could see that a task
finished and not that it finished by guessing.
"""

from __future__ import annotations

import argparse
import io
import json
import time
from contextlib import redirect_stdout

import pytest

from comodor import cli
from comodor.config import ProviderConfig, load
from comodor.providers.base import ToolCall
from comodor.providers.fake import Script
from comodor.providers.gateway import Gateway


@pytest.fixture
def scripted(tmp_path, monkeypatch):
    """A headless run against a provider we write the answers for."""
    home = tmp_path / "home"
    project = tmp_path / "work"
    project.mkdir(parents=True)
    monkeypatch.setenv("COMODOR_HOME", str(home))

    def build(scripts: list[Script]):
        config = load(cwd=project, use_environment=False)
        config.providers["fake"] = ProviderConfig(
            name="fake", kind="fake", base_url="offline", api_key="demo",
            model="scripted", configured=True)
        config.provider = "fake"
        # The brain would otherwise reflect on every one of these, which costs
        # a model call for a run that is testing neither.
        config.learning.enabled = False

        def make(configuration, scripts=None):
            gateway = Gateway(configuration, scripts=list(build.plan))
            # The provider is kept, not the gateway: `run_headless` closes the
            # gateway when it is done, which drops its instances, so asking for
            # one afterwards builds a fresh object that has recorded nothing.
            build.providers.append(gateway.provider("fake"))
            return gateway

        monkeypatch.setattr("comodor.providers.gateway.Gateway", make)
        build.plan = scripts
        return config

    build.plan = []
    build.providers = []
    return build


def a_question() -> ToolCall:
    return ToolCall(id="call-1", name="ask", arguments={"questions": [{
        "question": "Which framework?",
        "header": "Framework",
        "multiSelect": False,
        "options": [{"label": "Flask", "description": "small"},
                    {"label": "Django", "description": "large"}],
    }]})


def run(config, **overrides) -> argparse.Namespace:
    args = argparse.Namespace(task="build me something", yes=True, json=False,
                              max_steps=3)
    for key, value in overrides.items():
        setattr(args, key, value)
    return args


# --------------------------------------------------------------------------- #
# the thirty-minute wait
# --------------------------------------------------------------------------- #


@pytest.mark.performance
def test_a_question_nobody_can_answer_does_not_hold_the_run(scripted):
    """`ask` waits half an hour for an answer. Headless, one can never arrive.

    The timing is the assertion. A wall-clock bound is usually a bad test, but
    the failure being guarded against is *thirty minutes*, so any ceiling in
    seconds is nowhere near the line it is drawing.

    Fifteen, not two. It measures at 0.15s on a developer's machine and went
    over two seconds on a cold Windows CI runner — where the first `import
    comodor` of a process is doing most of the work. Two seconds was chosen to
    look tight; what it actually did was make an honest pass depend on how
    busy somebody else's machine was, and the thirty-minute hang it exists to
    catch is caught just as surely at fifteen.
    """
    config = scripted([
        Script(text="One thing first.", tool_calls=[a_question()]),
        Script(text="Flask it is."),
    ])

    started = time.monotonic()
    code = cli.run_headless(config, run(config))
    elapsed = time.monotonic() - started

    # Since spec 002 (FR-082) a question nobody can answer ends the run
    # needing a decision rather than carrying on; the exit is non-zero and
    # the run still does not wait.
    assert code != 0
    assert elapsed < 15.0, f"the run waited {elapsed:.0f}s for an answer"


def test_a_headless_form_ends_the_run_needing_a_decision(scripted):
    """Nobody is there to answer, so the run stops and says what is needed
    (spec 002, FR-033, FR-082). The model is never told to carry on."""
    config = scripted([
        Script(text="One thing first.", tool_calls=[a_question()]),
        Script(text="Flask it is."),
    ])

    code = cli.run_headless(config, run(config))

    assert code != 0
    assert scripted.providers, "the run should have built a gateway"
    replies = [message.content for call in scripted.providers[0].calls
               for message in call]
    assert not any("sensible defaults" in reply for reply in replies)
    assert not any("Flask it is" in reply for reply in replies), \
        "the second script never ran: the turn stopped at the question"


def test_a_permission_prompt_is_left_to_its_own_deadline(scripted):
    """Permissions must keep refusing by default. Answering them here would
    turn a headless run into one that approves whatever it is asked."""
    import inspect

    source = inspect.getsource(cli.run_headless)
    assert 'request.kind == "questions"' in source, \
        "the headless responder must not answer permission requests"


# --------------------------------------------------------------------------- #
# what the run reports
# --------------------------------------------------------------------------- #


def test_the_json_result_names_the_tools_that_ran(scripted):
    config = scripted([
        Script(text="Reading first.", tool_calls=[
            ToolCall(id="c1", name="list_dir", arguments={"path": "."})]),
        Script(text="Nothing to change."),
    ])

    out = io.StringIO()
    with redirect_stdout(out):
        cli.run_headless(config, run(config, json=True))

    report = json.loads(out.getvalue())
    assert report["tools"] == ["list_dir"]
    assert report["tool_calls"] == 1


def test_an_answer_with_an_arrow_in_it_does_not_kill_the_run(scripted, capsys):
    """A Windows console is cp1252, and `print` of anything outside it raises.

    Found by the benchmark: a run did all its work, wrote its files, and then
    died on `json.dumps` because the answer contained `→`. Exit code 1, nothing
    on stdout, and no sign that the task had actually been done. An em dash, a
    Persian word or an emoji does it just as well.
    """
    config = scripted([Script(text="Renamed foo → bar. Cost: €3 — done ✅")])

    code = cli.run_headless(config, run(config, json=True))

    assert code == 0
    report = json.loads(capsys.readouterr().out)
    assert "→" in report["text"]


def test_a_run_that_used_nothing_says_so_rather_than_omitting_it(scripted):
    config = scripted([Script(text="No tools needed.")])

    out = io.StringIO()
    with redirect_stdout(out):
        cli.run_headless(config, run(config, json=True))

    report = json.loads(out.getvalue())
    assert report["tools"] == [], "an empty list and a missing key are not the same"


def test_the_headless_json_carries_the_clarification_outcome(scripted):
    """A decision is still needed; the JSON says so, with the structured
    outcome and the partial work, and the exit code is distinct from both
    success and failure (T130, T131; FR-121, FR-123)."""
    config = scripted([Script(text="One thing first.", tool_calls=[a_question()])])

    out = io.StringIO()
    with redirect_stdout(out):
        code = cli.run_headless(config, run(config, json=True))

    report = json.loads(out.getvalue())
    assert report["stopped"] == "clarification_required"
    assert report["ok"] is False
    assert report["clarification"]["outcome"] == "unattended"
    assert report["clarification"]["decision"] == "Which framework?"
    assert report["tool_calls"] == 1, "partial work is preserved"
    assert code == 3, "distinct from success (0) and error (1)"


def test_a_dismissed_question_is_not_a_cancelled_turn(scripted):
    """`stopped: "cancelled"` keeps its turn-level meaning; a dismissed
    question never emits it (contracts §C2; FR-035)."""
    config = scripted([Script(text="One thing first.", tool_calls=[a_question()])])
    out = io.StringIO()
    with redirect_stdout(out):
        cli.run_headless(config, run(config, json=True))
    report = json.loads(out.getvalue())
    assert report["stopped"] != "cancelled"


# --------------------------------------------------------------------------- #
# the interface is not a cost the headless paths pay
# --------------------------------------------------------------------------- #

#: Modules that belong to drawing or reading a terminal. A headless run has no
#: terminal to draw on; loading these would be work with nothing to show for
#: it, and — for the launcher — a Bun requirement on a command that never
#: starts Bun.
#:
#: `comodor.transport.commands` is not on the list on purpose: building the
#: parser registers `core` and `tui-v2` from it, the way every subcommand
#: module is imported to register itself, and everything it needs to actually
#: launch — the renderer lookup, Bun, the spawn — is imported inside `run_tui`.
INTERFACE_ONLY = (
    "comodor.tui.runtime",          # where the packaged renderer is and whether it runs
    "comodor.terminal.chooser",     # the interactive picker
    "comodor.terminal.reader",      # raw key reading
    "comodor.terminal.keys",
)


@pytest.mark.parametrize("argv", [["--version"], ["--help"]])
def test_the_quick_commands_do_not_load_the_interface(argv, tmp_path):
    """`comodor --version` is answered without touching a renderer or a key
    reader. Measured in a fresh interpreter, because the test process has
    already imported half the package."""
    import os
    import subprocess
    import sys

    probe = (
        "import sys, comodor.cli as cli\n"
        "try:\n"
        f"    cli.main({argv!r})\n"
        "except SystemExit:\n"
        "    pass\n"
        "loaded = [name for name in sys.modules if name in "
        f"{INTERFACE_ONLY!r}]\n"
        "print('LOADED:' + ','.join(loaded))\n"
    )
    environment = dict(os.environ, COMODOR_HOME=str(tmp_path / "home"),
                       PYTHONIOENCODING="utf-8")
    done = subprocess.run([sys.executable, "-c", probe], capture_output=True,
                          text=True, encoding="utf-8", env=environment,
                          cwd=str(tmp_path), timeout=60)
    assert done.returncode == 0, done.stderr
    marker = [line for line in done.stdout.splitlines() if line.startswith("LOADED:")]
    assert marker, done.stdout
    assert marker[0] == "LOADED:", f"{argv} loaded {marker[0][7:]}"


def test_a_headless_run_does_not_load_the_interface(tmp_path):
    """`comodor run` answers through the core alone.

    A fresh interpreter, driven the way a script drives it — `--demo` so the
    scripted provider answers and nothing reaches a network — because the
    test process itself has long since imported the picker for other tests.
    """
    import os
    import subprocess
    import sys

    probe = (
        "import sys, comodor.cli as cli\n"
        "code = cli.main(['--demo', 'run', 'say hi', '--json', '--yes'])\n"
        "loaded = [name for name in sys.modules if name in "
        f"{INTERFACE_ONLY!r}]\n"
        "print('LOADED:' + ','.join(loaded))\n"
        "raise SystemExit(code)\n"
    )
    environment = dict(os.environ, COMODOR_HOME=str(tmp_path / "home"),
                       PYTHONIOENCODING="utf-8", COMODOR_OFFLINE="1")
    (tmp_path / "project").mkdir()
    done = subprocess.run([sys.executable, "-c", probe], capture_output=True,
                          text=True, encoding="utf-8", env=environment,
                          cwd=str(tmp_path / "project"), timeout=120)
    assert done.returncode == 0, done.stderr
    marker = [line for line in done.stdout.splitlines() if line.startswith("LOADED:")]
    assert marker, done.stdout
    assert marker[0] == "LOADED:", f"a headless run loaded {marker[0][7:]}"


# --------------------------------------------------------------------------- #
# scripted interactions: the user side of a clarification, automated (T149,
# T150). The form, the lifecycle and the outcome are the product's; only the
# person's reply is scripted.
# --------------------------------------------------------------------------- #


def test_a_scripted_answer_resumes_the_work(scripted):
    config = scripted([
        Script(text="One thing first.", tool_calls=[a_question()]),
        Script(text="Flask it is."),
    ])

    code = cli.run_headless(config, run(
        config, interactions=json.dumps([{"action": "answer", "value": "Flask"}])))

    assert code == 0
    assert scripted.providers, "the run should have built a gateway"
    replies = [message.content for call in scripted.providers[0].calls
               for message in call]
    assert any("Flask" in reply for reply in replies), "the answer never reached the model"


def test_a_scripted_cancellation_needs_a_decision_not_a_cancelled_turn(scripted):
    config = scripted([Script(text="One thing first.", tool_calls=[a_question()])])

    out = io.StringIO()
    with redirect_stdout(out):
        code = cli.run_headless(config, run(
            config, json=True, interactions=json.dumps(["cancel"])))

    report = json.loads(out.getvalue())
    assert report["stopped"] == "clarification_required"
    assert report["stopped"] != "cancelled"
    assert report["clarification"]["outcome"] == "cancelled"
    assert code == 3


def test_a_scripted_expiry_is_distinct_from_cancellation(scripted):
    config = scripted([Script(text="One thing first.", tool_calls=[a_question()])])

    out = io.StringIO()
    with redirect_stdout(out):
        cli.run_headless(config, run(
            config, json=True, interactions=json.dumps(["expire"])))

    report = json.loads(out.getvalue())
    assert report["stopped"] == "clarification_required"
    assert report["clarification"]["outcome"] == "expired"
    assert report["clarification"]["outcome"] != "cancelled"


def test_an_unscripted_form_is_still_unattended(scripted):
    """The old behaviour is unchanged: no script means nobody is there."""
    config = scripted([Script(text="One thing first.", tool_calls=[a_question()])])

    out = io.StringIO()
    with redirect_stdout(out):
        cli.run_headless(config, run(config, json=True))

    report = json.loads(out.getvalue())
    assert report["clarification"]["outcome"] == "unattended"


def test_a_cancelled_or_expired_run_invents_no_value(scripted):
    """Neither dismissal nor expiry becomes a chosen default."""
    for action in ("cancel", "expire", "unattended"):
        config = scripted([
            Script(text="One thing first.", tool_calls=[a_question()]),
            Script(text="Flask it is."),
        ])
        out = io.StringIO()
        with redirect_stdout(out):
            code = cli.run_headless(config, run(
                config, json=True, interactions=json.dumps([action])))
        report = json.loads(out.getvalue())
        assert code == 3
        assert report["ok"] is False
        replies = [message.content for call in scripted.providers[0].calls
                   for message in call]
        assert not any("Flask it is" in reply for reply in replies), (
            f"the second script ran under {action}: dependent work resumed")


def test_the_json_usage_reports_cache_creation_tokens(scripted):
    """A provider that bills cache creation reports it; the payload carries it
    so a benchmark total does not understate what the model read."""
    config = scripted([Script(text="Done.")])
    out = io.StringIO()
    with redirect_stdout(out):
        cli.run_headless(config, run(config, json=True))
    report = json.loads(out.getvalue())
    assert "written_tokens" in report["usage"]
