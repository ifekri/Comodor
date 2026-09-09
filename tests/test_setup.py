"""First-run setup and the JSON configuration it writes.

The wizard is the first thing a new user meets, and the config file is the only
thing they are ever asked to own. Both are driven here without a terminal: the
prompts are injected, so the whole flow — questions, answers, what lands on
disk, what comes back on the next start — runs in the suite.
"""

from __future__ import annotations

import io
import json
import os
import re
import stat

import pytest
from rich.console import Console

from comodor import catalogue
from comodor.config import Config, load
from comodor.onboarding import Check, Step
from comodor.paths import Paths
from comodor.setup import Answers, SetupWizard


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    """Nothing in this suite may reach the internet.

    Two different guards, on purpose. Constructing a GitHub connector is an
    isolation bug and fails the test on the spot — a deterministic test that
    wanders into the browser flow used to discover it only after a
    five-minute network timeout. The provider probe, by contrast, is a
    legitimate thing for the wizard to attempt and a legitimate thing to fail:
    it is made to fail offline here, which is the outcome every fallback test
    in this file was always relying on, without depending on what the network
    happens to be doing.
    """
    def forbidden(*_args, **_kwargs):
        raise AssertionError(
            "this test reached the network by constructing a GitHub connector")

    monkeypatch.setattr("comodor.github.connect.Connector", forbidden)

    def unreachable(*_args, **_kwargs):
        raise OSError("offline: model discovery is refused in this suite")

    monkeypatch.setattr("comodor.providers.gateway.build_provider", unreachable)
    return None


@pytest.fixture
def blank(tmp_path):
    """A config with nothing set up yet, pointed at a temporary home."""
    config = Config(paths=Paths(user=tmp_path / "home", project=tmp_path / "project"))
    (tmp_path / "project").mkdir(parents=True, exist_ok=True)
    from comodor.config import _build_providers

    config.providers = _build_providers()
    return config


def wizard(config, answers: list[str], key: str = "test-key-0123456789",
           github: str | None = None):
    """A wizard whose questions are answered from a list.

    The GitHub question is deliberately not one of that list's positions. It is
    answered by what it is — skip, unless the test says otherwise — because a
    reply stream is positional and the flow is not: inserting a step must not
    be able to turn a leftover "1" into "connect to GitHub", which is a real
    browser, a real worker and a real network, from a test about something
    else entirely.
    """
    replies = iter(answers)
    holder: dict = {}

    def prompt(message: str) -> str:
        plan = holder.get("plan")
        if plan is not None and plan.step is Step.GITHUB:
            return github if github is not None else ""
        return next(replies, "")

    made = SetupWizard(
        config,
        console=Console(file=io.StringIO(), width=90, force_terminal=False),
        prompt=prompt,
        secret=lambda message: key,
    )
    holder["plan"] = made.plan
    return made


# --------------------------------------------------------------------------- #
# the catalogue
# --------------------------------------------------------------------------- #


def test_the_catalogue_offers_the_providers_people_actually_use():
    ids = {spec.id for spec in catalogue.offered()}
    for expected in ("openrouter", "anthropic", "openai", "google", "deepseek",
                     "groq", "mistral", "xai", "ollama"):
        assert expected in ids, f"{expected} is missing from the catalogue"


def test_every_provider_entry_is_complete_enough_to_use():
    for spec in catalogue.CATALOGUE:
        assert spec.label and spec.blurb, spec.id

        # Two providers have no address and no default, for reasons rather than
        # by omission. `custom` is whatever URL the user types. `local` runs a
        # model from this disk on a port chosen when the server starts, so a URL
        # written here would be a number that is wrong the next time — and it
        # has no default model because nothing is downloaded until somebody
        # picks one.
        if spec.id in ("custom", "local"):
            assert not spec.base_url, f"{spec.id} should carry no URL"
            continue
        assert spec.base_url.startswith("http"), spec.id
        assert spec.default_model, spec.id
        if spec.needs_key:
            assert spec.keys_url.startswith("http"), f"{spec.id} has no key page"


def test_local_providers_need_no_key():
    for spec in catalogue.local():
        assert not spec.needs_key
        # Ollama and LM Studio are servers somebody already runs, so they have
        # a well-known address. `local` is a model Comodor downloads and starts
        # itself, on a port picked at startup — being local is what these have
        # in common, not being at a fixed URL.
        if spec.id == "local":
            assert not spec.base_url
            continue
        assert "localhost" in spec.base_url


# --------------------------------------------------------------------------- #
# the wizard
# --------------------------------------------------------------------------- #


def test_a_full_first_run_configures_a_provider(blank, monkeypatch):
    monkeypatch.setattr(SetupWizard, "_discover_models",
                        lambda self, spec, answers: ["gpt-4o", "gpt-4o-mini"])

    setup = wizard(blank, ["3", "2", "1", ""])   # openai, model, ask-first, no bot
    answers = setup.run()

    assert answers.provider == "openai"
    assert answers.model == "gpt-4o-mini"
    assert answers.api_key == "test-key-0123456789"
    assert answers.approvals == "ask"


def test_pressing_enter_takes_the_default(blank, monkeypatch):
    monkeypatch.setattr(SetupWizard, "_discover_models",
                        lambda self, spec, answers: ["a-model"])
    answers = wizard(blank, ["", "", "", ""]).run()

    assert answers.provider == catalogue.offered()[0].id
    assert answers.model == "a-model"
    assert answers.approvals == "ask"


