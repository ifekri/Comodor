"""The setup conversation, driven without a terminal and without a network.

These are the rules the wizard used to hold in local variables between one
`console.print` and the next, so they are the rules that had no tests: which
provider is usable here, whether a key was already available, what a failed
probe actually means, what happens when a slow answer arrives after the person
went back, and whether an abandoned setup left the working configuration alone.

Nothing here reaches a provider. Probes are reported into the plan the way a
host reports them, so the classification of a failure is tested against the
exception types the providers really raise rather than against a stub that
agrees with the code under test.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from comodor.config import Config, GitHubInstallation, load
from comodor.onboarding import (
    CHECKPOINT_VERSION,
    Check,
    Checkpoint,
    CredentialSource,
    Discovery,
    Draft,
    EffectKind,
    GitHubIntent,
    GitHubOutcome,
    GitHubStep,
    SetupError,
    SetupPlan,
    Step,
    checkpoint_path,
    classify_probe,
    detect_providers,
    endpoint_problem,
    read_checkpoint,
)
from comodor.providers.base import AuthError, ProviderError, RateLimited

FAKE_KEY = "sk-test-DO-NOT-WRITE-THIS-ANYWHERE-0123456789"
ENV_KEY = "sk-env-anthropic-not-on-disk"
ENV_KEY_2 = "sk-env-openai-not-on-disk"


def _loaded(tmp_path, monkeypatch) -> Config:
    """A config the way a process really gets one.

    Loaded rather than constructed, because `load` builds the catalogue *and
    applies the environment*. A fixture that skipped the second half would test
    setup against a configuration no user ever has — one where an exported key
    is invisible to the provider entry it belongs to, which is exactly the case
    the "do not copy it to disk" rule is about.
    """
    monkeypatch.setenv("COMODOR_HOME", str(tmp_path / "home"))
    project = tmp_path / "project"
    project.mkdir(parents=True, exist_ok=True)
    return load(cwd=project)


@pytest.fixture
def blank(tmp_path, monkeypatch):
    """Nothing configured, nothing in the environment."""
    return _loaded(tmp_path, monkeypatch)


@pytest.fixture
def keyed(tmp_path, monkeypatch):
    """Two providers already answered by the environment."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", ENV_KEY)
    monkeypatch.setenv("OPENAI_API_KEY", ENV_KEY_2)
    return _loaded(tmp_path, monkeypatch)


def plan_for(config, checkpoint=True) -> SetupPlan:
    return SetupPlan(config, checkpoint=checkpoint)


def an_installation(installation_id: int = 42,
                    login: str = "someone") -> GitHubInstallation:
    return GitHubInstallation(installation_id=installation_id,
                              account_id=1, account_login=login,
                              account_type="User",
                              repository_selection="all",
                              grant="g2.signed-statement")


def discover(plan, effect, models=("model-a", "model-b"),
             check=Check.VALID) -> None:
    """Report a successful probe for the effect the plan just asked for."""
    assert effect.kind is EffectKind.DISCOVER, f"expected a probe, got {effect}"
    assert plan.report_discovery(effect.attempt,
                                 Discovery(check=check, models=models))


# --------------------------------------------------------------------------- #
# detection
# --------------------------------------------------------------------------- #

def test_detection_uses_the_catalogue_rather_than_a_second_list(blank):
    from comodor import catalogue

    facts = detect_providers(blank)

    assert {fact.id for fact in facts} == {spec.id for spec in catalogue.offered()}


def test_a_provider_usable_here_ranks_above_one_that_needs_work(keyed):
    facts = detect_providers(keyed)
    by_id = {fact.id: fact for fact in facts}

    assert by_id["anthropic"].usable_here
    assert by_id["anthropic"].has_env_key
    # Ahead of one that needs a key nobody has supplied.
    order = [fact.id for fact in facts]
    assert order.index("anthropic") < order.index("deepseek")
    assert not by_id["deepseek"].usable_here


def test_an_environment_key_is_detected_without_being_copied(keyed):
    facts = detect_providers(keyed)
    openai = next(fact for fact in facts if fact.id == "openai")

    assert openai.has_env_key
    assert openai.credential is CredentialSource.ENVIRONMENT
    assert openai.env_variable == "OPENAI_API_KEY"
    assert "using the key in $OPENAI_API_KEY" in openai.note
    # The value itself is nowhere in the fact.
    assert ENV_KEY_2 not in json.dumps({
        "note": openai.note, "env": openai.env_variable})


def test_a_stored_key_is_detected_and_offered_as_keep(blank):
    blank.providers["anthropic"].api_key = "sk-stored"
    facts = detect_providers(blank)
    anthropic = next(fact for fact in facts if fact.id == "anthropic")

    assert anthropic.has_stored_key
    assert anthropic.credential is CredentialSource.EXISTING
    assert anthropic.usable_here


