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
from typing import Any, Callable, Sequence

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from . import catalogue, migrate
from .config import Config
from .onboarding import (
    Check,
    Checkpoint,
    CredentialSource,
    Discovery,
    Effect,
    EffectKind,
    GitHubIntent,
    GitHubOutcome,
    GitHubStep,
    SetupError,
    SetupPlan,
    Step,
    classify_probe,
    clear_checkpoint,
    read_checkpoint,
)
from .ui import chooser
from .ui import console as console_module
from .ui.theme import Theme

#: Injected in tests so the wizard can be driven without a terminal.
Prompt = Callable[[str], str]
Secret = Callable[[str], str]


@dataclass
class Answers:
    """What the wizard collected, before anything is written.

    The two credentials are excluded from the repr. A dataclass prints every
    field by default, so one unhandled exception anywhere in the wizard would
    put a working API key and a bot token into a traceback — and tracebacks get
    pasted into issues, screenshots and terminal scrollback.
    """

    provider: str = ""
    api_key: str = field(default="", repr=False)
    model: str = ""
    base_url: str = ""
    mode: str = "act"
    approvals: str = "ask"
    theme: str = "ember"
    #: Skills chosen from the library, downloaded after the config is saved.
    skills: list[str] = field(default_factory=list)
    #: A bot token, if one was given. Empty means the question was declined,
    #: which is the default — nothing about Telegram is switched on quietly.
    telegram_token: str = field(default="", repr=False)
    #: Accounts paired during setup. Kept here rather than written straight to
    #: the config so that abandoning the wizard leaves nothing behind.
    telegram_allowed: list[int] = field(default_factory=list)