def test_a_bad_choice_is_re_asked_rather_than_defaulted(blank, monkeypatch):
    """Falling through to a default the user did not pick is worse than asking."""
    monkeypatch.setattr(SetupWizard, "_discover_models",
                        lambda self, spec, answers: ["a-model"])
    answers = wizard(blank, ["999", "banana", "2", "", "", ""]).run()

    assert answers.provider == catalogue.offered()[1].id


def test_a_local_provider_skips_the_key_question(blank, monkeypatch):
    monkeypatch.setattr(SetupWizard, "_discover_models",
                        lambda self, spec, answers: ["llama3.3"])

    index = [spec.id for spec in catalogue.offered()].index("ollama") + 1
    setup = wizard(blank, [str(index), "1", "1", ""], key="should-not-be-asked")
    answers = setup.run()

    assert answers.provider == "ollama"
    assert answers.api_key == ""


def test_the_answers_are_applied_and_saved(blank, monkeypatch):
    monkeypatch.setattr(SetupWizard, "_discover_models",
                        lambda self, spec, answers: ["gpt-4o"])
    setup = wizard(blank, ["3", "1", "2", ""])   # openai, gpt-4o, writes-allowed
    saved = setup.apply(setup.run(minimal=False))

    assert saved.provider == "openai"
    assert saved.active_model() == "gpt-4o"
    assert saved.providers["openai"].configured
    assert saved.safety.auto_approve_writes is True
    assert saved.safety.auto_approve_shell is False
    assert saved.paths.config_file.exists()


def test_approval_choices_map_to_the_safety_settings(blank, monkeypatch):
    monkeypatch.setattr(SetupWizard, "_discover_models",
                        lambda self, spec, answers: ["m"])
    for choice, writes, shell in (("1", False, False), ("2", True, False),
                                  ("3", True, True)):
        setup = wizard(blank, ["3", "1", choice, ""])
        saved = setup.apply(setup.run(minimal=False))
        assert (saved.safety.auto_approve_writes,
                saved.safety.auto_approve_shell) == (writes, shell)


def test_a_custom_endpoint_can_be_supplied(blank, monkeypatch):
    monkeypatch.setattr(SetupWizard, "_discover_models",
                        lambda self, spec, answers: [])

    index = [spec.id for spec in catalogue.offered()].index("custom") + 1
    setup = wizard(blank, [str(index), "https://llm.internal/v1", "my-model", "1", ""])
    saved = setup.apply(setup.run())

    assert saved.providers["custom"].base_url == "https://llm.internal/v1"
    assert saved.active_model() == "my-model"


def test_model_discovery_falls_back_when_the_provider_cannot_be_reached(
        blank, monkeypatch):
    """A wizard that hangs or crashes on a bad key would be unusable.

    The provider is never reached: `build_provider` is replaced, because a test
    that discovered models by calling a real API would fail on a machine with
    no network and pass on one with a warm cache — and would spend somebody's
    quota proving that a list came back.
    """
    def unreachable(*_args, **_kwargs):
        raise OSError("the network is not there")

    monkeypatch.setattr("comodor.providers.gateway.build_provider", unreachable)

    setup = wizard(blank, [])
    setup.plan.start()
    setup.plan.choose_provider("openai")

    spec = catalogue.get("openai")
    models = setup._discover_models(spec, Answers(provider="openai"))

    assert models, "the known list should stand in when the API says nothing"
    assert set(models) <= set(spec.models)
    # And the plan is told the difference between "these are its models" and
    # "we could not ask", which is what stops an unverified list being
    # presented as a working provider.
    assert setup.plan.validation.check is Check.UNREACHABLE
    assert "reach" in setup.plan.validation.reason.lower()


# --------------------------------------------------------------------------- #
# a refused credential, corrected in place
#
# The P1 defect: an authentication failure used to fall through to the
# catalogue model list, so the wizard walked on to GitHub and Ready and only
# then died at `commit` — a dead end at the bottom of the flow instead of a
# correction at the point of the refusal. These drive the real wizard with a
# scripted probe (no network, no timing) and answer by plan state, because the
# correction screen inserts a `_choose` between the key and the model and a
# positional reply stream would drift onto it.
# --------------------------------------------------------------------------- #

FAKE_KEY = "sk-test-DO-NOT-WRITE-THIS-ANYWHERE-0123456789"


class ScriptedProbe:
    """A provider probe whose `list_models` replays scripted outcomes.

    Each call pops the next outcome: an exception to raise (classified by the
    real `classify_probe`, so INVALID is proved against the exception type the
    providers actually raise) or a list of models to return. INVALID-then-VALID
    is driven by order, with no network and no sleeps.
    """

    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.probes = 0

    def list_models(self):
        self.probes += 1
        outcome = self.outcomes.pop(0) if self.outcomes else []
        if isinstance(outcome, BaseException):
            raise outcome
        return list(outcome)

    def close(self):
        pass


def refused():
    from comodor.providers.base import AuthError

    return AuthError("invalid_api_key")


