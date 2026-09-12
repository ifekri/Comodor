"""Getting a console that behaves the same everywhere.

Three problems this solves, all of which produce garbled output rather than a
clean failure if left alone:

* **Legacy Windows console.** Rich falls back to a 16-colour, ASCII-only
  renderer when it detects one. Modern Windows Terminal supports VT sequences
  once they are enabled, so we enable them and tell Rich not to use the legacy
  path.
* **Code-page output.** A console encoding that cannot represent ``─`` raises
  ``UnicodeEncodeError`` mid-frame. Standard output is reconfigured to UTF-8,
  and where that is impossible the theme switches itself to ASCII glyphs.
* **Colour depth.** Truecolor is requested when the environment advertises it,
  so the amber and teal of the design land as specified instead of being
  approximated into a 16-colour palette.
"""

from __future__ import annotations

import os
import sys

from rich.console import Console

from .theme import Theme

_ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x0004
_STD_OUTPUT_HANDLE = -11


def enable_windows_vt() -> bool:
    """Turn on VT processing for the output handle. Returns whether it worked."""
    if os.name != "nt":
        return True
    try:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.windll.kernel32
        handle = kernel32.GetStdHandle(_STD_OUTPUT_HANDLE)
        if handle == -1:
            return False
        mode = wintypes.DWORD()
        if not kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            return False
        if mode.value & _ENABLE_VIRTUAL_TERMINAL_PROCESSING:
            return True
        return bool(kernel32.SetConsoleMode(
            handle, mode.value | _ENABLE_VIRTUAL_TERMINAL_PROCESSING))
    except Exception:
        return False


def force_utf8() -> bool:
    """Reconfigure stdout/stderr to UTF-8. Returns whether box glyphs are safe."""
    ok = True
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
        except Exception:
            encoding = (getattr(stream, "encoding", "") or "").lower()
            if "utf" not in encoding:
                ok = False
    return ok


def supports_unicode() -> bool:
    """Whether this terminal can encode what the interface actually draws.

    The probe was three box-drawing characters. Those are in cp437 and cp850 -
    still what a fresh `cmd.exe` gives a lot of people - so the answer came
    back yes, and then fourteen glyphs those code pages do not have went to
    the screen: the bullet, the tick, the warning triangle, and the arrow that
    is the only thing marking which row the cursor is on.

    Built from the glyph table rather than from a literal, so a glyph added
    later widens the probe by existing rather than by somebody remembering.
    """
    # Ask for UTF-8 before reading the encoding, because a fresh Windows
    # console reports cp1252 and takes UTF-8 the moment it is asked. Probing
    # first said no, so the wizard drew its ASCII fallback — while the
    # interface behind it, which builds its console before probing, drew the
    # real thing. Same program, two looks, on the same terminal.
    force_utf8()
    encoding = (getattr(sys.stdout, "encoding", "") or "").lower()
    if "utf" in encoding:
        return True

    from .theme import Glyphs

    wanted = "─┌│" + "".join(
        value for value in vars(Glyphs()).values() if isinstance(value, str))
    try:
        wanted.encode(encoding or "ascii")
        return True
    except (UnicodeEncodeError, LookupError):
        return False


def colour_system() -> str | None:
    """Pick the deepest colour system the terminal actually claims."""
    if os.environ.get("NO_COLOR"):
        return None
    term_program = os.environ.get("TERM_PROGRAM", "")
    colorterm = os.environ.get("COLORTERM", "").lower()
    if colorterm in ("truecolor", "24bit") or os.environ.get("WT_SESSION"):
        return "truecolor"
    if term_program in ("iTerm.app", "vscode", "WarpTerminal", "Hyper"):
        return "truecolor"
    term = os.environ.get("TERM", "")
    if "256" in term:
        return "256"
    return "auto"


def build(theme: Theme | None = None, width: int | None = None,
          height: int | None = None, record: bool = False) -> Console:
    """The console the whole interface draws through."""
    vt = enable_windows_vt()
    force_utf8()

    system = colour_system()
    console = Console(
        theme=theme.rich_theme() if theme else None,
        width=width,
        height=height,
        color_system=None if system is None else ("auto" if system == "auto" else system),
        legacy_windows=False if vt else None,
        force_terminal=None if width is None else True,
        highlight=False,          # the interface styles text deliberately
        soft_wrap=False,
        record=record,
    )
    return console


#: The typeface for anything this program renders itself: the SVG snapshot
#: `preview --svg` writes, and nothing else.
#:
#: Inside a terminal the font is the terminal emulator's setting and no
#: application can change it — a program writes characters, the terminal picks
#: the glyphs. What that means in practice is that right-to-left text renders
#: as boxes on a machine whose terminal font has no Arabic-script coverage, and
#: the only fix is in the terminal's own settings. `comodor doctor` says so,
#: and says where.
#:
#: Tahoma leads the stack because it is the face with the widest Persian and
#: Arabic coverage already installed on a Windows machine, and the one most
#: Persian users will recognise. The monospaced faces follow it for the Latin
#: and box-drawing characters it draws less evenly.
#:
#: One limit worth knowing: an SVG of a terminal is a grid, and every cell is
#: positioned on its own. Arabic script joins its letters, and letters that are
#: each nailed to a cell cannot join — so a snapshot shows the right characters
#: in the right order, unjoined. The terminal itself has no such problem; that
#: is its own text shaping, and it is the reason this only affects the export.
SVG_FONT = ("Tahoma, 'Segoe UI', 'DejaVu Sans Mono', 'Fira Code', "
            "'Cascadia Code', Menlo, monospace")


def prepare_theme(name: str, ascii_borders: bool, no_color: bool,
                  syntax: str = "") -> Theme:
    """Load a theme, downgrading it if the terminal cannot render it."""
    from . import theme as theme_module

    if not ascii_borders and not supports_unicode():
        ascii_borders = True
    if not no_color and colour_system() is None:
        no_color = True
    return theme_module.load(name, ascii_borders=ascii_borders, no_color=no_color,
                             syntax=syntax)
