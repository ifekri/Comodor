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

    assert code == 0
    assert elapsed < 15.0, f"the run waited {elapsed:.0f}s for an answer"


def test_the_model_is_told_to_carry_on_rather_than_ask_again(scripted):
    """The tool already has the right words for an unfilled form. What matters
    is that the model is handed them, rather than a timeout and no explanation."""
    config = scripted([
        Script(text="One thing first.", tool_calls=[a_question()]),
        Script(text="Flask it is."),
    ])

    cli.run_headless(config, run(config))

    assert scripted.providers, "the run should have built a gateway"
    replies = [message.content for call in scripted.providers[0].calls
               for message in call]
    assert any("closed the form without answering" in reply for reply in replies), \
        f"the model was never told the form came back empty: {replies}"


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