def credential_wizard(config, *, secrets, outcomes, corrections, providers,
                      model_reply="1", github_reply="2"):
    """A wizard driven by plan state through a credential correction.

    `secrets` answers the masked key prompts in order, `corrections` answers
    the correction screen (replace/retry/back/cancel by number), and
    `providers` names the provider to pick each time the provider question is
    asked — "back" re-asks it, so it is a queue rather than a single value.
    """
    probe = ScriptedProbe(outcomes)
    secret_replies = iter(secrets)
    correction_replies = iter(corrections)
    provider_replies = iter(providers)
    holder: dict = {}

    def prompt(message: str) -> str:
        plan = holder.get("plan")
        step = plan.step if plan is not None else None
        if step is Step.PROVIDER:
            wanted = next(provider_replies, providers[-1])
            return str([fact.id for fact in plan.facts].index(wanted) + 1)
        if step is Step.CREDENTIAL and plan.validation.check is Check.INVALID:
            return next(correction_replies, "")
        if step is Step.MODEL:
            return model_reply
        if step is Step.GITHUB:
            return github_reply
        return ""

    made = SetupWizard(
        config,
        console=Console(file=io.StringIO(), width=90, force_terminal=False),
        prompt=prompt,
        secret=lambda message: next(secret_replies, ""),
    )
    holder["plan"] = made.plan
    made._probe = probe                     # so a test can assert on it
    return made, probe


def test_a_refused_credential_is_corrected_in_place(blank, monkeypatch):
    made, probe = credential_wizard(
        blank, secrets=["sk-bad", FAKE_KEY],
        outcomes=[refused(), ["gpt-4o", "gpt-4o-mini"]],
        corrections=["1"], providers=["openai"])          # 1 = replace
    monkeypatch.setattr("comodor.providers.gateway.build_provider",
                        lambda entry, *a, **k: probe)

    answers = made.run()
    saved = made.apply(answers)

    drawn = made.console.file.getvalue()
    assert "That credential was refused" in drawn
    assert saved.provider == "openai"
    assert saved.active_model() == "gpt-4o"
    assert saved.providers["openai"].api_key == FAKE_KEY
    assert probe.probes == 2, "the replacement key was proved before advancing"


def test_a_replacement_that_is_refused_again_stays_recoverable(blank, monkeypatch):
    made, probe = credential_wizard(
        blank, secrets=["sk-bad-1", "sk-bad-2", FAKE_KEY],
        outcomes=[refused(), refused(), ["gpt-4o"]],
        corrections=["1", "1"], providers=["openai"])
    monkeypatch.setattr("comodor.providers.gateway.build_provider",
                        lambda entry, *a, **k: probe)

    saved = made.apply(made.run())

    assert saved.active_model() == "gpt-4o"
    assert saved.providers["openai"].api_key == FAKE_KEY
    assert probe.probes == 3


def test_retrying_a_refused_credential_proves_the_same_key(blank, monkeypatch):
    """A refusal can be the provider's bad minute. Retry must not cost the
    key: it is asked again with the credential the plan already holds."""
    made, probe = credential_wizard(
        blank, secrets=[FAKE_KEY], outcomes=[refused(), ["gpt-4o"]],
        corrections=["2"], providers=["openai"])          # 2 = retry
    monkeypatch.setattr("comodor.providers.gateway.build_provider",
                        lambda entry, *a, **k: probe)

    saved = made.apply(made.run())

    assert saved.active_model() == "gpt-4o"
    assert saved.providers["openai"].api_key == FAKE_KEY
    assert probe.probes == 2


def test_back_from_a_refused_credential_returns_to_the_provider(blank, monkeypatch):
    made, probe = credential_wizard(
        blank, secrets=["sk-bad"], outcomes=[refused(), ["qwen2.5-coder"]],
        corrections=["3"], providers=["openai", "ollama"])  # 3 = back
    monkeypatch.setattr("comodor.providers.gateway.build_provider",
                        lambda entry, *a, **k: probe)

    saved = made.apply(made.run())

    assert saved.provider == "ollama", "back reached the provider list"
    assert saved.active_model() == "qwen2.5-coder"


def test_cancel_during_correction_leaves_the_working_config_untouched(
        blank, monkeypatch):
    """Reconfiguring a working machine, then cancelling at the refusal, must
    leave the configuration that was already usable exactly as it was."""
    blank.use("ollama", model="already-working")
    blank.save()
    good = blank.paths.config_file.read_text(encoding="utf-8")

    made, probe = credential_wizard(
        blank, secrets=["sk-bad"], outcomes=[refused()],
        corrections=["4"], providers=["openai"])          # 4 = cancel
    monkeypatch.setattr("comodor.providers.gateway.build_provider",
                        lambda entry, *a, **k: probe)

    with pytest.raises(KeyboardInterrupt):
        made.run()

    assert blank.paths.config_file.read_text(encoding="utf-8") == good
    assert "sk-bad" not in blank.paths.config_file.read_text(encoding="utf-8")


# --------------------------------------------------------------------------- #
# resuming an interrupted setup, in the real wizard
#
# A checkpoint is only a recovery if the terminal setup path actually consumes
# it. These drive a real SetupWizard: make progress, interrupt, then prove a
# fresh wizard offers to continue and picks up mid-flow rather than from
# provider zero. The resume offer happens before `plan.start()`, so it is the
# one moment `plan.step is PROVIDER` with `plan.facts` still empty — which is
# how the harness tells it apart from the real provider question.
# --------------------------------------------------------------------------- #