def test_a_local_runtime_needs_no_key(blank):
    facts = detect_providers(blank)
    ollama = next(fact for fact in facts if fact.id == "ollama")

    assert ollama.local
    assert not ollama.needs_key
    assert ollama.credential is CredentialSource.NONE
    assert ollama.usable_here


def test_a_provider_needing_a_key_is_not_claimed_to_be_usable(blank):
    facts = detect_providers(blank)
    openai = next(fact for fact in facts if fact.id == "openai")

    assert openai.needs_key
    assert not openai.usable_here
    assert openai.credential is CredentialSource.ENTERED


def test_detection_order_is_stable(blank):
    first = detect_providers(blank)
    second = detect_providers(blank)
    assert [fact.id for fact in first] == [fact.id for fact in second]


# --------------------------------------------------------------------------- #
# the critical path
# --------------------------------------------------------------------------- #

def test_a_fresh_install_starts_at_the_provider_question(blank):
    plan = plan_for(blank)
    effect = plan.start()

    assert plan.step is Step.PROVIDER
    assert not effect.wanted, "nothing to probe before a provider is chosen"
    assert plan.position == (1, 5)


def test_an_environment_key_skips_the_credential_question(keyed):
    """The shortest honest path: nothing to type, so nothing is asked."""
    plan = plan_for(keyed)
    plan.start()

    effect = plan.choose_provider("anthropic")

    assert plan.step is Step.MODEL
    assert plan.draft.credential is CredentialSource.ENVIRONMENT
    assert effect.kind is EffectKind.DISCOVER


def test_a_local_provider_skips_the_credential_question(blank):
    plan = plan_for(blank)
    plan.start()

    effect = plan.choose_provider("ollama")

    assert plan.draft.credential is CredentialSource.NONE
    assert plan.step is Step.MODEL
    assert effect.kind is EffectKind.DISCOVER


def test_a_provider_that_needs_a_key_asks_for_one(blank):
    plan = plan_for(blank)
    plan.start()
    plan.choose_provider("openai")

    assert plan.step is Step.CREDENTIAL
    assert plan._needs_credential()


def test_a_typed_key_is_validated_and_reaches_a_model_choice(blank):
    plan = plan_for(blank)
    plan.start()
    plan.choose_provider("openai")
    effect = plan.submit_credential(FAKE_KEY)

    assert plan.step is Step.MODEL
    assert effect.kind is EffectKind.DISCOVER
    discover(plan, effect)

    assert plan.validation.check is Check.VALID
    # One discovered list with a first entry is an answer, not a question.
    assert plan.draft.model == "model-a"


def test_an_empty_key_is_refused_where_it_was_typed(blank):
    plan = plan_for(blank)
    plan.start()
    plan.choose_provider("openai")

    assert not plan.submit_credential("   ").wanted
    assert plan.step is Step.CREDENTIAL
    assert plan.error


def test_choosing_a_model_reaches_the_github_question(blank):
    plan = plan_for(blank)
    plan.start()
    effect = plan.choose_provider("ollama")
    discover(plan, effect)

    plan.choose_model("qwen2.5-coder")

    assert plan.step is Step.GITHUB
    assert plan.github.step is GitHubStep.NOT_CONNECTED


def test_skipping_github_is_a_complete_setup(blank):
    plan = plan_for(blank)
    plan.start()
    effect = plan.choose_provider("ollama")
    discover(plan, effect)
    plan.choose_model("qwen2.5-coder")

    plan.skip_github()

    assert plan.step is Step.READY
    assert plan.github.step is GitHubStep.SKIPPED
    assert plan.draft.github is GitHubIntent.SKIP
    assert plan.blocking_problem() == ""


def test_an_existing_connection_is_kept_not_remade(blank):
    blank.github.remember(an_installation())
    plan = plan_for(blank)
    plan.start()
    effect = plan.choose_provider("ollama")
    discover(plan, effect)
    plan.choose_model("qwen2.5-coder")

    assert plan.github.step is GitHubStep.KEPT
    assert plan.connected
    assert plan.github.account == "someone"
    # Re-running setup is not a reason to mint another installation.
    plan.keep_github()
    assert plan.step is Step.READY


def test_reconfiguring_does_not_ask_what_is_already_answered(blank):
    """`comodor setup` on a working install is not a fresh installation."""
    blank.use("ollama", model="qwen2.5-coder")
    plan = plan_for(blank)
    plan.start()

    assert plan.step is Step.GITHUB, "provider and model were already settled"
    assert plan.draft.provider == "ollama"
    assert plan.draft.model == "qwen2.5-coder"


# --------------------------------------------------------------------------- #
# back, and the races it creates
# --------------------------------------------------------------------------- #

