"""The wordmark, and the two lines under it that are worth the space.

A banner is a cost. It occupies the top of the terminal every single time, and
most of them are a logo and a version number that nobody reads twice. This one
earns its place by saying something that changes: what the agent has learned
since the last time it was opened.

    412 lessons · 7 skills · 3 rules you set

That is the only line here that is *about this installation* rather than about
the program, and it is the reason the banner is not decoration. A tool that
accumulates something should show what it has accumulated.

Three rules it follows, because a banner that ignores them is worse than none:

* **It never touches piped output.** `comodor run … | jq` must see the answer
  and nothing else, so this goes to the error stream when it goes anywhere at
  all, and not at all when the destination is not a terminal.
* **It shrinks rather than wraps.** The wordmark is 47 columns. Below that it
  becomes a single styled line, because ASCII art reflowed by a terminal is
  not a smaller logo, it is rubble.
* **It can be switched off**, and being switched off is remembered.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from rich.console import Group, RenderableType
from rich.text import Text

from .theme import Theme

#: The wordmark. Raw strings: it is made of backslashes.
WORDMARK = (
    r"   ______                          __          ",
    r"  / ____/___  ____ ___  ____  ____/ /___  _____",
    r" / /   / __ \/ __ `__ \/ __ \/ __  / __ \/ ___/",
    r"/ /___/ /_/ / / / / / / /_/ / /_/ / /_/ / /    ",
    r"\____/\____/_/ /_/ /_/\____/\__,_/\____/_/     ",
)
WIDTH = max(len(line) for line in WORDMARK)
#: Below this the wordmark is dropped rather than wrapped. Two columns of
#: margin, because a logo touching both edges reads as a mistake.
MINIMUM = WIDTH + 4

TAGLINE = "it learns the way you correct it"


def short(version: str) -> str:
    """A version fit for one line.

    An editable install reports something like
    `0.3.2.dev0+g702fb5d7d.d20260821`, which is thirty characters of build
    metadata and pushes everything after it onto the next line. The release
    part is the part anyone reads.
    """
    return (version or "").split("+")[0]


@dataclass
class Standing:
    """What this installation has accumulated. The part worth printing."""

    lessons: int = 0
    skills: int = 0
    rules: int = 0
    sessions: int = 0

    @property
    def anything(self) -> bool:
        return bool(self.lessons or self.skills or self.rules)

    def line(self) -> str:
        parts = []
        if self.lessons:
            parts.append(f"{self.lessons:,} lesson{'s' if self.lessons != 1 else ''}")
        if self.skills:
            parts.append(f"{self.skills} skill{'s' if self.skills != 1 else ''}")
        if self.rules:
            parts.append(f"{self.rules} rule{'s' if self.rules != 1 else ''} you set")
        return " · ".join(parts)


def gather(memory: Any = None, skills: Any = None) -> Standing:
    """Read the brain, and never fail because of it.

    A banner must not be able to stop the program starting, so every one of
    these is best-effort: a locked database or a half-written brain costs a
    line of text, not a session.
    """
    standing = Standing()
    if memory is not None:
        try:
            stats = memory.stats()
            standing.lessons = int(stats.get("lessons") or 0)
            standing.sessions = int(stats.get("episodes") or 0)
        except Exception:
            pass
        try:
            standing.rules = len(memory.active_rules())
        except Exception:
            pass
    if skills is not None:
        try:
            standing.skills = len(skills.all())
        except Exception:
            pass
    elif memory is not None:
        try:
            standing.skills = int(memory.stats().get("skills") or 0)
        except Exception:
            pass
    return standing


# --------------------------------------------------------------------------- #
# drawing
# --------------------------------------------------------------------------- #


def _shades(theme: Theme, count: int) -> list[str]:
    """A vertical fade from the accent into the body text.

    Interpolated rather than picked, so it follows whatever palette is in use —
    a fixed set of oranges would look wrong on the light themes and absurd on
    the monochrome one.
    """
    start, end = _rgb(theme.palette.accent), _rgb(theme.palette.text)
    if start is None or end is None:
        return [theme.palette.accent] * count
    shades = []
    for index in range(count):
        weight = index / max(1, count - 1)
        blend = tuple(round(a + (b - a) * weight * 0.65)
                      for a, b in zip(start, end, strict=True))
        shades.append("#%02x%02x%02x" % blend)
    return shades


def _rgb(colour: str) -> tuple[int, int, int] | None:
    value = (colour or "").strip().lstrip("#")
    if len(value) != 6:
        return None
    try:
        return int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16)
    except ValueError:
        return None


def wordmark(theme: Theme, width: int = 80) -> Text:
    """The logo, or a single line where it will not fit."""
    if width < MINIMUM:
        return Text("Comodor", style=theme.style("accent", bold=True))
    shades = _shades(theme, len(WORDMARK))
    art = Text()
    for line, shade in zip(WORDMARK, shades, strict=True):
        art.append(line + "\n", style=shade)
    return art


def render(theme: Theme, *, version: str = "", model: str = "",
           project: str = "", standing: Standing | None = None,
           width: int = 80) -> RenderableType:
    """The whole block: wordmark, what this is, and what it knows."""
    roomy = width >= MINIMUM
    indent = "  " if roomy else ""
    rows: list[RenderableType] = [wordmark(theme, width)]

    if roomy:
        identity = Text(indent)
        identity.append(TAGLINE, style=theme.style("dim"))
        if version:
            identity.append("   ")
            identity.append(short(version), style=theme.style("label"))
        if model:
            identity.append("  ·  ", style=theme.style("dim"))
            identity.append(model, style=theme.style("value"))
        rows.append(identity)
    else:
        # Narrow: one fact per line. A line that wraps in the middle of a
        # separator reads as damage rather than as a small layout.
        if version:
            rows.append(Text(short(version), style=theme.style("label")))
        if model:
            rows.append(Text(model, style=theme.style("value")))

    if standing is not None and standing.anything:
        learned = Text(indent)
        learned.append(standing.line(), style=theme.style("accent"))
        if standing.sessions:
            learned.append(f"   from {standing.sessions:,} finished task"
                           f"{'s' if standing.sessions != 1 else ''}",
                           style=theme.style("dim"))
        rows.append(learned)
    elif standing is not None:
        rows.append(Text(indent + "nothing learned yet — correct it once and "
                                  "it will remember", style=theme.style("dim")))

    if project:
        where = Text(indent)
        where.append(project, style=theme.style("dim"))
        rows.append(where)

    return Group(*rows)


def show(console: Any, theme: Theme, config: Any = None, **facts: Any) -> None:
    """Print it, unless printing it would be wrong."""
    if not wanted(console, config):
        return
    console.print()
    console.print(render(theme, width=console.size.width, **facts))
    console.print()


def wanted(console: Any = None, config: Any = None) -> bool:
    """Whether a banner belongs here at all.

    Off when asked to be off, and off when nobody is watching: a banner in a
    log file or a pipe is noise somebody has to filter out, and the one place
    it is guaranteed to be in the way is the output of a scripted run.

    The environment variable wins over the setting, in both directions, so a
    container can turn it on for a log and a script can turn it off for one
    command without editing anything.
    """
    asked = os.environ.get("COMODOR_BANNER", "")
    if asked:
        if _off(asked):
            return False
    else:
        if config is not None and not getattr(
                getattr(config, "ui", None), "banner", True):
            return False
        if os.environ.get("CI"):
            return False

    if console is not None:
        try:
            return bool(console.is_terminal)
        except Exception:
            return True
    return True


def _off(value: str) -> bool:
    return value.strip().lower() in ("0", "off", "no", "false", "none")