OLLAMA_MODELS = ["qwen2.5-coder:14b"]


def resume_wizard(config, outcomes, *, resume_reply, provider,
                  model_reply="1", github_reply="2",
                  interrupt_at_github=False):
    probe = ScriptedProbe(outcomes)
    asked: list[str] = []
    holder: dict = {}

    def prompt(message: str) -> str:
        plan = holder.get("plan")
        step = plan.step if plan is not None else None
        if step is Step.PROVIDER and not plan.facts:
            asked.append("resume")
            return resume_reply
        if step is Step.PROVIDER:
            asked.append("provider")
            return str([fact.id for fact in plan.facts].index(provider) + 1)
        if step is Step.MODEL:
            asked.append("model")
            return model_reply
        if step is Step.GITHUB:
            asked.append("github")
            if interrupt_at_github:
                raise KeyboardInterrupt
            return github_reply
        asked.append(str(step))
        return ""

    made = SetupWizard(
        config,
        console=Console(file=io.StringIO(), width=90, force_terminal=False),
        prompt=prompt,
        secret=lambda message: "",
    )
    holder["plan"] = made.plan
    return made, probe, asked


def _interrupt_a_run(blank, monkeypatch, provider="ollama",
                     outcomes=(OLLAMA_MODELS, OLLAMA_MODELS)):
    """Make non-secret progress, then stop at the GitHub question."""
    from comodor.onboarding import checkpoint_path

    made, probe, _ = resume_wizard(blank, list(outcomes), resume_reply="1",
                                   provider=provider, interrupt_at_github=True)
    monkeypatch.setattr("comodor.providers.gateway.build_provider",
                        lambda entry, *a, **k: probe)
    with pytest.raises(KeyboardInterrupt):
        made.run()
    assert checkpoint_path(blank).exists(), "progress was not saved"
    return probe


def test_an_interrupted_setup_resumes_in_the_real_wizard(blank, monkeypatch):
    from comodor.onboarding import checkpoint_path

    _interrupt_a_run(blank, monkeypatch)
    body = json.loads(checkpoint_path(blank).read_text(encoding="utf-8"))
    assert body["provider"] == "ollama"
    assert body["model"] == "qwen2.5-coder:14b"

    made2, probe2, asked2 = resume_wizard(blank, [OLLAMA_MODELS],
                                          resume_reply="1", provider="ollama")
    monkeypatch.setattr("comodor.providers.gateway.build_provider",
                        lambda entry, *a, **k: probe2)
    saved = made2.apply(made2.run())

    assert "resume" in asked2, "the resume offer was not made"
    assert "provider" not in asked2, "it restarted from the provider question"
    assert "model" not in asked2, "it re-asked a model already chosen"
    assert probe2.probes == 0, "it re-discovered models on resume"
    assert saved.provider == "ollama"
    assert saved.active_model() == "qwen2.5-coder:14b"
    assert not checkpoint_path(blank).exists(), "the checkpoint was not cleared"


def test_starting_over_from_a_checkpoint_begins_fresh(blank, monkeypatch):
    from comodor.onboarding import checkpoint_path

    _interrupt_a_run(blank, monkeypatch)
    assert checkpoint_path(blank).exists()

    made2, probe2, asked2 = resume_wizard(blank, [OLLAMA_MODELS, OLLAMA_MODELS],
                                          resume_reply="2", provider="ollama")
    monkeypatch.setattr("comodor.providers.gateway.build_provider",
                        lambda entry, *a, **k: probe2)
    saved = made2.apply(made2.run())

    assert "resume" in asked2
    assert "provider" in asked2, "start over must ask the provider again"
    assert probe2.probes == 1, "start over rediscovers rather than restoring"
    assert saved.provider == "ollama"
    assert not checkpoint_path(blank).exists()


def test_cancelling_at_the_resume_offer_leaves_the_config_untouched(
        blank, monkeypatch):
    """A working machine, an interrupted reconfiguration, then Cancel at the
    resume offer: the configuration that was already usable stays exactly as it
    was, and the staged reconfiguration is never written."""
    blank.use("ollama", model="already-working")
    blank.save()
    good = blank.paths.config_file.read_text(encoding="utf-8")

    # Reconfigure toward LM Studio, interrupted at GitHub. LM Studio needs no
    # key, so the interruption is about the flow, not a credential.
    _interrupt_a_run(blank, monkeypatch, provider="lmstudio",
                     outcomes=(["llama3.3"], ["llama3.3"]))
    assert blank.paths.config_file.read_text(encoding="utf-8") == good, \
        "the interrupted run wrote to the configuration"

    made2, _, asked2 = resume_wizard(blank, [["llama3.3"]], resume_reply="3",
                                     provider="lmstudio")   # 3 = cancel
    with pytest.raises(KeyboardInterrupt):
        made2.run()

    assert "resume" in asked2
    assert blank.paths.config_file.read_text(encoding="utf-8") == good


# --------------------------------------------------------------------------- #
# the config file
# --------------------------------------------------------------------------- #


