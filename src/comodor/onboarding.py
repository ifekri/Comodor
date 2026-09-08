"""The setup conversation, as state rather than as a screen.

Before this, "what happens during setup" lived inside a Rich wizard: the order
of the questions, which provider needed a key, whether a model list had arrived,
and what counted as finished were all local variables between one
``console.print`` and the next. That worked in a terminal and could not be
reused by anything else, could not be tested without a console, and had no
answer to a slow provider response arriving after the person had gone back.

So the decisions live here and the drawing lives elsewhere.

    detection → provider → credential → model → validation
              → workspace → GitHub (optional) → ready → commit

Three rules shaped it:

**The host performs effects; the plan only asks for them.** Listing models,
probing an endpoint and waiting on a browser are all slow, and none of them may
run on a drawing thread. The plan returns an :class:`Effect`, the host runs it
however it likes, and reports the outcome back with the attempt number it was
given. A result whose attempt is not the current one is dropped, which is the
whole fix for "provider A answered after I chose provider B" — the guard is in
one place rather than in every caller's head.

**Nothing secret is in the state.** The credential is held apart from the
:class:`Draft`, the checkpoint has no field that could carry one, and the
snapshot is built from an allow-list of named fields rather than by walking the
object. A key reaches exactly two places: the probe the host builds to validate
it, and the config write at commit time.

**The config is written once, at the end.** Staging happens on a copy, so
cancelling, a failed validation, or a GitHub flow that expires leaves the
working configuration byte-for-byte as it was. A half-finished setup that
overwrote a working key would be worse than no setup at all.
"""

from __future__ import annotations

import copy
import json
import os
import tempfile
import time
from dataclasses import dataclass, replace
from enum import Enum
from pathlib import Path
from typing import Any, Callable

from . import catalogue
from .config import Config, _discard, _durably

__all__ = [
    "CHECKPOINT_VERSION", "Checkpoint", "Check", "CredentialSource", "Discovery",
    "Draft", "Effect", "EffectKind", "GitHub", "GitHubIntent", "GitHubOutcome",
    "ProviderFact", "SetupPlan", "Step", "detect_providers",
]

#: Bumped when the checkpoint's shape changes. An older or newer file is
#: ignored rather than guessed at: a stale onboarding file must never be able
#: to stop Comodor starting, and it holds nothing worth recovering by force.
CHECKPOINT_VERSION = 1

CHECKPOINT_NAME = "setup-checkpoint.json"


# --------------------------------------------------------------------------- #
# where the conversation is
# --------------------------------------------------------------------------- #

class Step(str, Enum):
    """One decision at a time, in the order a first run needs them.

    The optional extras the old wizard asked about — approval policy, skills,
    phone channels — are not steps. None of them is needed to reach a working
    agent, and every one of them has its own command, so they moved out of the
    critical path rather than being deleted.
    """

    PROVIDER = "provider"
    CREDENTIAL = "credential"
    MODEL = "model"
    GITHUB = "github"
    READY = "ready"
    DONE = "done"
    CANCELLED = "cancelled"


#: The steps a person sees, for "2 of 5" progress. Detection is not one of
#: them, and Ready is the last rather than a step past the end.
VISIBLE_STEPS: tuple[Step, ...] = (
    Step.PROVIDER, Step.CREDENTIAL, Step.MODEL, Step.GITHUB, Step.READY,
)


class CredentialSource(str, Enum):
    """Where the key came from — never the key.

    Provenance is kept because it decides what gets written to disk. A key read
    from the environment belongs to the environment: copying it into a config
    file would move a secret from a place somebody chose to a place they did
    not, and would survive the shell that exported it.
    """

    NONE = "none"              # this provider needs no key at all
    ENVIRONMENT = "environment"  # use $VARIABLE, and do not copy it
    EXISTING = "existing"        # already stored; keep it
    IMPORTED = "imported"        # migration wrote it before setup began
    ENTERED = "entered"          # typed during this run


class Check(str, Enum):
    """What is known about whether the provider actually works.

    "Configured" and "working" are different facts, and collapsing them is how
    a wizard says Ready and then fails on the first message. Equally, a timeout
    is not a bad key: saying "wrong key" about a network blip sends somebody to
    rotate a credential that was fine.
    """

    IDLE = "idle"                # nothing attempted yet
    CHECKING = "checking"        # a probe is in flight
    VALID = "valid"              # authenticated, and it has models
    INVALID = "invalid"          # refused the credential, or the endpoint is wrong
    UNREACHABLE = "unreachable"  # network, timeout, rate limit, server error
    NO_MODELS = "no_models"      # authenticated, but offered nothing to run
    UNVERIFIED = "unverified"    # could not be checked; continuing is a choice


class GitHubIntent(str, Enum):
    """What the person asked for, as distinct from what happened."""

    ASK = "ask"
    CONNECT = "connect"
    SKIP = "skip"
    KEEP = "keep"


class GitHubStep(str, Enum):
    """Every state a connection can be in, told apart.

    "GitHub failed" is not a state. Somebody deciding whether to retry, wait or
    skip needs to know which of those is even meaningful, and an expired link
    and a refused installation call for different next steps.
    """

    NOT_CONNECTED = "not_connected"
    KEPT = "kept"                # already connected, and left alone
    STARTING = "starting"
    OPENED = "opened"            # browser launched, waiting not yet begun
    WAITING = "waiting"
    CONNECTED = "connected"
    SKIPPED = "skipped"
    CANCELLED = "cancelled"
    EXPIRED = "expired"
    REFUSED = "refused"          # GitHub or the worker said no
    UNREACHABLE = "unreachable"  # transient; retrying is reasonable
    FAILED = "failed"