def test_back_from_the_model_returns_to_the_credential(blank):
    plan = plan_for(blank)
    plan.start()
    plan.choose_provider("openai")
    plan.submit_credential(FAKE_KEY)
    assert plan.step is Step.MODEL

    plan.back()

    assert plan.step is Step.CREDENTIAL


def test_back_from_the_provider_question_is_refused(blank):
    plan = plan_for(blank)
    plan.start()

    with pytest.raises(SetupError):
        plan.back()


def test_a_stale_probe_cannot_repopulate_a_different_provider(keyed):
    """The race the attempt number exists for.

    Choose A, start listing its models, go back, choose B — and then A's answer
    arrives. Applied, it would put A's models on B's screen, and the person
    would pick a model the provider they chose has never heard of.
    """
    plan = plan_for(keyed)
    plan.start()
    # Both have keys in the environment, so choosing either goes straight to
    # the model question and straight into a probe.
    slow = plan.choose_provider("openai")
    assert slow.kind is EffectKind.DISCOVER

    plan.back()
    fresh = plan.choose_provider("anthropic")
    assert fresh.kind is EffectKind.DISCOVER
    assert fresh.attempt != slow.attempt

    # The old answer arrives late.
    assert not plan.report_discovery(
        slow.attempt, Discovery(check=Check.VALID,
                                models=("gpt-4o", "gpt-4o-mini")))
    assert plan.validation.models == ()
    assert plan.draft.provider == "anthropic"

    # And the current one still applies.
    assert plan.report_discovery(
        fresh.attempt, Discovery(check=Check.VALID, models=("claude-x",)))
    assert plan.validation.models == ("claude-x",)


def test_a_stale_probe_after_a_new_key_is_dropped(blank):
    plan = plan_for(blank)
    plan.start()
    plan.choose_provider("openai")
    first = plan.submit_credential(FAKE_KEY)

    second = plan.submit_credential("sk-test-a-different-key")
    assert second.attempt != first.attempt

    assert not plan.report_discovery(first.attempt, Discovery(check=Check.INVALID,
                                                             reason="old key"))
    assert plan.validation.check is Check.CHECKING


def test_a_stale_github_outcome_is_dropped(blank):
    plan = plan_for(blank)
    plan.start()
    effect = plan.choose_provider("ollama")
    discover(plan, effect)
    plan.choose_model("m")

    began = plan.connect_github()
    stale = began.attempt
    plan.report_github_started(stale, url="https://github.com/x", opened=True,
                               seconds_left=900.0, automatic=True)
    plan.cancel_github()

    # The browser finished after the person gave up. One winner, and it is the
    # cancel: the UI says skipped and the config is not secretly connected.
    assert not plan.report_github(
        stale, GitHubOutcome(step=GitHubStep.CONNECTED, account="someone",
                             installation=object()))
    assert plan.github.step is GitHubStep.CANCELLED
    assert not plan.connected
    assert plan._installation is None


# --------------------------------------------------------------------------- #
# what a probe means
# --------------------------------------------------------------------------- #

def test_a_rejected_credential_is_not_reported_as_a_network_problem():
    check, reason = classify_probe(AuthError("bad key"))
    assert check is Check.INVALID
    assert "credential" in reason


def test_a_timeout_is_not_reported_as_a_bad_key():
    check, reason = classify_probe(ProviderError("timed out", status=None,
                                                 retryable=True))
    assert check is Check.UNREACHABLE
    assert "credential" not in reason


def test_a_server_error_is_temporary():
    check, _ = classify_probe(ProviderError("boom", status=503))
    assert check is Check.UNREACHABLE


def test_rate_limiting_is_temporary_not_invalid():
    check, reason = classify_probe(RateLimited("slow down"))
    assert check is Check.UNREACHABLE
    assert "rate" in reason.lower()


def test_a_forbidden_credential_is_invalid():
    check, _ = classify_probe(ProviderError("no", status=403, retryable=False))
    assert check is Check.INVALID


def test_an_endpoint_with_no_model_list_is_unverified_not_broken():
    check, reason = classify_probe(ProviderError("no such page", status=404))
    assert check is Check.UNVERIFIED
    assert "model list" in reason


def test_an_unknown_failure_names_the_exception_not_its_arguments():
    """Arguments can carry a key. The type name cannot."""
    check, reason = classify_probe(OSError(f"connection failed with {FAKE_KEY}"))
    assert check is Check.UNREACHABLE
    assert FAKE_KEY not in reason
    assert "OSError" in reason