def test_the_saved_file_is_json_and_round_trips(blank, monkeypatch):
    monkeypatch.setattr(SetupWizard, "_discover_models",
                        lambda self, spec, answers: ["gpt-4o"])
    setup = wizard(blank, ["3", "1", "1", ""])
    saved = setup.apply(setup.run())

    document = json.loads(saved.paths.config_file.read_text(encoding="utf-8"))
    assert document["provider"] == "openai"
    assert document["providers"]["openai"]["api_key"] == "test-key-0123456789"

    reloaded = load(cwd=saved.paths.project, use_environment=False)
    reloaded.paths = saved.paths
    reloaded = load(cwd=saved.paths.project, use_environment=False)
    assert isinstance(document["agent"], dict)
    assert document["version"] >= 1


def test_reloading_finds_the_saved_provider(blank, monkeypatch, tmp_path):
    monkeypatch.setenv("COMODOR_HOME", str(tmp_path / "home"))
    monkeypatch.setattr(SetupWizard, "_discover_models",
                        lambda self, spec, answers: ["gpt-4o"])

    setup = wizard(blank, ["3", "1", "1", ""])
    setup.apply(setup.run())

    fresh = load(cwd=tmp_path / "project", use_environment=False)
    assert fresh.provider == "openai"
    assert fresh.active_model() == "gpt-4o"
    assert not fresh.needs_setup
    assert not fresh.first_run


def test_a_missing_config_asks_for_setup(tmp_path, monkeypatch):
    monkeypatch.setenv("COMODOR_HOME", str(tmp_path / "nothing-here"))
    config = load(cwd=tmp_path, use_environment=False)

    assert config.first_run
    assert config.needs_setup


def test_a_corrupt_config_does_not_stop_the_program(tmp_path, monkeypatch):
    """Defaults must carry the run; `doctor` reports the file separately."""
    home = tmp_path / "home"
    home.mkdir(parents=True)
    (home / "config.json").write_text("{ this is not json", encoding="utf-8")
    monkeypatch.setenv("COMODOR_HOME", str(home))

    config = load(cwd=tmp_path, use_environment=False)
    assert config.agent.mode == "act"


def test_the_config_file_is_not_world_readable(blank, monkeypatch):
    monkeypatch.setattr(SetupWizard, "_discover_models",
                        lambda self, spec, answers: ["gpt-4o"])
    setup = wizard(blank, ["3", "1", "1", ""])
    saved = setup.apply(setup.run())

    if os.name == "nt":
        pytest.skip("POSIX permissions do not apply on Windows")
    mode = stat.S_IMODE(saved.paths.config_file.stat().st_mode)
    assert mode & (stat.S_IRGRP | stat.S_IROTH) == 0, "the file holds an API key"


def test_no_temporary_file_is_left_behind(blank, monkeypatch):
    monkeypatch.setattr(SetupWizard, "_discover_models",
                        lambda self, spec, answers: ["gpt-4o"])
    setup = wizard(blank, ["3", "1", "1", ""])
    saved = setup.apply(setup.run())

    leftovers = list(saved.paths.user.glob("*.tmp"))
    assert leftovers == []