# --------------------------------------------------------------------------- #
# what the machine knows
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class ProviderFact:
    """One provider, as this machine sees it. Rendered, never re-derived.

    A client that rediscovered any of this would be a second source of truth
    about what is installed, and the two would disagree in exactly the cases
    that matter — an environment key present in one process and not another.
    """

    id: str
    label: str
    blurb: str
    needs_key: bool
    local: bool
    #: The environment variable that supplies a key, if there is one.
    env_variable: str
    has_env_key: bool
    has_stored_key: bool
    is_active: bool
    known_models: tuple[str, ...]
    rank: int

    @property
    def usable_here(self) -> bool:
        """Could answer right now without the person supplying anything."""
        if self.has_env_key or self.has_stored_key:
            return True
        return self.local and not self.needs_key

    @property
    def credential(self) -> CredentialSource:
        """Where a key would come from, before anybody is asked."""
        if not self.needs_key:
            return CredentialSource.NONE
        if self.has_env_key:
            return CredentialSource.ENVIRONMENT
        if self.has_stored_key:
            return CredentialSource.EXISTING
        return CredentialSource.ENTERED

    @property
    def note(self) -> str:
        """Why this one is where it is, in words a person can act on."""
        if self.has_env_key and self.env_variable:
            return f"using the key in ${self.env_variable}"
        if self.has_stored_key:
            return "already configured here"
        if self.local:
            return "runs on this machine, no key"
        return "needs an API key"


def detect_providers(config: Config, *,
                     environment: Any = None) -> tuple[ProviderFact, ...]:
    """What is available on this machine, ordered by how little work it needs.

    Reuses the one catalogue rather than keeping a second list: a provider this
    function did not know about would be a provider setup could not offer.
    """
    env = os.environ if environment is None else environment
    facts: list[ProviderFact] = []
    for spec in catalogue.offered():
        entry = config.providers.get(spec.id)
        env_variable = spec.env_key
        has_env = bool(env_variable and str(env.get(env_variable, "")).strip())
        stored = entry is not None and bool(entry.api_key) and not has_env
        facts.append(ProviderFact(
            id=spec.id,
            label=spec.label,
            blurb=spec.blurb,
            needs_key=spec.needs_key,
            local=spec.local,
            env_variable=env_variable,
            has_env_key=has_env,
            has_stored_key=bool(stored),
            is_active=config.provider == spec.id,
            known_models=tuple(spec.models),
            rank=spec.rank,
        ))
    # Usable now, then by the catalogue's own ranking, then by name so the
    # order is stable rather than whatever the dict happened to hold.
    ordered = sorted(facts, key=lambda fact: (not fact.usable_here, fact.rank,
                                              fact.id))
    return tuple(ordered)


@dataclass(frozen=True)
class Draft:
    """The answers so far. No field here can hold a credential."""

    provider: str = ""
    credential: CredentialSource = CredentialSource.NONE
    env_variable: str = ""
    base_url: str = ""
    model: str = ""
    #: True when the model was typed rather than picked from a discovered list,
    #: which is the difference between "validated" and "taken on trust".
    model_typed: bool = False
    github: GitHubIntent = GitHubIntent.ASK


@dataclass(frozen=True)
class Validation:
    """What the last probe established."""

    check: Check = Check.IDLE
    #: Safe to show. Never a stack trace, never a key.
    reason: str = ""
    models: tuple[str, ...] = ()
    #: Which attempt produced this, so a stale result can be recognised.
    attempt: int = 0


@dataclass(frozen=True)
class GitHub:
    """The connection, as far as setup knows it."""

    step: GitHubStep = GitHubStep.NOT_CONNECTED
    #: The account, once connected. A login is not a secret and hiding it would
    #: leave somebody unable to tell which account they connected.
    account: str = ""
    #: The URL to open. Not secret: it travels through the browser anyway.
    url: str = ""
    opened: bool = False
    #: The worker's deadline, when it gave one. Never a copy of it.
    seconds_left: float = 0.0
    detail: str = ""
    attempt: int = 0


class EffectKind(str, Enum):
    """What the host is being asked to do."""

    NONE = "none"
    DISCOVER = "discover"
    GITHUB_BEGIN = "github_begin"
    GITHUB_WAIT = "github_wait"


@dataclass(frozen=True)
class Effect:
    """Work the plan cannot do itself, handed to whoever is driving it.

    Carries no credential. The host that runs a `DISCOVER` effect asks the plan
    for a probe entry, which is the only path by which the secret reaches the
    network.
    """

    kind: EffectKind = EffectKind.NONE
    attempt: int = 0
    provider: str = ""
    base_url: str = ""
    model: str = ""

    @property
    def wanted(self) -> bool:
        return self.kind is not EffectKind.NONE


@dataclass(frozen=True)
class Discovery:
    """What a probe found."""

    check: Check
    reason: str = ""
    models: tuple[str, ...] = ()


@dataclass(frozen=True)
class GitHubOutcome:
    """How a GitHub attempt ended, in the worker's own terms."""

    step: GitHubStep
    account: str = ""
    detail: str = ""
    #: The verified installation, when there is one. Held by the plan and
    #: written only at commit — a browser that finished is not a connection
    #: until the local identity is saved and the config records it.
    installation: Any = None


