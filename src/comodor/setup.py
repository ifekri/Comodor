"""First-run setup: a few questions, asked once.

The first minute with a tool decides whether there is a second one. So Comodor
does not ask anybody to find a dotfile, learn an environment variable or read
documentation before their first task — it asks what it needs, in the terminal,
with the answers numbered, and writes them down.

Two ways of asking, and the second one is not optional.

On a real terminal each question arrives on a screen of its own: what has
already been answered is summarised in two or three quiet lines at the top, and
below it one framed list you move through with the arrow keys. Questions no
longer pile up — by the fourth one the terminal used to be a transcript of
decisions already made — and a provider with sixty models is a list you can
filter by typing rather than sixty numbered rows to read.

Anywhere without a terminal — a pipe, a test, an editor's console — the
numbered prompt is exactly what it was. A setup wizard that only works in one
kind of terminal is a setup wizard that cannot be scripted, and the first thing
a new user meets must not be a mode their terminal might not support.
"""

from __future__ import annotations

import getpass
from dataclasses import dataclass
from typing import Callable, Sequence

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from . import catalogue
from .config import Config
from .ui import chooser
from .ui import console as console_module
from .ui.theme import Theme

#: Injected in tests so the wizard can be driven without a terminal.
Prompt = Callable[[str], str]
Secret = Callable[[str], str]


@dataclass
class Answers:
    """What the wizard collected, before anything is written."""

    provider: str = ""
    api_key: str = ""
    model: str = ""
    base_url: str = ""
    mode: str = "act"
    approvals: str = "ask"
    theme: str = "ember"