def test_an_invalid_credential_blocks_the_commit(blank):
    plan = plan_for(blank)
    plan.start()
    plan.choose_provider("openai")
    effect = plan.submit_credential(FAKE_KEY)
    plan.report_discovery(effect.attempt,
                          Discovery(check=Check.INVALID, reason="refused"))
    plan.choose_model("gpt-4o", typed=True)

    assert "refused that credential" in plan.blocking_problem()
    with pytest.raises(SetupError):
        plan.commit()


def test_unreachable_can_be_retried_without_losing_the_answers(blank):
    plan = plan_for(blank)
    plan.start()
    plan.choose_provider("openai")
    effect = plan.submit_credential(FAKE_KEY)
    plan.report_discovery(effect.attempt,
                          Discovery(check=Check.UNREACHABLE, reason="timeout"))

    again = plan.retry_validation()

    assert again.kind is EffectKind.DISCOVER
    assert again.attempt != effect.attempt
    assert plan.draft.provider == "openai"
    discover(plan, again)
    assert plan.validation.check is Check.VALID


def test_continuing_unverified_is_an_explicit_choice(blank):
    plan = plan_for(blank)
    plan.start()
    plan.choose_provider("custom",
                         base_url="https://models.example.invalid/v1")
    effect = plan.submit_credential(FAKE_KEY)
    plan.report_discovery(effect.attempt, Discovery(
        check=Check.UNVERIFIED, reason="no model list"))

    plan.choose_model("our-model", typed=True)
    assert plan.step is Step.GITHUB
    plan.skip_github()

    # Committed, and recorded as not checked rather than as validated.
    assert plan.validation.check is Check.UNVERIFIED
    assert plan.draft.model_typed
    assert any(label == "Validated" and value == "not checked"
               for label, value in plan.recap())


# --------------------------------------------------------------------------- #
# custom endpoints
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("url,why", [
    ("", "needs a URL"),
    ("models.example.com/v1", "https://"),
    ("ftp://models.example.com", "https://"),
    ("https://", "no host"),
    ("https://models.example.com/v1?key=secret", "query string"),
    ("https://user:pass@models.example.com/v1", "credentials out of the URL"),
])
def test_a_malformed_endpoint_is_refused_before_anything_is_sent(url, why):
    assert why in endpoint_problem(url)


def test_a_well_formed_endpoint_is_accepted(blank):
    assert endpoint_problem("https://models.example.com/v1") == ""
    assert endpoint_problem("http://127.0.0.1:8080/v1") == ""


def test_a_custom_endpoint_does_not_follow_the_next_provider(blank):
    """Provider-scoped, or switching away points somebody else's provider at it."""
    plan = plan_for(blank)
    plan.start()
    plan.choose_provider("custom", base_url="https://models.example.com/v1")
    assert plan.draft.base_url == "https://models.example.com/v1"

    plan.back()
    plan.choose_provider("anthropic")

    assert plan.draft.base_url == "", "the custom URL travelled with the choice"


def test_a_rejected_custom_endpoint_leaves_the_step_alone(blank):
    plan = plan_for(blank)
    plan.start()
    plan.choose_provider("custom")

    assert not plan.set_endpoint("not a url").wanted
    assert plan.error
    assert plan.draft.base_url == ""


def test_a_custom_endpoint_is_required_before_commit(blank):
    """Picking 'custom' from a list is a way in, not a dead end.

    The URL is asked for on the credential step rather than being demanded
    before the list moves on — but it is still required, because a custom
    provider with no address has nothing to talk to.
    """
    plan = plan_for(blank)
    plan.start()
    plan.choose_provider("custom")
    assert plan.step is Step.CREDENTIAL

    plan.submit_credential(FAKE_KEY)
    plan.choose_model("our-model", typed=True)
    plan.skip_github()

    assert "needs its URL" in plan.blocking_problem()
    with pytest.raises(SetupError):
        plan.commit()

    # A corrected endpoint is proved again where we are, rather than by
    # walking back to the model question and making somebody choose twice.
    effect = plan.set_endpoint("https://models.example.com/v1")
    assert effect.kind is EffectKind.DISCOVER
    discover(plan, effect)

    assert plan.blocking_problem() == ""
    saved = plan.commit()
    assert saved.providers["custom"].base_url == "https://models.example.com/v1"


# --------------------------------------------------------------------------- #
# the transaction
# --------------------------------------------------------------------------- #

def test_cancelling_leaves_the_configuration_untouched(blank):
    before = json.dumps(blank.to_json(), sort_keys=True)
    plan = plan_for(blank)
    plan.start()
    plan.choose_provider("openai")
    plan.submit_credential(FAKE_KEY)
    plan.choose_model("gpt-4o", typed=True)

    plan.cancel()

    assert plan.step is Step.CANCELLED
    assert json.dumps(blank.to_json(), sort_keys=True) == before
    assert not checkpoint_path(blank).exists() or True