class SetupWizard:
    """Asks the questions and applies the answers to a :class:`Config`."""

    def __init__(self, config: Config, console: Console | None = None,
                 theme: Theme | None = None, prompt: Prompt | None = None,
                 secret: Secret | None = None, home: Path | None = None,
                 github: Callable[[Config, Console], Any] | None = None) -> None:
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
        #: Whether the screen can be cleared, which is a weaker thing than
        #: being able to take over the keyboard. Over a connection where raw
        #: key reading does not work the wizard falls back to typed numbers —
        #: and used to stop clearing as well, so a hundred and forty-seven
        #: skills were printed in full underneath everything already asked.
        #: One of those two capabilities failing should not cost the other.
        self._terminal = bool(self.console.is_terminal)
        #: What has been answered so far, shown at the top of each screen.
        self._done: list[tuple[str, str]] = []
        #: The question being asked, so the typed path can redraw its own
        #: header after clearing.
        self._step: tuple[str, int, int] = ("", 0, 0)
        self.imported = migrate.Outcome()
        #: Where the decisions live.
        #:
        #: This class draws screens and collects keystrokes; it does not decide
        #: which provider is usable here, whether a probe proved anything, what
        #: a GitHub flow is waiting on, or when the configuration may be
        #: written. Those are the plan's, which is what lets a second
        #: presentation — a desktop window, say — ask the same questions in the
        #: same order and reach the same answer without this file being copied.
        #:
        #: One instance for the whole run rather than one per question, because
        #: the attempt numbers that stop a slow provider response from
        #: repopulating a screen about a different provider live on it.
        self.plan = SetupPlan(config)
        #: How the browser flow is reached. A factory rather than an instance
        #: because each attempt wants a fresh connection, and a parameter
        #: rather than an import at the call site because everything that
        #: leaves this process — the worker, the browser, the clipboard, the
        #: polling loop — belongs behind one seam. Setup's orchestration is
        #: testable without any of it; a test substitutes the factory.
        self._make_github = github or GitHubHost
        #: The effect the last transition asked for, waiting to be run.
        #:
        #: Kept rather than acted on immediately, because the plan decides what
        #: is needed and the screen decides when it is polite to go and do it —
        #: a probe started before the question it answers is drawn would print
        #: its result underneath a header nobody had read yet.
        self._effect: Effect | None = None
        #: What one probe of this machine found: a note per provider, and which
        #: local runtimes are actually up. See `_detect`.
        self._notes: dict[str, str] = {}
        self._running: set[str] = set()
        self._detected = False

    # -- presentation ----------------------------------------------------- #

    def _rule(self, title: str, step: int, total: int) -> None:
        """Start a question.

        On a real terminal this is where the screen is cleared. The alternative
        — letting the questions stack — meant that by the last one the useful
        part of the screen was a few lines at the bottom under a wall of
        choices already made. What replaces the wall is the same information in
        one line each, which is all it was ever worth.
        """
        self._step = (title, step, total)
        self._header()

    def _header(self) -> None:
        """Clear, then draw the top of the current step."""
        if self._terminal:
            self.console.clear()
            self._crown()
            self._recap()
        title, step, total = self._step
        self.console.print()
        # No counter when there is nothing to count. The closing screen is not
        # one of the numbered questions — labelling it "0/0" reads as a bug,
        # which is what it was.
        chip = (f" {step}/{total} ", self.theme.style("accent", bold=True))
        heading = (title, self.theme.style("title", bold=True))
        self.console.print(
            Text.assemble(chip, heading) if total else
            Text.assemble((" ", ""), heading))

    def _crown(self) -> None:
        """The wordmark, at the top of whatever is about to be drawn.

        Every question clears the screen, so this is a header rather than a
        repetition — without it each step arrives on a blank terminal with
        nothing on it naming the program doing the asking.

        It shrinks on a short terminal as well as on a narrow one. Five rows
        of logo on a twenty-row screen is five rows the questions do not get,
        which is the same trade the width rule already makes.
        """
        from .ui.banner import TAGLINE, wordmark

        size = self.console.size
        if size.height < 22 or size.width < 51:
            self.console.print(Text.assemble(
                ("Comodor", self.theme.style("accent", bold=True)),
                (f"  {TAGLINE}", self.theme.style("dim")),
            ))
            return
        self.console.print(wordmark(self.theme, size.width))
        self.console.print(Text(f"  {TAGLINE}", style=self.theme.style("dim")))

    def _recap(self) -> None:
        """The questions already answered, one quiet line each."""
        if not self._done:
            self.console.print(
                Text("  Comodor setup", style=self.theme.style("dim")))
            return
        for label, value in self._done:
            self.console.print(Text.assemble(
                (f"  {self.theme.glyphs.check} ", self.theme.style("good")),
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
            (f"  {self.theme.glyphs.check} ", self.theme.style("good")),
            (value, self.theme.style("value", bold=True)),
        ))

    def _choose(self, options: Sequence[tuple[str, str, str]], default: int = 1,
                title: str = "", header: bool = True) -> str:
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

        taken = self._numbered(options, multi=False, default=default,
                               header=header)
        return taken[0] if taken else options[default - 1][0]

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

        return self._numbered(options, multi=True, verb=verb)

    def _chrome(self) -> int:
        """Rows a page spends on everything that is not an option.

        Counted rather than guessed at, because one part of it grows: the
        recap gains a line per question answered, so a fixed allowance that
        fits the first question overflows the last. The skills question is the
        last one with a list, and it was the one that ran off the screen.
        """
        size = self.console.size
        small = size.height < 22 or size.width < 51
        crown = 1 if small else 7          # the wordmark, or one line instead
        recap = max(1, len(self._done))
        # A blank and the title, a blank before the list, the page note, room
        # for a complaint, and the prompt line itself.
        return crown + recap + 6

    def _numbered(self, options: Sequence[tuple[str, str, str]], *,
                  multi: bool, default: int = 1, verb: str = "choose",
                  header: bool = True) -> list[str]:
        """The same question, typed, for a terminal that will not give up keys.

        A page at a time, because this used to print the lot: the skills
        question offers a hundred and forty-seven entries with a paragraph of
        description each, and printing them meant the question itself scrolled
        off the top before it could be read. Numbers stay absolute — number 92
        is the ninety-second option whatever page or filter you are looking
        through — because a number that means something different depending on
        what you searched for is a number you cannot trust typing.
        """
        needle = ""
        page = 0
        picked: list[int] = []
        complaint = ""
        # The caller has already drawn the header for this step. Where the
        # screen can be cleared that does not matter, because the redraw below
        # replaces it — but on a plain pipe nothing is replaced, and the
        # question appeared twice, one line apart.
        drawn = not self._terminal or not header

        while True:
            matching = [(index, entry) for index, entry in enumerate(options)
                        if not needle
                        or needle in f"{entry[1]} {entry[2]}".lower()]
            per = max(5, self.console.size.height - self._chrome())
            pages = max(1, (len(matching) + per - 1) // per)
            page = max(0, min(page, pages - 1))
            window = matching[page * per:(page + 1) * per]

            if not drawn:
                self._header()
            drawn = False
            self.console.print()
            self._page(window, default if not multi else 0, picked,
                       multi=multi, width=len(str(len(options))) + 1)

            note = []
            if pages > 1:
                note.append(f"page {page + 1}/{pages}")
            if needle:
                note.append(f"matching {needle!r}")
            if multi and picked:
                note.append(f"{len(picked)} chosen")
            if note:
                self.console.print(Text("  " + "  ·  ".join(note),
                                        style=self.theme.style("dim")))
            if complaint:
                # Under the list rather than above the next prompt, because the
                # screen is redrawn each time round and anything printed before
                # the redraw is gone. Not a second prompt either: a wizard that
                # asks you to press enter to acknowledge a typo is a wizard
                # that cannot be scripted.
                self.console.print(Text(f"  {complaint}",
                                        style=self.theme.style("bad")))
                complaint = ""

            raw = self._prompt(self._numbered_prompt(
                multi, default, pages, verb, picked)).strip()
            word = raw.lower()

            if word in ("m", "more", "n", "next") and pages > 1:
                page += 1
                continue
            if word in ("b", "back", "p", "prev") and pages > 1:
                page -= 1
                continue
            if word.startswith("/"):
                needle, page = word[1:].strip(), 0
                continue
            if word.startswith("?"):
                self._explain(options, word[1:].strip())
                continue
            if not raw:
                if multi:
                    return [options[index][0] for index in sorted(set(picked))]
                return [options[default - 1][0]]
            if word in ("d", "done") and multi:
                return [options[index][0] for index in sorted(set(picked))]

            wanted = [part for part in raw.replace(",", " ").split() if part]
            if all(part.isdigit() and 1 <= int(part) <= len(options)
                   for part in wanted):
                # Deduplicated within the line: "1,1,2" is somebody naming two
                # things clumsily, not somebody asking for the first and then
                # changing their mind about it in the same breath.
                chosen = list(dict.fromkeys(int(part) - 1 for part in wanted))
                if not multi:
                    return [options[chosen[0]][0]]
                # Typing a number again takes it back off, so a mistyped
                # number is fixable without starting the question over.
                for index in chosen:
                    picked.remove(index) if index in picked \
                        else picked.append(index)
                if pages == 1:
                    # One page, so there is nowhere else to add from and the
                    # answer is complete. This is what the question has always
                    # done — typing "1,3" answers it — and paging is not a
                    # reason to make the short case take an extra keypress.
                    return [options[index][0] for index in sorted(set(picked))]
                continue

            complaint = (f"a number between 1 and {len(options)}"
                         + (", or /word to search" if pages > 1 else ""))

    def _numbered_prompt(self, multi: bool, default: int, pages: int,
                         verb: str, picked: list[int]) -> str:
        parts = []
        if multi:
            parts.append("numbers to add or remove")
        else:
            parts.append(f"number [{default}]")
        if pages > 1:
            parts.append("m/b to page")
        parts.append("/word to search")
        parts.append("?n to read one")
        if multi:
            parts.append(f"enter to {verb} {len(picked) or 'nothing'}")
        return "  " + ", ".join(parts) + ": "

    def _page(self, window: Sequence[tuple[int, tuple[str, str, str]]],
              default: int, picked: Sequence[int], *, multi: bool = False,
              width: int = 4) -> None:
        """One screenful of options, one line each.

        One line each is the whole point: the descriptions in the skills
        catalogue run to four hundred characters, and printed in full they
        turned a list into a wall nobody could pick from. `?n` reads one.
        """
        table = Table.grid(padding=(0, 1), expand=True)
        table.add_column(justify="right", no_wrap=True, width=width)
        if multi:
            table.add_column(no_wrap=True, width=1)
        table.add_column(no_wrap=True, max_width=24)
        table.add_column(no_wrap=True, ratio=1,
                         overflow="crop" if self.theme.ascii
                         else "ellipsis")

        for index, (_, label, note) in window:
            number = index + 1
            cells = [Text(f"{number}.", style=self.theme.style("accent"))]
            if multi:
                cells.append(Text(
                    self.theme.glyphs.check if index in picked else " ",
                    style=self.theme.style("good", bold=True)))
            cells.append(Text(label, style=self.theme.style(
                "value", bold=number == default)))
            cells.append(Text(" ".join(note.split()),
                              style=self.theme.style("dim")))
            table.add_row(*cells)
        self.console.print(table)

    def _explain(self, options: Sequence[tuple[str, str, str]],
                 which: str) -> None:
        """The whole note for one option, for the typed path."""
        if not (which.isdigit() and 1 <= int(which) <= len(options)):
            self.console.print(Text("  ?  then the number, as in ?3",
                                    style=self.theme.style("bad")))
        else:
            _, label, note = options[int(which) - 1]
            self._header()
            self.console.print()
            self.console.print(Panel(
                Text(" ".join(note.split()) or "Nothing more to say about "
                     "this one.", style=self.theme.style("text")),
                title=Text(f" {label} ", style=self.theme.style("title")),
                title_align="left", box=self.theme.box,
                border_style=self.theme.style("border"), padding=(1, 2)))
        self._prompt("  enter to go back: ")

    def _ask(self, message: str, default: str = "") -> str:
        suffix = f" [{default}]" if default else ""
        answer = self._prompt(f"  {message}{suffix}: ").strip()
        return answer or default

    # -- the questions ---------------------------------------------------- #

    def run(self, minimal: bool | None = None) -> Answers:
        """Ask what it takes to reach a working agent, and only that.

        `minimal` defaults to "this is a first run". A new install gets the
        shortest honest path — provider, key if one is needed, model, and
        GitHub if wanted — because the point of the first minute is a working
        agent, not a tour of the settings.

        An explicit ``comodor setup`` asks the optional questions as well.
        Approval policy, the skills library and a phone channel are all still
        worth offering; they are simply not worth standing between somebody and
        their first task, and each has its own command for later. Nothing here
        was deleted, only moved off the critical path.

        An interrupted run left its non-secret progress in a checkpoint, and
        the offer to continue it comes before anything is asked: a resume is
        not a question that fits between the others, and quietly restarting
        would throw away answers the person already gave.
        """
        if minimal is None:
            minimal = bool(self.config.needs_setup or self.config.first_run)
        self._banner()

        # Offered ahead of the import, because a run that got far enough to
        # save a checkpoint already answered that question: re-asking it
        # before "continue where you left off" would be a fresh question
        # standing in front of an old decision.
        saved = read_checkpoint(self.config)
        resuming = saved is not None and self._offer_resume(saved)
        if saved is not None and not resuming:
            # Starting over discards the progress file and nothing else. The
            # configuration is a different state, and is not touched here.
            clear_checkpoint(self.config)

        # Asked before anything else, because everything after it depends on
        # the answer: an imported key is a key not to ask for, and an imported
        # model is the default for the model question.
        elsewhere = [] if resuming else self._look_for_another_agent()
        asked = 4 if minimal else 7
        total = asked + (1 if elsewhere else 0)
        step = 1
        if elsewhere:
            self._offer_import(elsewhere, step, total)
            step += 1

        # Detection runs after the import, not before: what is already
        # available just changed, and a provider list drawn from before the
        # import would offer a key that is already in the config as though
        # somebody still had to find one.
        #
        # Which local runtimes are up is passed in rather than probed by the
        # plan, because reaching a port is this host's kind of work and a test
        # that had to start Ollama to check an ordering would not be runnable.
        self.plan.start(running=self._running_here())

        answers = Answers()
        if resuming:
            self._effect = self.plan.continue_from_checkpoint()
            if self.plan.resumed is None:
                # The plan could not use the saved progress — a provider that
                # is no longer offered, a step no run can stand on. It
                # discarded the file; this says so rather than quietly
                # pretending the offer to continue was kept.
                resuming = False
                self.console.print(Text(
                    "  That saved progress could not be used, so the "
                    "questions start again.",
                    style=self.theme.style("dim")))
            else:
                step = 1
                total = self._questions_left(minimal)

        while True:
            if resuming:
                spec = catalogue.get(self.plan.draft.provider)
                answers.provider = self.plan.draft.provider
                answers.base_url = self.plan.draft.base_url
                self._recap_restored(spec)
                if self.plan.step is Step.CREDENTIAL:
                    answers.api_key = self._ask_key(step, total, spec)
                    step += 1
                if self.plan.step is Step.MODEL:
                    answers.model = self._ask_model(step, total, spec, answers)
                    step += 1
                    if answers.model is None:
                        # "Choose a different provider" out of a refused
                        # credential. The resumed path has ended and the
                        # ordinary one begins, with its own counting.
                        resuming = False
                        step, total = 1, asked
                        continue
                if self.plan.step is Step.GITHUB:
                    self._ask_github(step, total)
                    step += 1
                break

            first = step
            answers.provider = self._ask_provider(step, total)
            spec = catalogue.get(answers.provider)
            step += 1

            if answers.provider == "custom":
                answers.base_url = self._ask_endpoint()
            answers.api_key = self._ask_key(step, total, spec)
            step += 1

            answers.model = self._ask_model(step, total, spec, answers)
            step += 1
            if answers.model is None:
                step = first
                continue

            self._ask_github(step, total)
            step += 1
            break

        if not minimal:
            answers.approvals = self._ask_approvals(step, total)
            answers.skills = self._ask_skills(step + 1, total)
            self._ask_telegram(step + 2, total, answers)
        return answers

    # ---------------------------------------------------------------- resume #

    def _offer_resume(self, saved: Checkpoint) -> bool:
        """An interrupted run was found. Continue it, start over, or leave.

        Offered rather than applied in either direction: silently continuing
        would surprise somebody who had forgotten they started, and silently
        restarting would destroy answers they gave. The progress file holds no
        secrets — a typed key is asked again rather than written down — and
        saying so on the screen is what makes "continue" mean something.
        """
        self._rule("Continue where you left off?", 0, 0)
        spec = catalogue.get(saved.provider)
        where = spec.label if spec else (saved.provider or "the first question")
        reached = {
            "credential": "the API key",
            "model": "choosing a model",
            "github": "the GitHub question",
            "ready": "the last screen",
        }.get(saved.step, "the provider list")
        self.console.print(Text.assemble(
            ("  A previous setup reached ", self.theme.style("dim")),
            (reached, self.theme.style("value")),
            (f" with {where}.", self.theme.style("dim")),
        ))
        if saved.model:
            self.console.print(Text.assemble(
                ("  Model ", self.theme.style("dim")),
                (saved.model, self.theme.style("value")),
            ))
        if saved.base_url:
            self.console.print(Text.assemble(
                ("  Endpoint ", self.theme.style("dim")),
                (saved.base_url, self.theme.style("value")),
            ))
        self.console.print(Text(
            "  Saved progress holds no keys; one you typed is asked again.\n",
            style=self.theme.style("dim")))

        choice = self._choose([
            ("continue", "Continue previous setup", f"pick up at {reached}"),
            ("fresh", "Start over",
             "ask everything again; the saved progress is discarded"),
            ("cancel", "Cancel", "leave everything exactly as it is"),
        ], default=1, title="Setup")
        if choice == "cancel":
            # The configuration was never touched — the transaction sees to
            # that — and the progress file stays, so a later run can still
            # offer the same choice. Callers already handle this the way they
            # handle Ctrl-C, which is what it means.
            raise KeyboardInterrupt
        return choice == "continue"

    def _questions_left(self, minimal: bool) -> int:
        """How many questions a resumed run will still ask.

        Counted from the plan's own position rather than assumed: a resume
        that lands on the GitHub question has one left, and labelling it
        "3 of 4" would be the counter disagreeing with the screen.
        """
        left = {Step.CREDENTIAL: 3, Step.MODEL: 2, Step.GITHUB: 1}.get(
            self.plan.step, 0)
        return left + (0 if minimal else 3)

    def _recap_restored(self, spec) -> None:
        """The answers a resume brought back, one quiet line each.

        Restored answers are shown the way freshly given ones are, because a
        question that is not asked again still deserves to be seen — a wrong
        restoration is only catchable if it is visible. Nothing here can name
        a key: the checkpoint has nowhere to put one.
        """
        draft = self.plan.draft
        if draft.provider:
            label = spec.label if spec else draft.provider
            self._answered("provider", label)
        if draft.base_url:
            self._answered("endpoint", draft.base_url)
        words = {
            CredentialSource.ENVIRONMENT:
                f"from ${draft.env_variable}" if draft.env_variable
                else "from the environment",
            CredentialSource.EXISTING: "already stored here",
            CredentialSource.IMPORTED: "imported",
            CredentialSource.ENTERED: "to enter again",
        }.get(draft.credential)
        if words:
            self._answered("api key", words)
        if draft.model:
            self._answered("model", draft.model)
        if draft.github is GitHubIntent.SKIP:
            self._answered("github", "skipped")
        elif draft.github is GitHubIntent.KEEP:
            self._answered("github", "kept")

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

    def _already_here(self) -> dict[str, str]:
        """What this machine can already do, said before anything is asked.

        A local runtime that is up needs no key and no account, and an
        exported key is one somebody found an hour ago. Opening with eighteen
        billing pages when the answer is a port that is already open is asking
        a question that has been answered.

        Returns a note per provider, for the list to show beside it. Never
        raises: this is on the path that draws the first screen anybody sees.
        """
        self._detect()
        return self._notes

    def _running_here(self) -> set[str]:
        """The local runtimes that are actually up, by provider id."""
        self._detect()
        return self._running

    def _detect(self) -> None:
        """One probe, two answers.

        Cached, because both the ordering of the provider list and the notes
        beside it come from the same look — and that look touches ports, so
        doing it twice would be doing it twice.
        """
        if self._detected:
            return
        self._detected = True
        try:
            from .providers import discover

            running = discover.running_here()
            exported = discover.keys_in_the_environment()
        except Exception:
            return

        for item in running:
            if item.usable:
                self._running.add(item.provider)
            self._notes[item.provider] = (
                f"running here — {item.summary}" if item.usable
                else "running here, but no models installed yet")
        for item in exported:
            self._notes.setdefault(item.provider,
                                   f"key already in ${item.variable}")

        # Returned rather than announced. The list leads with these and names
        # their models, so a sentence above it saying the same thing is the
        # same fact twice — and the second telling is the one nobody reads.

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

    def _ask_telegram(self, step: int, total: int, answers: Answers) -> None:
        """Offer the phone, here, because nowhere else would be found.

        The bot shipped and setup did not mention it, so the only people who
        knew it existed were the ones who read the documentation for a feature
        they had no reason to look for. A capability nobody is told about is a
        capability nobody has.

        Declining is the default and costs one keypress. Nothing is written
        unless a token is given, and a token alone does not open anything: the
        bot answers a list of accounts, and that list is filled by pairing.
        """
        self._rule("Run it from your phone?", step, total)
        self.console.print(Text(
            "  The whole agent as buttons — send it a task, watch it work, "
            "answer\n  its questions. It reads and plans only, until you say "
            "otherwise.\n",
            style=self.theme.style("dim")))

        # The two are not equal work and the list says so. WhatsApp needs a
        # Meta app, an app secret and a public HTTPS address — twenty minutes
        # of somebody else's dashboard — and it does exactly what the one-token
        # option does. Somebody choosing it because it was listed second, and
        # discovering that twenty minutes later, is a question that cost them
        # their evening.
        wanted = self._choose(
            [("no", "Not now", "you can set any of them up later"),
             ("telegram", "Telegram",
              "recommended — one token from @BotFather, about a minute, "
              "nothing else to set up"),
             ("slack", "Slack",
              "about five minutes — create the app from a manifest we give "
              "you, then two tokens. No public address needed"),
             ("whatsapp", "WhatsApp",
              "about twenty minutes and technical: a Meta app, an app secret "
              "and a public HTTPS address. It does the same thing Telegram "
              "does — pick this only if it has to be WhatsApp")],
            default=1, title="From your phone")
        if wanted == "whatsapp":
            self._point_at_whatsapp(step, total)
            return
        if wanted == "slack":
            self._point_at_slack(step, total)
            return
        if wanted != "telegram":
            self._answered("phone", "not now")
            return

        self._rule("Run it from your phone?", step, total)
        self.console.print(Panel(
            Text.from_markup(
                "Open Telegram, message [bold]@BotFather[/bold] and send "
                "[bold]/newbot[/bold].\nGive it a name, then a username ending "
                "in `bot`. It answers with a token:\n\n"
                "   [dim]1234567890:AAF…[/dim]\n\n"
                "[dim]Paste it below, or press enter to skip this.[/dim]"),
            title=Text(" Getting a bot ", style=self.theme.style("title")),
            title_align="left", box=self.theme.box,
            border_style=self.theme.style("border"), padding=(1, 2)))

        token = self._ask("token")
        if not token:
            self._answered("phone", "not now")
            return

        username = self._check_token(token)
        if username is None:
            self._answered("phone", "not now")
            return

        answers.telegram_token = token
        # Named here, not only in the recap: this is the last question, so on
        # the typed path there is no next screen for a recap to appear on and
        # the one confirmation that the token worked would never be seen.
        self.console.print(Text.assemble(
            (f"  {self.theme.glyphs.check} Connected to ",
             self.theme.style("good")),
            (f"@{username}", self.theme.style("value", bold=True)),
        ))
        self._pair_now(token, username, answers)
        self._answered(
            "phone",
            f"Telegram @{username}" + (f", {len(answers.telegram_allowed)} paired"
                              if answers.telegram_allowed else ", not paired"))

    def _point_at_slack(self, step: int, total: int) -> None:
        """Say what Slack needs, and hand over to the command that does it.

        Not asked for here for the same reason as WhatsApp: an app has to be
        created in a browser. It is far less work than WhatsApp — Slack takes
        a manifest, so the app is one paste rather than eleven checkboxes, and
        Socket Mode means no public address at all.
        """
        self._rule("Run it from your phone?", step, total)
        self.console.print(Panel(
            Text.from_markup(
                "Slack needs an app in your workspace, which is made in a "
                "browser — but\nSlack takes a [bold]manifest[/bold], so it is "
                "one paste rather than a page of\ncheckboxes, and there is no "
                "public address to arrange.\n\n"
                "   [bold]comodor slack manifest[/bold]"
                "[dim]   the app definition to paste[/dim]\n"
                "   [bold]comodor slack connect[/bold]"
                "[dim]    the two tokens, checked as you paste them[/dim]\n\n"
                "[dim]About five minutes.[/dim]"),
            title=Text(" Slack ", style=self.theme.style("title")),
            title_align="left", box=self.theme.box,
            border_style=self.theme.style("border"), padding=(1, 2)))
        self._answered("phone", "Slack — `comodor slack connect`")

    def _point_at_whatsapp(self, step: int, total: int) -> None:
        """Say what WhatsApp needs, and hand over to the command that does it.

        Not asked for here, because none of it can be produced at a terminal: a
        Meta app, a business number, an app secret and a public HTTPS address
        are four things that live in a browser and a DNS record. A wizard that
        asked for them would be a wizard that stalled for twenty minutes on the
        last of six questions.
        """
        self._rule("Run it from your phone?", step, total)
        self.console.print(Panel(
            Text.from_markup(
                "WhatsApp goes through Meta's Cloud API, which needs an app "
                "set up at\n[bold]developers.facebook.com[/bold] — a business "
                "number, an access token, an\napp secret, and a public HTTPS "
                "address for Meta to deliver to.\n\n"
                "None of that can be made from a terminal, so it is its own "
                "command — and\nthat one walks you through it, links each "
                "page, checks each value as it\narrives, and starts the "
                "tunnel for you:\n\n"
                "   [bold]comodor whatsapp connect[/bold]\n\n"
                "[dim]About twenty minutes the first time. No real number, no "
                "card and no\nbusiness verification — the test number Meta "
                "makes you messages five\npeople for free.[/dim]"),
            title=Text(" WhatsApp ", style=self.theme.style("title")),
            title_align="left", box=self.theme.box,
            border_style=self.theme.style("border"), padding=(1, 2)))
        self._answered("phone", "WhatsApp — `comodor whatsapp connect`")

    def _check_token(self, token: str) -> str | None:
        """Ask Telegram whether the token is real, and who it belongs to.

        Checked here rather than at first use, because a mistyped token that is
        only discovered days later looks like a broken feature rather than a
        typo.
        """
        from .telegram.api import Bot, TelegramError, Unauthorised

        try:
            return str(Bot(token).me()["username"])
        except Unauthorised:
            self.console.print(Text(
                "  Telegram refused that token. BotFather can issue another "
                "with /token.", style=self.theme.style("bad")))
        except TelegramError as problem:
            self.console.print(Text(f"  {problem}",
                                    style=self.theme.style("bad")))
        except Exception:
            self.console.print(Text(
                "  Could not reach Telegram just now.",
                style=self.theme.style("bad")))
        self.console.print(Text(
            "  Skipping — `comodor telegram connect <token>` when you are "
            "ready.", style=self.theme.style("dim")))
        return None

    def _pair_now(self, token: str, username: str, answers: Answers) -> None:
        """Add this account to the list the bot answers, while it is open.

        A bot's username is public, so the bot answers a fixed list of accounts
        and nobody else. Filling that list is the difference between a bot that
        works and one that ignores you, so it happens here rather than in a
        command somebody has to be told about afterwards.
        """
        import threading

        from .telegram.bot import Service

        try:
            service = Service(_pairing_config(self.config, token),
                              announce=lambda line: None)
            code = service.offer_pairing()
        except Exception:
            self.console.print(Text(
                "  Could not start pairing. Run `comodor telegram pair` "
                "later.", style=self.theme.style("dim")))
            return

        self.console.print()
        self.console.print(Panel(
            Text.from_markup(
                f"Open [bold]t.me/{username}[/bold] and send it this code:\n\n"
                f"      [bold accent]{code}[/bold accent]\n\n"
                f"[dim]It works once, and expires in "
                f"{self.config.telegram.pair_window // 60} minutes. "
                f"Press Ctrl-C to skip.[/dim]"),
            title=Text(" Pair your account ", style=self.theme.style("title")),
            title_align="left", box=self.theme.box,
            border_style=self.theme.style("border"), padding=(1, 2)))
        self.console.print(Text("  waiting…", style=self.theme.style("dim")))

        worker = threading.Thread(target=service.run, daemon=True)
        worker.start()
        try:
            while True:
                if service.config.telegram.allowed:
                    answers.telegram_allowed = list(
                        service.config.telegram.allowed)
                    break
                if service.pairing is None or not service.pairing.live:
                    break
                if worker.join(0.5) is None and not worker.is_alive():
                    break
        except KeyboardInterrupt:
            pass
        finally:
            service.stop()

        if answers.telegram_allowed:
            self.console.print(Text(
                f"  {self.theme.glyphs.check} Paired. "
                f"`comodor telegram start` runs it.",
                style=self.theme.style("good")))
        else:
            self.console.print(Text(
                "  Not paired — the token is saved, so `comodor telegram "
                "pair` finishes it.", style=self.theme.style("dim")))

    def _banner(self) -> None:

        self.console.print()
        self._crown()
        body = Text.assemble(
            ("A few questions, once. The answers are saved to\n",
             self.theme.style("dim")),
            (str(self.config.paths.config_file), self.theme.style("value")),
            ("\nand you will not be asked again. Change anything later with ",
             self.theme.style("dim")),
            ("/settings", self.theme.style("accent")),
            (".", self.theme.style("dim")),
        )
        self.console.print(Panel(body, box=self.theme.box,
                                 border_style=self.theme.style("border"),
                                 padding=(1, 2)))

    def _ask_provider(self, step: int, total: int) -> str:
        self._rule("Which model provider?", step, total)
        self.console.print(
            Text("  You can add more later; this is just the one to start with.\n",
                 style=self.theme.style("dim")))
        here = self._already_here()
        # The order is the plan's, and so is the reasoning behind it: it knows
        # which providers are usable on this machine without anybody typing
        # anything. A second copy of that rule here — which is what this method
        # used to carry — is a second place for it to be wrong, and the two
        # disagreed about a local runtime that was running but had no key.
        # What this adds is wording, not decisions.
        options = [(fact.id, fact.label, self._provider_note(fact, here))
                   for fact in self.plan.facts]
        chosen = self._choose(options, default=1, title="Providers")
        labels = {value: label for value, label, _ in options}
        self._answered("provider", labels.get(chosen, chosen))
        self._effect = self.plan.choose_provider(chosen)
        return chosen

    def _provider_note(self, fact: Any, here: dict[str, str]) -> str:
        """What is known about this one, ahead of what the catalogue says.

        "Running here, three models" is an answer; the sales line is what you
        read when there is no answer yet.
        """
        if fact.id in here:
            return here[fact.id]
        if fact.has_stored_key:
            why = ("key imported" if fact.label in self.imported.keys
                   else "key already set")
            return f"{why} — {fact.blurb}"
        if fact.has_env_key:
            return f"key in ${fact.env_variable} — {fact.blurb}"
        return fact.blurb

    def _ask_endpoint(self) -> str:
        self.console.print()
        while True:
            url = self._ask("OpenAI-compatible base URL", "https://").strip()
            self._effect = self.plan.set_endpoint(url)
            if not self.plan.error:
                return url
            # Refused here rather than after a probe has been sent somewhere:
            # a URL with a key in its query string would otherwise be written
            # into a config file, echoed onto a recap screen, and handed to a
            # process that logs its arguments.
            self.console.print(Text(f"  {self.plan.error}",
                                    style=self.theme.style("bad")))

    def _ask_key(self, step: int, total: int,
                 spec: catalogue.ProviderSpec | None) -> str:
        self._rule("API key", step, total)

        if spec and spec.keys_url:
            self.console.print(Text.assemble(
                ("  Get one at ", self.theme.style("dim")),
                (spec.keys_url, self.theme.style("accent")),
            ))

        # Which of the four situations this is — no key needed, one already in
        # the environment, one already stored, or nothing yet — is the plan's
        # answer rather than a re-read of the config, because the plan is what
        # decides afterwards whether anything is written to disk.
        fact = next((each for each in self.plan.facts
                     if each.id == self.plan.draft.provider), None)
        source = fact.credential if fact else CredentialSource.ENTERED

        if source is CredentialSource.NONE:
            self.console.print(
                Text("  Not needed — this one runs on your machine.",
                     style=self.theme.style("dim")))
            self.console.print()
            self._answered("api key", "not needed")
            return ""

        if source in (CredentialSource.ENVIRONMENT, CredentialSource.EXISTING):
            self.console.print()
            where, note = self._where_the_key_is(spec)
            self.console.print(Text(f"  A key for this provider is {where}.",
                                    style=self.theme.style("good")))
            if note:
                self.console.print(
                    Text(f"  {note}", style=self.theme.style("dim")))
            keep = self._choose([
                ("keep", f"use the key {where}", "nothing to type"),
                ("replace", "enter a different one", "saved to your config file"),
            ], default=1, title="API key")
            if keep == "keep":
                self._answered("api key", f"{where}, kept")
                self._effect = self.plan.choose_credential(source)
                return ""
        else:
            self.console.print(
                Text("  It is stored in your config file and never sent "
                     "anywhere but the provider.", style=self.theme.style("dim")))
            self.console.print()

        while True:
            # Masked: keys get pasted in shared terminals and shoulder-surfed
            # off screen recordings.
            key = self._secret("  key (input hidden): ").strip()
            if key:
                self._answered("api key", "set, and never shown again")
                # Handed to the plan, which is the only place it is held. What
                # comes back is the probe the plan now wants run.
                self._effect = self.plan.submit_credential(key)
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
                   spec: catalogue.ProviderSpec | None,
                   answers: Answers) -> str | None:
        """The model question. None means "back to the provider list".

        Discovery first, and the question afterwards, because asking the
        provider what it has takes a second or two over the network. During
        that second the terminal is still in its ordinary mode, so anything
        impatient fingers press is echoed — an arrow key arrives on screen as
        `^[[B` and sits there. Clearing for the question is what wipes it, so
        the clearing has to come second. The keystrokes themselves are
        discarded when the reader takes the terminal.

        A credential the provider refused is corrected before any list is
        drawn. Choosing a model against a key that does not work ends at a
        Ready screen that cannot be committed — a dead end dressed up as
        progress — so the refusal is handled where it happens, with every
        earlier answer kept.
        """
        models = self._discover_models(spec, answers)
        while self.plan.validation.check is Check.INVALID:
            if self._offer_credential_fix(step, total, answers) == "back":
                return None
            models = self._discover_models(spec, answers)

        check = self.plan.validation.check
        reason = self.plan.validation.reason

        self._rule("Which model?", step, total)
        self._say_what_the_probe_found(check, reason)

        if not models:
            typed_model = self._ask("model id",
                                    spec.default_model if spec else "")
            self.plan.choose_model(typed_model, typed=True)
            self._effect = None
            return typed_model

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
        typed = chosen == "__other__"
        if typed:
            chosen = self._ask("model id", models[0])
        self._answered("model", chosen)
        self.plan.choose_model(chosen, typed=typed)
        self._effect = None
        return chosen

    def _say_what_the_probe_found(self, check: Any, reason: str) -> None:
        """Say what checking proved, including when it proved nothing.

        "Configured" and "working" are different facts. A wizard that showed a
        model list and said nothing about where it came from left somebody
        unable to tell a provider that answered from one that was guessed at —
        and unable to tell a wrong key from an outage, which is the difference
        between rotating a credential and waiting a minute.
        """
        if check is Check.VALID:
            self.console.print(Text("  That credential works, and these are "
                                    "the models it offers.",
                                    style=self.theme.style("good")))
            return
        if check in (Check.IDLE, Check.CHECKING):
            # Nothing to say: either no probe was possible, or one is still
            # running and this screen is not where its result lands.
            return
        style = ("bad" if check is Check.INVALID else
                 "warn" if check in (Check.UNREACHABLE, Check.NO_MODELS)
                 else "dim")
        headline = {
            Check.INVALID: "That credential was refused.",
            Check.UNREACHABLE: "The provider could not be reached.",
            Check.NO_MODELS: "The provider answered but offered no models.",
            Check.UNVERIFIED: "Nothing could be checked against this provider.",
            Check.CHECKING: "Checking…",
        }.get(check, "")
        self.console.print(Text(f"  {headline}", style=self.theme.style(style)))
        if reason:
            self.console.print(Text(f"  {reason}", style=self.theme.style("dim")))
        if check in (Check.UNREACHABLE, Check.NO_MODELS, Check.UNVERIFIED):
            self.console.print(Text(
                "  These are the models this provider is known to have. "
                "Pick one, or type the id you were given — nothing here was "
                "confirmed, and setup will say so rather than claim it works.",
                style=self.theme.style("dim")))

    def _offer_credential_fix(self, step: int, total: int,
                               answers: Answers) -> str:
        """The provider refused the credential. Fix that, and nothing else.

        Retry, replace, go back or cancel — the plan stays where it is, the
        staged configuration is still unwritten, and every earlier answer
        survives the correction. What must not happen is the wizard walking
        on: the plan refuses to commit an INVALID validation, so continuing
        would only move the failure to the end of the whole flow instead of
        fixing it where the problem is.
        """
        self._rule("That credential was refused", step, total)
        reason = self.plan.validation.reason or self.plan.error
        if reason:
            self.console.print(Text(f"  {reason}",
                                    style=self.theme.style("bad")))
        self.console.print(Text("  Everything else you answered is kept.\n",
                                style=self.theme.style("dim")))

        fact = next((each for each in self.plan.facts
                     if each.id == self.plan.draft.provider), None)
        options: list[tuple[str, str, str]] = []
        if fact is not None and fact.needs_key:
            options.append(("replace", "Enter a different key",
                            "the provider is asked again straight away"))
        options.append(("retry", "Try this credential again",
                        "a refusal can be the provider having a bad minute"))
        options.append(("back", "Choose a different provider",
                        "back to the provider list"))
        options.append(("cancel", "Cancel setup",
                        "nothing is written; your configuration stays as "
                        "it is"))
        choice = self._choose(options, default=1, title="API key")

        if choice == "cancel":
            self.plan.cancel()
            raise KeyboardInterrupt
        if choice == "back":
            self.plan.back()
            return "back"
        if choice == "retry":
            self._effect = self.plan.retry_validation()
            return "retry"
        while True:
            # Masked, exactly like the first asking: keys get pasted in
            # shared terminals and shoulder-surfed off screen recordings.
            key = self._secret("  key (input hidden): ").strip()
            if key:
                answers.api_key = key
                self._effect = self.plan.submit_credential(key)
                return "replace"
            self.console.print(Text("  a key is required for this provider",
                                    style=self.theme.style("bad")))

    def _discover_models(self, spec: catalogue.ProviderSpec | None,
                         answers: Answers) -> list[str]:
        """Run the probe the plan asked for, and tell it what happened.

        Live discovery is worth a couple of seconds here: a stale hard-coded
        list is how a setup wizard ends up recommending a model that was
        retired six months ago. It is also the cheapest way to prove a
        credential — an authenticated model list costs nothing, where a
        generation would spend money to learn something already learned.

        A provider that cannot be asked still gets a list, from the catalogue,
        because a dead end is worse than an unverified choice — but the
        validation state says which of the two happened, and the screen says so
        out loud rather than presenting a guess as an answer.
        """
        effect = self._effect
        self._effect = None
        if effect is None or effect.kind is not EffectKind.DISCOVER:
            effect = self.plan.retry_validation()
        if effect.kind is not EffectKind.DISCOVER:
            return list(self.plan.validation.models)

        self.console.print(Text("  checking what this provider offers…",
                                style=self.theme.style("dim")))
        entry = self.plan.probe_entry()
        models: list[str] = []
        check = Check.UNVERIFIED
        reason = ""
        if entry is None:
            reason = "There is nothing to check yet."
        else:
            try:
                from .providers.gateway import build_provider

                probe = build_provider(entry)
                try:
                    models = list(probe.list_models())
                finally:
                    close = getattr(probe, "close", None)
                    if close:
                        close()
                check = Check.VALID if models else Check.NO_MODELS
                if not models:
                    reason = "It answered, but listed nothing to run."
            except Exception as problem:      # noqa: BLE001 - classified below
                check, reason = classify_probe(problem)

        if (check is not Check.VALID and check is not Check.INVALID
                and spec is not None):
            # Offered, and labelled as not confirmed by `_say_what_the_probe_found`.
            # A refused credential is excluded: a list drawn under it would be
            # presented as though the key were fine and only the network were
            # slow, when what is owed is a correction.
            models = list(spec.models)

        known = list(spec.models) if spec is not None else []
        if check is Check.VALID and known:
            # What the catalogue recommends first, then everything else: the
            # provider's own ordering is alphabetical, which is not advice.
            models = [m for m in known if m in models] + \
                     [m for m in models if m not in known]
        self.plan.report_discovery(
            effect.attempt,
            Discovery(check=check, reason=reason, models=tuple(models[:40])))
        return list(self.plan.validation.models)

    # ------------------------------------------------------------------ github #

    def _ask_github(self, step: int, total: int) -> None:
        """Offer the connection, and make skipping it an equal answer.

        Comodor works on a local repository with no GitHub App anywhere near
        it, so this is not a required step and must not read like one: an
        optional thing presented as the last hurdle is a thing people abandon
        the install over. Skipping has to finish setup, not half-finish it.
        """
        self._rule("GitHub", step, total)

        if self.plan.github.step is GitHubStep.KEPT:
            account = self.plan.github.account or "this machine"
            self.console.print(Text(f"  Already connected as {account}.",
                                    style=self.theme.style("good")))
            self.console.print(Text(
                "  Re-running setup is not a reason to connect it again. "
                "`comodor github status` shows what it can see.",
                style=self.theme.style("dim")))
            self._answered("github", f"connected as {account}")
            self.plan.keep_github()
            return

        self.console.print(Text(
            "  Optional. Comodor works on a local repository without it.",
            style=self.theme.style("dim")))
        self.console.print(Text(
            "  Connecting lets it read issues, pull requests and CI, and open "
            "branches on repositories you have not checked out here.",
            style=self.theme.style("dim")))
        self.console.print()

        choice = self._choose([
            ("connect", "Connect GitHub",
             "opens a browser; this terminal notices when you finish"),
            ("skip", "Skip for now",
             "`comodor github connect` does it any time later"),
        ], default=2, title="GitHub")
        if choice == "skip":
            self.plan.skip_github()
            self._answered("github", "skipped")
            return
        self._connect_github()

    def _connect_github(self) -> None:
        """Run the browser flow through the host seam.

        Nothing here reimplements the protocol: the host begins the flow, opens
        the browser, and polls the signed claim endpoint until the worker says
        the installation is verified. What setup owns is the states around it
        — what to show while it waits, and what to offer when it does not
        succeed — so that a transient failure costs one retry rather than the
        whole onboarding.
        """
        from .github.connect import ConnectError

        for _attempt in range(3):
            effect = self.plan.connect_github()
            if effect.kind is not EffectKind.GITHUB_BEGIN:
                return
            host = self._make_github(self.config, self.console)
            try:
                pending = host.begin()
            except ConnectError as problem:
                self.plan.report_github(effect.attempt, GitHubOutcome(
                    step=_github_step(problem), detail=str(problem)))
            except (OSError, ValueError) as problem:
                self.plan.report_github(effect.attempt, GitHubOutcome(
                    step=GitHubStep.UNREACHABLE, detail=str(problem)))
            else:
                opened = host.open(pending)
                waiting = self.plan.report_github_started(
                    effect.attempt, url=pending.url, opened=opened,
                    seconds_left=pending.seconds_left,
                    automatic=pending.automatic)
                if waiting.kind is EffectKind.GITHUB_WAIT:
                    host.present(pending.url, opened)
                    try:
                        installation = host.wait(pending)
                    except ConnectError as problem:
                        self.plan.report_github(waiting.attempt, GitHubOutcome(
                            step=_github_step(problem), detail=str(problem)))
                    except KeyboardInterrupt:
                        # Ctrl-C stopped the waiting, not the setup: the
                        # person is still mid-onboarding, and leaving the plan
                        # on the GitHub step would strand it — unable to
                        # commit and unable to go back. The offer below is the
                        # same one a failure gets, and its default is to skip
                        # and finish.
                        self.plan.cancel_github()
                        self.console.print(Text("  Nothing was connected.",
                                                style=self.theme.style("dim")))
                    else:
                        self.plan.report_github(waiting.attempt, GitHubOutcome(
                            step=GitHubStep.CONNECTED,
                            account=getattr(installation, "account_login", ""),
                            installation=installation))
                # Anything else — an older endpoint that cannot hold a result,
                # and would need a receipt pasted back — has already put its
                # failure on the plan. It falls through to the offer below
                # rather than breaking out of it: the person chose Connect and
                # owes them an explanation and a way out, not a silent skip.

            if self.plan.github.step is GitHubStep.CONNECTED:
                account = self.plan.github.account or "this machine"
                self._answered("github", f"connected as {account}")
                return
            if not self._offer_github_retry():
                return
        if self.plan.github.step is not GitHubStep.CONNECTED:
            # Three attempts is enough. Skipping finishes setup; the command
            # exists for trying again later with a full screen to itself.
            self.plan.skip_github()
            self._answered("github", "skipped after it would not connect")

    def _offer_github_retry(self) -> bool:
        """What to do about a connection that did not happen. True to retry.

        The offer depends on what went wrong, because "try again" is the right
        answer to a 502 and the wrong one to a refusal — and neither is the
        right answer to somebody who has decided they do not want it yet.
        """
        step = self.plan.github.step
        headline = {
            GitHubStep.EXPIRED: "That link was not used in time.",
            GitHubStep.CANCELLED: "Nothing was connected.",
            GitHubStep.REFUSED: "GitHub would not confirm that installation.",
            GitHubStep.UNREACHABLE: "GitHub could not be reached.",
            GitHubStep.FAILED: "The connection did not complete.",
        }.get(step, "The connection did not complete.")
        self.console.print()
        self.console.print(Text(f"  {headline}", style=self.theme.style("bad")))
        if self.plan.github.detail:
            self.console.print(Text(f"  {self.plan.github.detail}",
                                    style=self.theme.style("dim")))

        options: list[tuple[str, str, str]] = []
        if step in (GitHubStep.UNREACHABLE, GitHubStep.EXPIRED,
                    GitHubStep.FAILED, GitHubStep.CANCELLED):
            options.append(("retry", "Try again", "a fresh link; the old one "
                                                  "is not reused"))
        options.append(("skip", "Skip for now",
                        "`comodor github connect` does it later"))
        choice = self._choose(options, default=len(options), title="GitHub")
        if choice == "skip":
            self.plan.skip_github()
            self._answered("github", "skipped")
            return False
        return True

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
        """Write everything collected, once, at the end.

        The provider, credential, model and GitHub connection belong to the
        plan: they were staged on a copy as they were chosen, so nothing has
        touched the real configuration yet. What this adds is the settings the
        wizard asks about and the plan does not own — approval policy, theme,
        context limit, a phone channel — onto that same copy, so all of it
        lands in one atomic write.

        That ordering is the transaction. A cancelled run, a refused
        credential, an unreachable provider and an expired GitHub flow all leave
        the working configuration exactly as it was, because none of them ever
        reached it. It used to be that a half-finished wizard could write a
        provider and then fail on the model, and the person would come back to
        a configuration that named a provider with no usable model.
        """
        staged = self.plan.staged
        staged.safety.auto_approve_writes = answers.approvals in ("writes", "auto")
        staged.safety.auto_approve_shell = answers.approvals == "auto"
        staged.agent.mode = answers.mode
        staged.ui.theme = answers.theme

        model_info = _model_info(answers.model)
        if model_info is not None:
            staged.agent.context_limit = model_info

        if answers.telegram_token:
            staged.telegram.token = answers.telegram_token
            staged.telegram.allowed = list(answers.telegram_allowed)
            # Switched on only once somebody can actually talk to it. A bot
            # that is enabled with an empty list is a bot that runs, answers
            # nobody, and looks broken.
            staged.telegram.enabled = bool(answers.telegram_allowed)

        saved = self.plan.commit()
        saved.first_run = False
        return saved

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

    def offer_start(self, config: Config) -> str:
        """The last screen: what to do with the thing that was just set up.

        Setup used to end by returning to the shell. Somebody had answered six
        questions, watched it say `Ready.`, and was then put back at a prompt
        with nothing running and no indication that the next step was to type
        the program's name again.

        A phone line is only offered when there is something to start, because
        an option that cannot work is worse than an option that is not there.
        The two channels are named rather than lumped together as "the bot":
        somebody who set up WhatsApp should not be offered "the Telegram bot".

        Returns one of `interface`, `telegram`, `whatsapp`, `both`, `nothing`.
        """
        from .channels import TELEGRAM, WHATSAPP

        ready = [channel for channel in (TELEGRAM, WHATSAPP)
                 if channel.can_run(config)[0]]

        options = [("interface", "Start Comodor",
                    "the interface, here in this terminal")]
        for channel in ready:
            options.append((
                channel.name, f"Start the {channel.label} bot",
                "in the background — answers while this terminal is closed"))
        if ready:
            named = " and ".join(channel.label for channel in ready)
            options.append(("both", "Both",
                            f"{named} in the background, the interface here"))
        options.append(("nothing", "Nothing yet",
                        "`comodor` starts it whenever you want"))

        # No clear here: this belongs under the `Ready.` panel `finish` has
        # just drawn, on the same screen. Cleared, that panel flashed past
        # unread — and it is the one that says where the answers were saved.
        self._step = ("What now?", 0, 0)
        self.console.print(Text(" What now?", style=self.theme.style(
            "title", bold=True)))
        return self._choose(options, default=1, title="What now?",
                            header=False)

    def start_phone(self, config: Config, channel: Any) -> bool:
        """Put one channel's bot in the background, and say what happened.

        Named by channel rather than hard-wired to Telegram: there are two of
        these now, they are started by the same code, and a message that says
        "Telegram" while starting WhatsApp is a message that will be believed.
        """
        from .channels import daemon

        ok, why = daemon.start(config, channel)
        self.console.print()
        if ok:
            self.console.print(Text.assemble(
                (f"  {self.theme.glyphs.check} {channel.label}: ",
                 self.theme.style("good")),
                (why, self.theme.style("value")),
            ))
            self.console.print(Text(
                f"  log   {daemon.log_file(config, channel)}",
                style=self.theme.style("dim")))
            self.console.print(Text(
                f"  stop  comodor {channel.name} stop",
                style=self.theme.style("dim")))
            self.console.print(Text(
                f"  keep it running after a reboot:  "
                f"comodor {channel.name} service install",
                style=self.theme.style("dim")))
        else:
            self.console.print(Text(f"  {channel.label}: {why}",
                                    style=self.theme.style("bad")))
            self.console.print(Text(
                f"  `comodor {channel.name} start --background` tries again.",
                style=self.theme.style("dim")))
        self.console.print()
        return ok

    def finish(self, config: Config, closing: bool = True) -> None:
        # `_terminal`, not `_keys`: over a connection where raw key reading
        # does not work the wizard still clears, and this used not to — so the
        # closing panel arrived underneath the last question instead of on a
        # screen of its own, which on a short terminal pushed it off the top.
        if self._terminal:
            self.console.clear()
            self._crown()
        # No recap here. The panel below already names the provider and the
        # model, and repeating every answer above it was what pushed the
        # closing screen past the bottom of a short terminal.
        entry = config.active()
        body = Text.assemble(
            ("Ready.\n\n", self.theme.style("good", bold=True)),
            ("  provider  ", self.theme.style("label")),
            (f"{entry.display if entry else '—'}\n", self.theme.style("value")),
            ("  model     ", self.theme.style("label")),
            (f"{config.active_model()}\n", self.theme.style("value")),
            ("  saved to  ", self.theme.style("label")),
            # The blank line goes with the sentence it separates. Left in when
            # the sentence was suppressed, it padded the panel with three
            # empty rows and pushed the question that follows off a short
            # terminal.
            (f"{config.paths.config_file}" + ("\n\n" if closing else ""),
             self.theme.style("value")),
            # Suppressed when a question follows: the question is the
            # instruction, and telling somebody to type a task immediately
            # above a list of things to choose between is two instructions.
            ("Type a task and press Enter. " if closing else "",
             self.theme.style("dim")),
            ("/help" if closing else "", self.theme.style("accent")),
            (" lists everything." if closing else "", self.theme.style("dim")),
        )
        self.console.print()
        self.console.print(Panel(body, box=self.theme.box,
                                 border_style=self.theme.style("good"),
                                 padding=(1, 2)))
        self.console.print()


