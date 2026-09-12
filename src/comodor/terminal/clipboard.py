"""Putting text on the clipboard, from a terminal, with nothing installed.

Selecting text with the mouse does not work while an application has mouse
tracking on: the terminal hands the drag to the program instead of drawing a
selection. That is a fair trade for a clickable interface and a bad one if it
means you cannot get a paragraph out of the thing.

So there are two answers, and this file is the better one — copying without
selecting at all. The other is turning mouse tracking off, which `/mouse` does.

Two mechanisms, tried in that order:

**The system clipboard**, through whatever the platform already has: `clip.exe`
on Windows, `pbcopy` on macOS, `wl-copy` or `xclip` or `xsel` on Linux. Most
reliable where it works, and it works on the machine you are sitting at.

**OSC 52**, an escape sequence that asks the *terminal* to set the clipboard.
Slower to explain and better in one important case: over SSH. The terminal
doing the copying is the one in front of you, so text from an agent running on
a server lands on your own clipboard rather than the server's — which has no
clipboard and no one to paste into it.
"""

from __future__ import annotations

import base64
import os
import shutil
import subprocess
import sys
from typing import Sequence

#: Per platform, in the order worth trying. The first one present is used.
TOOLS: dict[str, tuple[Sequence[str], ...]] = {
    "win32": (("clip.exe",),),
    "darwin": (("pbcopy",),),
    "linux": (("wl-copy",), ("xclip", "-selection", "clipboard"),
              ("xsel", "--clipboard", "--input")),
}

#: Above this, OSC 52 is not attempted. Terminals impose their own ceilings on
#: the sequence and a truncated paste is worse than a refusal — you would not
#: know which half you had.
OSC_LIMIT = 100_000


class Unavailable(RuntimeError):
    """Nothing here could reach a clipboard. The message says what would."""


def copy(text: str) -> str:
    """Put text on the clipboard. Returns how, or raises with what to install."""
    if not text:
        return "nothing to copy"

    tool = _native(text)
    if tool:
        return tool

    if len(text) <= OSC_LIMIT and _osc52(text):
        return "the terminal"

    raise Unavailable(_advice())


def available() -> bool:
    """Whether a copy would work, without doing one."""
    return bool(_tool_for_platform()) or _terminal_may_accept_osc52()


def describe() -> str:
    tool = _tool_for_platform()
    if tool:
        return tool[0]
    if _terminal_may_accept_osc52():
        return "the terminal (OSC 52)"
    return "nothing"


# --------------------------------------------------------------------------- #
# the system clipboard
# --------------------------------------------------------------------------- #


def _tool_for_platform() -> Sequence[str] | None:
    for candidate in TOOLS.get(sys.platform, TOOLS["linux"]):
        if shutil.which(candidate[0]):
            return candidate
    # WSL: the Linux tools are usually absent and the Windows one is reachable.
    if sys.platform.startswith("linux") and shutil.which("clip.exe"):
        return ("clip.exe",)
    return None


def _encode(text: str, tool: Sequence[str]) -> bytes:
    """The bytes that tool expects, which is not always UTF-8.

    `clip.exe` reads UTF-8 as the console's OEM code page. It does not fail -
    it copies something, and what lands on the clipboard is mojibake. Measured:
    `سلام` came back as `╪│┘ä╪º┘à`, and an em-dash as two characters. A silent
    corruption is the worst kind of bug to ship in a copy command.

    UTF-16 **without** a byte-order mark. With one it decodes correctly and
    keeps the mark as content, so every paste begins with an invisible U+FEFF -
    which a code editor will happily put at the top of a file. Measured both
    ways; clip.exe detects the encoding without needing the mark.

    Everything else here takes UTF-8.
    """
    if tool[0] == "clip.exe":
        return text.encode("utf-16-le")
    return text.encode("utf-8")


def _native(text: str) -> str:
    tool = _tool_for_platform()
    if tool is None:
        return ""
    try:
        done = subprocess.run(
            list(tool),
            # Bytes rather than text: `text=True` translates newlines on
            # Windows, and a copied code block would come back with its blank
            # lines doubled.
            input=_encode(text, tool),
            capture_output=True, timeout=5.0,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)
            if os.name == "nt" else 0,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return tool[0] if done.returncode == 0 else ""


# --------------------------------------------------------------------------- #
# the terminal's own clipboard
# --------------------------------------------------------------------------- #


def _terminal_may_accept_osc52() -> bool:
    """A guess, and it has to be one: there is no way to ask.

    OSC 52 has no reply, so a terminal that ignores it is indistinguishable
    from one that acted. The list is terminals known to support it; anything
    unrecognised is assumed not to, because reporting a copy that did not
    happen is worse than saying it could not be done.
    """
    if not sys.stdout.isatty():
        return False
    if os.environ.get("WT_SESSION"):                  # Windows Terminal
        return True
    program = os.environ.get("TERM_PROGRAM", "")
    if program in ("iTerm.app", "WezTerm", "ghostty", "vscode", "Hyper",
                   "Tabby", "rio"):
        return True
    term = os.environ.get("TERM", "")
    return any(name in term for name in ("kitty", "alacritty", "foot",
                                         "wezterm", "contour"))


def _osc52(text: str) -> bool:
    payload = base64.b64encode(text.encode("utf-8")).decode("ascii")
    sequence = f"\x1b]52;c;{payload}\x07"
    # Inside tmux the sequence has to be wrapped or tmux eats it rather than
    # passing it to the terminal that can act on it.
    if os.environ.get("TMUX"):
        sequence = f"\x1bPtmux;\x1b{sequence}\x1b\\"
    try:
        sys.stdout.write(sequence)
        sys.stdout.flush()
        return True
    except OSError:
        return False


def _advice() -> str:
    if sys.platform == "linux":
        return ("no clipboard tool found — install wl-clipboard, xclip or "
                "xsel, or use /mouse to turn mouse tracking off and select "
                "the text yourself")
    return ("could not reach the clipboard — use /mouse to turn mouse tracking "
            "off and select the text yourself")
