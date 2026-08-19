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

from rich.box import ASCII, Box, HEAVY, ROUNDED, SQUARE
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


EMBER = Palette(
    name="ember",
    background="#000000",
    border="#e8590c",
    border_dim="#7a3208",
    title="#e6e6e6",
    label="#ff8c42",
    value="#ededed",
    text="#d4d4d4",
    dim="#6b6b6b",
    accent="#ffb15c",
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
)

MIDNIGHT = Palette(
    name="midnight",
    background="#04070f",
    border="#3b82f6",
    border_dim="#1e3a5f",
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
)

MATRIX = Palette(
    name="matrix",
    background="#000000",
    border="#00b894",
    border_dim="#065f46",
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

PALETTES: dict[str, Palette] = {
    palette.name: palette for palette in (EMBER, MIDNIGHT, MATRIX, MONO)
}


@dataclass(frozen=True)
class Glyphs:
    """Every non-ASCII character the interface draws, in one place."""

    bullet: str = "•"
    arrow: str = "›"
    check: str = "●"
    pending: str = "○"
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
        }, inherit=True)


def load(name: str = "ember", ascii_borders: bool = False, no_color: bool = False,
         syntax: str = "monokai") -> Theme:
    palette = PALETTES.get((name or "ember").lower(), EMBER)
    if no_color:
        palette = MONO
    return Theme(palette=palette, ascii=ascii_borders, no_color=no_color, syntax=syntax)


def theme_names() -> list[str]:
    return sorted(PALETTES)