# --------------------------------------------------------------------------- #
# the checkpoint
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class Checkpoint:
    """Unfinished setup progress, with nowhere to put a secret.

    A frozen dataclass of strings and no key field, serialized through an
    allow-list. Both matter: omitting a secret "by convention" from a dict
    built by walking an object is one new field away from writing an API key
    into a file in somebody's home directory.

    This is not configuration. It says what a half-finished wizard had reached,
    and nothing here is honoured as a runtime setting.
    """

    version: int = CHECKPOINT_VERSION
    step: str = ""
    provider: str = ""
    credential: str = ""
    env_variable: str = ""
    base_url: str = ""
    model: str = ""
    model_typed: bool = False
    github: str = ""

    def to_json(self) -> dict[str, Any]:
        """An allow-list, deliberately. See the class docstring."""
        return {
            "version": self.version,
            "step": self.step,
            "provider": self.provider,
            "credential": self.credential,
            "env_variable": self.env_variable,
            "base_url": self.base_url,
            "model": self.model,
            "model_typed": bool(self.model_typed),
            "github": self.github,
        }

    @classmethod
    def from_json(cls, body: Any) -> "Checkpoint | None":
        """Read one, or None. Never raises: a corrupt onboarding file must not
        be able to stop Comodor starting."""
        if not isinstance(body, dict):
            return None
        if body.get("version") != CHECKPOINT_VERSION:
            return None
        known = set(cls.to_json(Checkpoint()))
        if not set(body).issubset(known):
            return None
        try:
            return cls(
                version=CHECKPOINT_VERSION,
                step=str(body.get("step") or ""),
                provider=str(body.get("provider") or ""),
                credential=str(body.get("credential") or ""),
                env_variable=str(body.get("env_variable") or ""),
                base_url=str(body.get("base_url") or ""),
                model=str(body.get("model") or ""),
                model_typed=bool(body.get("model_typed")),
                github=str(body.get("github") or ""),
            )
        except Exception:
            return None


def checkpoint_path(config: Config) -> Path:
    return Path(config.paths.user) / CHECKPOINT_NAME


def read_checkpoint(config: Config) -> Checkpoint | None:
    """The saved progress, or None if there is none or it cannot be trusted."""
    path = checkpoint_path(config)
    try:
        body = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return Checkpoint.from_json(body)


def write_checkpoint(config: Config, checkpoint: Checkpoint) -> bool:
    """Save progress, atomically. Failure is not fatal.

    A checkpoint is a convenience, so a filesystem that will not take one must
    not cost the person their setup. Written through a unique temporary file
    and renamed, using the same helpers as the configuration itself: a
    half-written checkpoint that parses as JSON but says something else is
    worse than none, and a second copy of that logic is a second place for it
    to be wrong.
    """
    path = checkpoint_path(config)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        handle, name = tempfile.mkstemp(prefix=".setup-", suffix=".tmp",
                                        dir=str(path.parent))
        temporary = Path(name)
        try:
            with os.fdopen(handle, "w", encoding="utf-8") as stream:
                json.dump(checkpoint.to_json(), stream, ensure_ascii=False)
                stream.flush()
                _durably(stream)
            os.replace(temporary, path)
        except BaseException:
            _discard(temporary)
            raise
        return True
    except OSError:
        return False


def clear_checkpoint(config: Config) -> None:
    """Remove the progress file. Setup finished, or was abandoned."""
    try:
        checkpoint_path(config).unlink()
    except OSError:
        pass


# --------------------------------------------------------------------------- #
# the plan
# --------------------------------------------------------------------------- #

class SetupError(Exception):
    """A transition that does not apply here.

    Raised rather than ignored, because a caller asking the plan to do
    something it is not waiting for is a bug in the caller, and silently
    returning the same state would hide it behind a screen that never changes.
    """


