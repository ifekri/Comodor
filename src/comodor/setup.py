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
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Sequence

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from . import catalogue, migrate
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
    #: Skills chosen from the library, downloaded after the config is saved.
    skills: list[str] = field(default_factory=list)


class SetupWizard:
    """Asks the questions and applies the answers to a :class:`Config`."""

    def __init__(self, config: Config, console: Console | None = None,
                 theme: Theme | None = None, prompt: Prompt | None = None,
                 secret: Secret | None = None, home: Path | None = None) -> None:
        self.config = config
        #: Where to look for another agent. An argument rather than
        #: `Path.home()` reached for directly, so that a test can point it at a
        #: temporary directory instead of reading the real one.
        self.home = home
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
        self.imported = migrate.Outcome()

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

    def _choose_many(self, options: Sequence[tuple[str, str, str]],
                     title: str = "", verb: str = "choose") -> list[str]:
        """Return every chosen value. An empty list is a real answer.

        The list is tried first; without a terminal to take over, the numbered
        form asks the same question. Both accept "none", because a question
        offering four things has to accept zero as an answer without a fifth
        option that means nothing.
        """
        if self._keys:
            picked = chooser.choose_many(
                self.console, self.theme,
                [chooser.Option(value, label, note) for value, label, note in options],
                title=title, verb=verb,
            )
            if picked is not None:
                return picked
            # Escaped, or the list would not run. Either way the question is
            # still unanswered, so the numbered form takes over.

        table = Table.grid(padding=(0, 2))
        table.add_column(justify="right", no_wrap=True)
        table.add_column(no_wrap=True)
        table.add_column()
        for index, (_, label, note) in enumerate(options, start=1):
            table.add_row(
                Text(f"{index}.", style=self.theme.style("accent")),
                Text(label, style=self.theme.style("value")),
                Text(note, style=self.theme.style("dim")),
            )
        self.console.print(table)

        while True:
            raw = self._prompt("  numbers, separated by commas "
                               "(enter for none): ").strip()
            if not raw:
                return []
            wanted = [part for part in raw.replace(",", " ").split() if part]
            if all(part.isdigit() and 1 <= int(part) <= len(options)
                   for part in wanted):
                # Deduplicated, and in the order they were offered — the same
                # order the list hands back, so the two paths agree.
                taken = {int(part) - 1 for part in wanted}
                return [options[index][0] for index in sorted(taken)]
            self.console.print(
                Text(f"  numbers between 1 and {len(options)}, "
                     f"or enter for none", style=self.theme.style("bad")))

    def _ask(self, message: str, default: str = "") -> str:
        suffix = f" [{default}]" if default else ""
        answer = self._prompt(f"  {message}{suffix}: ").strip()
        return answer or default

    # -- the questions ---------------------------------------------------- #

    def run(self) -> Answers:
        self._banner()

        # Asked before anything else, because everything after it depends on
        # the answer: an imported key is a key not to ask for, and an imported
        # model is the default for the model question.
        elsewhere = self._look_for_another_agent()
        total = 5 + (1 if elsewhere else 0)
        step = 1
        if elsewhere:
            self._offer_import(elsewhere, step, total)
            step += 1

        answers = Answers()
        answers.provider = self._ask_provider(step, total)
        spec = catalogue.get(answers.provider)

        step += 1

        if answers.provider == "custom":
            answers.base_url = self._ask_endpoint()
        if spec is not None and spec.needs_key or answers.provider == "custom":
            answers.api_key = self._ask_key(step, total, spec)
        else:
            self._rule("API key", step, total)
            self.console.print(
                Text("  Not needed — this one runs on your machine.",
                     style=self.theme.style("dim")))
            self._answered("api key", "not needed")

        answers.model = self._ask_model(step + 1, total, spec, answers)
        answers.approvals = self._ask_approvals(step + 2, total)
        answers.skills = self._ask_skills(step + 3, total)
        return answers

    # ---------------------------------------------------------------- import #

    def _look_for_another_agent(self) -> list:
        """Whether there is another agent here worth importing from.

        Never fatal: somebody's first run is not the place to fail because
        another program left a file in a state this could not read.
        """
        if os.environ.get("COMODOR_NO_IMPORT"):
            return []
        try:
            return migrate.discover(self.home)
        except Exception:
            return []

    def _offer_import(self, found: list, step: int, total: int) -> None:
        names = " and ".join(entry.tool for entry in found)
        self._rule(f"You already use {names}", step, total)

        for entry in found:
            self.console.print(Text.assemble(
                ("  ", ""),
                (entry.tool, self.theme.style("accent", bold=True)),
                (f"  {entry.summary()}", self.theme.style("text")),
            ))
            self.console.print(Text(f"  {entry.root}",
                                    style=self.theme.style("dim")))
        self.console.print(Text(
            "\n  Nothing is moved and nothing already set here is replaced.",
            style=self.theme.style("dim")))
        self.console.print(Text(
            "  Keys are copied into your config; the other tool keeps working.\n",
            style=self.theme.style("dim")))

        chosen = self._choose([
            ("all", "bring it over", "keys, model and skills"),
            ("keys", "keys only", "leave the skills and the model"),
            ("no", "start fresh", "import nothing"),
        ], default=1, title="Import")

        if chosen == "no":
            self._answered("import", "nothing")
            self._report_what_was_left(found)
            return

        taken = migrate.Outcome()
        for entry in found:
            try:
                got = migrate.apply(entry, self.config, take_keys=True,
                                    take_skills=chosen == "all",
                                    take_model=chosen == "all")
            except Exception as error:            # another program's files
                self.console.print(Text(f"  could not read {entry.tool}: {error}",
                                        style=self.theme.style("bad")))
                continue
            taken.keys += got.keys
            taken.skills += got.skills
            taken.skipped += got.skipped
            taken.model = taken.model or got.model

        self.imported = taken
        self._show_what_came_over(taken)
        self._report_what_was_left(found)

        # Saved now rather than at the end of the wizard. Somebody who closes
        # the terminal at the model question should not have to find their keys
        # a second time.
        if taken.anything:
            try:
                self.config.save()
            except OSError:
                pass

    def _show_what_came_over(self, taken) -> None:
        if not taken.anything:
            self.console.print(Text("  nothing to bring over after all",
                                    style=self.theme.style("dim")))
            self._answered("import", "nothing new")
            return
        parts = []
        if taken.keys:
            parts.append(f"{len(taken.keys)} key"
                         f"{'s' if len(taken.keys) != 1 else ''} "
                         f"({', '.join(taken.keys)})")
        if taken.model:
            parts.append(f"model {taken.model}")
        if taken.skills:
            parts.append(f"{len(taken.skills)} skill"
                         f"{'s' if len(taken.skills) != 1 else ''}")
        self._answered("imported", "; ".join(parts))
        for note in taken.skipped[:4]:
            self.console.print(Text(f"  kept as it was — {note}",
                                    style=self.theme.style("dim")))

    def _report_what_was_left(self, found: list) -> None:
        """What was seen and not taken, said rather than skipped silently.

        Somebody who has a MEMORY.md in the other tool will look for it here.
        Saying why it did not come is the difference between a decision and a
        thing that appears to be broken.
        """
        notes = [note for entry in found for note in entry.passed_over]
        for note in notes[:3]:
            self.console.print(Text(f"  not imported: {note}",
                                    style=self.theme.style("dim")))

    def _ask_skills(self, step: int, total: int) -> list[str]:
        """Offer the library, once, at the only moment it is not an interruption.

        Skills are not in the package: they live on a branch and are fetched on
        request, which keeps the install small and means adding one needs no
        release. The cost of that is that nobody would ever find them, so they
        are offered here — with nothing ticked, because a setup wizard that
        installs things you did not ask for is a setup wizard people learn to
        distrust.

        As many as you like. Wanting the review skill and the test skill is the
        ordinary case, not an unusual one, and a list that took a single answer
        made the second of them somebody else's problem for another day.

        A network that is not there is not a reason to fail a first run. It
        skips, and `comodor skills browse` is still there tomorrow.
        """
        self._rule("Any skills to start with?", step, total)
        self.console.print(Text(
            "  A skill is a written procedure the agent follows when the work "
            "calls for it.\n  Take as many as you like — you can add more "
            "later with `comodor skills`.\n",
            style=self.theme.style("dim")))

        try:
            from .skills.catalogue import fetch

            catalogue = fetch(self.config.skills.catalogue_url,
                              cache_root=self.config.paths.user,
                              timeout=(4.0, 6.0))
        except Exception:
            self.console.print(Text("  (the library is not reachable right now)",
                                    style=self.theme.style("dim")))
            self._answered("skills", "none")
            return []

        if not catalogue.skills:
            self._answered("skills", "none")
            return []

        options = [(entry.id, entry.id, entry.description)
                   for entry in catalogue.skills]

        chosen = self._choose_many(options, title="Skills", verb="install")
        if not chosen:
            self._answered("skills", "none")
            return []
        self._answered("skills", ", ".join(chosen))
        return chosen

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
        # A provider that already has a key — imported a moment ago, or found
        # in the environment — leads. The key is the expensive part of setting
        # this up, and offering a default that needs a new one, immediately
        # after announcing that a key was imported, is the wizard contradicting
        # itself. Order within each group stays the catalogue's own.
        def keyed(spec: catalogue.ProviderSpec) -> bool:
            entry = self.config.providers.get(spec.id)
            return bool(entry is not None and entry.api_key)

        offered = list(catalogue.offered())
        ready = [spec for spec in offered if keyed(spec)]
        rest = [spec for spec in offered if not keyed(spec)]

        def blurb(spec: catalogue.ProviderSpec) -> str:
            if not keyed(spec):
                return spec.blurb
            why = "key imported" if spec.label in self.imported.keys \
                else "key already set"
            return f"{why} — {spec.blurb}"

        options = [(spec.id, spec.label, blurb(spec)) for spec in ready + rest]
        chosen = self._choose(options, default=1, title="Providers")
        labels = {value: label for value, label, _ in options}
        self._answered("provider", labels.get(chosen, chosen))
        return chosen

    def _ask_endpoint(self) -> str:
        self.console.print()
        return self._ask("OpenAI-compatible base URL", "https://")

    def _ask_key(self, step: int, total: int,
                 spec: catalogue.ProviderSpec | None) -> str:
        self._rule("API key", step, total)

        entry = self.config.providers.get(spec.id) if spec else None
        if spec and spec.keys_url:
            self.console.print(Text.assemble(
                ("  Get one at ", self.theme.style("dim")),
                (spec.keys_url, self.theme.style("accent")),
            ))
        # Only when there is nothing already, because it is not true of a key
        # that lives in the environment - that one is deliberately not copied
        # to disk, and the offer below says so instead.
        if entry is None or not entry.api_key:
            self.console.print(
                Text("  It is stored in your config file and never sent "
                     "anywhere but the provider.", style=self.theme.style("dim")))
        self.console.print()

        # A key that arrived from another agent, or from the environment, is
        # already a working answer to this question. Asking for it again is how
        # an import announces itself and then makes no difference.
        if entry is not None and entry.api_key:
            where, note = self._where_the_key_is(spec)
            self.console.print(Text(f"  A key for this provider is {where}.",
                                    style=self.theme.style("good")))
            if note:
                self.console.print(Text(f"  {note}", style=self.theme.style("dim")))
            keep = self._choose([
                ("keep", f"use the key {where}", "nothing to type"),
                ("replace", "enter a different one", "saved to your config file"),
            ], default=1, title="API key")
            if keep == "keep":
                self._answered("api key", f"{where}, kept")
                return ""

        while True:
            # Masked: keys get pasted in shared terminals and shoulder-surfed
            # off screen recordings.
            key = self._secret("  key (input hidden): ").strip()
            if key:
                self._answered("api key", "set, and never shown again")
                return key
            self.console.print(Text("  a key is required for this provider",
                                    style=self.theme.style("bad")))

    def _where_the_key_is(self, spec) -> tuple[str, str]:
        """Which of the three sources put this key here, and what it means.

        They no longer behave alike. An imported key and one typed here are
        written to the config file; one in the environment is deliberately not,
        because exporting a key rather than saving it is a decision. Somebody
        told only "already configured" would unset the variable one day and
        find an agent that stopped working and a file that never held a key.
        """
        if spec and spec.label in self.imported.keys:
            return "imported", ""
        if spec and spec.env_key and os.environ.get(spec.env_key, "").strip():
            return (f"set in your environment (${spec.env_key})",
                    "It stays there rather than being copied into your config "
                    "file.")
        return "already in your config file", ""

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

        # A model that came over from another agent is the one this person was
        # already using. It leads the list rather than sitting somewhere in it.
        brought = self.imported.model
        if brought and brought in models:
            models = [brought] + [m for m in models if m != brought]

        options = [(model, model,
                    "brought over" if model == brought
                    else "recommended" if index == 0 else "")
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
                       {value: label for value, label, _ in options}.get(chosen, chosen))
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

    def install_skills(self, config: Config, answers: Answers) -> list[str]:
        """Fetch what was chosen. Reported, never fatal.

        A skill that will not download is a skill the user can fetch tomorrow.
        Failing the whole first run over one is not a trade worth making, and
        the configuration is already saved by the time this runs.
        """
        if not answers.skills:
            return []

        from .skills.catalogue import CatalogueError, fetch, install

        done: list[str] = []
        try:
            catalogue = fetch(config.skills.catalogue_url,
                              cache_root=config.paths.user)
        except CatalogueError as error:
            self.console.print(Text(f"  could not reach the library: {error}",
                                    style=self.theme.style("warn")))
            return []

        config.paths.skills.mkdir(parents=True, exist_ok=True)
        for skill_id in answers.skills:
            entry = catalogue.get(skill_id)
            if entry is None:
                continue
            try:
                install(entry, catalogue, config.paths.skills)
            except CatalogueError as error:
                self.console.print(Text(f"  {skill_id}: {error}",
                                        style=self.theme.style("warn")))
                continue
            done.append(skill_id)
        return done

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
    wizard.install_skills(saved, answers)
    wizard.finish(saved)
    return saved