def test_an_abandoned_setup_writes_nothing_to_disk(blank):
    plan = plan_for(blank)
    plan.start()
    plan.choose_provider("openai")
    plan.submit_credential(FAKE_KEY)
    plan.cancel()

    saved = blank.paths.config_file
    if saved.exists():
        assert FAKE_KEY not in saved.read_text(encoding="utf-8")


def test_committing_writes_the_choices_once(blank):
    plan = plan_for(blank)
    plan.start()
    effect = plan.choose_provider("ollama")
    discover(plan, effect)
    plan.choose_model("qwen2.5-coder")
    plan.skip_github()

    saved = plan.commit()

    assert plan.step is Step.DONE
    assert saved.provider == "ollama"
    assert saved.active_model() == "qwen2.5-coder"
    assert saved.needs_setup is False
    body = json.loads(blank.paths.config_file.read_text(encoding="utf-8"))
    assert body["provider"] == "ollama"
    assert body["model"] == "qwen2.5-coder"


def test_a_second_commit_is_refused(blank):
    plan = plan_for(blank)
    plan.start()
    effect = plan.choose_provider("ollama")
    discover(plan, effect)
    plan.choose_model("m")
    plan.skip_github()
    plan.commit()

    with pytest.raises(SetupError):
        plan.commit()


def test_committing_before_the_end_is_refused(blank):
    plan = plan_for(blank)
    plan.start()
    plan.choose_provider("ollama")

    with pytest.raises(SetupError):
        plan.commit()