class SetupPlan:
    """The setup conversation, without a screen in sight.

    Drive it by calling a transition, running whatever :class:`Effect` comes
    back, and reporting the outcome with the attempt number it was given.
    """

    def __init__(self, config: Config, *,
                 clock: Callable[[], float] = time.time,
                 environment: Any = None,
                 checkpoint: bool = True) -> None:
        #: The configuration as it is now. Never mutated: the transaction
        #: works by leaving this alone until commit.
        self.config = config
        self._clock = clock
        #: Injected in tests so detection can be told what the environment
        #: holds without the test having to mutate the process's own.
        self._environment = environment
        self._checkpointed = checkpoint
        #: Everything the answers will be applied to. A copy, so a cancelled
        #: run leaves the real configuration untouched.
        self._staged: Config = copy.deepcopy(config)
        #: The credential, held apart from every serializable structure.
        self._secret = ""
        self._attempt = 0
        self._committed = False
        self.step = Step.PROVIDER
        self.draft = Draft()
        self.facts: tuple[ProviderFact, ...] = ()
        self.validation = Validation()
        self.github = GitHub()
        self.error = ""
        #: The verified installation, held between "the browser finished" and
        #: "the config was written".
        self._installation: Any = None
        #: What a resumable checkpoint said, so the host can offer to continue.
        self.resumed: Checkpoint | None = None

    # -- reading ---------------------------------------------------------- #

    @property
    def position(self) -> tuple[int, int]:
        """(which step, of how many), for "2 of 5"."""
        try:
            at = VISIBLE_STEPS.index(self.step) + 1
        except ValueError:
            at = len(VISIBLE_STEPS)
        return at, len(VISIBLE_STEPS)

    @property
    def can_go_back(self) -> bool:
        return self.step in (Step.CREDENTIAL, Step.MODEL, Step.GITHUB, Step.READY)

    @property
    def finished(self) -> bool:
        return self.step in (Step.DONE, Step.CANCELLED)

    def snapshot(self) -> dict[str, Any]:
        """Everything a renderer needs, and nothing it should not have.

        An allow-list of named fields rather than a walk over the object, so
        that adding a field to this class cannot quietly start shipping a
        credential to a screen.
        """
        return {
            "step": self.step.value,
            "position": list(self.position),
            "can_go_back": self.can_go_back,
            "error": self.error,
            "provider": self.draft.provider,
            "credential": self.draft.credential.value,
            "env_variable": self.draft.env_variable,
            "base_url": self.draft.base_url,
            "model": self.draft.model,
            "model_typed": self.draft.model_typed,
            "workspace": str(self._staged.paths.project),
            "providers": [
                {
                    "id": fact.id, "label": fact.label, "blurb": fact.blurb,
                    "needs_key": fact.needs_key, "local": fact.local,
                    "env_variable": fact.env_variable,
                    "has_env_key": fact.has_env_key,
                    "has_stored_key": fact.has_stored_key,
                    "is_active": fact.is_active,
                    "usable_here": fact.usable_here,
                    "credential": fact.credential.value,
                    "note": fact.note,
                }
                for fact in self.facts
            ],
            "validation": {
                "check": self.validation.check.value,
                "reason": self.validation.reason,
                "models": list(self.validation.models),
            },
            "github": {
                "step": self.github.step.value,
                "account": self.github.account,
                "url": self.github.url,
                "opened": self.github.opened,
                "seconds_left": self.github.seconds_left,
                "detail": self.github.detail,
            },
            "connected": self.connected,
            "committed": self._committed,
        }

    @property
    def connected(self) -> bool:
        """Whether GitHub is genuinely connected and usable.

        Not "the browser finished": the installation has to have been verified
        and the local identity saved before anything here says connected.
        """
        if self.github.step is GitHubStep.CONNECTED:
            return self._installation is not None
        return bool(self._staged.github.installations)

    def recap(self) -> tuple[tuple[str, str], ...]:
        """What has been decided, for a summary screen. No secret material."""
        rows: list[tuple[str, str]] = []
        if self.draft.provider:
            fact = self._fact(self.draft.provider)
            rows.append(("Provider", fact.label if fact else self.draft.provider))
        if self.draft.base_url:
            rows.append(("Endpoint", self.draft.base_url))
        if self.draft.credential is not CredentialSource.NONE:
            rows.append(("Credential", _credential_words(self.draft)))
        if self.draft.model:
            rows.append(("Model", self.draft.model))
        rows.append(("Workspace", str(self._staged.paths.project)))
        rows.append(("GitHub", _github_words(self)))
        if self.validation.check is not Check.IDLE:
            rows.append(("Validated", _check_words(self.validation.check)))
        return tuple(rows)

    def _fact(self, provider_id: str) -> ProviderFact | None:
        return next((fact for fact in self.facts if fact.id == provider_id), None)

    # -- starting --------------------------------------------------------- #

    def start(self) -> Effect:
        """Detect what is here and stand on the first real question.

        Offered progress is restored if there is any; the host decides whether
        to ask about it, and `continue_from` applies the answer.
        """
        self.facts = detect_providers(self._staged, environment=self._env())
        if self._checkpointed:
            self.resumed = read_checkpoint(self.config)
        self._advance_to_first_step()
        return self._effect_for_step()

    def _env(self) -> Any:
        return self._environment

    def continue_from_checkpoint(self) -> Effect:
        """Pick up where an interrupted run got to.

        Deliberately does not restore a credential. If the step that was
        interrupted needed one, the person types it again — trading one
        re-entry against never writing a secret into a file is not a close
        call.
        """
        saved = self.resumed
        if saved is None:
            return self.start()
        draft = Draft(
            provider=saved.provider,
            credential=_credential(saved.credential),
            env_variable=saved.env_variable,
            base_url=saved.base_url,
            model=saved.model,
            model_typed=saved.model_typed,
            github=_intent(saved.github),
        )
        # A stored credential is still there; a typed one is not, so a step
        # that depended on it goes back to being asked.
        if draft.credential is CredentialSource.ENTERED:
            draft = replace(draft, credential=CredentialSource.ENTERED, model="")
        self.draft = draft
        self.step = _step(saved.step) or Step.PROVIDER
        return self._settle()

    def start_over(self) -> Effect:
        """Throw the saved progress away and begin again."""
        clear_checkpoint(self.config)
        self.resumed = None
        self.draft = Draft()
        self.validation = Validation()
        self.github = GitHub()
        self._installation = None
        self.error = ""
        self.step = Step.PROVIDER
        return self._advance_to_first_step()

    def _advance_to_first_step(self) -> Effect:
        """Skip the questions this machine has already answered.

        A provider that works here, with a key already available and a model
        already chosen, is not a question — it is a fact to confirm. Asking it
        anyway is what makes re-running setup feel like a fresh install.
        """
        active = self._fact(self._staged.provider)
        if active is not None and active.usable_here and self._staged.active_model():
            self.draft = Draft(
                provider=active.id,
                credential=active.credential,
                env_variable=active.env_variable if
                active.credential is CredentialSource.ENVIRONMENT else "",
                base_url=str(self._staged.providers[active.id].base_url or ""),
                model=self._staged.active_model(),
                github=self.draft.github,
            )
            self.step = Step.GITHUB
            return self._enter_github()
        if active is not None and active.usable_here:
            self.draft = Draft(
                provider=active.id,
                credential=active.credential,
                env_variable=active.env_variable if
                active.credential is CredentialSource.ENVIRONMENT else "",
                base_url=str(self._staged.providers[active.id].base_url or ""),
            )
            self.step = Step.MODEL
            return self._enter_model()
        self.step = Step.PROVIDER
        return Effect()

    # -- transitions ------------------------------------------------------ #

    def choose_provider(self, provider_id: str, *, base_url: str = "") -> Effect:
        """Pick a provider. Resets everything downstream of it.

        Going back and choosing differently must not leave the previous
        provider's model, endpoint or validation on screen: a stale model list
        under a new provider is how somebody ends up configured with a model
        the provider they chose has never heard of.
        """
        self._require(Step.PROVIDER, Step.MODEL, Step.CREDENTIAL, Step.READY,
                      Step.GITHUB)
        fact = self._fact(provider_id)
        if fact is None:
            raise SetupError(f"no provider named {provider_id!r}")
        # A custom endpoint's address is part of choosing it when it is given
        # here, and part of the credential step when it is not: refusing to
        # move on until a URL exists would leave somebody who picked "custom"
        # from a list staring at a list with no way in.
        endpoint = base_url.strip() if provider_id == "custom" else ""
        if endpoint:
            problem = endpoint_problem(endpoint)
            if problem:
                self.error = problem
                return Effect()
        self.error = ""
        previous = self.draft.provider
        self.draft = Draft(
            provider=provider_id,
            credential=fact.credential,
            env_variable=fact.env_variable
            if fact.credential is CredentialSource.ENVIRONMENT else "",
            base_url=endpoint or _stored_base_url(self._staged, provider_id),
        )
        # Anything learned about the old provider is about the old provider.
        self.validation = Validation()
        self._secret = ""
        if previous and previous != provider_id:
            self._bump()
        self.step = Step.CREDENTIAL if self._needs_credential() else Step.MODEL
        return self._settle()

    def set_endpoint(self, base_url: str) -> Effect:
        """A custom OpenAI-compatible endpoint's address.

        Accepted at any unfinished step, for the same reason the workspace is:
        noticing a typo on the Ready screen should cost one correction, not a
        walk back through three questions.
        """
        if self.finished:
            raise SetupError("setup is already finished")
        endpoint = base_url.strip()
        problem = endpoint_problem(endpoint)
        if problem:
            self.error = problem
            return Effect()
        changed = endpoint != self.draft.base_url
        self.error = ""
        self.draft = replace(self.draft, base_url=endpoint)
        if changed:
            # A different address is a different endpoint, and whatever the old
            # one proved says nothing about this one. The typed key stays: a
            # corrected URL is not a reason to make somebody paste it again.
            self._bump()
            if self.step is Step.READY:
                # Re-proved where we are rather than by walking back to the
                # model question. The model is still the model that was
                # chosen; an endpoint that turns out to be wrong is caught by
                # the commit guard, which refuses while validation says so.
                self.validation = Validation(check=Check.CHECKING,
                                             attempt=self._attempt)
                self._save_progress()
                return Effect(kind=EffectKind.DISCOVER, attempt=self._attempt,
                              provider=self.draft.provider,
                              base_url=self.draft.base_url,
                              model=self.draft.model)
            self.validation = Validation()
            return self._settle()
        return Effect()

    def choose_credential(self, source: CredentialSource) -> Effect:
        """Keep what is there, use the environment's, or replace it."""
        self._require(Step.CREDENTIAL, Step.READY, Step.MODEL)
        fact = self._fact(self.draft.provider)
        if fact is None:
            raise SetupError("no provider has been chosen")
        if source is CredentialSource.EXISTING and not fact.has_stored_key:
            raise SetupError("there is no stored credential to keep")
        if source is CredentialSource.ENVIRONMENT and not fact.has_env_key:
            raise SetupError("there is no environment key to use")
        self.draft = replace(
            self.draft, credential=source,
            env_variable=fact.env_variable
            if source is CredentialSource.ENVIRONMENT else "")
        if source is not CredentialSource.ENTERED:
            self._secret = ""
        self.error = ""
        self.step = Step.MODEL
        return self._settle()

    def submit_credential(self, secret: str) -> Effect:
        """Take a typed key. Held apart from everything serializable.

        The value goes no further than this object and the probe the host asks
        for: not into the draft, not into the checkpoint, not into the
        snapshot, not into a repr.
        """
        self._require(Step.CREDENTIAL, Step.MODEL)
        value = secret.strip()
        if not value:
            self.error = "That was empty. Paste the key, or go back and choose " \
                         "a provider that does not need one."
            return Effect()
        self.error = ""
        self._secret = value
        self.draft = replace(self.draft, credential=CredentialSource.ENTERED,
                             env_variable="")
        # A new key invalidates whatever the old one proved.
        self.validation = Validation()
        self._bump()
        self.step = Step.MODEL
        return self._settle()

    def choose_model(self, model: str, *, typed: bool = False) -> Effect:
        """Pick a model. `typed` says it did not come from a discovered list."""
        self._require(Step.MODEL, Step.READY)
        value = model.strip()
        if not value:
            self.error = "Choose a model, or type one."
            return Effect()
        self.error = ""
        known = set(self.validation.models)
        self.draft = replace(
            self.draft, model=value,
            model_typed=bool(typed) or value not in known)
        self.step = Step.GITHUB
        return self._enter_github()

    def retry_validation(self) -> Effect:
        """Try the probe again, without losing anything else."""
        self._require(Step.MODEL, Step.READY, Step.CREDENTIAL)
        self.error = ""
        return self._enter_model()

    def use_unverified(self) -> Effect:
        """Continue without a validation that could not be made.

        An explicit choice rather than a silent pass: some endpoints have no
        model-list call, and refusing to proceed would make them unusable, but
        claiming they work when nothing checked would be a lie.
        """
        self._require(Step.MODEL)
        if self.validation.check not in (Check.UNVERIFIED, Check.NO_MODELS,
                                         Check.IDLE):
            raise SetupError("nothing to continue past")
        self.validation = replace(self.validation, check=Check.UNVERIFIED,
                                  reason="not checked; you chose to continue")
        if not self.draft.model:
            self.error = "Say which model to use, then continue."
            return Effect()
        self.error = ""
        self.draft = replace(self.draft, model_typed=True)
        self.step = Step.GITHUB
        return self._enter_github()

    def set_workspace(self, path: str) -> Effect:
        """Point the session somewhere else.

        Allowed at any unfinished step rather than only at a workspace step of
        its own: where the agent will work is a fact about the whole setup, and
        somebody who notices it is wrong on the Ready screen should not have to
        walk back three questions to fix it.
        """
        if self.finished:
            raise SetupError("setup is already finished")
        target = Path(path).expanduser()
        try:
            target = target.resolve(strict=True)
        except (OSError, RuntimeError):
            self.error = f"There is no folder at {path}."
            return Effect()
        if not target.is_dir():
            self.error = f"{target} is a file, not a folder."
            return Effect()
        self.error = ""
        # `Paths` is frozen, and deliberately: the directories a run works in
        # are decided once, so this is a new one rather than an assignment.
        self._staged.paths = replace(self._staged.paths, project=target)
        return self._settle()

    # -- GitHub ----------------------------------------------------------- #

    def _enter_github(self) -> Effect:
        self.step = Step.GITHUB
        if self._staged.github.installations:
            # Already connected. Re-running setup is not a reason to mint
            # another installation or re-open a browser.
            self.github = GitHub(step=GitHubStep.KEPT,
                                 account=_account_of(self._staged))
            self._save_progress()
            return Effect()
        self.github = GitHub(step=GitHubStep.NOT_CONNECTED)
        self._save_progress()
        return Effect()

    def connect_github(self) -> Effect:
        """Begin the browser flow."""
        self._require(Step.GITHUB, Step.READY)
        self.error = ""
        self._bump()
        self.github = GitHub(step=GitHubStep.STARTING,
                             attempt=self._attempt)
        return Effect(kind=EffectKind.GITHUB_BEGIN, attempt=self._attempt)

    def skip_github(self) -> Effect:
        """Skip it. Skipping is a successful setup, not an incomplete one."""
        self._require(Step.GITHUB, Step.READY)
        self.error = ""
        self._bump()
        self._installation = None
        self.github = GitHub(step=GitHubStep.SKIPPED, attempt=self._attempt)
        self.draft = replace(self.draft, github=GitHubIntent.SKIP)
        self.step = Step.READY
        self._save_progress()
        return Effect()

    def keep_github(self) -> Effect:
        """Leave an existing connection alone."""
        self._require(Step.GITHUB, Step.READY)
        self.error = ""
        self.draft = replace(self.draft, github=GitHubIntent.KEEP)
        self.step = Step.READY
        self._save_progress()
        return Effect()

    def cancel_github(self) -> Effect:
        """Stop waiting. Nothing is connected and nothing is written."""
        self._require(Step.GITHUB, Step.READY)
        self._bump()
        self._installation = None
        self.github = GitHub(step=GitHubStep.CANCELLED, attempt=self._attempt,
                             detail="Nothing was connected.")
        self.error = ""
        return Effect()

    def report_github_started(self, attempt: int, *, url: str, opened: bool,
                              seconds_left: float,
                              automatic: bool) -> Effect:
        """The flow was created. Automatic means no receipt is needed."""
        if not self._current(attempt):
            return Effect()
        if not automatic:
            # An older worker that cannot hold a result. Setup does not ask
            # anybody to copy a receipt: that path stays where it already
            # lives, in `comodor github connect`.
            self.github = GitHub(step=GitHubStep.FAILED, attempt=attempt,
                                 detail="This connection needs a newer "
                                        "endpoint. Try again later, or run "
                                        "comodor github connect.")
            return Effect()
        self.github = GitHub(
            step=GitHubStep.OPENED if opened else GitHubStep.STARTING,
            url=url, opened=opened, seconds_left=max(0.0, seconds_left),
            attempt=attempt)
        self._bump()
        return Effect(kind=EffectKind.GITHUB_WAIT, attempt=self._attempt)

    def report_github(self, attempt: int, outcome: GitHubOutcome) -> bool:
        """How the wait ended. A stale attempt is dropped, not applied.

        Returns whether the outcome was accepted, so a host can tell "I
        changed the state" from "this was already over".
        """
        if not self._current(attempt):
            return False
        self.github = replace(
            self.github, step=outcome.step, account=outcome.account,
            detail=outcome.detail, attempt=attempt,
            # The link belonged to the attempt that just ended. Keeping it
            # would offer somebody a URL that has already expired or been
            # cancelled, and a browser reopened on it lands somewhere with no
            # result waiting.
            url="", opened=False, seconds_left=0.0)
        if outcome.step is GitHubStep.CONNECTED and outcome.installation is not None:
            # Verified by the connector before it got here: the grant was
            # checked and the local key was written. Held, not committed —
            # that happens with everything else, once, at the end.
            self._installation = outcome.installation
            self.step = Step.READY
            self._save_progress()
            return True
        self._installation = None
        # A failure stays on the GitHub step so it can be retried or skipped.
        # Being thrown back to the provider list because a poll got a 502
        # would be a restart nobody asked for.
        self._save_progress()
        return True

    # -- reporting a probe ------------------------------------------------ #

    def report_discovery(self, attempt: int, result: Discovery) -> bool:
        """What the provider probe found, if it is still the current question.

        This is the guard that makes "go back and choose another provider"
        safe: the slow answer from the provider nobody wants any more arrives,
        is recognised as stale, and is dropped on the floor rather than
        repopulating a screen about something else.
        """
        if not self._current(attempt):
            return False
        models = tuple(result.models)
        self.validation = Validation(check=result.check, reason=result.reason,
                                     models=models, attempt=attempt)
        # A discovered list with one entry is not a choice, it is an answer.
        if result.check is Check.VALID and models and not self.draft.model:
            self.draft = replace(self.draft, model=models[0])
        self._save_progress()
        return True

    # -- finishing -------------------------------------------------------- #

    def back(self) -> Effect:
        """Correct an earlier answer without starting over."""
        if not self.can_go_back:
            raise SetupError("there is nothing before this")
        self.error = ""
        if self.step is Step.READY:
            self.step = Step.GITHUB
            return self._enter_github()
        if self.step is Step.GITHUB:
            # Leaving the GitHub step abandons a flow that was only ever
            # waiting; nothing has been written either way.
            self._bump()
            self._installation = None
            self.github = GitHub(step=GitHubStep.CANCELLED,
                                 attempt=self._attempt)
            self.step = Step.MODEL
            return self._settle()
        if self.step is Step.MODEL:
            self.step = (Step.CREDENTIAL if self._needs_credential()
                         else Step.PROVIDER)
            self._bump()
            self.validation = Validation()
            return Effect()
        self.step = Step.PROVIDER
        self._bump()
        return Effect()

    def commit(self) -> Config:
        """Write everything, once. The only place setup touches the disk.

        Returns the configuration that was saved. If this raises, nothing was
        written and the previous configuration is still the one on disk.
        """
        if self._committed:
            raise SetupError("setup has already been committed")
        if self.step is not Step.READY:
            raise SetupError(f"setup is not finished (at {self.step.value})")
        problem = self.blocking_problem()
        if problem:
            raise SetupError(problem)

        staged = self._staged
        staged.use(self.draft.provider,
                   api_key=self._secret if
                   self.draft.credential is CredentialSource.ENTERED else "",
                   model=self.draft.model, base_url=self.draft.base_url)
        if self._installation is not None:
            staged.github.remember(self._installation)
            staged.github.enabled = True
        staged.first_run = False

        staged.save()
        self._committed = True
        self.step = Step.DONE
        # Finished. Leaving the progress file behind would mean the next run
        # offering to resume a setup that already succeeded.
        clear_checkpoint(self.config)
        self._secret = ""
        return staged

    def cancel(self) -> None:
        """Abandon. The staged configuration is simply dropped."""
        self.step = Step.CANCELLED
        self._bump()
        self._secret = ""
        self._installation = None

    def blocking_problem(self) -> str:
        """Why this cannot be committed yet, or an empty string."""
        if not self.draft.provider:
            return "No provider has been chosen."
        if self.draft.provider == "custom" and not self.draft.base_url:
            return "A custom endpoint needs its URL."
        if not self.draft.model:
            return "No model has been chosen."
        if self._needs_credential() and self.draft.credential is CredentialSource.ENTERED \
                and not self._secret:
            return "A credential is still needed."
        if self.validation.check is Check.INVALID:
            return "The provider refused that credential. Fix it or choose " \
                   "another provider."
        return ""

    # -- the host's side of the secret ------------------------------------ #

    def probe_entry(self) -> Any:
        """A provider entry to validate with, key included.

        The one path by which the credential reaches the network. The object is
        transient, its ``api_key`` is excluded from its own repr, and it is
        never handed to anything that serializes.
        """
        from .config import provider_from_spec

        fact = self._fact(self.draft.provider)
        entry = copy.deepcopy(self._staged.providers.get(self.draft.provider))
        if entry is None:
            spec = catalogue.get(self.draft.provider)
            entry = provider_from_spec(spec) if spec else None
        if entry is None:
            return None
        if self.draft.base_url:
            entry.base_url = self.draft.base_url.rstrip("/")
        if self.draft.credential is CredentialSource.ENTERED and self._secret:
            entry.api_key = self._secret
        elif fact is not None and fact.has_env_key and fact.env_variable:
            entry.api_key = str(os.environ.get(fact.env_variable, ""))
        return entry

    # -- internals -------------------------------------------------------- #

    def _require(self, *steps: Step) -> None:
        if self.step not in steps:
            raise SetupError(
                f"cannot do that while at {self.step.value}")

    def _needs_credential(self) -> bool:
        """Whether the person has to supply something.

        False when the provider needs no key, when the environment already has
        one, and when one is already stored — in each of those there is nothing
        to type, and asking anyway is how setup ends up requesting a key
        somebody already gave.
        """
        fact = self._fact(self.draft.provider)
        if fact is None:
            return False
        if not fact.needs_key:
            return False
        if fact.has_env_key or fact.has_stored_key:
            return self.draft.credential is CredentialSource.ENTERED
        return True

    def _bump(self) -> int:
        """A new attempt, which retires every result still in flight."""
        self._attempt += 1
        return self._attempt

    def _current(self, attempt: int) -> bool:
        return attempt == self._attempt and attempt > 0

    def _settle(self) -> Effect:
        """Do whatever the current step needs doing, once."""
        if self.step is Step.CREDENTIAL:
            if not self._needs_credential():
                self.step = Step.MODEL
            else:
                self._save_progress()
                return Effect()
        if self.step is Step.MODEL:
            return self._enter_model()
        if self.step is Step.GITHUB:
            return self._enter_github()
        if self.step is Step.READY:
            self._save_progress()
        return Effect()

    def _enter_model(self) -> Effect:
        """Ask the provider what it has, which is also how the key is proved.

        A model list is the cheapest authenticated call there is: it proves the
        credential and the endpoint in one request and costs no tokens, where a
        generation would spend money to prove something already proven.
        """
        self.step = Step.MODEL
        self._bump()
        self.validation = Validation(check=Check.CHECKING, attempt=self._attempt)
        self._save_progress()
        return Effect(kind=EffectKind.DISCOVER, attempt=self._attempt,
                      provider=self.draft.provider,
                      base_url=self.draft.base_url, model=self.draft.model)

    def _effect_for_step(self) -> Effect:
        return self._settle()

    def _save_progress(self) -> None:
        if not self._checkpointed or self.finished:
            return
        write_checkpoint(self.config, Checkpoint(
            step=self.step.value,
            provider=self.draft.provider,
            credential=self.draft.credential.value,
            env_variable=self.draft.env_variable,
            base_url=self.draft.base_url,
            model=self.draft.model,
            model_typed=self.draft.model_typed,
            github=self.draft.github.value,
        ))


