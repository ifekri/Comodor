"""Colours, glyphs, and the styles every widget draws with.

The default theme, **Ember**, is the one in the design: a black canvas, amber
panel borders with the title inset at the top-left, amber labels against near-
white values, and teal action buttons. The other themes reuse the same token
names, so switching one changes the whole interface without touching a widget.

Two accessibility paths matter as much as the colours. ``ascii`` swaps every
box-drawing and status glyph for plain ASCII, for terminals and fonts that
render Unicode boxes as garbage. ``no_color`` drops to bold/dim only, for
monochrome terminals, screen readers, and piped output.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from rich.box import ASCII, HEAVY, ROUNDED, SQUARE, Box
from rich.style import Style
from rich.theme import Theme as RichTheme

# The square outline with an inset title is the design's signature shape.
PANEL_BOX: Box = SQUARE
ASCII_BOX: Box = ASCII


@dataclass(frozen=True)
class Palette:
    name: str
    background: str
    border: str
    border_dim: str
    title: str
    label: str            # "Context:", "Mode :", "Provider :"
    value: str            # what follows a label
    text: str
    dim: str
    accent: str           # highlights, cursor, selection
    good: str             # "On", "Connected"
    warn: str
    bad: str              # "Disable", errors
    button_primary_bg: str
    button_primary_fg: str
    button_bg: str
    button_fg: str
    user: str
    assistant: str
    tool: str
    #: Behind what you typed, and behind the answer. Muted on purpose: this
    #: sits under body text somebody reads for minutes, and a background with
    #: any presence of its own competes with the words. "default" means none,
    #: which is what a colourless theme wants.
    user_bg: str = "default"
    assistant_bg: str = "default"

    #: Paint every cell, rather than drawing on whatever the terminal already
    #: has behind it. Off for the dark palettes, which are designed to sit on
    #: the user's own black and look wrong forcing a particular one. On for the
    #: light ones, which are unreadable on a dark terminal and cannot ask the
    #: terminal to change: a light theme that only works if you already had a
    #: light theme is not a theme.
    paint: bool = False
    #: The pygments style for fenced code. It has to follow the palette: a dark
    #: syntax theme on a light background renders half its tokens in near-white
    #: on near-white, which is not "hard to read" but "gone".
    syntax: str = "monokai"


# Retuned for a page with no borders on it. The rules used to be the same
# orange as the accent, which was fine when they were panel edges and loud now
# that they are the only two lines on the screen: a rule is punctuation, not
# content, and it should be the quietest mark there is.
EMBER = Palette(
    name="ember",
    background="#000000",
    border="#5a4636",
    border_dim="#3a2e24",
    title="#f2ede4",
    label="#a8998a",
    value="#ede7dc",
    text="#c9c1b5",
    dim="#8a8078",
    accent="#ff9d5c",
    good="#3dd68c",
    warn="#ffcc66",
    bad="#ff4d4d",
    button_primary_bg="#8a4b28",
    button_primary_fg="#ffffff",
    button_bg="#0f4f52",
    button_fg="#4ecdc4",
    user="#ffb15c",
    assistant="#d4d4d4",
    tool="#4ecdc4",
    user_bg="#1a120b",
    assistant_bg="#0d0d0f"
)

MIDNIGHT = Palette(
    name="midnight",
    background="#04070f",
    border="#2b3a52",
    border_dim="#1b2534",
    title="#e6edf7",
    label="#7aa2f7",
    value="#e6edf7",
    text="#c8d3e6",
    dim="#5c6a85",
    accent="#89b4fa",
    good="#4ade80",
    warn="#fbbf24",
    bad="#f87171",
    button_primary_bg="#1e3a8a",
    button_primary_fg="#ffffff",
    button_bg="#134e4a",
    button_fg="#5eead4",
    user="#89b4fa",
    assistant="#c8d3e6",
    tool="#5eead4",
    user_bg="#0b1120",
    assistant_bg="#0a0d15"
)

MATRIX = Palette(
    name="matrix",
    background="#000000",
    border="#1d5c48",
    border_dim="#0f3a2c",
    title="#d1fae5",
    label="#34d399",
    value="#ecfdf5",
    text="#a7f3d0",
    dim="#4b7a68",
    accent="#6ee7b7",
    good="#22c55e",
    warn="#facc15",
    bad="#ef4444",
    button_primary_bg="#065f46",
    button_primary_fg="#ecfdf5",
    button_bg="#134e4a",
    button_fg="#5eead4",
    user="#6ee7b7",
    assistant="#a7f3d0",
    tool="#34d399",
    user_bg="#04140d",
    assistant_bg="#050a08"
)

MONO = Palette(
    name="mono",
    background="default", border="default", border_dim="default", title="default",
    label="default", value="default", text="default", dim="default", accent="default",
    good="default", warn="default", bad="default",
    button_primary_bg="default", button_primary_fg="default",
    button_bg="default", button_fg="default",
    user="default", assistant="default", tool="default",
)

# Two new ones, for the layout the interface has now rather than the one it
# used to have. Both are near-monochrome with a single warm accent, which is
# what a page of text wants: colour reads as meaning when there is one of it
# and as decoration when there are six.
PAPER = Palette(
    name="paper",
    background="#faf8f4",
    border="#d8d2c6",
    border_dim="#e6e1d7",
    title="#17150f",
    label="#6f6960",
    value="#17150f",
    text="#302b23",
    dim="#6f6960",
    accent="#c4441e",
    good="#2f7d4f",
    warn="#a9741a",
    bad="#b3261e",
    button_primary_bg="#17150f",
    button_primary_fg="#faf8f4",
    button_bg="#ece7dc",
    button_fg="#302b23",
    user="#c4441e",
    assistant="#302b23",
    tool="#6f6960",
    paint=True,
    syntax="friendly",
    user_bg="#f0e9dd",
    assistant_bg="#f5f2ec"
)

#: The website's dark side, which is the same drawing with the values swapped.
INK = Palette(
    name="ink",
    background="#151310",
    border="#3a352d",
    border_dim="#28241e",
    title="#f2ede4",
    label="#8f887d",
    value="#f2ede4",
    text="#cdc6b9",
    dim="#8f887d",
    accent="#e2703a",
    good="#5cc47f",
    warn="#d9a441",
    bad="#e0604f",
    button_primary_bg="#e2703a",
    button_primary_fg="#151310",
    button_bg="#28241e",
    button_fg="#cdc6b9",
    user="#e2703a",
    assistant="#cdc6b9",
    tool="#8f887d",
    paint=True,
    user_bg="#221c16",
    assistant_bg="#1b1917"
)

PALETTES: dict[str, Palette] = {
    palette.name: palette
    for palette in (EMBER, INK, PAPER, MIDNIGHT, MATRIX, MONO)
}


@dataclass(frozen=True)
class Glyphs:
    """Every non-ASCII character the interface draws, in one place."""

    bullet: str = "•"
    arrow: str = "›"
    check: str = "●"
    pending: str = "○"
    #: A box you can tick, which is a different thing from the filled and
    #: hollow dots above: those report whether a step has happened, these
    #: report whether you have asked for something.
    ticked: str = "☑"
    unticked: str = "☐"
    active: str = "◐"
    blocked: str = "✗"
    spinner: tuple[str, ...] = ("⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏")
    gauge_full: str = "█"
    gauge_empty: str = "░"
    cursor: str = "▌"
    divider: str = "─"
    tool: str = "⚙"
    memory: str = "◈"
    warn: str = "▲"
    rise: str = "↑"
    fall: str = "↓"
    dot: str = "·"
    dash: str = "—"


ASCII_GLYPHS = Glyphs(
    bullet="*", arrow=">", check="[x]", pending="[ ]", active="[~]", blocked="[!]",
    ticked="[x]", unticked="[ ]",
    spinner=("|", "/", "-", "\\"), gauge_full="#", gauge_empty=".", cursor="_",
    divider="-", tool="*", memory="+", warn="!",
    rise="^", fall="v", dot="-", dash="-",
)


@dataclass
class Theme:
    """A palette plus the rendering decisions that go with it."""

    palette: Palette = field(default=EMBER)
    ascii: bool = False
    no_color: bool = False
    syntax: str = "monokai"

    @property
    def glyphs(self) -> Glyphs:
        return ASCII_GLYPHS if self.ascii else Glyphs()

    @property
    def box(self) -> Box:
        return ASCII_BOX if self.ascii else PANEL_BOX

    @property
    def heavy_box(self) -> Box:
        return ASCII_BOX if self.ascii else HEAVY

    @property
    def round_box(self) -> Box:
        return ASCII_BOX if self.ascii else ROUNDED

    def colour(self, token: str) -> str:
        """A palette colour by name, or ``default`` in no-colour mode."""
        if self.no_color:
            return "default"
        return getattr(self.palette, token, "default")

    def palette_colour(self, token: str) -> str:
        """One colour by name, or empty when this theme has no colour.

        `style` builds a Style; a caller that needs the colour itself - to put
        it behind a whole block rather than behind some text - needs the string.
        """
        if self.no_color:
            return ""
        return getattr(self.palette, token, "") or ""

    def style(self, token: str, bold: bool = False, dim: bool = False,
              on: str = "") -> Style:
        if self.no_color:
            return Style(bold=bold, dim=dim)
        return Style(color=self.colour(token), bold=bold, dim=dim,
                     bgcolor=self.colour(on) if on else None)

    # -- rich integration -------------------------------------------------- #

    def rich_theme(self) -> RichTheme:
        """Named styles usable as markup, e.g. ``[label]Mode :[/label]``."""
        palette = self.palette
        if self.no_color:
            return RichTheme({
                "label": Style(bold=True), "value": Style(),
                "good": Style(bold=True), "bad": Style(bold=True),
                "warn": Style(bold=True), "dim": Style(dim=True),
                "accent": Style(bold=True), "border": Style(),
                "title": Style(bold=True), "user": Style(bold=True),
                "assistant": Style(), "tool": Style(dim=True),
                "button": Style(reverse=True), "button.primary": Style(reverse=True, bold=True),
                "markdown.code": Style(bold=True),
                "markdown.code_block": Style(),
            }, inherit=True)

        return RichTheme({
            "label": Style(color=palette.label),
            "value": Style(color=palette.value),
            "text": Style(color=palette.text),
            "good": Style(color=palette.good),
            "warn": Style(color=palette.warn),
            "bad": Style(color=palette.bad),
            "dim": Style(color=palette.dim),
            "accent": Style(color=palette.accent),
            "border": Style(color=palette.border),
            "border.dim": Style(color=palette.border_dim),
            "title": Style(color=palette.title, bold=True),
            "user": Style(color=palette.user, bold=True),
            "assistant": Style(color=palette.assistant),
            "tool": Style(color=palette.tool),
            "button": Style(color=palette.button_fg, bgcolor=palette.button_bg, bold=True),
            "button.primary": Style(color=palette.button_primary_fg,
                                    bgcolor=palette.button_primary_bg, bold=True),
            # Inline `code` inside a sentence. Rich's own default for this is
            # bright cyan on black, which is a hole punched in the paragraph;
            # a name in the accent colour reads as a name.
            "markdown.code": Style(color=palette.accent),
            "markdown.code_block": Style(color=palette.text),
        }, inherit=True)


def load(name: str = "ember", ascii_borders: bool = False, no_color: bool = False,
         syntax: str = "") -> Theme:
    palette = PALETTES.get((name or "ember").lower(), EMBER)
    if no_color:
        palette = MONO
    # An empty string means "whatever this palette wants", which is what every
    # caller should pass unless the user has picked a style themselves.
    return Theme(palette=palette, ascii=ascii_borders, no_color=no_color,
                 syntax=syntax or palette.syntax)


def theme_names() -> list[str]:
    return sorted(PALETTES)
