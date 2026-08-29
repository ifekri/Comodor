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
    #: A bot token, if one was given. Empty means the question was declined,
    #: which is the default — nothing about Telegram is switched on quietly.
    telegram_token: str = ""
    #: Accounts paired during setup. Kept here rather than written straight to
    #: the config so that abandoning the wizard leaves nothing behind.
    telegram_allowed: list[int] = field(default_factory=list)


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

    def run(self) -> Answers:
        self._banner()

        # Asked before anything else, because everything after it depends on
        # the answer: an imported key is a key not to ask for, and an imported
        # model is the default for the model question.
        elsewhere = self._look_for_another_agent()
        total = 6 + (1 if elsewhere else 0)
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
        self._ask_telegram(step + 4, total, answers)
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

    def _already_here(self) -> dict[str, str]:
        """What this machine can already do, said before anything is asked.

        A local runtime that is up needs no key and no account, and an
        exported key is one somebody found an hour ago. Opening with eighteen
        billing pages when the answer is a port that is already open is asking
        a question that has been answered.

        Returns a note per provider, for the list to show beside it. Never
        raises: this is on the path that draws the first screen anybody sees.
        """
        try:
            from .providers import discover

            running = discover.running_here()
            exported = discover.keys_in_the_environment()
        except Exception:
            return {}

        notes: dict[str, str] = {}
        for item in running:
            notes[item.provider] = (f"running here — {item.summary}"
                                    if item.usable else
                                    "running here, but no models installed yet")
        for item in exported:
            notes.setdefault(item.provider, f"key already in ${item.variable}")

        # Returned rather than announced. The list leads with these and names
        # their models, so a sentence above it saying the same thing is the
        # same fact twice — and the second telling is the one nobody reads.
        return notes

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

        wanted = self._choose(
            [("no", "Not now", "you can set either up later"),
             ("telegram", "Telegram",
              "a bot from @BotFather — one token, set up here in a minute"),
             ("whatsapp", "WhatsApp",
              "a Meta business number — needs an app at developers.facebook.com")],
            default=1, title="From your phone")
        if wanted == "whatsapp":
            self._point_at_whatsapp(step, total)
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
        # A provider that already has a key — imported a moment ago, or found
        # in the environment — leads. The key is the expensive part of setting
        # this up, and offering a default that needs a new one, immediately
        # after announcing that a key was imported, is the wizard contradicting
        # itself. Order within each group stays the catalogue's own.
        def keyed(spec: catalogue.ProviderSpec) -> bool:
            entry = self.config.providers.get(spec.id)
            return bool(entry is not None and entry.api_key)

        def usable_now(spec: catalogue.ProviderSpec) -> bool:
            """Nothing left to find before this one can answer.

            A runtime already up on this machine is the same argument as a key
            already set, taken further: it needs no key at all.
            """
            return keyed(spec) or spec.id in here

        offered = list(catalogue.offered())
        ready = [spec for spec in offered if usable_now(spec)]
        rest = [spec for spec in offered if not usable_now(spec)]

        def blurb(spec: catalogue.ProviderSpec) -> str:
            # What was found about this one outranks what the catalogue says
            # about it: "running here, three models" is the answer, and the
            # sales line is what you read when there is no answer yet.
            if spec.id in here:
                return here[spec.id]
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

        if answers.telegram_token:
            config.telegram.token = answers.telegram_token
            config.telegram.allowed = list(answers.telegram_allowed)
            # Switched on only once somebody can actually talk to it. A bot
            # that is enabled with an empty list is a bot that runs, answers
            # nobody, and looks broken.
            config.telegram.enabled = bool(answers.telegram_allowed)

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

    def start_telegram(self, config: Config) -> bool:
        """Kept as a name of its own, because the tests and the closing
        question both reached for it before there was a second channel."""
        from .channels import TELEGRAM

        return self.start_phone(config, TELEGRAM)

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
    """
    wizard = SetupWizard(config, console=console)
    answers = wizard.run()
    saved = wizard.apply(answers)
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