def _pairing_config(config: Config, token: str) -> Config:
    """A copy carrying the token, for the pairing run only.

    A copy rather than the real config, because pairing may be abandoned — by
    Ctrl-C, by the code expiring, by closing the terminal — and a token written
    into the live config by a question that was never finished is a setting
    nobody chose. `apply` writes it, once, if the wizard gets that far.
    """
    import copy

    spare = copy.deepcopy(config)
    spare.telegram.token = token
    spare.telegram.enabled = True
    spare.telegram.allowed = []
    return spare


class GitHubHost:
    """The browser flow as setup drives it, behind one seam.

    The default is the real thing: the connector that signs and polls, and the
    link presentation the standalone `comodor github connect` command already
    uses — OSC 8 short label, clipboard fallback, raw URL only when nothing
    else can reach it. Setup adds none of that again.

    The seam exists so that a deterministic test — or a future desktop host
    with its own browser and its own wait presentation — can replace
    everything that leaves this process without setup's orchestration knowing
    the difference. A test that answers "Connect" at the GitHub question
    supplies a fake here and touches no network, no browser, no clipboard.
    """

    def __init__(self, config: Config, console: Console) -> None:
        from .github.connect import Connector

        self._connector = Connector(config)
        self._console = console

    def begin(self):
        return self._connector.begin()

    def open(self, pending) -> bool:
        return self._connector.open(pending)

    def present(self, url: str, opened: bool) -> None:
        from .github.commands import _offer_the_link

        _offer_the_link(self._console, url, opened)

    def wait(self, pending):
        from .github.commands import _wait

        return _wait(self._console, self._connector, pending)