def test_a_project_config_can_pin_settings_without_carrying_a_key(tmp_path, monkeypatch):
    home = tmp_path / "home"
    project = tmp_path / "project"
    (project / ".comodor").mkdir(parents=True)
    home.mkdir(parents=True)
    (project / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")

    (home / "config.json").write_text(json.dumps({
        "provider": "openai",
        "providers": {"openai": {"api_key": "sk-user", "configured": True}},
    }), encoding="utf-8")
    (project / ".comodor" / "config.json").write_text(json.dumps({
        "agent": {"mode": "plan", "max_steps": 5},
    }), encoding="utf-8")
    monkeypatch.setenv("COMODOR_HOME", str(home))

    config = load(cwd=project, use_environment=False)
    assert config.agent.mode == "plan"
    assert config.agent.max_steps == 5
    assert config.providers["openai"].api_key == "sk-user"


def test_environment_variables_still_win_for_ci(tmp_path, monkeypatch):
    monkeypatch.setenv("COMODOR_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("OPENAI_API_KEY", "sk-from-the-environment")

    config = load(cwd=tmp_path, use_environment=True)
    assert config.providers["openai"].api_key == "sk-from-the-environment"
    assert not config.needs_setup


def test_use_selects_and_configures_in_one_step():
    config = Config()
    from comodor.config import _build_providers

    config.providers = _build_providers()
    config.use("groq", api_key="gsk-x", model="llama-3.3-70b-versatile")

    assert config.provider == "groq"
    assert config.active_model() == "llama-3.3-70b-versatile"
    assert config.providers["groq"].configured
    assert not config.needs_setup


def test_an_unconfigured_local_provider_is_not_chosen_silently():
    """Ollama is 'ready' without a key, but only if the user asked for it."""
    config = Config()
    from comodor.config import _build_providers

    config.providers = _build_providers()
    assert config.needs_setup, "a fresh install has nothing selectable"

    config.use("ollama")
    assert not config.needs_setup


# --------------------------------------------------------------------------- #
# taking several skills
#
# The question offered a library and took exactly one thing out of it. Somebody
# setting up for a Python project wants the review skill and the test skill,
# and the list had no way to say so.
# --------------------------------------------------------------------------- #

THREE = [("a", "a", ""), ("b", "b", ""), ("c", "c", "")]


def test_the_numbered_form_takes_several(blank):
    """No terminal to take over, and the question still has to accept more
    than one answer — the wizard runs in pipes, in tests and under curl | sh."""
    assert wizard(blank, ["1, 3"])._choose_many(THREE, title="Skills") == ["a", "c"]


def test_spaces_work_as_well_as_commas(blank):
    assert wizard(blank, ["2 3"])._choose_many(THREE) == ["b", "c"]


def test_an_empty_answer_is_none_of_them(blank):
    """What the "None for now" row used to be for."""
    assert wizard(blank, [""])._choose_many(THREE) == []


def test_a_number_that_is_not_on_the_list_is_asked_again(blank):
    """Not taken as a default. A silent wrong choice here is one the user has
    to undo later, having never been told it happened."""
    assert wizard(blank, ["9", "nonsense", "2"])._choose_many(THREE) == ["b"]


def test_the_same_number_twice_is_one_skill(blank):
    assert wizard(blank, ["1,1,2"])._choose_many(THREE) == ["a", "b"]


def test_they_come_back_in_the_order_they_were_offered(blank):
    """However they were typed. The list on screen is what a reader
    remembers, and a summary in another order reads as a mistake."""
    assert wizard(blank, ["3,1"])._choose_many(THREE) == ["a", "c"]


def test_every_chosen_skill_is_installed(blank, monkeypatch):
    """The loop was already there and had never been handed more than one."""
    installed: list[str] = []

    class Entry:
        def __init__(self, name):
            self.id, self.description = name, ""

    class Catalogue:
        skills = [Entry("one"), Entry("two"), Entry("three")]

        def get(self, name):
            return next((s for s in self.skills if s.id == name), None)

    monkeypatch.setattr("comodor.skills.catalogue.fetch", lambda *a, **k: Catalogue())
    monkeypatch.setattr("comodor.skills.catalogue.install",
                        lambda entry, cat, root: installed.append(entry.id))

    done = wizard(blank, []).install_skills(blank, Answers(skills=["one", "three"]))

    assert installed == ["one", "three"]
    assert done == ["one", "three"]


def test_the_summary_names_every_skill_taken(blank, monkeypatch):
    """One line saying "3 skills" and another naming one of them would be the
    wizard disagreeing with itself about what it just did."""
    class Entry:
        def __init__(self, name):
            self.id, self.description = name, f"the {name} procedure"

    class Catalogue:
        skills = [Entry("one"), Entry("two"), Entry("three")]

    monkeypatch.setattr("comodor.skills.catalogue.fetch", lambda *a, **k: Catalogue())

    it = wizard(blank, ["1,3"])
    taken = it._ask_skills(1, 1)

    assert taken == ["one", "three"]
    assert ("skills", "one, three") in it._done


# --------------------------------------------------------------------------- #
# the phone
#
# The bot shipped and setup never mentioned it, so the only people who could
# find it were the ones already reading documentation for a feature they had
# no reason to look for.
# --------------------------------------------------------------------------- #


def test_the_wizard_asks_about_telegram(blank, monkeypatch):
    monkeypatch.setattr(SetupWizard, "_discover_models",
                        lambda self, spec, answers: ["a-model"])
    setup = wizard(blank, ["", "", "", ""])
    setup.run(minimal=False)

    printed = setup.console.file.getvalue()
    assert "Run it from your phone?" in printed
    assert "/7" in printed, "it is one of the steps, not an afterthought"


def test_declining_leaves_telegram_untouched(blank, monkeypatch):
    monkeypatch.setattr(SetupWizard, "_discover_models",
                        lambda self, spec, answers: ["a-model"])
    setup = wizard(blank, ["", "", "", "1"])
    answers = setup.run(minimal=False)
    config = setup.apply(answers)

    assert answers.telegram_token == ""
    assert config.telegram.token == ""
    assert config.telegram.enabled is False


def test_a_token_is_checked_before_it_is_believed(blank, monkeypatch):
    """A typo found days later looks like a broken feature, not a typo."""
    from comodor.telegram.api import Unauthorised

    monkeypatch.setattr(SetupWizard, "_discover_models",
                        lambda self, spec, answers: ["a-model"])
    monkeypatch.setattr("comodor.telegram.api.Bot.me",
                        lambda self: (_ for _ in ()).throw(Unauthorised("no")))

    setup = wizard(blank, ["", "", "", "2", "42:wrong"])
    answers = setup.run(minimal=False)

    assert answers.telegram_token == ""
    assert "refused that token" in setup.console.file.getvalue()


def test_a_good_token_is_kept_and_the_bot_is_named(blank, monkeypatch):
    monkeypatch.setattr(SetupWizard, "_discover_models",
                        lambda self, spec, answers: ["a-model"])
    monkeypatch.setattr("comodor.telegram.api.Bot.me",
                        lambda self: {"username": "comodor_bot",
                                      "first_name": "Comodor"})
    monkeypatch.setattr(SetupWizard, "_pair_now",
                        lambda self, token, username, answers: None)

    setup = wizard(blank, ["", "", "", "2", "42:right"])
    answers = setup.run(minimal=False)
    config = setup.apply(answers)

    assert answers.telegram_token == "42:right"
    assert config.telegram.token == "42:right"
    # Nobody paired, so nothing is listening. A bot that runs and answers
    # nobody looks broken; it is switched on by pairing, not by a token.
    assert config.telegram.enabled is False
    assert "comodor_bot" in setup.console.file.getvalue()


def test_pairing_switches_it_on(blank, monkeypatch):
    monkeypatch.setattr(SetupWizard, "_discover_models",
                        lambda self, spec, answers: ["a-model"])
    monkeypatch.setattr("comodor.telegram.api.Bot.me",
                        lambda self: {"username": "comodor_bot",
                                      "first_name": "Comodor"})

    def paired(self, token, username, answers):
        answers.telegram_allowed = [4242]

    monkeypatch.setattr(SetupWizard, "_pair_now", paired)

    setup = wizard(blank, ["", "", "", "2", "42:right"])
    config = setup.apply(setup.run(minimal=False))

    assert config.telegram.allowed == [4242]
    assert config.telegram.enabled is True


def test_an_abandoned_pairing_writes_no_token(blank):
    """Ctrl-C during pairing must not leave a setting nobody chose."""
    from comodor.setup import _pairing_config

    spare = _pairing_config(blank, "42:right")

    assert spare.telegram.token == "42:right"
    assert blank.telegram.token == ""
    assert blank.telegram.enabled is False


# --------------------------------------------------------------------------- #
# one screen per question
#
# Over a connection where raw key reading does not work, the wizard falls back
# to typed numbers — and it used to stop clearing the screen as well. Each
# question was printed under the last, and the skills question printed all 147
# entries with a paragraph of description each. Two capabilities, one of them
# failing, and the other went with it.
# --------------------------------------------------------------------------- #


class Screen(Console):
    """A console that is a terminal, and remembers where it was cleared."""

    def __init__(self, **kw):
        super().__init__(**kw)
        self.frames: list[list[str]] = [[]]

    @property
    def is_terminal(self) -> bool:
        return True

    def clear(self, home: bool = True) -> None:
        self.frames.append([])

    def print(self, *args, **kw):
        at = self.file.tell()
        super().print(*args, **kw)
        self.file.seek(at)
        self.frames[-1].extend(self.file.read().splitlines())


def a_whole_run(blank, width: int, height: int, replies: list[str]) -> Screen:
    """A full run for the screen tests: every question, offline.

    `minimal=False` because these tests are about the screens the full path
    draws — approvals, skills, telegram — which the first-run path skips. The
    GitHub question is answered by what it is rather than by its position in
    the stream, so a reply that used to mean "approvals: ask" cannot silently
    become "open a browser".
    """
    console = Screen(width=width, height=height, file=io.StringIO(),
                     no_color=True, legacy_windows=False)
    answers = iter(replies)
    holder: dict = {}

    def prompt(message: str) -> str:
        plan = holder.get("plan")
        if plan is not None and plan.step is Step.GITHUB:
            return "2"
        return next(answers, "")

    setup = SetupWizard(blank, console=console,
                        prompt=prompt,
                        secret=lambda message: "unused")
    holder["plan"] = setup.plan
    setup._discover_models = lambda spec, ans: [f"model-{n}" for n in range(40)]
    result = setup.run(minimal=False)
    setup.finish(setup.apply(result))
    return console


LONG = [(f"s{n}", f"skill-{n:03d}",
         "A description long enough to have been the problem. " * 8)
        for n in range(147)]


@pytest.mark.parametrize("width,height", [(100, 30), (80, 24), (120, 40),
                                          (90, 20), (76, 18)])
def test_no_step_of_the_typed_path_runs_past_the_bottom(blank, width, height,
                                                        monkeypatch):
    monkeypatch.setattr(SetupWizard, "_ask_skills",
                        lambda self, step, total: self._choose_many(
                            LONG, title="Skills", verb="install"))

    console = a_whole_run(blank, width, height,
                          ["17", "1", "1", "", "1", "1"])

    over = [(number, len(frame))
            for number, frame in enumerate(console.frames, start=1)
            if len(frame) > height]
    assert over == [], f"screens past the bottom of a {width}x{height}: {over}"


def test_each_question_gets_a_screen_of_its_own(blank):
    console = a_whole_run(blank, 100, 30, ["17", "1", "1", "", "1"])

    drawn = [frame for frame in console.frames
             if any(line.strip() for line in frame)]
    assert len(drawn) >= 6, "the questions are stacking rather than replacing"

    # And no screen carries two questions.
    for frame in drawn:
        titles = [line for line in frame if re.search(r"\s\d/\d\s", line)]
        assert len(titles) <= 1, f"two questions on one screen: {titles}"


def test_the_page_shrinks_as_the_recap_grows(blank):
    """The recap gains a line per answer, so a fixed allowance that fits the
    first question overflows the last — which is the skills one."""
    console = Screen(width=90, height=24, file=io.StringIO(), no_color=True,
                     legacy_windows=False)
    setup = SetupWizard(blank, console=console, prompt=lambda m: "",
                        secret=lambda m: "")

    empty = setup._chrome()
    setup._done = [("a", "1"), ("b", "2"), ("c", "3"), ("d", "4")]
    assert setup._chrome() == empty + 3, "the recap is not being counted"


def test_the_typed_path_still_clears_when_the_keyboard_does_not_work(blank):
    """Two capabilities. One failing must not cost the other."""
    console = Screen(width=90, height=24, file=io.StringIO(), no_color=True,
                     legacy_windows=False)
    setup = SetupWizard(blank, console=console, prompt=lambda m: "",
                        secret=lambda m: "")

    assert setup._keys is False, "an injected prompt means no raw keys"
    assert setup._terminal is True, "but it is still a terminal"

    before = len(console.frames)
    setup._rule("A question", 1, 6)
    assert len(console.frames) == before + 1


# --------------------------------------------------------------------------- #
# what happens when the questions are over
#
# Setup used to end by returning to the shell. Somebody answered six
# questions, watched it say `Ready.`, and was put back at a prompt with
# nothing running — and `comodor setup` is the command the installer calls, so
# that was the last thing an install did.
# --------------------------------------------------------------------------- #


def closing(blank, replies: list[str], *, paired: bool = False) -> tuple:
    if paired:
        blank.telegram.token = "42:x"
        blank.telegram.allowed = [7]
    console = Screen(width=90, height=26, file=io.StringIO(), no_color=True,
                     legacy_windows=False)
    answers = iter(replies)
    setup = SetupWizard(blank, console=console,
                        prompt=lambda message: next(answers, ""),
                        secret=lambda message: "unused")
    return setup, setup.offer_start(blank)


def test_the_last_screen_offers_to_start_it(blank):
    setup, chosen = closing(blank, ["1"])

    assert chosen == "interface"
    drawn = "\n".join(setup.console.frames[-1])
    assert "What now?" in drawn
    assert "Start Comodor" in drawn


def test_telegram_is_offered_only_when_there_is_a_bot_to_start(blank):
    """An option that cannot work is worse than an option that is not there."""
    without, _ = closing(blank, ["1"])
    assert "Telegram" not in "\n".join(without.console.frames[-1])

    fresh = Config(paths=blank.paths)
    with_bot, _ = closing(fresh, ["1"], paired=True)
    assert "Telegram" in "\n".join(with_bot.console.frames[-1])


@pytest.mark.parametrize("reply,expected", [("1", "interface"),
                                            ("2", "telegram"),
                                            ("3", "both"),
                                            ("4", "nothing")])
def test_each_answer_maps_to_what_it_says(blank, reply, expected):
    _, chosen = closing(blank, [reply], paired=True)
    assert chosen == expected


def test_the_closing_screen_carries_no_step_number(blank):
    """It is not one of the numbered questions, and labelling it 0/0 read as
    the bug it was."""
    setup, _ = closing(blank, ["1"])
    drawn = "\n".join(setup.console.frames[-1])

    assert "0/0" not in drawn
    assert "What now?" in drawn


def test_the_wizard_does_not_ask_unless_it_was_asked_to(blank, monkeypatch):
    """The path into the interface is already going there; asking somebody to
    confirm what they are visibly already doing is a question wasted. The path
    that ends at a shell prompt is the one that has to ask."""
    from comodor.setup import run_setup

    monkeypatch.setattr(SetupWizard, "run", lambda self: Answers())
    monkeypatch.setattr(SetupWizard, "apply", lambda self, answers: blank)
    monkeypatch.setattr(SetupWizard, "install_skills",
                        lambda self, config, answers: [])
    monkeypatch.setattr(SetupWizard, "finish", lambda self, config, closing=True: None)

    asked: list[int] = []
    monkeypatch.setattr(SetupWizard, "offer_start",
                        lambda self, config: asked.append(1) or "interface")

    quiet = run_setup(blank)
    assert asked == [], "it asked when it was not supposed to"
    assert quiet.start_after_setup == "nothing"

    loud = run_setup(blank, offer=True)
    assert asked == [1]
    assert loud.start_after_setup == "interface"


def test_choosing_a_bot_actually_starts_that_one(blank, monkeypatch):
    """Named by channel: "both" with only Telegram set up must not try to
    start a WhatsApp that was never connected."""
    from comodor.setup import run_setup

    blank.telegram.token = "42:x"
    blank.telegram.allowed = [7]

    monkeypatch.setattr(SetupWizard, "run", lambda self: Answers())
    monkeypatch.setattr(SetupWizard, "apply", lambda self, answers: blank)
    monkeypatch.setattr(SetupWizard, "install_skills",
                        lambda self, config, answers: [])
    monkeypatch.setattr(SetupWizard, "finish",
                        lambda self, config, closing=True: None)
    monkeypatch.setattr(SetupWizard, "offer_start", lambda self, config: "both")

    started: list[str] = []
    monkeypatch.setattr(SetupWizard, "start_phone",
                        lambda self, config, channel:
                        started.append(channel.name) or True)

    saved = run_setup(blank, offer=True)
    assert started == ["telegram"], "it started something that is not set up"
    assert saved.start_after_setup == "both"


def test_the_closing_question_names_the_channel_that_is_ready(blank):
    """Somebody who set up WhatsApp should not be offered "the Telegram bot"."""
    blank.whatsapp.token = "EAA"
    blank.whatsapp.phone_number_id = "1234567890"
    blank.whatsapp.allowed = ["15550001111"]

    setup, _ = closing(blank, ["1"])
    drawn = "\n".join(setup.console.frames[-1])

    assert "WhatsApp" in drawn
    assert "Telegram" not in drawn