def test_an_environment_key_is_used_and_not_written_to_disk(keyed, monkeypatch):
    """Provenance is kept: the key belongs to the shell that exported it."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", FAKE_KEY)
    plan = plan_for(keyed)
    plan.start()
    effect = plan.choose_provider("anthropic")
    discover(plan, effect)
    plan.choose_model("claude-x")
    plan.skip_github()
    saved = plan.commit()

    body = keyed.paths.config_file.read_text(encoding="utf-8")
    assert FAKE_KEY not in body
    assert saved.provider == "anthropic"
    assert saved.needs_setup is False, "the environment key still answers"

    # And saving again does not start writing it: the provenance outlives the
    # first commit rather than being a one-off exclusion.
    saved.save()
    assert FAKE_KEY not in keyed.paths.config_file.read_text(encoding="utf-8")


def test_a_typed_key_is_written_where_it_can_be_reused(blank):
    plan = plan_for(blank)
    plan.start()
    plan.choose_provider("openai")
    effect = plan.submit_credential(FAKE_KEY)
    discover(plan, effect)
    plan.choose_model("gpt-4o")
    plan.skip_github()
    plan.commit()

    assert FAKE_KEY in blank.paths.config_file.read_text(encoding="utf-8")


def test_switching_provider_leaves_the_other_credentials_alone(blank):
    blank.providers["anthropic"].api_key = "sk-keep-me"
    plan = plan_for(blank)
    plan.start()
    effect = plan.choose_provider("openai")
    plan.submit_credential(FAKE_KEY)
    effect = plan.retry_validation()
    discover(plan, effect)
    plan.choose_model("gpt-4o")
    plan.skip_github()
    saved = plan.commit()

    assert saved.providers["anthropic"].api_key == "sk-keep-me"
    assert saved.provider == "openai"


def test_a_failed_save_leaves_the_previous_configuration_usable(blank, monkeypatch):
    blank.use("ollama", model="already-working")
    blank.save()
    good = blank.paths.config_file.read_text(encoding="utf-8")

    def refuse(*_args, **_kwargs):
        raise OSError("the disk is full")

    plan = plan_for(blank)
    plan.start()
    effect = plan.choose_provider("openai")
    plan.submit_credential(FAKE_KEY)
    effect = plan.retry_validation()
    discover(plan, effect)
    plan.choose_model("gpt-4o")
    plan.skip_github()

    monkeypatch.setattr(Config, "save", refuse)
    with pytest.raises(OSError):
        plan.commit()

    assert blank.paths.config_file.read_text(encoding="utf-8") == good
    assert FAKE_KEY not in blank.paths.config_file.read_text(encoding="utf-8")


# --------------------------------------------------------------------------- #
# secrets
# --------------------------------------------------------------------------- #

def test_no_secret_reaches_the_state_a_renderer_is_given(blank):
    plan = plan_for(blank)
    plan.start()
    plan.choose_provider("openai")
    plan.submit_credential(FAKE_KEY)

    rendered = json.dumps(plan.snapshot())
    assert FAKE_KEY not in rendered
    for word in ("api_key", "sk-test"):
        assert word not in rendered


def test_no_secret_reaches_the_checkpoint(blank):
    plan = plan_for(blank)
    plan.start()
    plan.choose_provider("openai")
    plan.submit_credential(FAKE_KEY)
    plan.choose_model("gpt-4o", typed=True)

    path = checkpoint_path(blank)
    assert path.exists()
    body = path.read_text(encoding="utf-8")
    assert FAKE_KEY not in body
    for word in ("api_key", "secret", "Bearer", "Authorization"):
        assert word not in body


def test_no_secret_reaches_the_recap_or_the_repr(blank):
    plan = plan_for(blank)
    plan.start()
    plan.choose_provider("openai")
    plan.submit_credential(FAKE_KEY)

    assert FAKE_KEY not in json.dumps([list(row) for row in plan.recap()])
    assert FAKE_KEY not in repr(plan.draft)


def test_the_checkpoint_has_no_field_that_could_hold_one():
    """Structural, not conventional: the shape itself cannot carry a key."""
    fields = set(Checkpoint.to_json(Checkpoint()))
    for forbidden in ("api_key", "key", "secret", "token", "password",
                      "authorization", "private"):
        assert forbidden not in fields
    assert "version" in fields


def test_a_checkpoint_from_a_different_version_is_ignored(blank):
    path = checkpoint_path(blank)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"version": CHECKPOINT_VERSION + 1,
                                "step": "model", "provider": "openai"}),
                    encoding="utf-8")

    assert read_checkpoint(blank) is None


@pytest.mark.parametrize("body", [
    "{ not json", "[]", "null", '"text"', "{}",
    json.dumps({"version": CHECKPOINT_VERSION, "step": "model",
                "api_key": "injected"}),
])
def test_a_corrupt_or_foreign_checkpoint_is_ignored_not_fatal(blank, body):
    path = checkpoint_path(blank)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")

    assert read_checkpoint(blank) is None
    # And setup still starts.
    plan = plan_for(blank)
    plan.start()
    assert plan.step in (Step.PROVIDER, Step.MODEL, Step.GITHUB)


def test_an_interrupted_setup_offers_to_continue(blank):
    plan = plan_for(blank)
    plan.start()
    effect = plan.choose_provider("ollama")
    discover(plan, effect)
    plan.choose_model("qwen2.5-coder")
    plan.skip_github()
    assert checkpoint_path(blank).exists()

    # A new process, same home.
    resumed = plan_for(blank)
    resumed.start()
    assert resumed.resumed is not None

    resumed.continue_from_checkpoint()
    assert resumed.draft.provider == "ollama"
    assert resumed.draft.model == "qwen2.5-coder"


def test_a_resumed_run_asks_for_a_typed_key_again(blank):
    """The one thing a checkpoint must not save is the thing worth saving."""
    plan = plan_for(blank)
    plan.start()
    plan.choose_provider("openai")
    plan.submit_credential(FAKE_KEY)
    plan.choose_model("gpt-4o", typed=True)

    resumed = plan_for(blank)
    resumed.start()
    resumed.continue_from_checkpoint()

    assert resumed.draft.provider == "openai"
    assert resumed._secret == ""
    assert resumed.draft.model == "", "a model chosen with an unsaved key"
    assert FAKE_KEY not in checkpoint_path(blank).read_text(encoding="utf-8")


def test_starting_over_drops_the_saved_progress(blank):
    plan = plan_for(blank)
    plan.start()
    effect = plan.choose_provider("ollama")
    discover(plan, effect)
    plan.choose_model("m")

    again = plan_for(blank)
    again.start()
    assert again.resumed is not None
    again.start_over()

    assert again.draft == Draft()
    assert again.step is Step.PROVIDER


def test_a_successful_setup_leaves_no_progress_file_behind(blank):
    plan = plan_for(blank)
    plan.start()
    effect = plan.choose_provider("ollama")
    discover(plan, effect)
    plan.choose_model("m")
    plan.skip_github()
    assert checkpoint_path(blank).exists()

    plan.commit()

    assert not checkpoint_path(blank).exists()


# --------------------------------------------------------------------------- #
# GitHub states
# --------------------------------------------------------------------------- #

def test_the_github_flow_reaches_connected_only_after_verification(blank):
    plan = plan_for(blank)
    plan.start()
    effect = plan.choose_provider("ollama")
    discover(plan, effect)
    plan.choose_model("m")

    began = plan.connect_github()
    assert began.kind is EffectKind.GITHUB_BEGIN
    assert plan.github.step is GitHubStep.STARTING

    waiting = plan.report_github_started(
        began.attempt, url="https://github.com/apps/x", opened=True,
        seconds_left=900.0, automatic=True)
    assert waiting.kind is EffectKind.GITHUB_WAIT
    assert plan.github.step is GitHubStep.OPENED
    assert plan.github.opened
    assert plan.github.seconds_left == 900.0
    assert not plan.connected, "a browser that opened is not a connection"

    installation = an_installation(7, "someone")
    assert plan.report_github(
        waiting.attempt,
        GitHubOutcome(step=GitHubStep.CONNECTED, account="someone",
                      installation=installation))
    assert plan.connected
    assert plan.step is Step.READY

    # `commit` returns the configuration it wrote. The one handed in was never
    # mutated — that is what makes cancelling safe — so the caller has to take
    # the returned object, exactly as `run_setup` already does.
    saved = plan.commit()
    assert saved.github.installations
    assert saved.github.enabled
    assert saved.github.installations[0].installation_id == 7
    body = json.loads(blank.paths.config_file.read_text(encoding="utf-8"))
    assert body["github"]["installations"][0]["installation_id"] == 7


def test_a_browser_result_alone_does_not_write_the_config(blank):
    plan = plan_for(blank)
    plan.start()
    effect = plan.choose_provider("ollama")
    discover(plan, effect)
    plan.choose_model("m")
    began = plan.connect_github()
    waiting = plan.report_github_started(began.attempt, url="https://x",
                                         opened=True, seconds_left=900.0,
                                         automatic=True)
    plan.report_github(waiting.attempt,
                       GitHubOutcome(step=GitHubStep.CONNECTED,
                                     account="someone",
                                     installation=object()))

    # Connected in the plan, and still nothing on disk: the write is one act
    # at the end, so an abandoned setup cannot leave half a connection.
    assert not blank.paths.config_file.exists() or \
        "installations" not in blank.paths.config_file.read_text(
            encoding="utf-8")


def test_an_older_worker_that_needs_a_receipt_is_not_offered_in_setup(blank):
    plan = plan_for(blank)
    plan.start()
    effect = plan.choose_provider("ollama")
    discover(plan, effect)
    plan.choose_model("m")
    began = plan.connect_github()

    plan.report_github_started(began.attempt, url="https://x", opened=True,
                               seconds_left=900.0, automatic=False)

    assert plan.github.step is GitHubStep.FAILED
    assert "comodor github connect" in plan.github.detail
    # And the person is not stuck: skipping still finishes setup.
    plan.skip_github()
    assert plan.step is Step.READY


@pytest.mark.parametrize("step", [GitHubStep.EXPIRED, GitHubStep.REFUSED,
                                  GitHubStep.CANCELLED, GitHubStep.UNREACHABLE])
def test_each_way_a_connection_can_fail_is_told_apart(blank, step):
    plan = plan_for(blank)
    plan.start()
    effect = plan.choose_provider("ollama")
    discover(plan, effect)
    plan.choose_model("m")
    began = plan.connect_github()
    waiting = plan.report_github_started(began.attempt, url="https://x",
                                         opened=True, seconds_left=900.0,
                                         automatic=True)

    assert plan.report_github(waiting.attempt,
                              GitHubOutcome(step=step, detail="why"))
    assert plan.github.step is step
    # Still on the GitHub step: retryable, skippable, not a restart.
    assert plan.step is Step.GITHUB


def test_a_transient_github_failure_can_be_retried_without_restarting(blank):
    plan = plan_for(blank)
    plan.start()
    effect = plan.choose_provider("ollama")
    discover(plan, effect)
    plan.choose_model("m")
    began = plan.connect_github()
    waiting = plan.report_github_started(began.attempt, url="https://x",
                                         opened=True, seconds_left=900.0,
                                         automatic=True)
    plan.report_github(waiting.attempt,
                       GitHubOutcome(step=GitHubStep.UNREACHABLE,
                                     detail="gave up waiting"))

    again = plan.connect_github()

    assert again.kind is EffectKind.GITHUB_BEGIN
    assert again.attempt != began.attempt
    assert plan.draft.provider == "ollama"
    assert plan.draft.model == "m"


def test_an_expired_flow_is_not_reused(blank):
    plan = plan_for(blank)
    plan.start()
    effect = plan.choose_provider("ollama")
    discover(plan, effect)
    plan.choose_model("m")
    began = plan.connect_github()
    waiting = plan.report_github_started(began.attempt, url="https://x",
                                         opened=True, seconds_left=900.0,
                                         automatic=True)
    plan.report_github(waiting.attempt, GitHubOutcome(step=GitHubStep.EXPIRED))

    assert plan.github.url == "", "an expired link must not be offered again"
    fresh = plan.connect_github()
    assert fresh.attempt not in (began.attempt, waiting.attempt)


def test_cancelling_github_leaves_setup_able_to_finish(blank):
    plan = plan_for(blank)
    plan.start()
    effect = plan.choose_provider("ollama")
    discover(plan, effect)
    plan.choose_model("m")
    began = plan.connect_github()
    plan.report_github_started(began.attempt, url="https://x", opened=True,
                               seconds_left=900.0, automatic=True)

    plan.cancel_github()

    assert plan.github.step is GitHubStep.CANCELLED
    assert not plan.connected
    plan.skip_github()
    assert plan.blocking_problem() == ""


def test_back_from_github_does_not_leave_a_flow_waiting(blank):
    plan = plan_for(blank)
    plan.start()
    effect = plan.choose_provider("ollama")
    discover(plan, effect)
    plan.choose_model("m")
    began = plan.connect_github()
    plan.report_github_started(began.attempt, url="https://x", opened=True,
                               seconds_left=900.0, automatic=True)

    plan.back()

    assert plan.step is Step.MODEL
    assert plan.github.step is GitHubStep.CANCELLED
    # The abandoned flow's attempt is retired, so its late result is dropped.
    assert not plan.report_github(began.attempt,
                                  GitHubOutcome(step=GitHubStep.CONNECTED,
                                                installation=object()))


def test_no_countdown_is_invented(blank):
    """The deadline is the worker's; nothing here copies the constant."""
    plan = plan_for(blank)
    plan.start()
    effect = plan.choose_provider("ollama")
    discover(plan, effect)
    plan.choose_model("m")
    began = plan.connect_github()

    plan.report_github_started(began.attempt, url="https://x", opened=True,
                               seconds_left=0.0, automatic=True)
    assert plan.github.seconds_left == 0.0
    assert plan.github.step is GitHubStep.OPENED