def _github_step(problem: Any) -> Any:
    """Which kind of failure a connection error describes.

    Read from the error's own `kind` rather than from words in its message: a
    message is written for a person and gets improved, and a caller that
    branched on the wording would break the first time somebody improved it.
    """
    from .github import connect

    return {
        connect.EXPIRED: GitHubStep.EXPIRED,
        connect.CANCELLED: GitHubStep.CANCELLED,
        connect.REFUSED: GitHubStep.REFUSED,
        connect.UNREACHABLE: GitHubStep.UNREACHABLE,
    }.get(getattr(problem, "kind", ""), GitHubStep.FAILED)


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


def run_setup(config: Config, console: Console | None = None,
              offer: bool = False) -> Config:
    """Run the wizard and return the saved configuration.

    `offer` adds the closing question — start the interface, start the bot, or
    neither — and acts on the answer. It is off for the path that runs the
    wizard on the way into the interface, because that one is already going
    there and asking would be asking somebody to confirm what they are visibly
    already doing.

    What was chosen is left on the config as `start_after_setup`, so the caller
    can act on the half it owns without this function reaching into it.

    A plan that refuses to commit returns the configuration it was given,
    unchanged, with the refusal said on screen. The questions above are
    supposed to make that unreachable — an invalid credential is corrected
    where it was refused — and if one ever does reach this point, a first run
    ends with an explanation rather than a traceback and a caller that can
    still see `needs_setup` is a caller that can still exit honestly.
    """
    wizard = SetupWizard(config, console=console)
    answers = wizard.run()
    try:
        saved = wizard.apply(answers)
    except SetupError as problem:
        wizard.console.print()
        wizard.console.print(Text(f"  Setup stopped: {problem}",
                                  style=wizard.theme.style("bad")))
        wizard.console.print(Text("  Nothing was changed.",
                                  style=wizard.theme.style("dim")))
        return config
    wizard.install_skills(saved, answers)
    wizard.finish(saved, closing=not offer)

    saved.start_after_setup = "nothing"
    if offer:
        from .channels import CHANNELS

        chosen = wizard.offer_start(saved)
        saved.start_after_setup = chosen
        for channel in CHANNELS:
            if chosen == channel.name or (
                    chosen == "both" and channel.can_run(saved)[0]):
                wizard.start_phone(saved, channel)
    return saved