def _credential(value: str) -> CredentialSource:
    try:
        return CredentialSource(value)
    except ValueError:
        return CredentialSource.NONE


def _intent(value: str) -> GitHubIntent:
    try:
        return GitHubIntent(value)
    except ValueError:
        return GitHubIntent.ASK


def _step(value: str) -> Step | None:
    try:
        return Step(value)
    except ValueError:
        return None


def _stored_base_url(config: Config, provider_id: str) -> str:
    entry = config.providers.get(provider_id)
    if entry is None:
        return ""
    spec = catalogue.get(provider_id)
    stored = str(entry.base_url or "")
    # A stored URL that is just the catalogue default is not a custom
    # endpoint, and carrying it across to another provider would point that
    # provider at somebody else's server.
    if spec is not None and stored.rstrip("/") == spec.base_url.rstrip("/"):
        return ""
    return stored if provider_id == "custom" else ""


def _account_of(config: Config) -> str:
    """The login a person recognises, from the installation record.

    `account_login` rather than the numeric id: "ifekri" is what somebody
    remembers installing, and 49218334 is not.
    """
    for entry in config.github.installations:
        login = getattr(entry, "account_login", "")
        if login:
            return str(login)
    return "connected"


def _credential_words(draft: Draft) -> str:
    if draft.credential is CredentialSource.ENVIRONMENT and draft.env_variable:
        return f"from ${draft.env_variable}"
    return {
        CredentialSource.EXISTING: "already stored here",
        CredentialSource.IMPORTED: "imported",
        CredentialSource.ENTERED: "set",
        CredentialSource.NONE: "not needed",
    }.get(draft.credential, "set")