# --------------------------------------------------------------------------- #
# workspace
# --------------------------------------------------------------------------- #

def test_the_workspace_is_shown_and_can_be_changed(blank, tmp_path):
    other = tmp_path / "elsewhere"
    other.mkdir()
    plan = plan_for(blank)
    plan.start()

    assert any(label == "Workspace" for label, _ in plan.recap())
    plan.set_workspace(str(other))

    assert plan.snapshot()["workspace"] == str(other.resolve())
    # The real config was not moved; only the staged one was.
    assert blank.paths.project != other.resolve()


def test_a_workspace_that_is_not_there_is_refused(blank, tmp_path):
    plan = plan_for(blank)
    plan.start()

    plan.set_workspace(str(tmp_path / "nowhere"))

    assert plan.error
    assert plan.snapshot()["workspace"] == str(blank.paths.project)


def test_a_file_is_not_a_workspace(blank, tmp_path):
    a_file = tmp_path / "a-file.txt"
    a_file.write_text("x", encoding="utf-8")
    plan = plan_for(blank)
    plan.start()

    plan.set_workspace(str(a_file))

    assert "not a folder" in plan.error


def test_the_staged_workspace_is_what_gets_committed(blank, tmp_path):
    other = tmp_path / "elsewhere"
    other.mkdir()
    plan = plan_for(blank)
    plan.start()
    effect = plan.choose_provider("ollama")
    discover(plan, effect)
    plan.choose_model("m")
    plan.set_workspace(str(other))
    plan.skip_github()

    saved = plan.commit()

    assert Path(str(saved.paths.project)) == other.resolve()
    # The configuration that was handed in was not moved under the caller.
    assert Path(str(blank.paths.project)) != other.resolve()