class SetupWizard:
    """Asks the questions and applies the answers to a :class:`Config`."""

    def __init__(self, config: Config, console: Console | None = None,
                 theme: Theme | None = None, prompt: Prompt | None = None,
                 secret: Secret | None = None) -> None:
        self.config = config
        self.theme = theme or console_module.prepare_theme(
            config.ui.theme, config.ui.ascii_borders, no_color=False)
        self.console = console or console_module.build(self.theme)
        self._prompt = prompt or (lambda message: input(message))
        self._secret = secret or (lambda message: getpass.getpass(message))
        # An injected prompt means somebody is driving this without a keyboard,
        # so the interactive list is off whatever the terminal says it can do.
        self._keys = prompt is None and chooser.interactive(self.console)
        #: What has been answered so far, shown at the top of each screen.
        self._done: list[tuple[str, str]] = []

    # -- presentation ----------------------------------------------------- #

    def _rule(self, title: str, step: int, total: int) -> None:
        """Start a question.

        On a real terminal this is where the screen is cleared. The alternative
        — letting the questions stack — meant that by the last one the useful
        part of the screen was a few lines at the bottom under a wall of
        choices already made. What replaces the wall is the same information in
        one line each, which is all it was ever worth.
        """
        if self._keys:
            self.console.clear()
            self._recap()
        self.console.print()
        self.console.print(
            Text.assemble(
                (f" {step}/{total} ", self.theme.style("accent", bold=True)),
                (title, self.theme.style("title", bold=True)),
            )
        )

    def _recap(self) -> None:
        """The questions already answered, one quiet line each."""
        if not self._done:
            self.console.print(
                Text("  Comodor setup", style=self.theme.style("dim")))
            return
        for label, value in self._done:
            self.console.print(Text.assemble(
                ("  ✓ ", self.theme.style("good")),
                (f"{label}  ", self.theme.style("dim")),
                (value, self.theme.style("value")),
            ))

    def _answered(self, label: str, value: str) -> None:
        self._done.append((label, value))
        if not self._keys:
            return
        # Echoed once here, because the list it came from is erased on the way
        # out: a choice that leaves no trace reads as a choice that did not
        # register.
        self.console.print(Text.assemble(
            ("  ✓ ", self.theme.style("good")),
            (value, self.theme.style("value", bold=True)),
        ))

    def _choose(self, options: Sequence[tuple[str, str, str]], default: int = 1,
                title: str = "") -> str:
        """Return the chosen value, by arrow key or by number.

        ``options`` is ``(value, label, note)``. The numbered path re-asks on a
        bad answer rather than falling through to a default the user did not
        pick — a silent wrong choice here is one they would have to undo later.
        """
        if self._keys:
            picked = chooser.choose(
                self.console, self.theme,
                [chooser.Option(value, label, note) for value, label, note in options],
                title=title, default=default - 1,
            )
            if picked is not None:
                return picked
            # The list could not run, or was escaped out of. Either way the
            # question still needs an answer, so the numbered form takes over.

        table = Table.grid(padding=(0, 2))
        table.add_column(justify="right", no_wrap=True)
        table.add_column(no_wrap=True)
        table.add_column()

        for index, (_, label, note) in enumerate(options, start=1):
            marker = f"{index}."
            table.add_row(
                Text(marker, style=self.theme.style("accent")),
                Text(label, style=self.theme.style("value", bold=index == default)),
                Text(note, style=self.theme.style("dim")),
            )
        self.console.print(table)

        while True:
            raw = self._prompt(f"  choice [{default}]: ").strip()
            if not raw:
                return options[default - 1][0]
            if raw.isdigit() and 1 <= int(raw) <= len(options):
                return options[int(raw) - 1][0]
            self.console.print(
                Text(f"  enter a number between 1 and {len(options)}",
                     style=self.theme.style("bad")))

    def _ask(self, message: str, default: str = "") -> str:
        suffix = f" [{default}]" if default else ""
        answer = self._prompt(f"  {message}{suffix}: ").strip()
        return answer or default

    # -- the questions ---------------------------------------------------- #

    def run(self) -> Answers:
        total = 4
        self._banner()

        answers = Answers()
        answers.provider = self._ask_provider(1, total)
        spec = catalogue.get(answers.provider)

        if answers.provider == "custom":
            answers.base_url = self._ask_endpoint()
        if spec is not None and spec.needs_key or answers.provider == "custom":
            answers.api_key = self._ask_key(2, total, spec)
        else:
            self._rule("API key", 2, total)
            self.console.print(
                Text("  Not needed — this one runs on your machine.",
                     style=self.theme.style("dim")))
            self._answered("api key", "not needed")

        answers.model = self._ask_model(3, total, spec, answers)
        answers.approvals = self._ask_approvals(4, total)
        return answers

    def _banner(self) -> None:
        body = Text.assemble(
            ("Comodor", self.theme.style("accent", bold=True)),
            (" — it learns the way you correct it.\n\n", self.theme.style("text")),
            ("A few questions, once. The answers are saved to\n",
             self.theme.style("dim")),
            (str(self.config.paths.config_file), self.theme.style("value")),
            ("\nand you will not be asked again. Change anything later with ",
             self.theme.style("dim")),
            ("/settings", self.theme.style("accent")),
            (".", self.theme.style("dim")),
        )
        self.console.print()
        self.console.print(Panel(body, box=self.theme.box,
                                 border_style=self.theme.style("border"),
                                 padding=(1, 2)))

    def _ask_provider(self, step: int, total: int) -> str:
        self._rule("Which model provider?", step, total)
        self.console.print(
            Text("  You can add more later; this is just the one to start with.\n",
                 style=self.theme.style("dim")))
        options = [(spec.id, spec.label, spec.blurb) for spec in catalogue.offered()]
        chosen = self._choose(options, default=1, title="Providers")
        self._answered("provider", dict((v, l) for v, l, _ in options).get(chosen, chosen))
        return chosen

    def _ask_endpoint(self) -> str:
        self.console.print()
        return self._ask("OpenAI-compatible base URL", "https://")

    def _ask_key(self, step: int, total: int,
                 spec: catalogue.ProviderSpec | None) -> str:
        self._rule("API key", step, total)
        if spec and spec.keys_url:
            self.console.print(Text.assemble(
                ("  Get one at ", self.theme.style("dim")),
                (spec.keys_url, self.theme.style("accent")),
            ))
        self.console.print(
            Text("  It is stored in your config file and never sent anywhere but "
                 "the provider.\n", style=self.theme.style("dim")))

        while True:
            # Masked: keys get pasted in shared terminals and shoulder-surfed
            # off screen recordings.
            key = self._secret("  key (input hidden): ").strip()
            if key:
                self._answered("api key", "set, and never shown again")
                return key
            self.console.print(Text("  a key is required for this provider",
                                    style=self.theme.style("bad")))

    def _ask_model(self, step: int, total: int,
                   spec: catalogue.ProviderSpec | None, answers: Answers) -> str:
        # Discovery first, and the question afterwards, because asking the
        # provider what it has takes a second or two over the network. During
        # that second the terminal is still in its ordinary mode, so anything
        # impatient fingers press is echoed — an arrow key arrives on screen as
        # `^[[B` and sits there. Clearing for the question is what wipes it, so
        # the clearing has to come second. The keystrokes themselves are
        # discarded when the reader takes the terminal.
        models = self._discover_models(spec, answers)

        self._rule("Which model?", step, total)
        if not models:
            return self._ask("model id", spec.default_model if spec else "")

        options = [(model, model, "recommended" if index == 0 else "")
                   for index, model in enumerate(models)]
        options.append(("__other__", "something else", "type the model id"))
        chosen = self._choose(options, default=1, title="Models")
        if chosen == "__other__":
            chosen = self._ask("model id", models[0])
        self._answered("model", chosen)
        return chosen

    def _discover_models(self, spec: catalogue.ProviderSpec | None,
                         answers: Answers) -> list[str]:
        """Ask the provider what it has, and fall back to the known list.

        Live discovery is worth a couple of seconds here: a stale hard-coded
        list is how a setup wizard ends up recommending a model that was retired
        six months ago.
        """
        if spec is None:
            return []
        self.console.print(Text("  checking what this provider offers…",
                                style=self.theme.style("dim")))
        try:
            from .providers.gateway import build_provider

            entry = self.config.providers.get(spec.id)
            if entry is None:
                return list(spec.models)
            probe = build_provider(_with(entry, answers))
            live = probe.list_models()
            close = getattr(probe, "close", None)
            if close:
                close()
        except Exception:
            live = []

        if not live:
            return list(spec.models)

        # Put the models we know are good first, then everything else.
        known = [model for model in spec.models if model in live]
        rest = [model for model in live if model not in known]
        return (known + rest)[:12]

    def _ask_approvals(self, step: int, total: int) -> str:
        self._rule("How much should it ask before acting?", step, total)
        options = [
            ("ask", "Ask before writing or running anything",
             "safest; you see a diff or the command first"),
            ("writes", "Write files freely, ask before running commands",
             "a good middle ground"),
            ("auto", "Do not ask", "fastest; everything is still checkpointed"),
        ]
        chosen = self._choose(options, default=1, title="Approvals")
        self._answered("approvals",
                       dict((v, l) for v, l, _ in options).get(chosen, chosen))
        return chosen

    # -- applying --------------------------------------------------------- #

    def apply(self, answers: Answers) -> Config:
        config = self.config
        config.use(answers.provider, api_key=answers.api_key,
                   model=answers.model, base_url=answers.base_url)

        config.safety.auto_approve_writes = answers.approvals in ("writes", "auto")
        config.safety.auto_approve_shell = answers.approvals == "auto"
        config.agent.mode = answers.mode
        config.ui.theme = answers.theme

        model_info = _model_info(answers.model)
        if model_info is not None:
            config.agent.context_limit = model_info

        config.save()
        config.first_run = False
        return config

    def finish(self, config: Config) -> None:
        entry = config.active()
        body = Text.assemble(
            ("Ready.\n\n", self.theme.style("good", bold=True)),
            ("  provider  ", self.theme.style("label")),
            (f"{entry.display if entry else '—'}\n", self.theme.style("value")),
            ("  model     ", self.theme.style("label")),
            (f"{config.active_model()}\n", self.theme.style("value")),
            ("  saved to  ", self.theme.style("label")),
            (f"{config.paths.config_file}\n\n", self.theme.style("value")),
            ("Type a task and press Enter. ", self.theme.style("dim")),
            ("/help", self.theme.style("accent")),
            (" lists everything.", self.theme.style("dim")),
        )
        self.console.print()
        self.console.print(Panel(body, box=self.theme.box,
                                 border_style=self.theme.style("good"),
                                 padding=(1, 2)))
        self.console.print()


def _with(entry, answers: Answers):
    """A copy of the provider entry carrying the answers given so far."""
    # dataclasses.replace, not copy.replace: the latter is 3.13 and Comodor
    # supports 3.11.
    from dataclasses import replace

    updates = {}
    if answers.api_key:
        updates["api_key"] = answers.api_key
    if answers.base_url:
        updates["base_url"] = answers.base_url.rstrip("/")
    return replace(entry, **updates) if updates else entry


def _model_info(model: str) -> int | None:
    """The model's context window, so the gauge starts out honest."""
    try:
        from .providers import registry

        info = registry.lookup(model)
        return info.context if info and info.context else None
    except Exception:
        return None


def run_setup(config: Config, console: Console | None = None) -> Config:
    """Run the wizard and return the saved configuration."""
    wizard = SetupWizard(config, console=console)
    answers = wizard.run()
    saved = wizard.apply(answers)
    wizard.finish(saved)
    return saved