def _github_words(plan: SetupPlan) -> str:
    step = plan.github.step
    if step is GitHubStep.CONNECTED:
        return f"connected ({plan.github.account})" if plan.github.account \
            else "connected"
    if step is GitHubStep.KEPT:
        return f"already connected ({plan.github.account})"
    if step is GitHubStep.SKIPPED:
        return "skipped"
    if step is GitHubStep.NOT_CONNECTED:
        return "not connected"
    return step.value


def _check_words(check: Check) -> str:
    return {
        Check.VALID: "yes",
        Check.INVALID: "no — credential refused",
        Check.UNREACHABLE: "not reachable",
        Check.NO_MODELS: "reachable, no models offered",
        Check.UNVERIFIED: "not checked",
        Check.CHECKING: "checking…",
        Check.IDLE: "not checked",
    }.get(check, check.value)


# --------------------------------------------------------------------------- #
# what a probe means
# --------------------------------------------------------------------------- #

def classify_probe(problem: BaseException) -> tuple[Check, str]:
    """Turn a provider failure into a truthful state and a usable sentence.

    The distinction that matters is between "your key is wrong" and "we could
    not reach them": the first sends somebody to rotate a credential, the
    second sends them to wait a moment and retry. Collapsing them is the reason
    a wizard that says "invalid key" during an outage gets its user's key
    revoked for nothing.
    """
    from .providers.base import AuthError, ProviderError, RateLimited

    if isinstance(problem, AuthError):
        return Check.INVALID, "The provider rejected that credential."
    if isinstance(problem, RateLimited):
        return Check.UNREACHABLE, "The provider is rate-limiting. Try again " \
                                  "in a moment."
    if isinstance(problem, ProviderError):
        status = getattr(problem, "status", None)
        if status in (401, 403):
            return Check.INVALID, "The provider rejected that credential."
        if status is not None and status >= 500:
            return Check.UNREACHABLE, f"The provider returned {status}. " \
                                      "Nothing wrong on this side; retry."
        if status == 404:
            return Check.UNVERIFIED, "That endpoint has no model list, so " \
                                     "nothing could be checked."
        if getattr(problem, "retryable", False):
            return Check.UNREACHABLE, "Could not reach the provider."
        return Check.INVALID, "The provider refused the request."
    # Not a provider error at all: DNS, a refused connection, a timeout, a TLS
    # problem. All of them are "not reachable", none of them is a bad key.
    return Check.UNREACHABLE, f"Could not reach the provider ({_kind(problem)})."


def _kind(problem: BaseException) -> str:
    """The exception's name, which is safe to show; never its arguments."""
    return type(problem).__name__


def endpoint_problem(url: str) -> str:
    """What is wrong with a custom endpoint, or an empty string.

    Checked before anything is sent anywhere: a URL that carries a key in its
    query string would be written into a config file, printed back on a recap
    screen, and handed to a process that logs its arguments.
    """
    if not url:
        return "An endpoint needs a URL."
    if not url.startswith(("https://", "http://")):
        return "The URL has to start with https:// (or http:// for a local " \
               "server)."
    from urllib.parse import urlsplit

    try:
        parts = urlsplit(url)
    except ValueError:
        return "That is not a URL this machine can parse."
    if not parts.hostname:
        return "That URL has no host in it."
    if parts.query or parts.fragment:
        return "Leave the query string off — a key in a URL ends up in shell " \
               "history, logs and this config file."
    if parts.username or parts.password:
        return "Take the credentials out of the URL; they belong in the key " \
               "field, not in the address."
    return ""


def normalize_endpoint(url: str) -> str:
    """The stored form of a custom endpoint."""
    return url.strip().rstrip("/")