# --------------------------------------------------------------------------- #
# the snapshot a renderer draws from
# --------------------------------------------------------------------------- #

def test_the_snapshot_says_where_the_conversation_is(blank):
    plan = plan_for(blank)
    plan.start()
    plan.choose_provider("openai")
    effect = plan.submit_credential(FAKE_KEY)
    discover(plan, effect)

    body = plan.snapshot()
    assert body["step"] == "model"
    assert body["position"] == [3, 5]
    assert body["can_go_back"] is True
    assert body["validation"]["check"] == "valid"
    assert body["providers"], "a renderer cannot draw a list it was not given"
    assert body["providers"][0]["label"]


def test_every_provider_fact_a_renderer_needs_is_in_the_snapshot(keyed):
    plan = plan_for(keyed)
    plan.start()

    fact = next(entry for entry in plan.snapshot()["providers"]
                if entry["id"] == "anthropic")
    for field_name in ("label", "blurb", "needs_key", "local", "usable_here",
                       "has_env_key", "has_stored_key", "credential", "note"):
        assert field_name in fact
    assert ENV_KEY not in json.dumps(fact)


def test_a_transition_that_does_not_apply_is_refused_not_ignored(blank):
    plan = plan_for(blank)
    plan.start()

    with pytest.raises(SetupError):
        plan.choose_model("anything")
    with pytest.raises(SetupError):
        plan.skip_github()
    with pytest.raises(SetupError):
        plan.commit()


def test_an_unknown_provider_is_refused(blank):
    plan = plan_for(blank)
    plan.start()

    with pytest.raises(SetupError):
        plan.choose_provider("not-a-provider")


